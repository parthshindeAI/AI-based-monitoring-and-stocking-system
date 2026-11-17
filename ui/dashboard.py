from __future__ import annotations

import smtplib
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from config.settings import settings
from database.inventory_store import (
    INVENTORY_COLUMNS,
    delete_inventory_item,
    get_inventory,
    get_sales_history,
    upsert_inventory,
    upsert_sales_history,
)
from models.predictor import build_inventory_forecast, summarize_inventory
from utils.notifications import get_email_settings, send_restock_alert


st.set_page_config(page_title=settings.APP_NAME, page_icon="📦", layout="wide")


def _render_dashboard() -> None:
    inventory = get_inventory()
    sales = get_sales_history()
    st.title(settings.APP_NAME)
    st.caption("Inventory health, replenishment recommendations, and ML-assisted demand forecasting")

    if inventory.empty:
        st.info("No inventory records yet. Add items on the Inventory page or import an inventory CSV.")
        return

    with st.sidebar:
        st.header("Dashboard filters")
        categories = ["All"] + sorted(inventory["category"].dropna().unique().tolist())
        category = st.selectbox("Category", categories)
        if st.button("Refresh data"):
            st.rerun()

    if category != "All":
        inventory = inventory[inventory["category"] == category]
    forecast = build_inventory_forecast(inventory, sales)
    summary = summarize_inventory(forecast)

    metrics = st.columns(4)
    metrics[0].metric("Inventory items", summary["total_items"])
    metrics[1].metric("Units in stock", f"{summary['total_stock']:,.0f}")
    metrics[2].metric("Inventory value", f"${summary['inventory_value']:,.2f}")
    metrics[3].metric("Urgent restocks", summary["low_stock"])

    alerts = forecast.loc[forecast["risk_level"].isin(["High", "Medium"])].to_dict("records")
    if alerts:
        st.subheader("Inventory alerts")
        for alert in alerts:
            message = (
                f"{alert['item_name']}: {alert['risk_level']} risk — "
                f"{alert['current_stock']:g} units in stock; "
                f"recommended order: {alert['recommended_order_quantity']} units."
            )
            if alert["risk_level"] == "High":
                st.error(message)
            else:
                st.warning(message)

        try:
            email_settings = get_email_settings(st.secrets)
        except StreamlitSecretNotFoundError:
            email_settings = None
        except (TypeError, ValueError) as exc:
            email_settings = None
            st.error(f"Email alerts are misconfigured: {exc}")

        if email_settings is None:
            st.caption("Email alerts are optional. Configure [email] in .streamlit/secrets.toml to enable them.")
        elif st.button("Send restock alert email"):
            try:
                send_restock_alert(email_settings, alerts)
                st.success(f"Restock alert email sent to {email_settings.recipient}.")
            except (OSError, smtplib.SMTPException) as exc:
                st.error(f"Could not send restock alert email: {exc}")

    if not sales.empty:
        ml_items = int(forecast["forecast_method"].str.startswith("ML:").sum())
        st.info(
            f"Forecasting uses Random Forest ML for {ml_items} item(s) with at least "
            f"{28} days of sales history. Other items use a clearly labeled baseline."
        )
    else:
        st.warning(
            "No sales history is loaded. Forecasts use the current daily-demand estimate; "
            "upload dated sales records on the Forecasting page to enable per-item ML training."
        )

    left, right = st.columns(2)
    with left:
        st.subheader("Stock and reorder point")
        st.bar_chart(
            forecast.set_index("item_name")[["current_stock", "reorder_point"]],
            color=["#2E8B57", "#E0A526"],
        )
    with right:
        st.subheader("Predicted daily demand")
        fig = px.bar(
            forecast.sort_values("forecasted_daily_demand", ascending=False),
            x="item_name",
            y="forecasted_daily_demand",
            color="risk_level",
            color_discrete_map={"High": "#D9534F", "Medium": "#E0A526", "Low": "#2E8B57"},
        )
        st.plotly_chart(fig, width="stretch")

    display = forecast[
        [
            "item_name",
            "category",
            "current_stock",
            "reorder_point",
            "forecasted_daily_demand",
            "stock_coverage_days",
            "recommended_order_quantity",
            "risk_level",
            "forecast_method",
        ]
    ].copy()
    display["stock_coverage_days"] = display["stock_coverage_days"].replace(float("inf"), pd.NA).round(1)
    st.subheader("Inventory and restock recommendations")
    st.dataframe(display, width="stretch", hide_index=True)
    st.download_button(
        "Download recommendations (CSV)",
        forecast.to_csv(index=False).encode("utf-8"),
        "restock_recommendations.csv",
        "text/csv",
    )


def _render_inventory_management() -> None:
    st.title("Inventory management")
    st.caption("Inventory records are saved to the local SQLite database.")

    with st.expander("Add inventory item", expanded=False):
        with st.form("add_inventory"):
            name = st.text_input("Item name")
            category = st.text_input("Category", value="General")
            supplier = st.text_input("Supplier")
            stock_col, reorder_col = st.columns(2)
            stock = stock_col.number_input("Current stock", min_value=0.0, step=1.0)
            reorder = reorder_col.number_input("Reorder point", min_value=0.0, step=1.0)
            demand_col, lead_col, price_col = st.columns(3)
            demand = demand_col.number_input("Estimated daily demand", min_value=0.0, step=0.1)
            lead = lead_col.number_input("Supplier lead time (days)", min_value=0.0, step=1.0)
            price = price_col.number_input("Unit price", min_value=0.0, step=1.0)
            submitted = st.form_submit_button("Add item")
        if submitted:
            row = pd.DataFrame(
                [[name, category, stock, reorder, demand, lead, price, supplier]],
                columns=INVENTORY_COLUMNS,
            )
            try:
                upsert_inventory(row)
                st.success(f"Saved {name}.")
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc))

    current = get_inventory()
    if current.empty:
        st.info("There are no inventory records.")
    else:
        st.subheader("Current inventory")
        st.dataframe(current, width="stretch", hide_index=True)
        st.download_button(
            "Download inventory CSV",
            current.to_csv(index=False).encode("utf-8"),
            "inventory.csv",
            "text/csv",
            key="download_inventory",
        )

        with st.expander("Edit or delete an item"):
            selected = st.selectbox("Choose item", current["item_name"].tolist())
            item = current.loc[current["item_name"] == selected].iloc[0]
            with st.form("edit_inventory"):
                edit_category = st.text_input("Category", value=str(item["category"]))
                edit_supplier = st.text_input("Supplier", value=str(item["supplier"]))
                c1, c2 = st.columns(2)
                edit_stock = c1.number_input("Current stock", min_value=0.0, value=float(item["current_stock"]), step=1.0)
                edit_reorder = c2.number_input("Reorder point", min_value=0.0, value=float(item["reorder_point"]), step=1.0)
                c3, c4, c5 = st.columns(3)
                edit_demand = c3.number_input("Estimated daily demand", min_value=0.0, value=float(item["daily_demand"]), step=0.1)
                edit_lead = c4.number_input("Supplier lead time (days)", min_value=0.0, value=float(item["lead_time_days"]), step=1.0)
                edit_price = c5.number_input("Unit price", min_value=0.0, value=float(item["unit_price"]), step=1.0)
                save = st.form_submit_button("Save changes")
            if save:
                updated = pd.DataFrame(
                    [[selected, edit_category, edit_stock, edit_reorder, edit_demand, edit_lead, edit_price, edit_supplier]],
                    columns=INVENTORY_COLUMNS,
                )
                try:
                    upsert_inventory(updated)
                    st.success("Inventory item updated.")
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(str(exc))

            confirm = st.checkbox(f"Confirm deletion of {selected}")
            if st.button("Delete item", type="secondary", disabled=not confirm):
                delete_inventory_item(selected)
                st.success("Inventory item deleted.")
                st.rerun()

    st.subheader("Import inventory CSV")
    st.caption("Required columns: " + ", ".join(INVENTORY_COLUMNS))
    uploaded = st.file_uploader("Choose inventory CSV", type=["csv"], key="inventory_csv")
    if uploaded is not None and st.button("Import inventory", key="import_inventory"):
        try:
            imported = pd.read_csv(uploaded)
            upsert_inventory(imported)
            st.success(f"Imported {len(imported)} inventory record(s). Existing item names were updated.")
            st.rerun()
        except (ValueError, pd.errors.ParserError, OSError) as exc:
            st.error(f"Could not import inventory: {exc}")


def _render_forecasting() -> None:
    st.title("Sales history and forecasting")
    st.write(
        "Upload daily sales history with columns `date`, `item_name`, and `quantity_sold`. "
        "For each item, the app trains a Random Forest regressor on lagged sales and calendar features "
        "when at least 28 calendar days are available."
    )
    sales = get_sales_history()
    if not sales.empty:
        st.metric("Stored daily sales records", len(sales))
        st.dataframe(sales.tail(100), width="stretch", hide_index=True)
        st.download_button(
            "Download sales history CSV",
            sales.to_csv(index=False).encode("utf-8"),
            "sales_history.csv",
            "text/csv",
        )

    st.caption("Repeated date/item rows in an import are rejected. Re-importing an existing date/item updates it.")
    uploaded = st.file_uploader("Choose sales history CSV", type=["csv"], key="sales_csv")
    if uploaded is not None and st.button("Import sales history"):
        try:
            imported = pd.read_csv(uploaded)
            count = upsert_sales_history(imported)
            st.success(f"Imported {count} sales history record(s).")
            st.rerun()
        except (ValueError, pd.errors.ParserError, OSError) as exc:
            st.error(f"Could not import sales history: {exc}")


def render_dashboard() -> None:
    page = st.sidebar.radio("Navigate", ["Dashboard", "Inventory", "Forecasting"])
    try:
        if page == "Dashboard":
            _render_dashboard()
        elif page == "Inventory":
            _render_inventory_management()
        else:
            _render_forecasting()
    except (OSError, sqlite3.Error) as exc:
        st.error(f"Could not access inventory data: {exc}")
