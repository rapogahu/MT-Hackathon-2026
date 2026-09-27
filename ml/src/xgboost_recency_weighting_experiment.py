"""Run the shared controlled recency-weighting experiment for tuned XGBoost."""

from pathlib import Path

import model_selection as ms
import recency_weighting_experiment as rw

ARTIFACT = ms.RESULTS / "xgboost_recency_weighting.json"


def run_experiment() -> dict:
    return rw.run_experiment("XGBRegressor", ARTIFACT)


if __name__ == "__main__":
    result = run_experiment()
    for name in rw.WEIGHTING_CONFIGURATIONS:
        print(f"{name}: pooled WAPE={result['summaries'][name]['pooled_wape']:.6f}")
    print(f"Best: {result['best_weighting']}; classification: {result['classification']}")
    print(f"Saved: {ARTIFACT.relative_to(ms.ROOT).as_posix()}")
