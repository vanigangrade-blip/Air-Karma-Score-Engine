"""Orchestrates the full analysis for the latest snapshot and caches the result as JSON."""
import json
import math
import time
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from . import config as C
from . import ml, qc, scoring, spatial, store
from .explain import station_text


def _clean(o):
    """Make numpy/pandas values JSON safe (NaN -> None)."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(o) or math.isinf(o)) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if o is pd.NA or o is pd.NaT:
        return None
    return o


def build(progress=lambda msg: None) -> dict:
    t0 = time.time()
    snaps = store.snapshots()
    if not snaps:
        raise RuntimeError("No data loaded. Put a CSV in data/raw/ or POST one to /api/ingest.")
    latest = snaps[-1]
    progress("Cleaning data")
    raw = store.load(latest)
    d, qc_rep = qc.clean(raw)
    scored = qc_rep["scored_pollutants"]
    w = scoring.to_wide(d)
    # include stations that have only NA readings so coverage is honest
    all_st = raw[["state", "city", "station", "latitude", "longitude"]].drop_duplicates("station")
    w = all_st.merge(w.drop(columns=["state", "city", "latitude", "longitude"]), on="station", how="left")
    w = w.sort_values(["state", "city", "station"]).reset_index(drop=True)

    progress("Scoring")
    k = scoring.karma(w, scored)
    a = scoring.aqi(w)
    st = pd.concat([w, k, a], axis=1)
    st["id"] = [f"s{i}" for i in range(len(st))]
    st["pm25"], st["pm10"] = st["PM2.5"], st["PM10"]
    st["label"] = st["score"].map(scoring.label)

    # ---------- ML: PM2.5 estimation ----------
    progress("Validating PM2.5 models (random vs spatial blocks)")
    mdf = st.dropna(subset=["pm25", "latitude", "longitude"]).rename(columns={"latitude": "lat", "longitude": "lon"})
    cv = ml.cross_validate(mdf[["city", "state", "lat", "lon", "pm25"] + ml.GASES + ["PM10"]])
    cvdf = pd.DataFrame(cv)
    best_spatial = cvdf[(cvdf.scheme == "Leave-state-out") & (cvdf.model != "-")].sort_values("r2", ascending=False).iloc[0]
    feats_best = ml.FEATURE_SETS[best_spatial.features]
    progress("Explaining model (SHAP, permutation, bootstrap stability)")
    xai_feats = ml.GASES + ["PM10", "nbr_pm25"]
    xai, rf, trn = ml.explain(mdf[["city", "state", "lat", "lon", "pm25"] + ml.GASES + ["PM10"]], xai_feats)
    # local SHAP by station id
    local = {}
    ids = mdf["id"].tolist()
    for j, sid in enumerate(ids):
        sv = xai["local"]["shap"][j]
        local[sid] = {"base": xai["local"]["base"], "pred": xai["local"]["base"] + sum(sv),
                      "contrib": dict(zip(xai_feats, map(float, sv))),
                      "values": dict(zip(xai_feats, map(float, xai["local"]["x"][j])))}
    xai.pop("local")

    # gap filling: stations with no PM2.5 but other readings
    progress("Filling missing PM2.5")
    model, trn2 = ml.fit_best(mdf[["city", "state", "lat", "lon", "pm25"] + ml.GASES + ["PM10"]],
                              feats_best, best_spatial.model)
    miss = st[st["pm25"].isna() & st["latitude"].notna() & st[ml.GASES + ["PM10"]].notna().any(axis=1)].copy()
    st["pm25_est"] = np.nan
    if len(miss):
        nb, _ = spatial.idw(trn2["lat"].values, trn2["lon"].values, trn2["pm25"].values,
                            miss["latitude"].values, miss["longitude"].values, 5)
        X = pd.DataFrame({c: miss[c].values for c in ml.GASES + ["PM10"]})
        X["nbr_pm25"] = nb
        st.loc[miss.index, "pm25_est"] = model.predict(X[feats_best])

    # ---------- Fairness ----------
    progress("Fairness analysis")
    cf = spatial.city_fairness(st)
    cf["rank"] = cf["score"].rank(ascending=False, method="min").astype(int)
    multi = cf[cf.stations >= 2]
    st_sc = st.dropna(subset=["score"])
    moran = spatial.morans_i(st_sc["latitude"], st_sc["longitude"], st_sc["score"])
    vd = spatial.variance_decomposition(st_sc, "pm25")
    state_tbl = (cf.groupby("state").apply(lambda g: pd.Series({
        "cities": len(g), "stations": g["stations"].sum(),
        "score": np.average(g["score"], weights=g["stations"]),
        "best_city": g.loc[g["score"].idxmax(), "city"], "best_score": g["score"].max(),
        "worst_city": g.loc[g["score"].idxmin(), "city"], "worst_score": g["score"].min()}), include_groups=False)
        .reset_index())
    state_tbl["gap"] = state_tbl["best_score"] - state_tbl["worst_score"]

    # ---------- Sensitivity of the score design (gap: arbitrary weights) ----------
    progress("Sensitivity analysis")
    base = k["score"]
    sens = []
    for wm in (0.3, 0.5, 0.7):
        for kd in (0.5, 0.7, 1.0):
            alt = scoring.karma(w, scored, wm, kd)["score"]
            ok = base.notna() & alt.notna()
            sens.append({"w_max": wm, "k": kd, "station_rho": float(spearmanr(base[ok], alt[ok])[0])})
    ok = base.notna() & a["aqi"].notna()
    sens_aqi = float(spearmanr(base[ok], -a["aqi"][ok])[0])
    withco = scoring.karma(w, C.SCORED_DEFAULT + ["CO"])["score"]
    ok2 = base.notna() & withco.notna()
    co_rho = float(spearmanr(base[ok2], withco[ok2])[0])

    # ---------- Assemble ----------
    progress("Assembling")
    city_lookup = {(r["state"], r["city"]): r for r in cf.to_dict("records")}
    stations = []
    for rec in st.to_dict("records"):
        ratios = {p: rec.get(f"r_{p}") for p in scored}
        contrib = {p: rec.get(f"c_{p}") for p in scored}
        item = {
            "id": rec["id"], "state": rec["state"], "city": rec["city"], "station": rec["station"],
            "lat": rec["latitude"], "lon": rec["longitude"],
            "score": rec["score"], "burden": rec["burden"], "label": rec["label"],
            "dominant": rec["dominant"], "n_scored": int(rec["n_scored"]),
            "aqi": rec["aqi"], "aqi_cat": rec["aqi_cat"],
            "pm25": rec["pm25"], "pm10": rec["pm10"], "pm25_est": rec["pm25_est"],
            "readings": {p: rec.get(p) for p in C.POLLUTANTS},
            "ratios": ratios, "contrib": contrib,
        }
        cs = city_lookup.get((rec["state"], rec["city"]))
        item = _clean(item)
        item["text"] = station_text(item, _clean(cs) if cs else None)
        stations.append(item)

    top_state = state_tbl.sort_values("score")
    result = {
        "meta": {"snapshot": latest, "snapshots": snaps, "n_stations": len(st), "n_scored": int(st["score"].notna().sum()),
                 "n_cities": int(st["city"].nunique()), "n_states": int(st["state"].nunique()),
                 "scored_pollutants": scored, "built_seconds": round(time.time() - t0, 1),
                 "score_formula": {"w_max": C.W_MAX, "k": C.K_DECAY, "naaqs": C.NAAQS}},
        "stations": stations,
        "cities": cf.sort_values("rank").to_dict("records"),
        "states": top_state.to_dict("records"),
        "fairness": {"moran": moran, "variance": vd,
                     "cities_multi": int(len(multi)),
                     "median_gap": float(multi["gap"].median()) if len(multi) else None,
                     "widest": multi.sort_values("gap", ascending=False).head(15).to_dict("records")},
        "model": {"cv": cvdf.to_dict("records"), "best_spatial": best_spatial.to_dict(),
                  "xai": xai, "n_train": int(len(mdf)), "n_filled": int(st["pm25_est"].notna().sum()),
                  "local": local},
        "qc": qc_rep,
        "sensitivity": {"grid": sens, "vs_cpcb_aqi_rho": sens_aqi, "with_co_rho": co_rho},
    }
    return _clean(result)


def build_and_cache(progress=lambda m: None) -> dict:
    res = build(progress)
    C.CACHE_PATH.write_text(json.dumps(res))
    return res


def load_cache():
    if C.CACHE_PATH.exists():
        return json.loads(C.CACHE_PATH.read_text())
    return None


def equity(res: dict):
    """Optional: join user-supplied city covariates (city,state,population,...) for environmental justice."""
    if not C.EQUITY_PATH.exists():
        return {"available": False,
                "how": "Add data/city_covariates.csv with columns city,state,population (and any other "
                       "numeric columns, e.g. literacy, slum_share) from data.gov.in / Census."}
    cov = pd.read_csv(C.EQUITY_PATH)
    cov.columns = [c.strip().lower() for c in cov.columns]
    cities = pd.DataFrame(res["cities"])
    m = cities.merge(cov, on=["city", "state"], how="inner")
    out = {"available": True, "matched_cities": int(len(m)), "of": int(len(cities)), "correlations": {}}
    for c in cov.columns:
        if c in ("city", "state") or not pd.api.types.is_numeric_dtype(cov[c]):
            continue
        if m[c].notna().sum() >= 8:
            rho, p = spearmanr(m["score"], m[c], nan_policy="omit")
            out["correlations"][c] = {"rho": float(rho), "p": float(p), "n": int(m[c].notna().sum())}
    if "population" in m:
        mm = m.dropna(subset=["population", "score"])
        if len(mm):
            out["population_weighted_score"] = float(np.average(mm["score"], weights=mm["population"]))
            out["people_in_poor_air"] = int(mm.loc[mm["score"] < 35, "population"].sum())
    return _clean(out)
