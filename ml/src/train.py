"""Train and save the frozen final Pilot Model v5."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBRegressor


# Make sibling project modules importable for `python -m ml.src.train`.
ML_SRC = Path(__file__).resolve().parent
if str(ML_SRC) not in sys.path:
    sys.path.insert(0, str(ML_SRC))

import model_selection as ms
import final_model_config as config


MODEL_PATH = config.ROOT / "ml/models/pilot_model_v5_xgboost.json"


def main() -> None:
    train = pd.read_csv(
        config.TRAIN_PATH,
        sep=";",
        encoding="utf-8",
        parse_dates=["date"],
        dtype={"temperature_bucket": config.BUCKET_DTYPE},
    )

    if len(train) != config.TRAIN_ROWS:
        raise ValueError(f"Expected {config.TRAIN_ROWS} training rows, got {len(train)}")
    actual_period = (train["date"].min().strftime("%Y-%m-%d"),
                     train["date"].max().strftime("%Y-%m-%d"))
    if actual_period != config.TRAIN_PERIOD:
        raise ValueError(f"Expected training period {config.TRAIN_PERIOD}, got {actual_period}")
    if train.duplicated(list(config.KEYS)).any():
        raise ValueError(f"Duplicate training keys: {config.KEYS}")

    x_train = ms.make_features(train, config.CONFIGURATION, "XGBRegressor")
    if tuple(x_train.columns) != tuple(config.FEATURES):
        raise ValueError("Canonical preprocessing did not produce the frozen feature set")

    age_days = (train["date"].max() - train["date"]).dt.days.to_numpy()
    sample_weight = np.exp(-np.log(2) * age_days / config.HALF_LIFE_DAYS)

    model = XGBRegressor(**config.XGBOOST_PARAMS)
    model.fit(x_train, train["boardings"], sample_weight=sample_weight)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.get_booster().save_model(MODEL_PATH)

    print(f"Training shape: {train.shape}")
    print(f"Feature shape: {x_train.shape}")
    print(f"Date range: {actual_period[0]}..{actual_period[1]}")
    print(f"Features: {x_train.shape[1]}")
    print(
        "Sample weight min/max/mean: "
        f"{sample_weight.min():.12f}/{sample_weight.max():.12f}/{sample_weight.mean():.12f}"
    )
    print(f"Model artifact: {MODEL_PATH.relative_to(config.ROOT).as_posix()}")


if __name__ == "__main__":
    main()
