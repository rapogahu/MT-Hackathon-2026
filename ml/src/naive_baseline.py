"""Evaluate a fixed weekly naive forecast on prepared hourly tables."""

import csv
from collections import Counter
from datetime import date, timedelta
from math import floor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data/processed"
TRAIN_TABLE = PROCESSED / "baseline_train_hourly.csv"
VALIDATION_TABLE = PROCESSED / "baseline_validation_hourly.csv"
ROUTES = (1, 5, 7, 11, 12, 17, 25, 26, 28, 50)
TRAIN_START, TRAIN_END = date(2025, 1, 1), date(2025, 8, 31)
VALIDATION_START, VALIDATION_END = date(2025, 9, 1), date(2025, 10, 31)
LOOKBACK_DAYS = 28


def dates(start: date, end: date):
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def read_hourly_grid(path: Path, start: date, end: date):
    """Load a complete prepared grid; raw transactions are not read here."""
    counts = {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if reader.fieldnames != ["route", "date", "hour", "boardings"]:
            raise ValueError(f"Unexpected hourly table schema: {path}")
        for row in reader:
            key = (int(row["route"]), date.fromisoformat(row["date"]), int(row["hour"]))
            value = int(row["boardings"])
            if (
                key in counts
                or key[0] not in ROUTES
                or not start <= key[1] <= end
                or not 0 <= key[2] < 24
                or value < 0
            ):
                raise ValueError(f"Invalid hourly table row: {path}")
            counts[key] = value
    expected = len(ROUTES) * ((end - start).days + 1) * 24
    if len(counts) != expected:
        raise ValueError(f"Incomplete hourly grid: {path}")
    return counts


def fit_weekly_profile(train_counts):
    """Mean of four occurrences of each weekday, with absent cells equal to zero."""
    window_start = TRAIN_END - timedelta(days=LOOKBACK_DAYS - 1)
    totals = Counter()
    for (route, day, hour), target in train_counts.items():
        if window_start <= day <= TRAIN_END:
            totals[(route, day.weekday(), hour)] += target
    return {
        (route, weekday, hour): totals[(route, weekday, hour)] / 4
        for route in ROUTES
        for weekday in range(7)
        for hour in range(24)
    }


def forecast(profile):
    return {
        (route, day, hour): floor(profile[(route, day.weekday(), hour)] + 0.5)
        for day in dates(VALIDATION_START, VALIDATION_END)
        for route in ROUTES
        for hour in range(24)
    }


def main():
    train_counts = read_hourly_grid(TRAIN_TABLE, TRAIN_START, TRAIN_END)

    # Complete the entire pseudo-future forecast before opening validation targets.
    predictions = forecast(fit_weekly_profile(train_counts))
    validation_counts = read_hourly_grid(VALIDATION_TABLE, VALIDATION_START, VALIDATION_END)

    target_sum = sum(validation_counts.values())
    if target_sum == 0:
        raise ValueError("WAPE is undefined for zero validation target sum")
    absolute_error = sum(abs(validation_counts.get(key, 0) - pred) for key, pred in predictions.items())
    wape = absolute_error / target_sum
    print(f"validation_rows={len(predictions)}")
    print(f"wape={wape:.6f}")
    print(f"wape_score={max(0.0, 1.0 - wape):.6f}")


if __name__ == "__main__":
    main()
