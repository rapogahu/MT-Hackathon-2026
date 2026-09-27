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
    H19_NAME, H20_NAME, H21_NAME, H22_NAME, H23_NAME, H24_NAME, H25_NAME, H26_NAME, H27_NAME,
    RouteWeekdayHourHistoricalMedian,
    RouteWeekdayHourHistoricalMean, MedianLast4SameWeekdayHour, MeanLast4SameWeekdayHour,
    RouteRecent4WeekMean, RoutePrevious4WeekMean, RouteRecentVsPreviousDiff,
    RouteRecentVsPreviousRelChange, LastObservedSameRouteWeekdayHour,
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
    ratio_diagnostics = None
    anchor_age_diagnostics = None
    forecast_distance_bucket_metrics = None
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
        if hasattr(candidate_builder, "ratio_diagnostics"):
            ratio_diagnostics = candidate_builder.ratio_diagnostics(
                train[["route", "date", "hour"]], valid[["route", "date", "hour"]],
                history, train[candidate_name], valid[candidate_name]
            )
        if hasattr(candidate_builder, "anchor_age_days"):
            age = candidate_builder.anchor_age_days(valid[["route", "date", "hour"]], history)
            if not age.index.equals(valid.index) or not age.notna().equals(valid[candidate_name].notna()):
                raise ValueError("Anchor age does not align with validation feature coverage")
            observed_age = age.dropna()
            if not observed_age.ge(1).all():
                raise ValueError("Anchor must precede every validation row")
            quantiles = observed_age.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
            anchor_age_diagnostics = {
                "non_null": int(age.notna().sum()), "nan_count": int(age.isna().sum()),
                "min": float(observed_age.min()), "p05": float(quantiles.loc[0.05]),
                "p25": float(quantiles.loc[0.25]), "median": float(quantiles.loc[0.5]),
                "p75": float(quantiles.loc[0.75]), "p95": float(quantiles.loc[0.95]),
                "max": float(observed_age.max()), "mean": float(observed_age.mean()),
            }
            forecast_day = (valid["date"] - pd.Timestamp(VALID_START)).dt.days + 1
            forecast_distance_bucket_metrics = {}
            for name, mask in (
                ("days_1_7", forecast_day.between(1, 7)),
                ("days_8_28", forecast_day.between(8, 28)),
                ("days_29_plus", forecast_day.ge(29)),
            ):
                selected = mask.to_numpy()
                baseline_bucket = wape(actual[selected], baseline_pred[selected])
                candidate_bucket = wape(actual[selected], candidate_pred[selected])
                forecast_distance_bucket_metrics[name] = {
                    "rows": int(selected.sum()),
                    "baseline_wape": baseline_bucket,
                    "candidate_wape": candidate_bucket,
                    "delta_wape": candidate_bucket - baseline_bucket,
                    "mean_anchor_age_days": float(age.loc[mask].mean()),
                }
    result = {
        "experiment": experiment,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_sources": ["data/raw/labels/labels_day_train.csv", "data/raw/labels/labels_day_test.csv"],
        "grid_rows": {"train": len(train), "validation": len(valid)},
        "periods": {"train": [TRAIN_START, TRAIN_END], "validation": [VALID_START, VALID_END]},
        "temporal_boundary_passed": bool(train["date"].max() < valid["date"].min()),
        "model_parameters": MODEL_PARAMETERS,
        "candidate_parameters": getattr(candidate_builder, "PARAMETERS", None),
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
        "ratio_diagnostics": ratio_diagnostics,
        "anchor_age_diagnostics": anchor_age_diagnostics,
        "forecast_distance_bucket_metrics": forecast_distance_bucket_metrics,
        "missing_value_handling": "Native LightGBM missing value; no numeric fallback" if candidate_name else None,
        "decision": None,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    destination = RESULTS / f"{experiment.lower()}_result.json"
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    result["artifact"] = destination.relative_to(ROOT).as_posix()
    return result



def run_calendar_group(decompose: bool = False) -> dict:
    """Controlled A/B for the official leakage-safe calendar feature group."""
    calendar_path = ROOT / "dataset/meta features/calendar_2025_ml.csv"
    flags = (
        "is_day_off", "is_official_holiday", "is_transferred_day_off",
        "is_transferred_workday", "is_shortened_workday",
    )
    calendar = pd.read_csv(calendar_path, parse_dates=["date", "known_from"])
    if calendar["date"].duplicated().any():
        raise ValueError("Calendar must contain one row per date")
    required = {"date", "availability_type", "known_from", *flags}
    if not required.issubset(calendar.columns):
        raise ValueError("Calendar is missing required columns")
    if calendar[list(flags)].isna().any().any():
        raise ValueError("Calendar flags must be fully populated")

    # Validation origin is Aug 31; future-inference origin is Oct 31. Any
    # annual-decree row must have been published by the relevant origin.
    annual = calendar[calendar["availability_type"].eq("annual_decree")]
    origins = {"validation": pd.Timestamp("2025-08-31"),
               "nov_dec_inference": pd.Timestamp("2025-10-31")}
    availability = {name: {
        "origin": origin.date().isoformat(),
        "annual_decree_rows": int(len(annual)),
        "all_known_by_origin": bool(annual["known_from"].notna().all() and annual["known_from"].le(origin).all()),
        "latest_known_from": annual["known_from"].max().date().isoformat() if len(annual) else None,
    } for name, origin in origins.items()}
    if not all(v["all_known_by_origin"] for v in availability.values()):
        raise ValueError("An annual_decree calendar event was not known at forecast origin")

    train = _label_grid(TRAIN_LABELS, TRAIN_START, TRAIN_END)
    valid = _label_grid(VALID_LABELS, VALID_START, VALID_END)
    train = train.merge(calendar[["date", *flags]], on="date", how="left", validate="many_to_one")
    valid = valid.merge(calendar[["date", *flags]], on="date", how="left", validate="many_to_one")
    if train[list(flags)].isna().any().any() or valid[list(flags)].isna().any().any():
        raise ValueError("Calendar does not cover the complete train/validation periods")

    base_x_train, base_x_valid = calendar_features(train), calendar_features(valid)
    group_x_train = pd.concat([base_x_train, train[list(flags)].astype("int8")], axis=1)
    group_x_valid = pd.concat([base_x_valid, valid[list(flags)].astype("int8")], axis=1)
    y_train = train["boardings"]
    model_base = LGBMRegressor(**MODEL_PARAMETERS)
    model_base.fit(base_x_train, y_train, categorical_feature=list(BASE_FEATURES[:-1]))
    base_pred = np.floor(np.maximum(model_base.predict(base_x_valid), 0) + 0.5)
    model_group = LGBMRegressor(**MODEL_PARAMETERS)
    model_group.fit(group_x_train, y_train, categorical_feature=list(BASE_FEATURES[:-1]))
    group_pred = np.floor(np.maximum(model_group.predict(group_x_valid), 0) + 0.5)
    base_pred[valid["route"].to_numpy() == 5] = 0
    group_pred[valid["route"].to_numpy() == 5] = 0
    actual = valid["boardings"].to_numpy(dtype=float)

    def route_wapes(pred):
        return {str(int(r)): (wape(g["boardings"].to_numpy(dtype=float), pred[g.index.to_numpy()])
                            if r != 5 else None)
                for r, g in valid.groupby("route", sort=True)}

    base_wape, group_wape = wape(actual, base_pred), wape(actual, group_pred)
    flag_days = {flag: {
        "active_days_2025": int(calendar.loc[calendar[flag].eq(1), "date"].nunique()),
        "validation_active_days": int(valid.loc[valid[flag].eq(1), "date"].nunique()),
        "nov_dec_inference_active_days": int(calendar.loc[calendar["date"].between("2025-11-01", "2025-12-31") & calendar[flag].eq(1), "date"].nunique()),
        "validation_coverage_rows": int(valid[flag].notna().sum()),
    } for flag in flags}
    result = {
        "experiment": "CALENDAR_OFFICIAL_GROUP",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_sources": ["data/raw/labels/labels_day_train.csv", "data/raw/labels/labels_day_test.csv",
                         "dataset/meta features/calendar_2025_ml.csv"],
        "periods": {"train": [TRAIN_START, TRAIN_END], "validation": [VALID_START, VALID_END]},
        "validation_origins": availability,
        "feature_group": list(flags),
        "model_parameters": MODEL_PARAMETERS,
        "baseline_feature_names": list(BASE_FEATURES),
        "candidate_feature_names": list(BASE_FEATURES) + list(flags),
        "metrics": {
            "baseline_overall_wape": base_wape, "baseline_wape_score": 1-base_wape,
            "candidate_overall_wape": group_wape, "candidate_wape_score": 1-group_wape,
            "delta_wape": group_wape-base_wape, "delta_wape_score": base_wape-group_wape,
            "baseline_per_route_wape": route_wapes(base_pred),
            "candidate_per_route_wape": route_wapes(group_pred),
            "flag_days": flag_days,
        },
        "decision": "INCONCLUSIVE",
        "decision_note": "Single temporal holdout; classify KEEP only for lower WAPE without severe route regressions, REJECT for clear overall regression, otherwise INCONCLUSIVE.",
    }
    if decompose:
        weekend_train = train["date"].dt.weekday.ge(5).astype("int8")
        weekend_valid = valid["date"].dt.weekday.ge(5).astype("int8")
        day_off_train = train["is_day_off"].astype("int8")
        day_off_valid = valid["is_day_off"].astype("int8")

        def flag_counts(frame):
            return {flag: {
                "active_dates": int(frame.loc[frame[flag].eq(1), "date"].nunique()),
                "active_rows": int(frame[flag].eq(1).sum()),
                "non_null_rows": int(frame[flag].notna().sum()),
            } for flag in flags}

        def fit_subset(subset):
            x_train = pd.concat([base_x_train, train[list(subset)].astype("int8")], axis=1)
            x_valid = pd.concat([base_x_valid, valid[list(subset)].astype("int8")], axis=1)
            model = LGBMRegressor(**MODEL_PARAMETERS)
            model.fit(x_train, y_train, categorical_feature=list(BASE_FEATURES[:-1]))
            pred = np.floor(np.maximum(model.predict(x_valid), 0) + 0.5)
            pred[valid["route"].to_numpy() == 5] = 0
            return pred

        day_off_pred = fit_subset(("is_day_off",))
        other_pred = fit_subset(flags[1:])

        def variant_metrics(pred):
            value = wape(actual, pred)
            return {"overall_wape": value, "wape_score": 1 - value,
                    "delta_wape_vs_accepted": value - base_wape,
                    "per_route_wape": route_wapes(pred)}

        result["decomposition"] = {
            "flag_counts": {"train": flag_counts(train), "validation": flag_counts(valid)},
            "weekend_semantics": {
                "definition": "date.weekday >= 5",
                "h6_added_feature_dtype": "int8",
                "day_off_feature_dtype": str(day_off_train.dtype),
                "preprocessing": "Numeric flag; not in categorical_feature. Accepted categorical fields unchanged.",
                "train_mismatch_rows": int(day_off_train.ne(weekend_train).sum()),
                "train_mismatch_dates": int(train.loc[day_off_train.ne(weekend_train), "date"].nunique()),
                "train_day_off_1_weekend_0_rows": int(day_off_train.gt(weekend_train).sum()),
                "train_day_off_0_weekend_1_rows": int(day_off_train.lt(weekend_train).sum()),
                "validation_mismatch_rows": int(day_off_valid.ne(weekend_valid).sum()),
                "validation_mismatch_dates": int(valid.loc[day_off_valid.ne(weekend_valid), "date"].nunique()),
                "train_weekend_active_rows": int(weekend_train.sum()),
                "validation_weekend_active_rows": int(weekend_valid.sum()),
            },
            "variants": {
                "accepted": variant_metrics(base_pred),
                "accepted_plus_is_day_off": variant_metrics(day_off_pred),
                "accepted_plus_other_four": variant_metrics(other_pred),
                "accepted_plus_official_group": variant_metrics(group_pred),
            },
        }
        result["classification"] = "REPRESENTATION_DIFFERENCE"
        result["classification_note"] = (
            "The only nonconstant validation flag equals weekend exactly. Four other flags "
            "are zero throughout validation but change the fitted tree structure through training. "
            "No holiday-specific validation effect is identified."
        )
        prior = RESULTS / "calendar_official_group_result.json"
        if prior.exists():
            previous = json.loads(prior.read_text(encoding="utf-8"))
            for name in ("baseline_overall_wape", "candidate_overall_wape"):
                if abs(result["metrics"][name] - previous["metrics"][name]) > 1e-12:
                    raise ValueError(f"Calendar decomposition failed to reproduce {name}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    destination = RESULTS / ("calendar_official_group_decomposition.json" if decompose
                             else "calendar_official_group_result.json")
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    result["artifact"] = destination.relative_to(ROOT).as_posix()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default="SMOKE", help="Experiment ID; SMOKE runs accepted features only")
    parser.add_argument("--calendar-official-group", action="store_true", help="Run controlled official calendar A/B")
    parser.add_argument("--calendar-decomposition", action="store_true", help="Decompose the official calendar A/B")
    args = parser.parse_args()
    if args.calendar_official_group or args.calendar_decomposition:
        result = run_calendar_group(decompose=args.calendar_decomposition)
        print(json.dumps(result, indent=2, allow_nan=False))
        return
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
    elif experiment == "H25":
        result = run_experiment(experiment, RouteRecentVsPreviousDiff, H25_NAME)
    elif experiment == "H26":
        result = run_experiment(experiment, RouteRecentVsPreviousRelChange, H26_NAME)
    elif experiment == "H27":
        result = run_experiment(experiment, LastObservedSameRouteWeekdayHour, H27_NAME)
    else:
        parser.error(f"No candidate builder registered for {experiment}")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
