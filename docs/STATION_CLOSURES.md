# BART stations at risk of closing: what the ridership says

> **Status (2026-10-17):** the stations below are the ones named in BART staff's February 2026 presentation, as
> reported by the press. The list isn't final: the BART board still has to vote on which stations or segments would
> close. **TransitPulse doesn't take a position on the measure** on the November 3, 2026 ballot; the verdicts here
> weigh ridership, recovery and distance. This page will need revisiting after the election.

The site's **Station closures** band (`web/js/closures.js`, `GET /api/closures`) shows the same numbers as this
write-up. Everything in the results table comes from the local warehouse and is checked against it by
`tests/local/test_closures_local.py`.

## Background

- **The ballot measure.** "Connect Bay Area" (SB 63, the Regional Transit Measure) is on the **November 3, 2026**
  ballot in Alameda, Contra Costa, San Mateo and Santa Clara counties (a 0.5% sales tax) and San Francisco (1%), for
  14 years, about $980M a year, mostly for BART, Muni, Caltrain and AC Transit. It qualified with 305,895 signatures
  (certified by MTC in July 2026).
- **The BART board's vote.** On **February 26, 2026** the board adopted an "Alternative Service Plan" **8–1**
  (Director Liz Ames against). It applies only if the measure fails and no other money is found. BART's structural
  deficit is $350–400M a year ($376M in FY27).
  - January 2027: 3 lines, 2 trains an hour per line, closing at 9 PM, fares and parking +30%, about 600 layoffs, no
    station closures yet.
  - From **July 2027** (FY28): up to **15 station closures** (30% of 50 stations) and/or up to 25% of track miles
    (32 miles of segment closures), a cumulative 70% cut in train hours, fares up to +50%, about 1,200 layoffs in
    total. The board moved closures from January to July 2027 using $10M of reserves.
  - A third phase stops passenger service if BART can't operate safely and legally.
  - The adopted framework doesn't name stations; the board still has to vote on which stations or segments close.

## The 15 stations, as reported

Staff started from "the 10 lowest-ridership stations" and added five more that shrink the network by closing whole
line ends. KRON4 reported that closing the first 10 leaves 40 stations and affects about 12% of BART's ridership.

| Group | Stations | Segment |
|---|---|---|
| 1: the 10 lowest ridership | Castro Valley, West Dublin/Pleasanton | Bay Fair to Dublin/Pleasanton |
| 1 | North Concord/Martinez, Pittsburg Center | Concord to Antioch |
| 1 | South San Francisco, San Bruno | Daly City to Millbrae |
| 1 | Oakland International Airport, Orinda, South Hayward, Warm Springs/South Fremont | none (single stations on lines that stay open) |
| 2: five more, line-end segments | Dublin/Pleasanton | Bay Fair to Dublin/Pleasanton |
| 2 | Pittsburg/Bay Point, Antioch | Concord to Antioch |
| 2 | Colma, Millbrae | Daly City to Millbrae |

With both groups, every listed station on three line ends closes: the Blue line east of Bay Fair, the Yellow line
east of Concord, and the Peninsula south of Daly City. San Francisco International Airport (SFO), on the Peninsula
segment between San Bruno and Millbrae, isn't on the list as reported; the sources don't say how it would be served,
and this analysis counts it as open (see [The SFO assumption](#the-sfo-assumption)). The list lives in one file,
`dbt/transitpulse/seeds/bart_closure_candidates.csv`; if the board votes on a final list, that file is what changes.

## Data and definitions

- **Data:** BART's hourly origin-destination ridership, 2018-01-01 → 2025-12-31 (50 stations). BART hasn't
  published 2026 yet, so the **period year is 2025**, the latest calendar year whose data reaches December 31.
- **Service weekdays only:** Monday to Friday, not holidays (250 days in 2025).
- **Weekday trips** at a station = its average service-weekday **entries + exits**, i.e. the trips that start or end
  there.
- **Rank:** 1 = the fewest weekday trips among all 50 stations with 2025 data.
- **Recovery:** a station's weekday trips in 2025 as a percentage of its weekday trips in 2019. BART's figure is
  systemwide weekday entries in 2025 as a percentage of 2019: **43%** (43.1%). Stations with fewer than 200 service
  weekdays of 2019 data (Milpitas and Berryessa, opened in 2020) have no recovery figure.
- **Nearest station still open:** the closest station, in a straight line (haversine, Earth radius 3,958.8 miles),
  that is **not** one of the 15, assuming all 15 close.
- **Top destinations:** the three stations a station's riders most often travel to on 2025 service weekdays, with
  their share of all trips that start there.

## The rules

Each rule a station meets is a point **for keeping it** (the "case to keep"). The first three were set in the build plan
before the section was built. The fourth, **Growing**, was added afterwards at the owner's request, to give more weight
to the case for keeping; with only the first three, the counts were strong 2, mixed 4, weak 9. The first three were
written from stated principles, but rough numbers had been looked at while checking the plan was feasible, so none of
this is a blind pre-registration.

| Rule | Met when | Why |
|---|---|---|
| **Riders** | Its weekday trips rank above the 10 least-used stations (rank 11 or higher of 50) | BART staff's own cut, "the 10 lowest" |
| **Recovery** | Its recovery, as a whole percentage (rounded half up), is at or above BART's systemwide whole percentage; no 2019 baseline = not met | Compared with BART's own average, not an absolute bar |
| **Distance** | The nearest station still open (if all 15 close) is at least 3.0 miles away in a straight line, rounded to 0.1 mile | Beyond a short walk or bike ride, riders need a car or a bus |
| **Growing** | Its weekday trips in 2025 are up on 2024, rounded half up to 0.1% (so +0.0% doesn't count) | A station whose riders are coming back would be closed just as it recovers |

**Verdict:** 3 or 4 rules met = **strong**, 2 = **mixed**, 0–1 = **weak**. The rules compare the rounded numbers the page
shows, so anyone can check a verdict by eye. The thresholds live in one place, `api/routes/data.py`
(`CLOSURE_RULES`), and the page shows their text from the API.

## Results (local warehouse, 2025 service weekdays)

Ordered by group, then by weekday trips (fewest first).

| Code | Station | Group | Weekday trips | Rank (1 = fewest) | % of 2019 (BART: 43%) | Change vs 2024 | Nearest station still open | Rules met | Verdict |
|---|---|---|---:|---:|---:|---:|---|---|---|
| OAKL | Oakland International Airport | 1 | 1,085 | 1 of 50 | 41% | −17.9% | San Leandro, 2.9 mi | none | weak |
| PCTR | Pittsburg Center | 1 | 1,121 | 2 of 50 | 46% | +14.9% | Concord, 8.2 mi | Recovery, Distance, Growing | strong |
| NCON | North Concord / Martinez | 1 | 1,382 | 3 of 50 | 34% | +7.2% | Concord, 2.1 mi | Growing | weak |
| WARM | Warm Springs / South Fremont | 1 | 2,443 | 4 of 50 | 28% | +2.8% | Fremont, 4.3 mi | Distance, Growing | mixed |
| CAST | Castro Valley | 1 | 2,549 | 6 of 50 | 45% | +5.1% | Hayward, 1.6 mi | Recovery, Growing | mixed |
| WDUB | West Dublin / Pleasanton | 1 | 2,573 | 7 of 50 | 37% | +2.4% | Hayward, 8.9 mi | Distance, Growing | mixed |
| ORIN | Orinda | 1 | 2,761 | 8 of 50 | 47% | +8.8% | Lafayette, 3.4 mi | Recovery, Distance, Growing | strong |
| SSAN | South San Francisco | 1 | 2,839 | 9 of 50 | 41% | +3.2% | Daly City, 3.2 mi | Distance, Growing | mixed |
| SHAY | South Hayward | 1 | 2,959 | 10 of 50 | 49% | +5.2% | Hayward, 2.9 mi | Recovery, Growing | mixed |
| SBRN | San Bruno | 1 | 3,114 | 12 of 50 | 43% | +5.6% | San Francisco International Airport, 2.0 mi | Riders, Recovery, Growing | strong |
| COLM | Colma | 2 | 3,340 | 13 of 50 | 38% | +6.3% | Daly City, 1.5 mi | Riders, Growing | mixed |
| ANTC | Antioch | 2 | 3,704 | 16 of 50 | 61% | +3.5% | Concord, 13.6 mi | Riders, Recovery, Distance, Growing | strong |
| MLBR | Millbrae | 2 | 3,830 | 18 of 50 | 31% | +5.4% | San Francisco International Airport, 1.1 mi | Riders, Growing | mixed |
| PITT | Pittsburg / Bay Point | 2 | 4,572 | 23 of 50 | 58% | +9.4% | Concord, 5.6 mi | Riders, Recovery, Distance, Growing | strong |
| DUBL | Dublin / Pleasanton | 2 | 6,240 | 32 of 50 | 38% | +4.8% | Union City, 10.0 mi | Riders, Distance, Growing | strong |

**Verdict counts:** strong 6 (Pittsburg Center, Orinda, San Bruno, Antioch, Pittsburg/Bay Point, Dublin/Pleasanton),
mixed 7 (Warm Springs/South Fremont, Castro Valley, West Dublin/Pleasanton, South San Francisco, South Hayward, Colma,
Millbrae), weak 2 (Oakland International Airport, North Concord/Martinez).

What stands out, without reading more into it than the data allows:
- Every first-10 station except San Bruno fails the **Riders** rule, as it should if staff's list was built from
  ridership: they are BART's least-used stations.
- The two stations that meet all four rules are the last two at the Yellow line's eastern end (Antioch,
  Pittsburg/Bay Point): busier than the bottom 10, recovering better than BART overall (61% and 58% of 2019 against
  43%), growing, and far from the next open station (Concord, 13.6 and 5.6 miles) once the whole Concord-to-Antioch
  segment closes.
- Every listed station carried more weekday trips in 2025 than in 2024 except Oakland International Airport
  (−17.9%), so 14 of 15 meet **Growing**.
- The two weak cases are the airport, the least-used station and the only one shrinking, and North Concord/Martinez,
  2.1 miles from Concord. Several mixed cases are also close to another station: Castro Valley (Hayward, 1.6 mi),
  Colma (Daly City, 1.5 mi), Millbrae (SFO, 1.1 mi).
- The most common top destination is Embarcadero (10 of 15); Pittsburg Center's is Concord, and Millbrae's is SFO.

## What closing would cost

The band's "What closing would cost" card puts these next to the verdicts:
- **Riders:** 24.1% of 2025 service-weekday trips start or end at one of the 15 (42,524 a day), and 14 of the 15 grew
  on 2024. Eight are 3 miles or more from the next open station; Antioch riders would be 13.6 miles from Concord.
- **Traffic:** when a 35-day strike stopped Los Angeles bus and rail service in October 2003, average peak-hour
  highway delay rose 47%, most on freeways running alongside busy transit lines (Anderson, *American Economic Review*
  104(9), 2014).
- **The Bay Bridge:** during the July 2013 BART strike, Bay Bridge travel times and volumes nearly doubled their
  median on the worst day, and roads parallel to BART were as bad as the worst day of a typical week; freeways across
  the region showed negligible change (Moylan, Foti and Skabardonis, *Transportation Planning and Technology* 39(2),
  2016; abstract only, the full text is paywalled).
- **Lost work time:** the Bay Area Council Economic Institute, a business group, estimated the 2013 strike at about
  $73 million a day in lost productivity alone (CBS News Bay Area, July 2013).

These were shutdowns of a whole system. Closing 15 stations would be smaller, none of the studies measured station
closures, and none of this says what closing would save.

## Claim checks

- **"The 10 lowest-ridership stations."** 9 of the first 10 are among our 10 least-used stations in 2025. The
  exception is San Bruno, 12th from the bottom. Our 10 least used also include **Milpitas** (5th), which isn't on the
  list; Berryessa/North San Jose is 11th. The reported list may use a different period or measure; this write-up
  doesn't guess why it differs.
- **"About 12% of BART's ridership."** 12.6% of 2025 service-weekday trips start or end at one of the first 10
  stations (22,135 of 176,284 a day; a trip between two listed stations counts once). That matches the reported
  ~12%.
- **All 15.** 24.1% of 2025 service-weekday trips start or end at one of all 15 stations (42,524 a day).
- **South San Francisco, 1,538 weekday riders (BART's January 2026 report).** Our 2025 average weekday **exits** at
  South San Francisco are 1,409 (entries 1,430), a ratio of 0.92 to BART's figure; January 2025 alone averaged 1,397
  exits. The periods differ (2025 vs January 2026), so a gap of this size is plausible, and it is inside the
  0.75–1.25 range the plan set for revisiting the station measure.

## Close calls

Stations within one point of BART's recovery percentage, within 0.2 mile of the 3.0-mile line, or ranked 10th or
11th. They are reported, not moved:
- **San Bruno:** recovery 43.05% rounds to 43%, equal to BART's 43% (43.1%), so Recovery is met; on unrounded numbers
  it is just below BART's. Without that point San Bruno would be mixed instead of strong.
- **South Hayward:** ranked exactly 10th, so it is among the 10 least used (Riders not met); its nearest open
  station, Hayward, is 2.94 miles away (2.9, Distance not met). Either rule going the other way would make it strong.
- **Oakland International Airport:** the nearest open station in a straight line is San Leandro at 2.88 miles (2.9,
  not met). The airport's train runs to Coliseum, 2.91 miles away, also under 3.0.
- **South San Francisco:** Daly City is 3.19 miles away (3.2, Distance met); without it, the verdict would be weak
  instead of mixed.
- **Growing** has no close calls: the smallest rise is West Dublin/Pleasanton's +2.4%, and the airport's −17.9% is
  the only fall.

## The SFO assumption

SFO isn't on the list as reported, and the sources don't say how it would be served if the stations around it
closed. Like every station not on the list, this analysis counts it as open. That makes it the nearest open station
for two listed stations, and both fail **Distance** because of it:
- **San Bruno:** SFO is 2.0 mi away, so Distance isn't met and the verdict is strong (Riders, Recovery, Growing). If
  SFO lost service too, the nearest open station would be Daly City, 5.5 mi away: Distance met, all four rules, verdict
  still **strong**.
- **Millbrae:** SFO is 1.1 mi away, so Distance isn't met and the verdict is mixed (Riders, Growing). If SFO lost
  service too, the nearest open station would be Daly City, 8.6 mi away: Distance met, verdict **strong**.

The miles are straight lines, rounded half up to 0.1 mile, as the rule does. No other listed station has SFO as its
nearest open station. With both changes the counts would be strong 7, mixed 6, weak 2 (instead of strong 6, mixed 7,
weak 2). This is reported, not applied: the verdicts in the results table stay as the rules define them (any station
not on the list counts as open), because changing a rule after seeing the results would be tuning. The figures here
are checked against the warehouse by `tests/local/test_closures_local.py`.

## What the data can't see

- What each station costs to run, and what closing it would save. BART's plan is about money; these rules aren't.
- Who rides: income, disability and access to a car. A quiet station can be the only option for its riders.
- Parking, bus and shuttle links at each station, and how far riders really travel to the next one (distances here
  are straight lines, not roads or rail).
- Transfers to other systems: Caltrain at Millbrae, air travellers at Oakland International Airport and SFO.
- Whether riders would switch to another station or stop riding.
- Anything after 2025: BART hasn't published 2026 ridership yet.
- How the plan would actually be applied: the "all 15 close" assumption is the worst case, and the board may close
  segments rather than stations, or fewer stations.
- How SFO would be served. This analysis counts it as open, and that decides the verdicts for San Bruno and Millbrae:
  see [The SFO assumption](#the-sfo-assumption).

## Reproduce

```bash
# the seed and the three marts (DuckDB; the same models run on BigQuery)
DBT_TARGET=local uv run --group dbt dbt build --select bart_closure_candidates+ \
  --project-dir dbt/transitpulse --profiles-dir dbt/transitpulse

# the endpoint the band reads
TP_WAREHOUSE=duckdb uv run python tasks.py api   # then GET http://localhost:8000/api/closures

# checks against the warehouse, including every column of the results table and the SFO assumption
uv run --group dbt --group ml --group agent pytest -m localdata tests/local/test_closures_local.py
```

Models: `mart_station_closures` (one row per station), `mart_closure_destinations` (top 3 destinations of each
listed station) and `mart_closure_scenarios` (the first 10 / all 15 trip shares), all in
`dbt/transitpulse/models/marts/`.

## Sources

- CBS News Bay Area, "BART could close 15 stations, lay off 1,200 without sales tax measure" (updated Feb 9, 2026):
  https://www.cbsnews.com/sanfrancisco/news/bart-could-close-15-stations-lay-off-1200-without-sales-tax-measure/
- CBS News Bay Area, "BART board approves plan to close stations if voters reject sales tax measure" (Feb 2026):
  https://www.cbsnews.com/sanfrancisco/news/bart-board-approves-station-closures-if-2026-sales-tax-measure-rejected/
- BART, "BART Board to discuss and adopt an Alternative Service Plan" (updated Feb 26, 2026):
  https://www.bart.gov/node/44936
- BART, Proposed Alternative Service Framework (Feb 12, 2026):
  https://www.bart.gov/sites/default/files/2026-02/Proposed%20Alternative%20Service%20Framework%20from%20Feb%2012%202026.pdf
- The San Francisco Standard, "BART won't close stations in January after vote" (Feb 26, 2026):
  https://sfstandard.com/2026/02/26/bart-doomsday-scenario-less-doomy/
- KRON4, the BART stations that could close under the worst-case scenario (2026):
  https://www.kron4.com/news/bay-area/these-are-the-bart-stations-that-could-close-under-transit-systems-worst-case-scenario/
- Medill Reports, several stations on the chopping block as BART heads for a financial cliff (Feb 18, 2026):
  https://news.medill.northwestern.edu/chicago/several-stations-on-chopping-block-as-bart-heads-for-financial-cliff/
- Local News Matters, the Connect Bay Area measure certified for the ballot (Jul 2, 2026):
  https://localnewsmatters.org/2026/07/02/connect-bay-area-transit-tax-ballot-november-2026/
- The Stanford Daily, "Bay Area to vote on transit measure" (Oct 7, 2026):
  https://stanforddaily.com/2026/10/07/bay-area-to-vote-on-transit-measure/
- Antioch Herald, the BART board votes 8-1 to close up to 15 stations if the November tax measure fails (Feb 2026):
  https://antiochherald.com/2026/02/bart-board-votes-8-1-to-close-up-to-15-stations-if-proposed-nov-tax-measure-fails/
- Michael L. Anderson, "Subways, Strikes, and Slowdowns: The Impacts of Public Transit on Traffic Congestion",
  *American Economic Review* 104(9), 2014 (NBER working paper 18757): https://www.nber.org/papers/w18757
- E. Moylan, F. Foti and A. Skabardonis, "Observed and simulated traffic impacts from the 2013 Bay Area Rapid Transit
  strike", *Transportation Planning and Technology* 39(2), 2016: https://doi.org/10.1080/03081060.2015.1127539
- CBS News Bay Area, "BART strike economic impact put at $73 million" (July 2013):
  https://www.cbsnews.com/sanfrancisco/news/bart-strike-economic-impact-put-at-73-million-no-new-talks-set
- Ridership: BART hourly origin-destination ridership reports. Data provided by BART.
