"""Constants for the Window Advisor integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "window_advisor"
PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SENSOR]

# ---------------------------------------------------------------------------
# Main config entry (the "hub"): inputs shared by every room.
# ---------------------------------------------------------------------------
CONF_WEATHER_ENTITY = "weather_entity"
CONF_OUTDOOR_TEMPERATURE_ENTITY = "outdoor_temperature_entity"
# Optional: when empty, the integration provides its own number entities.
CONF_TARGET_TEMPERATURE_ENTITY = "target_temperature_entity"
CONF_TARGET_DELTA_ENTITY = "target_delta_entity"
CONF_FORECAST_INTERVAL = "forecast_interval"
# Alert-fatigue fix, see advisor.evaluate_aggregate().
CONF_IGNORE_IDLE_ROOMS = "ignore_idle_rooms"
CONF_DISCOVERY_REPAIRS = "discovery_repairs"

DEFAULT_FORECAST_INTERVAL = 900  # 15 minutes, same as the old template trigger
MIN_FORECAST_INTERVAL = 300
DEFAULT_IGNORE_IDLE_ROOMS = True
DEFAULT_DISCOVERY_REPAIRS = True

# Built-in target number entities (used when no external entity is set).
DEFAULT_TARGET_TEMPERATURE = 21.0
DEFAULT_TARGET_DELTA = 1.5

# Consecutive failed forecast fetches before a repair issue is raised.
FORECAST_FAILURES_BEFORE_ISSUE = 4
FORECAST_TIMEOUT = 30  # seconds

# ---------------------------------------------------------------------------
# Rooms (one config subentry per room).
# ---------------------------------------------------------------------------
SUBENTRY_TYPE_ROOM = "room"

CONF_AREA = "area"
CONF_WINDOW_ENTITIES = "window_entities"
CONF_TEMPERATURE_ENTITY = "temperature_entity"
CONF_ROOMS = "rooms"

# ---------------------------------------------------------------------------
# Entity state attributes (names kept from the template sensors: dashboards
# and automations read them).
# ---------------------------------------------------------------------------
ATTR_ADVICE = "advice"
ATTR_TODO = "todo"
ATTR_TODO_NEXT = "todo_next"
ATTR_MESSAGE = "message"
ATTR_PRIMARY_INFO = "primary_info"
ATTR_SECONDARY_INFO = "secondary_info"
ATTR_ROOMS = "rooms"
ATTR_TIMEDELTA = "timedelta"
ATTR_RELATIVE_DATETIME = "relative_datetime"
ATTR_OPEN_WINDOWS = "open_windows"

# ---------------------------------------------------------------------------
# Repairs.
# ---------------------------------------------------------------------------
ISSUE_ROOM_DISCOVERED = "room_discovered_"
ISSUE_MISSING_ENTITIES = "missing_entities_"
ISSUE_FORECAST_UNAVAILABLE = "forecast_unavailable"
HUB_ISSUE_KEY = "hub"

SERVICE_REFRESH = "refresh"

URL_INTEGRATION_PAGE = "/config/integrations/integration/" + DOMAIN
