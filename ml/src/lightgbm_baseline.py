"""LightGBM baseline on hourly aggregates with a 61-day temporal holdout."""

from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor


ROOT = Path(__file__).resolve().parents[2]
TRAIN_TABLE = ROOT / "data/processed/baseline_train_hourly.csv"
VALIDATION_TABLE = ROOT / "data/processed/baseline_validation_hourly.csv"
ROUTES = (1, 5, 7, 11, 12, 17, 25, 26, 28, 50)
FEATURES = ("route", "weekday", "hour")


def calendar_features(rows: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "route": pd.Categorical(rows["route"], categories=ROUTES),
            "weekday": pd.Categorical(rows["date"].dt.weekday, categories=range(7)),
            "hour": pd.Categorical(rows["hour"], categories=range(24)),
        }
    )


def main() -> None:
    train = pd.read_csv(TRAIN_TABLE, sep=";", parse_dates=["date"])
    validation_keys = pd.read_csv(
        VALIDATION_TABLE, sep=";", usecols=["route", "date", "hour"], parse_dates=["date"]
    )
    if len(train) != 58_320 or len(validation_keys) != 14_640:
        raise ValueError("Unexpected hourly grid size")
    if train["date"].max() >= validation_keys["date"].min():
        raise ValueError("Training and validation periods overlap")

    model = LGBMRegressor(
        objective="regression_l1",
        n_estimators=300,
        max_depth=6,
        num_leaves=31,
        learning_rate=0.1,
        random_state=42,
        n_jobs=4,
        verbosity=-1,
    )
    model.fit(calendar_features(train), train["boardings"], categorical_feature=list(FEATURES))

    # Validation targets are opened only after the complete forecast is made.
    predictions = np.floor(np.maximum(model.predict(calendar_features(validation_keys)), 0) + 0.5)
    actual = pd.read_csv(VALIDATION_TABLE, sep=";", usecols=["boardings"])["boardings"].to_numpy()
    if len(actual) != len(predictions) or actual.sum() == 0 or not np.isfinite(predictions).all():
        raise ValueError("Invalid validation targets or predictions")
    wape = np.abs(actual - predictions).sum() / actual.sum()
    print(f"validation_rows={len(actual)}")
    print(f"wape={wape:.6f}")
    print(f"wape_score={max(0.0, 1.0 - wape):.6f}")


if __name__ == "__main__":
    main()
