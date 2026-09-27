"""Three single-feature weather climatology comparisons on established folds."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import lightgbm
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from calendar_temporal_stability import FOLDS, ROOT, ROUTES, TRAIN_PATH, features, fit_predict, wape
from feature_experiment_runner import BASE_FEATURES, MODEL_PARAMETERS, RESULTS


ARCHIVE_PATH = ROOT / "dataset/meta features/moscow_weather_2020_2024_era5.csv"
CLIMATOLOGY_PATH = ROOT / "dataset/meta features/moscow_weather_climatology_month_hour_2020_2024.csv"
FORECAST_PATH = ROOT / "data/processed/model_ready_forecast_2025_nov_dec.csv"
REFERENCE_PATH = RESULTS / "calendar_final_ablation.json"
ARTIFACT = RESULTS / "weather_climatology_single_feature.json"
BUCKET_ARTIFACT = RESULTS / "weather_temperature_bucket_final.json"
BUCKET_LABELS = ("<0", "[0,10)", "[10,20)", ">=20")
CANDIDATES = (
    "climatological_rain_probability",
    "climatological_temperature",
    "climatological_precipitation",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_climatology() -> tuple[pd.DataFrame, dict]:
    archive = pd.read_csv(ARCHIVE_PATH, parse_dates=["date", "valid_at"])
    climatology = pd.read_csv(CLIMATOLOGY_PATH)
    if len(archive) != 43_848 or archive.duplicated(["date", "hour"]).any():
        raise ValueError("ERA5 archive grid is incomplete or duplicated")
    if archive["date"].nunique() != len(pd.date_range("2020-01-01", "2024-12-31")):
        raise ValueError("ERA5 archive does not cover every date")
    if not archive.groupby("date")["hour"].nunique().eq(24).all():
        raise ValueError("ERA5 archive does not cover every hour of each date")
    valid_local = archive["valid_at"].dt.tz_localize(None)
    if not (valid_local.dt.normalize().eq(archive["date"]) & valid_local.dt.hour.eq(archive["hour"])).all():
        raise ValueError("ERA5 valid_at does not match the local date-hour key")
    if not archive["date"].dt.year.between(2020, 2024).all():
        raise ValueError("ERA5 archive includes dates outside 2020-2024")
    if not archive["archive_year"].eq(archive["date"].dt.year).all():
        raise ValueError("ERA5 archive_year disagrees with date")
    if not archive["source_model"].eq("ERA5").all() or not archive["timezone"].eq("Europe/Moscow").all():
        raise ValueError("ERA5 source or timezone changed")
    if not archive[["safe_for_2025_backtest", "safe_for_2025_forecast"]].eq(1).all().all():
        raise ValueError("ERA5 archive availability flags changed")
    if archive[["temperature_2m", "precipitation"]].isna().any().any():
        raise ValueError("ERA5 archive has missing candidate inputs")
    expected_keys = {(month, hour) for month in range(1, 13) for hour in range(24)}
    if len(climatology) != 288 or climatology.duplicated(["month", "hour"]).any():
        raise ValueError("Climatology must have 288 unique month-hour rows")
    if set(map(tuple, climatology[["month", "hour"]].to_numpy())) != expected_keys:
        raise ValueError("Climatology does not cover every month-hour key")
    if climatology.isna().any().any():
        raise ValueError("Climatology has missing values")
    if not climatology["climatological_rain_probability"].between(0, 1).all():
        raise ValueError("Invalid rain frequency")

    archive["month"] = archive["date"].dt.month
    grouped = archive.groupby(["month", "hour"], sort=True)
    recomputed = grouped.agg(
        temperature=("temperature_2m", "mean"),
        precipitation=("precipitation", "mean"),
        rain_probability=("precipitation", lambda values: values.gt(0).mean()),
        n_temperature=("temperature_2m", "count"),
        n_precipitation=("precipitation", "count"),
    ).reset_index()
    comparison = climatology.merge(recomputed, on=["month", "hour"], validate="one_to_one")
    pairs = (
        ("climatological_temperature", "temperature"),
        ("climatological_precipitation", "precipitation"),
        ("climatological_rain_probability", "rain_probability"),
        ("n_obs_temperature", "n_temperature"),
        ("n_obs_precipitation", "n_precipitation"),
    )
    max_difference = {left: float((comparison[left] - comparison[right]).abs().max()) for left, right in pairs}
    if max(max_difference.values()) > 1e-12:
        raise ValueError("Climatology differs from 2020-2024 archive aggregation")
    summary = {
        "archive_rows": len(archive),
        "archive_years": sorted(archive["date"].dt.year.unique().astype(int).tolist()),
        "climatology_rows": len(climatology),
        "missing_cells": int(climatology.isna().sum().sum()),
        "n_obs_temperature_range": [int(climatology.n_obs_temperature.min()), int(climatology.n_obs_temperature.max())],
        "n_obs_precipitation_range": [int(climatology.n_obs_precipitation.min()), int(climatology.n_obs_precipitation.max())],
        "recomputed_max_absolute_difference": max_difference,
    }
    return climatology, summary


def join_climatology(rows: pd.DataFrame, climatology: pd.DataFrame) -> pd.DataFrame:
    existing = [candidate for candidate in CANDIDATES if candidate in rows.columns]
    keyed = rows.assign(month=rows["date"].dt.month)
    joined = keyed.merge(
        climatology[["month", "hour", *CANDIDATES]].rename(
            columns={candidate: f"_source_{candidate}" for candidate in existing}
        ),
        on=["month", "hour"], how="left", validate="many_to_one", indicator=True,
        sort=False,
    )
    if len(joined) != len(rows) or joined["_merge"].ne("both").any():
        raise ValueError("Incomplete climatology join")
    for candidate in existing:
        source = f"_source_{candidate}"
        if not np.allclose(joined[candidate], joined[source], rtol=0, atol=1e-12):
            raise ValueError(f"Existing {candidate} differs from frozen climatology")
        joined = joined.drop(columns=source)
    if joined[list(CANDIDATES)].isna().any().any():
        raise ValueError("Missing climatology candidate after join")
    return joined.drop(columns=["_merge"])


def distribution(values: pd.Series) -> dict:
    quantiles = values.quantile([0.1, 0.5, 0.9])
    return {
        "count": int(values.count()), "unique_values": int(values.nunique()),
        "min": float(values.min()), "p10": float(quantiles.loc[0.1]),
        "median": float(quantiles.loc[0.5]), "p90": float(quantiles.loc[0.9]),
        "max": float(values.max()), "mean": float(values.mean()),
        "std": float(values.std()),
    }


def fit_candidate(train: pd.DataFrame, validation: pd.DataFrame, candidate: str) -> np.ndarray:
    x_train = features(train)
    x_validation = features(validation)
    x_train[candidate] = train[candidate].astype("float64")
    x_validation[candidate] = validation[candidate].astype("float64")
    model = LGBMRegressor(**MODEL_PARAMETERS)
    model.fit(x_train, train["boardings"], categorical_feature=list(BASE_FEATURES[:-1]))
    prediction = np.floor(np.maximum(model.predict(x_validation), 0) + 0.5)
    prediction[validation["route"].to_numpy() == 5] = 0
    return prediction


def add_temperature_bucket(rows: pd.DataFrame) -> pd.DataFrame:
    result = rows.copy()
    bucket = pd.cut(
        result["climatological_temperature"],
        bins=[-np.inf, 0, 10, 20, np.inf],
        right=False, labels=BUCKET_LABELS,
    )
    if "temperature_bucket" in result and not result["temperature_bucket"].eq(bucket.astype(str)).all():
        raise ValueError("Existing temperature_bucket differs from frozen bins")
    result["temperature_bucket"] = bucket
    if result["temperature_bucket"].isna().any():
        raise ValueError("Temperature bucket has missing values")
    return result


def bucket_distribution(rows: pd.DataFrame) -> dict[str, int]:
    counts = rows["temperature_bucket"].value_counts(sort=False)
    return {label: int(counts[label]) for label in BUCKET_LABELS}


def fit_temperature_bucket(train: pd.DataFrame, validation: pd.DataFrame) -> np.ndarray:
    x_train = features(train)
    x_validation = features(validation)
    x_train["temperature_bucket"] = train["temperature_bucket"]
    x_validation["temperature_bucket"] = validation["temperature_bucket"]
    model = LGBMRegressor(**MODEL_PARAMETERS)
    model.fit(
        x_train, train["boardings"],
        categorical_feature=[*BASE_FEATURES[:-1], "temperature_bucket"],
    )
    prediction = np.floor(np.maximum(model.predict(x_validation), 0) + 0.5)
    prediction[validation["route"].to_numpy() == 5] = 0
    return prediction


def run_temperature_bucket() -> None:
    climatology, source_checks = verify_climatology()
    data = add_temperature_bucket(join_climatology(
        pd.read_csv(TRAIN_PATH, sep=";", parse_dates=["date"]), climatology
    ))
    forecast = add_temperature_bucket(join_climatology(
        pd.read_csv(FORECAST_PATH, sep=";", parse_dates=["date"]), climatology
    ))
    if len(data) != 72_960 or len(forecast) != 14_640:
        raise ValueError("Model-ready grid size changed")
    if data.duplicated(["route", "date", "hour"]).any() or forecast.duplicated(["route", "date", "hour"]).any():
        raise ValueError("Model-ready grid has duplicate keys")
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    prepared = []
    for name, train_start, train_end, valid_start, valid_end in FOLDS:
        train = data.loc[data.date.between(train_start, train_end)].reset_index(drop=True)
        validation = data.loc[data.date.between(valid_start, valid_end)].reset_index(drop=True)
        if len(train) != len(ROUTES) * len(pd.date_range(train_start, train_end)) * 24:
            raise ValueError(f"Incomplete train grid: {name}")
        if len(validation) != len(ROUTES) * len(pd.date_range(valid_start, valid_end)) * 24:
            raise ValueError(f"Incomplete validation grid: {name}")
        train_counts = bucket_distribution(train)
        validation_counts = bucket_distribution(validation)
        present_train = [label for label in BUCKET_LABELS if train_counts[label] > 0]
        present_validation = [label for label in BUCKET_LABELS if validation_counts[label] > 0]
        unseen = [label for label in present_validation if label not in present_train]
        unseen_fraction = sum(validation_counts[label] for label in unseen) / len(validation)
        diagnostics = {
            "train_category_counts": train_counts,
            "validation_category_counts": validation_counts,
            "train_categories_present": present_train,
            "validation_categories_present": present_validation,
            "validation_unseen_categories": unseen,
            "validation_unseen_category_fraction": unseen_fraction,
        }
        prepared.append((name, train_start, train_end, valid_start, valid_end, train, validation, diagnostics))

    # Print every fold's category support before the first model fit.
    print("pre_fit_bucket_diagnostics", json.dumps({item[0]: item[-1] for item in prepared}, ensure_ascii=False), flush=True)

    folds = []
    for index, (name, train_start, train_end, valid_start, valid_end, train, validation, diagnostics) in enumerate(prepared):
        core_prediction = fit_predict(train, validation)
        bucket_prediction = fit_temperature_bucket(train, validation)
        actual = validation.boardings.to_numpy(dtype=float)
        core_wape = wape(actual, core_prediction)
        bucket_wape = wape(actual, bucket_prediction)
        prior = reference["folds"][index]
        if prior["fold"] != name or abs(core_wape - prior["variants"]["core"]["wape"]) > 1e-12:
            raise ValueError(f"Prior core WAPE not reproduced: {name}")
        per_route = {}
        for route, group in validation.groupby("route", sort=True):
            positions = group.index.to_numpy()
            core_route = wape(actual[positions], core_prediction[positions])
            bucket_route = wape(actual[positions], bucket_prediction[positions])
            per_route[str(int(route))] = {
                "core_wape": core_route if np.isfinite(core_route) else None,
                "bucket_wape": bucket_route if np.isfinite(bucket_route) else None,
                "delta_wape": bucket_route - core_route if np.isfinite(core_route) else None,
            }
        folds.append({
            "fold": name,
            "train_period": [train_start, train_end],
            "validation_period": [valid_start, valid_end],
            "forecast_origin": train_end,
            "rows": {"train": len(train), "validation": len(validation)},
            "coverage": {"train": int(train.temperature_bucket.notna().sum()),
                         "validation": int(validation.temperature_bucket.notna().sum())},
            "pre_fit_bucket_diagnostics": diagnostics,
            "core_wape": core_wape,
            "bucket_wape": bucket_wape,
            "delta_wape_vs_core": bucket_wape - core_wape,
            "per_route": per_route,
        })
        print(name, {"core_wape": core_wape, "bucket_wape": bucket_wape,
                     "delta_wape": bucket_wape - core_wape}, flush=True)

    improvements = sum(fold["delta_wape_vs_core"] < 0 for fold in folds)
    classification = (
        "TEMPERATURE_BUCKET_KEEP" if improvements == 3 else
        "WEATHER_REJECT" if improvements == 0 else "WEATHER_CANDIDATE_ONLY"
    )
    result = {
        "experiment": "WEATHER_TEMPERATURE_BUCKET_FINAL",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_files_sha256": {
            path.relative_to(ROOT).as_posix(): file_sha256(path)
            for path in (ARCHIVE_PATH, CLIMATOLOGY_PATH, TRAIN_PATH, FORECAST_PATH)
        },
        "source_checks": source_checks,
        "bucket_source": "frozen 2020-2024 month-hour climatological_temperature",
        "bucket_labels": list(BUCKET_LABELS),
        "bucket_intervals": ["(-inf, 0)", "[0, 10)", "[10, 20)", "[20, inf)"],
        "bucket_boundary_selection": "predefined; no validation-based selection",
        "core_features": list(BASE_FEATURES),
        "candidate_features": [*BASE_FEATURES, "temperature_bucket"],
        "categorical_features": [*BASE_FEATURES[:-1], "temperature_bucket"],
        "model_parameters": MODEL_PARAMETERS,
        "postprocessing": "floor(max(raw_prediction, 0) + 0.5); route 5 = 0",
        "classification_rule": "3/3 fold improvements: KEEP; 0/3: REJECT; otherwise: CANDIDATE_ONLY",
        "classification": classification,
        "weather_branch_closed": True,
        "observed_weather_2025_used": False,
        "forecast_coverage": int(forecast.temperature_bucket.notna().sum()),
        "forecast_category_counts": bucket_distribution(forecast),
        "environment": {"python": platform.python_version(), "pandas": pd.__version__,
                        "numpy": np.__version__, "lightgbm": lightgbm.__version__},
        "folds": folds,
    }
    BUCKET_ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("classification", classification)
    print("result", BUCKET_ARTIFACT.relative_to(ROOT).as_posix())


def main() -> None:
    climatology, source_checks = verify_climatology()
    data = pd.read_csv(TRAIN_PATH, sep=";", parse_dates=["date"])
    forecast = pd.read_csv(FORECAST_PATH, sep=";", parse_dates=["date"])
    if len(data) != 72_960 or len(forecast) != 14_640:
        raise ValueError("Model-ready grid size changed")
    for rows in (data, forecast):
        if rows.duplicated(["route", "date", "hour"]).any() or rows.isna().any().any():
            raise ValueError("Model-ready grid has duplicates or missing values")
    data = join_climatology(data, climatology)
    forecast = join_climatology(forecast, climatology)
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))

    folds = []
    for index, (name, train_start, train_end, valid_start, valid_end) in enumerate(FOLDS):
        train = data.loc[data.date.between(train_start, train_end)].reset_index(drop=True)
        validation = data.loc[data.date.between(valid_start, valid_end)].reset_index(drop=True)
        if len(train) != len(ROUTES) * len(pd.date_range(train_start, train_end)) * 24:
            raise ValueError(f"Incomplete train grid: {name}")
        if len(validation) != len(ROUTES) * len(pd.date_range(valid_start, valid_end)) * 24:
            raise ValueError(f"Incomplete validation grid: {name}")
        if train.date.max() >= validation.date.min():
            raise ValueError(f"Overlapping fold dates: {name}")

        core_prediction = fit_predict(train, validation)
        actual = validation.boardings.to_numpy(dtype=float)
        core_wape = wape(actual, core_prediction)
        prior = reference["folds"][index]
        if prior["fold"] != name or abs(core_wape - prior["variants"]["core"]["wape"]) > 1e-12:
            raise ValueError(f"Prior core WAPE not reproduced: {name}")

        candidates = {}
        for candidate in CANDIDATES:
            prediction = fit_candidate(train, validation, candidate)
            candidate_wape = wape(actual, prediction)
            per_route = {}
            for route, group in validation.groupby("route", sort=True):
                positions = group.index.to_numpy()
                core_route = wape(actual[positions], core_prediction[positions])
                candidate_route = wape(actual[positions], prediction[positions])
                per_route[str(int(route))] = {
                    "core_wape": core_route if np.isfinite(core_route) else None,
                    "candidate_wape": candidate_route if np.isfinite(candidate_route) else None,
                    "delta_wape": candidate_route - core_route if np.isfinite(core_route) else None,
                }
            train_values = train[candidate]
            validation_values = validation[candidate]
            candidates[candidate] = {
                "wape": candidate_wape,
                "delta_wape_vs_core": candidate_wape - core_wape,
                "per_route": per_route,
                "coverage": {"train": int(train_values.notna().sum()),
                             "validation": int(validation_values.notna().sum())},
                "distribution": {"train": distribution(train_values),
                                 "validation": distribution(validation_values)},
                "shift": {
                    "validation_outside_train_minmax_fraction": float(
                        ((validation_values < train_values.min()) |
                         (validation_values > train_values.max())).mean()
                    ),
                    "validation_below_train_min_fraction": float((validation_values < train_values.min()).mean()),
                    "validation_above_train_max_fraction": float((validation_values > train_values.max()).mean()),
                    "validation_unseen_exact_value_fraction": float(
                        (~validation_values.isin(train_values.unique())).mean()
                    ),
                },
            }
        folds.append({
            "fold": name,
            "train_period": [train_start, train_end],
            "validation_period": [valid_start, valid_end],
            "forecast_origin": train_end,
            "rows": {"train": len(train), "validation": len(validation)},
            "core_wape": core_wape,
            "candidates": candidates,
        })
        print(name, {candidate: round(metrics["delta_wape_vs_core"], 6)
                     for candidate, metrics in candidates.items()}, flush=True)

    classifications = {}
    for candidate in CANDIDATES:
        improvements = sum(fold["candidates"][candidate]["delta_wape_vs_core"] < 0 for fold in folds)
        classifications[candidate] = (
            "KEEP_CANDIDATE" if improvements == 3 else
            "REJECT" if improvements == 0 else "MIXED"
        )
    result = {
        "experiment": "WEATHER_CLIMATOLOGY_SINGLE_FEATURE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_files_sha256": {
            path.relative_to(ROOT).as_posix(): file_sha256(path)
            for path in (ARCHIVE_PATH, CLIMATOLOGY_PATH, TRAIN_PATH, FORECAST_PATH)
        },
        "source_checks": source_checks,
        "climatology_formula": {
            "group_by": ["month", "hour"],
            "source_years": [2020, 2021, 2022, 2023, 2024],
            "temperature": "mean(temperature_2m)",
            "precipitation": "mean(precipitation)",
            "rain_probability": "mean(precipitation > 0)",
            "frozen_across_folds": True,
            "observed_2025_weather_used": False,
        },
        "core_features": list(BASE_FEATURES),
        "candidate_features": list(CANDIDATES),
        "categorical_features": list(BASE_FEATURES[:-1]),
        "model_parameters": MODEL_PARAMETERS,
        "postprocessing": "floor(max(raw_prediction, 0) + 0.5); route 5 = 0",
        "classification_rule": "3/3 folds improved: KEEP_CANDIDATE; 0/3: REJECT; otherwise: MIXED",
        "environment": {"python": platform.python_version(), "pandas": pd.__version__,
                        "numpy": np.__version__, "lightgbm": lightgbm.__version__},
        "forecast_coverage": {candidate: int(forecast[candidate].notna().sum()) for candidate in CANDIDATES},
        "folds": folds,
        "classifications": classifications,
    }
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("classifications", classifications)
    print("result", ARTIFACT.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--temperature-bucket", action="store_true")
    args = parser.parse_args()
    if args.temperature_bucket:
        run_temperature_bucket()
    else:
        main()
