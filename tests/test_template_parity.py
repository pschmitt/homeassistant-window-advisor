"""Differential test: the Python port vs. the original Jinja macros.

``fixtures/window_advisor.jinja`` is the template the integration replaced.
It is rendered with plain Jinja2 plus minimal stand-ins for the Home Assistant
template helpers it uses, then compared against ``advisor.py`` over many
random inputs.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

from test_advisor import NOW, advisor  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    return advisor.parse_datetime(value) if isinstance(value, str) else None


def _env(states: dict[str, str], attrs: dict[str, dict]) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(FIXTURES), extensions=["jinja2.ext.do"]
    )
    env.filters["as_datetime"] = _as_datetime
    env.filters["as_local"] = lambda value: value.astimezone(NOW.tzinfo)
    env.globals["now"] = lambda: NOW
    env.globals["states"] = lambda entity_id: states.get(entity_id, "unknown")
    env.globals["state_attr"] = lambda entity_id, attr: attrs.get(entity_id, {}).get(
        attr
    )
    return env


def _render(env: jinja2.Environment, call: str) -> str:
    source = "{% from 'window_advisor.jinja' import " + call.split("(")[0] + " %}"
    return env.from_string(source + "{{ " + call + " }}").render().strip()


@pytest.mark.parametrize("seed", range(600))
def test_when_to_and_room_parity(seed: int) -> None:
    rng = random.Random(seed)
    indoor = round(rng.uniform(14, 28), 1)
    outdoor = round(rng.uniform(0, 35), 1)
    target = round(rng.uniform(19, 23) * 2) / 2
    delta = rng.choice([0.5, 1.0, 1.5, 2.0])
    start = rng.randint(-3, 1)
    temps = [round(rng.uniform(0, 35), 1) for _ in range(rng.randint(0, 30))]
    forecast = [
        {
            "datetime": (
                NOW + timedelta(hours=start + i, minutes=-NOW.minute)
            ).isoformat(),
            "temperature": t,
        }
        for i, t in enumerate(temps)
    ]
    points = [
        advisor.ForecastPoint(advisor.parse_datetime(f["datetime"]), f["temperature"])
        for f in forecast
    ]
    states = {
        "sensor.indoor": str(indoor),
        "sensor.outdoor": str(outdoor),
        "input_number.target": str(target),
        "input_number.delta": str(delta),
    }
    env = _env(states, {})
    env.globals["wx"] = {"forecast": forecast}

    results = {}
    for action in ("open", "close"):
        expected = _render(
            env,
            f"when_to('{action}', 'sensor.indoor', 'sensor.outdoor', "
            "'input_number.target', 'input_number.delta', wx)",
        )
        actual = advisor.compute_when_to(
            action,
            indoor_temp=indoor,
            outdoor_temp=outdoor,
            target_temp=target,
            target_delta=delta,
            forecast=points,
            unit="°C",
            now=NOW,
        )
        assert actual.state == expected, (action, states, forecast)
        # The template renders the timedelta attribute slightly *after* the
        # state, so a "now" timestamp is already in the past -> NOW!.
        if expected == NOW.isoformat():
            assert actual.timedelta == "NOW!"
        else:
            assert actual.timedelta == _render(env, f"timedelta('{expected}')")
        results[action] = actual

    window = rng.choice(["on", "off"])
    states.update(
        {
            "binary_sensor.window": window,
            "sensor.open": results["open"].state,
            "sensor.close": results["close"].state,
        }
    )
    attrs = {
        "sensor.open": {"timedelta": results["open"].timedelta},
        "sensor.close": {"timedelta": results["close"].timedelta},
    }
    env = _env(states, attrs)
    expected_advice = _render(
        env, "advice('binary_sensor.window', 'sensor.open', 'sensor.close')"
    )
    room = advisor.evaluate_room(window, results["open"], results["close"])
    assert room.advice == expected_advice
    assert room.todo == _render(env, f"todo('binary_sensor.window', '{room.advice}')")
    assert room.icon == _render(
        env, f"window_advisor_icon('binary_sensor.window', '{room.todo}')"
    )
