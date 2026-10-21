"""Constants. Every threshold used by the engine is defined here so it can be audited."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "karma.sqlite"
CACHE_PATH = DATA_DIR / "cache.json"
EQUITY_PATH = DATA_DIR / "city_covariates.csv"  # optional: city,state,population,...

# Indian NAAQS (2009) 24-hour / 8-hour standards. ug/m3 except CO (mg/m3).
NAAQS = {"PM2.5": 60.0, "PM10": 100.0, "NO2": 80.0, "SO2": 80.0, "OZONE": 100.0, "NH3": 400.0, "CO": 2.0}
POLLUTANTS = list(NAAQS)
# CO is excluded from the score when its unit looks wrong (see qc.py).
SCORED_DEFAULT = ["PM2.5", "PM10", "NO2", "SO2", "OZONE", "NH3"]

# Above these values a reading is an instrument error, not a pollution episode.
CAP = {"PM2.5": 1500, "PM10": 2500, "NO2": 1000, "SO2": 1000, "OZONE": 1000, "NH3": 3000, "CO": 1000}

# Score parameters (starting choices; sensitivity analysis in pipeline.py tests them).
W_MAX = 0.5
K_DECAY = 0.7
MIN_POLLUTANTS = 3  # a score needs >= 3 scored pollutants including PM2.5 or PM10

SCORE_BANDS = [(75, "Clean"), (55, "Fair"), (35, "Poor"), (15, "Very poor"), (-1, "Severe")]

# CPCB AQI breakpoints (Good, Satisfactory, Moderate, Poor, Very Poor, Severe)
AQI_BANDS = [(0, 50), (51, 100), (101, 200), (201, 300), (301, 400), (401, 500)]
AQI_NAMES = ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
AQI_BREAKS = {
    "PM2.5": [0, 30, 60, 90, 120, 250, 380],
    "PM10": [0, 50, 100, 250, 350, 430, 510],
    "NO2": [0, 40, 80, 180, 280, 400, 520],
    "OZONE": [0, 50, 100, 168, 208, 748, 900],
    "SO2": [0, 40, 80, 380, 800, 1600, 2000],
    "NH3": [0, 200, 400, 800, 1200, 1800, 2400],
}
HEALTH = {
    "Good": "Minimal impact.",
    "Satisfactory": "May cause minor breathing discomfort to sensitive people.",
    "Moderate": "May cause breathing discomfort to people with lung or heart disease, children and older adults.",
    "Poor": "May cause breathing discomfort to most people on prolonged exposure.",
    "Very Poor": "May cause respiratory illness on prolonged exposure.",
    "Severe": "Affects healthy people and seriously affects those with existing diseases.",
}
