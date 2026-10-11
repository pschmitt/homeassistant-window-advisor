"""Sensors for the Window Advisor: when to open/close, and open windows."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_FRIENDLY_NAME, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .advisor import ACTION_CLOSE, ACTION_OPEN, WhenTo
from .const import (
    ATTR_MESSAGE,
    ATTR_OPEN_WINDOWS,
    ATTR_RELATIVE_DATETIME,
    ATTR_TIMEDELTA,
)
from .coordinator import Room, WindowAdvisorCoordinator
from .entity import WindowAdvisorEntity, WindowAdvisorRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator: WindowAdvisorCoordinator = entry.runtime_data
    async_add_entities([OpenWindowsSensor(coordinator)])
    for room in coordinator.rooms.values():
        async_add_entities(
            [
                WhenToSensor(coordinator, room, ACTION_OPEN),
                WhenToSensor(coordinator, room, ACTION_CLOSE),
            ],
            config_subentry_id=room.subentry_id,
        )


class WhenToSensor(WindowAdvisorRoomEntity, SensorEntity):
    """When the room's windows should be opened/closed.

    The state is an ISO timestamp, "All good" or "unknown" (not a timestamp
    sensor, to stay compatible with the template sensor it replaces).
    """

    def __init__(
        self, coordinator: WindowAdvisorCoordinator, room: Room, action: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            room,
            key=f"when_to_{action}",
            entity_id=f"sensor.when_to_{action}_{room.slug}_windows",
            name=f"When to {action} {room.name} windows",
        )
        self._action = action
        self._attr_icon = (
            "mdi:window-open-variant"
            if action == ACTION_OPEN
            else "mdi:window-closed-variant"
        )

    @property
    def _when(self) -> WhenTo | None:
        data = self.coordinator.data
        when = data.rooms.get(self.room.subentry_id) if data else None
        if when is None:
            return None
        return when.open if self._action == ACTION_OPEN else when.close

    @property
    def available(self) -> bool:
        """Available once indoor/outdoor/target temperatures are known."""
        return super().available and self._when is not None

    @property
    def native_value(self) -> str | None:
        """Return the when-to state."""
        when = self._when
        return when.state if when else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Relative/human-readable renderings of the state."""
        when = self._when
        if when is None:
            return {}
        return {
            ATTR_RELATIVE_DATETIME: when.relative_datetime,
            ATTR_TIMEDELTA: when.timedelta,
            ATTR_MESSAGE: when.message,
        }


class OpenWindowsSensor(WindowAdvisorEntity, SensorEntity):
    """Number of open windows across all rooms."""

    _attr_icon = "mdi:window-open-variant"
    _attr_native_unit_of_measurement = "windows"

    def __init__(self, coordinator: WindowAdvisorCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            key="open_windows",
            entity_id="sensor.open_windows",
            name="Open windows",
        )

    @property
    def available(self) -> bool:
        """Only depends on window states, not on the forecast."""
        return True

    def _open(self) -> list[str]:
        names = []
        for room in self.coordinator.rooms.values():
            for entity_id in room.window_entities:
                state = self.hass.states.get(entity_id)
                if state is None or state.state != STATE_ON:
                    continue
                name = str(state.attributes.get(ATTR_FRIENDLY_NAME) or entity_id)
                names.append(name.replace("Aqara ", "").replace(" sensor Opening", ""))
        return names

    @property
    def native_value(self) -> int:
        """Return the number of open windows."""
        return len(self._open())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """List the open windows."""
        names = self._open()
        if not names:
            message = "*No* windows are open."
        elif len(names) == 1:
            message = f"{names[0]} is open."
        else:
            comma = "," if len(names) > 2 else ""
            message = f"{', '.join(names[:-1])}{comma} and {names[-1]} are open."
        return {ATTR_OPEN_WINDOWS: ", ".join(names), ATTR_MESSAGE: message}
