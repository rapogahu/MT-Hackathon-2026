"""Controlled, independent categorical interactions for Pilot Model v5."""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
import xgboost
from xgboost import XGBRegressor

import model_selection as ms
import recency_weighting_experiment as rw


ARTIFACT = ms.RESULTS / "interaction_features_experiment.json"
REFERENCE = ms.RESULTS / "ensemble_experiment.json"
CANDIDATES = ("route_temperature_bucket", "route_is_day_off", "hour_temperature_bucket")
ROUTE_DEGRADATION_THRESHOLD = 0.01  # Absolute pooled per-route WAPE.


def interaction_dtype(name: str) -> pd.CategoricalDtype:
    if name == "route_temperature_bucket":
        values = (ms.ROUTES, ms.BUCKET_DTYPE.categories)
    elif name == "route_is_day_off":
        values = (ms.ROUTES, (0, 1))
    elif name == "hour_temperature_bucket":
        values = (range(24), ms.BUCKET_DTYPE.categories)
    else:
        raise ValueError(f"Unknown interaction: {name}")
    return pd.CategoricalDtype(categories=[f"{left}|{right}" for left in values[0]
                                       for right in values[1]], ordered=False)


def make_features(rows: pd.DataFrame, interactions: tuple[str, ...]) -> pd.DataFrame:
    features = ms.make_features(rows, rw.CONFIGURATION, "XGBRegressor")
    for name in interactions:
        left, right = name.split("_", 1)
        if left not in ("route", "hour") or right not in ("temperature_bucket", "is_day_off"):
            raise ValueError(f"Invalid interaction: {name}")
        tokens = rows[left].astype(str) + "|" + rows[right].astype(str)
        features[name] = pd.Categorical(tokens, dtype=interaction_dtype(name))
        if features[name].isna().any():
            raise ValueError(f"Unknown interaction category: {name}")
    expected = [*ms.FEATURE_CONFIGURATIONS[rw.CONFIGURATION], *interactions]
    if features.columns.tolist() != expected or features.isna().any().any():
        raise ValueError("Feature contract changed")
    return features


def evaluate(train: pd.DataFrame, valid: pd.DataFrame, parameters: dict,
             interactions: tuple[str, ...]) -> dict:
    weights, info = rw.sample_weights(train, "exponential_180")
    x_train = make_features(train, interactions)
    x_valid = make_features(valid, interactions)
    if any(x_train[name].cat.categories.tolist() != x_valid[name].cat.categories.tolist()
           for name in interactions):
        raise ValueError("Train/validation category semantics differ")
    model = XGBRegressor(**parameters)
    started = perf_counter()
    model.fit(x_train, train.boardings, sample_weight=weights)
    fit_seconds = perf_counter() - started
    started = perf_counter()
    raw = np.asarray(model.predict(x_valid), dtype="float64")
    predict_seconds = perf_counter() - started
    if len(raw) != len(valid) or not np.isfinite(raw).all():
        raise ValueError("Invalid prediction")
    prediction = np.floor(np.maximum(raw, 0) + 0.5).astype("int64")
    prediction[valid.route.to_numpy() == 5] = 0
    metrics = ms.measure(valid.boardings.to_numpy(dtype="int64"), prediction,
                         valid.route.to_numpy())
    if metrics["per_route"]["5"]["absolute_error"] != 0:
        raise ValueError("Route 5 contract failed")
    metrics.update({"train_seconds": fit_seconds, "inference_seconds": predict_seconds,
                    "train_rows": len(train), "validation_rows": len(valid),
                    "weight_origin": info["origin"]})
    return metrics


def compare(folds: list[dict], reference_folds: list[dict]) -> dict:
    summary = ms.summarize(folds)
    baseline = ms.summarize(reference_folds)
    fold_delta = {spec[0]: current["wape"] - prior["wape"]
                  for spec, current, prior in zip(ms.FOLDS, folds, reference_folds, strict=True)}
    route_delta = {key: summary["per_route"][key]["wape"] - value["wape"]
                   for key, value in baseline["per_route"].items() if value["wape"] is not None}
    delta = summary["pooled_wape"] - baseline["pooled_wape"]
    wins = sum(value < 0 for value in fold_delta.values())
    decision = ("REJECTED" if delta >= 0 else
                "SUPPORTED" if wins >= 2 and max(route_delta.values()) <= ROUTE_DEGRADATION_THRESHOLD
                else "MIXED")
    return {"delta_pooled_wape": delta, "delta_pooled_absolute_error":
            summary["pooled_absolute_error"] - baseline["pooled_absolute_error"],
            "fold_delta_wape": fold_delta, "fold_wins": wins,
            "route_delta_pooled_wape": route_delta, "decision": decision}


def check_reference(folds: list[dict], previous: dict) -> None:
    prior_folds = previous["fold_metrics"]["1.0"]
    for index, (actual, expected) in enumerate(zip(folds, prior_folds, strict=True), 1):
        if (actual["absolute_error"] != expected["absolute_error"] or
                actual["actual_sum"] != expected["actual_sum"] or
                any(actual["per_route"][str(route)]["absolute_error"] !=
                    expected["per_route"][str(route)]["absolute_error"] for route in ms.ROUTES)):
            raise ValueError(f"Pilot v5 reference mismatch on fold {index}; stop experiments")
    if ms.summarize(folds)["pooled_absolute_error"] != previous["summaries"]["1.0"]["pooled_absolute_error"]:
        raise ValueError("Pilot v5 pooled reference mismatch; stop experiments")


def run_experiment() -> dict:
    _, folds, hpo = rw.load_inputs("XGBRegressor")
    parameters = rw.model_contract(hpo, "XGBRegressor")
    previous = json.loads(REFERENCE.read_text(encoding="utf-8"))
    data_key = ms.DATA_PATH.relative_to(ms.ROOT).as_posix()
    if previous["source_sha256"][data_key] != ms.sha256(ms.DATA_PATH):
        raise ValueError("Reference data changed")
    if previous["parameters"]["XGBRegressor"] != parameters:
        raise ValueError("Reference parameters changed")

    configurations = {"Pilot v5": ()}
    configurations.update({name: (name,) for name in CANDIDATES})
    results = {"Pilot v5": [evaluate(train, valid, parameters, ()) for train, valid in folds]}
    check_reference(results["Pilot v5"], previous)
    comparisons = {}
    for name in CANDIDATES:
        results[name] = [evaluate(train, valid, parameters, (name,)) for train, valid in folds]
        comparisons[name] = compare(results[name], results["Pilot v5"])

    supported = tuple(name for name in CANDIDATES if comparisons[name]["decision"] == "SUPPORTED")
    if len(supported) >= 2:
        configurations["combined_supported"] = supported
        results["combined_supported"] = [evaluate(train, valid, parameters, supported)
                                         for train, valid in folds]
        comparisons["combined_supported"] = compare(results["combined_supported"], results["Pilot v5"])

    paths = (ms.DATA_PATH, ms.JAN_AUG_PATH, ms.SEP_OCT_PATH, rw.HPO_PATH,
             REFERENCE, Path(ms.__file__), Path(rw.__file__), Path(__file__))
    result = {
        "experiment": "PILOT_V5_CONTROLLED_INTERACTIONS",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {path.relative_to(ms.ROOT).as_posix(): ms.sha256(path) for path in paths},
        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                        "pandas": pd.__version__, "xgboost": xgboost.__version__},
        "target": "boardings", "observation_unit": ["route", "date", "hour"],
        "base_features": list(ms.FEATURE_CONFIGURATIONS[rw.CONFIGURATION]),
        "base_categorical_features": list(ms.CATEGORICAL),
        "configurations": {name: list(features) for name, features in configurations.items()},
        "interaction_categories": {name: interaction_dtype(name).categories.tolist() for name in CANDIDATES},
        "parameters": parameters,
        "weighting": "exp(-ln(2) * age_days / 180); origin=max(fold train date)",
        "postprocessing": "floor(max(raw, 0) + 0.5); route 5 = 0",
        "folds": [{"name": f[0], "train_period": [f[1], f[2]],
                   "validation_period": [f[3], f[4]]} for f in ms.FOLDS],
        "fold_results": results,
        "summaries": {name: ms.summarize(metrics) for name, metrics in results.items()},
        "comparisons_vs_pilot_v5": comparisons,
        "classification_rule": "SUPPORTED: pooled WAPE improves, at least two folds win, maximum route degradation <= 0.01 absolute WAPE; MIXED: pooled gain without these conditions; REJECTED: no pooled gain",
        "route_degradation_threshold": ROUTE_DEGRADATION_THRESHOLD,
        "reference_reproduced": True, "nov_dec_used": False,
        "final_fit_performed": False, "accepted_feature_registry_changed": False,
    }
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run_experiment()
    for name, summary in result["summaries"].items():
        decision = result["comparisons_vs_pilot_v5"].get(name, {}).get("decision", "REFERENCE")
        print(f"{name}: pooled WAPE={summary['pooled_wape']:.6f}; {decision}")
