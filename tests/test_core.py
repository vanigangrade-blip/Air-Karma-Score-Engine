import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import numpy as np, pandas as pd
from app import config as C, scoring, spatial, qc


def _w(**vals):
    row = {p: np.nan for p in C.POLLUTANTS}
    row.update(vals)
    return pd.DataFrame([row])


def test_score_at_legal_limit_is_about_50():
    w = _w(**{"PM2.5": 60, "PM10": 100, "NO2": 80, "SO2": 80, "OZONE": 100, "NH3": 400})
    k = scoring.karma(w)
    assert abs(k["burden"].iloc[0] - 1.0) < 1e-9
    assert abs(k["score"].iloc[0] - 100 * np.exp(-0.7)) < 1e-9


def test_contributions_add_up_to_burden():
    w = _w(**{"PM2.5": 150, "PM10": 120, "NO2": 20, "SO2": 10, "OZONE": 30, "NH3": 5})
    k = scoring.karma(w)
    total = sum(k[f"c_{p}"].iloc[0] for p in C.SCORED_DEFAULT)
    assert abs(total - k["burden"].iloc[0]) < 1e-9


def test_needs_three_pollutants_and_a_pm_reading():
    assert not scoring.karma(_w(**{"PM2.5": 50, "NO2": 10}))["scorable"].iloc[0]
    assert not scoring.karma(_w(**{"NO2": 10, "SO2": 5, "OZONE": 20}))["scorable"].iloc[0]
    assert scoring.karma(_w(**{"PM2.5": 50, "NO2": 10, "SO2": 5}))["scorable"].iloc[0]


def test_aqi_breakpoints():
    assert abs(scoring._sub_index("PM2.5", 60) - 100) < 1e-9
    assert abs(scoring._sub_index("PM2.5", 30) - 50) < 1e-9


def test_qc_counts_na_and_flags_co_unit():
    df = pd.DataFrame({"state": "S", "city": "C", "station": ["a"] * 3, "latitude": 20.0, "longitude": 78.0,
                       "last_update": pd.Timestamp("2026-10-21 08:00"),
                       "pollutant_id": ["PM2.5", "PM10", "CO"],
                       "pollutant_min": [1, 1, 30], "pollutant_max": [90, 99, 50], "pollutant_avg": [np.nan, 50, 35]})
    d, rep = qc.clean(df)
    assert rep["na_by_pollutant"] == {"PM2.5": 1}
    assert "CO" not in rep["scored_pollutants"] and rep["notes"]


def test_gini_and_haversine():
    assert spatial.gini([1, 1, 1, 1]) == 0
    assert 0.7 < spatial.gini([0, 0, 0, 10]) < 0.8
    d = spatial.haversine_matrix([28.61], [77.21], [19.07], [72.88])[0, 0]  # Delhi - Mumbai
    assert 1100 < d < 1200
