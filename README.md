# Window Advisor — Home Assistant integration

<img src="custom_components/window_advisor/brand/icon.png" width="96" align="right" alt="Window Advisor icon">

Tells you **when to open or close the windows**, per room and for the whole
home, so rooms drift towards a target temperature for free: open up when it's
cooler outside and the room is too hot (or the other way round), close again
before the outside turns against you.

It started out as a pile of template sensors and Jinja macros; this
integration is a 1:1 port of that logic (verified by a differential test
against the original templates) plus discovery, repairs and a UI.

## Features

- **Rooms are discovered from areas**: any area with window contacts
  (`device_class: window`, window groups are expanded so balcony doors count)
  and a temperature sensor. Rooms are config subentries, so you can add,
  reconfigure and remove them from the UI.
- Per room:
  - `sensor.when_to_open_<room>_windows` / `sensor.when_to_close_<room>_windows`:
    `now`, the next forecast hour at which it helps, `All good` or `unknown`.
    Attributes: `timedelta` (`NOW!`, `2h05`, …), `relative_datetime`,
    `message`.
  - `binary_sensor.window_advisor_<room>`: on when something needs doing.
    Attributes: `advice` (`open`/`close`/`nothing`) and `todo` (the same, but
    `nothing` once the window already is in that state).
- Whole home:
  - `binary_sensor.window_advisor`: majority vote across rooms. Attributes:
    `advice`, `todo` (e.g. `Open: Bedroom, Living Room`), `todo_next`
    (`Close in 2h05 (21:52)`), `primary_info`/`secondary_info` for dashboards,
    `rooms`.
  - `sensor.open_windows`: number of open windows, with `open_windows` and a
    human-readable `message`.
- **Target temperature** and **tolerance** come from your own helpers
  (`input_number`, `number` or `sensor`) or from built-in number entities.
- **Repairs**:
  - *New room discovered*: one click adds it (ignore the issue to never be
    asked about that area again).
  - *Missing entities*: a configured sensor was renamed or removed; the fix
    flow lets you pick a replacement.
  - *Forecast unavailable*: the weather entity keeps failing. The last good
    forecast is used meanwhile.
- Diagnostics, and a `window_advisor.refresh` action to fetch the forecast
  right away.

## Avoiding alert fatigue

**Only list rooms that need it** (on by default) changes one thing compared
to the original templates. The whole-home vote used to list *every* room
whose window wasn't in the winning state. Since a 0:0 tie resolves to "open",
a single unavailable room was enough to get "Open: Living Room" while the
living room was perfectly fine. With the option on, only rooms whose own
advisor recommends the action are listed. Turn it off for the exact old
behaviour.

The whole-home advice is also computed in one go now. The template read its
own previous attributes, so state and `todo` briefly disagreed and the
sensor flapped off/on within a minute. It also stays *unavailable* until the
first evaluation after a restart instead of reporting on with stale data.

## Installation

HACS (custom repository) or copy `custom_components/window_advisor` into your
configuration directory, restart, then **Settings → Devices & services → Add
integration → Window Advisor**.

## How the advice works

For each room, with `target ± tolerance`:

| Room is… | and outside is… | when to open | when to close |
| --- | --- | --- | --- |
| too hot | cooler | now | first hotter forecast hour |
| too hot | hotter | first cooler forecast hour | now |
| too cold | hotter | now | first cooler forecast hour |
| too cold | cooler | first hotter forecast hour | now |
| in range | — | All good | All good |

A room advisor says **open** when opening is due now and closing isn't (or
both are and opening is the more recent call), and likewise for **close**.
