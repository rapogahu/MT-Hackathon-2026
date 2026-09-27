"""Generate the final Nov-Dec 2025 forecast submission from pilot_v3."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor


ROOT = Path(__file__).resolve().parents[2]
ML_SRC = Path(__file__).resolve().parent

if str(ML_SRC) not in sys.path:
    sys.path.insert(0, str(ML_SRC))


from calendar_temporal_stability import (  # noqa: E402
    FLAGS,
    ROUTES,
    TRAIN_PATH,
    features,
)
from feature_experiment_runner import BASE_FEATURES, MODEL_PARAMETERS  # noqa: E402
from weather_climatology_experiment import FORECAST_PATH  # noqa: E402


SUBMISSION_PATH = ROOT / "dataset" / "test_submission.csv"

TRAIN_START = "2025-01-01"
TRAIN_END = "2025-10-31"
FORECAST_START = "2025-11-01"
FORECAST_END = "2025-12-31"

EXPECTED_TRAIN_ROWS = 72_960
EXPECTED_FORECAST_ROWS = 14_640

BUCKET_LABELS = ("<0", "[0,10)", "[10,20)", ">=20")


def validate_grid(
    rows: pd.DataFrame,
    *,
    start: str,
    end: str,
    expected_rows: int,
    name: str,
) -> None:
    # route x date x hour

    required = {"route", "date", "hour"}

    missing = required - set(rows.columns)
    if missing:
        raise ValueError(
            f"{name}: missing required columns: {sorted(missing)}"
        )

    if len(rows) != expected_rows:
        raise ValueError(
            f"{name}: expected {expected_rows} rows, got {len(rows)}"
        )

    min_date = rows["date"].min()
    max_date = rows["date"].max()

    if min_date != start or max_date != end:
        raise ValueError(
            f"{name}: unexpected date range: "
            f"{min_date} .. {max_date}"
        )

    actual_routes = set(rows["route"].unique())

    if actual_routes != set(ROUTES):
        raise ValueError(
            f"{name}: unexpected routes: {sorted(actual_routes)}"
        )

    actual_hours = set(rows["hour"].unique())

    if actual_hours != set(range(24)):
        raise ValueError(
            f"{name}: hours must be exactly 0..23"
        )

    if rows.duplicated(
        ["route", "date", "hour"]
    ).any():
        raise ValueError(
            f"{name}: duplicate route/date/hour keys"
        )

    expected_days = (
        304 if start == "2025-01-01" else 61
    )

    expected_rows_per_route = expected_days * 24

    for route in ROUTES:
        route_rows = rows.loc[
            rows["route"] == route,
            ["date", "hour"],
        ]

        if len(route_rows) != expected_rows_per_route:
            raise ValueError(
                f"{name}: route {route} has "
                f"{len(route_rows)} rows, expected "
                f"{expected_rows_per_route}"
            )

        if len(set(route_rows["date"])) != expected_days:
            raise ValueError(
                f"{name}: route {route} does not contain "
                f"{expected_days} distinct dates"
            )

        if len(set(route_rows["hour"])) != 24:
            raise ValueError(
                f"{name}: route {route} does not contain "
                f"all 24 hours"
            )


def prepare_features(
    train: pd.DataFrame,
    forecast: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    x_train = features(train, FLAGS)
    x_forecast = features(forecast, FLAGS)

    x_train["temperature_bucket"] = pd.Categorical(
        train["temperature_bucket"],
        categories=BUCKET_LABELS,
    )

    x_forecast["temperature_bucket"] = pd.Categorical(
        forecast["temperature_bucket"],
        categories=BUCKET_LABELS,
    )

    if x_train["temperature_bucket"].isna().any():
        raise ValueError(
            "temperature_bucket значения невалидны"
        )

    if x_forecast["temperature_bucket"].isna().any():
        raise ValueError(
            "temperature_bucket значения невалидны"
        )

    expected_columns = [
        *BASE_FEATURES,
        *FLAGS,
        "temperature_bucket",
    ]

    if x_train.columns.tolist() != expected_columns:
        raise ValueError(
            "Unexpected train feature order:\n"
            f"expected={expected_columns}\n"
            f"actual={x_train.columns.tolist()}"
        )

    if x_forecast.columns.tolist() != expected_columns:
        raise ValueError(
            "Unexpected forecast feature order:\n"
            f"expected={expected_columns}\n"
            f"actual={x_forecast.columns.tolist()}"
        )

    return x_train, x_forecast


def main() -> None:
    if not TRAIN_PATH.exists():
        raise FileNotFoundError(
            f"Train file not found: {TRAIN_PATH}"
        )

    if not FORECAST_PATH.exists():
        raise FileNotFoundError(
            f"Forecast file not found: {FORECAST_PATH}"
        )

    print(f"Train:    {TRAIN_PATH}")
    print(f"Forecast: {FORECAST_PATH}")
    print(f"Output:   {SUBMISSION_PATH}")

    print("\n[1/5] Загрузка тренировочных данных...")

    train = pd.read_csv(
        TRAIN_PATH,
        sep=";",
    )

    print(f"{len(train):,}")

    print("\n[2/5] Загрузка данных прогноза...")

    forecast = pd.read_csv(
        FORECAST_PATH,
        sep=";",
    )

    print(f"Forecast rows: {len(forecast):,}")

    print("\n[3/5] Валидация данных...")

    validate_grid(
        train,
        start=TRAIN_START,
        end=TRAIN_END,
        expected_rows=EXPECTED_TRAIN_ROWS,
        name="train",
    )

    validate_grid(
        forecast,
        start=FORECAST_START,
        end=FORECAST_END,
        expected_rows=EXPECTED_FORECAST_ROWS,
        name="forecast",
    )

    required_train_columns = {
        *BASE_FEATURES,
        *FLAGS,
        "boardings",
        "temperature_bucket",
    }

    required_forecast_columns = {
        *BASE_FEATURES,
        *FLAGS,
        "temperature_bucket",
    }

    missing_train = required_train_columns - set(train.columns)
    if missing_train:
        raise ValueError(
            f"Отсутствующие колонки: {sorted(missing_train)}"
        )

    missing_forecast = required_forecast_columns - set(forecast.columns)
    if missing_forecast:
        raise ValueError(
            f"Отсутствующие колонки: {sorted(missing_forecast)}"
        )
    
    print("\n[4/5] Подготовка признаков...")

    x_train, x_forecast = prepare_features(
        train,
        forecast,
    )

    print("Колонки:")
    for column in x_train.columns:
        print(f"  - {column}")

    categorical_features = [
        *BASE_FEATURES[:-1],
        "temperature_bucket",
    ]

    model = LGBMRegressor(**MODEL_PARAMETERS)

    model.fit(
        x_train,
        train["boardings"],
        categorical_feature=categorical_features,
    )

    print("Модель обучена. Генерация прогноза...")

    raw_prediction = model.predict(x_forecast)

    prediction = np.floor(
        np.maximum(raw_prediction, 0) + 0.5
    ).astype("int64")

    # Exactly the same postprocessing as pilot_model_v3_experiment.py.
    prediction[forecast["route"].to_numpy() == 5] = 0

    if len(prediction) != EXPECTED_FORECAST_ROWS:
        raise ValueError(
            f"Ожидались {EXPECTED_FORECAST_ROWS} прогнозы"
        )

    if (prediction < 0).any():
        raise ValueError(
            "Негативный прогноз"
        )

    print("\n[5/5] Заполнение прогноза...")

    submission = forecast[
        ["route", "date", "hour"]
    ].copy()

    submission["prediction"] = prediction

    submission = submission[
        ["route", "date", "hour", "prediction"]
    ]

    route_5 = submission["route"].eq(5)

    if not (
        submission.loc[route_5, "prediction"] == 0
    ).all():
        raise ValueError(
            "Полагается, что прогноза маршрута 5 равны нулю"
        )

    SUBMISSION_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    submission.to_csv(
        SUBMISSION_PATH,
        sep=";",
        index=False,
    )

    print("\n Готово:")
    print(f"Файл: {SUBMISSION_PATH}")
    print(f"Строки: {len(submission):,}")
    print(
        f"Даты: {submission['date'].min()} "
        f".. {submission['date'].max()}"
    )
    print(
        f"Маршруты: {sorted(submission['route'].unique())}"
    )
    print(
        f"Прогноз минимум: {submission['prediction'].min()}"
    )
    print(
        f"Прогноз максимум: {submission['prediction'].max()}"
    )
    print(
        f"Прогноз среднее: {submission['prediction'].mean():.2f}"
    )


if __name__ == "__main__":
    main()