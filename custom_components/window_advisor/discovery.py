"""Discover rooms (areas) and shared inputs for the Window Advisor.

A room is any area that has at least one window contact and a temperature
sensor. Window contacts are binary sensors with the ``window`` device class;
window *groups* (e.g. ``binary_sensor.living_room_windows``) are expanded to
their members, which is how balcony doors that are classed as ``door`` get
picked up. Plain ``door`` sensors (room doors) are deliberately ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

# Aggregated/smoothed helpers make much better room temperatures than a single
# device's sensor; the order is the preference.
_TEMP_PREFERRED_SUFFIXES = ("_filtered", "_median", "_mean", "_average")
_TEMP_DISCOURAGED = ("device_temperature", "cpu", "thermal", "light_temperature")


@dataclass(frozen=True, slots=True)
class DiscoveredRoom:
    """A room candidate."""

    area_id: str
    name: str
    window_entities: tuple[str, ...]
    temperature_entity: str

    @property
    def label(self) -> str:
        """Human-readable summary for selectors."""
        count = len(self.window_entities)
        windows = "1 window" if count == 1 else f"{count} windows"
        return f"{self.name} ({windows}, {self.temperature_entity})"


@callback
def _area_entities(hass: HomeAssistant) -> dict[str, list[str]]:
    """Map area id -> entity ids (entity area, falling back to device area)."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    result: dict[str, list[str]] = {}
    for entry in ent_reg.entities.values():
        if entry.disabled_by is not None:
            continue
        area_id = entry.area_id
        if area_id is None and entry.device_id is not None:
            device = dev_reg.async_get(entry.device_id)
            area_id = device.area_id if device else None
        if area_id is not None:
            result.setdefault(area_id, []).append(entry.entity_id)
    return result


@callback
def _window_entities(hass: HomeAssistant, entity_ids: list[str]) -> list[str]:
    """Window contacts among ``entity_ids``, with groups expanded."""
    found: list[str] = []
    for entity_id in sorted(entity_ids):
        if not entity_id.startswith("binary_sensor."):
            continue
        state = hass.states.get(entity_id)
        if state is None:
            continue
        if state.attributes.get(ATTR_DEVICE_CLASS) != BinarySensorDeviceClass.WINDOW:
            continue
        members = state.attributes.get(ATTR_ENTITY_ID)
        for member in members if isinstance(members, list) else [entity_id]:
            if member not in found:
                found.append(member)
    return found


@callback
def _temperature_entity(hass: HomeAssistant, area_id: str, entity_ids: list[str]) -> str | None:
    """Best temperature sensor for an area."""
    # Helpers like sensor.<area>_temperature_filtered often have no area.
    for suffix in _TEMP_PREFERRED_SUFFIXES:
        candidate = f"sensor.{area_id}_temperature{suffix}"
        if hass.states.get(candidate) is not None:
            return candidate

    candidates = []
    for entity_id in sorted(entity_ids):
        state = hass.states.get(entity_id)
        if (
            state is None
            or not entity_id.startswith("sensor.")
            or state.attributes.get(ATTR_DEVICE_CLASS) != SensorDeviceClass.TEMPERATURE
            or any(word in entity_id for word in _TEMP_DISCOURAGED)
        ):
            continue
        candidates.append(entity_id)
    for suffix in _TEMP_PREFERRED_SUFFIXES:
        for entity_id in candidates:
            if suffix.strip("_") in entity_id:
                return entity_id
    return candidates[0] if candidates else None


@callback
def async_discover_rooms(hass: HomeAssistant) -> list[DiscoveredRoom]:
    """Return every area that looks like a room the advisor can handle."""
    area_reg = ar.async_get(hass)
    by_area = _area_entities(hass)
    rooms: list[DiscoveredRoom] = []
    for area in sorted(area_reg.async_list_areas(), key=lambda a: a.name):
        entity_ids = by_area.get(area.id, [])
        windows = _window_entities(hass, entity_ids)
        if not windows:
            continue
        temperature = _temperature_entity(hass, area.id, entity_ids)
        if temperature is None:
            continue
        rooms.append(
            DiscoveredRoom(
                area_id=area.id,
                name=area.name,
                window_entities=tuple(windows),
                temperature_entity=temperature,
            )
        )
    return rooms


@callback
def async_discover_room(hass: HomeAssistant, area_id: str) -> DiscoveredRoom | None:
    """Discover a single area (None if it has no window contacts)."""
    return next(
        (room for room in async_discover_rooms(hass) if room.area_id == area_id),
        None,
    )


@callback
def async_discover_weather(hass: HomeAssistant) -> str | None:
    """First weather entity that provides an hourly forecast."""
    for state in sorted(hass.states.async_all("weather"), key=lambda s: s.entity_id):
        features = state.attributes.get(ATTR_SUPPORTED_FEATURES) or 0
        if features & WeatherEntityFeature.FORECAST_HOURLY:
            return state.entity_id
    return None


@callback
def async_discover_outdoor_temperature(hass: HomeAssistant) -> str | None:
    """Best guess for an outdoor temperature sensor."""
    candidates = [
        state.entity_id
        for state in hass.states.async_all("sensor")
        if state.attributes.get(ATTR_DEVICE_CLASS) == SensorDeviceClass.TEMPERATURE
        and ("outdoor" in state.entity_id or "outside" in state.entity_id)
    ]
    candidates.sort()
    for suffix in ("median", "filtered", "mean", "average"):
        for entity_id in candidates:
            if suffix in entity_id:
                return entity_id
    return candidates[0] if candidates else None


@callback
def async_discover_target(hass: HomeAssistant) -> tuple[str | None, str | None]:
    """Existing target temperature / delta helpers, if any."""
    target = delta = None
    for state in sorted(
        hass.states.async_all(("input_number", "number")), key=lambda s: s.entity_id
    ):
        object_id = state.entity_id.split(".", 1)[1]
        if object_id.startswith(DOMAIN):
            # Our own built-in number entities.
            continue
        if "target_temperature" not in object_id:
            continue
        if "delta" in object_id:
            delta = delta or state.entity_id
        else:
            target = target or state.entity_id
    return target, delta
