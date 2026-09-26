"""One-off controlled global versus per-route LightGBM architecture comparison."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from lightgbm import LGBMRegressor

from feature_experiment_runner import (
    BASE_FEATURES, MODEL_PARAMETERS, RESULTS, ROUTES, TRAIN_END, TRAIN_LABELS,
    TRAIN_START, VALID_END, VALID_LABELS, VALID_START, _fit_predict, _label_grid,
    calendar_features, wape,
)


LOCAL_FEATURES = ("weekday", "hour", "hour_weekend", "is_night")
CATEGORICAL_FEATURES = ("weekday", "hour", "hour_weekend")
ARTIFACT = RESULTS / "route_specific_lightgbm_v1.json"


def main() -> None:
    train = _label_grid(TRAIN_LABELS, TRAIN_START, TRAIN_END)
    validation = _label_grid(VALID_LABELS, VALID_START, VALID_END)
    assert len(train) == 58_320 and len(validation) == 14_640
    assert train["date"].max() < validation["date"].min()

    # Validation targets remain separate from both model feature matrices.
    validation_keys = validation[["route", "date", "hour"]]
    baseline, baseline_features = _fit_predict(train, validation_keys)
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

    actual = validation["boardings"].to_numpy(dtype=float)
    baseline_wape = wape(actual, baseline)
    candidate_wape = wape(actual, candidate)
    assert abs(baseline_wape - 0.12357994025785918) < 1e-10
    assert np.all(baseline[validation_keys["route"].eq(5)] == 0)
    assert np.all(candidate[validation_keys["route"].eq(5)] == 0)
    denominator = float(np.abs(actual).sum())
    per_route = {}
    for route in ROUTES:
        mask = validation_keys["route"].eq(route).to_numpy()
        route_actual = actual[mask]
        baseline_error = float(np.abs(route_actual - baseline[mask]).sum())
        candidate_error = float(np.abs(route_actual - candidate[mask]).sum())
        per_route[str(route)] = {
            "baseline_wape": wape(route_actual, baseline[mask]),
            "candidate_wape": wape(route_actual, candidate[mask]),
            "baseline_absolute_error": baseline_error,
            "candidate_absolute_error": candidate_error,
            "delta_absolute_error": candidate_error - baseline_error,
            "delta_overall_wape_contribution": (candidate_error - baseline_error) / denominator,
        }
    assert abs(sum(v["delta_overall_wape_contribution"] for v in per_route.values()) - (candidate_wape - baseline_wape)) < 1e-12

    result = {
        "experiment_class": "model_architecture",
        "name": "route_specific_lightgbm_v1",
        "data_sources": [str(TRAIN_LABELS.relative_to(Path(__file__).resolve().parents[2])), str(VALID_LABELS.relative_to(Path(__file__).resolve().parents[2]))],
        "grid_rows": {"train": len(train), "validation": len(validation)},
        "periods": {"train": [TRAIN_START, TRAIN_END], "validation": [VALID_START, VALID_END]},
        "baseline_features": list(baseline_features),
        "candidate_features": list(LOCAL_FEATURES),
        "candidate_categorical_features": list(CATEGORICAL_FEATURES),
        "model_parameters": MODEL_PARAMETERS,
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
        },
        "per_route": per_route,
        "decision": None,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(ARTIFACT), "metrics": result["metrics"], "per_route": per_route}, indent=2))


if __name__ == "__main__":
    main()
