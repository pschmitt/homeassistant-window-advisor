# Window advice

Window Advisor discovers rooms from Home Assistant areas with both a
temperature sensor and window contacts (`device_class: window`). Window groups
are expanded, so balcony doors are included. Each room is a config subentry
that you can add, reconfigure or remove in the UI.

For each room, with `target ± tolerance`:

| Room temperature | Outside temperature | Open | Close |
|------------------|---------------------|------|-------|
| Too hot | Cooler | Now | First hotter forecast hour |
| Too hot | Hotter | First cooler forecast hour | Now |
| Too cold | Hotter | Now | First cooler forecast hour |
| Too cold | Cooler | First hotter forecast hour | Now |
| In range | Any | All good | All good |

A room advisor recommends **open** when opening is due now and closing is not
(or both are due, with opening more recent), and similarly for **close**.
`input_number`, `number` and `sensor` entities may provide the target and
tolerance instead of the integration's built-in number entities.

## Entities

Per-room open and close sensors report `now`, the next helpful forecast hour,
`All good` or `unknown`, with `timedelta`, `relative_datetime` and `message`
attributes. A room binary sensor reports an `advice` and a `todo` action; the
latter is `nothing` if the window is already in the desired state.

The whole-home `binary_sensor.window_advisor` takes a majority vote across
rooms and includes `advice`, `todo`, `todo_next`, `primary_info`,
`secondary_info` and `rooms` attributes. `sensor.open_windows` counts open
windows and provides a readable `message`.

## Avoiding alert fatigue

**Only list rooms that need it** (enabled by default) limits whole-home action
lists to rooms whose own advisor recommends the action. With it disabled, the
vote lists every room whose window is not in the winning state; even an empty
vote can resolve to opening.

The whole-home advisor remains unavailable until its first evaluation after a
restart. A room advisor can still give useful close advice if an open time is
unknown, or vice versa; it only becomes unavailable when temperatures or
window contacts are missing.

Repairs help add newly discovered rooms, replace missing entities and deal
with unavailable forecasts. The last good forecast remains in use while a
fresh forecast is unavailable. Run `window_advisor.refresh` to fetch one
immediately.
