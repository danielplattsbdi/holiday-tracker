import pandas as pd
import streamlit as st
import calendar, datetime as dt, html, re, requests

# ================= CONFIG =================
REQUESTS_URL_EDIT = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=231607063"
TEAM_URL_EDIT     = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=1533771603"
BANK_URL_EDIT     = ""  

REQUESTS_URL_EDIT = st.secrets.get("SHEET_URL_REQUESTS", REQUESTS_URL_EDIT)
TEAM_URL_EDIT     = st.secrets.get("SHEET_URL_TEAM", TEAM_URL_EDIT)
BANK_URL_EDIT     = st.secrets.get("SHEET_URL_BANKHOLIDAYS", BANK_URL_EDIT)

LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"

PRIMARY  = "#a31fea"   # Annual Leave
SICK     = "#e6d4fa"   # Sickness tint
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
    try: return pd.read_csv(url)
    except Exception: return pd.DataFrame()

@st.cache_data(ttl=60)
def load_requests() -> pd.DataFrame:
    url = to_csv_export_url(REQUESTS_URL_EDIT)
    df = read_csv(url)
    if df.empty: return df
    df = df.rename(columns=lambda c: str(c).strip())
    for c in ["Team Member","Type","From (Date)","Until (Date)","Office"]:
        if c not in df.columns: df[c] = None
    df["From (Date)"]  = df["From (Date)"].map(_smart_date)
    df["Until (Date)"] = df["Until (Date)"].map(_smart_date)
    def norm_type(x):
        s = str(x).strip().lower()
        if "sick" in s: return "Sickness"
        if any(k in s for k in ["annual","holiday","leave"]): return "Annual Leave"
        return str(x)
    df["Type"] = df["Type"].map(norm_type)
    df = df.dropna(subset=["Team Member","Type","From (Date)","Until (Date)"])
    df = df[df["Until (Date)"] >= df["From (Date)"]]
    return df

@st.cache_data(ttl=300)
def load_team() -> list[str]:
    url = to_csv_export_url(TEAM_URL_EDIT)
    tdf = read_csv(url)
    if not tdf.empty:
        tdf = tdf.rename(columns=lambda c: str(c).strip())
        for col in ["Team Member","Name","Full Name"]:
            if col in tdf.columns:
                names = tdf[col].dropna().astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())
                names = sorted(pd.unique(names).tolist())
                if names: return names
    rdf = load_requests()
    if rdf.empty: return []
    names = rdf["Team Member"].dropna().astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())
    return sorted(pd.unique(names).tolist())

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
    gov = set(gov_idx.to_pydatetime())
    if not BANK_URL_EDIT: return {pd.Timestamp(d) for d in gov}
    url = to_csv_export_url(BANK_URL_EDIT)
    df = read_csv(url)
    if df.empty: return {pd.Timestamp(d) for d in gov}
    sheet_idx = pd.to_datetime(df[df.columns[0]], dayfirst=True, errors="coerce").dropna().dt.normalize()
    sheet = set(sheet_idx.to_pydatetime())
    return {pd.Timestamp(d) for d in (gov.union(sheet))}

def explode_days(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return pd.DataFrame(columns=["Member","Date","Type","Office"])
    out=[]
    for _, r in df.iterrows():
        cur = r["From (Date)"].date(); end = r["Until (Date)"].date()
        while cur <= end:
            out.append({"Member": r["Team Member"], "Date": pd.Timestamp(cur), "Type": r["Type"], "Office": r.get("Office","")})
            cur += dt.timedelta(days=1)
    return pd.DataFrame(out)

# ================= UI HEADER =================
st.set_page_config(page_title="BDI Holiday & Sickness", layout="wide")

st.markdown(f"""
<style>
  .main > div {{max-width: 1100px; margin:auto;}}
  .bdi-header {{
    background:{DARK_HDR}; border-radius:12px; padding:12px 16px;
    display:flex; align-items:center; gap:14px; margin-bottom:12px;
  }}
  .bdi-title {{ color:#fff; font:700 16px system-ui; }}
  table {{ border-collapse:collapse; font-size:12px; }}
  th,td {{ border:1px solid {GRID}; padding:3px 6px; }}
  th {{ background:#fafafa; font-weight:700; position:sticky; top:0; }}
  td:first-child, th:first-child {{ position:sticky; left:0; background:#fff; }}
  .namecell {{ font-weight:600; text-align:left; }}
  .daysleft {{ color:{MUTED}; font-size:11px; }}
</style>
""", unsafe_allow_html=True)

st.markdown(
    f"""
    <div class="bdi-header">
      <img src="{LOGO_URL}" style="height:36px;object-fit:contain">
      <div class="bdi-title">BDI Holiday &amp; Sickness Tracker</div>
    </div>
    """,
    unsafe_allow_html=True
)

# ================= DATA =================
df_req = load_requests()
df_days = explode_days(df_req)
team_members = load_team()
bank_holidays = load_bank_holidays()

now = dt.datetime.now()
years = list(range(now.year-1, now.year+2))

c1, c2, c3 = st.columns([1,1,1])
with c1:
    year = st.selectbox("Year", years, index=years.index(now.year))
with c2:
    month = st.selectbox("Month", list(calendar.month_name)[1:], index=now.month-1)
with c3:
    office_choice = st.selectbox("Office", ["Whole Team","London","Bristol"])

def is_bank_holiday(ts: pd.Timestamp) -> bool:
    return ts.normalize() in bank_holidays

def is_working_day(ts: pd.Timestamp) -> bool:
    return ts.weekday() < 5 and not is_bank_holiday(ts)

def remaining_for(member: str, yr: int) -> float:
    if df_days.empty: return ALLOWANCE
    mask = ((df_days["Member"] == member) &
            (df_days["Type"] == "Annual Leave") &
            (df_days["Date"].dt.year == yr))
    days = df_days.loc[mask, "Date"]
    used = sum(1 for d in days if is_working_day(pd.Timestamp(d)))
    return ALLOWANCE - used

month_index = list(calendar.month_name).index(month)
num_days = calendar.monthrange(year, month_index)[1]
dates = pd.date_range(dt.date(year, month_index, 1), periods=num_days)
today = pd.Timestamp.now().normalize()

# Filter team by office if chosen
if office_choice != "Whole Team" and not df_days.empty:
    members_in_office = df_days.loc[df_days["Office"].str.contains(office_choice, case=False, na=False), "Member"].unique()
    team_members = [m for m in team_members if m in members_in_office]

# ================= RENDER =================
head = ["<th style='min-width:220px;text-align:left'>Member</th>"] + [
    f"<th style='width:28px;background:{WEEKEND if (d.weekday()>=5 or is_bank_holiday(d)) else '#fff'}'>{d.day}</th>"
    for d in dates
]

rows=[]
for m in team_members:
    rem = remaining_for(m, year)
    row = [f"<td class='namecell'>{html.escape(m)}<div class='daysleft'>{rem:.0f} days left</div></td>"]
    md = df_days[df_days["Member"]==m]
    for d in dates:
        is_bh = is_bank_holiday(d)
        bg = WEEKEND if (d.weekday()>=5 or is_bh) else "#fff"
        border = f"2px dashed {MUTED}" if d==today else GRID
        rec = md[md["Date"]==d]
        if not rec.empty and (d.weekday()<5 and not is_bh):
            t = rec.iloc[0]["Type"]
            color = TYPE_COLORS.get(t, PRIMARY)
            text_color = INK if t=="Sickness" else "#fff"
            label = TYPE_LABELS.get(t,"")
            row.append(f"<td style='background:{color};color:{text_color};text-align:center'>{label}</td>")
        else:
            row.append(f"<td style='background:{bg};border:1px solid {border}'></td>")
    rows.append("<tr>"+"".join(row)+"</tr>")

st.markdown(f"<table><tr>{''.join(head)}</tr>{''.join(rows)}</table>", unsafe_allow_html=True)

st.markdown(
    f"""
    <div style='margin-top:10px;'>
      <b>Legend:</b>
      <span style='background:{PRIMARY};color:#fff;padding:2px 6px;border-radius:4px;'>AL</span> Annual Leave &nbsp;
      <span style='background:{SICK};color:{INK};padding:2px 6px;border-radius:4px;'>S</span> Sickness &nbsp;
      <span style='display:inline-block;width:18px;height:14px;background:{WEEKEND};border:1px solid {GRID};border-radius:3px;'></span>
      Weekend / Bank holiday
    </div>
    """,
    unsafe_allow_html=True
)
