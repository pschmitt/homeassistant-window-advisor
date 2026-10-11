"""Tests for the pure Window Advisor logic."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Load advisor.py directly: importing the package would pull in Home Assistant.
_PATH = (
    Path(__file__).parent.parent / "custom_components" / "window_advisor" / "advisor.py"
)
_SPEC = importlib.util.spec_from_file_location("advisor", _PATH)
advisor = importlib.util.module_from_spec(_SPEC)
sys.modules["advisor"] = advisor
_SPEC.loader.exec_module(advisor)

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 10, 11, 20, 0, 0, tzinfo=TZ)


def _forecast(*temps: float) -> list:
    return [
        advisor.ForecastPoint(NOW + timedelta(hours=i + 1), t)
        for i, t in enumerate(temps)
    ]


def _when(action: str, indoor: float, outdoor: float, forecast=()) -> str:
    return advisor.when_to(
        action,
        indoor_temp=indoor,
        outdoor_temp=outdoor,
        target_temp=21.0,
        target_delta=1.5,
        forecast=list(forecast),
        now=NOW,
    )


def test_when_to_all_good_in_range() -> None:
    assert _when("open", 21.0, 10.0) == "All good"
    assert _when("close", 21.0, 10.0) == "All good"


def test_when_to_too_cold_and_colder_outside() -> None:
    # Bedroom on 2026-10-11: 17.98 °C inside, 9.8 °C outside.
    assert _when("close", 17.98, 9.8) == NOW.isoformat()
    # No hotter hour ahead: opening can't be scheduled.
    assert _when("open", 17.98, 9.8, _forecast(9, 8, 7)) == "unknown"
    assert (
        _when("open", 17.98, 9.8, _forecast(9, 19, 7))
        == (NOW + timedelta(hours=2)).isoformat()
    )


def test_when_to_too_hot() -> None:
    assert _when("open", 25.0, 18.0) == NOW.isoformat()
    assert (
        _when("close", 25.0, 18.0, _forecast(20, 26))
        == (NOW + timedelta(hours=2)).isoformat()
    )
    # No hotter hour ahead -> closing won't be needed.
    assert _when("close", 25.0, 18.0, _forecast(20, 21)) == "All good"


def test_when_to_ignores_past_forecast() -> None:
    past = [advisor.ForecastPoint(NOW - timedelta(hours=1), 30.0)]
    assert _when("open", 17.0, 9.0, past) == "unknown"


def test_format_timedelta() -> None:
    fmt = advisor.format_timedelta
    assert fmt("All good", NOW) == "N/A"
    assert fmt("unknown", NOW) == "N/A"
    assert fmt(NOW.isoformat(), NOW) == "NOW!"
    assert fmt((NOW + timedelta(hours=2, minutes=5)).isoformat(), NOW) == "2h05"
    assert (
        fmt((NOW + timedelta(days=1, hours=2, minutes=5)).isoformat(), NOW)
        == "1days 2h05"
    )


def test_relative_datetime() -> None:
    rel = advisor.relative_datetime
    assert rel("All good", NOW) == "N/A"
    assert rel((NOW + timedelta(hours=1)).isoformat(), NOW) == "Today, 21:00"
    assert rel((NOW + timedelta(hours=5)).isoformat(), NOW) == "Tomorrow, 01:00"
    assert rel((NOW - timedelta(hours=1)).isoformat(), NOW) == "Earlier today, 19:00"
    assert rel((NOW - timedelta(days=1)).isoformat(), NOW) == "Yesterday, 20:00"


def test_message() -> None:
    msg = advisor.message
    assert msg("All good", "N/A", indoor_temp=21, outdoor_temp=9, unit="°C") == "N/A"
    assert (
        msg(NOW.isoformat(), "NOW!", indoor_temp=21.7, outdoor_temp=9.1, unit="°C")
        == "❄️ NOW! (Δ 12.6°C)"
    )
    assert (
        msg(NOW.isoformat(), "NOW!", indoor_temp=20, outdoor_temp=25, unit="°C")
        == "🔥 NOW! (Δ -5°C)"
    )


def _wt(state: str) -> advisor.WhenTo:
    return advisor.WhenTo(
        state=state,
        timedelta=advisor.format_timedelta(state, NOW),
        relative_datetime="",
        message="",
    )


def test_room_advice() -> None:
    now = NOW.isoformat()
    later = (NOW + timedelta(hours=3)).isoformat()
    # Close now, open later -> close (window open -> todo close).
    room = advisor.evaluate_room("on", _wt(later), _wt(now))
    assert (room.advice, room.todo, room.problem) == ("close", "close", True)
    assert room.icon == "mdi:window-closed-variant"
    # Same advice, window already closed -> nothing to do.
    room = advisor.evaluate_room("off", _wt(later), _wt(now))
    assert (room.advice, room.todo, room.problem) == ("close", "nothing", False)
    assert room.icon == "mdi:thumb-up"
    # Both "All good".
    room = advisor.evaluate_room("off", _wt("All good"), _wt("All good"))
    assert (room.advice, room.todo) == ("nothing", "nothing")


def _status(name, window, advice, when_open="All good", when_close="All good"):
    return advisor.RoomStatus(name, window, advice, when_open, when_close)


def test_aggregate_majority() -> None:
    rooms = [
        _status("Bedroom", "off", "open"),
        _status("Living Room", "off", "open"),
        _status("Office", "on", "nothing"),
    ]
    agg = advisor.evaluate_aggregate(rooms, NOW)
    assert agg.problem
    assert agg.advice == "open"
    assert agg.todo == "Open: Bedroom, Living Room"
    assert agg.todo_next == "Close: not anytime soon"
    assert agg.primary_info == "Open: Bedroom, Living Room"


def test_aggregate_template_quirk_vs_ignore_idle() -> None:
    # Live state on 2026-10-11: bedroom advisor unavailable, nobody advises
    # anything, yet the template said "Open: Bedroom, Living Room".
    close_at = (NOW + timedelta(hours=1, minutes=52)).isoformat()
    rooms = [
        _status("Bedroom", "off", None, "unknown", close_at),
        _status("Living Room", "off", "nothing"),
        _status("Office", "on", "nothing"),
    ]
    agg = advisor.evaluate_aggregate(rooms, NOW)
    assert agg.todo == "Open: Bedroom, Living Room"
    assert agg.todo_next == "Close in 1h52 (21:52)"

    agg = advisor.evaluate_aggregate(rooms, NOW, ignore_idle_rooms=True)
    assert not agg.problem
    assert agg.todo == "nothing"
    assert agg.primary_info == "Perfect — nothing to do"


def test_aggregate_ignore_idle_keeps_actionable_rooms() -> None:
    rooms = [
        _status("Bedroom", "on", "close"),
        _status("Living Room", "on", "close"),
        _status("Office", "on", "nothing"),
    ]
    assert advisor.evaluate_aggregate(rooms, NOW).todo == (
        "Close: Bedroom, Living Room, Office"
    )
    assert (
        advisor.evaluate_aggregate(rooms, NOW, ignore_idle_rooms=True).todo
        == "Close: Bedroom, Living Room"
    )
