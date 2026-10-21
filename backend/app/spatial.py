"""Geometry, inequality and spatial statistics."""
import numpy as np
import pandas as pd


def haversine_matrix(lat1, lon1, lat2, lon2):
    """Pairwise distance in km, shape (len1, len2)."""
    la1, lo1 = np.radians(np.asarray(lat1))[:, None], np.radians(np.asarray(lon1))[:, None]
    la2, lo2 = np.radians(np.asarray(lat2))[None, :], np.radians(np.asarray(lon2))[None, :]
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def idw(train_lat, train_lon, train_val, q_lat, q_lon, k=5, exclude_self=False):
    """Inverse-distance-weighted mean of the k nearest training values (min distance 1 km)."""
    D = haversine_matrix(q_lat, q_lon, train_lat, train_lon)
    if exclude_self:
        np.fill_diagonal(D, np.inf)
    k = min(k, D.shape[1] - (1 if exclude_self else 0))
    idx = np.argpartition(D, k - 1, axis=1)[:, :k]
    d = np.take_along_axis(D, idx, 1)
    v = np.asarray(train_val)[idx]
    w = 1.0 / np.maximum(d, 1.0)
    return (w * v).sum(1) / w.sum(1), d.min(1)


def gini(x):
    x = np.sort(np.asarray(x, float))
    x = x[~np.isnan(x)]
    if len(x) < 2 or x.sum() <= 0:
        return None
    n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def morans_i(lat, lon, val, k=8, n_perm=499, seed=0):
    """Global Moran's I with k-nearest-neighbour weights (row-standardised) and a permutation p-value."""
    lat, lon, val = np.asarray(lat), np.asarray(lon), np.asarray(val, float)
    ok = ~np.isnan(val)
    lat, lon, val = lat[ok], lon[ok], val[ok]
    n = len(val)
    D = haversine_matrix(lat, lon, lat, lon)
    np.fill_diagonal(D, np.inf)
    kk = min(k, n - 1)
    idx = np.argpartition(D, kk - 1, axis=1)[:, :kk]
    W = np.zeros((n, n))
    np.put_along_axis(W, idx, 1.0 / kk, 1)
    z = val - val.mean()

    def stat(zv):
        return float((n / W.sum()) * (zv @ W @ zv) / (zv @ zv))

    obs = stat(z)
    rng = np.random.default_rng(seed)
    perm = np.array([stat(rng.permutation(z)) for _ in range(n_perm)])
    p = float((1 + (perm >= obs).sum()) / (n_perm + 1))
    return {"I": obs, "expected": -1.0 / (n - 1), "p_value": p, "n": int(n), "k": int(kk)}


def variance_decomposition(df: pd.DataFrame, col: str):
    """Share of variance of `col` that lies *within* cities (cities with >=2 stations)."""
    g = df.dropna(subset=[col]).groupby("city")
    sizes = g[col].transform("size")
    d = df.dropna(subset=[col])[sizes >= 2]
    if len(d) < 4:
        return None
    grand = d[col].mean()
    ss_tot = ((d[col] - grand) ** 2).sum()
    ss_within = ((d[col] - d.groupby("city")[col].transform("mean")) ** 2).sum()
    return {"within_city_share": float(ss_within / ss_tot), "stations": int(len(d)),
            "cities": int(d["city"].nunique())}


def city_fairness(st: pd.DataFrame) -> pd.DataFrame:
    """st: station table with columns state, city, station, score, burden, pm25."""
    rows = []
    for (state, city), g in st.dropna(subset=["score"]).groupby(["state", "city"]):
        best, worst = g.loc[g["score"].idxmax()], g.loc[g["score"].idxmin()]
        mean, sd = g["score"].mean(), g["score"].std(ddof=0)
        rows.append({
            "state": state, "city": city, "stations": int(len(g)),
            "score": float(mean), "best_station": best["station"], "best_score": float(best["score"]),
            "worst_station": worst["station"], "worst_score": float(worst["score"]),
            "gap": float(best["score"] - worst["score"]),
            "burden_gini": gini(g["burden"]) if len(g) >= 2 else None,
            "hotspots": int((g["score"] < mean - sd).sum()) if len(g) >= 3 and sd > 0 else 0,
            "worst_pm25": None if g["pm25"].isna().all() else float(g["pm25"].max()),
            "best_pm25": None if g["pm25"].isna().all() else float(g["pm25"].min()),
        })
    return pd.DataFrame(rows)
