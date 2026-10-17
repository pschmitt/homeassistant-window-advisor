"""Repair issues for the Window Advisor.

* **Room discovered** (fixable): an area gained window contacts and a
  temperature sensor but has no room yet. The fix flow adds the room in one
  click; ignore the issue to never be asked about that area again. Can be
  turned off in the options.
* **Missing entities** (fixable): a configured entity no longer exists
  (renamed or removed). The fix flow lets you pick replacements.
* **Forecast unavailable**: the weather entity keeps failing to provide an
  hourly forecast. Advice falls back to the last good forecast meanwhile.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import (
    CONF_AREA,
    CONF_DISCOVERY_REPAIRS,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_TARGET_DELTA_ENTITY,
    CONF_TARGET_TEMPERATURE_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_ENTITIES,
    DEFAULT_DISCOVERY_REPAIRS,
    DOMAIN,
    FORECAST_FAILURES_BEFORE_ISSUE,
    HUB_ISSUE_KEY,
    ISSUE_FORECAST_UNAVAILABLE,
    ISSUE_MISSING_ENTITIES,
    ISSUE_ROOM_DISCOVERED,
    SUBENTRY_TYPE_ROOM,
    URL_INTEGRATION_PAGE,
)
from .coordinator import WindowAdvisorCoordinator
from .discovery import async_discover_room, async_discover_rooms

_TARGET_DOMAINS = ["input_number", "number", "sensor"]


def _entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry | None:
    return hass.config_entries.async_get_entry(entry_id)


@callback
def _sync(hass: HomeAssistant, prefix: str, wanted: dict[str, dict[str, Any]]) -> None:
    """Make the issues starting with ``prefix`` match ``wanted``."""
    issue_registry = ir.async_get(hass)
    for issue in list(issue_registry.issues.values()):
        if (
            issue.domain == DOMAIN
            and issue.issue_id.startswith(prefix)
            and issue.issue_id not in wanted
        ):
            ir.async_delete_issue(hass, DOMAIN, issue.issue_id)
    for issue_id, kwargs in wanted.items():
        ir.async_create_issue(hass, DOMAIN, issue_id, **kwargs)


@callback
def async_sync_forecast_issue(
    hass: HomeAssistant, coordinator: WindowAdvisorCoordinator | None
) -> None:
    """Raise/clear the forecast issue (cheap; runs on every update)."""
    wanted = {}
    if coordinator is not None and coordinator.forecast_failures >= FORECAST_FAILURES_BEFORE_ISSUE:
        wanted[ISSUE_FORECAST_UNAVAILABLE] = {
            "is_fixable": False,
            "severity": ir.IssueSeverity.WARNING,
            "translation_key": "forecast_unavailable",
            "translation_placeholders": {
                "entity_id": coordinator.weather_entity,
                "failures": str(coordinator.forecast_failures),
                "error": coordinator.last_forecast_error or "—",
            },
        }
    _sync(hass, ISSUE_FORECAST_UNAVAILABLE, wanted)


@callback
def async_sync_issues(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: WindowAdvisorCoordinator | None,
) -> None:
    """Reconcile discovery and missing-entity issues.

    Passing ``coordinator=None`` clears every issue (used on unload).
    """
    async_sync_forecast_issue(hass, coordinator)

    missing: dict[str, dict[str, Any]] = {}
    discovered: dict[str, dict[str, Any]] = {}
    if coordinator is not None:
        ent_reg = er.async_get(hass)
        for owner, entity_ids in coordinator.configured_entities().items():
            gone = [
                entity_id
                for entity_id in entity_ids
                if hass.states.get(entity_id) is None and ent_reg.async_get(entity_id) is None
            ]
            if not gone:
                continue
            room = coordinator.rooms.get(owner)
            missing[f"{ISSUE_MISSING_ENTITIES}{owner}"] = {
                "is_fixable": True,
                "severity": ir.IssueSeverity.ERROR,
                "translation_key": "missing_entities",
                "translation_placeholders": {
                    "owner": room.name if room else "Window Advisor",
                    "entities": ", ".join(f"`{entity_id}`" for entity_id in gone),
                },
                "data": {"entry_id": entry.entry_id, "owner": owner},
            }

        if entry.options.get(CONF_DISCOVERY_REPAIRS, DEFAULT_DISCOVERY_REPAIRS):
            configured = {room.area_id for room in coordinator.rooms.values()}
            for room in async_discover_rooms(hass):
                if room.area_id in configured:
                    continue
                discovered[f"{ISSUE_ROOM_DISCOVERED}{room.area_id}"] = {
                    "is_fixable": True,
                    "is_persistent": False,
                    "severity": ir.IssueSeverity.WARNING,
                    "translation_key": "room_discovered",
                    "translation_placeholders": {
                        "name": room.name,
                        "windows": ", ".join(
                            f"`{entity_id}`" for entity_id in room.window_entities
                        ),
                        "temperature": f"`{room.temperature_entity}`",
                        "integration_link": URL_INTEGRATION_PAGE,
                    },
                    "data": {"entry_id": entry.entry_id, "area_id": room.area_id},
                }

    _sync(hass, ISSUE_MISSING_ENTITIES, missing)
    _sync(hass, ISSUE_ROOM_DISCOVERED, discovered)


class RoomDiscoveredRepairFlow(RepairsFlow):
    """Add a discovered room."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Store the issue data."""
        self._data = data

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Entry point."""
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Confirm and create the room."""
        entry = _entry(self.hass, self._data["entry_id"])
        room = async_discover_room(self.hass, self._data["area_id"])
        if entry is None or room is None:
            return self.async_abort(reason="room_gone")

        if user_input is not None:
            self.hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType(
                        {
                            CONF_AREA: room.area_id,
                            CONF_WINDOW_ENTITIES: list(room.window_entities),
                            CONF_TEMPERATURE_ENTITY: room.temperature_entity,
                        }
                    ),
                    subentry_type=SUBENTRY_TYPE_ROOM,
                    title=room.name,
                    unique_id=room.area_id,
                ),
            )
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": room.name,
                "windows": ", ".join(f"`{e}`" for e in room.window_entities),
                "temperature": f"`{room.temperature_entity}`",
            },
        )


class MissingEntitiesRepairFlow(RepairsFlow):
    """Pick replacements for entities that no longer exist."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Store the issue data."""
        self._data = data

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Entry point."""
        entry = _entry(self.hass, self._data["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_gone")
        owner = self._data["owner"]
        if owner == HUB_ISSUE_KEY:
            return await self.async_step_hub()
        if owner not in entry.subentries:
            return self.async_abort(reason="room_gone")
        return await self.async_step_room()

    async def async_step_hub(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Replace hub entities."""
        entry = _entry(self.hass, self._data["entry_id"])
        assert entry is not None
        if user_input is not None:
            options = dict(entry.options)
            for key in (CONF_TARGET_TEMPERATURE_ENTITY, CONF_TARGET_DELTA_ENTITY):
                options[key] = user_input.get(key) or ""
            options[CONF_WEATHER_ENTITY] = user_input[CONF_WEATHER_ENTITY]
            options[CONF_OUTDOOR_TEMPERATURE_ENTITY] = user_input[CONF_OUTDOOR_TEMPERATURE_ENTITY]
            self.hass.config_entries.async_update_entry(entry, options=options)
            return self.async_create_entry(data={})

        schema = vol.Schema(
            {
                vol.Required(CONF_WEATHER_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="weather")
                ),
                vol.Required(CONF_OUTDOOR_TEMPERATURE_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_TARGET_TEMPERATURE_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain=_TARGET_DOMAINS)
                ),
                vol.Optional(CONF_TARGET_DELTA_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain=_TARGET_DOMAINS)
                ),
            }
        )
        return self.async_show_form(
            step_id="hub",
            data_schema=self.add_suggested_values_to_schema(schema, self._existing(entry.options)),
        )

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Replace a room's entities."""
        entry = _entry(self.hass, self._data["entry_id"])
        assert entry is not None
        subentry = entry.subentries[self._data["owner"]]
        if user_input is not None:
            data = dict(subentry.data)
            data[CONF_WINDOW_ENTITIES] = list(user_input[CONF_WINDOW_ENTITIES])
            data[CONF_TEMPERATURE_ENTITY] = user_input[CONF_TEMPERATURE_ENTITY]
            self.hass.config_entries.async_update_subentry(entry, subentry, data=data)
            return self.async_create_entry(data={})

        schema = vol.Schema(
            {
                vol.Required(CONF_WINDOW_ENTITIES): EntitySelector(
                    EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Required(CONF_TEMPERATURE_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
            }
        )
        return self.async_show_form(
            step_id="room",
            data_schema=self.add_suggested_values_to_schema(schema, self._existing(subentry.data)),
            description_placeholders={"name": subentry.title},
        )

    def _existing(self, values: Any) -> dict[str, Any]:
        """Current values minus the entities that no longer exist."""
        ent_reg = er.async_get(self.hass)

        def _exists(entity_id: str) -> bool:
            return bool(entity_id) and (
                self.hass.states.get(entity_id) is not None
                or ent_reg.async_get(entity_id) is not None
            )

        result: dict[str, Any] = {}
        for key, value in values.items():
            if isinstance(value, list):
                result[key] = [item for item in value if _exists(item)]
            elif isinstance(value, str) and _exists(value):
                result[key] = value
        return result


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create the fix flow for an issue."""
    del hass
    if issue_id.startswith(ISSUE_ROOM_DISCOVERED):
        return RoomDiscoveredRepairFlow(data or {})
    return MissingEntitiesRepairFlow(data or {})
