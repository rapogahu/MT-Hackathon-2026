"""Controlled open-loop weekly-lag experiment on the tuned v4 LightGBM."""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import lightgbm
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

import model_selection as ms
from recency_weighting_experiment import assert_reference_reproduced, load_inputs

ARTIFACT = ms.RESULTS / "recursive_lag_168.json"
FEATURES = list(ms.FEATURE_CONFIGURATIONS["calendar_weather"])
LAG_HOURS = 168


def time_keys(rows: pd.DataFrame) -> pd.Series:
    return rows["date"] + pd.to_timedelta(rows["hour"], unit="h")


def train_lag(train: pd.DataFrame) -> pd.Series:
    # The complete hourly grid is already verified by ms.load_data/make_fold.
    order = train.assign(_time=time_keys(train)).sort_values(["route", "_time"])
    lag = order.groupby("route", sort=False)["boardings"].shift(LAG_HOURS).astype("float64")
    lag.loc[order.route.eq(5)] = np.nan
    result = lag.reindex(train.index)
    assert result.loc[train.route.eq(5)].isna().all()
    assert result.notna().sum() == int((~train.route.eq(5)).sum() - 9 * LAG_HOURS)
    return result


def postprocess(raw: np.ndarray, routes: np.ndarray) -> np.ndarray:
    if not np.isfinite(raw).all():
        raise ValueError("Non-finite model output")
    prediction = np.floor(np.maximum(raw, 0) + 0.5).astype("int64")
    prediction[routes == 5] = 0
    return prediction


def fit_candidate(train: pd.DataFrame, parameters: dict,
                  features: list[str] | None = None) -> tuple[LGBMRegressor, float, dict]:
    features = FEATURES if features is None else features
    x = ms.make_features(train, "calendar_weather", "LightGBM")[features].copy()
    lag = train_lag(train)
    x["lag_168"] = lag
    if x.columns.tolist() != features + ["lag_168"]:
        raise ValueError("Candidate feature order changed")
    start = perf_counter()
    model = LGBMRegressor(**parameters)
    model.fit(x, train.boardings, categorical_feature=[name for name in features if name in ms.CATEGORICAL])
    seconds = perf_counter() - start
    diagnostics = {"rows": len(train), "available": int(lag.notna().sum()),
                   "available_fraction": float(lag.notna().mean()),
                   "route_5_missing": bool(lag.loc[train.route.eq(5)].isna().all()),
                   "first_168_hours_missing_per_valid_route": True}
    return model, seconds, diagnostics


def recursive_predict(model: LGBMRegressor, train: pd.DataFrame,
                      valid_features: pd.DataFrame,
                      features: list[str] | None = None) -> tuple[np.ndarray, dict, float]:
    # This function accepts no validation target. State contains train actuals and
    # postprocessed predictions only; validation labels cannot enter it.
    if "boardings" in valid_features.columns:
        raise ValueError("Validation target must not enter recursive inference")
    features = FEATURES if features is None else features
    valid = valid_features.copy()
    valid["_time"] = time_keys(valid)
    valid = valid.sort_values(["_time", "route"]).reset_index().rename(columns={"index": "_original_index"})
    if valid.duplicated(["route", "_time"]).any():
        raise ValueError("Duplicate validation key")
    history = {(int(route), timestamp): (int(value), "actual_pre_origin")
               for route, timestamp, value in zip(train.route, time_keys(train), train.boardings)
               if route != 5}
    if any(key[0] == 5 for key in history):
        raise ValueError("Artificial route 5 history")
    predictions = np.empty(len(valid), dtype="int64")
    records = []
    lag_prediction_pairs = []
    origin = valid._time.min()
    start = perf_counter()
    for first in range(0, len(valid), 7 * 24 * len(ms.ROUTES)):
        block = valid.iloc[first:first + 7 * 24 * len(ms.ROUTES)]
        x = ms.make_features(block, "calendar_weather", "LightGBM")[features].copy()
        lag_values, sources = [], []
        for route, timestamp in zip(block.route, block._time):
            if route == 5:
                lag_values.append(np.nan)
                sources.append("missing_route_5")
                continue
            key = (int(route), timestamp - pd.Timedelta(hours=LAG_HOURS))
            if key not in history:
                raise ValueError(f"Missing lag key at {timestamp}")
            value, source = history[key]
            if source == "actual_pre_origin" and key[1] >= origin:
                raise ValueError("Validation actual leaked into state")
            if source == "recursive_prediction" and key[1] < origin:
                raise ValueError("Prediction predates origin")
            lag_values.append(value)
            sources.append(source)
        x["lag_168"] = np.asarray(lag_values, dtype="float64")
        if not x.loc[block.route.eq(5), "lag_168"].isna().all():
            raise ValueError("Route 5 lag must remain missing")
        pred = postprocess(model.predict(x), block.route.to_numpy())
        lag_prediction_pairs.extend((lag, value) for lag, value in zip(lag_values, pred) if np.isfinite(lag))
        predictions[first:first + len(block)] = pred
        for route, timestamp, value in zip(block.route, block._time, pred):
            if route != 5:
                history[(int(route), timestamp)] = (int(value), "recursive_prediction")
        records.extend((timestamp, source) for timestamp, source in zip(block._time, sources))
    seconds = perf_counter() - start
    if any(source not in ("actual_pre_origin", "recursive_prediction") for value, source in history.values()):
        raise ValueError("Unexpected state source")
    record = pd.DataFrame(records, columns=["time", "source"])
    record["day"] = ((record.time - origin).dt.total_seconds() // 86400).astype(int) + 1
    record["week"] = (record.day - 1) // 7 + 1
    source_counts = record.source.value_counts().to_dict()
    weekly = []
    for week, group in record.groupby("week", sort=True):
        counts = group.source.value_counts().to_dict()
        weekly.append({"week": int(week), "days": [int(group.day.min()), int(group.day.max())],
                       "rows": len(group), "actual_pre_origin_fraction": counts.get("actual_pre_origin", 0) / len(group),
                       "recursive_prediction_fraction": counts.get("recursive_prediction", 0) / len(group),
                       "missing_route_5_fraction": counts.get("missing_route_5", 0) / len(group)})
    diagnostics = {"rows": len(valid), "source_counts": source_counts,
                   "source_fractions": {name: source_counts.get(name, 0) / len(valid) for name in
                                        ("actual_pre_origin", "recursive_prediction", "missing_route_5")},
                   "weekly": weekly, "validation_actual_in_state": False,
                   "route_5_history_entries": 0, "route_5_lag_nonmissing": 0,
                   "prediction_lag_168_correlation": float(np.corrcoef(np.asarray(lag_prediction_pairs).T)[0, 1])}
    original_order = np.empty(len(valid), dtype="int64")
    original_order[valid._original_index.to_numpy()] = predictions
    return original_order, diagnostics, seconds


def horizon_metrics(valid: pd.DataFrame, reference: np.ndarray, candidate: np.ndarray) -> dict:
    day = (valid.date - valid.date.min()).dt.days.to_numpy() + 1
    result = {}
    for name, lower, upper in (("days_1_7", 1, 7), ("days_8_28", 8, 28), ("days_29_61", 29, 61)):
        mask = (day >= lower) & (day <= upper)
        actual = valid.boardings.to_numpy(dtype="int64")[mask]
        routes = valid.route.to_numpy()[mask]
        result[name] = {"reference": ms.measure(actual, reference[mask], routes),
                        "candidate": ms.measure(actual, candidate[mask], routes)}
        result[name]["delta_wape"] = result[name]["candidate"]["wape"] - result[name]["reference"]["wape"]
    return result


def run_experiment() -> dict:
    _, folds, hpo = load_inputs()
    parameters = hpo["final_configuration"]["parameters"]
    results = []
    for spec, (train, valid) in zip(ms.FOLDS, folds, strict=True):
        reference, ref_fit, ref_predict = ms.fit_predict(train, valid, "calendar_weather", "LightGBM", parameters)
        model, candidate_fit, train_diagnostic = fit_candidate(train, parameters)
        candidate, validation_diagnostic, candidate_predict = recursive_predict(
            model, train, valid.drop(columns="boardings"))
        actual = valid.boardings.to_numpy(dtype="int64")
        routes = valid.route.to_numpy()
        reference_metric = ms.measure(actual, reference, routes)
        reference_metric.update(train_seconds=ref_fit, inference_seconds=ref_predict)
        candidate_metric = ms.measure(actual, candidate, routes)
        candidate_metric.update(train_seconds=candidate_fit, inference_seconds=candidate_predict)
        results.append({"fold": spec[0], "reference": reference_metric, "candidate": candidate_metric,
                        "train_lag": train_diagnostic, "validation_lag": validation_diagnostic,
                        "horizons": horizon_metrics(valid, reference, candidate)})
    assert_reference_reproduced([row["reference"] for row in results], hpo)
    summaries = {name: ms.summarize([row[name] for row in results]) for name in ("reference", "candidate")}
    pooled_horizons = {}
    for bucket in ("days_1_7", "days_8_28", "days_29_61"):
        pooled_horizons[bucket] = {}
        for name in ("reference", "candidate"):
            actual = sum(row["horizons"][bucket][name]["actual_sum"] for row in results)
            error = sum(row["horizons"][bucket][name]["absolute_error"] for row in results)
            pooled_horizons[bucket][name] = {"actual_sum": actual, "absolute_error": error,
                                            "wape": error / actual, "wape_score": max(0.0, 1 - error / actual)}
        pooled_horizons[bucket]["delta_wape"] = (pooled_horizons[bucket]["candidate"]["wape"] -
                                                 pooled_horizons[bucket]["reference"]["wape"])
    delta = summaries["candidate"]["pooled_wape"] - summaries["reference"]["pooled_wape"]
    late = [pooled_horizons[key]["delta_wape"] for key in ("days_8_28", "days_29_61")]
    fold_delta = [row["candidate"]["wape"] - row["reference"]["wape"] for row in results]
    if delta >= 0 or all(value >= 0 for value in late):
        classification = "RECURSIVE_LAG168_REJECTED"
    elif all(value <= 0 for value in fold_delta) and all(value < 0 for value in late):
        classification = "RECURSIVE_LAG168_SUPPORTED"
    else:
        classification = "RECURSIVE_LAG168_MIXED"
    result = {"experiment": "RECURSIVE_LAG168_CONTROLLED", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_sha256": {p.relative_to(ms.ROOT).as_posix(): ms.sha256(p) for p in
                                (ms.DATA_PATH, ms.JAN_AUG_PATH, ms.SEP_OCT_PATH,
                                 ms.RESULTS / "hyperparameter_tuning.json", Path(ms.__file__), Path(__file__))},
              "environment": {"python": platform.python_version(), "pandas": pd.__version__,
                              "numpy": np.__version__, "lightgbm": lightgbm.__version__},
              "parameters": parameters, "reference_features": FEATURES, "candidate_features": FEATURES + ["lag_168"],
              "lag_hours": LAG_HOURS, "postprocessing": "floor(max(raw, 0) + 0.5); route 5 = 0",
              "folds": results, "summaries": summaries, "pooled_horizons": pooled_horizons,
              "delta_pooled_wape": delta,
              "delta_pooled_absolute_error": (summaries["candidate"]["pooled_absolute_error"] -
                                              summaries["reference"]["pooled_absolute_error"]),
              "classification_rule": "REJECTED if pooled WAPE does not improve or neither late horizon improves; SUPPORTED if pooled WAPE and both late horizons improve with no worse fold; otherwise MIXED",
              "classification": classification, "nov_dec_used": False, "final_fit_performed": False,
              "accepted_feature_registry_changed": False}
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run_experiment()
    print("Fold WAPE:", [(row["fold"], round(row["reference"]["wape"], 6),
                          round(row["candidate"]["wape"], 6)) for row in result["folds"]])
    print("Pooled WAPE:", result["summaries"]["reference"]["pooled_wape"],
          result["summaries"]["candidate"]["pooled_wape"])
    print("Classification:", result["classification"])
