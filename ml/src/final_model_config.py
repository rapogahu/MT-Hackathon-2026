"""Declarative, frozen configuration for the final Pilot Model v5."""

from model_selection import (
    BUCKET_DTYPE,
    CALENDAR_FEATURES,
    FEATURE_CONFIGURATIONS,
    ROOT,
    ROUTES,
    SET_FEATURES,
    WEATHER_FEATURES,
    XGBOOST_PARAMETERS,
)


CONFIGURATION = "calendar_weather"
FEATURES = FEATURE_CONFIGURATIONS[CONFIGURATION]
KEYS = ("route", "date", "hour")

XGBOOST_PARAMS = {
    **XGBOOST_PARAMETERS,
    "n_estimators": 500,
    "max_depth": 6,
    "learning_rate": 0.1,
    "min_child_weight": 1,
}
HALF_LIFE_DAYS = 180

TRAIN_PATH = ROOT / "data/processed/model_ready_train_2025_jan_oct.csv"
FORECAST_PATH = ROOT / "data/processed/model_ready_forecast_2025_nov_dec.csv"
MODEL_SELECTION_PATH = ROOT / "ml/experiments/results/model_selection.json"
HPO_PATH = ROOT / "ml/experiments/results/hyperparameter_tuning.json"

TRAIN_PERIOD = ("2025-01-01", "2025-10-31")
FORECAST_PERIOD = ("2025-11-01", "2025-12-31")
TRAIN_ROWS = 72_960
FORECAST_ROWS = 14_640
