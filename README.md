# Ops Dashboard — Setup Guide

Dashboard showing daily/weekly/monthly KPIs (GMV, Deliveries, Cancellations, Absences, Utilization) for DTC Imdaad, DTC Connect, and FF Innovation.

---

## Step 1 — Create a free GitHub account (2 min)
1. Go to **github.com/signup**
2. Use your work email, pick a username, verify your email
3. Done — you now have a place to host the code

---

## Step 2 — Upload this code to GitHub (3 min)
1. Log in to GitHub → click the **+** button (top right) → **New repository**
2. Name it `ops-dashboard`, set it to **Private**, click **Create repository**
3. Click **uploading an existing file**
4. Drag and drop these files from the `ops-dashboard` folder on your Mac:
   - `app.py`
   - `drive_loader.py`
   - `requirements.txt`
   - `.gitignore`
   - The `.streamlit/` folder (with the template `secrets.toml` — the real credentials go in Streamlit Cloud, NOT here)
5. Click **Commit changes**

---

## Step 3 — Set up Google Drive API credentials (15 min)
This gives the dashboard read-only access to your Drive folder.

1. Go to **console.cloud.google.com** (sign in with your Google account)
2. Click **Select a project** (top bar) → **New Project** → name it `ops-dashboard` → **Create**
3. In the search bar, search **"Google Drive API"** → click it → click **Enable**
4. In the left menu go to **IAM & Admin → Service Accounts** → **+ Create Service Account**
   - Name: `ops-dashboard-reader`
   - Click **Create and Continue** → **Done**
5. Click on the service account you just created → **Keys** tab → **Add Key → Create new key** → **JSON** → **Create**
   - A `.json` file downloads to your Mac — keep this safe, it's your credential file
6. Copy the **service account email** (looks like `ops-dashboard-reader@ops-dashboard-xxxxx.iam.gserviceaccount.com`)
7. Go to your **Google Drive folder** → right-click → **Share** → paste the service account email → give **Viewer** access → **Send**

---

## Step 4 — Deploy on Streamlit Community Cloud (5 min)
1. Go to **share.streamlit.io** → sign in with GitHub
2. Click **New app**
3. Select your `ops-dashboard` repo, branch `main`, main file `app.py`
4. Click **Advanced settings → Secrets** — paste the contents of your downloaded `.json` credential file like this:

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."          # copy from the JSON file
private_key_id = "..."
private_key = "..."
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

5. Click **Deploy** — in ~2 minutes you'll have a public URL like `https://your-app.streamlit.app`
6. Share that URL with your team

---

## Step 5 — Auto-refresh at 10 AM (optional, 5 min)
The dashboard auto-refreshes data whenever someone opens it (1-hour cache).
For a true scheduled push at exactly 10 AM UAE time every weekday:

1. Go to **cron-job.org** → create a free account
2. Click **Create cronjob**
   - URL: your Streamlit app URL
   - Schedule: `0 6 * * 1-5` (6 AM UTC = 10 AM UAE, Mon–Fri)
3. Save — this pings your dashboard at 10 AM UAE to wake it up and pull fresh data

---

## How the dashboard works
- **Daily tab** — current week (Mon → today) vs same days last week
- **Weekly tab** — latest full week vs week before
- **Monthly tab** — latest month vs month before
- **Sidebar** — filter by service category (Home Cleaning, Salon at Home, etc.)
- **Force Refresh** button in sidebar — bypasses cache and fetches latest files immediately
- Green/red deltas: green = improvement (↑ GMV, ↑ Deliveries, ↑ Util; ↓ Cancellations, ↓ Absences)
