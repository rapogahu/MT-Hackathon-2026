"""Final fixed-group calendar ablation on the three established temporal folds."""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone

import lightgbm
import numpy as np
import pandas as pd

from calendar_temporal_stability import (
    CALENDAR_PATH, FOLDS, FLAGS, REGISTRY_PATH, ROOT, ROUTES, TRAIN_PATH,
    fit_predict, wape,
)
from feature_experiment_runner import BASE_FEATURES, MODEL_PARAMETERS, RESULTS


STABILITY_RESULT = RESULTS / "calendar_official_group_temporal_stability.json"
ARTIFACT = RESULTS / "calendar_final_ablation.json"
SPECIAL_FLAGS = FLAGS[1:]
VARIANTS = {
    "core": (),
    "day_off_only": ("is_day_off",),
    "special_calendar": SPECIAL_FLAGS,
    "all_calendar": FLAGS,
}


def main() -> None:
    data = pd.read_csv(TRAIN_PATH, sep=";", parse_dates=["date"])
    calendar = pd.read_csv(CALENDAR_PATH, parse_dates=["date", "known_from"])
    registry = pd.read_csv(REGISTRY_PATH, parse_dates=["date", "known_from"])
    previous = json.loads(STABILITY_RESULT.read_text(encoding="utf-8"))
    if len(data) != 72_960 or data.duplicated(["route", "date", "hour"]).any():
        raise ValueError("Model-ready Jan-Oct grid changed")
    if calendar["date"].duplicated().any() or data[list(FLAGS)].isna().any().any():
        raise ValueError("Calendar source or model-ready flags are invalid")
    joined = data[["date", *FLAGS]].merge(
        calendar[["date", "known_from", *FLAGS]], on="date", how="left",
        validate="many_to_one", suffixes=("_model", "_source"), indicator=True,
    )
    if joined["_merge"].ne("both").any():
        raise ValueError("Calendar does not cover every model-ready date")
    for flag in FLAGS:
        if not joined[f"{flag}_model"].equals(joined[f"{flag}_source"]):
            raise ValueError(f"Model-ready calendar values changed: {flag}")
    transfers = registry.loc[
        registry["availability_type"].eq("annual_decree") & registry["is_transfer"].eq(1)
    ]
    if len(transfers) != 6 or not transfers["known_from"].eq(pd.Timestamp("2024-10-04")).all():
        raise ValueError("2025 transfer decree provenance changed")

    folds = []
    for index, (name, train_start, train_end, valid_start, valid_end) in enumerate(FOLDS):
        train = data.loc[data["date"].between(train_start, train_end)].copy().reset_index(drop=True)
        validation = data.loc[data["date"].between(valid_start, valid_end)].copy().reset_index(drop=True)
        expected_train = len(ROUTES) * len(pd.date_range(train_start, train_end)) * 24
        expected_valid = len(ROUTES) * len(pd.date_range(valid_start, valid_end)) * 24
        if len(train) != expected_train or len(validation) != expected_valid:
            raise ValueError(f"Incomplete fold grid: {name}")
        origin = pd.Timestamp(train_end)
        selected_calendar = calendar.loc[calendar["date"].between(valid_start, valid_end)]
        known_dates = selected_calendar["known_from"].dropna()
        if not known_dates.le(origin).all() or not transfers["known_from"].le(origin).all():
            raise ValueError(f"Calendar feature unavailable at forecast origin: {name}")

        predictions = {
            variant: fit_predict(train, validation, selected_flags)
            for variant, selected_flags in VARIANTS.items()
        }
        actual = validation["boardings"].to_numpy(dtype=float)
        core_wape = wape(actual, predictions["core"])
        metrics = {}
        for variant, pred in predictions.items():
            value = wape(actual, pred)
            route_metrics = {}
            for route, group in validation.groupby("route", sort=True):
                positions = group.index.to_numpy()
                route_actual = actual[positions]
                baseline = wape(route_actual, predictions["core"][positions])
                candidate = wape(route_actual, pred[positions])
                route_metrics[str(int(route))] = {
                    "wape": candidate if np.isfinite(candidate) else None,
                    "delta_wape_vs_core": candidate - baseline if np.isfinite(baseline) else None,
                }
            metrics[variant] = {
                "wape": value,
                "delta_wape_vs_core": value - core_wape,
                "per_route": route_metrics,
            }
        prior = previous["folds"][index]
        if prior["fold"] != name:
            raise ValueError("Stability fold order changed")
        for new_name, old_name in (("core", "core_wape"), ("all_calendar", "calendar_wape")):
            if abs(metrics[new_name]["wape"] - prior["metrics"][old_name]) > 1e-12:
                raise ValueError(f"Prior {name} {new_name} WAPE not reproduced")
        folds.append({
            "fold": name,
            "train_period": [train_start, train_end],
            "validation_period": [valid_start, valid_end],
            "forecast_origin": origin.date().isoformat(),
            "rows": {"train": len(train), "validation": len(validation)},
            "availability": {
                "dated_validation_calendar_known_by_origin": True,
                "six_annual_decree_transfers_known_by_origin": True,
                "annual_transfer_known_from": "2024-10-04",
            },
            "special_validation_active_days": {
                flag: int(validation.loc[validation[flag].eq(1), "date"].nunique())
                for flag in SPECIAL_FLAGS
            },
            "day_off_validation_active_days": int(
                validation.loc[validation["is_day_off"].eq(1), "date"].nunique()
            ),
            "variants": metrics,
        })

    result = {
        "experiment": "CALENDAR_FINAL_ABLATION",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_sources": [
            TRAIN_PATH.relative_to(ROOT).as_posix(),
            CALENDAR_PATH.relative_to(ROOT).as_posix(),
            REGISTRY_PATH.relative_to(ROOT).as_posix(),
        ],
        "model_parameters": MODEL_PARAMETERS,
        "core_features": list(BASE_FEATURES),
        "variant_features": {
            key: list(BASE_FEATURES + selected_flags) for key, selected_flags in VARIANTS.items()
        },
        "categorical_features": list(BASE_FEATURES[:-1]),
        "postprocessing": "floor(max(raw_prediction, 0) + 0.5); route 5 = 0",
        "environment": {
            "python": platform.python_version(), "pandas": pd.__version__,
            "numpy": np.__version__, "lightgbm": lightgbm.__version__,
        },
        "prior_stability_results_reproduced": True,
        "folds": folds,
        "classification": "CALENDAR_CANDIDATE_ONLY",
        "decision_basis": {
            "day_off_improved_folds": sum(f["variants"]["day_off_only"]["delta_wape_vs_core"] < 0 for f in folds),
            "special_improved_folds": sum(f["variants"]["special_calendar"]["delta_wape_vs_core"] < 0 for f in folds),
            "all_improved_folds": sum(f["variants"]["all_calendar"]["delta_wape_vs_core"] < 0 for f in folds),
            "special_active_fold_delta_vs_core": folds[0]["variants"]["special_calendar"]["delta_wape_vs_core"],
            "all_vs_day_off_on_special_active_fold": (
                folds[0]["variants"]["all_calendar"]["wape"]
                - folds[0]["variants"]["day_off_only"]["wape"]
            ),
            "reason": (
                "Each calendar variant improves 2 of 3 folds and worsens Jul-Aug. "
                "Special flags improve their active fold versus core, but adding them to day_off "
                "does not improve the active fold. Inactive-fold changes show representation effects. "
                "No calendar set is accepted from this evidence."
            ),
        },
    }
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({fold["fold"]: {
        name: {"wape": entry["wape"], "delta": entry["delta_wape_vs_core"]}
        for name, entry in fold["variants"].items()
    } for fold in folds}, indent=2))


if __name__ == "__main__":
    main()
