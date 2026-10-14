# eBART study data

**Data provided by BART** (San Francisco Bay Area Rapid Transit District). These files are derived from BART's
public ridership data under BART's developer license terms. They are aggregates, not BART's original files, and
this project is not affiliated with or endorsed by BART.

| File | Derived from |
|---|---|
| `station_week.csv` | BART hourly origin-destination ridership (afcweb.bart.gov/ridership/origin-destination), summed to station × ISO week by `analysis/causal/panel.py` |
| `station_month_weekday.csv` | BART monthly ridership reports, 2016–2020 (bart.gov → About → Reports → Ridership, "Weekday OD" sheets), parsed by `analysis/causal/monthly.py` |
| `station_codes_2letter.csv` | A lookup from the two-letter station codes in BART's monthly reports to the four-letter codes used everywhere else, with BART's station names |

The study window (2016–2020) is fixed by the pre-registration (`analysis/causal/preregistration.json`), so these
files do not change when BART publishes new months. The live ridership in the warehouse refreshes on its own
schedule (`pipeline/definitions.py`).
