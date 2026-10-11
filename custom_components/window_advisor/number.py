"""Built-in target temperature / delta for the Window Advisor.

Only created when the hub options don't point at external helpers (e.g. an
``input_number``), so a fresh install works without any extra setup.
"""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_TARGET_DELTA_ENTITY,
    CONF_TARGET_TEMPERATURE_ENTITY,
    DEFAULT_TARGET_DELTA,
    DEFAULT_TARGET_TEMPERATURE,
)
from .coordinator import WindowAdvisorCoordinator
from .entity import WindowAdvisorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the built-in target numbers that aren't overridden."""
    coordinator: WindowAdvisorCoordinator = entry.runtime_data
    entities = []
    if not coordinator.external_target(CONF_TARGET_TEMPERATURE_ENTITY):
        entities.append(
            TargetNumber(
                coordinator,
                CONF_TARGET_TEMPERATURE_ENTITY,
                name="Window advisor target temperature",
                icon="mdi:home-thermometer",
                default=DEFAULT_TARGET_TEMPERATURE,
                minimum=5.0,
                maximum=30.0,
            )
        )
    if not coordinator.external_target(CONF_TARGET_DELTA_ENTITY):
        entities.append(
            TargetNumber(
                coordinator,
                CONF_TARGET_DELTA_ENTITY,
                name="Window advisor target temperature delta",
                icon="mdi:diversify",
                default=DEFAULT_TARGET_DELTA,
                minimum=0.0,
                maximum=5.0,
            )
        )
    async_add_entities(entities)


class TargetNumber(WindowAdvisorEntity, RestoreNumber):
    """Target temperature or tolerance, restored across restarts."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: WindowAdvisorCoordinator,
        key: str,
        *,
        name: str,
        icon: str,
        default: float,
        minimum: float,
        maximum: float,
    ) -> None:
        """Initialize the number."""
        object_id = key.removesuffix("_entity")
        super().__init__(
            coordinator,
            key=object_id,
            entity_id=f"number.window_advisor_{object_id}",
            name=name,
        )
        self._key = key
        if key == CONF_TARGET_DELTA_ENTITY:
            # A tolerance, not an absolute temperature: unit conversion of
            # the temperature device class would apply an offset to it.
            self._attr_device_class = None
        self._attr_icon = icon
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_value = default

    @property
    def available(self) -> bool:
        """Always settable, even before the first forecast."""
        return True

    async def async_added_to_hass(self) -> None:
        """Restore the last value."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None:
            if last.native_value is not None:
                self._attr_native_value = last.native_value
        self.coordinator.builtin_targets[self._key] = float(self._attr_native_value)
        self.coordinator.async_recompute()

    async def async_set_native_value(self, value: float) -> None:
        """Update the target and re-evaluate."""
        self._attr_native_value = value
        self.coordinator.builtin_targets[self._key] = float(value)
        self.async_write_ha_state()
        self.coordinator.async_recompute()
