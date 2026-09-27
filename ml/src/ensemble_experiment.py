"""Controlled blend of the frozen weighted tuned XGBoost and LightGBM models."""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import lightgbm
import numpy as np
import pandas as pd
import xgboost
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor

import model_selection as ms
import recency_weighting_experiment as rw


ARTIFACT = ms.RESULTS / "ensemble_experiment.json"
PREDICTIONS = ms.RESULTS / "ensemble_experiment_raw_predictions.csv.gz"
ALPHAS = (1.0, 0.9, 0.75, 0.6, 0.5, 0.0)
FAMILIES = ("XGBRegressor", "LightGBM")
ROUTE_DEGRADATION_THRESHOLD = 0.01  # Absolute pooled route WAPE, fixed before evaluation.


def postprocess(raw: np.ndarray, route: np.ndarray) -> np.ndarray:
    if not np.isfinite(raw).all():
        raise ValueError("Non-finite raw prediction")
    predicted = np.floor(np.maximum(raw, 0) + 0.5).astype("int64")
    predicted[route == 5] = 0
    return predicted


def correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 2 or np.std(left) == 0 or np.std(right) == 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def complementarity(actual: np.ndarray, route: np.ndarray,
                    xgb: np.ndarray, lgbm: np.ndarray) -> dict:
    xgb_error = actual - xgb
    lgbm_error = actual - lgbm
    xgb_abs = np.abs(xgb_error)
    lgbm_abs = np.abs(lgbm_error)
    difference = np.abs(xgb - lgbm)
    return {
        "prediction_correlation": correlation(xgb, lgbm),
        "residual_correlation": correlation(xgb_error, lgbm_error),
        "absolute_error_correlation": correlation(xgb_abs, lgbm_abs),
        "xgb_lower_absolute_error_share": float(np.mean(xgb_abs < lgbm_abs)),
        "lgbm_lower_absolute_error_share": float(np.mean(lgbm_abs < xgb_abs)),
        "equal_absolute_error_share": float(np.mean(xgb_abs == lgbm_abs)),
        "mean_absolute_prediction_difference": float(difference.mean()),
        "median_absolute_prediction_difference": float(np.median(difference)),
        "per_route_mean_absolute_prediction_difference": {
            str(key): float(difference[route == key].mean()) for key in ms.ROUTES
        },
    }


def assert_reference(family: str, folds: list[dict]) -> None:
    path = (ms.RESULTS / "xgboost_recency_weighting.json" if family == "XGBRegressor"
            else ms.RESULTS / "recency_weighting.json")
    prior = json.loads(path.read_text(encoding="utf-8"))
    expected = prior["all_folds"]["exponential_180"]
    for index, (actual, previous) in enumerate(zip(folds, expected, strict=True)):
        if (actual["absolute_error"] != previous["absolute_error"] or
                actual["actual_sum"] != previous["actual_sum"]):
            raise ValueError(f"{family} weighted reference mismatch on fold {index + 1}")
        for route in ms.ROUTES:
            key = str(route)
            if actual["per_route"][key]["absolute_error"] != previous["per_route"][key]["absolute_error"]:
                raise ValueError(f"{family} weighted route mismatch on fold {index + 1}, route {route}")
    if ms.summarize(folds)["pooled_absolute_error"] != prior["summaries"]["exponential_180"]["pooled_absolute_error"]:
        raise ValueError(f"{family} weighted pooled reference mismatch")


def train_raw(train: pd.DataFrame, valid: pd.DataFrame,
              family: str, parameters: dict) -> tuple[np.ndarray, dict]:
    weights, weight_info = rw.sample_weights(train, "exponential_180")
    x_train = ms.make_features(train, rw.CONFIGURATION, family)
    x_valid = ms.make_features(valid, rw.CONFIGURATION, family)
    if x_train.columns.tolist() != list(ms.FEATURE_CONFIGURATIONS[rw.CONFIGURATION]):
        raise ValueError("Feature order changed")
    model = XGBRegressor(**parameters) if family == "XGBRegressor" else LGBMRegressor(**parameters)
    fit_options = {} if family == "XGBRegressor" else {"categorical_feature": list(ms.CATEGORICAL)}
    started = perf_counter()
    model.fit(x_train, train.boardings, sample_weight=weights, **fit_options)
    train_seconds = perf_counter() - started
    started = perf_counter()
    raw = np.asarray(model.predict(x_valid), dtype="float64")
    inference_seconds = perf_counter() - started
    if len(raw) != len(valid) or not np.isfinite(raw).all():
        raise ValueError("Invalid raw prediction")
    return raw, {"train_seconds": train_seconds, "inference_seconds": inference_seconds,
                 "weight_diagnostics": weight_info}


def run_experiment() -> dict:
    _, folds, hpo = rw.load_inputs("XGBRegressor")
    rw.load_inputs("LightGBM")  # Confirm the same frozen HPO and data contract.
    parameters = {family: rw.model_contract(hpo, family) for family in FAMILIES}
    previous_paths = (ms.RESULTS / "xgboost_recency_weighting.json",
                      ms.RESULTS / "recency_weighting.json")
    for path, family in zip(previous_paths, FAMILIES, strict=True):
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous["source_sha256"]["data/processed/model_ready_train_2025_jan_oct.csv"] != ms.sha256(ms.DATA_PATH):
            raise ValueError(f"Historical input differs from {family} recency experiment")

    fold_metrics = {str(alpha): [] for alpha in ALPHAS}
    diagnostics = {}
    raw_frames = []
    pooled_arrays = []
    for spec, (train, valid) in zip(ms.FOLDS, folds, strict=True):
        name = spec[0]
        route = valid.route.to_numpy()
        actual = valid.boardings.to_numpy(dtype="int64")
        xgb, xgb_info = train_raw(train, valid, "XGBRegressor", parameters["XGBRegressor"])
        lgbm, lgbm_info = train_raw(train, valid, "LightGBM", parameters["LightGBM"])
        if xgb_info["weight_diagnostics"] != lgbm_info["weight_diagnostics"]:
            raise ValueError("Model weights differ within a fold")
        diagnostics[name] = complementarity(actual, route, xgb, lgbm)
        diagnostics[name]["weight_diagnostics"] = xgb_info["weight_diagnostics"]
        pooled_arrays.append((actual, route, xgb, lgbm))
        raw_frames.append(pd.DataFrame({"fold": name, "route": route,
                                        "date": valid.date.dt.strftime("%Y-%m-%d"),
                                        "hour": valid.hour.to_numpy(),
                                        "xgb_raw": xgb, "lgbm_raw": lgbm}))
        for alpha in ALPHAS:
            predicted = postprocess(alpha * xgb + (1 - alpha) * lgbm, route)
            metrics = ms.measure(actual, predicted, route)
            metrics["fold"] = name
            if alpha == 1.0:
                metrics.update({key: xgb_info[key] for key in ("train_seconds", "inference_seconds")})
            elif alpha == 0.0:
                metrics.update({key: lgbm_info[key] for key in ("train_seconds", "inference_seconds")})
            else:
                metrics["train_seconds"] = xgb_info["train_seconds"] + lgbm_info["train_seconds"]
                metrics["inference_seconds"] = xgb_info["inference_seconds"] + lgbm_info["inference_seconds"]
            fold_metrics[str(alpha)].append(metrics)

    assert_reference("XGBRegressor", fold_metrics["1.0"])
    assert_reference("LightGBM", fold_metrics["0.0"])
    summaries = {alpha: ms.summarize(metrics) for alpha, metrics in fold_metrics.items()}
    reference = summaries["1.0"]
    best = min((alpha for alpha in ALPHAS if alpha not in (1.0, 0.0)),
               key=lambda alpha: (summaries[str(alpha)]["pooled_wape"], alpha))
    best_key = str(best)
    fold_delta = {spec[0]: current["wape"] - baseline["wape"]
                  for spec, current, baseline in zip(ms.FOLDS, fold_metrics[best_key],
                                                     fold_metrics["1.0"], strict=True)}
    route_delta = {key: summaries[best_key]["per_route"][key]["wape"] - value["wape"]
                   for key, value in reference["per_route"].items() if value["wape"] is not None}
    improved = [alpha for alpha in ALPHAS if alpha not in (1.0, 0.0)
                and summaries[str(alpha)]["pooled_wape"] < reference["pooled_wape"]]
    if not improved:
        classification = "ENSEMBLE_REJECTED"
    elif (sum(delta < 0 for delta in fold_delta.values()) >= 2
          and max(route_delta.values()) <= ROUTE_DEGRADATION_THRESHOLD):
        classification = "ENSEMBLE_SUPPORTED"
    else:
        classification = "ENSEMBLE_MIXED"
    pooled = [np.concatenate([part[i] for part in pooled_arrays]) for i in range(4)]
    diagnostics["pooled"] = complementarity(*pooled)
    result = {
        "experiment": "CONTROLLED_WEIGHTED_MODEL_ENSEMBLE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {path.relative_to(ms.ROOT).as_posix(): ms.sha256(path)
                          for path in (ms.DATA_PATH, ms.JAN_AUG_PATH, ms.SEP_OCT_PATH,
                                       rw.HPO_PATH, *previous_paths, Path(ms.__file__),
                                       Path(rw.__file__), Path(__file__))},
        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                        "pandas": pd.__version__, "xgboost": xgboost.__version__,
                        "lightgbm": lightgbm.__version__},
        "features": list(ms.FEATURE_CONFIGURATIONS[rw.CONFIGURATION]),
        "categorical_features": list(ms.CATEGORICAL),
        "parameters": parameters,
        "weighting": "exp(-ln(2) * age_days / 180); origin=max(each fold train date)",
        "postprocessing": "floor(max(raw_blend, 0) + 0.5); route 5 = 0",
        "folds": [{"name": f[0], "train_period": [f[1], f[2]],
                   "validation_period": [f[3], f[4]]} for f in ms.FOLDS],
        "alphas": list(ALPHAS), "fold_metrics": fold_metrics, "summaries": summaries,
        "complementarity": diagnostics, "best_blend_alpha": best,
        "best_delta_pooled_wape_vs_xgb": summaries[best_key]["pooled_wape"] - reference["pooled_wape"],
        "best_fold_delta_wape_vs_xgb": fold_delta,
        "best_route_delta_pooled_wape_vs_xgb": route_delta,
        "route_degradation_threshold": ROUTE_DEGRADATION_THRESHOLD,
        "classification_rule": (
            "SUPPORTED if a fixed blend improves pooled WAPE, improves at least two folds, "
            "and no nonzero-target route worsens by more than 0.01 absolute WAPE; "
            "REJECTED if no fixed blend improves pooled WAPE; otherwise MIXED"
        ),
        "classification": classification,
        "reference_checks": "Exact fold and per-route absolute errors reproduce prior weighted D results",
        "raw_predictions_path": PREDICTIONS.relative_to(ms.ROOT).as_posix(),
        "nov_dec_used": False, "final_fit_performed": False,
        "accepted_feature_registry_changed": False,
    }
    # Write outputs only after all contract and standalone reference checks succeed.
    pd.concat(raw_frames, ignore_index=True).to_csv(PREDICTIONS, index=False,
                                                      compression="gzip", float_format="%.17g")
    result["raw_predictions_sha256"] = ms.sha256(PREDICTIONS)
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run_experiment()
    for alpha in ALPHAS:
        print(f"XGB alpha={alpha:.2f}: pooled WAPE={result['summaries'][str(alpha)]['pooled_wape']:.6f}")
    print(f"Best blend alpha={result['best_blend_alpha']:.2f}; {result['classification']}")
