"""Config flow for the Window Advisor integration.

The main entry is the shared "hub" (weather, outdoor temperature, targets).
Each room is a config subentry. Rooms are discovered from areas: the initial
setup offers every discovered room, and adding a room later pre-fills the
form from the chosen area. Rooms that appear after setup are offered through
a repair issue (see repairs.py).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import (
    AreaSelector,
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)
from homeassistant.util import slugify

from .const import (
    CONF_AREA,
    CONF_DISCOVERY_REPAIRS,
    CONF_FORECAST_INTERVAL,
    CONF_IGNORE_IDLE_ROOMS,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_ROOMS,
    CONF_TARGET_DELTA_ENTITY,
    CONF_TARGET_TEMPERATURE_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_ENTITIES,
    DEFAULT_DISCOVERY_REPAIRS,
    DEFAULT_FORECAST_INTERVAL,
    DEFAULT_IGNORE_IDLE_ROOMS,
    DOMAIN,
    MIN_FORECAST_INTERVAL,
    SUBENTRY_TYPE_ROOM,
)
from .discovery import (
    DiscoveredRoom,
    async_discover_outdoor_temperature,
    async_discover_room,
    async_discover_rooms,
    async_discover_target,
    async_discover_weather,
)

TITLE = "Window Advisor"

_TARGET_DOMAINS = ["input_number", "number", "sensor"]


def _suggested(value: Any) -> dict[str, Any]:
    return {"suggested_value": value or None}


def _hub_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Schema for the shared inputs."""
    return vol.Schema(
        {
            vol.Required(
                CONF_WEATHER_ENTITY,
                description=_suggested(defaults.get(CONF_WEATHER_ENTITY)),
            ): EntitySelector(EntitySelectorConfig(domain="weather")),
            vol.Required(
                CONF_OUTDOOR_TEMPERATURE_ENTITY,
                description=_suggested(defaults.get(CONF_OUTDOOR_TEMPERATURE_ENTITY)),
            ): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional(
                CONF_TARGET_TEMPERATURE_ENTITY,
                description=_suggested(defaults.get(CONF_TARGET_TEMPERATURE_ENTITY)),
            ): EntitySelector(EntitySelectorConfig(domain=_TARGET_DOMAINS)),
            vol.Optional(
                CONF_TARGET_DELTA_ENTITY,
                description=_suggested(defaults.get(CONF_TARGET_DELTA_ENTITY)),
            ): EntitySelector(EntitySelectorConfig(domain=_TARGET_DOMAINS)),
            vol.Required(
                CONF_FORECAST_INTERVAL,
                default=defaults.get(CONF_FORECAST_INTERVAL, DEFAULT_FORECAST_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_FORECAST_INTERVAL,
                    step=60,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
            vol.Required(
                CONF_IGNORE_IDLE_ROOMS,
                default=defaults.get(CONF_IGNORE_IDLE_ROOMS, DEFAULT_IGNORE_IDLE_ROOMS),
            ): BooleanSelector(),
            vol.Required(
                CONF_DISCOVERY_REPAIRS,
                default=defaults.get(CONF_DISCOVERY_REPAIRS, DEFAULT_DISCOVERY_REPAIRS),
            ): BooleanSelector(),
        }
    )


def _hub_options(user_input: dict[str, Any]) -> dict[str, Any]:
    """Coerce the hub form into clean, typed entry options."""
    return {
        CONF_WEATHER_ENTITY: user_input[CONF_WEATHER_ENTITY],
        CONF_OUTDOOR_TEMPERATURE_ENTITY: user_input[CONF_OUTDOOR_TEMPERATURE_ENTITY],
        CONF_TARGET_TEMPERATURE_ENTITY: user_input.get(CONF_TARGET_TEMPERATURE_ENTITY)
        or "",
        CONF_TARGET_DELTA_ENTITY: user_input.get(CONF_TARGET_DELTA_ENTITY) or "",
        CONF_FORECAST_INTERVAL: int(user_input[CONF_FORECAST_INTERVAL]),
        CONF_IGNORE_IDLE_ROOMS: bool(user_input[CONF_IGNORE_IDLE_ROOMS]),
        CONF_DISCOVERY_REPAIRS: bool(user_input[CONF_DISCOVERY_REPAIRS]),
    }


def _room_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Schema for a room."""
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME, default=defaults.get(CONF_NAME, "")
            ): TextSelector(),
            vol.Optional(
                CONF_AREA, description=_suggested(defaults.get(CONF_AREA))
            ): AreaSelector(),
            vol.Required(
                CONF_WINDOW_ENTITIES,
                default=list(defaults.get(CONF_WINDOW_ENTITIES, [])),
            ): EntitySelector(
                EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Required(
                CONF_TEMPERATURE_ENTITY,
                description=_suggested(defaults.get(CONF_TEMPERATURE_ENTITY)),
            ): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
        }
    )


def room_data(
    area_id: str | None, windows: list[str] | tuple[str, ...], temperature: str
) -> dict[str, Any]:
    """Subentry payload for a room."""
    return {
        CONF_AREA: area_id or "",
        CONF_WINDOW_ENTITIES: list(windows),
        CONF_TEMPERATURE_ENTITY: temperature,
    }


def room_subentry(room: DiscoveredRoom) -> ConfigSubentryData:
    """Subentry for a discovered room."""
    return ConfigSubentryData(
        data=room_data(room.area_id, room.window_entities, room.temperature_entity),
        subentry_type=SUBENTRY_TYPE_ROOM,
        title=room.name,
        unique_id=room.area_id,
    )


@callback
def configured_areas(entry: ConfigEntry) -> set[str]:
    """Areas that already have a room."""
    return {
        subentry.data.get(CONF_AREA)
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_ROOM and subentry.data.get(CONF_AREA)
    }


@callback
def _hub_defaults(hass: HomeAssistant) -> dict[str, Any]:
    target, delta = async_discover_target(hass)
    return {
        CONF_WEATHER_ENTITY: async_discover_weather(hass),
        CONF_OUTDOOR_TEMPERATURE_ENTITY: async_discover_outdoor_temperature(hass),
        CONF_TARGET_TEMPERATURE_ENTITY: target,
        CONF_TARGET_DELTA_ENTITY: delta,
    }


class WindowAdvisorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Window Advisor."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._options: dict[str, Any] = {}
        self._discovered: list[DiscoveredRoom] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WindowAdvisorOptionsFlow:
        """Return the options flow."""
        return WindowAdvisorOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Rooms are managed as subentries."""
        return {SUBENTRY_TYPE_ROOM: RoomSubentryFlowHandler}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Shared inputs (pre-filled from discovery)."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            self._options = _hub_options(user_input)
            self._discovered = async_discover_rooms(self.hass)
            if not self._discovered:
                return self._create([])
            return await self.async_step_rooms()

        return self.async_show_form(
            step_id="user", data_schema=_hub_schema(_hub_defaults(self.hass))
        )

    async def async_step_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which discovered rooms to set up."""
        if user_input is not None:
            selected = set(user_input.get(CONF_ROOMS, []))
            return self._create(
                [room for room in self._discovered if room.area_id in selected]
            )

        options = [
            SelectOptionDict(value=room.area_id, label=room.label)
            for room in self._discovered
        ]
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ROOMS, default=[room.area_id for room in self._discovered]
                ): SelectSelector(SelectSelectorConfig(options=options, multiple=True))
            }
        )
        return self.async_show_form(
            step_id="rooms",
            data_schema=schema,
            description_placeholders={"count": str(len(self._discovered))},
        )

    def _create(self, rooms: list[DiscoveredRoom]) -> ConfigFlowResult:
        return self.async_create_entry(
            title=TITLE,
            data={},
            options=self._options,
            subentries=[room_subentry(room) for room in rooms],
        )


class WindowAdvisorOptionsFlow(OptionsFlow):
    """Handle the shared options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the shared inputs."""
        if user_input is not None:
            return self.async_create_entry(title="", data=_hub_options(user_input))

        return self.async_show_form(
            step_id="init",
            data_schema=_hub_schema(dict(self.config_entry.options)),
        )


class RoomSubentryFlowHandler(ConfigSubentryFlow):
    """Add or reconfigure a room."""

    def __init__(self) -> None:
        """Initialize the flow."""
        self._defaults: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick an area to pre-fill the room from (optional)."""
        entry = self._get_entry()
        if user_input is not None:
            area_id = user_input.get(CONF_AREA)
            if area_id and area_id in configured_areas(entry):
                return self.async_abort(reason="already_configured")
            self._defaults = {CONF_AREA: area_id}
            if area_id:
                area = ar.async_get(self.hass).async_get_area(area_id)
                self._defaults[CONF_NAME] = area.name if area else ""
                if room := async_discover_room(self.hass, area_id):
                    self._defaults[CONF_WINDOW_ENTITIES] = list(room.window_entities)
                    self._defaults[CONF_TEMPERATURE_ENTITY] = room.temperature_entity
            return await self.async_step_room()

        unconfigured = [
            room
            for room in async_discover_rooms(self.hass)
            if room.area_id not in configured_areas(entry)
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_AREA,
                        description=_suggested(
                            unconfigured[0].area_id if unconfigured else None
                        ),
                    ): AreaSelector()
                }
            ),
            description_placeholders={
                "discovered": ", ".join(room.name for room in unconfigured) or "—"
            },
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Room details (name, window contacts, temperature)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input)
            if not errors:
                area_id = user_input.get(CONF_AREA) or None
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=room_data(
                        area_id,
                        user_input[CONF_WINDOW_ENTITIES],
                        user_input[CONF_TEMPERATURE_ENTITY],
                    ),
                    unique_id=area_id,
                )
        return self.async_show_form(
            step_id="room",
            data_schema=self.add_suggested_values_to_schema(
                _room_schema(self._defaults), user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing room."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input, exclude=subentry.subentry_id)
            if not errors:
                area_id = user_input.get(CONF_AREA) or None
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=user_input[CONF_NAME],
                    data=room_data(
                        area_id,
                        user_input[CONF_WINDOW_ENTITIES],
                        user_input[CONF_TEMPERATURE_ENTITY],
                    ),
                    unique_id=area_id,
                )

        defaults = {CONF_NAME: subentry.title, **subentry.data}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_room_schema(defaults),
            errors=errors,
        )

    def _validate(
        self, user_input: dict[str, Any], exclude: str | None = None
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if not user_input.get(CONF_WINDOW_ENTITIES):
            errors[CONF_WINDOW_ENTITIES] = "no_windows"
        slug = slugify(user_input[CONF_NAME])
        for subentry in self._get_entry().subentries.values():
            if subentry.subentry_id != exclude and slugify(subentry.title) == slug:
                errors[CONF_NAME] = "name_in_use"
        return errors
