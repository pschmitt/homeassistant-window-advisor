<p align="center">
  <img src="logo.png" width="128" alt="Window Advisor logo">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/marketplace_repository/?owner=pschmitt&amp;repository=homeassistant-window-advisor&amp;category=integration"><img src="https://my.home-assistant.io/badges/marketplace_repository.svg" alt="Open this integration in Home Assistant Marketplace"></a>
</p>

<h1 align="center">Window Advisor</h1>

<p align="center">Find when opening or closing each room's windows helps reach your target temperature.</p>

The integration combines indoor temperatures, window contacts and an hourly
weather forecast to recommend an action for each room and the whole home.

## Features

- **Room discovery:** Find areas with window contacts and a temperature sensor, and configure them through UI subentries.
- **Forecast advice:** Show when opening or closing a window will help a room reach its target. See [Window advice](docs/advice.md).
- **Whole-home summary:** Combine room recommendations into actionable dashboard text and count open windows.
- **Repairs:** Offer fixes for new rooms, missing entities or an unavailable forecast.

## Install

Use the Marketplace badge above on Home Assistant 2026.11 or later to add this
repository as a custom integration. On older versions, add it as a HACS
custom repository of type **Integration**. Install and restart Home Assistant.
The badge does not imply a public catalog listing. For manual installation,
copy `custom_components/window_advisor/` into Home Assistant's
`custom_components/` directory and restart.

## Quick start

1. Add **Window Advisor** under **Settings → Devices & services → Add integration**.
2. Select a weather entity with an hourly forecast, then configure target temperature and tolerance.
3. Add a discovered room with window contacts and a temperature sensor.
4. Add `binary_sensor.window_advisor` to a dashboard to see the whole-home recommendation.

## Documentation

| Topic | Description |
|-------|-------------|
| [Window advice](docs/advice.md) | Forecast rules, room entities and whole-home behavior |

## License

[GPL-3.0](LICENSE).
