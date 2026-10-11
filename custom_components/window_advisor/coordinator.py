"""Coordinator for the Window Advisor integration.

Two layers, mirroring the old template setup:

* **when-to** (open/close per room) is computed from the hourly forecast plus
  indoor/outdoor/target temperatures. It is recomputed when the forecast is
  refreshed (every 15 minutes by default) and whenever one of those inputs
  changes. The forecast itself is cached, so input changes don't hit the
  weather service.
* **advice** (per room and whole home) is derived live from the when-to
  results and the current window states, so it reacts to a window opening or
  closing immediately.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .advisor import (
    ACTION_CLOSE,
    ACTION_OPEN,
    STATE_OFF,
    STATE_ON,
    AggregateAdvice,
    ForecastPoint,
    RoomAdvice,
    RoomStatus,
    WhenTo,
    compute_when_to,
    evaluate_aggregate,
    evaluate_room,
)
from .const import (
    CONF_AREA,
    CONF_FORECAST_INTERVAL,
    CONF_IGNORE_IDLE_ROOMS,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_TARGET_DELTA_ENTITY,
    CONF_TARGET_TEMPERATURE_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_ENTITIES,
    DEFAULT_FORECAST_INTERVAL,
    DEFAULT_IGNORE_IDLE_ROOMS,
    DEFAULT_TARGET_DELTA,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
    FORECAST_TIMEOUT,
    SUBENTRY_TYPE_ROOM,
)

_LOGGER = logging.getLogger(__name__)

INVALID = (STATE_UNKNOWN, STATE_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class Room:
    """A configured room (one config subentry)."""

    subentry_id: str
    name: str
    slug: str
    area_id: str | None
    window_entities: tuple[str, ...]
    temperature_entity: str

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> Room:
        """Build a room from its config subentry."""
        data = subentry.data
        return cls(
            subentry_id=subentry.subentry_id,
            name=subentry.title,
            slug=slugify(subentry.title),
            area_id=data.get(CONF_AREA) or None,
            window_entities=tuple(data.get(CONF_WINDOW_ENTITIES, ())),
            temperature_entity=data[CONF_TEMPERATURE_ENTITY],
        )


@dataclass(frozen=True, slots=True)
class RoomWhenTo:
    """When-to results for one room."""

    open: WhenTo
    close: WhenTo


@dataclass(slots=True)
class Snapshot:
    """Coordinator data."""

    forecast: tuple[ForecastPoint, ...] = ()
    forecast_updated: datetime | None = None
    computed_at: datetime | None = None
    # None for rooms whose inputs are unavailable.
    rooms: dict[str, RoomWhenTo | None] = field(default_factory=dict)


class WindowAdvisorCoordinator(DataUpdateCoordinator[Snapshot]):
    """Fetch the forecast and evaluate every room."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(
                seconds=config_entry.options.get(
                    CONF_FORECAST_INTERVAL, DEFAULT_FORECAST_INTERVAL
                )
            ),
        )
        self.rooms: dict[str, Room] = {
            subentry.subentry_id: Room.from_subentry(subentry)
            for subentry in config_entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_ROOM
        }
        self.hub_device_id: str | None = None
        self.forecast_failures = 0
        self.last_forecast_error: str | None = None
        # Built-in target numbers register their current value here.
        self.builtin_targets: dict[str, float] = {
            CONF_TARGET_TEMPERATURE_ENTITY: DEFAULT_TARGET_TEMPERATURE,
            CONF_TARGET_DELTA_ENTITY: DEFAULT_TARGET_DELTA,
        }

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def option(self, key: str, default: object = None) -> object:
        """Return a hub option."""
        return self.config_entry.options.get(key, default)

    @property
    def weather_entity(self) -> str:
        """The weather entity providing the hourly forecast."""
        return str(self.option(CONF_WEATHER_ENTITY))

    @property
    def outdoor_entity(self) -> str:
        """The outdoor temperature sensor."""
        return str(self.option(CONF_OUTDOOR_TEMPERATURE_ENTITY))

    @property
    def ignore_idle_rooms(self) -> bool:
        """Whether idle rooms are left out of the whole-home advice."""
        return bool(self.option(CONF_IGNORE_IDLE_ROOMS, DEFAULT_IGNORE_IDLE_ROOMS))

    def external_target(self, key: str) -> str | None:
        """External target/delta entity, or None to use the built-in number."""
        return self.option(key) or None  # type: ignore[return-value]

    def configured_entities(self) -> dict[str, list[str]]:
        """Every external entity the config references, by owner.

        The key is ``"hub"`` or a room subentry id (used by repairs).
        """
        hub = [self.weather_entity, self.outdoor_entity]
        hub += [
            entity_id
            for key in (CONF_TARGET_TEMPERATURE_ENTITY, CONF_TARGET_DELTA_ENTITY)
            if (entity_id := self.external_target(key))
        ]
        result = {"hub": hub}
        for room in self.rooms.values():
            result[room.subentry_id] = [*room.window_entities, room.temperature_entity]
        return result

    # ------------------------------------------------------------------
    # Input readers
    # ------------------------------------------------------------------
    def _float_state(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in INVALID:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def target(self, key: str) -> float | None:
        """Current target temperature or delta."""
        if entity_id := self.external_target(key):
            return self._float_state(entity_id)
        return self.builtin_targets[key]

    def window_state(self, room: Room) -> str:
        """Combined window state of a room (like a binary_sensor group)."""
        states = [self.hass.states.get(entity_id) for entity_id in room.window_entities]
        values = [state.state for state in states if state is not None]
        if STATE_ON in values:
            return STATE_ON
        if not values or all(value in INVALID for value in values):
            return STATE_UNAVAILABLE
        return STATE_OFF

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    def _compute_rooms(
        self, forecast: tuple[ForecastPoint, ...]
    ) -> dict[str, RoomWhenTo | None]:
        now = dt_util.now()
        outdoor = self._float_state(self.outdoor_entity)
        target = self.target(CONF_TARGET_TEMPERATURE_ENTITY)
        delta = self.target(CONF_TARGET_DELTA_ENTITY)
        result: dict[str, RoomWhenTo | None] = {}
        for room in self.rooms.values():
            indoor = self._float_state(room.temperature_entity)
            if None in (indoor, outdoor, target, delta):
                result[room.subentry_id] = None
                continue
            indoor_state = self.hass.states.get(room.temperature_entity)
            unit = (
                indoor_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                if indoor_state
                else None
            )
            kwargs = {
                "indoor_temp": indoor,
                "outdoor_temp": outdoor,
                "target_temp": target,
                "target_delta": delta,
                "forecast": forecast,
                "unit": unit,
                "now": now,
            }
            result[room.subentry_id] = RoomWhenTo(
                open=compute_when_to(ACTION_OPEN, **kwargs),
                close=compute_when_to(ACTION_CLOSE, **kwargs),
            )
        return result

    def room_advice(self, room: Room) -> RoomAdvice | None:
        """Per-room advice, None when the room advisor is unavailable."""
        when = (self.data.rooms if self.data else {}).get(room.subentry_id)
        window = self.window_state(room)
        if (
            when is None
            or window in INVALID
            or when.open.state in INVALID
            or when.close.state in INVALID
        ):
            return None
        return evaluate_room(window, when.open, when.close)

    def aggregate(self) -> AggregateAdvice | None:
        """Whole-home advice, None until the first evaluation."""
        if self.data is None or self.data.computed_at is None:
            return None
        statuses = []
        for room in self.rooms.values():
            when = self.data.rooms.get(room.subentry_id)
            advice = self.room_advice(room)
            statuses.append(
                RoomStatus(
                    name=room.name,
                    window_state=self.window_state(room),
                    advice=advice.advice if advice else None,
                    when_to_open=when.open.state if when else STATE_UNAVAILABLE,
                    when_to_close=when.close.state if when else STATE_UNAVAILABLE,
                )
            )
        return evaluate_aggregate(
            statuses, dt_util.now(), ignore_idle_rooms=self.ignore_idle_rooms
        )

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    async def _async_fetch_forecast(self) -> tuple[ForecastPoint, ...]:
        weather_entity = self.weather_entity
        async with asyncio.timeout(FORECAST_TIMEOUT):
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"type": "hourly", "entity_id": weather_entity},
                blocking=True,
                return_response=True,
            )
        raw = (response or {}).get(weather_entity, {}).get("forecast") or []
        points = []
        for item in raw:
            when = dt_util.parse_datetime(str(item.get("datetime") or ""))
            temperature = item.get("temperature")
            if when is None or temperature is None:
                continue
            try:
                points.append(ForecastPoint(dt_util.as_utc(when), float(temperature)))
            except (TypeError, ValueError):
                continue
        points.sort(key=lambda point: point.datetime)
        return tuple(points)

    async def _async_update_data(self) -> Snapshot:
        """Refresh the forecast and recompute every room.

        A failed fetch keeps the previous forecast (weather integrations blip
        regularly); repairs raise an issue once it keeps failing.
        """
        previous = self.data or Snapshot()
        forecast = previous.forecast
        forecast_updated = previous.forecast_updated
        try:
            forecast = await self._async_fetch_forecast()
        except Exception as err:  # noqa: BLE001 - any service failure is non-fatal
            self.forecast_failures += 1
            self.last_forecast_error = str(err) or type(err).__name__
            _LOGGER.warning(
                "Could not get hourly forecast from %s (%s failures in a row): %s",
                self.weather_entity,
                self.forecast_failures,
                self.last_forecast_error,
            )
        else:
            self.forecast_failures = 0
            self.last_forecast_error = None
            forecast_updated = dt_util.utcnow()

        return Snapshot(
            forecast=forecast,
            forecast_updated=forecast_updated,
            computed_at=dt_util.utcnow(),
            rooms=self._compute_rooms(forecast),
        )

    @callback
    def async_recompute(self) -> None:
        """Re-evaluate the when-to layer with the cached forecast."""
        if self.data is None:
            # The first refresh is still running; it will read fresh inputs.
            return
        # Not async_set_updated_data(): that reschedules the next refresh, and
        # indoor temperatures change often enough to starve the forecast poll.
        self.data = Snapshot(
            forecast=self.data.forecast,
            forecast_updated=self.data.forecast_updated,
            computed_at=dt_util.utcnow(),
            rooms=self._compute_rooms(self.data.forecast),
        )
        self.async_update_listeners()

    @callback
    def async_setup_listeners(self) -> None:
        """Track every input entity."""
        temperature_inputs = [self.outdoor_entity]
        temperature_inputs += [
            entity_id
            for key in (CONF_TARGET_TEMPERATURE_ENTITY, CONF_TARGET_DELTA_ENTITY)
            if (entity_id := self.external_target(key))
        ]
        temperature_inputs += [room.temperature_entity for room in self.rooms.values()]
        windows = [
            entity_id
            for room in self.rooms.values()
            for entity_id in room.window_entities
        ]

        @callback
        def _on_temperature(event: Event) -> None:
            old, new = event.data["old_state"], event.data["new_state"]
            if old is not None and new is not None and old.state == new.state:
                # Attribute-only change.
                return
            self.async_recompute()

        @callback
        def _on_window(event: Event) -> None:
            old, new = event.data["old_state"], event.data["new_state"]
            if old is not None and new is not None and old.state == new.state:
                return
            self.async_update_listeners()

        self.config_entry.async_on_unload(
            async_track_state_change_event(
                self.hass, temperature_inputs, _on_temperature
            )
        )
        self.config_entry.async_on_unload(
            async_track_state_change_event(self.hass, windows, _on_window)
        )

        @callback
        def _on_weather(event: Event) -> None:
            # At startup the weather integration often loads after us, so the
            # first fetch fails. Retry as soon as it shows up instead of
            # waiting a full forecast interval.
            new = event.data["new_state"]
            if self.forecast_failures and new is not None and new.state not in INVALID:
                self.config_entry.async_create_background_task(
                    self.hass, self.async_request_refresh(), f"{DOMAIN}_weather_retry"
                )

        self.config_entry.async_on_unload(
            async_track_state_change_event(
                self.hass, [self.weather_entity], _on_weather
            )
        )
