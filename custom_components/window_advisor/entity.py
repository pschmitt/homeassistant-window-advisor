"""Shared entity helpers for the Window Advisor integration."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Room, WindowAdvisorCoordinator

MANUFACTURER = "pschmitt"


def hub_device_info(coordinator: WindowAdvisorCoordinator) -> DeviceInfo:
    """Device for the whole-home entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        name="Window Advisor",
        manufacturer=MANUFACTURER,
        model="Window advisor",
        entry_type=DeviceEntryType.SERVICE,
    )


class WindowAdvisorEntity(CoordinatorEntity[WindowAdvisorCoordinator]):
    """Base entity.

    Names are fixed (``has_entity_name`` off) and entity ids are requested
    explicitly so they match the template sensors this integration replaced;
    dashboards and automations keep working unchanged.
    """

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: WindowAdvisorCoordinator,
        *,
        key: str,
        entity_id: str,
        name: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = hub_device_info(coordinator)


class WindowAdvisorRoomEntity(WindowAdvisorEntity):
    """Base entity bound to a room device (one config subentry)."""

    def __init__(
        self,
        coordinator: WindowAdvisorCoordinator,
        room: Room,
        *,
        key: str,
        entity_id: str,
        name: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(
            coordinator,
            key=f"{room.subentry_id}_{key}",
            entity_id=entity_id,
            name=name,
        )
        self.room = room
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room.subentry_id)},
            name=f"Window Advisor: {room.name}",
            manufacturer=MANUFACTURER,
            model="Room window advisor",
            entry_type=DeviceEntryType.SERVICE,
        )
        if coordinator.hub_device_id is not None:
            self._attr_device_info["via_device_id"] = coordinator.hub_device_id

    async def async_added_to_hass(self) -> None:
        """Put the room device into the room's area (once)."""
        await super().async_added_to_hass()
        if self.room.area_id is None or self.registry_entry is None:
            return
        dev_reg = dr.async_get(self.hass)
        device_id = self.registry_entry.device_id
        device = dev_reg.async_get(device_id) if device_id else None
        if device is not None and device.area_id is None:
            dev_reg.async_update_device(device.id, area_id=self.room.area_id)
