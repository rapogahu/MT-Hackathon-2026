"""Leakage-aware target-history feature builders for temporal experiments."""

from __future__ import annotations

import pandas as pd

KEYS = ("route", "date", "hour")
H19_NAME = "route_weekday_hour_historical_median"
H20_NAME = "route_weekday_hour_historical_mean"
H21_NAME = "median_last_4_same_weekday_hour"
H22_NAME = "mean_last_4_same_weekday_hour"
H23_NAME = "route_recent_4w_mean"
H24_NAME = "route_previous_4w_mean"
H25_NAME = "route_recent_vs_previous_diff"


class RouteWeekdayHourHistoricalMedian:
    """H19: past-only train median and Jan-Aug-frozen validation median."""

    @staticmethod
    def build_train(train_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        if not train_rows[["route", "date", "hour"]].equals(history[["route", "date", "hour"]]):
            raise ValueError("Train history must align with train keys")
        if history["date"].max() > pd.Timestamp("2025-08-31"):
            raise ValueError("Train history extends beyond forecast origin")
        ordered = history.assign(weekday=history["date"].dt.weekday)
        if not ordered.sort_values(["route", "date", "hour"]).index.equals(ordered.index):
            raise ValueError("Train history must be in chronological order within route")
        values = ordered.groupby(["route", "weekday", "hour"], sort=False)["boardings"].transform(
            lambda group: group.shift(1).expanding(min_periods=1).median()
        )
        values.loc[history["route"].eq(5)] = float("nan")
        return values.rename(H19_NAME)

    @staticmethod
    def build_validation(validation_keys: pd.DataFrame, frozen_history: pd.DataFrame) -> pd.Series:
        if "boardings" in validation_keys:
            raise ValueError("Validation feature builder accepts keys only")
        if frozen_history.empty or frozen_history["date"].max() != pd.Timestamp("2025-08-31"):
            raise ValueError("Validation history must end at 2025-08-31")
        if validation_keys["date"].min() <= frozen_history["date"].max():
            raise ValueError("Validation keys overlap target history")
        past = frozen_history.loc[frozen_history["route"].ne(5)].assign(
            weekday=lambda frame: frame["date"].dt.weekday
        )
        medians = past.groupby(["route", "weekday", "hour"])["boardings"].median()
        query = pd.MultiIndex.from_arrays(
            [validation_keys["route"], validation_keys["date"].dt.weekday, validation_keys["hour"]],
            names=["route", "weekday", "hour"],
        )
        return pd.Series(medians.reindex(query).to_numpy(), index=validation_keys.index,
                         name=H19_NAME, dtype="float64")


class RouteWeekdayHourHistoricalMean:
    """H20: past-only train mean and Jan-Aug-frozen validation mean."""

    @staticmethod
    def build_train(train_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        if not train_rows[["route", "date", "hour"]].equals(history[["route", "date", "hour"]]):
            raise ValueError("Train history must align with train keys")
        if history["date"].max() > pd.Timestamp("2025-08-31"):
            raise ValueError("Train history extends beyond forecast origin")
        ordered = history.assign(weekday=history["date"].dt.weekday)
        if not ordered.sort_values(["route", "date", "hour"]).index.equals(ordered.index):
            raise ValueError("Train history must be in chronological order within route")
        values = ordered.groupby(["route", "weekday", "hour"], sort=False)["boardings"].transform(
            lambda group: group.shift(1).expanding(min_periods=1).mean()
        )
        values.loc[history["route"].eq(5)] = float("nan")
        return values.rename(H20_NAME)

    @staticmethod
    def build_validation(validation_keys: pd.DataFrame, frozen_history: pd.DataFrame) -> pd.Series:
        if "boardings" in validation_keys:
            raise ValueError("Validation feature builder accepts keys only")
        if frozen_history.empty or frozen_history["date"].max() != pd.Timestamp("2025-08-31"):
            raise ValueError("Validation history must end at 2025-08-31")
        if validation_keys["date"].min() <= frozen_history["date"].max():
            raise ValueError("Validation keys overlap target history")
        past = frozen_history.loc[frozen_history["route"].ne(5)].assign(
            weekday=lambda frame: frame["date"].dt.weekday
        )
        means = past.groupby(["route", "weekday", "hour"])["boardings"].mean()
        query = pd.MultiIndex.from_arrays(
            [validation_keys["route"], validation_keys["date"].dt.weekday, validation_keys["hour"]],
            names=["route", "weekday", "hour"],
        )
        return pd.Series(means.reindex(query).to_numpy(), index=validation_keys.index,
                         name=H20_NAME, dtype="float64")


class MedianLast4SameWeekdayHour:
    """H21: median of up to four prior group observations, frozen for validation."""

    @staticmethod
    def build_train(train_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        if not train_rows[["route", "date", "hour"]].equals(history[["route", "date", "hour"]]):
            raise ValueError("Train history must align with train keys")
        if history["date"].max() > pd.Timestamp("2025-08-31"):
            raise ValueError("Train history extends beyond forecast origin")
        ordered = history.assign(weekday=history["date"].dt.weekday)
        if not ordered.sort_values(["route", "date", "hour"]).index.equals(ordered.index):
            raise ValueError("Train history must be in chronological order within route")
        values = ordered.groupby(["route", "weekday", "hour"], sort=False)["boardings"].transform(
            lambda group: group.shift(1).rolling(window=4, min_periods=1).median()
        )
        values.loc[history["route"].eq(5)] = float("nan")
        return values.rename(H21_NAME)

    @staticmethod
    def build_validation(validation_keys: pd.DataFrame, frozen_history: pd.DataFrame) -> pd.Series:
        if "boardings" in validation_keys:
            raise ValueError("Validation feature builder accepts keys only")
        if frozen_history.empty or frozen_history["date"].max() != pd.Timestamp("2025-08-31"):
            raise ValueError("Validation history must end at 2025-08-31")
        if validation_keys["date"].min() <= frozen_history["date"].max():
            raise ValueError("Validation keys overlap target history")
        past = frozen_history.loc[frozen_history["route"].ne(5)].assign(
            weekday=lambda frame: frame["date"].dt.weekday
        )
        if not past.sort_values(["route", "date", "hour"]).index.equals(past.index):
            raise ValueError("Frozen history must be in chronological order within route")
        recent = past.groupby(["route", "weekday", "hour"], sort=False).tail(4)
        medians = recent.groupby(["route", "weekday", "hour"])["boardings"].median()
        query = pd.MultiIndex.from_arrays(
            [validation_keys["route"], validation_keys["date"].dt.weekday, validation_keys["hour"]],
            names=["route", "weekday", "hour"],
        )
        return pd.Series(medians.reindex(query).to_numpy(), index=validation_keys.index,
                         name=H21_NAME, dtype="float64")

    @staticmethod
    def history_counts(
        train_keys: pd.DataFrame, validation_keys: pd.DataFrame, history: pd.DataFrame
    ) -> dict[str, pd.Series]:
        ordered = history.assign(weekday=history["date"].dt.weekday)
        train_count = ordered.groupby(["route", "weekday", "hour"]).cumcount().clip(upper=4)
        train_count.loc[train_keys["route"].eq(5)] = 0
        past = ordered.loc[ordered["route"].ne(5)]
        group_size = past.groupby(["route", "weekday", "hour"]).size().clip(upper=4)
        query = pd.MultiIndex.from_arrays(
            [validation_keys["route"], validation_keys["date"].dt.weekday, validation_keys["hour"]],
            names=["route", "weekday", "hour"],
        )
        valid_count = pd.Series(group_size.reindex(query, fill_value=0).to_numpy(),
                                index=validation_keys.index, dtype="int64")
        return {"train": train_count, "validation": valid_count}


class MeanLast4SameWeekdayHour(MedianLast4SameWeekdayHour):
    """H22: mean of up to four prior group observations, frozen for validation."""

    @staticmethod
    def build_train(train_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        if not train_rows[["route", "date", "hour"]].equals(history[["route", "date", "hour"]]):
            raise ValueError("Train history must align with train keys")
        if history["date"].max() > pd.Timestamp("2025-08-31"):
            raise ValueError("Train history extends beyond forecast origin")
        ordered = history.assign(weekday=history["date"].dt.weekday)
        if not ordered.sort_values(["route", "date", "hour"]).index.equals(ordered.index):
            raise ValueError("Train history must be in chronological order within route")
        values = ordered.groupby(["route", "weekday", "hour"], sort=False)["boardings"].transform(
            lambda group: group.shift(1).rolling(window=4, min_periods=1).mean()
        )
        values.loc[history["route"].eq(5)] = float("nan")
        return values.rename(H22_NAME)

    @staticmethod
    def build_validation(validation_keys: pd.DataFrame, frozen_history: pd.DataFrame) -> pd.Series:
        if "boardings" in validation_keys:
            raise ValueError("Validation feature builder accepts keys only")
        if frozen_history.empty or frozen_history["date"].max() != pd.Timestamp("2025-08-31"):
            raise ValueError("Validation history must end at 2025-08-31")
        if validation_keys["date"].min() <= frozen_history["date"].max():
            raise ValueError("Validation keys overlap target history")
        past = frozen_history.loc[frozen_history["route"].ne(5)].assign(
            weekday=lambda frame: frame["date"].dt.weekday
        )
        if not past.sort_values(["route", "date", "hour"]).index.equals(past.index):
            raise ValueError("Frozen history must be in chronological order within route")
        recent = past.groupby(["route", "weekday", "hour"], sort=False).tail(4)
        means = recent.groupby(["route", "weekday", "hour"])["boardings"].mean()
        query = pd.MultiIndex.from_arrays(
            [validation_keys["route"], validation_keys["date"].dt.weekday, validation_keys["hour"]],
            names=["route", "weekday", "hour"],
        )
        return pd.Series(means.reindex(query).to_numpy(), index=validation_keys.index,
                         name=H22_NAME, dtype="float64")


class RouteRecent4WeekMean:
    """H23: mean hourly target over 28 complete prior calendar days by route."""

    @staticmethod
    def _daily(history: pd.DataFrame) -> pd.DataFrame:
        daily = history.groupby(["route", "date"], sort=False).agg(
            total=("boardings", "sum"), hours=("boardings", "size")
        ).reset_index()
        if not daily["hours"].eq(24).all():
            raise ValueError("Route-day history must contain all 24 hourly cells")
        if not daily.sort_values(["route", "date"]).index.equals(daily.index):
            raise ValueError("Route-day history must be chronological within route")
        return daily

    @staticmethod
    def _query(rows: pd.DataFrame, daily_values: pd.Series) -> pd.Series:
        query = pd.MultiIndex.from_frame(rows[["route", "date"]])
        return pd.Series(daily_values.reindex(query).to_numpy(), index=rows.index)

    @classmethod
    def build_train(cls, train_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        if not train_rows[["route", "date", "hour"]].equals(history[["route", "date", "hour"]]):
            raise ValueError("Train history must align with train keys")
        if history["date"].max() > pd.Timestamp("2025-08-31"):
            raise ValueError("Train history extends beyond forecast origin")
        daily = cls._daily(history)
        # Shift by a whole route-day: every hour of the current date sees only earlier dates.
        daily["feature"] = daily.groupby("route")["total"].transform(
            lambda group: group.shift(1).rolling(window=28, min_periods=1).mean() / 24
        )
        values = cls._query(train_rows, daily.set_index(["route", "date"])["feature"])
        values.loc[train_rows["route"].eq(5)] = float("nan")
        return values.rename(H23_NAME).astype("float64")

    @classmethod
    def build_validation(cls, validation_keys: pd.DataFrame, frozen_history: pd.DataFrame) -> pd.Series:
        if "boardings" in validation_keys:
            raise ValueError("Validation feature builder accepts keys only")
        if frozen_history.empty or frozen_history["date"].max() != pd.Timestamp("2025-08-31"):
            raise ValueError("Validation history must end at 2025-08-31")
        if validation_keys["date"].min() <= frozen_history["date"].max():
            raise ValueError("Validation keys overlap target history")
        recent_start = pd.Timestamp("2025-08-31") - pd.Timedelta(days=27)
        recent = frozen_history.loc[
            frozen_history["date"].between(recent_start, pd.Timestamp("2025-08-31"))
            & frozen_history["route"].ne(5)
        ]
        cls._daily(recent)
        levels = recent.groupby("route")["boardings"].mean()
        return pd.Series(validation_keys["route"].map(levels).to_numpy(),
                         index=validation_keys.index, name=H23_NAME, dtype="float64")

    @classmethod
    def history_days(
        cls, train_keys: pd.DataFrame, validation_keys: pd.DataFrame, history: pd.DataFrame
    ) -> dict[str, pd.Series]:
        daily = cls._daily(history)
        daily["days"] = daily.groupby("route").cumcount().clip(upper=28)
        train_days = cls._query(train_keys, daily.set_index(["route", "date"])["days"])
        train_days.loc[train_keys["route"].eq(5)] = 0
        valid_days = pd.Series(28, index=validation_keys.index, dtype="int64")
        valid_days.loc[validation_keys["route"].eq(5)] = 0
        return {"train": train_days.astype("int64"), "validation": valid_days}

    @classmethod
    def frozen_route_levels(cls, history: pd.DataFrame) -> dict[str, dict[str, float | None]]:
        recent_start = pd.Timestamp("2025-08-31") - pd.Timedelta(days=27)
        past = history.loc[history["route"].ne(5)]
        recent = past.loc[past["date"].between(recent_start, pd.Timestamp("2025-08-31"))]
        full_level = past.groupby("route")["boardings"].mean()
        recent_level = recent.groupby("route")["boardings"].mean()
        return {
            str(route): {
                "recent_4w_mean": float(recent_level.loc[route]) if route in recent_level else None,
                "jan_aug_mean": float(full_level.loc[route]) if route in full_level else None,
                "relative_shift_pct": float(100 * (recent_level.loc[route] / full_level.loc[route] - 1))
                if route in recent_level and full_level.loc[route] > 0 else None,
            }
            for route in sorted(history["route"].unique())
        }


class RoutePrevious4WeekMean(RouteRecent4WeekMean):
    """H24: mean hourly target in the 28 days preceding the recent 28 days."""

    @classmethod
    def build_train(cls, train_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        if not train_rows[["route", "date", "hour"]].equals(history[["route", "date", "hour"]]):
            raise ValueError("Train history must align with train keys")
        if history["date"].max() > pd.Timestamp("2025-08-31"):
            raise ValueError("Train history extends beyond forecast origin")
        daily = cls._daily(history)
        # At day i, shifted index i-29 ends the interval [i-56, i-28).
        daily["feature"] = daily.groupby("route")["total"].transform(
            lambda group: group.shift(29).rolling(window=28, min_periods=1).mean() / 24
        )
        values = cls._query(train_rows, daily.set_index(["route", "date"])["feature"])
        values.loc[train_rows["route"].eq(5)] = float("nan")
        return values.rename(H24_NAME).astype("float64")

    @classmethod
    def build_validation(cls, validation_keys: pd.DataFrame, frozen_history: pd.DataFrame) -> pd.Series:
        if "boardings" in validation_keys:
            raise ValueError("Validation feature builder accepts keys only")
        if frozen_history.empty or frozen_history["date"].max() != pd.Timestamp("2025-08-31"):
            raise ValueError("Validation history must end at 2025-08-31")
        if validation_keys["date"].min() <= frozen_history["date"].max():
            raise ValueError("Validation keys overlap target history")
        previous = frozen_history.loc[
            frozen_history["date"].between(pd.Timestamp("2025-07-07"), pd.Timestamp("2025-08-03"))
            & frozen_history["route"].ne(5)
        ]
        cls._daily(previous)
        levels = previous.groupby("route")["boardings"].mean()
        return pd.Series(validation_keys["route"].map(levels).to_numpy(),
                         index=validation_keys.index, name=H24_NAME, dtype="float64")

    @classmethod
    def history_days(
        cls, train_keys: pd.DataFrame, validation_keys: pd.DataFrame, history: pd.DataFrame
    ) -> dict[str, pd.Series]:
        daily = cls._daily(history)
        daily["days"] = daily.groupby("route").cumcount().sub(28).clip(lower=0, upper=28)
        train_days = cls._query(train_keys, daily.set_index(["route", "date"])["days"])
        train_days.loc[train_keys["route"].eq(5)] = 0
        valid_days = pd.Series(28, index=validation_keys.index, dtype="int64")
        valid_days.loc[validation_keys["route"].eq(5)] = 0
        return {"train": train_days.astype("int64"), "validation": valid_days}

    @classmethod
    def frozen_route_levels(cls, history: pd.DataFrame) -> dict[str, dict[str, float | None]]:
        past = history.loc[history["route"].ne(5)]
        previous = past.loc[past["date"].between(pd.Timestamp("2025-07-07"), pd.Timestamp("2025-08-03"))]
        recent = past.loc[past["date"].between(pd.Timestamp("2025-08-04"), pd.Timestamp("2025-08-31"))]
        previous_level = previous.groupby("route")["boardings"].mean()
        recent_level = recent.groupby("route")["boardings"].mean()
        levels = {}
        for route in sorted(history["route"].unique()):
            if route not in previous_level or route not in recent_level:
                levels[str(route)] = {
                    "previous_4w_mean": None, "recent_4w_mean": None,
                    "signed_difference_recent_minus_previous": None,
                    "absolute_difference": None, "recent_over_previous": None,
                }
                continue
            before = float(previous_level.loc[route])
            after = float(recent_level.loc[route])
            levels[str(route)] = {
                "previous_4w_mean": before,
                "recent_4w_mean": after,
                "signed_difference_recent_minus_previous": after - before,
                "absolute_difference": abs(after - before),
                "recent_over_previous": after / before if before > 0 else None,
            }
        return levels


class RouteRecentVsPreviousDiff(RoutePrevious4WeekMean):
    """H25: one feature, recent 28-day level minus previous 28-day level."""

    @staticmethod
    def build_train(train_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        recent = RouteRecent4WeekMean.build_train(train_rows, history)
        previous = RoutePrevious4WeekMean.build_train(train_rows, history)
        return (recent - previous).rename(H25_NAME)

    @staticmethod
    def build_validation(validation_keys: pd.DataFrame, frozen_history: pd.DataFrame) -> pd.Series:
        recent = RouteRecent4WeekMean.build_validation(validation_keys, frozen_history)
        previous = RoutePrevious4WeekMean.build_validation(validation_keys, frozen_history)
        return (recent - previous).rename(H25_NAME)

    @classmethod
    def frozen_route_levels(cls, history: pd.DataFrame) -> dict[str, dict[str, float | None]]:
        levels = super().frozen_route_levels(history)
        for route_levels in levels.values():
            route_levels[H25_NAME] = route_levels["signed_difference_recent_minus_previous"]
        return levels


def build_train_lag(
    train_rows: pd.DataFrame,
    history: pd.DataFrame,
    *,
    days: int,
    name: str | None = None,
) -> pd.Series:
    """Build an exact same-route/hour lag; each row reads only earlier targets."""
    if days < 1:
        raise ValueError("days must be positive")
    feature_name = name or f"target_lag_{days}d"
    lookup = history.set_index(["route", "date", "hour"])["boardings"]
    query = pd.MultiIndex.from_arrays(
        [train_rows["route"].to_numpy(), train_rows["date"].sub(pd.Timedelta(days=days)), train_rows["hour"].to_numpy()],
        names=KEYS,
    )
    values = lookup.reindex(query).to_numpy()
    # Enforce availability explicitly, including for callers passing broad history.
    available = history["date"].max() if not history.empty else pd.NaT
    if pd.notna(available) and (train_rows["date"] - pd.Timedelta(days=days) > available).any():
        raise ValueError("Requested lag target is not available in supplied history")
    return pd.Series(values, index=train_rows.index, name=feature_name, dtype="float64")


def build_validation_lag(
    validation_rows: pd.DataFrame,
    frozen_history: pd.DataFrame,
    *,
    days: int,
    name: str | None = None,
) -> pd.Series:
    """Build validation lag using only history ending at the Jan–Aug origin."""
    if days < 1:
        raise ValueError("days must be positive")
    if frozen_history.empty or frozen_history["date"].max() > pd.Timestamp("2025-08-31"):
        raise ValueError("Validation history must be frozen at or before 2025-08-31")
    query_dates = validation_rows["date"] - pd.Timedelta(days=days)
    if (query_dates > frozen_history["date"].max()).any():
        # No recursive predictions are implied: unavailable history remains NaN.
        pass
    lookup = frozen_history.set_index(["route", "date", "hour"])["boardings"]
    query = pd.MultiIndex.from_arrays(
        [validation_rows["route"].to_numpy(), query_dates, validation_rows["hour"].to_numpy()], names=KEYS
    )
    return pd.Series(lookup.reindex(query).to_numpy(), index=validation_rows.index,
                     name=name or f"target_lag_{days}d", dtype="float64")
