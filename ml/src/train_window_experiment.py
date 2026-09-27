"""Controlled Pilot v5 train-window backtest on the frozen temporal folds."""

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


ARTIFACT = ms.RESULTS / "train_window_experiment.json"
REFERENCE = ms.RESULTS / "ensemble_experiment.json"
WINDOWS = ("FULL", "8m", "6m", "4m", "2m")
MONTHS = {"8m": 8, "6m": 6, "4m": 4, "2m": 2}
ROUTE_DEGRADATION_THRESHOLD = 0.01


def slice_train(train: pd.DataFrame, window: str) -> pd.DataFrame:
    if window not in WINDOWS:
        raise ValueError(f"Unknown train window: {window}")
    if window == "FULL":
        return train
    end_month = train.date.max().to_period("M")
    first_month = end_month - (MONTHS[window] - 1)
    sliced = train.loc[train.date.dt.to_period("M") >= first_month].reset_index(drop=True)
    if sliced.empty or sliced.date.max() != train.date.max():
        raise ValueError("Invalid train window")
    return sliced


def evaluate(train: pd.DataFrame, valid: pd.DataFrame, parameters: dict) -> dict:
    # The input is already trimmed; the origin and all weights come from this input.
    weights, weight_info = rw.sample_weights(train, "exponential_180")
    x_train = ms.make_features(train, rw.CONFIGURATION, "XGBRegressor")
    x_valid = ms.make_features(valid, rw.CONFIGURATION, "XGBRegressor")
    if x_train.columns.tolist() != list(ms.FEATURE_CONFIGURATIONS[rw.CONFIGURATION]):
        raise ValueError("Feature order changed")
    model = XGBRegressor(**parameters)
    started = perf_counter()
    model.fit(x_train, train.boardings, sample_weight=weights)
    fit_seconds = perf_counter() - started
    started = perf_counter()
    raw = np.asarray(model.predict(x_valid), dtype="float64")
    predict_seconds = perf_counter() - started
    if len(raw) != len(valid) or not np.isfinite(raw).all():
        raise ValueError("Invalid raw prediction")
    prediction = np.floor(np.maximum(raw, 0) + 0.5).astype("int64")
    prediction[valid.route.to_numpy() == 5] = 0
    metrics = ms.measure(valid.boardings.to_numpy(dtype="int64"), prediction,
                         valid.route.to_numpy())
    if metrics["per_route"]["5"]["absolute_error"] != 0:
        raise ValueError("Route 5 prediction policy failed")
    metrics.update({
        "first_train_date": train.date.min().strftime("%Y-%m-%d"),
        "last_train_date": train.date.max().strftime("%Y-%m-%d"),
        "train_rows": len(train),
        "min_weight": weight_info["min_weight"],
        "mean_weight": weight_info["mean_weight"],
        "max_weight": weight_info["max_weight"],
        "effective_weight_sum": float(weights.sum()),
        "train_seconds": fit_seconds,
        "inference_seconds": predict_seconds,
    })
    return metrics


def check_full(folds: list[dict]) -> None:
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    previous = reference["fold_metrics"]["1.0"]
    for index, (current, prior) in enumerate(zip(folds, previous, strict=True)):
        if (current["actual_sum"] != prior["actual_sum"] or
                current["absolute_error"] != prior["absolute_error"]):
            raise ValueError(f"FULL reference mismatch on fold {index + 1}")
        for route in ms.ROUTES:
            key = str(route)
            if current["per_route"][key]["absolute_error"] != prior["per_route"][key]["absolute_error"]:
                raise ValueError(f"FULL route mismatch on fold {index + 1}, route {key}")
    if ms.summarize(folds)["pooled_absolute_error"] != reference["summaries"]["1.0"]["pooled_absolute_error"]:
        raise ValueError("FULL pooled reference mismatch")


def run_experiment() -> dict:
    _, folds, hpo = rw.load_inputs("XGBRegressor")
    parameters = rw.model_contract(hpo, "XGBRegressor")
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if reference["source_sha256"][ms.DATA_PATH.relative_to(ms.ROOT).as_posix()] != ms.sha256(ms.DATA_PATH):
        raise ValueError("Ensemble reference data changed")
    if reference["parameters"]["XGBRegressor"] != parameters:
        raise ValueError("Ensemble reference parameters changed")

    fold_results = {window: [] for window in WINDOWS}
    for train, valid in folds:
        fold_results["FULL"].append(evaluate(train, valid, parameters))
    check_full(fold_results["FULL"])

    fold_details = []
    for spec, (train, valid), full_result in zip(ms.FOLDS, folds, fold_results["FULL"], strict=True):
        cache = {train.date.min(): full_result}
        detail = {"fold": spec[0], "windows": {"FULL": "FULL"}}
        for window in WINDOWS[1:]:
            sliced = slice_train(train, window)
            first = sliced.date.min()
            if first not in cache:
                cache[first] = evaluate(sliced, valid, parameters)
            fold_results[window].append(cache[first])
            detail["windows"][window] = "FULL" if first == train.date.min() else f"{first:%Y-%m-%d} to {train.date.max():%Y-%m-%d}"
        fold_details.append(detail)

    summaries = {window: ms.summarize(metrics) for window, metrics in fold_results.items()}
    full = summaries["FULL"]
    comparisons = {}
    for window in WINDOWS[1:]:
        current = summaries[window]
        fold_delta = {spec[0]: candidate["wape"] - baseline["wape"]
                      for spec, candidate, baseline in zip(ms.FOLDS, fold_results[window],
                                                           fold_results["FULL"], strict=True)}
        route_delta = {str(route): current["per_route"][str(route)]["wape"] - full["per_route"][str(route)]["wape"]
                       for route in ms.ROUTES if full["per_route"][str(route)]["wape"] is not None}
        comparisons[window] = {
            "delta_pooled_wape": current["pooled_wape"] - full["pooled_wape"],
            "fold_delta_wape": fold_delta,
            "fold_wins": sum(delta < 0 for delta in fold_delta.values()),
            "fold_losses": sum(delta > 0 for delta in fold_delta.values()),
            "route_delta_pooled_wape": route_delta,
            "train_rows_ratio_by_fold": {spec[0]: candidate["train_rows"] / baseline["train_rows"]
                                         for spec, candidate, baseline in zip(ms.FOLDS, fold_results[window],
                                                                              fold_results["FULL"], strict=True)},
        }
    shorter = [window for window in WINDOWS[1:]
               if any(candidate["train_rows"] < baseline["train_rows"]
                      for candidate, baseline in zip(fold_results[window], fold_results["FULL"], strict=True))]
    if not shorter:
        raise ValueError("No genuinely shorter window was evaluated")
    best = min(shorter, key=lambda window: (summaries[window]["pooled_wape"], -MONTHS[window]))
    candidate = comparisons[best]
    if candidate["delta_pooled_wape"] >= 0:
        classification = "TRAIN_WINDOW_REJECTED"
    elif candidate["fold_wins"] >= 2 and max(candidate["route_delta_pooled_wape"].values()) <= ROUTE_DEGRADATION_THRESHOLD:
        classification = "TRAIN_WINDOW_SUPPORTED"
    else:
        classification = "TRAIN_WINDOW_MIXED"
    source_paths = (ms.DATA_PATH, ms.JAN_AUG_PATH, ms.SEP_OCT_PATH, rw.HPO_PATH,
                    REFERENCE, Path(ms.__file__), Path(rw.__file__), Path(__file__))
    result = {
        "experiment": "PILOT_V5_TRAIN_WINDOW_CONTROLLED",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {path.relative_to(ms.ROOT).as_posix(): ms.sha256(path) for path in source_paths},
        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                        "pandas": pd.__version__, "xgboost": xgboost.__version__},
        "features": list(ms.FEATURE_CONFIGURATIONS[rw.CONFIGURATION]),
        "categorical_features": list(ms.CATEGORICAL),
        "parameters": parameters,
        "weighting": "exp(-ln(2) * age_days / 180); origin=max(sliced fold train date)",
        "postprocessing": "floor(max(raw, 0) + 0.5); route 5 = 0",
        "folds": [{"name": f[0], "train_period": [f[1], f[2]], "validation_period": [f[3], f[4]]} for f in ms.FOLDS],
        "windows": list(WINDOWS), "fold_details": fold_details,
        "fold_results": fold_results, "summaries": summaries,
        "comparisons_vs_full": comparisons, "best_shorter_window": best,
        "classification": classification,
        "classification_rule": "SUPPORTED if best shorter window improves pooled WAPE, wins at least two folds, and no route worsens by more than 0.01 absolute WAPE; REJECTED if no pooled gain; otherwise MIXED",
        "full_reference_reproduced": True,
        "nov_dec_used": False, "final_fit_performed": False,
        "accepted_feature_registry_changed": False,
    }
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run_experiment()
    for window in WINDOWS:
        print(f"{window}: pooled WAPE={result['summaries'][window]['pooled_wape']:.6f}")
    print(f"Best shorter window={result['best_shorter_window']}; {result['classification']}")
