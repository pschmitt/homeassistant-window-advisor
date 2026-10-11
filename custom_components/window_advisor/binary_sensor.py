"""Binary sensors for the Window Advisor: per room and whole home."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_utc_time_change

from .advisor import AggregateAdvice, RoomAdvice
from .const import (
    ATTR_ADVICE,
    ATTR_MESSAGE,
    ATTR_PRIMARY_INFO,
    ATTR_ROOMS,
    ATTR_SECONDARY_INFO,
    ATTR_TODO,
    ATTR_TODO_NEXT,
)
from .coordinator import Room, WindowAdvisorCoordinator
from .entity import WindowAdvisorEntity, WindowAdvisorRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator: WindowAdvisorCoordinator = entry.runtime_data
    async_add_entities([WindowAdvisorBinarySensor(coordinator)])
    for room in coordinator.rooms.values():
        async_add_entities(
            [RoomAdvisorBinarySensor(coordinator, room)],
            config_subentry_id=room.subentry_id,
        )


class RoomAdvisorBinarySensor(WindowAdvisorRoomEntity, BinarySensorEntity):
    """On when the room's windows should be opened or closed right now."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: WindowAdvisorCoordinator, room: Room) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            room,
            key="advisor",
            entity_id=f"binary_sensor.window_advisor_{room.slug}",
            name=f"Window advisor: {room.name}",
        )

    @property
    def _advice(self) -> RoomAdvice | None:
        return self.coordinator.room_advice(self.room)

    @property
    def available(self) -> bool:
        """Unavailable while temperatures or window states are."""
        return super().available and self._advice is not None

    @property
    def is_on(self) -> bool | None:
        """Return true if something needs to be done."""
        advice = self._advice
        return advice.problem if advice else None

    @property
    def icon(self) -> str:
        """Icon reflecting the advice."""
        advice = self._advice
        return advice.icon if advice else "mdi:map-marker-question"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose advice and todo."""
        advice = self._advice
        if advice is None:
            return {}
        return {ATTR_ADVICE: advice.advice, ATTR_TODO: advice.todo}


class WindowAdvisorBinarySensor(WindowAdvisorEntity, BinarySensorEntity):
    """Whole-home advice (majority vote across rooms)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: WindowAdvisorCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            key="advisor",
            entity_id="binary_sensor.window_advisor",
            name="Window advisor",
        )

    async def async_added_to_hass(self) -> None:
        """Re-render every minute: todo_next is relative to now."""
        await super().async_added_to_hass()

        @callback
        def _tick(_now: datetime) -> None:
            self.async_write_ha_state()

        self.async_on_remove(async_track_utc_time_change(self.hass, _tick, second=0))

    @property
    def _advice(self) -> AggregateAdvice | None:
        return self.coordinator.aggregate()

    @property
    def available(self) -> bool:
        """Unavailable until the first evaluation (avoids startup flaps)."""
        return super().available and self._advice is not None

    @property
    def is_on(self) -> bool | None:
        """Return true if any room needs the advised action."""
        advice = self._advice
        return advice.problem if advice else None

    @property
    def icon(self) -> str:
        """Icon reflecting the advice."""
        advice = self._advice
        return advice.icon if advice else "mdi:thumb-up"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the advice in machine- and human-readable form."""
        advice = self._advice
        if advice is None:
            return {}
        return {
            ATTR_ADVICE: advice.advice,
            ATTR_MESSAGE: advice.advice,
            ATTR_TODO: advice.todo,
            ATTR_TODO_NEXT: advice.todo_next,
            ATTR_PRIMARY_INFO: advice.primary_info,
            ATTR_SECONDARY_INFO: advice.todo_next,
            ATTR_ROOMS: list(advice.rooms),
        }
