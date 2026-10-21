"""PM2.5 estimation with honest validation, plus explanation-stability tests.

Research gaps addressed
  G6  models are validated on sites they already saw  -> we compare random-station CV against
      leave-city-out and leave-state-out CV (spatial blocks).
  G4  SHAP/LIME explanations can be unstable          -> we compare SHAP, permutation and impurity
      importance, and bootstrap how stable each ranking is.
  G1/G2 sparse monitoring                              -> we test whether neighbouring stations (IDW) help
      estimate PM2.5 where there is no sensor.
"""
import warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .spatial import idw

warnings.filterwarnings("ignore")
GASES = ["NO2", "SO2", "OZONE", "NH3", "CO"]
FEATURE_SETS = {
    "Gases only": GASES,
    "Gases + PM10": GASES + ["PM10"],
    "Neighbours only (IDW)": ["nbr_pm25"],
    "Gases + neighbours": GASES + ["nbr_pm25"],
    "Gases + PM10 + neighbours": GASES + ["PM10", "nbr_pm25"],
}
MODELS = {
    "Ridge": lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                   RidgeCV(alphas=np.logspace(-2, 3, 12))),
    "Random forest": lambda: make_pipeline(SimpleImputer(strategy="median"),
                                           RandomForestRegressor(300, min_samples_leaf=3, n_jobs=-1,
                                                                 random_state=0)),
    "Gradient boosting": lambda: HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05,
                                                               max_iter=250, random_state=0),
}


def _add_nbr(train: pd.DataFrame, test: pd.DataFrame | None, k=5):
    """Neighbour PM2.5 feature built ONLY from training stations (no leakage)."""
    tr = train.copy()
    tr["nbr_pm25"], _ = idw(tr["lat"].values, tr["lon"].values, tr["pm25"].values,
                            tr["lat"].values, tr["lon"].values, k, exclude_self=True)
    if test is None:
        return tr, None
    te = test.copy()
    te["nbr_pm25"], _ = idw(tr["lat"].values, tr["lon"].values, tr["pm25"].values,
                            te["lat"].values, te["lon"].values, k)
    return tr, te


def _splits(df, scheme, seed=0):
    if scheme == "Random stations":
        return list(KFold(5, shuffle=True, random_state=seed).split(df))
    groups = df["city"] if scheme == "Leave-city-out" else df["state"]
    return list(GroupKFold(5).split(df, groups=groups))


def cross_validate(df: pd.DataFrame) -> list[dict]:
    """df: one row per station with measured PM2.5 (pm25) and features."""
    df = df.reset_index(drop=True)
    results = []
    y_all = df["pm25"].values
    for scheme in ["Random stations", "Leave-city-out", "Leave-state-out"]:
        folds = _splits(df, scheme)
        # baseline: predict the training mean
        pred = np.zeros(len(df))
        for tr, te in folds:
            pred[te] = y_all[tr].mean()
        results.append(_row(scheme, "Baseline: training mean", "-", y_all, pred))
        for fs_name, feats in FEATURE_SETS.items():
            for m_name, mk in MODELS.items():
                if feats == ["nbr_pm25"] and m_name != "Ridge":
                    continue  # one feature: a linear model is enough
                pred = np.full(len(df), np.nan)
                for tr, te in folds:
                    a, b = _add_nbr(df.iloc[tr], df.iloc[te])
                    model = mk().fit(a[feats], a["pm25"])
                    pred[te] = model.predict(b[feats])
                results.append(_row(scheme, fs_name, m_name, y_all, pred))
    return results


def _row(scheme, fs, model, y, pred):
    return {"scheme": scheme, "features": fs, "model": model,
            "r2": float(r2_score(y, pred)), "mae": float(mean_absolute_error(y, pred)),
            "rmse": float(np.sqrt(np.mean((y - pred) ** 2)))}


def explain(df: pd.DataFrame, feats: list[str], n_boot=20, seed=0):
    """Fit on all stations; return SHAP (global+local), permutation and impurity importance and the
    bootstrap stability of each ranking."""
    import shap
    d = df.reset_index(drop=True)
    tr, _ = _add_nbr(d, None)
    X, y = tr[feats], tr["pm25"]
    Xf = X.fillna(X.median())
    rf = RandomForestRegressor(300, min_samples_leaf=3, n_jobs=-1, random_state=seed).fit(Xf, y)
    sv = shap.TreeExplainer(rf).shap_values(Xf)
    base = float(np.ravel(shap.TreeExplainer(rf).expected_value)[0])
    shap_imp = np.abs(sv).mean(0)
    perm = permutation_importance(rf, Xf, y, n_repeats=10, random_state=seed, n_jobs=-1).importances_mean
    imp = rf.feature_importances_

    rng = np.random.default_rng(seed)
    ranks = {"SHAP": [], "Permutation": [], "Impurity": []}
    pair_rho = {"SHAP vs Permutation": [], "SHAP vs Impurity": [], "Permutation vs Impurity": []}
    top1 = {"SHAP": [], "Permutation": [], "Impurity": []}
    for _ in range(n_boot):
        idx = rng.integers(0, len(Xf), len(Xf))
        Xb, yb = Xf.iloc[idx], y.iloc[idx]
        m = RandomForestRegressor(100, min_samples_leaf=3, n_jobs=-1, random_state=int(rng.integers(1e6))).fit(Xb, yb)
        s = np.abs(shap.TreeExplainer(m).shap_values(Xf.iloc[:200])).mean(0)
        p = permutation_importance(m, Xf, y, n_repeats=3, random_state=0, n_jobs=-1).importances_mean
        i = m.feature_importances_
        vals = {"SHAP": s, "Permutation": p, "Impurity": i}
        for k, v in vals.items():
            ranks[k].append(pd.Series(v).rank(ascending=False).values)
            top1[k].append(feats[int(np.argmax(v))])
        pair_rho["SHAP vs Permutation"].append(spearmanr(s, p)[0])
        pair_rho["SHAP vs Impurity"].append(spearmanr(s, i)[0])
        pair_rho["Permutation vs Impurity"].append(spearmanr(p, i)[0])

    stability = {}
    for k in ranks:
        arr = np.array(ranks[k])
        mode = pd.Series(top1[k]).value_counts(normalize=True)
        stability[k] = {"mean_rank": dict(zip(feats, map(float, arr.mean(0)))),
                        "rank_sd": dict(zip(feats, map(float, arr.std(0)))),
                        "top1_feature": mode.index[0], "top1_frequency": float(mode.iloc[0])}
    corr = tr[feats].corr().abs()
    pairs = [(a, b, float(corr.loc[a, b])) for i, a in enumerate(feats) for b in feats[i + 1:]]
    pairs.sort(key=lambda t: -t[2])
    return {
        "features": feats,
        "importance": {"SHAP": dict(zip(feats, map(float, shap_imp))),
                       "Permutation": dict(zip(feats, map(float, perm))),
                       "Impurity": dict(zip(feats, map(float, imp)))},
        "stability": stability,
        "method_agreement_rho": {k: [float(np.nanmean(v)), float(np.nanstd(v))] for k, v in pair_rho.items()},
        "correlated_pairs": [{"a": a, "b": b, "abs_corr": c} for a, b, c in pairs[:4]],
        "n_boot": n_boot,
        "local": {"index": tr.index.tolist(), "base": base, "shap": sv.tolist(),
                  "x": Xf.round(3).values.tolist()},
    }, rf, tr


def fit_best(df: pd.DataFrame, feats: list[str], model_name: str):
    tr, _ = _add_nbr(df.reset_index(drop=True), None)
    return MODELS[model_name]().fit(tr[feats], tr["pm25"]), tr
