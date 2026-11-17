from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor


MIN_HISTORY_DAYS = 28
FORECAST_DAYS = 7


def _features(history: list[float], day: pd.Timestamp) -> list[float]:
    return [
        history[-1],
        history[-2],
        history[-7],
        history[-14],
        float(np.mean(history[-7:])),
        float(np.mean(history[-14:])),
        float(day.dayofweek),
        float(day.month),
    ]


def _predict_from_history(history_frame: pd.DataFrame, fallback_demand: float) -> tuple[float, str]:
    if history_frame.empty:
        return max(0.0, float(fallback_demand)), "Baseline (no sales history)"

    daily = history_frame.copy()
    daily["date"] = pd.to_datetime(daily["date"], errors="raise")
    daily = daily.groupby("date", as_index=True)["quantity_sold"].sum().sort_index()
    daily = daily.asfreq("D", fill_value=0.0)
    if len(daily) < MIN_HISTORY_DAYS:
        return max(0.0, float(daily.tail(7).mean())), "7-day average (insufficient history for ML)"

    values = daily.to_numpy(dtype=float).tolist()
    features: list[list[float]] = []
    targets: list[float] = []
    for index in range(14, len(values)):
        features.append(_features(values[:index], daily.index[index]))
        targets.append(values[index])
    if len(features) < 10:
        return max(0.0, float(daily.tail(7).mean())), "7-day average (insufficient training rows)"

    model = RandomForestRegressor(
        n_estimators=80,
        max_depth=6,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=1,
    )
    model.fit(np.asarray(features), np.asarray(targets))

    forecast_history = values.copy()
    future_values: list[float] = []
    for offset in range(1, FORECAST_DAYS + 1):
        next_day = daily.index[-1] + pd.Timedelta(days=offset)
        prediction = max(0.0, float(model.predict([_features(forecast_history, next_day)])[0]))
        future_values.append(prediction)
        forecast_history.append(prediction)
    return float(np.mean(future_values)), "ML: Random Forest (7-day forecast)"


def build_inventory_forecast(
    frame: pd.DataFrame,
    sales_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    forecast = frame.copy()
    sales = sales_history if sales_history is not None else pd.DataFrame(
        columns=["date", "item_name", "quantity_sold"]
    )
    sales_by_item = {
        str(item_name): group
        for item_name, group in sales.groupby("item_name")
    } if not sales.empty else {}

    demand_and_method = forecast.apply(
        lambda row: _predict_from_history(
            sales_by_item.get(str(row["item_name"]), pd.DataFrame()),
            float(row["daily_demand"]),
        ),
        axis=1,
    )
    forecast["forecasted_daily_demand"] = demand_and_method.map(lambda result: result[0])
    forecast["forecast_method"] = demand_and_method.map(lambda result: result[1])
    forecast["stock_coverage_days"] = np.where(
        forecast["forecasted_daily_demand"] > 0,
        forecast["current_stock"] / forecast["forecasted_daily_demand"],
        np.inf,
    )
    forecast["risk_level"] = np.select(
        [
            forecast["current_stock"] <= forecast["reorder_point"],
            forecast["stock_coverage_days"] <= forecast["lead_time_days"],
            forecast["stock_coverage_days"] <= forecast["lead_time_days"] + 7,
        ],
        ["High", "High", "Medium"],
        default="Low",
    )
    forecast["recommended_order_quantity"] = np.ceil(
        np.maximum(
            0,
            forecast["reorder_point"]
            + forecast["forecasted_daily_demand"] * forecast["lead_time_days"]
            - forecast["current_stock"],
        )
    ).astype(int)
    return forecast


def summarize_inventory(frame: pd.DataFrame) -> dict[str, float | int]:
    return {
        "total_items": int(frame.shape[0]),
        "total_stock": float(frame["current_stock"].sum()),
        "inventory_value": float((frame["current_stock"] * frame["unit_price"]).sum()),
        "low_stock": int((frame["risk_level"] == "High").sum()),
        "forecasted_demand_7d": float(frame["forecasted_daily_demand"].sum() * FORECAST_DAYS),
    }
