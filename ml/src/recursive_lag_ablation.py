"""Controlled feature ablation of the validated recursive weekly-lag protocol."""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import lightgbm
import numpy as np
import pandas as pd

import model_selection as ms
import recursive_lag_experiment as recursive
from recency_weighting_experiment import assert_reference_reproduced, load_inputs

ARTIFACT = ms.RESULTS / "recursive_lag_ablation.json"
PRIOR_B = ms.RESULTS / "recursive_lag_168.json"
FEATURES = {
    "A": recursive.FEATURES,
    "B": recursive.FEATURES + ["lag_168"],
    "C": ["route", *ms.CALENDAR_FEATURES, *ms.WEATHER_FEATURES, "lag_168"],
    "D": [*ms.CALENDAR_FEATURES, *ms.WEATHER_FEATURES, "lag_168"],
}
BUCKETS = (("days_1_7", 1, 7), ("days_8_28", 8, 28), ("days_29_61", 29, 61))


def gain_diagnostic(model, features: list[str]) -> dict:
    gains = model.booster_.feature_importance(importance_type="gain")
    index = features.index("lag_168")
    descending = sorted(range(len(gains)), key=lambda i: (-gains[i], i))
    total = float(gains.sum())
    return {"lag_168_gain": float(gains[index]), "rank": descending.index(index) + 1,
            "feature_count": len(features), "total_gain_fraction": float(gains[index] / total) if total else None}


def run_experiment() -> dict:
    _, folds, hpo = load_inputs()
    parameters = hpo["final_configuration"]["parameters"]
    expected = {"objective": "regression_l1", "n_estimators": 400, "max_depth": 8,
                "learning_rate": 0.1, "num_leaves": 15, "min_child_samples": 40}
    if any(parameters.get(key) != value for key, value in expected.items()):
        raise ValueError("Frozen tuned LightGBM parameters changed")
    previous = json.loads(PRIOR_B.read_text(encoding="utf-8"))
    folds_out = []
    for spec, (train, valid) in zip(ms.FOLDS, folds, strict=True):
        actual = valid.boardings.to_numpy(dtype="int64")
        routes = valid.route.to_numpy()
        predictions = {}
        metrics = {}
        diagnostics = {}
        predictions["A"], fit_seconds, inference_seconds = ms.fit_predict(
            train, valid, "calendar_weather", "LightGBM", parameters)
        metrics["A"] = ms.measure(actual, predictions["A"], routes)
        metrics["A"].update(train_seconds=fit_seconds, inference_seconds=inference_seconds)
        for name in ("B", "C", "D"):
            features = FEATURES[name][:-1]
            model, fit_seconds, train_lag = recursive.fit_candidate(train, parameters, features)
            predictions[name], validation_lag, inference_seconds = recursive.recursive_predict(
                model, train, valid.drop(columns="boardings"), features)
            metrics[name] = ms.measure(actual, predictions[name], routes)
            metrics[name].update(train_seconds=fit_seconds, inference_seconds=inference_seconds)
            diagnostics[name] = {"train_lag": train_lag, "validation_lag": validation_lag,
                                 "importance": gain_diagnostic(model, FEATURES[name])}
        day = (valid.date - valid.date.min()).dt.days.to_numpy() + 1
        horizons = {}
        for bucket, low, high in BUCKETS:
            mask = (day >= low) & (day <= high)
            horizons[bucket] = {name: ms.measure(actual[mask], prediction[mask], routes[mask])
                                for name, prediction in predictions.items()}
            for metric in horizons[bucket].values():
                metric.update(train_seconds=0.0, inference_seconds=0.0)
        prior_fold = next(row for row in previous["folds"] if row["fold"] == spec[0])
        for current, prior in ((metrics["A"], prior_fold["reference"]),
                               (metrics["B"], prior_fold["candidate"])):
            if current["absolute_error"] != prior["absolute_error"] or current["per_route"] != prior["per_route"]:
                raise ValueError(f"A/B prior result not reproduced in {spec[0]}")
        for bucket, _, _ in BUCKETS:
            if horizons[bucket]["B"]["absolute_error"] != prior_fold["horizons"][bucket]["candidate"]["absolute_error"]:
                raise ValueError(f"B horizon not reproduced in {spec[0]}, {bucket}")
        folds_out.append({"fold": spec[0], "metrics": metrics, "horizons": horizons,
                          "diagnostics": diagnostics})
    assert_reference_reproduced([row["metrics"]["A"] for row in folds_out], hpo)
    summary = {name: ms.summarize([row["metrics"][name] for row in folds_out]) for name in FEATURES}
    horizons = {bucket: {name: ms.summarize([row["horizons"][bucket][name] for row in folds_out])
                         for name in FEATURES} for bucket, _, _ in BUCKETS}
    for name in FEATURES:
        summary[name]["delta_vs_A"] = summary[name]["pooled_wape"] - summary["A"]["pooled_wape"]
        summary[name]["delta_vs_B"] = summary[name]["pooled_wape"] - summary["B"]["pooled_wape"]
    if summary["C"]["pooled_wape"] < summary["B"]["pooled_wape"] and summary["C"]["pooled_wape"] <= summary["A"]["pooled_wape"]:
        classification = "RECURSIVE_MASKING_SUPPORTED"
    elif summary["C"]["pooled_wape"] >= summary["B"]["pooled_wape"]:
        classification = "RECURSIVE_MASKING_REJECTED"
    else:
        classification = "RECURSIVE_MASKING_MIXED"
    paths = (ms.DATA_PATH, ms.JAN_AUG_PATH, ms.SEP_OCT_PATH, ms.RESULTS / "hyperparameter_tuning.json",
             PRIOR_B, Path(ms.__file__), Path(recursive.__file__), Path(__file__))
    result = {"experiment": "RECURSIVE_LAG168_REPRESENTATION_ABLATION",
              "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_sha256": {path.relative_to(ms.ROOT).as_posix(): ms.sha256(path) for path in paths},
              "environment": {"python": platform.python_version(), "pandas": pd.__version__,
                              "numpy": np.__version__, "lightgbm": lightgbm.__version__},
              "parameters": parameters, "features": FEATURES, "folds": folds_out, "summary": summary,
              "pooled_horizons": horizons, "classification": classification,
              "classification_rule": "SUPPORTED if C improves B and reaches A; REJECTED if C does not improve B; otherwise MIXED",
              "reference_A_and_prior_B_reproduced": True, "final_fit_performed": False,
              "nov_dec_used": False, "accepted_feature_registry_changed": False}
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run_experiment()
    print("Fold WAPE:", {row["fold"]: {name: round(row["metrics"][name]["wape"], 6)
                                       for name in FEATURES} for row in result["folds"]})
    print("Pooled WAPE:", {name: round(result["summary"][name]["pooled_wape"], 6) for name in FEATURES})
    print("Classification:", result["classification"])
