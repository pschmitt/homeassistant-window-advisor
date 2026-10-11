"""Diagnostics for the Window Advisor integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import WindowAdvisorCoordinator
from .discovery import async_discover_rooms


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: WindowAdvisorCoordinator = entry.runtime_data
    data = coordinator.data

    rooms: dict[str, Any] = {}
    for room in coordinator.rooms.values():
        when = data.rooms.get(room.subentry_id) if data else None
        advice = coordinator.room_advice(room)
        rooms[room.name] = {
            "config": asdict(room),
            "window_state": coordinator.window_state(room),
            "when_to_open": asdict(when.open) if when else None,
            "when_to_close": asdict(when.close) if when else None,
            "advice": asdict(advice) if advice else None,
        }

    aggregate = coordinator.aggregate()
    return {
        "options": dict(entry.options),
        "targets": {
            "target_temperature": coordinator.target("target_temperature_entity"),
            "target_delta": coordinator.target("target_delta_entity"),
        },
        "forecast": {
            "updated": data.forecast_updated.isoformat()
            if data and data.forecast_updated
            else None,
            "failures": coordinator.forecast_failures,
            "last_error": coordinator.last_forecast_error,
            "points": [
                {
                    "datetime": point.datetime.isoformat(),
                    "temperature": point.temperature,
                }
                for point in (data.forecast if data else ())
            ],
        },
        "rooms": rooms,
        "aggregate": asdict(aggregate) if aggregate else None,
        "discovered_rooms": [asdict(room) for room in async_discover_rooms(hass)],
    }
