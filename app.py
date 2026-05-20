import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

from drive_loader import (
    load_daily, load_weekly, load_monthly,
    COMPANIES, COMPANY_LABELS,
    _list_folder, FOLDER_IDS,
)

st.set_page_config(
    page_title="Ops Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

UAE_TZ = pytz.timezone("Asia/Dubai")

METRICS = [
    ("gmv",                "GMV (AED)",        "currency", False),
    ("bookings_completed", "Deliveries",        "int",      False),
    ("total_cancellations","Cancellations",     "int",      True),
    ("absent_hc",          "Absences (HC)",     "int",      True),
    ("utilization_pct",    "Utilization",       "pct",      False),
]


def fmt_value(val, kind: str) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    if kind == "currency":
        if val >= 1_000_000:
            return f"AED {val / 1_000_000:.2f}M"
        if val >= 1_000:
            return f"AED {val / 1_000:.1f}K"
        return f"AED {val:.0f}"
    if kind == "int":
        return f"{int(val):,}"
    if kind == "pct":
        return f"{val:.1f}%"
    return str(val)


def fmt_delta(curr, prev, inverse: bool):
    if curr is None or prev is None:
        return None, None
    if isinstance(curr, float) and np.isnan(curr):
        return None, None
    if isinstance(prev, float) and np.isnan(prev):
        return None, None
    if prev == 0:
        return None, None
    pct = (curr - prev) / abs(prev) * 100
    sign = "+" if pct >= 0 else ""
    label = f"{sign}{pct:.1f}%"
    color = "inverse" if inverse else "normal"
    return label, color


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    exclude = {"utilization_pct", "total_cancellations"}
    num_cols = [c for c in df.select_dtypes(include="number").columns if c not in exclude]
    result = df.groupby("dim_company")[num_cols].sum().reset_index()
    result["total_cancellations"] = (
        result.get("same_day_cancel_bookings", 0).fillna(0)
        + result.get("na_cancelled", 0).fillna(0)
        + result.get("cancellation_and_release", 0).fillna(0)
    )
    elig = result.get("eligible_hour_hc", pd.Series(dtype=float)).replace(0, float("nan"))
    result["utilization_pct"] = (result.get("duration_hour_hc", 0) / elig * 100).round(1)
    return result


def get_company_row(agg_df: pd.DataFrame, company: str) -> dict:
    if agg_df.empty:
        return {}
    rows = agg_df[agg_df["dim_company"] == company]
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


def render_company_block(company: str, curr_row: dict, prev_row: dict | None):
    label = COMPANY_LABELS[company]
    st.markdown(f"#### {label}")
    for key, display, kind, inverse in METRICS:
        curr_val = curr_row.get(key)
        prev_val = prev_row.get(key) if prev_row else None
        delta_label, delta_color = fmt_delta(curr_val, prev_val, inverse)
        st.metric(
            label=display,
            value=fmt_value(curr_val, kind),
            delta=delta_label,
            delta_color=delta_color if delta_color else "normal",
        )


def render_comparison(curr_df, prev_df):
    curr_agg = aggregate(curr_df)
    prev_agg = aggregate(prev_df) if (prev_df is not None and not prev_df.empty) else pd.DataFrame()
    cols = st.columns(3)
    for col, company in zip(cols, COMPANIES):
        curr_row = get_company_row(curr_agg, company)
        prev_row = get_company_row(prev_agg, company) if not prev_agg.empty else None
        with col:
            render_company_block(company, curr_row, prev_row)


# ── App ───────────────────────────────────────────────────────────────────────

now_uae = datetime.now(UAE_TZ)
today = now_uae.date()
yesterday = today - timedelta(days=1)
days_since_monday = today.weekday()
this_monday = today - timedelta(days=days_since_monday)
days_in_week = days_since_monday + 1

# Sidebar
if st.sidebar.button("Force Refresh Data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption(f"Data as of: {now_uae.strftime('%d %b %Y, %H:%M')} UAE")

with st.sidebar.expander("🔍 Drive diagnostics", expanded=False):
    for label, fid in FOLDER_IDS.items():
        try:
            files = _list_folder(fid)
            st.write(f"**{label}** ({len(files)} files)")
            for f in files[:5]:
                st.caption(f["name"])
            if len(files) > 5:
                st.caption(f"…and {len(files)-5} more")
        except Exception as e:
            st.error(f"{label}: {e}")

# Header
st.title("Ops Dashboard")

# Load data (31 days to cover full month for monthly view)
with st.spinner("Fetching latest data from Drive…"):
    try:
        daily_df   = load_daily(days=31)
        monthly_df = load_monthly()
    except Exception as e:
        st.error(f"Drive error: {e}")
        daily_df = monthly_df = pd.DataFrame()

tab_daily, tab_weekly, tab_monthly = st.tabs(["📅 Daily", "📆 Weekly", "🗓️ Monthly"])

# ── DAILY TAB — yesterday vs same day last week ───────────────────────────────
with tab_daily:
    same_day_lw = yesterday - timedelta(weeks=1)
    st.subheader(f"{yesterday.strftime('%d %b %Y')}")
    st.caption(f"↕ vs {same_day_lw.strftime('%d %b %Y')}")
    st.markdown("---")
    if daily_df.empty:
        st.warning("No daily data loaded. Check your Drive connection.")
    else:
        curr_d = daily_df[daily_df["dim_master_date"].dt.date == yesterday]
        prev_d = daily_df[daily_df["dim_master_date"].dt.date == same_day_lw]
        render_comparison(curr_d, prev_d)

# ── WEEKLY TAB — week to date vs same days last week ─────────────────────────
with tab_weekly:
    last_monday   = this_monday - timedelta(weeks=1)
    last_week_end = last_monday + timedelta(days=days_in_week - 1)
    st.subheader(f"Week to date: {this_monday.strftime('%d %b')} – {today.strftime('%d %b %Y')}")
    st.caption(f"↕ vs same {days_in_week} day(s) last week ({last_monday.strftime('%d %b')} – {last_week_end.strftime('%d %b')})")
    st.markdown("---")
    if daily_df.empty:
        st.warning("No weekly data loaded. Check your Drive connection.")
    else:
        curr_w = daily_df[
            (daily_df["dim_master_date"].dt.date >= this_monday) &
            (daily_df["dim_master_date"].dt.date <= today)
        ]
        prev_w = daily_df[
            (daily_df["dim_master_date"].dt.date >= last_monday) &
            (daily_df["dim_master_date"].dt.date <= last_week_end)
        ]
        render_comparison(curr_w, prev_w)

# ── MONTHLY TAB — current month vs previous month ────────────────────────────
with tab_monthly:
    curr_month_start = today.replace(day=1)
    prev_month_end   = curr_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    st.subheader(f"{today.strftime('%B %Y')} (month to date)")
    st.caption(f"↕ vs {prev_month_end.strftime('%B %Y')}")
    st.markdown("---")
    if daily_df.empty:
        st.warning("No monthly data loaded. Check your Drive connection.")
    else:
        curr_m = daily_df[daily_df["dim_master_date"].dt.date >= curr_month_start]
        if not monthly_df.empty:
            prev_m = monthly_df[
                (monthly_df["dim_master_date"].dt.month == prev_month_end.month) &
                (monthly_df["dim_master_date"].dt.year == prev_month_end.year)
            ]
        else:
            prev_m = daily_df[
                (daily_df["dim_master_date"].dt.date >= prev_month_start) &
                (daily_df["dim_master_date"].dt.date <= prev_month_end)
            ]
        render_comparison(curr_m, prev_m)
