# Air Karma Score Engine - India

A locality-level air-quality **fairness and explanation** dashboard built on the real CPCB feed from
[data.gov.in](https://data.gov.in/resource/real-time-air-quality-index-various-locations).

## Run it
```bash
pip install -r requirements.txt
python run.py            # http://localhost:8000
```
First start loads every CSV in `data/raw/` into SQLite and runs the analysis (about 45 s). Results are cached.
Python 3.10+.

## What it does
| Tab | What | Research gap it answers |
|---|---|---|
| Overview | Score for every station, city, state; map | G1 India focus |
| My locality | Search a station: score, exact per-pollutant split, plain-language reasons, SHAP for the PM2.5 estimate | G3, G7 (explanations to citizens) |
| Fairness | Within-city gaps, Gini, Moran's I, share of variance inside cities | G2, G3 |
| Model & XAI | PM2.5 estimation with random vs leave-city-out vs leave-state-out validation; SHAP vs permutation vs impurity; bootstrap stability | G4, G6 |
| Data quality | Every cleaning step counted; score sensitivity | G5 |
| Data | Upload newer snapshots to build history | temporal work later |

## Score
`burden = 0.5*max(r) + 0.5*mean(r)`, `r = concentration / Indian NAAQS limit`; `score = 100*exp(-0.7*burden)`.
50 means about at the legal limit. Needs >=3 scored pollutants including PM2.5 or PM10.
Weights are starting choices; the Data quality tab shows the ranking is insensitive to them.

## Honest limits
* The CSV is a **single hourly snapshot**, so no forecasting or time trend yet. Run `scripts/fetch_datagov.py`
  hourly (free data.gov.in API key) or upload newer CSVs; history accumulates in `data/karma.sqlite`.
* Hourly values are compared with 24-hour standards: a snapshot, not a legal compliance test.
* **CO is excluded from the score**: its median in this file (35) is ~18x the NAAQS in mg/m3, so the unit is not mg/m3.
  Confirm the unit with CPCB, then it re-enters automatically if the median is plausible.
* The score ranks stations almost identically to the CPCB-style AQI (rho 0.99). Its added value is the exact
  decomposition, the fairness view and PM2.5 estimates where no sensor exists.
* No demographic data in this file, so "who is exposed" needs `data/city_covariates.csv`
  (`city,state,population,...`); the Fairness tab picks it up automatically.

## Layout
```
backend/app/  config, qc, scoring, spatial, ml, explain, pipeline, store, main (FastAPI)
frontend/     index.html, app.js, style.css, vendor/ (Leaflet, Chart.js, offline)
data/raw/     the data.gov.in CSVs     scripts/  fetch_datagov.py     tests/  pytest
```
Tests: `python -m pytest tests`
