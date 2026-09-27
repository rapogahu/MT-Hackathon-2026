"""Shared, fixed model-selection logic for the CLI and notebook."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import catboost
import lightgbm
import numpy as np
import pandas as pd
import xgboost
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor

from calendar_temporal_stability import CATEGORIES, FLAGS, FOLDS, ROUTES
from feature_experiment_runner import BASE_FEATURES, MODEL_PARAMETERS, RESULTS, ROOT
from weather_climatology_experiment import BUCKET_LABELS

DATA_PATH = ROOT / "data/processed/model_ready_train_2025_jan_oct.csv"
JAN_AUG_PATH = ROOT / "data/processed/model_ready_train_2025_jan_aug.csv"
SEP_OCT_PATH = ROOT / "data/processed/model_ready_validation_2025_sep_oct.csv"
REFERENCE_WEATHER = RESULTS / "weather_temperature_bucket_final.json"
REFERENCE_CALENDAR_WEATHER = RESULTS / "pilot_model_v3_controlled.json"
ARTIFACT = RESULTS / "model_selection.json"

SET_FEATURES = BASE_FEATURES
CALENDAR_FEATURES = FLAGS
WEATHER_FEATURES = ("temperature_bucket",)
FEATURE_CONFIGURATIONS = {
    "weather_only": SET_FEATURES + WEATHER_FEATURES,
    "calendar_weather": SET_FEATURES + CALENDAR_FEATURES + WEATHER_FEATURES,
}
FAMILIES = ("LightGBM", "CatBoostRegressor", "XGBRegressor")
CATEGORICAL = SET_FEATURES[:-1] + WEATHER_FEATURES
BUCKET_DTYPE = pd.CategoricalDtype(categories=BUCKET_LABELS, ordered=True)
CATBOOST_PARAMETERS = {
    "iterations": 300, "depth": 6, "learning_rate": 0.1,
    "loss_function": "MAE", "random_seed": 42, "thread_count": 4,
    "verbose": False, "allow_writing_files": False,
}
XGBOOST_PARAMETERS = {
    "objective": "reg:absoluteerror", "n_estimators": 300,
    "max_depth": 6, "learning_rate": 0.1, "tree_method": "hist",
    "enable_categorical": True, "random_state": 42, "n_jobs": 4,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_data() -> pd.DataFrame:
    rows = pd.read_csv(DATA_PATH, sep=";", parse_dates=["date"],
                       dtype={"temperature_bucket": BUCKET_DTYPE})
    expected_columns = {"route", "date", "hour", "boardings", *SET_FEATURES,
                        *CALENDAR_FEATURES, "temperature_bucket"}
    if not expected_columns.issubset(rows.columns):
        raise ValueError("Model-ready columns are missing")
    if len(rows) != 72_960 or rows.duplicated(["route", "date", "hour"]).any():
        raise ValueError("Model-ready grid changed")
    if rows.date.min() != pd.Timestamp("2025-01-01") or rows.date.max() != pd.Timestamp("2025-10-31"):
        raise ValueError("Model-ready dates changed")
    if rows.isna().any().any() or set(rows.route) != set(ROUTES):
        raise ValueError("Missing values or route coverage changed")
    if not rows.groupby(["route", "date"]).hour.nunique().eq(24).all():
        raise ValueError("Incomplete route-day hours")
    if not rows.loc[rows.route.eq(5), "boardings"].eq(0).all():
        raise ValueError("Route 5 target contract changed")
    # The two published historical CSVs must reproduce the same Jan-Oct table.
    for path, mask in ((JAN_AUG_PATH, rows.date.le("2025-08-31")),
                       (SEP_OCT_PATH, rows.date.ge("2025-09-01"))):
        part = pd.read_csv(path, sep=";", parse_dates=["date"],
                           dtype={"temperature_bucket": BUCKET_DTYPE})
        if not part.equals(rows.loc[mask].reset_index(drop=True)):
            raise ValueError(f"Model-ready historical partitions differ: {path.name}")
    return rows


def make_fold(rows: pd.DataFrame, fold: tuple[str, str, str, str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    name, train_start, train_end, valid_start, valid_end = fold
    train = rows.loc[rows.date.between(train_start, train_end)].reset_index(drop=True)
    valid = rows.loc[rows.date.between(valid_start, valid_end)].reset_index(drop=True)
    for subset, start, end in ((train, train_start, train_end),
                               (valid, valid_start, valid_end)):
        if len(subset) != len(ROUTES) * len(pd.date_range(start, end)) * 24:
            raise ValueError(f"Incomplete fold {name}")
    if train.date.max() >= valid.date.min():
        raise ValueError(f"Temporal overlap in {name}")
    return train, valid


def make_features(rows: pd.DataFrame, configuration: str, family: str) -> pd.DataFrame:
    feature_names = FEATURE_CONFIGURATIONS[configuration]
    x = rows.loc[:, list(feature_names)].copy()
    for column in SET_FEATURES[:-1]:
        x[column] = pd.Categorical(x[column], categories=CATEGORIES[column])
    x["temperature_bucket"] = x["temperature_bucket"].astype(BUCKET_DTYPE)
    if x.isna().any().any():
        raise ValueError("Unknown or missing feature category")
    for column in feature_names:
        if column not in CATEGORICAL:
            x[column] = x[column].astype("int8")
    if family == "CatBoostRegressor":
        # CatBoost expects category tokens; strings preserve the same labels.
        for column in CATEGORICAL:
            x[column] = x[column].astype(str)
    return x


def fit_predict(train: pd.DataFrame, valid: pd.DataFrame,
                configuration: str, family: str,
                parameters: dict | None = None) -> tuple[np.ndarray, float, float]:
    x_train = make_features(train, configuration, family)
    x_valid = make_features(valid, configuration, family)
    if list(x_train.columns) != list(FEATURE_CONFIGURATIONS[configuration]):
        raise ValueError("Feature set order changed")
    if family == "LightGBM":
        model = LGBMRegressor(**(MODEL_PARAMETERS if parameters is None else parameters))
        fit_options = {"categorical_feature": list(CATEGORICAL)}
    elif family == "CatBoostRegressor":
        model = CatBoostRegressor(**(CATBOOST_PARAMETERS if parameters is None else parameters))
        fit_options = {"cat_features": list(CATEGORICAL)}
    elif family == "XGBRegressor":
        model = XGBRegressor(**(XGBOOST_PARAMETERS if parameters is None else parameters))
        fit_options = {}
    else:
        raise ValueError(f"Unknown model family: {family}")
    start = perf_counter()
    model.fit(x_train, train.boardings, **fit_options)
    train_seconds = perf_counter() - start
    start = perf_counter()
    raw = model.predict(x_valid)
    inference_seconds = perf_counter() - start
    prediction = np.floor(np.maximum(raw, 0) + 0.5).astype("int64")
    prediction[valid.route.to_numpy() == 5] = 0
    return prediction, train_seconds, inference_seconds


def measure(actual: np.ndarray, predicted: np.ndarray, routes: np.ndarray) -> dict:
    absolute_error = np.abs(actual - predicted)
    actual_sum = int(actual.sum())
    if actual_sum <= 0:
        raise ValueError("WAPE denominator is zero")
    route_metrics = {}
    for route in ROUTES:
        mask = routes == route
        route_actual = int(actual[mask].sum())
        route_error = int(absolute_error[mask].sum())
        route_metrics[str(route)] = {
            "actual_sum": route_actual, "absolute_error": route_error,
            "wape": route_error / route_actual if route_actual else None,
        }
    error_sum = int(absolute_error.sum())
    return {"actual_sum": actual_sum, "absolute_error": error_sum,
            "wape": error_sum / actual_sum,
            "wape_score": max(0.0, 1.0 - error_sum / actual_sum),
            "per_route": route_metrics}


def evaluate_fold(train: pd.DataFrame, valid: pd.DataFrame,
                  configuration: str, family: str,
                  parameters: dict | None = None) -> dict:
    prediction, train_seconds, inference_seconds = fit_predict(
        train, valid, configuration, family, parameters)
    if not (prediction[valid.route.to_numpy() == 5] == 0).all():
        raise ValueError("Route 5 prediction policy failed")
    result = measure(valid.boardings.to_numpy(dtype="int64"), prediction,
                     valid.route.to_numpy())
    result["train_seconds"] = train_seconds
    result["inference_seconds"] = inference_seconds
    return result


def check_lightgbm_reference(results: dict) -> dict:
    weather = json.loads(REFERENCE_WEATHER.read_text(encoding="utf-8"))
    calendar_weather = json.loads(REFERENCE_CALENDAR_WEATHER.read_text(encoding="utf-8"))
    checks = {}
    for configuration, reference, key in (
        ("weather_only", weather, "bucket_wape"),
        ("calendar_weather", calendar_weather, "pilot_v3"),
    ):
        differences = {}
        for current, prior in zip(results[configuration], reference["folds"], strict=True):
            expected = prior[key] if key == "bucket_wape" else prior["variants"][key]["wape"]
            difference = abs(current["wape"] - expected)
            differences[prior["fold"]] = difference
            if difference > 1e-12:
                raise ValueError(f"LightGBM reference mismatch: {configuration}, {prior['fold']}, delta={difference}")
        checks[configuration] = differences
    return checks


def summarize(fold_results: list[dict]) -> dict:
    actual_sum = sum(f["actual_sum"] for f in fold_results)
    error_sum = sum(f["absolute_error"] for f in fold_results)
    fold_wapes = [f["wape"] for f in fold_results]
    per_route = {}
    for route in ROUTES:
        actual = sum(f["per_route"][str(route)]["actual_sum"] for f in fold_results)
        error = sum(f["per_route"][str(route)]["absolute_error"] for f in fold_results)
        per_route[str(route)] = {"actual_sum": actual, "absolute_error": error,
                                 "wape": error / actual if actual else None}
    return {
        "pooled_actual_sum": actual_sum, "pooled_absolute_error": error_sum,
        "pooled_wape": error_sum / actual_sum,
        "wape_score": max(0.0, 1.0 - error_sum / actual_sum),
        "mean_wape": float(np.mean(fold_wapes)),
        "median_wape": float(np.median(fold_wapes)),
        "fold_wape_range": max(fold_wapes) - min(fold_wapes),
        "train_seconds": sum(f["train_seconds"] for f in fold_results),
        "inference_seconds": sum(f["inference_seconds"] for f in fold_results),
        "per_route": per_route,
    }


def build_result(all_results: dict, reference_checks: dict) -> dict:
    summaries = {family: {config: summarize(all_results[family][config])
                          for config in FEATURE_CONFIGURATIONS} for family in FAMILIES}
    ranking = sorted(((family, config) for family in FAMILIES for config in FEATURE_CONFIGURATIONS),
                     key=lambda pair: (summaries[pair[0]][pair[1]]["pooled_wape"],
                                       summaries[pair[0]][pair[1]]["fold_wape_range"]))
    reference_routes = summaries["LightGBM"]["calendar_weather"]["per_route"]
    selected_route_deltas = {}
    for family, config in ranking[:2]:
        route_metrics = summaries[family][config]["per_route"]
        selected_route_deltas[f"{family}/{config}"] = {
            route: route_metrics[route]["wape"] - reference_routes[route]["wape"]
            for route in reference_routes if reference_routes[route]["wape"] is not None
        }
    return {
        "experiment": "MODEL_SELECTION", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_sha256": sha256(Path(__file__)),
        "data_sha256": {p.relative_to(ROOT).as_posix(): sha256(p)
                        for p in (DATA_PATH, JAN_AUG_PATH, SEP_OCT_PATH)},
        "reference_sha256": {p.relative_to(ROOT).as_posix(): sha256(p)
                             for p in (REFERENCE_WEATHER, REFERENCE_CALENDAR_WEATHER)},
        "features": {name: list(value) for name, value in FEATURE_CONFIGURATIONS.items()},
        "categorical_features": list(CATEGORICAL),
        "preprocessing": {
            "LightGBM": "fixed pandas categories and LightGBM categorical_feature",
            "CatBoostRegressor": "same category labels as strings and CatBoost cat_features",
            "XGBRegressor": "fixed pandas categories and native categorical hist splits",
        },
        "parameters": {"LightGBM": MODEL_PARAMETERS, "CatBoostRegressor": CATBOOST_PARAMETERS,
                       "XGBRegressor": XGBOOST_PARAMETERS},
        "folds": [{"name": f[0], "train_period": [f[1], f[2]],
                   "validation_period": [f[3], f[4]]} for f in FOLDS],
        "postprocessing": "floor(max(raw_prediction, 0) + 0.5); route 5 = 0",
        "lightgbm_reference_max_abs_wape_delta": reference_checks,
        "results": all_results, "summaries": summaries,
        "ranking_by_pooled_wape": [{"family": a, "configuration": b} for a, b in ranking],
        "hpo_candidates": [{"family": a, "configuration": b} for a, b in ranking[:2]],
        "selection_criteria": "pooled WAPE first, fold stability second, route degradation review third",
        "selected_pooled_route_wape_delta_vs_lightgbm_calendar_weather": selected_route_deltas,
        "nov_dec_used": False, "hpo_performed": False,
        "environment": {"python": platform.python_version(), "pandas": pd.__version__,
                        "numpy": np.__version__, "lightgbm": lightgbm.__version__,
                        "catboost": catboost.__version__, "xgboost": xgboost.__version__},
    }


def save_result(result: dict) -> None:
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8")


def run_selection() -> dict:
    rows = load_data()
    folds = [make_fold(rows, fold) for fold in FOLDS]
    all_results = {family: {} for family in FAMILIES}
    for config in FEATURE_CONFIGURATIONS:
        all_results["LightGBM"][config] = [evaluate_fold(train, valid, config, "LightGBM")
                                                 for train, valid in folds]
    checks = check_lightgbm_reference(all_results["LightGBM"])
    for family in FAMILIES[1:]:
        for config in FEATURE_CONFIGURATIONS:
            all_results[family][config] = [evaluate_fold(train, valid, config, family)
                                           for train, valid in folds]
    result = build_result(all_results, checks)
    save_result(result)
    return result


if __name__ == "__main__":
    result = run_selection()
    for item in result["ranking_by_pooled_wape"]:
        family, config = item.values()
        summary = result["summaries"][family][config]
        print(f"{family} {config}: pooled WAPE={summary['pooled_wape']:.6f}, "
              f"fold range={summary['fold_wape_range']:.6f}")
    print(f"Saved {ARTIFACT.relative_to(ROOT).as_posix()}")
