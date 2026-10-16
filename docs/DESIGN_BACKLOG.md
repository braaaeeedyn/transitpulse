# Design backlog

Gaps or deviations found while building against the frozen `DESIGN.md` v1.0. Nothing here changes `DESIGN.md`
until v1.1 (after launch). See `DESIGN.md` → Change policy.

The F7 design review (2026-10-14) walked `web/styleguide.html` and every page section against `DESIGN.md`. Drift it
found in code was fixed in code (the answer panel's type sizes, the footer's "Data through" line and write-up links,
right-aligned numeric table headers; see `DEVLOG.md`). Every open row of the old backlog table moved into the
numbered list below, with the gaps the review added (11–19). Each item names the section, what was built, and the
proposed change.

## v1.1 list

1. **§6 map, land source** (2026-10-07). DESIGN.md names Natural Earth for the coastline; it is too coarse at Bay
   scale. Built from US Census cartographic county boundaries (also public domain). *Proposal:* change the source
   line in §6 to "US Census cartographic boundaries".
2. **§2 data colours** (2026-10-07). BART's GTFS calls the Oakland Airport connector "Grey" (`#B0BEC7`); the design
   token is `line-beige`. Kept the design value. *Proposal:* consider renaming the token to `line-grey` and using a
   grey value.
3. **§7 stat tile, text values** (2026-10-08). A station name in the `stat` size (40 px) doesn't fit a 4-up tile
   ("Embarcadero" wraps), which changes tile heights. Text values use `display-md` instead, in a box with the `stat`
   line height. *Proposal:* add a "text value" variant to the stat tile.
4. **§7 chip, selected state** (2026-10-08). No selected state is defined for chips (needed for the forecast station
   chips). Used the `pressed` grey + a 1 px ink inset outline, like a pressed subtle pill. *Proposal:* define a
   selected chip state.
5. **§7 chart card, legend swatches** (2026-10-08). No legend swatch for an interval band. Used a small
   `interval-fill` rectangle next to the solid and dashed line keys. *Proposal:* add band and dashed-line swatches to
   the legend spec.
6. **§7 stat tile, ⓘ placement** (2026-10-08). The ⓘ button has no specified position. It's a 20 px icon with a
   44 px hit area in the tile's top-right corner, so the label row stays one line tall. *Proposal:* specify the ⓘ
   placement.
7. **§7 chart card, event marker** (2026-10-10). No event marker is specified for charts (the eBART opening on the
   Findings event study). Used a 1 px `color-mute` dashed vertical line with a caption-size "Opening" label.
   *Proposal:* add an event/annotation marker to the chart spec.
8. **§7 chart card, zero line** (2026-10-10). No emphasised zero line. On the event study, where 0 = "no effect",
   the 0 gridline uses `color-mute` instead of `gridline`. *Proposal:* specify a zero/reference line style.
9. **§7 card-ink, charts on the ink band** (2026-10-10). No rule for small multiples or white chart cards inside the
   ink band, or for the inline message there. The Findings band puts two white `card`s (ink text) side by side from
   768 px, and stacked below. The light `message` box keeps ink text, and the skeletons use `ink-elevated`.
   *Proposal:* define charts on the ink band: white cards vs. on-ink charts, and message and skeleton colours.
10. **§7 card-ink, leaving the site** (2026-10-10). The spec has a `button-on-ink` "Read the analysis". The band uses
    an underlined on-ink text link to `docs/FINDINGS.md` in the method line, because the write-up is on GitHub, not on
    the site. *Proposal:* decide between a link and a button for leaving the site.
11. **§7 text-input, placeholder colour** (2026-10-14). The front matter says `mute on canvas-softer`, but `mute`
    is AA only on white (4.2:1 on `canvas-softer`, 3.9:1 on `canvas-soft`), and §10 forbids `mute` on grey. The
    input row is `canvas-soft` with a `body` placeholder (5.6:1). *Proposal:* placeholder = `body`.
12. **§7 answer panel on phones** (2026-10-14). The spec opens answers as a full-screen sheet on phones. They render
    inline under the hero at every width, so earlier answers stay in view below. *Proposal:* drop the sheet, or spec
    it with its history.
13. **§7 answer panel, progress steps** (2026-10-14). The spec has spinner → check rows ending in "Drawing chart".
    Built as a numbered list of step names as each event arrives; the chart step was cut with the chart tool (F6).
    *Proposal:* spec the step list without the chart step.
14. **§7 answer panel, earlier answers** (2026-10-14). No spec for the last 5 Q&As kept across a reload. Built as an
    `eyebrow` heading "Earlier answers" and the same answer cards, newest first. *Proposal:* add it to the answer
    panel spec.
15. **§7 answer panel, Copy SQL** (2026-10-14). The spec's "Copy icon button" has no position. It sits under the
    `sql-block` inside the disclosure (an `icon-btn` with the Lucide copy icon, labelled "Copy SQL"), and "Copied" is
    the toast. *Proposal:* specify the placement.
16. **§6 tooltips, station** (2026-10-14). The spec's "Entries yesterday" line reads "Entries on <date>", because
    BART publishes ridership a year at a time. The station tooltip also has a "See its forecast" link, the only
    clickable part of any tooltip (24 px tall, 44 px on touch). *Proposal:* update the §6 wording and allow one link.
17. **§7 dashboard card** (2026-10-14). The Looker Studio embed has no component. Built as a chart card titled
    "Dashboard": a 4:3 `iframe` (`loading="lazy"`) on cards at least 768 px wide, a subtle "Open dashboard" pill with
    the arrow icon on narrower ones. *Proposal:* add an embed card.
18. **§7 segmented control, thumb** (2026-10-14). The spec says the thumb slides (`duration-base`). Built as a
    background and shadow change on the pressed button, with the same duration. *Proposal:* accept the fade, or spec
    the slide.
19. **§7 stat tile, label** (2026-10-14). The prose says "eyebrow label"; the front matter says `body-sm`. Built as
    `body-sm` in `body`, per the front matter. *Proposal:* make the prose match the front matter.
