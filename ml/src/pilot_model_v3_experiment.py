"""Controlled v3 comparison on frozen folds, followed by diagnostic inference."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import lightgbm
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from calendar_temporal_stability import (
    CALENDAR_PATH, FLAGS, FOLDS, ROOT, ROUTES, TRAIN_PATH, features, wape,
)
from feature_experiment_runner import BASE_FEATURES, MODEL_PARAMETERS, RESULTS
from weather_climatology_experiment import (
    ARCHIVE_PATH, BUCKET_LABELS, CLIMATOLOGY_PATH, FORECAST_PATH,
    add_temperature_bucket, join_climatology, verify_climatology,
)


REFERENCE_PATH = RESULTS / "calendar_final_ablation.json"
ARTIFACT = RESULTS / "pilot_model_v3_controlled.json"
DIAGNOSTIC_PREDICTIONS = RESULTS / "pilot_model_v3_nov_dec_diagnostic_predictions.csv.gz"
VARIANTS = ("core", "pilot_v2", "pilot_v3")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_grid(rows: pd.DataFrame, start: str, end: str, target: bool) -> None:
    dates = pd.date_range(start, end)
    if len(rows) != len(ROUTES) * len(dates) * 24:
        raise ValueError("Incomplete model-ready grid")
    if rows.duplicated(["route", "date", "hour"]).any() or rows.isna().any().any():
        raise ValueError("Duplicate keys or missing model-ready values")
    if rows.date.min() != dates.min() or rows.date.max() != dates.max():
        raise ValueError("Model-ready date range differs")
    if set(rows.route.unique()) != set(ROUTES):
        raise ValueError("Model-ready routes differ")
    if not rows.groupby(["route", "date"]).hour.nunique().eq(24).all():
        raise ValueError("Incomplete route-day hours")
    if ("boardings" in rows.columns) != target:
        raise ValueError("Target presence differs from expected")


def check_calendar_availability(calendar: pd.DataFrame, origin: str, start: str, end: str) -> None:
    selected = calendar.loc[calendar.date.between(start, end)]
    if selected.date.nunique() != len(pd.date_range(start, end)):
        raise ValueError("Calendar does not cover prediction dates")
    dated = selected.known_from.notna()
    if not selected.loc[dated, "known_from"].le(pd.Timestamp(origin)).all():
        raise ValueError("Calendar event unavailable by origin")
    undated = selected.loc[~dated]
    deterministic = undated.availability_type.eq("deterministic_recurring")
    ordinary = undated.availability_type.isna()
    if not (deterministic | ordinary).all():
        raise ValueError("Undated calendar availability is unclear")
    active_ordinary = ordinary & undated[list(FLAGS)].any(axis=1)
    if not undated.loc[active_ordinary, "date"].dt.weekday.ge(5).all():
        raise ValueError("Undated active calendar row is not an ordinary weekend")
    if not undated.loc[active_ordinary, list(FLAGS)[1:]].eq(0).all().all():
        raise ValueError("Undated special calendar flag is active")


def prepare(rows: pd.DataFrame, variant: str) -> pd.DataFrame:
    if variant == "core":
        return features(rows)
    x = features(rows, FLAGS)
    if variant == "pilot_v3":
        x["temperature_bucket"] = rows["temperature_bucket"]
        if not isinstance(x["temperature_bucket"].dtype, pd.CategoricalDtype):
            raise TypeError("Temperature bucket lost categorical dtype")
        if list(x["temperature_bucket"].cat.categories) != list(BUCKET_LABELS):
            raise ValueError("Temperature bucket categories changed")
    elif variant != "pilot_v2":
        raise ValueError(f"Unknown variant: {variant}")
    return x


def fit_predict_variant(train: pd.DataFrame, future: pd.DataFrame, variant: str) -> np.ndarray:
    x_train = prepare(train, variant)
    x_future = prepare(future, variant)
    expected = list(BASE_FEATURES)
    if variant in ("pilot_v2", "pilot_v3"):
        expected += list(FLAGS)
    if variant == "pilot_v3":
        expected += ["temperature_bucket"]
    if x_train.columns.tolist() != expected or x_future.columns.tolist() != expected:
        raise ValueError("Variant feature order changed")
    categorical = list(BASE_FEATURES[:-1])
    if variant == "pilot_v3":
        categorical += ["temperature_bucket"]
    model = LGBMRegressor(**MODEL_PARAMETERS)
    model.fit(x_train, train.boardings, categorical_feature=categorical)
    prediction = np.floor(np.maximum(model.predict(x_future), 0) + 0.5).astype("int64")
    prediction[future.route.to_numpy() == 5] = 0
    if (prediction < 0).any():
        raise ValueError("Negative prediction after postprocessing")
    return prediction


def metrics(actual: np.ndarray, prediction: np.ndarray, routes: np.ndarray) -> dict:
    absolute_error = np.abs(actual - prediction)
    overall = wape(actual, prediction)
    per_route = {}
    for route in ROUTES:
        mask = routes == route
        route_actual = int(actual[mask].sum())
        route_error = int(absolute_error[mask].sum())
        per_route[str(route)] = {
            "actual_sum": route_actual,
            "absolute_error": route_error,
            "wape": route_error / route_actual if route_actual else None,
        }
    return {
        "wape": overall,
        "actual_sum": int(actual.sum()),
        "absolute_error": int(absolute_error.sum()),
        "per_route": per_route,
    }


def grouped_totals(rows: pd.DataFrame, keys: list[str]) -> list[dict]:
    grouped = rows.groupby(keys, dropna=False, sort=True, observed=True).agg(
        rows=("route", "size"),
        core_total=("core_prediction", "sum"),
        pilot_v2_total=("pilot_v2_prediction", "sum"),
        pilot_v3_total=("pilot_v3_prediction", "sum"),
    ).reset_index()
    return grouped.to_dict(orient="records")


def prediction_distribution(values: pd.Series) -> dict:
    quantiles = values.quantile([0.01, 0.05, 0.5, 0.95, 0.99])
    return {
        "count": int(values.count()), "zero_count": int(values.eq(0).sum()),
        "min": int(values.min()), "p01": float(quantiles.loc[0.01]),
        "p05": float(quantiles.loc[0.05]), "median": float(quantiles.loc[0.5]),
        "p95": float(quantiles.loc[0.95]), "p99": float(quantiles.loc[0.99]),
        "max": int(values.max()), "mean": float(values.mean()),
        "std": float(values.std()),
    }


def diagnostic_summary(forecast: pd.DataFrame, predictions: dict[str, np.ndarray]) -> dict:
    diagnostic = forecast[["route", "date", "hour", "weekday", *FLAGS]].copy()
    diagnostic["month"] = diagnostic.date.dt.month
    diagnostic["weekend"] = diagnostic.weekday.ge(5).astype("int8")
    for variant in VARIANTS:
        diagnostic[f"{variant}_prediction"] = predictions[variant]
    if len(diagnostic) != 14_640 or diagnostic.duplicated(["route", "date", "hour"]).any():
        raise ValueError("Diagnostic predictions do not cover forecast grid")
    if not diagnostic.loc[diagnostic.route.eq(5), [f"{variant}_prediction" for variant in VARIANTS]].eq(0).all().all():
        raise ValueError("Route 5 policy failed")
    columns = [f"{variant}_prediction" for variant in VARIANTS]
    diagnostic[["route", "date", "hour", *columns]].to_csv(
        DIAGNOSTIC_PREDICTIONS, sep=";", index=False, compression="gzip",
    )
    ordered = diagnostic.sort_values(["pilot_v3_prediction", "route", "date", "hour"],
                                     ascending=[False, True, True, True])
    differences = diagnostic.assign(
        v3_minus_v2=diagnostic.pilot_v3_prediction - diagnostic.pilot_v2_prediction,
    )
    differences["absolute_difference"] = differences.v3_minus_v2.abs()
    biggest_change = differences.sort_values(
        ["absolute_difference", "route", "date", "hour"],
        ascending=[False, True, True, True],
    )
    extreme_columns = ["route", "date", "hour", *columns]
    change_columns = [*extreme_columns, "v3_minus_v2"]
    return {
        "rows": len(diagnostic),
        "total_predictions": {variant: int(diagnostic[f"{variant}_prediction"].sum()) for variant in VARIANTS},
        "totals_by_route": grouped_totals(diagnostic, ["route"]),
        "totals_by_month": grouped_totals(diagnostic, ["month"]),
        "totals_by_weekend": grouped_totals(diagnostic, ["weekend"]),
        "totals_by_calendar_flag": {flag: grouped_totals(diagnostic, [flag]) for flag in FLAGS},
        "distribution": {
            variant: prediction_distribution(diagnostic[f"{variant}_prediction"])
            for variant in VARIANTS
        },
        "extreme_top_v3": ordered[extreme_columns].head(10).assign(
            date=lambda frame: frame.date.dt.strftime("%Y-%m-%d")
        ).to_dict(orient="records"),
        "extreme_v3_vs_v2_change": biggest_change[change_columns].head(10).assign(
            date=lambda frame: frame.date.dt.strftime("%Y-%m-%d")
        ).to_dict(orient="records"),
        "diagnostic_predictions_artifact": DIAGNOSTIC_PREDICTIONS.relative_to(ROOT).as_posix(),
    }


def main() -> None:
    climatology, climatology_checks = verify_climatology()
    train = pd.read_csv(TRAIN_PATH, sep=";", parse_dates=["date"])
    forecast = pd.read_csv(FORECAST_PATH, sep=";", parse_dates=["date"])
    calendar = pd.read_csv(CALENDAR_PATH, parse_dates=["date", "known_from"])
    if calendar.date.duplicated().any():
        raise ValueError("Calendar date is not unique")
    check_grid(train, "2025-01-01", "2025-10-31", target=True)
    check_grid(forecast, "2025-11-01", "2025-12-31", target=False)
    for rows in (train, forecast):
        joined = rows[["date", *FLAGS]].merge(
            calendar[["date", *FLAGS]], on="date", how="left", validate="many_to_one",
            suffixes=("_model", "_source"), indicator=True,
        )
        if joined._merge.ne("both").any():
            raise ValueError("Calendar join coverage changed")
        for flag in FLAGS:
            if not joined[f"{flag}_model"].equals(joined[f"{flag}_source"]):
                raise ValueError(f"Calendar value changed: {flag}")
    train = add_temperature_bucket(join_climatology(train, climatology))
    forecast = add_temperature_bucket(join_climatology(forecast, climatology))
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))

    folds = []
    pooled = {variant: {"actual_sum": 0, "absolute_error": 0} for variant in VARIANTS}
    for index, (name, train_start, train_end, valid_start, valid_end) in enumerate(FOLDS):
        train_fold = train.loc[train.date.between(train_start, train_end)].reset_index(drop=True)
        valid_fold = train.loc[train.date.between(valid_start, valid_end)].reset_index(drop=True)
        if len(train_fold) != len(ROUTES) * len(pd.date_range(train_start, train_end)) * 24:
            raise ValueError(f"Incomplete train fold: {name}")
        if len(valid_fold) != len(ROUTES) * len(pd.date_range(valid_start, valid_end)) * 24:
            raise ValueError(f"Incomplete validation fold: {name}")
        check_calendar_availability(calendar, train_end, valid_start, valid_end)
        predictions = {
            variant: fit_predict_variant(train_fold, valid_fold, variant)
            for variant in VARIANTS
        }
        actual = valid_fold.boardings.to_numpy(dtype="int64")
        routes = valid_fold.route.to_numpy()
        variant_metrics = {variant: metrics(actual, predictions[variant], routes) for variant in VARIANTS}
        prior = reference["folds"][index]
        if prior["fold"] != name:
            raise ValueError("Prior calendar fold order changed")
        for variant, prior_variant in (("core", "core"), ("pilot_v2", "all_calendar")):
            if abs(variant_metrics[variant]["wape"] - prior["variants"][prior_variant]["wape"]) > 1e-12:
                raise ValueError(f"Prior {variant} WAPE not reproduced on {name}")
        for variant in VARIANTS:
            pooled[variant]["actual_sum"] += variant_metrics[variant]["actual_sum"]
            pooled[variant]["absolute_error"] += variant_metrics[variant]["absolute_error"]
        folds.append({
            "fold": name,
            "train_period": [train_start, train_end],
            "validation_period": [valid_start, valid_end],
            "forecast_origin": train_end,
            "rows": {"train": len(train_fold), "validation": len(valid_fold)},
            "weather_coverage": {"train": int(train_fold.temperature_bucket.notna().sum()),
                                 "validation": int(valid_fold.temperature_bucket.notna().sum())},
            "temperature_bucket_train_categories": {
                label: int(train_fold.temperature_bucket.eq(label).sum()) for label in BUCKET_LABELS
            },
            "temperature_bucket_validation_categories": {
                label: int(valid_fold.temperature_bucket.eq(label).sum()) for label in BUCKET_LABELS
            },
            "variants": variant_metrics,
            "delta_wape_vs_core": {
                variant: variant_metrics[variant]["wape"] - variant_metrics["core"]["wape"]
                for variant in VARIANTS
            },
            "delta_wape_v3_vs_v2": variant_metrics["pilot_v3"]["wape"] - variant_metrics["pilot_v2"]["wape"],
        })
        print(name, {variant: round(variant_metrics[variant]["wape"], 6) for variant in VARIANTS}, flush=True)

    for variant in VARIANTS:
        pooled[variant]["wape"] = pooled[variant]["absolute_error"] / pooled[variant]["actual_sum"]
    v3_vs_v2 = [fold["delta_wape_v3_vs_v2"] for fold in folds]
    v3_vs_core = [fold["delta_wape_vs_core"]["pilot_v3"] for fold in folds]
    if (all(delta < 0 for delta in v3_vs_v2) and all(delta < 0 for delta in v3_vs_core)
            and pooled["pilot_v3"]["absolute_error"] < min(
                pooled["core"]["absolute_error"], pooled["pilot_v2"]["absolute_error"]
            )):
        classification = "V3_PROMISING_CANDIDATE"
    elif all(delta >= 0 for delta in v3_vs_v2):
        classification = "V3_NO_GAIN"
    else:
        classification = "V3_UNSTABLE"

    check_calendar_availability(calendar, "2025-10-31", "2025-11-01", "2025-12-31")
    final_predictions = {
        variant: fit_predict_variant(train, forecast, variant) for variant in VARIANTS
    }
    diagnostics = diagnostic_summary(forecast, final_predictions)
    result = {
        "experiment": "PILOT_MODEL_V3_CONTROLLED",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_sources_sha256": {
            path.relative_to(ROOT).as_posix(): sha256(path)
            for path in (TRAIN_PATH, FORECAST_PATH, CALENDAR_PATH, ARCHIVE_PATH, CLIMATOLOGY_PATH)
        },
        "climatology_checks": climatology_checks,
        "climatology_source_years": [2020, 2021, 2022, 2023, 2024],
        "observed_weather_2025_used": False,
        "temperature_bucket_boundaries": ["<0", "[0,10)", "[10,20)", ">=20"],
        "core_features": list(BASE_FEATURES),
        "calendar_candidates": list(FLAGS),
        "variant_features": {
            "core": list(BASE_FEATURES),
            "pilot_v2": [*BASE_FEATURES, *FLAGS],
            "pilot_v3": [*BASE_FEATURES, *FLAGS, "temperature_bucket"],
        },
        "categorical_features": {
            "core_and_v2": list(BASE_FEATURES[:-1]),
            "pilot_v3": [*BASE_FEATURES[:-1], "temperature_bucket"],
        },
        "model_parameters": MODEL_PARAMETERS,
        "postprocessing": "floor(max(raw_prediction, 0) + 0.5); route 5 = 0",
        "prior_core_v2_wape_reproduced": True,
        "classification_rule": (
            "PROMISING: v3 improves both core and v2 in all folds and pooled absolute error; "
            "NO_GAIN: v3 never improves v2; otherwise UNSTABLE"
        ),
        "classification": classification,
        "accepted_feature_registry_changed": False,
        "pooled_absolute_error": pooled,
        "folds": folds,
        "nov_dec_diagnostic_only": diagnostics,
        "nov_dec_ground_truth_available": False,
        "environment": {"python": platform.python_version(), "pandas": pd.__version__,
                        "numpy": np.__version__, "lightgbm": lightgbm.__version__},
    }
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("classification", classification, flush=True)
    print("pooled_absolute_error", {variant: pooled[variant]["absolute_error"] for variant in VARIANTS}, flush=True)
    print("nov_dec_totals", diagnostics["total_predictions"], flush=True)
    print("artifact", ARTIFACT.relative_to(ROOT).as_posix(), flush=True)


if __name__ == "__main__":
    main()
