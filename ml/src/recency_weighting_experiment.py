"""Controlled sample-weight experiment for the tuned Pilot v4 LightGBM."""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import lightgbm
import xgboost
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor

import model_selection as ms

HPO_PATH = ms.RESULTS / "hyperparameter_tuning.json"
ARTIFACT = ms.RESULTS / "recency_weighting.json"
CONFIGURATION = "calendar_weather"
WEIGHTING_CONFIGURATIONS = ("reference", "fixed", "exponential_120", "exponential_180")
ROUTE_DEGRADATION_THRESHOLD = 0.01  # Absolute pooled route WAPE.


def model_contract(hpo: dict, family: str) -> dict:
    if family == "LightGBM":
        contract = hpo["final_configuration"]
        expected = {**ms.MODEL_PARAMETERS, "n_estimators": 400, "max_depth": 8,
                    "learning_rate": 0.1, "num_leaves": 15, "min_child_samples": 40}
    elif family == "XGBRegressor":
        contract = hpo["ensemble_candidate"]
        expected = {**ms.XGBOOST_PARAMETERS, "n_estimators": 500,
                    "max_depth": 6, "learning_rate": 0.1, "min_child_weight": 1}
    else:
        raise ValueError(f"Unsupported family: {family}")
    if contract["family"] != family or contract["parameters"] != expected:
        raise ValueError(f"Tuned {family} parameters differ from current HPO contract")
    return contract["parameters"]


def load_inputs(family: str = "LightGBM") -> tuple[pd.DataFrame, list[tuple[pd.DataFrame, pd.DataFrame]], dict]:
    hpo = json.loads(HPO_PATH.read_text(encoding="utf-8"))
    model_contract(hpo, family)
    if hpo["configuration"] != CONFIGURATION or hpo["features"] != list(ms.FEATURE_CONFIGURATIONS[CONFIGURATION]):
        raise ValueError("HPO feature configuration differs")
    if hpo["folds"] != [
        {"name": f[0], "train_period": [f[1], f[2]],
         "validation_period": [f[3], f[4]]} for f in ms.FOLDS
    ]:
        raise ValueError("Temporal folds differ from HPO")
    for path in (ms.DATA_PATH, ms.JAN_AUG_PATH, ms.SEP_OCT_PATH,
                 Path(ms.__file__), ms.ROOT / "ml/src/hyperparameter_tuning.py"):
        relative = path.relative_to(ms.ROOT).as_posix()
        if ms.sha256(path) != hpo["source_sha256"][relative]:
            raise ValueError(f"HPO source changed: {relative}")
    rows = ms.load_data()
    folds = [ms.make_fold(rows, spec) for spec in ms.FOLDS]
    return rows, folds, hpo


def sample_weights(train: pd.DataFrame, configuration: str) -> tuple[np.ndarray | None, dict]:
    if configuration not in WEIGHTING_CONFIGURATIONS:
        raise ValueError(f"Unknown weighting configuration: {configuration}")
    origin = train.date.max()
    age_days = (origin - train.date).dt.days.to_numpy(dtype="int64")
    if len(age_days) != len(train) or age_days.min() != 0 or (age_days < 0).any():
        raise ValueError("Age must be relative to the current fold train end")
    if configuration == "reference":
        weights = None
    elif configuration == "fixed":
        weights = np.select(
            [age_days <= 30, age_days <= 60, age_days <= 120],
            [1.0, 0.95, 0.85], default=0.70,
        ).astype("float64")
    else:
        half_life_days = 120 if configuration == "exponential_120" else 180
        weights = np.exp(-np.log(2.0) * age_days / half_life_days)
    effective = np.ones(len(train), dtype="float64") if weights is None else weights
    if not np.isfinite(effective).all() or (effective <= 0).any() or (effective > 1).any():
        raise ValueError("Invalid sample weights")
    if not np.all(effective[age_days == 0] == 1.0):
        raise ValueError("Newest train observations must have weight 1")
    diagnostics = {
        "origin": origin.strftime("%Y-%m-%d"),
        "min_age_days": int(age_days.min()),
        "max_age_days": int(age_days.max()),
        "min_weight": float(effective.min()),
        "mean_weight": float(effective.mean()),
        "max_weight": float(effective.max()),
        "rows": len(train),
        "age_bin_rows": {
            "0_30": int((age_days <= 30).sum()),
            "31_60": int(((age_days > 30) & (age_days <= 60)).sum()),
            "61_120": int(((age_days > 60) & (age_days <= 120)).sum()),
            "over_120": int((age_days > 120).sum()),
        },
    }
    return weights, diagnostics


def evaluate_fold(train: pd.DataFrame, valid: pd.DataFrame, configuration: str,
                  parameters: dict, family: str = "LightGBM") -> dict:
    weights, weight_diagnostics = sample_weights(train, configuration)
    x_train = ms.make_features(train, CONFIGURATION, family)
    x_valid = ms.make_features(valid, CONFIGURATION, family)
    if x_train.columns.tolist() != list(ms.FEATURE_CONFIGURATIONS[CONFIGURATION]):
        raise ValueError("Feature order changed")
    model = LGBMRegressor(**parameters) if family == "LightGBM" else XGBRegressor(**parameters)
    fit_options = {"categorical_feature": list(ms.CATEGORICAL)} if family == "LightGBM" else {}
    start = perf_counter()
    model.fit(x_train, train.boardings, sample_weight=weights, **fit_options)
    train_seconds = perf_counter() - start
    start = perf_counter()
    raw = model.predict(x_valid)
    inference_seconds = perf_counter() - start
    if not np.isfinite(raw).all():
        raise ValueError("Non-finite raw validation prediction")
    prediction = np.floor(np.maximum(raw, 0) + 0.5).astype("int64")
    prediction[valid.route.to_numpy() == 5] = 0
    result = ms.measure(valid.boardings.to_numpy(dtype="int64"), prediction,
                        valid.route.to_numpy())
    if result["per_route"]["5"]["absolute_error"] != 0:
        raise ValueError("Route 5 prediction policy failed")
    result["train_seconds"] = train_seconds
    result["inference_seconds"] = inference_seconds
    result["weight_diagnostics"] = weight_diagnostics
    return result


def evaluate_configuration(folds: list[tuple[pd.DataFrame, pd.DataFrame]],
                           configuration: str, parameters: dict,
                           family: str = "LightGBM") -> list[dict]:
    return [evaluate_fold(train, valid, configuration, parameters, family) for train, valid in folds]


def assert_reference_reproduced(reference_folds: list[dict], hpo: dict,
                                family: str = "LightGBM") -> None:
    expected = hpo["studies"][family]["best_tuned"]["fold_results"]
    for index, (current, prior) in enumerate(zip(reference_folds, expected, strict=True)):
        if current["actual_sum"] != prior["actual_sum"] or current["absolute_error"] != prior["absolute_error"]:
            raise ValueError(f"Tuned {family} reference mismatch on fold {index + 1}")
        for route in ms.ROUTES:
            if current["per_route"][str(route)]["absolute_error"] != prior["per_route"][str(route)]["absolute_error"]:
                raise ValueError(f"Tuned {family} route mismatch on fold {index + 1}, route {route}")
    pooled = ms.summarize(reference_folds)
    prior_pooled = hpo["studies"][family]["best_tuned"]["summary"]
    if pooled["pooled_absolute_error"] != prior_pooled["pooled_absolute_error"]:
        raise ValueError("Tuned LightGBM pooled absolute error differs from HPO")
    if abs(pooled["pooled_wape"] - prior_pooled["pooled_wape"]) > 1e-12:
        raise ValueError("Tuned LightGBM pooled WAPE differs from HPO")


def build_result(all_folds: dict, hpo: dict, family: str = "LightGBM") -> dict:
    if set(all_folds) != set(WEIGHTING_CONFIGURATIONS):
        raise ValueError("All four predeclared configurations are required")
    assert_reference_reproduced(all_folds["reference"], hpo, family)
    summaries = {name: ms.summarize(folds) for name, folds in all_folds.items()}
    reference = summaries["reference"]
    best = min(WEIGHTING_CONFIGURATIONS[1:],
               key=lambda name: (summaries[name]["pooled_wape"],
                                 summaries[name]["fold_wape_range"]))
    best_folds = all_folds[best]
    reference_folds = all_folds["reference"]
    fold_delta = {spec[0]: candidate["wape"] - baseline["wape"]
                  for spec, candidate, baseline in zip(ms.FOLDS, best_folds, reference_folds, strict=True)}
    route_delta = {
        str(route): summaries[best]["per_route"][str(route)]["wape"] -
        reference["per_route"][str(route)]["wape"]
        for route in ms.ROUTES if reference["per_route"][str(route)]["wape"] is not None
    }
    pooled_delta = summaries[best]["pooled_wape"] - reference["pooled_wape"]
    if pooled_delta >= 0:
        classification = "RECENCY_WEIGHTING_REJECTED"
    elif all(delta <= 0 for delta in fold_delta.values()) and max(route_delta.values()) <= ROUTE_DEGRADATION_THRESHOLD:
        classification = "RECENCY_WEIGHTING_SUPPORTED"
    else:
        classification = "RECENCY_WEIGHTING_MIXED"
    return {
        "experiment": "RECENCY_WEIGHTING_CONTROLLED",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {
            path.relative_to(ms.ROOT).as_posix(): ms.sha256(path)
            for path in (ms.DATA_PATH, ms.JAN_AUG_PATH, ms.SEP_OCT_PATH,
                         HPO_PATH, Path(ms.__file__), Path(__file__))
        },
        "environment": {"python": platform.python_version(), "pandas": pd.__version__,
                        "numpy": np.__version__, "lightgbm": lightgbm.__version__,
                        "xgboost": xgboost.__version__},
        "model": family, "model_parameters": model_contract(hpo, family),
        "feature_configuration": CONFIGURATION,
        "features": list(ms.FEATURE_CONFIGURATIONS[CONFIGURATION]),
        "categorical_features": list(ms.CATEGORICAL),
        "folds": [{"name": f[0], "train_period": [f[1], f[2]],
                   "validation_period": [f[3], f[4]]} for f in ms.FOLDS],
        "weighting_configurations": {
            "reference": "sample_weight=None",
            "fixed": "age<=30:1.00; 31-60:0.95; 61-120:0.85; >120:0.70",
            "exponential_120": "exp(-ln(2)*age_days/120)",
            "exponential_180": "exp(-ln(2)*age_days/180)",
        },
        "weight_origin": "max(date) of each fold train, computed independently",
        "postprocessing": "floor(max(raw_prediction, 0) + 0.5); route 5 = 0",
        "all_folds": all_folds, "summaries": summaries,
        "best_weighting": best,
        "best_delta_pooled_wape": pooled_delta,
        "best_fold_delta_wape": fold_delta,
        "best_route_delta_pooled_wape": route_delta,
        "route_degradation_threshold": ROUTE_DEGRADATION_THRESHOLD,
        "classification_rule": (
            "SUPPORTED if pooled WAPE improves, every fold does not worsen, and no route worsens "
            "by more than 0.01 absolute WAPE; REJECTED if no candidate improves pooled WAPE; "
            "otherwise MIXED"
        ),
        "classification": classification,
        "nov_dec_used": False, "final_fit_performed": False,
        "accepted_feature_registry_changed": False,
    }


def save_result(result: dict) -> None:
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8")


def run_experiment(family: str = "LightGBM", artifact: Path = ARTIFACT) -> dict:
    _, folds, hpo = load_inputs(family)
    parameters = model_contract(hpo, family)
    all_folds = {"reference": evaluate_configuration(folds, "reference", parameters, family)}
    assert_reference_reproduced(all_folds["reference"], hpo, family)
    for name in WEIGHTING_CONFIGURATIONS[1:]:
        all_folds[name] = evaluate_configuration(folds, name, parameters, family)
    result = build_result(all_folds, hpo, family)
    artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run_experiment()
    for name in WEIGHTING_CONFIGURATIONS:
        print(f"{name}: pooled WAPE={result['summaries'][name]['pooled_wape']:.6f}")
    print(f"Best: {result['best_weighting']}; classification: {result['classification']}")
    print(f"Saved: {ARTIFACT.relative_to(ms.ROOT).as_posix()}")
