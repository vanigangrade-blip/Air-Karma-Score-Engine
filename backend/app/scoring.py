"""Air Karma Score: transparent, additive, exactly decomposable. Also CPCB-style indicative AQI."""
import numpy as np
import pandas as pd
from . import config as C


def _idxmax(df: pd.DataFrame) -> pd.Series:
    """Row-wise column of the maximum; NaN for all-NaN rows (pandas idxmax raises on those)."""
    filled = df.fillna(-np.inf)
    res = filled.idxmax(axis=1)
    return res.where(df.notna().any(axis=1))


def to_wide(d: pd.DataFrame) -> pd.DataFrame:
    keys = ["state", "city", "station", "latitude", "longitude"]
    w = d.pivot_table(index=keys, columns="pollutant_id", values="pollutant_avg", aggfunc="mean").reset_index()
    for p in C.POLLUTANTS:
        if p not in w.columns:
            w[p] = np.nan
    return w


def karma(w: pd.DataFrame, scored=None, w_max=C.W_MAX, k=C.K_DECAY) -> pd.DataFrame:
    """burden = w_max*max_p r_p + (1-w_max)*mean_p r_p ; score = 100*exp(-k*burden).
    r_p = concentration / NAAQS.  Score 50 ~ burden 1 ~ at the legal limit."""
    scored = scored or C.SCORED_DEFAULT
    r = pd.DataFrame({p: w[p] / C.NAAQS[p] for p in scored})
    n = r.notna().sum(axis=1)
    has_pm = r[[c for c in ("PM2.5", "PM10") if c in r]].notna().any(axis=1)
    ok = (n >= C.MIN_POLLUTANTS) & has_pm
    mx, mean = r.max(axis=1), r.mean(axis=1)
    burden = (w_max * mx + (1 - w_max) * mean).where(ok)
    out = pd.DataFrame({"burden": burden, "score": 100 * np.exp(-k * burden),
                        "n_scored": n, "scorable": ok})
    out["dominant"] = _idxmax(r).where(ok)
    for p in scored:
        out[f"r_{p}"] = r[p]
    # exact additive contribution of each pollutant to the burden
    top = _idxmax(r)
    for p in scored:
        out[f"c_{p}"] = (w_max * (top == p) * r[p] + (1 - w_max) * r[p] / n).where(ok)
    return out


def label(score: float) -> str:
    if score is None or np.isnan(score):
        return "Not scorable"
    for lo, name in C.SCORE_BANDS:
        if score >= lo:
            return name
    return "Severe"


def _sub_index(p: str, c: float):
    if p not in C.AQI_BREAKS or pd.isna(c):
        return np.nan
    b = C.AQI_BREAKS[p]
    for i in range(6):
        if c <= b[i + 1]:
            lo_c, hi_c = b[i], b[i + 1]
            lo_i, hi_i = C.AQI_BANDS[i]
            return lo_i + (c - lo_c) * (hi_i - lo_i) / (hi_c - lo_c)
    return 500.0


def aqi(w: pd.DataFrame) -> pd.DataFrame:
    """Indicative CPCB-style AQI = max sub-index. CPCB requires >=3 pollutants incl. PM and 24-h
    averages; this feed is one hourly value, so the result is indicative only."""
    subs = pd.DataFrame({p: [_sub_index(p, v) for v in w[p]] for p in C.AQI_BREAKS}, index=w.index)
    n = subs.notna().sum(axis=1)
    ok = (n >= 3) & subs[["PM2.5", "PM10"]].notna().any(axis=1)
    val = subs.max(axis=1).where(ok)
    cat = pd.cut(val, [-1, 50, 100, 200, 300, 400, 1000], labels=C.AQI_NAMES)
    return pd.DataFrame({"aqi": val, "aqi_cat": cat.astype(object), "aqi_driver": _idxmax(subs).where(ok)})
