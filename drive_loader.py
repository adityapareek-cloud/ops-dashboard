import io
import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from google.oauth2 import service_account

FOLDER_IDS = {
    "daily":   "1WHWrT_CmPv5sOkXXCx0QQGZ9-KJZP_ES",
    "weekly":  "1QSADMGO7qHF58OwDDxw-vgQGWrqlcPyh",
    "monthly": "1Jhm5dn9N2EMAe-cRxdXd8zTBX6Fapkt-",
}

COMPANIES = [
    "Excl Justlife DTC - Imdaad",
    "Excl Justlife DTC - Connect Resource",
    "Excl Justlife FF - Innovation",
]

COMPANY_LABELS = {
    "Excl Justlife DTC - Imdaad":          "DTC · Imdaad",
    "Excl Justlife DTC - Connect Resource": "DTC · Connect",
    "Excl Justlife FF - Innovation":        "FF · Innovation",
}

SERVICE_CATEGORIES = ["Home Cleaning", "Salon at Home", "Specialty", "Healthcare"]


def _drive_service():
    # Read credentials directly from TOML section
        info = dict(st.secrets["gcp_service_account"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


@st.cache_data(ttl=3600, show_spinner=False)
def _list_folder(folder_id: str) -> list:
    svc = _drive_service()
    files, token = [], None
    while True:
        resp = svc.files().list(
            q=f"'{folder_id}' in parents and mimeType='text/csv' and trashed=false",
            fields="nextPageToken, files(id, name)",
            pageToken=token,
            pageSize=200,
        ).execute()
        files.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return sorted(files, key=lambda f: f["name"], reverse=True)


@st.cache_data(ttl=3600, show_spinner=False)
def _read_csv(file_id: str) -> pd.DataFrame:
    svc = _drive_service()
    data = svc.files().get_media(fileId=file_id).execute()
    return pd.read_csv(io.BytesIO(data))


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["dim_master_date"] = pd.to_datetime(df["dim_master_date"])
    df["total_cancellations"] = (
        df.get("same_day_cancel_bookings", 0).fillna(0)
        + df.get("na_cancelled", 0).fillna(0)
        + df.get("cancellation_and_release", 0).fillna(0)
    )
    elig = df.get("eligible_hour_hc", pd.Series(dtype=float)).replace(0, float("nan"))
    df["utilization_pct"] = (df.get("duration_hour_hc", 0) / elig * 100).round(1)
    return df[df["dim_company"].isin(COMPANIES)].copy()


def load_daily(days: int = 14) -> pd.DataFrame:
    files = [f for f in _list_folder(FOLDER_IDS["daily"])
             if f["name"].startswith("daily_company_summary")]
    dfs = [_read_csv(f["id"]) for f in files[:days]]
    if not dfs:
        return pd.DataFrame()
    return _enrich(pd.concat(dfs, ignore_index=True))


def load_weekly() -> pd.DataFrame:
    files = [f for f in _list_folder(FOLDER_IDS["weekly"])
             if "company_summary_total" in f["name"]]
    if not files:
        return pd.DataFrame()
    return _enrich(_read_csv(files[0]["id"]))


def load_monthly() -> pd.DataFrame:
    files = [f for f in _list_folder(FOLDER_IDS["monthly"])
             if "company_summary_total" in f["name"]]
    if not files:
        return pd.DataFrame()
    return _enrich(_read_csv(files[0]["id"]))
