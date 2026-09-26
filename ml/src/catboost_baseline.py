"""CatBoost baseline on hourly aggregates with a 61-day temporal holdout."""

from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor


ROOT = Path(__file__).resolve().parents[2]
TRAIN_TABLE = ROOT / "data/processed/baseline_train_hourly.csv"
VALIDATION_TABLE = ROOT / "data/processed/baseline_validation_hourly.csv"
FEATURES = ("route", "weekday", "hour")


def calendar_features(rows: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "route": rows["route"].astype(str),
            "weekday": rows["date"].dt.weekday.astype(str),
            "hour": rows["hour"].astype(str),
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

    model = CatBoostRegressor(
        iterations=300,
        depth=6,
        learning_rate=0.1,
        loss_function="MAE",
        random_seed=42,
        thread_count=4,
        verbose=False,
        allow_writing_files=False,
    )
    model.fit(calendar_features(train), train["boardings"], cat_features=list(FEATURES))

    # Validation targets are opened only after the complete forecast is made.
    predictions = np.floor(np.maximum(model.predict(calendar_features(validation_keys)), 0) + 0.5)
    actual = pd.read_csv(VALIDATION_TABLE, sep=";", usecols=["boardings"])["boardings"].to_numpy()
    if len(actual) != len(predictions) or actual.sum() == 0:
        raise ValueError("Invalid validation targets")
    wape = np.abs(actual - predictions).sum() / actual.sum()
    print(f"validation_rows={len(actual)}")
    print(f"wape={wape:.6f}")
    print(f"wape_score={max(0.0, 1.0 - wape):.6f}")


if __name__ == "__main__":
    main()
