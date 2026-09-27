"""One-off controlled global versus per-route LightGBM architecture comparison."""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm
from lightgbm import LGBMRegressor

from feature_experiment_runner import (
    BASE_FEATURES, MODEL_PARAMETERS, RESULTS, ROUTES, TRAIN_END, TRAIN_LABELS,
    TRAIN_START, VALID_END, VALID_LABELS, VALID_START, _fit_predict, _label_grid,
    calendar_features, wape,
)


LOCAL_FEATURES = ("weekday", "hour", "hour_weekend", "is_night")
CATEGORICAL_FEATURES = ("weekday", "hour", "hour_weekend")
ARTIFACT = RESULTS / "route_specific_lightgbm_v1.json"
STABILITY_ARTIFACT = RESULTS / "route_specific_lightgbm_temporal_stability.json"
HISTORY_PERIOD_ARTIFACT = RESULTS / "route_specific_history_vs_period.json"
DECOMPOSITION_ARTIFACT = RESULTS / "route_specific_may_aug_sep_oct_decomposition.json"
PREDICTIONS_ARTIFACT = RESULTS / "route_specific_may_aug_sep_oct_predictions.csv.gz"
EARLY_DECOMPOSITION_ARTIFACT = RESULTS / "route_specific_early_holdouts_decomposition.json"
FOLDS = (
    ("fold_1", "2025-01-01", "2025-04-30", "2025-05-01", "2025-06-30", TRAIN_LABELS),
    ("fold_2", "2025-01-01", "2025-06-30", "2025-07-01", "2025-08-31", TRAIN_LABELS),
    ("fold_3", TRAIN_START, TRAIN_END, VALID_START, VALID_END, VALID_LABELS),
)


def run_fold(
    fold: str, train_start: str, train_end: str,
    validation_start: str, validation_end: str, validation_labels: Path,
    *, return_predictions: bool = False,
) -> dict | tuple[dict, pd.DataFrame]:
    train = _label_grid(TRAIN_LABELS, train_start, train_end)
    validation = _label_grid(validation_labels, validation_start, validation_end)
    assert len(train) == len(ROUTES) * len(pd.date_range(train_start, train_end)) * 24
    assert len(validation) == len(ROUTES) * len(pd.date_range(validation_start, validation_end)) * 24
    assert train["date"].max() < validation["date"].min()
    assert train["date"].min() == pd.Timestamp(train_start)
    assert validation["date"].max() == pd.Timestamp(validation_end)
    assert not train.duplicated(["route", "date", "hour"]).any()
    assert not validation.duplicated(["route", "date", "hour"]).any()

    print(f"{fold}: global features: {', '.join(BASE_FEATURES)}", flush=True)
    print(f"{fold}: route-specific features: {', '.join(LOCAL_FEATURES)}", flush=True)
    print("Excluded route: constant within route; route_hour: equivalent to hour within route.", flush=True)

    # Validation targets remain separate from both model feature matrices.
    validation_keys = validation[["route", "date", "hour"]]
    baseline, baseline_features = _fit_predict(train, validation_keys)
    actual = validation["boardings"].to_numpy(dtype=float)
    baseline_wape = wape(actual, baseline)
    if fold == "fold_3" and abs(baseline_wape - 0.12357994025785918) >= 1e-10:
        raise ValueError(f"Global baseline contract mismatch: {baseline_wape}")
    train_features = calendar_features(train)
    validation_features = calendar_features(validation_keys)
    candidate = np.zeros(len(validation), dtype=float)
    fitted_routes = []
    for route in ROUTES:
        if route == 5:
            continue
        train_mask = train["route"].eq(route).to_numpy()
        valid_mask = validation_keys["route"].eq(route).to_numpy()
        model = LGBMRegressor(**MODEL_PARAMETERS)
        model.fit(
            train_features.loc[train_mask, LOCAL_FEATURES],
            train.loc[train_mask, "boardings"],
            categorical_feature=list(CATEGORICAL_FEATURES),
        )
        raw = model.predict(validation_features.loc[valid_mask, LOCAL_FEATURES])
        candidate[valid_mask] = np.floor(np.maximum(raw, 0) + 0.5)
        fitted_routes.append(int(route))

    candidate_wape = wape(actual, candidate)
    if fold == "fold_3" and ARTIFACT.exists():
        reference = json.loads(ARTIFACT.read_text(encoding="utf-8"))["metrics"]
        if abs(candidate_wape - reference["candidate_wape"]) >= 1e-10:
            raise ValueError(f"Fold 3 candidate contract mismatch: {candidate_wape}")
    assert np.all(baseline[validation_keys["route"].eq(5)] == 0)
    assert np.all(candidate[validation_keys["route"].eq(5)] == 0)
    denominator = float(np.abs(actual).sum())
    per_route = {}
    for route in ROUTES:
        mask = validation_keys["route"].eq(route).to_numpy()
        route_actual = actual[mask]
        baseline_error = float(np.abs(route_actual - baseline[mask]).sum())
        candidate_error = float(np.abs(route_actual - candidate[mask]).sum())
        route_denominator = float(np.abs(route_actual).sum())
        per_route[str(route)] = {
            "baseline_wape": wape(route_actual, baseline[mask]) if route_denominator else None,
            "candidate_wape": wape(route_actual, candidate[mask]) if route_denominator else None,
            "actual_boardings": route_denominator,
            "baseline_absolute_error": baseline_error,
            "candidate_absolute_error": candidate_error,
            "delta_absolute_error": candidate_error - baseline_error,
            "delta_overall_wape_contribution": (candidate_error - baseline_error) / denominator,
        }
    assert abs(sum(v["delta_overall_wape_contribution"] for v in per_route.values()) - (candidate_wape - baseline_wape)) < 1e-12
    scored = [values for values in per_route.values() if values["baseline_wape"] is not None]
    wins = sum(values["candidate_wape"] < values["baseline_wape"] for values in scored)
    losses = sum(values["candidate_wape"] > values["baseline_wape"] for values in scored)

    result = {
        "fold": fold,
        "experiment_class": "model_architecture",
        "name": "route_specific_lightgbm_v1",
        "data_sources": [str(TRAIN_LABELS.relative_to(Path(__file__).resolve().parents[2])), str(validation_labels.relative_to(Path(__file__).resolve().parents[2]))],
        "grid_rows": {"train": len(train), "validation": len(validation)},
        "periods": {"train": [train_start, train_end], "validation": [validation_start, validation_end]},
        "baseline_features": list(baseline_features),
        "candidate_features": list(LOCAL_FEATURES),
        "candidate_categorical_features": list(CATEGORICAL_FEATURES),
        "model_parameters": MODEL_PARAMETERS,
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "lightgbm": lightgbm.__version__},
        "fitted_routes": fitted_routes,
        "route_5_prediction": 0,
        "postprocessing": "floor(max(raw_prediction, 0) + 0.5)",
        "metrics": {
            "baseline_wape": baseline_wape,
            "candidate_wape": candidate_wape,
            "delta_wape_absolute": candidate_wape - baseline_wape,
            "delta_wape_relative": (candidate_wape - baseline_wape) / baseline_wape,
            "baseline_wape_score": max(0.0, 1.0 - baseline_wape),
            "candidate_wape_score": max(0.0, 1.0 - candidate_wape),
            "total_actual_boardings": denominator,
            "routes_improved": wins,
            "routes_worsened": losses,
        },
        "per_route": per_route,
        "decision": None,
    }
    if return_predictions:
        predictions = validation_keys.copy()
        predictions["actual_boardings"] = actual
        predictions["global_prediction"] = baseline.astype("int64")
        predictions["route_specific_prediction"] = candidate.astype("int64")
        return result, predictions
    return result


def run_temporal_stability() -> dict:
    folds = [run_fold(*configuration) for configuration in FOLDS]
    reference = json.loads(ARTIFACT.read_text(encoding="utf-8"))["metrics"]
    fold_3 = folds[2]["metrics"]
    for metric in ("baseline_wape", "candidate_wape"):
        if abs(fold_3[metric] - reference[metric]) >= 1e-10:
            raise ValueError(f"Fold 3 does not reproduce stored {metric}")
    deltas = np.array([fold["metrics"]["delta_wape_absolute"] for fold in folds])
    pooled_actual = sum(fold["metrics"]["total_actual_boardings"] for fold in folds)
    pooled_global_error = sum(
        sum(route["baseline_absolute_error"] for route in fold["per_route"].values())
        for fold in folds
    )
    pooled_local_error = sum(
        sum(route["candidate_absolute_error"] for route in fold["per_route"].values())
        for fold in folds
    )
    result = {
        "experiment_class": "model_architecture_temporal_stability",
        "name": "route_specific_lightgbm_temporal_stability",
        "reference_artifact": ARTIFACT.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
        "fold_3_reference_reproduced": True,
        "folds": folds,
        "aggregate": {
            "mean_delta_wape": float(deltas.mean()),
            "median_delta_wape": float(np.median(deltas)),
            "folds_route_specific_wins": int((deltas < 0).sum()),
            "pooled_actual_boardings": pooled_actual,
            "pooled_global_absolute_error": pooled_global_error,
            "pooled_route_specific_absolute_error": pooled_local_error,
            "pooled_global_wape": pooled_global_error / pooled_actual,
            "pooled_route_specific_wape": pooled_local_error / pooled_actual,
        },
        "decision": None,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    STABILITY_ARTIFACT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact": str(STABILITY_ARTIFACT),
        "folds": [{"fold": fold["fold"], "metrics": fold["metrics"]} for fold in folds],
        "aggregate": result["aggregate"],
    }, indent=2))
    return result


def target_shift_diagnostics(configuration: tuple) -> dict:
    """Describe target-level changes after fitting; never feed these to a model."""
    _, train_start, train_end, validation_start, validation_end, validation_labels = configuration
    train = _label_grid(TRAIN_LABELS, train_start, train_end)
    validation = _label_grid(validation_labels, validation_start, validation_end)
    diagnostics = {}
    for route in ROUTES:
        train_route = train.loc[train["route"].eq(route)]
        valid_route = validation.loc[validation["route"].eq(route)]
        train_mean = float(train_route["boardings"].mean())
        valid_mean = float(valid_route["boardings"].mean())
        levels = {}
        for name, weekend in (("weekday", False), ("weekend", True)):
            train_part = train_route.loc[train_route["date"].dt.weekday.ge(5).eq(weekend)]
            valid_part = valid_route.loc[valid_route["date"].dt.weekday.ge(5).eq(weekend)]
            previous = float(train_part["boardings"].mean())
            current = float(valid_part["boardings"].mean())
            levels[name] = {
                "train_mean": previous,
                "validation_mean": current,
                "change": current - previous,
                "relative_change": (current / previous - 1) if previous else None,
            }
        diagnostics[str(route)] = {
            "train_rows": len(train_route),
            "train_days": train_route["date"].nunique(),
            "train_mean_target": train_mean,
            "validation_mean_target": valid_mean,
            "mean_target_change": valid_mean - train_mean,
            "mean_target_relative_change": (valid_mean / train_mean - 1) if train_mean else None,
            "weekday_weekend": levels,
        }
    return diagnostics


def run_history_vs_period() -> dict:
    """Reuse known folds and fit only three missing architecture comparisons."""
    previous = json.loads(STABILITY_ARTIFACT.read_text(encoding="utf-8"))
    reference_fold_1, reference_fold_3 = previous["folds"][0], previous["folds"][2]
    configurations = {
        "jan_apr_may_jun": FOLDS[0],
        "mar_jun_jul_aug": ("mar_jun_jul_aug", "2025-03-01", "2025-06-30", "2025-07-01", "2025-08-31", TRAIN_LABELS),
        "may_aug_sep_oct": ("may_aug_sep_oct", "2025-05-01", "2025-08-31", VALID_START, VALID_END, VALID_LABELS),
        "mar_aug_sep_oct": ("mar_aug_sep_oct", "2025-03-01", "2025-08-31", VALID_START, VALID_END, VALID_LABELS),
        "jan_aug_sep_oct": FOLDS[2],
    }
    runs = {
        "jan_apr_may_jun": reference_fold_1,
        "mar_jun_jul_aug": run_fold(*configurations["mar_jun_jul_aug"]),
        "may_aug_sep_oct": run_fold(*configurations["may_aug_sep_oct"]),
        "mar_aug_sep_oct": run_fold(*configurations["mar_aug_sep_oct"]),
        "jan_aug_sep_oct": reference_fold_3,
    }
    for name, run in runs.items():
        _, train_start, train_end, validation_start, validation_end, _ = configurations[name]
        if run["periods"] != {"train": [train_start, train_end], "validation": [validation_start, validation_end]}:
            raise ValueError(f"Stored period mismatch for {name}")
        run["target_shift_diagnostics"] = target_shift_diagnostics(configurations[name])
    reference = json.loads(ARTIFACT.read_text(encoding="utf-8"))["metrics"]
    for metric in ("baseline_wape", "candidate_wape"):
        if abs(runs["jan_aug_sep_oct"]["metrics"][metric] - reference[metric]) >= 1e-10:
            raise ValueError(f"Stored Sep-Oct reference mismatch: {metric}")
    result = {
        "experiment_class": "model_architecture_history_vs_period_diagnostic",
        "name": "route_specific_history_vs_period",
        "reference_artifacts": [
            STABILITY_ARTIFACT.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
            ARTIFACT.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
        ],
        "comparisons": {
            "fixed_four_month_windows": ["jan_apr_may_jun", "mar_jun_jul_aug", "may_aug_sep_oct"],
            "sep_oct_history_lengths": ["may_aug_sep_oct", "mar_aug_sep_oct", "jan_aug_sep_oct"],
        },
        "runs": runs,
        "decision": None,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    HISTORY_PERIOD_ARTIFACT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact": str(HISTORY_PERIOD_ARTIFACT),
        "runs": {name: run["metrics"] for name, run in runs.items()},
    }, indent=2))
    return result


def slice_metrics(rows: pd.DataFrame) -> dict:
    """Calculate the frozen WAPE and absolute-error metrics on existing predictions."""
    actual = rows["actual_boardings"].to_numpy(dtype=float)
    global_pred = rows["global_prediction"].to_numpy(dtype=float)
    local_pred = rows["route_specific_prediction"].to_numpy(dtype=float)
    denominator = float(np.abs(actual).sum())
    global_error = float(np.abs(actual - global_pred).sum())
    local_error = float(np.abs(actual - local_pred).sum())
    return {
        "rows": len(rows),
        "actual_boardings": denominator,
        "global_wape": global_error / denominator if denominator else None,
        "route_specific_wape": local_error / denominator if denominator else None,
        "delta_wape": (local_error - global_error) / denominator if denominator else None,
        "global_absolute_error": global_error,
        "route_specific_absolute_error": local_error,
        "delta_absolute_error": local_error - global_error,
    }


def decompose_time_slices(predictions: pd.DataFrame, validation_start: str, validation_end: str) -> dict:
    """Apply the same month, seven-day, route-month, and route-week slicing."""
    predictions["month"] = predictions["date"].dt.strftime("%Y-%m")
    predictions["week_number"] = (
        (predictions["date"] - pd.Timestamp(validation_start)).dt.days // 7 + 1
    )
    by_month = {month: slice_metrics(part) for month, part in predictions.groupby("month", sort=True)}
    by_week = {}
    for week, part in predictions.groupby("week_number", sort=True):
        first = pd.Timestamp(validation_start) + pd.Timedelta(days=7 * (int(week) - 1))
        last = min(first + pd.Timedelta(days=6), pd.Timestamp(validation_end))
        by_week[f"week_{int(week):02d}"] = {
            "start": first.strftime("%Y-%m-%d"),
            "end": last.strftime("%Y-%m-%d"),
            **slice_metrics(part),
        }
    route_month = {
        str(route): {month: slice_metrics(part) for month, part in route_rows.groupby("month", sort=True)}
        for route, route_rows in predictions.groupby("route", sort=True)
    }
    route_week = {
        str(route): {f"week_{int(week):02d}": slice_metrics(part)
                     for week, part in route_rows.groupby("week_number", sort=True)}
        for route, route_rows in predictions.groupby("route", sort=True)
    }
    result = {
        "week_definition": f"Consecutive seven-day buckets from {validation_start}; final bucket may be shorter",
        "overall": slice_metrics(predictions),
        "month": by_month,
        "week": by_week,
        "route_month": route_month,
        "route_week": route_week,
    }
    assert sum(item["delta_absolute_error"] for item in by_month.values()) == result["overall"]["delta_absolute_error"]
    assert sum(item["delta_absolute_error"] for item in by_week.values()) == result["overall"]["delta_absolute_error"]
    return result


def run_may_aug_decomposition() -> dict:
    """Refit the exact stored run once and split its validated predictions by time."""
    reference = json.loads(HISTORY_PERIOD_ARTIFACT.read_text(encoding="utf-8"))["runs"]["may_aug_sep_oct"]
    configuration = (
        "may_aug_sep_oct", "2025-05-01", "2025-08-31", VALID_START, VALID_END, VALID_LABELS
    )
    run, predictions = run_fold(*configuration, return_predictions=True)
    for metric in ("baseline_wape", "candidate_wape"):
        if abs(run["metrics"][metric] - reference["metrics"][metric]) >= 1e-10:
            raise ValueError(f"May-Aug reference mismatch: {metric}")
    for route in ROUTES:
        current = run["per_route"][str(route)]
        stored = reference["per_route"][str(route)]
        for metric in ("baseline_absolute_error", "candidate_absolute_error"):
            if current[metric] != stored[metric]:
                raise ValueError(f"May-Aug route {route} reference mismatch: {metric}")

    slices = decompose_time_slices(predictions, VALID_START, VALID_END)
    by_month, by_week = slices["month"], slices["week"]
    route_month, route_week = slices["route_month"], slices["route_week"]
    route_50 = predictions.loc[predictions["route"].eq(50)]
    route_50_periods = {
        "sep_1_5_weekdays": slice_metrics(route_50.loc[route_50["date"].lt(pd.Timestamp("2025-09-06"))]),
        "sep_6_30": slice_metrics(route_50.loc[route_50["date"].between("2025-09-06", "2025-09-30")]),
        "october": slice_metrics(route_50.loc[route_50["month"].eq("2025-10")]),
        "sep_6_onward_weekdays": slice_metrics(route_50.loc[route_50["date"].ge(pd.Timestamp("2025-09-06")) & route_50["date"].dt.weekday.lt(5)]),
        "sep_6_onward_weekends": slice_metrics(route_50.loc[route_50["date"].ge(pd.Timestamp("2025-09-06")) & route_50["date"].dt.weekday.ge(5)]),
    }
    assert abs(sum(item["delta_absolute_error"] for item in by_month.values()) - run["metrics"]["total_actual_boardings"] * run["metrics"]["delta_wape_absolute"]) < 1e-8
    assert sum(item["delta_absolute_error"] for item in by_week.values()) == sum(item["delta_absolute_error"] for item in by_month.values())

    result = {
        "experiment_class": "model_architecture_prediction_decomposition",
        "name": "route_specific_may_aug_sep_oct_decomposition",
        "reference_artifact": HISTORY_PERIOD_ARTIFACT.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
        "reference_reproduced": True,
        "run_periods": run["periods"],
        "feature_names": {"global": run["baseline_features"], "route_specific": run["candidate_features"]},
        "model_parameters": MODEL_PARAMETERS,
        "postprocessing": run["postprocessing"],
        "route_5_prediction": 0,
        "week_definition": "Consecutive seven-day buckets from 2025-09-01; final bucket has five days",
        "overall": slice_metrics(predictions),
        "early_september_weekdays": slice_metrics(
            predictions.loc[predictions["date"].lt(pd.Timestamp("2025-09-06"))]
        ),
        "month": by_month,
        "week": by_week,
        "route_month": route_month,
        "route_week": route_week,
        "route_50_breakpoint_diagnostics": route_50_periods,
        "decision": None,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    predictions[["route", "date", "hour", "global_prediction", "route_specific_prediction"]].to_csv(
        PREDICTIONS_ARTIFACT, sep=";", index=False, date_format="%Y-%m-%d", compression="gzip"
    )
    result["predictions_artifact"] = PREDICTIONS_ARTIFACT.relative_to(Path(__file__).resolve().parents[2]).as_posix()
    DECOMPOSITION_ARTIFACT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact": str(DECOMPOSITION_ARTIFACT),
        "overall": result["overall"],
        "month": by_month,
        "week": by_week,
        "route_50_breakpoint_diagnostics": route_50_periods,
    }, indent=2))
    return result


def run_early_decompositions() -> dict:
    """Reproduce each stored early run once, then slice the resulting predictions."""
    stored = json.loads(HISTORY_PERIOD_ARTIFACT.read_text(encoding="utf-8"))["runs"]
    configurations = {
        "jan_apr_may_jun": FOLDS[0],
        "mar_jun_jul_aug": (
            "mar_jun_jul_aug", "2025-03-01", "2025-06-30",
            "2025-07-01", "2025-08-31", TRAIN_LABELS,
        ),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    decompositions = {}
    for name, configuration in configurations.items():
        _, _, _, validation_start, validation_end, validation_labels = configuration
        reference = stored[name]
        prediction_artifact = RESULTS / f"route_specific_{name}_predictions.csv.gz"
        if prediction_artifact.exists():
            predictions = pd.read_csv(prediction_artifact, sep=";", parse_dates=["date"])
            validation = _label_grid(validation_labels, validation_start, validation_end)
            if not predictions[["route", "date", "hour"]].equals(validation[["route", "date", "hour"]]):
                raise ValueError(f"Stored prediction keys differ from canonical grid: {name}")
            predictions["actual_boardings"] = validation["boardings"].to_numpy(dtype=float)
        else:
            _, predictions = run_fold(*configuration, return_predictions=True)

        overall = slice_metrics(predictions)
        if abs(overall["global_wape"] - reference["metrics"]["baseline_wape"]) >= 1e-10:
            raise ValueError(f"Global reference mismatch: {name}")
        if abs(overall["route_specific_wape"] - reference["metrics"]["candidate_wape"]) >= 1e-10:
            raise ValueError(f"Route-specific reference mismatch: {name}")
        for route in ROUTES:
            current = slice_metrics(predictions.loc[predictions["route"].eq(route)])
            saved = reference["per_route"][str(route)]
            if current["global_absolute_error"] != saved["baseline_absolute_error"]:
                raise ValueError(f"Global route {route} mismatch: {name}")
            if current["route_specific_absolute_error"] != saved["candidate_absolute_error"]:
                raise ValueError(f"Route-specific route {route} mismatch: {name}")
        if not prediction_artifact.exists():
            predictions[["route", "date", "hour", "global_prediction", "route_specific_prediction"]].to_csv(
                prediction_artifact, sep=";", index=False, date_format="%Y-%m-%d", compression="gzip"
            )
        decomposition = decompose_time_slices(predictions, validation_start, validation_end)
        decompositions[name] = {
            "periods": reference["periods"],
            "reference_reproduced": True,
            "predictions_artifact": prediction_artifact.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
            **decomposition,
        }

    result = {
        "experiment_class": "model_architecture_prediction_decomposition",
        "name": "route_specific_early_holdouts_decomposition",
        "reference_artifact": HISTORY_PERIOD_ARTIFACT.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
        "sep_oct_decomposition_artifact": DECOMPOSITION_ARTIFACT.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
        "feature_names": {
            "global": list(BASE_FEATURES), "route_specific": list(LOCAL_FEATURES),
        },
        "model_parameters": MODEL_PARAMETERS,
        "postprocessing": "floor(max(raw_prediction, 0) + 0.5)",
        "route_5_prediction": 0,
        "runs": decompositions,
        "decision": None,
    }
    EARLY_DECOMPOSITION_ARTIFACT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact": str(EARLY_DECOMPOSITION_ARTIFACT),
        "runs": {name: {"overall": run["overall"], "month": run["month"], "week": run["week"]}
                 for name, run in decompositions.items()},
    }, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--temporal-stability", action="store_true", help="Run the three fixed expanding-window folds")
    modes.add_argument("--history-vs-period", action="store_true", help="Compare fixed history and fixed validation windows")
    modes.add_argument("--decompose-may-aug-sep-oct", action="store_true", help="Refit the stored run once and decompose predictions by time")
    modes.add_argument("--decompose-early-holdouts", action="store_true", help="Reproduce and slice the two early architecture runs")
    args = parser.parse_args()
    if args.temporal_stability:
        run_temporal_stability()
        return
    if args.history_vs_period:
        run_history_vs_period()
        return
    if args.decompose_may_aug_sep_oct:
        run_may_aug_decomposition()
        return
    if args.decompose_early_holdouts:
        run_early_decompositions()
        return
    result = run_fold(*FOLDS[2])
    RESULTS.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(ARTIFACT), "metrics": result["metrics"], "per_route": result["per_route"]}, indent=2))


if __name__ == "__main__":
    main()
