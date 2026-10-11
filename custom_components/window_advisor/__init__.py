"""The Window Advisor integration.

Tells you when to open or close the windows, per room and for the whole
home, from indoor/outdoor temperatures, a target temperature and the hourly
forecast. Rooms are config subentries discovered from areas.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import (
    CoreState,
    Event,
    HomeAssistant,
    ServiceCall,
    callback,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS, SERVICE_REFRESH
from .coordinator import WindowAdvisorCoordinator
from .entity import hub_device_info
from .repairs import async_sync_forecast_issue, async_sync_issues

type WindowAdvisorConfigEntry = ConfigEntry[WindowAdvisorCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Discovery/missing-entity checks walk the registries; no need to do that on
# every window or temperature change.
REPAIRS_INTERVAL = timedelta(minutes=15)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services."""

    async def _refresh(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            await entry.runtime_data.async_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _refresh)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: WindowAdvisorConfigEntry
) -> bool:
    """Set up Window Advisor from a config entry."""
    coordinator = WindowAdvisorCoordinator(hass, entry)
    entry.runtime_data = coordinator

    # Register the hub device first: room devices link to it by registry id
    # (via_device_id; the identifier-based via_device is deprecated).
    hub = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **hub_device_info(coordinator)
    )
    coordinator.hub_device_id = hub.id

    # Never block startup on the weather service: forward the platforms first
    # and fetch the forecast in the background. Entities stay unavailable
    # until the first evaluation.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_setup_listeners()
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), f"{DOMAIN}_first_refresh"
    )

    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: async_sync_forecast_issue(hass, coordinator)
        )
    )

    @callback
    def _sync_repairs(*_args: object) -> None:
        async_sync_issues(hass, entry, coordinator)

    entry.async_on_unload(
        async_track_time_interval(hass, _sync_repairs, REPAIRS_INTERVAL)
    )
    # Entities of other integrations are still loading during startup; only
    # check for missing ones once everything is up.
    if hass.state is CoreState.running:
        _sync_repairs()
    else:
        started = False

        @callback
        def _on_started(_event: Event) -> None:
            nonlocal started
            started = True
            _sync_repairs()
            if coordinator.forecast_failures:
                entry.async_create_background_task(
                    hass, coordinator.async_request_refresh(), f"{DOMAIN}_started_retry"
                )

        unsub = hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)

        @callback
        def _unsub_started() -> None:
            # Removing an already-fired once-listener logs an error.
            if not started:
                unsub()

        entry.async_on_unload(_unsub_started)

    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: WindowAdvisorConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        async_sync_issues(hass, entry, None)
    return unloaded


async def _async_reload_on_update(
    hass: HomeAssistant, entry: WindowAdvisorConfigEntry
) -> None:
    """Reload when options or rooms change (the entity set changes)."""
    await hass.config_entries.async_reload(entry.entry_id)
