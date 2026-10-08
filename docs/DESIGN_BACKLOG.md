# Design backlog

Gaps or deviations found while building against the frozen `DESIGN.md` v1.0. Nothing here changes `DESIGN.md`
until v1.1 (after launch). See `DESIGN.md` → Change policy.

| Date | Area | Note | Proposed for v1.1 |
|---|---|---|---|
| 2026-10-07 | §6 map, land source | DESIGN.md names Natural Earth for the coastline; it is too coarse at Bay scale. Built from US Census cartographic county boundaries (also public domain). | Change the source line in §6 to "US Census cartographic boundaries". |
| 2026-10-07 | §2 data colours | BART's GTFS calls the Oakland Airport connector "Grey" (`#B0BEC7`); the design token is `line-beige`. Kept the design value. | Consider renaming the token to `line-grey` and using a grey value. |
