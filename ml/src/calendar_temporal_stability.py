"""Fixed three-fold temporal stability check for the official calendar group."""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import lightgbm
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from feature_experiment_runner import BASE_FEATURES, MODEL_PARAMETERS, RESULTS, ROUTES, wape


ROOT = Path(__file__).resolve().parents[2]
TRAIN_PATH = ROOT / "data/processed/model_ready_train_2025_jan_oct.csv"
CALENDAR_PATH = ROOT / "dataset/meta features/calendar_2025_ml.csv"
REGISTRY_PATH = ROOT / "dataset/meta features/holidays_v2.csv"
PRIOR_RESULT = RESULTS / "calendar_official_group_result.json"
ARTIFACT = RESULTS / "calendar_official_group_temporal_stability.json"
FLAGS = (
    "is_day_off", "is_official_holiday", "is_transferred_day_off",
    "is_transferred_workday", "is_shortened_workday",
)
CATEGORICAL = BASE_FEATURES[:-1]
CATEGORIES = {
    "route": ROUTES,
    "weekday": tuple(range(7)),
    "hour": tuple(range(24)),
    "route_hour": tuple(route * 24 + hour for route in ROUTES for hour in range(24)),
    "hour_weekend": tuple(range(48)),
}
FOLDS = (
    ("jan_apr_to_may_jun", "2025-01-01", "2025-04-30", "2025-05-01", "2025-06-30"),
    ("jan_jun_to_jul_aug", "2025-01-01", "2025-06-30", "2025-07-01", "2025-08-31"),
    ("jan_aug_to_sep_oct", "2025-01-01", "2025-08-31", "2025-09-01", "2025-10-31"),
)


def features(rows: pd.DataFrame, calendar_flags: tuple[str, ...] = ()) -> pd.DataFrame:
    names = BASE_FEATURES + calendar_flags
    x = rows.loc[:, list(names)].copy()
    for name in CATEGORICAL:
        x[name] = pd.Categorical(x[name], categories=CATEGORIES[name])
        if x[name].isna().any():
            raise ValueError(f"Unknown category: {name}")
    for name in names:
        if name not in CATEGORICAL:
            x[name] = x[name].astype("int8")
    return x


def fit_predict(train: pd.DataFrame, validation: pd.DataFrame, calendar_flags: tuple[str, ...] = ()) -> np.ndarray:
    model = LGBMRegressor(**MODEL_PARAMETERS)
    model.fit(
        features(train, calendar_flags), train["boardings"],
        categorical_feature=list(CATEGORICAL),
    )
    prediction = np.floor(np.maximum(model.predict(features(validation, calendar_flags)), 0) + 0.5)
    prediction[validation["route"].to_numpy() == 5] = 0
    return prediction


def main() -> None:
    data = pd.read_csv(TRAIN_PATH, sep=";", parse_dates=["date"])
    calendar = pd.read_csv(CALENDAR_PATH, parse_dates=["date", "known_from"])
    registry = pd.read_csv(REGISTRY_PATH, parse_dates=["date", "known_from"])
    required = {"route", "date", "hour", "boardings", *BASE_FEATURES, *FLAGS}
    if not required.issubset(data.columns) or len(data) != 72_960:
        raise ValueError("Model-ready Jan-Oct schema or grid size changed")
    if data.duplicated(["route", "date", "hour"]).any() or calendar["date"].duplicated().any():
        raise ValueError("Duplicate model-ready or calendar keys")
    if data[list(FLAGS)].isna().any().any():
        raise ValueError("Calendar flags have missing values")
    source = data[["date", *FLAGS]].merge(
        calendar[["date", "availability_type", "known_from", *FLAGS]],
        on="date", how="left", validate="many_to_one", suffixes=("_model", "_source"),
        indicator=True,
    )
    if source["_merge"].ne("both").any():
        raise ValueError("Calendar does not cover all model-ready dates")
    for flag in FLAGS:
        if not source[f"{flag}_model"].equals(source[f"{flag}_source"]):
            raise ValueError(f"Model-ready values disagree with calendar source: {flag}")

    annual_transfers = registry.loc[
        registry["availability_type"].eq("annual_decree") & registry["is_transfer"].eq(1)
    ]
    if len(annual_transfers) != 6 or not annual_transfers["known_from"].eq(pd.Timestamp("2024-10-04")).all():
        raise ValueError("Transfer registry provenance differs from 2024-10-04 decree")
    annual_calendar = calendar.loc[calendar["availability_type"].eq("annual_decree")]
    if annual_calendar.empty or not annual_calendar["known_from"].eq(pd.Timestamp("2024-10-04")).all():
        raise ValueError("Calendar annual_decree availability is inconsistent")

    folds = []
    for name, train_start, train_end, valid_start, valid_end in FOLDS:
        train = data.loc[data["date"].between(train_start, train_end)].copy().reset_index(drop=True)
        validation = data.loc[data["date"].between(valid_start, valid_end)].copy().reset_index(drop=True)
        train_days = len(pd.date_range(train_start, train_end))
        valid_days = len(pd.date_range(valid_start, valid_end))
        if len(train) != len(ROUTES) * train_days * 24 or len(validation) != len(ROUTES) * valid_days * 24:
            raise ValueError(f"Incomplete fold grid: {name}")
        if train["date"].max() >= validation["date"].min():
            raise ValueError(f"Overlapping fold periods: {name}")

        origin = pd.Timestamp(train_end)
        validation_calendar = calendar.loc[calendar["date"].between(valid_start, valid_end)]
        dated = validation_calendar["known_from"].notna()
        if not validation_calendar.loc[dated, "known_from"].le(origin).all():
            raise ValueError(f"Calendar entry unavailable at {name} forecast origin")
        if not annual_transfers["known_from"].le(origin).all():
            raise ValueError(f"Annual transfers unavailable at {name} forecast origin")

        core_pred = fit_predict(train, validation)
        calendar_pred = fit_predict(train, validation, FLAGS)
        actual = validation["boardings"].to_numpy(dtype=float)
        core_wape = wape(actual, core_pred)
        calendar_wape = wape(actual, calendar_pred)
        route_metrics = {}
        for route, group in validation.groupby("route", sort=True):
            indices = group.index.to_numpy()
            route_actual = actual[indices]
            core_route = wape(route_actual, core_pred[indices])
            calendar_route = wape(route_actual, calendar_pred[indices])
            route_metrics[str(int(route))] = {
                "core_wape": core_route if np.isfinite(core_route) else None,
                "calendar_wape": calendar_route if np.isfinite(calendar_route) else None,
                "delta_wape": calendar_route - core_route if np.isfinite(core_route) else None,
            }
        folds.append({
            "fold": name,
            "train_period": [train_start, train_end],
            "validation_period": [valid_start, valid_end],
            "forecast_origin": origin.date().isoformat(),
            "rows": {"train": len(train), "validation": len(validation)},
            "availability": {
                "annual_transfer_registry_rows": len(annual_transfers),
                "annual_transfer_known_from": "2024-10-04",
                "all_dated_validation_calendar_entries_known_by_origin": True,
                "annual_transfers_known_by_origin": True,
            },
            "metrics": {
                "core_wape": core_wape,
                "calendar_wape": calendar_wape,
                "delta_wape": calendar_wape - core_wape,
                "core_wape_score": 1 - core_wape,
                "calendar_wape_score": 1 - calendar_wape,
                "per_route": route_metrics,
            },
            "validation_active_days": {
                flag: int(validation.loc[validation[flag].eq(1), "date"].nunique()) for flag in FLAGS
            },
        })

    previous = json.loads(PRIOR_RESULT.read_text(encoding="utf-8"))
    last = folds[-1]["metrics"]
    if abs(last["core_wape"] - previous["metrics"]["baseline_overall_wape"]) > 1e-12:
        raise ValueError("Sep-Oct core baseline was not reproduced")
    if abs(last["calendar_wape"] - previous["metrics"]["candidate_overall_wape"]) > 1e-12:
        raise ValueError("Sep-Oct official calendar result was not reproduced")

    improvements = sum(fold["metrics"]["delta_wape"] < 0 for fold in folds)
    classification = (
        "CALENDAR_STABLE" if improvements == 3 else
        "CALENDAR_HOLDOUT_SPECIFIC" if improvements == 1 else "CALENDAR_MIXED"
    )
    result = {
        "experiment": "CALENDAR_OFFICIAL_GROUP_TEMPORAL_STABILITY",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_sources": [
            TRAIN_PATH.relative_to(ROOT).as_posix(), CALENDAR_PATH.relative_to(ROOT).as_posix(),
            REGISTRY_PATH.relative_to(ROOT).as_posix(),
        ],
        "core_features": list(BASE_FEATURES),
        "calendar_group": list(FLAGS),
        "categorical_features": list(CATEGORICAL),
        "model_parameters": MODEL_PARAMETERS,
        "postprocessing": "floor(max(raw_prediction, 0) + 0.5); route 5 = 0",
        "environment": {
            "python": platform.python_version(), "pandas": pd.__version__,
            "numpy": np.__version__, "lightgbm": lightgbm.__version__,
        },
        "classification_rule": "3/3 improved: STABLE; 1/3 improved: HOLDOUT_SPECIFIC; otherwise: MIXED",
        "folds_improved": improvements,
        "classification": classification,
        "fold_3_prior_result_reproduced": True,
        "folds": folds,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"classification": classification, "folds": [
        {"fold": fold["fold"], "core_wape": fold["metrics"]["core_wape"],
         "calendar_wape": fold["metrics"]["calendar_wape"],
         "delta_wape": fold["metrics"]["delta_wape"]} for fold in folds
    ]}, indent=2))


if __name__ == "__main__":
    main()
