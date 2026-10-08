# Design backlog

Gaps or deviations found while building against the frozen `DESIGN.md` v1.0. Nothing here changes `DESIGN.md`
until v1.1 (after launch). See `DESIGN.md` → Change policy.

| Date | Area | Note | Proposed for v1.1 |
|---|---|---|---|
| 2026-10-07 | §6 map, land source | DESIGN.md names Natural Earth for the coastline; it is too coarse at Bay scale. Built from US Census cartographic county boundaries (also public domain). | Change the source line in §6 to "US Census cartographic boundaries". |
| 2026-10-07 | §2 data colours | BART's GTFS calls the Oakland Airport connector "Grey" (`#B0BEC7`); the design token is `line-beige`. Kept the design value. | Consider renaming the token to `line-grey` and using a grey value. |
| 2026-10-08 | §7 stat tile | A station name in the `stat` size (40 px) doesn't fit a 4-up tile ("Embarcadero" wraps), which changes tile heights. Text values use `display-md` instead, in a box with the `stat` line height. | Add a "text value" variant to the stat tile. |
| 2026-10-08 | §7 chip | No selected state is defined for chips (needed for the forecast station chips). Used the `pressed` grey + a 1 px ink inset outline, like a pressed subtle pill. | Define a selected chip state. |
| 2026-10-08 | §7 chart card | No legend swatch for an interval band. Used a small `interval-fill` rectangle next to the solid and dashed line keys. | Add band and dashed-line swatches to the legend spec. |
| 2026-10-08 | §7 stat tile | The ⓘ button has no specified position. It's a 20 px icon with a 44 px hit area in the tile's top-right corner, so the label row stays one line tall. | Specify the ⓘ placement. |
