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

# Metrics: key → (display label, format type, delta_inverse)
# delta_inverse=True means "down is good" (cancellations, absences)
METRICS = [
    ("gmv",                      "GMV (AED)",      "currency", False),
    ("bookings_completed",        "Deliveries",      "int",      False),
    ("cancellation_and_release", "Cancellations",   "int",      True),
    ("absent_hc",                "Absent",          "int",      True),
    ("absent_hc_pct",            "Absent %",        "pct",      True),
    ("absent_bd_hc",             "Absent BD",       "int",      True),
    ("absent_bd_pct",            "Absent BD %",     "pct",      True),
    ("utilization_pct",          "Utilization",     "pct",      False),
    ("avg_rating",               "Avg Rating",      "rating",   False),
    ("number_of_active_cleaner", "Active Cleaners", "int",      False),
]


# ── Formatting helpers ────────────────────────────────────────────────────────

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
        return f"{int(round(val)):,}"
    if kind == "pct":
        return f"{val:.1f}%"
    if kind == "rating":
        return f"{val:.2f} ⭐"
    return str(val)


def fmt_delta(curr, prev, inverse: bool):
    """Return (delta_string, delta_color) or (None, None) if not computable."""
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


# ── Aggregation ───────────────────────────────────────────────────────────────

# Columns that must be averaged (not summed) across multiple days
_MEAN_COLS = {"avg_rating", "number_of_active_cleaner"}
# Columns computed separately after groupby
_DERIVED_COLS = {"utilization_pct", "absent_hc_pct", "absent_bd_pct"}

def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    exclude = _MEAN_COLS | _DERIVED_COLS
    num_cols = [c for c in df.select_dtypes(include="number").columns if c not in exclude]

    result = df.groupby("dim_company")[num_cols].sum().reset_index()

    # Utilization: recompute from summed hours
    elig = result.get("eligible_hour_hc", pd.Series(dtype=float)).replace(0, float("nan"))
    result["utilization_pct"] = (result.get("duration_hour_hc", 0) / elig * 100).round(1)

    # Absent % and Absent BD %: sum(absent) / sum(active_cleaners) — correct across all periods
    if "number_of_active_cleaner" in df.columns:
        nc_sum = df.groupby("dim_company")["number_of_active_cleaner"].sum().replace(0, float("nan"))
        for absent_col, pct_col in [("absent_hc", "absent_hc_pct"), ("absent_bd_hc", "absent_bd_pct")]:
            if absent_col in df.columns:
                ab_sum = df.groupby("dim_company")[absent_col].sum()
                pct = (ab_sum / nc_sum * 100).round(1)
                result[pct_col] = result["dim_company"].map(pct)

    # Rating and headcount: average across days (not sum)
    for col in ["avg_rating", "number_of_active_cleaner"]:
        if col in df.columns:
            means = df.groupby("dim_company")[col].mean()
            result[col] = result["dim_company"].map(means)

    result["avg_rating"] = result["avg_rating"].round(2)
    result["number_of_active_cleaner"] = result["number_of_active_cleaner"].round(0)

    return result


def get_company_row(agg_df: pd.DataFrame, company: str) -> dict:
    if agg_df.empty:
        return {}
    rows = agg_df[agg_df["dim_company"] == company]
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


# ── KPI card block for one company ───────────────────────────────────────────

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


# ── Three-company comparison row ─────────────────────────────────────────────

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

# Load data
with st.spinner("Fetching latest data from Drive…"):
    try:
        daily_df   = load_daily(days=31)
        weekly_df  = load_weekly()
        monthly_df = load_monthly()
    except Exception as e:
        st.error(f"Drive error: {e}")
        daily_df = weekly_df = monthly_df = pd.DataFrame()

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

# ── WEEKLY TAB — week to date vs full previous week ──────────────────────────
with tab_weekly:
    last_monday   = this_monday - timedelta(weeks=1)
    last_week_end = last_monday + timedelta(days=6)

    st.subheader(
        f"Week to date: {this_monday.strftime('%d %b')} – {today.strftime('%d %b %Y')}"
    )
    st.caption(
        f"↕ vs last week ({last_monday.strftime('%d %b')} – {last_week_end.strftime('%d %b')})"
    )
    st.markdown("---")

    if daily_df.empty:
        st.warning("No weekly data loaded. Check your Drive connection.")
    else:
        curr_w = daily_df[
            (daily_df["dim_master_date"].dt.date >= this_monday) &
            (daily_df["dim_master_date"].dt.date <= today)
        ]
        if not weekly_df.empty:
            prev_w = weekly_df[
                (weekly_df["dim_master_date"].dt.date >= last_monday) &
                (weekly_df["dim_master_date"].dt.date <= last_week_end)
            ]
        else:
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
        # For previous month use monthly file if available, else daily
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
