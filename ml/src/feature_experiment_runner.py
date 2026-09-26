"""Small controlled harness for temporal feature experiments."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_features import (  # noqa: E402
    H19_NAME, H20_NAME, H21_NAME, H22_NAME, H23_NAME, H24_NAME, RouteWeekdayHourHistoricalMedian,
    RouteWeekdayHourHistoricalMean, MedianLast4SameWeekdayHour, MeanLast4SameWeekdayHour,
    RouteRecent4WeekMean, RoutePrevious4WeekMean,
)

TRAIN_LABELS = ROOT / "data/raw/labels/labels_day_train.csv"
VALID_LABELS = ROOT / "data/raw/labels/labels_day_test.csv"
RESULTS = ROOT / "ml/experiments/results"
ROUTES = (1, 5, 7, 11, 12, 17, 25, 26, 28, 50)
BASE_FEATURES = ("route", "weekday", "hour", "route_hour", "hour_weekend", "is_night")
TRAIN_START, TRAIN_END = "2025-01-01", "2025-08-31"
VALID_START, VALID_END = "2025-09-01", "2025-10-31"
MODEL_PARAMETERS = {
    "objective": "regression_l1", "n_estimators": 300, "max_depth": 6,
    "num_leaves": 31, "learning_rate": 0.1, "random_state": 42,
    "n_jobs": 4, "verbosity": -1,
}


def _label_grid(path: Path, start: str, end: str) -> pd.DataFrame:
    labels = pd.read_csv(path, sep=";", parse_dates=["date"])
    required = {"route", "date", "hour", "boardings"}
    if not required.issubset(labels.columns):
        raise ValueError(f"{path.name} missing required label columns")
    if labels.duplicated(["route", "date", "hour"]).any():
        raise ValueError(f"Duplicate canonical label keys in {path.name}")
    dates = pd.date_range(start, end, freq="D")
    index = pd.MultiIndex.from_product([ROUTES, dates, range(24)], names=["route", "date", "hour"])
    sparse = labels.set_index(["route", "date", "hour"])["boardings"]
    grid = sparse.reindex(index, fill_value=0).rename("boardings").reset_index()
    if len(grid) != len(ROUTES) * len(dates) * 24:
        raise ValueError("Unexpected canonical grid size")
    return grid


def calendar_features(rows: pd.DataFrame) -> pd.DataFrame:
    weekday = rows["date"].dt.weekday
    features = pd.DataFrame(index=rows.index)
    features["route"] = pd.Categorical(rows["route"], categories=ROUTES)
    features["weekday"] = pd.Categorical(weekday, categories=range(7))
    features["hour"] = pd.Categorical(rows["hour"], categories=range(24))
    route_hour_categories = [route * 24 + hour for route in ROUTES for hour in range(24)]
    features["route_hour"] = pd.Categorical(
        rows["route"] * 24 + rows["hour"], categories=route_hour_categories
    )
    features["hour_weekend"] = pd.Categorical(rows["hour"] * 2 + (weekday >= 5).astype(int), categories=range(48))
    features["is_night"] = (rows["hour"].isin(range(6))).astype("int8")
    return features.loc[:, BASE_FEATURES]


def wape(actual: np.ndarray, prediction: np.ndarray) -> float:
    denominator = float(np.abs(actual).sum())
    return float(np.abs(actual - prediction).sum() / denominator) if denominator else float("nan")


def _fit_predict(train: pd.DataFrame, valid: pd.DataFrame, candidate_name: str | None = None):
    x_train, x_valid = calendar_features(train), calendar_features(valid)
    if candidate_name:
        train_candidate = train[candidate_name].astype(float)
        valid_candidate = valid[candidate_name].astype(float)
        x_train[candidate_name] = train_candidate
        x_valid[candidate_name] = valid_candidate
    features = list(x_train.columns)
    model = LGBMRegressor(**MODEL_PARAMETERS)
    model.fit(x_train, train["boardings"], categorical_feature=list(BASE_FEATURES[:-1]))
    pred = np.floor(np.maximum(model.predict(x_valid), 0) + 0.5)
    pred[valid["route"].to_numpy() == 5] = 0
    return pred, features


def run_experiment(experiment: str = "SMOKE", candidate_builder=None, candidate_name: str | None = None) -> dict:
    train = _label_grid(TRAIN_LABELS, TRAIN_START, TRAIN_END)
    valid = _label_grid(VALID_LABELS, VALID_START, VALID_END)
    if train["date"].max() != pd.Timestamp(TRAIN_END) or valid["date"].min() != pd.Timestamp(VALID_START):
        raise ValueError("Temporal boundary contract failed")
    if train["date"].max() >= valid["date"].min():
        raise ValueError("Train/validation overlap")

    history = train[["route", "date", "hour", "boardings"]].copy()
    # Candidate construction has distinct train and frozen-validation entry points.
    if candidate_builder is not None:
        if not candidate_name or candidate_name in BASE_FEATURES:
            raise ValueError("Candidate needs a distinct feature name")
        train[candidate_name] = candidate_builder.build_train(
            train[["route", "date", "hour"]], history
        )
        valid[candidate_name] = candidate_builder.build_validation(
            valid[["route", "date", "hour"]], history.copy()
        )
        if train.loc[train["route"].eq(5), candidate_name].notna().any() or valid.loc[
            valid["route"].eq(5), candidate_name
        ].notna().any():
            raise ValueError("Route 5 cannot receive an ordinary historical target feature")

    baseline_pred, baseline_features = _fit_predict(train, valid)
    candidate_pred, candidate_features = (
        _fit_predict(train, valid, candidate_name) if candidate_name else (baseline_pred.copy(), baseline_features)
    )
    actual = valid["boardings"].to_numpy(dtype=float)
    base_wape, candidate_wape = wape(actual, baseline_pred), wape(actual, candidate_pred)

    def route_wapes(pred):
        return {str(int(route)): (lambda value: value if np.isfinite(value) else None)(
                    wape(group["boardings"].to_numpy(dtype=float), pred[group.index.to_numpy()]))
                for route, group in valid.groupby("route", sort=True)}

    coverage = float(valid[candidate_name].notna().mean()) if candidate_name else 1.0
    feature_diagnostics = None
    history_observation_counts = None
    historical_day_diagnostics = None
    frozen_route_levels = None
    if candidate_name:
        feature_diagnostics = {}
        for split_name, frame in (("train", train), ("validation", valid)):
            series = frame[candidate_name]
            eligible = frame["route"].ne(5)
            observed = series.dropna()
            quantiles = observed.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
            feature_diagnostics[split_name] = {
                "non_null": int(series.notna().sum()),
                "nan_count": int(series.isna().sum()),
                "coverage_all_routes": float(series.notna().mean()),
                "coverage_excluding_route_5": float(series.loc[eligible].notna().mean()),
                "route_5_nan_count": int(series.loc[~eligible].isna().sum()),
                "distribution": {
                    "min": float(observed.min()), "p05": float(quantiles.loc[0.05]),
                    "p25": float(quantiles.loc[0.25]), "median": float(quantiles.loc[0.5]),
                    "p75": float(quantiles.loc[0.75]), "p95": float(quantiles.loc[0.95]),
                    "max": float(observed.max()), "mean": float(observed.mean()),
                },
            }
        if hasattr(candidate_builder, "history_counts"):
            counts_by_split = candidate_builder.history_counts(
                train[["route", "date", "hour"]], valid[["route", "date", "hour"]], history
            )
            history_observation_counts = {}
            for split_name, frame in (("train", train), ("validation", valid)):
                counts = counts_by_split[split_name]
                if not counts.index.equals(frame.index) or not counts.between(0, 4).all():
                    raise ValueError("Invalid historical observation counts")
                if not counts.gt(0).equals(frame[candidate_name].notna()):
                    raise ValueError("Feature coverage disagrees with historical observation counts")
                eligible_counts = counts.loc[frame["route"].ne(5)]
                history_observation_counts[split_name] = {
                    "all_routes": {
                        str(i): {"rows": int((counts == i).sum()),
                                 "fraction": float((counts == i).mean())} for i in range(5)
                    },
                    "excluding_route_5": {
                        str(i): {"rows": int((eligible_counts == i).sum()),
                                 "fraction": float((eligible_counts == i).mean())} for i in range(5)
                    },
                }
        if hasattr(candidate_builder, "history_days"):
            days_by_split = candidate_builder.history_days(
                train[["route", "date", "hour"]], valid[["route", "date", "hour"]], history
            )
            historical_day_diagnostics = {}
            for split_name, frame in (("train", train), ("validation", valid)):
                days = days_by_split[split_name]
                if not days.index.equals(frame.index) or not days.between(0, 28).all():
                    raise ValueError("Invalid historical day counts")
                if not days.gt(0).equals(frame[candidate_name].notna()):
                    raise ValueError("Feature coverage disagrees with historical day counts")
                historical_day_diagnostics[split_name] = {
                    "rows_by_available_days": {str(i): int((days == i).sum()) for i in range(29)},
                    "zero_days": int(days.eq(0).sum()),
                    "partial_1_to_27_days": int(days.between(1, 27).sum()),
                    "full_28_days": int(days.eq(28).sum()),
                    "mean_days_all_routes": float(days.mean()),
                    "mean_days_excluding_route_5": float(days.loc[frame["route"].ne(5)].mean()),
                }
            frozen_route_levels = candidate_builder.frozen_route_levels(history)
    result = {
        "experiment": experiment,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_sources": ["data/raw/labels/labels_day_train.csv", "data/raw/labels/labels_day_test.csv"],
        "grid_rows": {"train": len(train), "validation": len(valid)},
        "periods": {"train": [TRAIN_START, TRAIN_END], "validation": [VALID_START, VALID_END]},
        "temporal_boundary_passed": bool(train["date"].max() < valid["date"].min()),
        "model_parameters": MODEL_PARAMETERS,
        "baseline_feature_names": baseline_features,
        "candidate_feature_names": candidate_features,
        "metrics": {
            "baseline_overall_wape": base_wape, "candidate_overall_wape": candidate_wape,
            "delta_wape": candidate_wape - base_wape,
            "wape_score": max(0.0, 1.0 - candidate_wape),
            "baseline_per_route_wape": route_wapes(baseline_pred),
            "candidate_per_route_wape": route_wapes(candidate_pred),
            "candidate_coverage": coverage, "candidate_nan_rate": 1.0 - coverage,
        },
        "candidate_diagnostics": feature_diagnostics,
        "history_observation_counts": history_observation_counts,
        "historical_day_diagnostics": historical_day_diagnostics,
        "frozen_route_levels": frozen_route_levels,
        "missing_value_handling": "Native LightGBM missing value; no numeric fallback" if candidate_name else None,
        "decision": None,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    destination = RESULTS / f"{experiment.lower()}_result.json"
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    result["artifact"] = destination.relative_to(ROOT).as_posix()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default="SMOKE", help="Experiment ID; SMOKE runs accepted features only")
    args = parser.parse_args()
    experiment = args.experiment.upper()
    if experiment == "SMOKE":
        result = run_experiment(experiment)
    elif experiment == "H19":
        result = run_experiment(experiment, RouteWeekdayHourHistoricalMedian, H19_NAME)
    elif experiment == "H20":
        result = run_experiment(experiment, RouteWeekdayHourHistoricalMean, H20_NAME)
    elif experiment == "H21":
        result = run_experiment(experiment, MedianLast4SameWeekdayHour, H21_NAME)
    elif experiment == "H22":
        result = run_experiment(experiment, MeanLast4SameWeekdayHour, H22_NAME)
    elif experiment == "H23":
        result = run_experiment(experiment, RouteRecent4WeekMean, H23_NAME)
    elif experiment == "H24":
        result = run_experiment(experiment, RoutePrevious4WeekMean, H24_NAME)
    else:
        parser.error(f"No candidate builder registered for {experiment}")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
