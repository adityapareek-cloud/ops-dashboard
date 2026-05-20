import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

from drive_loader import (
    load_daily, load_weekly, load_monthly,
    COMPANIES, COMPANY_LABELS, SERVICE_CATEGORIES,
)

st.set_page_config(
    page_title="Ops Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

UAE_TZ = pytz.timezone("Asia/Dubai")

# Metrics: key → (display label, format type)
# delta_inverse=True means "down is good" (cancellations, absences)
METRICS = [
    ("gmv",                "GMV (AED)",        "currency", False),
    ("bookings_completed", "Deliveries",        "int",      False),
    ("total_cancellations","Cancellations",     "int",      True),
    ("absent_hc",          "Absences (HC)",     "int",      True),
    ("utilization_pct",    "Utilization",       "pct",      False),
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
        return f"{int(val):,}"
    if kind == "pct":
        return f"{val:.1f}%"
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
    # For inverse metrics (cancellations, absences), up = bad = red
    if inverse:
        color = "inverse"
    else:
        color = "normal"
    return label, color


# ── Aggregation ───────────────────────────────────────────────────────────────

def aggregate(df: pd.DataFrame, service_filter: list | None) -> pd.DataFrame:
    if df.empty:
        return df
    if service_filter:
        df = df[df["dim_service_category"].isin(service_filter)]
    if df.empty:
        return df

    # Columns to NOT sum (will recalculate derived ones)
    exclude = {"utilization_pct", "total_cancellations"}
    num_cols = [c for c in df.select_dtypes(include="number").columns if c not in exclude]

    result = df.groupby("dim_company")[num_cols].sum().reset_index()

    # Recalculate derived metrics after aggregation
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

def render_comparison(curr_df, prev_df, service_filter):
    curr_agg = aggregate(curr_df, service_filter)
    prev_agg = aggregate(prev_df, service_filter) if (prev_df is not None and not prev_df.empty) else pd.DataFrame()

    cols = st.columns(3)
    for col, company in zip(cols, COMPANIES):
        curr_row = get_company_row(curr_agg, company)
        prev_row = get_company_row(prev_agg, company) if not prev_agg.empty else None
        with col:
            render_company_block(company, curr_row, prev_row)


# ── App ───────────────────────────────────────────────────────────────────────

now_uae = datetime.now(UAE_TZ)
today = now_uae.date()
days_since_monday = today.weekday()          # Mon=0, Sun=6
this_monday = today - timedelta(days=days_since_monday)
days_in_week = days_since_monday + 1         # 1 on Mon, 5 on Fri

# Sidebar
st.sidebar.title("Filters")
selected_svc = st.sidebar.multiselect(
    "Service Category",
    SERVICE_CATEGORIES,
    default=SERVICE_CATEGORIES,
)
service_filter = selected_svc if selected_svc else None

if st.sidebar.button("Force Refresh Data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption(f"Data as of: {now_uae.strftime('%d %b %Y, %H:%M')} UAE")

# Header
st.title("Ops Dashboard")


# Load data
from drive_loader import _list_folder, FOLDER_IDS
with st.spinner("Fetching latest data from Drive…"):
    try:
        daily_df  = load_daily(days=14)
        weekly_df = load_weekly()
        monthly_df = load_monthly()
    except Exception as e:
        st.error(f"Drive error: {e}")
        daily_df = weekly_df = monthly_df = pd.DataFrame()

with st.sidebar.expander("🔍 Drive diagnostics", expanded=False):
    from googleapiclient.discovery import build
    from google.oauth2 import service_account
    info = dict(st.secrets["gcp_service_account"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    for label, fid in FOLDER_IDS.items():
        try:
            resp = svc.files().list(
                q=f"'{fid}' in parents and trashed=false",
                fields="files(id, name, mimeType)",
                pageSize=20,
            ).execute()
            files = resp.get("files", [])
            st.write(f"**{label}** ({len(files)} files)")
            for f in files:
                st.caption(f"{f['name']} — {f['mimeType']}")
        except Exception as e:
            st.error(f"{label}: {e}")

tab_daily, tab_weekly, tab_monthly = st.tabs(["📅 Daily", "📆 Weekly", "🗓️ Monthly"])

# ── DAILY TAB ────────────────────────────────────────────────────────────────
with tab_daily:
    last_monday    = this_monday - timedelta(weeks=1)
    last_week_end  = last_monday + timedelta(days=days_in_week - 1)

    st.subheader(
        f"Week to date: {this_monday.strftime('%d %b')} – {today.strftime('%d %b %Y')}"
    )
    st.caption(
        f"↕ vs same {days_in_week} day(s) last week "
        f"({last_monday.strftime('%d %b')} – {last_week_end.strftime('%d %b')})"
    )
    st.markdown("---")

    if daily_df.empty:
        st.warning("No daily data loaded. Check your Drive connection.")
    else:
        curr_w = daily_df[
            (daily_df["dim_master_date"].dt.date >= this_monday) &
            (daily_df["dim_master_date"].dt.date <= today)
        ]
        prev_w = daily_df[
            (daily_df["dim_master_date"].dt.date >= last_monday) &
            (daily_df["dim_master_date"].dt.date <= last_week_end)
        ]
        render_comparison(curr_w, prev_w, service_filter)

# ── WEEKLY TAB ───────────────────────────────────────────────────────────────
with tab_weekly:
    if weekly_df.empty:
        st.warning("No weekly data loaded. Check your Drive connection.")
    else:
        periods = sorted(weekly_df["dim_master_date"].dt.date.unique(), reverse=True)
        curr_p = periods[0] if periods else None
        prev_p = periods[1] if len(periods) >= 2 else None

        if curr_p:
            st.subheader(f"Week of {curr_p.strftime('%d %b %Y')}")
            if prev_p:
                st.caption(f"↕ vs week of {prev_p.strftime('%d %b %Y')}")
            st.markdown("---")

            curr_w = weekly_df[weekly_df["dim_master_date"].dt.date == curr_p]
            prev_w = weekly_df[weekly_df["dim_master_date"].dt.date == prev_p] if prev_p else pd.DataFrame()
            render_comparison(curr_w, prev_w if not prev_w.empty else None, service_filter)

# ── MONTHLY TAB ──────────────────────────────────────────────────────────────
with tab_monthly:
    if monthly_df.empty:
        st.warning("No monthly data loaded. Check your Drive connection.")
    else:
        periods = sorted(monthly_df["dim_master_date"].dt.date.unique(), reverse=True)
        curr_p = periods[0] if periods else None
        prev_p = periods[1] if len(periods) >= 2 else None

        if curr_p:
            st.subheader(f"{curr_p.strftime('%B %Y')}")
            if prev_p:
                st.caption(f"↕ vs {prev_p.strftime('%B %Y')}")
            st.markdown("---")

            curr_m = monthly_df[monthly_df["dim_master_date"].dt.date == curr_p]
            prev_m = monthly_df[monthly_df["dim_master_date"].dt.date == prev_p] if prev_p else pd.DataFrame()
            render_comparison(curr_m, prev_m if not prev_m.empty else None, service_filter)
