import pandas as pd
import streamlit as st
import calendar, datetime as dt, html, re, requests

# ================= CONFIG =================
# Google Sheets (edit URLs – we convert them to CSV export)
REQUESTS_URL_EDIT = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=231607063"   # Requests
TEAM_URL_EDIT     = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=1533771603"  # Team
BANK_URL_EDIT     = ""  # optional extra BH tab; leave blank to use only GOV.UK

LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"

# Brand / palette
PRIMARY  = "#a31fea"   # Annual Leave (brand purple)
SICK     = "#e6d4fa"   # Sickness (pale brand tint)
WEEKEND  = "#f7f8fb"
MUTED    = "#636672"
INK      = "#25262b"
GRID     = "#e5e6eb"
DARK_HDR = "#1b1b1b"

TYPE_COLORS = {"Annual Leave": PRIMARY, "Sickness": SICK}
TYPE_LABELS = {"Annual Leave": "AL", "Sickness": "S"}
ALLOWANCE = 25  # days per calendar year

# ===== Cancellation backend config =====
CANCELLATION_ENDPOINT = "https://script.google.com/macros/s/AKfycbzXbLxVdJccDz1PdVoRBBJOC5OM0LgIsdEs566AB_J_cNkKK0XTKfD22HQ47z9OF0aB/exec"
CANCEL_TOKEN = "adfouehrgounvroung8168evs"   # <- your shared secret

# ================= HELPERS =================
def to_csv_export_url(edit_url: str) -> str:
    if "/edit?gid=" in edit_url:
        return edit_url.replace("/edit?gid=", "/export?format=csv&gid=")
    if "/edit#gid=" in edit_url:
        return edit_url.replace("/edit#gid=", "/export?format=csv&gid=")
    return edit_url.replace("/edit", "/export?format=csv")

def _smart_date(val):
    if pd.isna(val): return pd.NaT
    s = str(val).strip()
    d = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if pd.notna(d): return d
    n = pd.to_numeric(s, errors="coerce")
    if pd.notna(n):
        return pd.to_datetime(n, unit="d", origin="1899-12-30", errors="coerce")
    return pd.NaT

@st.cache_data(ttl=60)
def read_csv(url: str) -> pd.DataFrame:
    try:
        return pd.read_csv(url)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_team_df() -> pd.DataFrame:
    url = to_csv_export_url(TEAM_URL_EDIT)
    raw = read_csv(url).copy()
    raw = raw.rename(columns=lambda c: str(c).strip())
    if raw.empty:
        return pd.DataFrame(columns=["Member","Office"])
    name_col = next((c for c in ["Team Member","Name","Full Name","Member"] if c in raw.columns), None)
    office_col = "Office" if "Office" in raw.columns else None
    out = pd.DataFrame({"Member": raw[name_col].astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())})
    if office_col:
        out["Office"] = raw[office_col].fillna("Unassigned").astype(str).map(lambda s: s.strip().title())
    else:
        out["Office"] = "Unassigned"
    return out.drop_duplicates("Member").reset_index(drop=True)

@st.cache_data(ttl=60)
def load_requests() -> pd.DataFrame:
    url = to_csv_export_url(REQUESTS_URL_EDIT)
    df = read_csv(url)
    if df.empty: return df
    df = df.rename(columns=lambda c: str(c).strip())
    for c in ["Team Member","Type","From (Date)","Until (Date)","Start Time","End Time","Line Manager"]:
        if c not in df.columns: df[c] = None
    df["From (Date)"]  = df["From (Date)"].map(_smart_date)
    df["Until (Date)"] = df["Until (Date)"].map(_smart_date)
    df["Team Member"]  = df["Team Member"].astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())
    return df.dropna(subset=["Team Member","Type","From (Date)","Until (Date)"])

ENG_WALES_KEY = "england-and-wales"

@st.cache_data(ttl=86400)
def fetch_govuk_bank_holidays_eng() -> pd.DatetimeIndex:
    try:
        r = requests.get("https://www.gov.uk/bank-holidays.json", timeout=10)
        r.raise_for_status()
        data = r.json()
        events = data.get(ENG_WALES_KEY, {}).get("events", [])
        idx = pd.to_datetime([e["date"] for e in events], errors="coerce")
        return idx.dropna().normalize()
    except Exception:
        return pd.DatetimeIndex([])

@st.cache_data(ttl=300)
def load_bank_holidays() -> set[pd.Timestamp]:
    gov_idx = fetch_govuk_bank_holidays_eng()
    return {pd.Timestamp(d) for d in gov_idx.to_pydatetime()}

def explode_days(df_req: pd.DataFrame) -> pd.DataFrame:
    if df_req.empty:
        return pd.DataFrame(columns=["Member","Date","Type","Office"])
    out=[]
    for _, r in df_req.iterrows():
        cur = r["From (Date)"].date()
        end = r["Until (Date)"].date()
        while cur <= end:
            out.append({
                "Member": r["Team Member"],
                "Date": pd.Timestamp(cur),
                "Type": r["Type"],
                "Office": r.get("Office","")
            })
            cur += dt.timedelta(days=1)
    return pd.DataFrame(out)

# ================= UI =================
st.set_page_config(page_title="BDI Holiday & Sickness", layout="wide")
st.markdown(f"<div style='background:{DARK_HDR};padding:12px;border-radius:8px'><img src='{LOGO_URL}' style='height:36px'><span style='color:white;font-weight:700;margin-left:12px'>BDI Holiday & Sickness Tracker</span></div>", unsafe_allow_html=True)

df_req  = load_requests()
df_days = explode_days(df_req)
team_df = load_team_df()
bank_holidays = load_bank_holidays()

# Cancel request UI
st.markdown("### Cancel a request")
if "Type" in df_req.columns:
    df_al = df_req[df_req["Type"].str.lower().str.contains("annual")].copy()
else:
    df_al = pd.DataFrame()

members_all = team_df["Member"].tolist()
m_selected = st.selectbox("Team Member", members_all)

sub = df_al[df_al["Team Member"] == m_selected]
options = []
for _, r in sub.iterrows():
    f = r["From (Date)"].strftime("%d %b %Y")
    u = r["Until (Date)"].strftime("%d %b %Y")
    options.append((f"{m_selected} — {f} → {u}", {
        "member": m_selected,
        "type": "Annual Leave",
        "from": r["From (Date)"].strftime("%d/%m/%Y"),
        "until": r["Until (Date)"].strftime("%d/%m/%Y"),
    }))

if options:
    labels = [o[0] for o in options]
    choice = st.selectbox("Select request", labels)
    chosen_payload = dict(options[labels.index(choice)][1])
    if st.button("Cancel selected request", type="primary"):
        try:
            payload = {**chosen_payload, "token": CANCEL_TOKEN}
            resp = requests.post(CANCELLATION_ENDPOINT, json=payload, timeout=10)
            ok = resp.ok and resp.json().get("ok")
            if ok:
                st.success("Request cancelled. Refresh to update.")
            else:
                st.error(f"Cancellation failed: {resp.text}")
        except Exception as e:
            st.error(f"Error contacting cancellation service: {e}")
else:
    st.info("No Annual Leave requests found for that person.")
