import pandas as pd
import streamlit as st
import calendar, datetime as dt, html, re, requests

# ================= CONFIG =================
# Requests tab (gid=231607063)
REQUESTS_URL_EDIT = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=231607063"
# Team tab (roster, gid=1533771603)
TEAM_URL_EDIT     = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=1533771603"
# OPTIONAL: Bank holidays tab (add a tab with a single column 'Date')
BANK_URL_EDIT     = ""  # set in Streamlit Secrets if you create it

# (optional) override via Streamlit Secrets (kept, but not required)
REQUESTS_URL_EDIT = st.secrets.get("SHEET_URL_REQUESTS", REQUESTS_URL_EDIT)
TEAM_URL_EDIT     = st.secrets.get("SHEET_URL_TEAM", TEAM_URL_EDIT)
BANK_URL_EDIT     = st.secrets.get("SHEET_URL_BANKHOLIDAYS", BANK_URL_EDIT)

LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"

# Brand / palette
PRIMARY  = "#a31fea"   # Annual Leave (brand purple)
SICK     = "#e6d4fa"   # Sickness (pale tint of brand purple)
WEEKEND  = "#f7f8fb"
MUTED    = "#636672"
INK      = "#25262b"
GRID     = "#e5e6eb"
DARK_HDR = "#1b1b1b"

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

# ---------- GOV.UK bank holidays (England & Wales only) ----------
ENG_WALES_KEY = "england-and-wales"

@st.cache_data(ttl=86400)  # cache for 1 day
def fetch_govuk_bank_holidays_eng() -> pd.DatetimeIndex:
    """
    Fetch England & Wales bank holidays from GOV.UK JSON feed.
    Returns a normalized DatetimeIndex (no .dt used anywhere). Silent on UI.
    """
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
    """Union of GOV.UK (England & Wales) + optional Sheet tab with extra dates."""
    gov_idx = fetch_govuk_bank_holidays_eng()         # DatetimeIndex
    gov = set(gov_idx.to_pydatetime())                # -> set of python datetimes (naive)
    if not BANK_URL_EDIT:
        return {pd.Timestamp(d) for d in gov}

    # Optional extra/override dates from user sheet
    url = to_csv_export_url(BANK_URL_EDIT)
    df = read_csv(url)
    if df.empty:
        return {pd.Timestamp(d) for d in gov}
    # find a date column
    col = None
    for c in df.columns:
        if str(c).strip().lower() in {"date","dates"}:
            col = c; break
    if col is None:
        col = df.columns[0]
    sheet_idx = pd.to_datetime(df[col], dayfirst=True, errors="coerce").dropna().dt.normalize()
    sheet = set(sheet_idx.to_pydatetime())
    merged = {pd.Timestamp(d) for d in (gov.union(sheet))}
    return merged

def explode_days(df: pd.DataFrame) -> pd.DataFrame:
    """Row per member/day with Type (for display)."""
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

# ================= UI HEADER & LAYOUT =================
st.set_page_config(page_title="BDI Holiday & Sickness", layout="wide")

# Global CSS (header + table polish)
st.markdown(f"""
<style>
  .main > div {{max-width: 1100px; margin-left: auto; margin-right: auto;}}
  .bdi-header {{
    background:{DARK_HDR}; border-radius:12px; padding:12px 16px;
    display:flex; align-items:center; gap:14px; margin-bottom:12px;
  }}
  .bdi-title {{ color:#fff; font:700 16px/1.2 system-ui, -apple-system, Segoe UI, Roboto; }}
  table {{ border-collapse:collapse; font-family:system-ui, -apple-system, Segoe UI, Roboto; font-size:12px; }}
  th,td {{ border:1px solid {GRID}; padding:3px 6px; }}
  th {{ background:#fafafa; font-weight:700; position:sticky; top:0; z-index:2; }}
  td:first-child, th:first-child {{ position:sticky; left:0; background:#fff; z-index:3; }}
  .namecell {{ font-weight:600; text-align:left; }}
  .daysleft {{ color:{MUTED}; font-size:11px; }}
</style>
""", unsafe_allow_html=True)

# Brand header
st.markdown(
    f"""
    <div class="bdi-header">
      <img src="{LOGO_URL}" style="height:36px;object-fit:contain">
      <div class="bdi-title">BDI Holiday &amp; Sickness Tracker</div>
    </div>
    """,
    unsafe_allow_html=True
)

# ================= DATA & CONTROLS =================
df_req = load_requests()
team_members = load_team()
bank_holidays = load_bank_holidays()  # set of normalized pd.Timestamp (naive)

now = dt.datetime.now()
if df_req.empty:
    year_min = now.year - 1
    year_max = now.year + 1
else:
    year_min = int(min(df_req["From (Date)"].dt.year.min(), df_req["Until (Date)"].dt.year.min(), now.year)) - 1
    year_max = int(max(df_req["From (Date)"].dt.year.max(), df_req["Until (Date)"].dt.year.max(), now.year)) + 1

years = list(range(year_min, year_max + 1))
c1, c2 = st.columns([1,1])
with c1:
    year = st.selectbox("Year", years, index=years.index(now.year) if now.year in years else 0)
with c2:
    month = st.selectbox("Month", list(calendar.month_name)[1:], index=now.month-1)

df_days = explode_days(df_req)

def is_bank_holiday(ts: pd.Timestamp) -> bool:
    # ts is naive Timestamp; bank_holidays is a set of naive Timestamps
    return ts.normalize() in bank_holidays

def is_working_day(ts: pd.Timestamp) -> bool:
    """Mon–Fri and not a bank holiday."""
    if ts.weekday() >= 5: return False
    if is_bank_holiday(ts): return False
    return True

def remaining_for(member: str, yr: int) -> float:
    """25 minus AL days in that calendar year, excluding weekends/bank holidays."""
    if df_days.empty: return float(ALLOWANCE)
    mask = (
        (df_days["Member"] == member) &
        (df_days["Type"] == "Annual Leave") &
        (df_days["Date"].dt.year == yr)
    )
    days = df_days.loc[mask, "Date"]
    used = sum(1 for d in days if is_working_day(pd.Timestamp(d)))
    return float(ALLOWANCE) - used

# Month dates
month_index = list(calendar.month_name).index(month)
num_days = calendar.monthrange(year, month_index)[1]
dates = pd.date_range(dt.date(year, month_index, 1), periods=num_days)
today = pd.Timestamp.now().normalize()

# ================= RENDER TABLE =================
# header
head = ["<th style='min-width:220px;text-align:left'>Member</th>"] + [
    f"<th style='padding:6px 4px; width:28px; background:{WEEKEND if (d.weekday()>=5 or is_bank_holiday(d)) else '#fff'}'>{d.day}</th>"
    for d in dates
]

# rows for full team list (even with no requests)
rows = []
for m in team_members:
    rem = remaining_for(m, year)
    row = [f"<td class='namecell'>{html.escape(m)}"
           f"<div class='daysleft'>{rem:.0f} days left</div></td>"]
    # member's records for month (speed-up lookup)
    md = df_days[df_days["Member"]==m]
    for d in dates:
        # weekend / bank holiday shading
        is_bh = is_bank_holiday(d)
        bg = WEEKEND if (d.weekday()>=5 or is_bh) else "#fff"
        border = f"2px dashed {MUTED}" if d==today else GRID

        rec = md[md["Date"]==d]
        if not rec.empty and (d.weekday() < 5 and not is_bh):  # paint only Mon–Fri and not bank holidays
            t = rec.iloc[0]["Type"]
            color = TYPE_COLORS.get(t, PRIMARY)
            # Dark text for pale sickness, white for AL
            text_color = INK if t == "Sickness" else "#fff"
            label = TYPE_LABELS.get(t, "")
            row.append(
                f"<td style='background:{color};color:{text_color};text-align:center;width:28px'>{label}</td>"
            )
        else:
            row.append(f"<td style='background:{bg};border:1px solid {border};width:28px'></td>")
    rows.append("<tr>" + "".join(row) + "</tr>")

html_table = f"""
<table>
  <tr>{"".join(head)}</tr>
  {"".join(rows)}
</table>
"""

st.markdown(html_table, unsafe_allow_html=True)

# Legend (updated colour)
st.markdown(
    f"""
    <div style='margin-top:10px;'>
      <b>Legend:</b>
      <span style='background:{PRIMARY};color:#fff;padding:2px 6px;border-radius:4px;'>AL</span> Annual Leave &nbsp;
      <span style='background:{SICK};color:{INK};padding:2px 6px;border-radius:4px;'>S</span> Sickness &nbsp;
      <span style='display:inline-block;width:18px;height:14px;background:{WEEKEND};border:1px solid {GRID};border-radius:3px;vertical-align:middle'></span>
      Weekend / Bank holiday
    </div>
    """,
    unsafe_allow_html=True
)
