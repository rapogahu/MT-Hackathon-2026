"""Controlled holiday-position feature groups against the frozen Pilot v5."""

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

import interaction_features_experiment as reference
import model_selection as ms
import recency_weighting_experiment as rw
from calendar_temporal_stability import CALENDAR_PATH, REGISTRY_PATH, FLAGS


ARTIFACT = ms.RESULTS / "holiday_distance_experiment.json"
GROUPS = {
    "holiday_distance": ("days_to_next_holiday", "days_since_prev_holiday"),
    "pre_post_flags": ("is_pre_holiday_1d", "is_post_holiday_1d",
                       "is_pre_holiday_3d", "is_post_holiday_3d"),
    "long_holiday_period": ("is_long_holiday_period",),
}
DISTANCE_DTYPE = pd.CategoricalDtype(categories=[str(i) for i in range(8)] + [">7"])


def load_calendar() -> pd.DataFrame:
    calendar = pd.read_csv(CALENDAR_PATH, parse_dates=["date", "known_from"])
    registry = pd.read_csv(REGISTRY_PATH, parse_dates=["date", "known_from"])
    if len(calendar) != 365 or calendar.date.duplicated().any() or not calendar.date.equals(
        pd.Series(pd.date_range("2025-01-01", "2025-12-31"), name="date")
    ):
        raise ValueError("Calendar must cover each day of 2025 exactly once")
    event = calendar.is_official_holiday.eq(1) | calendar.is_transferred_day_off.eq(1)
    if calendar.loc[event, "known_from"].isna().any():
        raise ValueError("Holiday event has unknown availability")
    transfers = registry.loc[registry.availability_type.eq("annual_decree") & registry.is_transfer.eq(1)]
    if len(transfers) != 6 or not transfers.known_from.eq(pd.Timestamp("2024-10-04")).all():
        raise ValueError("Transfer decree provenance changed")
    for fold in ms.FOLDS:
        origin = pd.Timestamp(fold[2])
        if calendar.known_from.dropna().gt(origin).any():
            raise ValueError(f"Calendar unavailable at {fold[0]} forecast origin")
    return calendar


def calendar_features(calendar: pd.DataFrame) -> pd.DataFrame:
    dates = calendar.date.to_numpy(dtype="datetime64[D]")
    event = (calendar.is_official_holiday.eq(1) | calendar.is_transferred_day_off.eq(1)).to_numpy()
    event_dates = dates[event]
    if not len(event_dates):
        raise ValueError("No official holiday events")
    next_index = np.searchsorted(event_dates, dates, side="left")
    prev_index = np.searchsorted(event_dates, dates, side="right") - 1
    to_next = np.full(len(dates), 8, dtype="int8")
    since_prev = np.full(len(dates), 8, dtype="int8")
    available_next = next_index < len(event_dates)
    available_prev = prev_index >= 0
    to_next[available_next] = np.minimum(
        (event_dates[next_index[available_next]] - dates[available_next]).astype(int), 8)
    since_prev[available_prev] = np.minimum(
        (dates[available_prev] - event_dates[prev_index[available_prev]]).astype(int), 8)

    # A long period is a run of at least three consecutive official days off.
    # The source's is_day_off includes statutory holidays, transfers and weekends.
    off = calendar.is_day_off.eq(1).to_numpy()
    boundaries = np.r_[0, np.flatnonzero(off[1:] != off[:-1]) + 1, len(off)]
    long_period = np.zeros(len(off), dtype="int8")
    for start, stop in zip(boundaries[:-1], boundaries[1:], strict=True):
        if off[start] and stop - start >= 3:
            long_period[start:stop] = 1
    return pd.DataFrame({
        "date": calendar.date,
        "days_to_next_holiday": [str(x) if x < 8 else ">7" for x in to_next],
        "days_since_prev_holiday": [str(x) if x < 8 else ">7" for x in since_prev],
        "is_pre_holiday_1d": (to_next == 1).astype("int8"),
        "is_post_holiday_1d": (since_prev == 1).astype("int8"),
        "is_pre_holiday_3d": ((to_next >= 1) & (to_next <= 3)).astype("int8"),
        "is_post_holiday_3d": ((since_prev >= 1) & (since_prev <= 3)).astype("int8"),
        "is_long_holiday_period": long_period,
    })


def attach(rows: pd.DataFrame, calendar: pd.DataFrame, derived: pd.DataFrame) -> pd.DataFrame:
    checked = rows[["date", *FLAGS]].merge(calendar[["date", *FLAGS]], on="date",
                                               how="left", validate="many_to_one",
                                               suffixes=("_model", "_source"), indicator=True)
    if checked._merge.ne("both").any():
        raise ValueError("Calendar does not cover model-ready rows")
    for flag in FLAGS:
        if not checked[f"{flag}_model"].equals(checked[f"{flag}_source"]):
            raise ValueError(f"Calendar source differs from model-ready {flag}")
    result = rows.merge(derived, on="date", how="left", validate="many_to_one", sort=False)
    if len(result) != len(rows) or result[list(derived.columns[1:])].isna().any().any():
        raise ValueError("Derived calendar coverage differs")
    return result


def make_features(rows: pd.DataFrame, extra: tuple[str, ...]) -> pd.DataFrame:
    features = ms.make_features(rows, rw.CONFIGURATION, "XGBRegressor")
    for name in extra:
        if name.startswith("days_"):
            features[name] = pd.Categorical(rows[name], dtype=DISTANCE_DTYPE)
        else:
            features[name] = rows[name].astype("int8")
    if features.isna().any().any() or features.columns.tolist() != [*ms.FEATURE_CONFIGURATIONS[rw.CONFIGURATION], *extra]:
        raise ValueError("Feature contract changed")
    return features


def evaluate(train: pd.DataFrame, valid: pd.DataFrame, parameters: dict,
             extra: tuple[str, ...]) -> dict:
    weights, info = rw.sample_weights(train, "exponential_180")
    x_train, x_valid = make_features(train, extra), make_features(valid, extra)
    model = XGBRegressor(**parameters)
    started = perf_counter()
    model.fit(x_train, train.boardings, sample_weight=weights)
    fit_seconds = perf_counter() - started
    started = perf_counter()
    raw = np.asarray(model.predict(x_valid), dtype="float64")
    predict_seconds = perf_counter() - started
    if not np.isfinite(raw).all() or len(raw) != len(valid):
        raise ValueError("Invalid prediction")
    prediction = np.floor(np.maximum(raw, 0) + 0.5).astype("int64")
    prediction[valid.route.to_numpy() == 5] = 0
    metrics = ms.measure(valid.boardings.to_numpy(dtype="int64"), prediction,
                         valid.route.to_numpy())
    metrics.update({"train_seconds": fit_seconds, "inference_seconds": predict_seconds,
                    "train_rows": len(train), "validation_rows": len(valid),
                    "weight_origin": info["origin"]})
    return metrics


def compare(current: list[dict], baseline: list[dict]) -> dict:
    summary, base = ms.summarize(current), ms.summarize(baseline)
    fold_delta = {spec[0]: a["wape"] - b["wape"]
                  for spec, a, b in zip(ms.FOLDS, current, baseline, strict=True)}
    route_delta = {key: summary["per_route"][key]["wape"] - value["wape"]
                   for key, value in base["per_route"].items() if value["wape"] is not None}
    delta = summary["pooled_wape"] - base["pooled_wape"]
    wins = sum(value < 0 for value in fold_delta.values())
    return {"delta_pooled_wape": delta, "delta_pooled_absolute_error":
            summary["pooled_absolute_error"] - base["pooled_absolute_error"],
            "fold_delta_wape": fold_delta, "fold_wins": wins,
            "route_delta_pooled_wape": route_delta,
            "decision": "REJECTED" if delta >= 0 else "SUPPORTED" if wins >= 2 else "MIXED"}


def run_experiment() -> dict:
    rows, _, hpo = rw.load_inputs("XGBRegressor")
    parameters = rw.model_contract(hpo, "XGBRegressor")
    previous = json.loads(reference.REFERENCE.read_text(encoding="utf-8"))
    data_key = ms.DATA_PATH.relative_to(ms.ROOT).as_posix()
    if previous["source_sha256"][data_key] != ms.sha256(ms.DATA_PATH) or previous["parameters"]["XGBRegressor"] != parameters:
        raise ValueError("Pilot v5 source or parameters changed")
    calendar = load_calendar()
    enriched = attach(rows, calendar, calendar_features(calendar))
    folds = [ms.make_fold(enriched, spec) for spec in ms.FOLDS]
    configurations = {"Pilot v5": ()} | GROUPS
    results = {"Pilot v5": [evaluate(train, valid, parameters, ()) for train, valid in folds]}
    reference.check_reference(results["Pilot v5"], previous)
    comparisons = {}
    for name, extra in GROUPS.items():
        results[name] = [evaluate(train, valid, parameters, extra) for train, valid in folds]
        comparisons[name] = compare(results[name], results["Pilot v5"])
    supported = tuple(name for name in GROUPS if comparisons[name]["decision"] == "SUPPORTED")
    if len(supported) >= 2:
        extra = tuple(feature for name in supported for feature in GROUPS[name])
        configurations["combined_supported"] = extra
        results["combined_supported"] = [evaluate(train, valid, parameters, extra) for train, valid in folds]
        comparisons["combined_supported"] = compare(results["combined_supported"], results["Pilot v5"])
    paths = (ms.DATA_PATH, ms.JAN_AUG_PATH, ms.SEP_OCT_PATH, rw.HPO_PATH,
             reference.REFERENCE, CALENDAR_PATH, REGISTRY_PATH, Path(ms.__file__),
             Path(rw.__file__), Path(reference.__file__), Path(__file__))
    result = {
        "experiment": "PILOT_V5_HOLIDAY_POSITION", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {p.relative_to(ms.ROOT).as_posix(): ms.sha256(p) for p in paths},
        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                        "pandas": pd.__version__, "xgboost": xgboost.__version__},
        "target": "boardings", "observation_unit": ["route", "date", "hour"],
        "base_features": list(ms.FEATURE_CONFIGURATIONS[rw.CONFIGURATION]),
        "configurations": {name: list(extra) for name, extra in configurations.items()},
        "distance_categories": DISTANCE_DTYPE.categories.tolist(),
        "event_definition": "is_official_holiday OR is_transferred_day_off",
        "long_period_definition": "at least 3 consecutive is_day_off dates in calendar_2025_ml.csv",
        "calendar_boundary": "Distances beyond 2025 calendar are >7; runs are bounded by source year",
        "parameters": parameters, "weighting": "exp(-ln(2) * age_days / 180); origin=max(fold train date)",
        "postprocessing": "floor(max(raw, 0) + 0.5); route 5 = 0",
        "folds": [{"name": f[0], "train_period": [f[1], f[2]], "validation_period": [f[3], f[4]]} for f in ms.FOLDS],
        "fold_results": results, "summaries": {name: ms.summarize(metrics) for name, metrics in results.items()},
        "comparisons_vs_pilot_v5": comparisons,
        "classification_rule": "SUPPORTED: pooled WAPE improves and at least two folds win; MIXED: pooled gain in one fold; REJECTED: no pooled gain",
        "reference_reproduced": True, "calendar_known_by_all_origins": True,
        "nov_dec_used": False, "final_fit_performed": False, "accepted_feature_registry_changed": False,
    }
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run_experiment()
    for name, summary in result["summaries"].items():
        decision = result["comparisons_vs_pilot_v5"].get(name, {}).get("decision", "REFERENCE")
        print(f"{name}: pooled WAPE={summary['pooled_wape']:.6f}; {decision}")
