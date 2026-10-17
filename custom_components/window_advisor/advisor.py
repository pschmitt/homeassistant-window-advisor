"""Pure decision logic for the Window Advisor.

This is a 1:1 port of the original ``window_advisor.jinja`` template macros so
behaviour stays identical after the move from templates to an integration.
Nothing in here imports Home Assistant: every function takes the current time
explicitly, which keeps the logic trivially unit-testable.

Vocabulary (kept from the templates, since dashboards and automations parse
these strings):

* ``when_to`` state: an ISO timestamp, ``"All good"`` or ``"unknown"``.
* ``timedelta``: ``"NOW!"``, ``"N/A"`` or a relative time like ``"2h05"``.
* room ``advice``: ``"open"``, ``"close"``, ``"nothing"`` or ``"N/A"``.
* room ``todo``: like ``advice``, but ``"nothing"`` once the window already is
  in the advised state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

ACTION_OPEN = "open"
ACTION_CLOSE = "close"
ACTION_NOTHING = "nothing"

ALL_GOOD = "All good"
UNKNOWN = "unknown"
NOT_AVAILABLE = "N/A"
NOW = "NOW!"

# Binary sensor states of the window contacts.
STATE_ON = "on"
STATE_OFF = "off"

INVALID_STATES = ("unknown", "unavailable")


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """A single hourly forecast entry."""

    datetime: datetime
    temperature: float


@dataclass(frozen=True, slots=True)
class WhenTo:
    """Result of a when-to-open/close computation for one room."""

    state: str
    timedelta: str
    relative_datetime: str
    message: str


@dataclass(frozen=True, slots=True)
class RoomAdvice:
    """Per-room advice, as exposed by the room advisor binary sensor."""

    advice: str
    todo: str
    problem: bool
    icon: str


@dataclass(frozen=True, slots=True)
class RoomStatus:
    """What the aggregate advisor needs to know about a room."""

    name: str
    window_state: str
    # None when the room advisor is unavailable.
    advice: str | None
    when_to_open: str
    when_to_close: str


@dataclass(frozen=True, slots=True)
class AggregateAdvice:
    """Whole-home advice, as exposed by the top-level advisor."""

    problem: bool
    advice: str
    todo: str
    todo_next: str
    rooms: tuple[str, ...]

    @property
    def primary_info(self) -> str:
        """Dashboard headline ("todo" itself stays machine-readable)."""
        if self.todo == ACTION_NOTHING:
            return "Perfect — nothing to do"
        return self.todo

    @property
    def icon(self) -> str:
        """Icon for the aggregate advisor."""
        return "mdi:window-open-variant" if self.problem else "mdi:thumb-up"


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO timestamp like Jinja's ``as_datetime`` (None on failure)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    # Naive timestamps can't be compared with "now"; treat them as invalid.
    return parsed if parsed.tzinfo is not None else None


def when_to(
    action: str,
    *,
    indoor_temp: float,
    outdoor_temp: float,
    target_temp: float,
    target_delta: float,
    forecast: Sequence[ForecastPoint],
    now: datetime,
) -> str:
    """Decide when the windows should be opened or closed.

    Returns ``now`` as ISO timestamp when the action is due right away, the
    first future forecast hour at which it becomes useful, ``"All good"`` when
    nothing needs to happen, or ``"unknown"`` when it can't be determined.
    """
    # Only consider future forecast entries; older points create stale "NOW!"
    # close/open advice.
    future = [point for point in forecast if point.datetime > now]
    first_hotter = next((p.datetime for p in future if p.temperature > indoor_temp), None)
    first_cooler = next((p.datetime for p in future if p.temperature < indoor_temp), None)

    too_cold = indoor_temp < (target_temp - target_delta)
    too_hot = indoor_temp > (target_temp + target_delta)
    outside_cooler = outdoor_temp < indoor_temp
    outside_hotter = outdoor_temp > indoor_temp

    def _fmt(value: datetime | None, fallback: str) -> str:
        return value.astimezone(now.tzinfo).isoformat() if value else fallback

    if action == ACTION_OPEN:
        if (too_hot and outside_cooler) or (too_cold and outside_hotter):
            return now.isoformat()
        if too_cold:
            return _fmt(first_hotter, UNKNOWN)
        if too_hot:
            return _fmt(first_cooler, UNKNOWN)
        return ALL_GOOD

    if action == ACTION_CLOSE:
        if (too_cold and outside_cooler) or (too_hot and outside_hotter):
            return now.isoformat()
        # No cooler/hotter hour in the horizon -> closing will not be needed.
        if too_cold:
            return _fmt(first_cooler, ALL_GOOD)
        if too_hot:
            return _fmt(first_hotter, ALL_GOOD)
        return ALL_GOOD

    return UNKNOWN


def format_timedelta(state: str, now: datetime) -> str:
    """Render a when-to state as ``NOW!``, ``N/A`` or ``[Ndays ]Hh MM``."""
    when = parse_datetime(state)
    if state in (ALL_GOOD, *INVALID_STATES) or when is None:
        return NOT_AVAILABLE
    if when <= now:
        return NOW
    rel = int((when - now).total_seconds())
    days = rel // 86400
    hours = (rel % 86400) // 3600
    minutes = (rel % 3600) // 60
    prefix = f"{days}days " if days > 0 else ""
    return f"{prefix}{hours}h{minutes:02d}"


def relative_datetime(state: str, now: datetime) -> str:
    """Render a timestamp like "Today, 21:54" (port of datetime.jinja)."""
    when = parse_datetime(state)
    if when is None:
        return NOT_AVAILABLE
    when = when.astimezone(now.tzinfo)
    hhmm = when.strftime("%H:%M")
    today = now.date()
    # <=: a when-to of "now" is in the past by the time anyone reads it.
    if when <= now:
        if when.date() == today:
            return f"Earlier today, {hhmm}"
        if when.date() == today - timedelta(days=1):
            return f"Yesterday, {hhmm}"
    elif when.date() == today:
        return f"Today, {hhmm}"
    elif when.date() == today + timedelta(days=1):
        return f"Tomorrow, {hhmm}"
    return when.strftime("%A, %d %B %Y %H:%M")


def message(
    state: str,
    td: str,
    *,
    indoor_temp: float | None,
    outdoor_temp: float | None,
    unit: str | None,
) -> str:
    """Human-readable summary, e.g. ``❄️ 2h05 (Δ 12.6°C)``."""
    if state in (UNKNOWN, "unavailable", ALL_GOOD):
        return NOT_AVAILABLE
    if indoor_temp is None or outdoor_temp is None:
        return td
    delta = indoor_temp - outdoor_temp
    emoji = "❄️" if delta > 0 else "🔥"
    return f"{emoji} {td} (Δ {round(delta, 1)}{unit or ''})"


def compute_when_to(
    action: str,
    *,
    indoor_temp: float,
    outdoor_temp: float,
    target_temp: float,
    target_delta: float,
    forecast: Sequence[ForecastPoint],
    unit: str | None,
    now: datetime,
) -> WhenTo:
    """Compute a when-to sensor's state and attributes in one go."""
    state = when_to(
        action,
        indoor_temp=indoor_temp,
        outdoor_temp=outdoor_temp,
        target_temp=target_temp,
        target_delta=target_delta,
        forecast=forecast,
        now=now,
    )
    td = format_timedelta(state, now)
    return WhenTo(
        state=state,
        timedelta=td,
        relative_datetime=relative_datetime(state, now),
        message=message(
            state,
            td,
            indoor_temp=indoor_temp,
            outdoor_temp=outdoor_temp,
            unit=unit,
        ),
    )


def room_advice(window_state: str, open_to: WhenTo, close_to: WhenTo) -> str:
    """Decide whether a room's windows should be opened or closed right now."""
    open_now = open_to.timedelta == NOW
    close_now = close_to.timedelta == NOW
    open_at = parse_datetime(open_to.state)
    close_at = parse_datetime(close_to.state)
    both_known = open_at is not None and close_at is not None

    if (
        (open_now and not close_now)
        or (open_now and close_now and both_known and open_at > close_at)
        or (open_now and close_now and not both_known and window_state == STATE_OFF)
    ):
        return ACTION_OPEN
    if (
        (close_now and not open_now)
        or (open_now and close_now and both_known and close_at > open_at)
        or (open_now and close_now and not both_known and window_state == STATE_ON)
    ):
        return ACTION_CLOSE
    return ACTION_NOTHING


def room_todo(window_state: str, advice: str) -> str:
    """Return the advice only if the window isn't in that state already."""
    if advice == NOT_AVAILABLE:
        return NOT_AVAILABLE
    if advice == ACTION_OPEN and window_state != STATE_ON:
        return ACTION_OPEN
    if advice == ACTION_CLOSE and window_state != STATE_OFF:
        return ACTION_CLOSE
    return ACTION_NOTHING


def room_icon(window_state: str, todo: str | None) -> str:
    """Icon for a room advisor."""
    if todo in (None, NOT_AVAILABLE, *INVALID_STATES):
        return "mdi:map-marker-question"
    if todo == ACTION_CLOSE:
        return "mdi:window-closed-variant" if window_state == STATE_ON else "mdi:thumb-up"
    if todo == ACTION_OPEN:
        return "mdi:window-open-variant" if window_state == STATE_OFF else "mdi:thumb-up"
    return "mdi:thumb-up"


def evaluate_room(window_state: str, open_to: WhenTo, close_to: WhenTo) -> RoomAdvice:
    """Full per-room evaluation."""
    advice = room_advice(window_state, open_to, close_to)
    todo = room_todo(window_state, advice)
    return RoomAdvice(
        advice=advice,
        todo=todo,
        problem=todo in (ACTION_OPEN, ACTION_CLOSE),
        icon=room_icon(window_state, todo),
    )


def _needs(target: str, window_state: str) -> bool:
    """Whether a window still needs ``target`` done to it."""
    if target == ACTION_OPEN:
        return window_state != STATE_ON
    return window_state != STATE_OFF


def evaluate_aggregate(
    rooms: Sequence[RoomStatus],
    now: datetime,
    *,
    ignore_idle_rooms: bool = False,
) -> AggregateAdvice:
    """Majority election across rooms.

    If 2+ rooms advise one way, that wins; otherwise the higher count wins and
    ties go to "open". Every room whose window isn't in the winning state yet
    is listed.

    ``ignore_idle_rooms`` (alert-fatigue fix, off = template behaviour): only
    rooms that themselves advise the winning action are listed. Without it,
    a single room advising "open" (or even none at all, since a 0:0 tie
    resolves to "open") lists *every* closed window in the home.
    """
    advices = [room.advice for room in rooms]
    open_ct = advices.count(ACTION_OPEN)
    close_ct = advices.count(ACTION_CLOSE)
    if open_ct >= 2:
        target = ACTION_OPEN
    elif close_ct >= 2:
        target = ACTION_CLOSE
    else:
        target = ACTION_OPEN if open_ct >= close_ct else ACTION_CLOSE

    need = tuple(
        room.name
        for room in rooms
        if _needs(target, room.window_state) and (not ignore_idle_rooms or room.advice == target)
    )
    todo = f"{target.capitalize()}: {', '.join(need)}" if need else ACTION_NOTHING

    # When the opposite action should happen next.
    opposite = ACTION_CLOSE if target == ACTION_OPEN else ACTION_OPEN
    times = []
    for room in rooms:
        state = room.when_to_close if opposite == ACTION_CLOSE else room.when_to_open
        if state in (*INVALID_STATES, ALL_GOOD):
            continue
        when = parse_datetime(state)
        if when is not None:
            times.append(when)
    if times:
        when = min(times)
        # Clamped at 0: the template floor-divided negative deltas, so a time
        # that had just passed showed up as "in 23h59".
        delta = max(int((when - now).total_seconds()), 0)
        days = delta // 86400
        hours = (delta % 86400) // 3600
        minutes = (delta % 3600) // 60
        hhmm = when.astimezone(now.tzinfo).strftime("%H:%M")
        if delta < 60:
            todo_next = f"{opposite.capitalize()} now ({hhmm})"
        else:
            rel = (f"{days}d " if days > 0 else "") + f"{hours}h{minutes:02d}"
            todo_next = f"{opposite.capitalize()} in {rel} ({hhmm})"
    else:
        todo_next = f"{opposite.capitalize()}: not anytime soon"

    return AggregateAdvice(
        problem=bool(need),
        advice=target,
        todo=todo,
        todo_next=todo_next,
        rooms=need,
    )
