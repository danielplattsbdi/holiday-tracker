import pandas as pd
import streamlit as st
import calendar, datetime as dt, html, re

# ================= CONFIG =================
# Requests tab (your existing gid=231607063)
REQUESTS_URL_EDIT = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=231607063"
# Team tab (your roster gid=1533771603)
TEAM_URL_EDIT     = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=1533771603"

# (optional) allow overriding via Streamlit Secrets
REQUESTS_URL_EDIT = st.secrets.get("SHEET_URL_REQUESTS", REQUESTS_URL_EDIT)
TEAM_URL_EDIT     = st.secrets.get("SHEET_URL_TEAM", TEAM_URL_EDIT)

LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"

PRIMARY  = "#a31fea"   # Annual Leave
SICK     = "#1feabf"   # Sickness
WEEKEND  = "#f7f8fb"
MUTED    = "#636672"
INK      = "#25262b"
GRID     = "#e5e6eb"
TYPE_COLORS = {"Annual Leave": PRIMARY, "Sickness": SICK}
TYPE_LABELS = {"Annual Leave": "AL", "Sickness": "S"}
ALLOWANCE = 25

# ================= HELPERS =================
def to_csv_export_url(edit_url: str) -> str:
    """Turn a Google Sheets /edit?gid=... (or /edit#gid=...) URL into a CSV export URL."""
    if "/edit?gid=" in edit_url:
        return edit_url.replace("/edit?gid=", "/export?format=csv&gid=")
    if "/edit#gid=" in edit_url:
        return edit_url.replace("/edit#gid=", "/export?format=csv&gid=")
    return edit_url.replace("/edit", "/export?format=csv")

def _smart_date(val):
    """Accept YYYY-MM-DD[ HH:MM:SS], DD/MM/YYYY, and Excel serials."""
    if pd.isna(val): return pd.NaT
    s = str(val).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        d = pd.to_datetime(s, errors="coerce")
        if pd.notna(d): return d
    d = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if pd.notna(d): return d
    n = pd.to_numeric(s, errors="coerce")
    if pd.notna(n):
        d = pd.to_datetime(n, unit="d", origin="1899-12-30", errors="coerce")
        if pd.notna(d): return d
    return pd.NaT

@st.cache_data(ttl=60)
def read_csv(url: str) -> pd.DataFrame:
    try:
        return pd.read_csv(url)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_requests() -> pd.DataFrame:
    url = to_csv_export_url(REQUESTS_URL_EDIT)
    df = read_csv(url)
    if df.empty: return df
    df = df.rename(columns=lambda c: str(c).strip())
    # Ensure required columns exist
    for c in ["Team Member","Type","From (Date)","Until (Date)","Start Time","End Time","Office","Line Manager","Notes"]:
        if c not in df.columns: df[c] = None
    # Dates (robust)
    df["From (Date)"]  = df["From (Date)"].map(_smart_date)
    df["Until (Date)"] = df["Until (Date)"].map(_smart_date)
    # Normalise Type
    def norm_type(x):
        s = str(x).strip().lower()
        if "sick" in s: return "Sickness"
        if any(k in s for k in ["annual","holiday","leave"]): return "Annual Leave"
        return str(x)
    df["Type"] = df["Type"].map(norm_type)
    # Drop rows without essentials
    df = df.dropna(subset=["Team Member","Type","From (Date)","Until (Date)"])
    # Keep sensible ranges
    df = df[df["Until (Date)"] >= df["From (Date)"]]
    return df

@st.cache_data(ttl=300)
def load_team() -> list[str]:
    """Get full roster from Team tab. Fallback to names seen in requests."""
    url = to_csv_export_url(TEAM_URL_EDIT)
    tdf = read_csv(url)
    if not tdf.empty:
        tdf = tdf.rename(columns=lambda c: str(c).strip())
        for col in ["Team Member","Name","Full Name"]:
            if col in tdf.columns:
                names = (tdf[col].dropna().astype(str)
                         .map(lambda s: re.sub(r"\s+"," ",s).strip()))
                names = sorted(pd.unique(names).tolist())
                if names: return names
    # fallback to requests
    rdf = load_requests()
    if rdf.empty: return []
    names = rdf["Team Member"].dropna().astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())
    return sorted(pd.unique(names).tolist())

def explode_days(df: pd.DataFrame) -> pd.DataFrame:
    """Row per member/day with Type."""
    if df.empty:
        return pd.DataFrame(columns=["Member","Date","Type"])
    out=[]
    for _, r in df.iterrows():
        cur = r["From (Date)"].date()
        end = r["Until (Date)"].date()
        while cur <= end:
            out.append({"Member": r["Team Member"], "Date": pd.Timestamp(cur), "Type": r["Type"]})
            cur += dt.timedelta(days=1)
    return pd.DataFrame(out)

# ================= UI HEADER =================
st.set_page_config(page_title="BDI Holiday & Sickness", layout="wide")

col_logo, col_title = st.columns([1,4])
with col_logo:
    st.markdown(
        f'<img src="{LOGO_URL}" style="width:100%;max-height:60px;object-fit:contain;">',
        unsafe_allow_html=True
    )
with col_title:
    st.markdown("### **BDI Holiday & Sickness Tracker**")
    st.caption("Reach. Recruit. Relocate.")

# ================= DATA =================
df_req = load_requests()
team_members = load_team()

# Year/month controls (robust if df empty)
now = dt.datetime.now()
if df_req.empty:
    year_min = now.year - 1
    year_max = now.year + 1
else:
    year_min = int(min(df_req["From (Date)"].dt.year.min(), df_req["Until (Date)"].dt.year.min(), now.year)) - 1
    year_max = int(max(df_req["From (Date)"].dt.year.max(), df_req["Until (Date)"].dt.year.max(), now.year)) + 1

years = list(range(year_min, year_max + 1))
c1, c2 = st.columns(2)
with c1:
    year = st.selectbox("Year", years, index=years.index(now.year) if now.year in years else 0)
with c2:
    month = st.selectbox("Month", list(calendar.month_name)[1:], index=now.month-1)

# ================= TRANSFORM =================
df_days = explode_days(df_req)

def remaining_for(member: str, yr: int) -> int | float:
    if df_days.empty: return ALLOWANCE
    used = df_days[(df_days["Member"]==member) &
                   (df_days["Type"]=="Annual Leave") &
                   (df_days["Date"].dt.year==yr)].shape[0]
    return ALLOWANCE - used

# Month dates
month_index = list(calendar.month_name).index(month)
num_days = calendar.monthrange(year, month_index)[1]
dates = pd.date_range(dt.date(year, month_index, 1), periods=num_days)
today = pd.Timestamp.now().normalize()

# ================= RENDER TABLE =================
# header
head = ["<th>Member</th>"] + [
    f"<th style='padding:4px; background:{WEEKEND if d.weekday()>=5 else '#fff'}'>{d.day}</th>"
    for d in dates
]

# rows for full team list (even with no requests)
rows = []
for m in team_members:
    rem = remaining_for(m, year)
    row = [f"<td style='font-weight:600;text-align:left'>{html.escape(m)}"
           f"<br><small>{rem} days left</small></td>"]
    for d in dates:
        bg = WEEKEND if d.weekday()>=5 else "#fff"
        border = f"2px dashed {MUTED}" if d==today else GRID

        if not df_days.empty:
            rec = df_days[(df_days["Member"]==m) & (df_days["Date"]==d)]
        else:
            rec = pd.DataFrame()

        if not rec.empty:
            t = rec.iloc[0]["Type"]
            color = TYPE_COLORS.get(t, PRIMARY)
            label = TYPE_LABELS.get(t, "")
            row.append(f"<td style='background:{color};color:#fff;text-align:center'>{label}</td>")
        else:
            row.append(f"<td style='background:{bg};border:1px solid {border}'></td>")
    rows.append("<tr>" + "".join(row) + "</tr>")

html_table = f"""
<style>
  table {{ border-collapse:collapse; font-family:system-ui, -apple-system, Segoe UI, Roboto; font-size:12px; }}
  th,td {{ border:1px solid {GRID}; padding:4px; }}
  th {{ background:#fafafa; font-weight:700; position:sticky; top:0; }}
  td:first-child, th:first-child {{ position:sticky; left:0; background:#fff; }}
</style>
<table>
  <tr>{"".join(head)}</tr>
  {"".join(rows)}
</table>
"""

st.markdown(html_table, unsafe_allow_html=True)

# Legend
st.markdown(
    f"""
    <div style='margin-top:1em;'>
      <b>Legend:</b>
      <span style='background:{PRIMARY};color:#fff;padding:2px 6px;border-radius:4px;'>AL</span> Annual Leave &nbsp;
      <span style='background:{SICK};color:#fff;padding:2px 6px;border-radius:4px;'>S</span> Sickness &nbsp;
      <span style='background:{WEEKEND};padding:2px 6px;border:1px solid {GRID};border-radius:4px;'> </span> Weekend
    </div>
    """,
    unsafe_allow_html=True
)
