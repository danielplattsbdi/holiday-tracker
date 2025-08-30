import pandas as pd
import streamlit as st
import calendar, datetime as dt, html, re, requests

# ================= CONFIG =================
REQUESTS_URL_EDIT = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=231607063"
TEAM_URL_EDIT     = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=1533771603"

# Cancellation endpoint (Google Apps Script)
CANCELLATION_ENDPOINT = "https://script.google.com/macros/s/AKfycbxD8IQ2_JU6ajKY4tFUrtGYVhTTRFklCZ2q4RY0ctOKGG3lGriHFH7vhXqTbmRljAH6/exec"
CANCEL_TOKEN          = "adfouehrgounvroung8168evs"

LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"

# Brand / palette
PRIMARY  = "#a31fea"   # Annual Leave
SICK     = "#e5b3f3"   # Sickness (pale purple variant)
WEEKEND  = "#f7f8fb"
MUTED    = "#636672"
INK      = "#25262b"
GRID     = "#e5e6eb"
HEADER   = "#1b1b1b"

TYPE_COLORS = {"Annual Leave": PRIMARY, "Sickness": SICK}
TYPE_LABELS = {"Annual Leave": "AL", "Sickness": "S"}
ALLOWANCE = 25

ENG_WALES_KEY = "england-and-wales"

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
    for c in ["Team Member","Type","From (Date)","Until (Date)","Start Time","End Time","Office","Line Manager"]:
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
def load_team() -> pd.DataFrame:
    url = to_csv_export_url(TEAM_URL_EDIT)
    df = read_csv(url)
    if df.empty: return df
    df = df.rename(columns=lambda c: str(c).strip())
    return df[["Team Member","Office"]].dropna()

@st.cache_data(ttl=86400)
def fetch_govuk_bank_holidays_eng() -> set[pd.Timestamp]:
    try:
        r = requests.get("https://www.gov.uk/bank-holidays.json", timeout=10)
        r.raise_for_status()
        data = r.json()
        events = data.get(ENG_WALES_KEY, {}).get("events", [])
        dates = pd.to_datetime([e["date"] for e in events], errors="coerce").dropna().dt.normalize()
        return set(dates.tolist())
    except Exception:
        return set()

def explode_days(df: pd.DataFrame) -> pd.DataFrame:
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

# ================= UI =================
st.set_page_config(page_title="BDI Holiday & Sickness", layout="wide")

st.markdown(f"""
<style>
  .main > div {{max-width: 1100px; margin-left: auto; margin-right: auto;}}
  header, .css-18ni7ap, .css-1avcm0n {{background:{HEADER} !important;}}
  table {{border-collapse:collapse; font-family:system-ui; font-size:12px;}}
  th,td {{border:1px solid {GRID}; padding:3px 6px;}}
  th {{background:#fafafa; font-weight:700; position:sticky; top:0; z-index:2;}}
  td:first-child, th:first-child {{position:sticky; left:0; background:#fff; z-index:3;}}
  .namecell {{font-weight:600; text-align:left;}}
  .daysleft {{color:{MUTED}; font-size:11px;}}
</style>
""", unsafe_allow_html=True)

col_logo, col_title = st.columns([1,4])
with col_logo:
    st.markdown(
        f'<div style="background:{HEADER};padding:5px;"><img src="{LOGO_URL}" style="width:100%;max-height:60px;object-fit:contain;"></div>',
        unsafe_allow_html=True
    )
with col_title:
    st.markdown("## **BDI Holiday & Sickness Tracker**")
    st.caption("Reach. Recruit. Relocate.")

# Data
df_req = load_requests()
df_team = load_team()
df_days = explode_days(df_req)
bank_holidays = fetch_govuk_bank_holidays_eng()

# Year/month/office filter
now = dt.datetime.now()
years = list(range(now.year-1, now.year+2))
offices = ["Whole Team"] + sorted(df_team["Office"].unique())

c1, c2, c3 = st.columns([1,1,2])
with c1:
    year = st.selectbox("Year", years, index=years.index(now.year))
with c2:
    month = st.selectbox("Month", list(calendar.month_name)[1:], index=now.month-1)
with c3:
    office = st.selectbox("Office", offices)

month_index = list(calendar.month_name).index(month)
dates = pd.date_range(dt.date(year, month_index, 1), periods=calendar.monthrange(year, month_index)[1])
today = pd.Timestamp.now().normalize()

def is_bank_holiday(ts): return ts.normalize() in bank_holidays
def is_working_day(ts): return ts.weekday()<5 and not is_bank_holiday(ts)

def remaining_for(member, yr):
    mask = ((df_days["Member"]==member) & (df_days["Type"]=="Annual Leave") & (df_days["Date"].dt.year==yr))
    days = df_days.loc[mask,"Date"]
    used = sum(1 for d in days if is_working_day(pd.Timestamp(d)))
    return ALLOWANCE - used

# ========== RENDER TABLE ==========
head = ["<th style='min-width:220px;text-align:left'>Member</th>"] + [
    f"<th style='width:28px;background:{WEEKEND if (d.weekday()>=5 or is_bank_holiday(d)) else '#fff'}'>{d.day}</th>"
    for d in dates
]

rows=[]
for _, r in df_team.iterrows():
    if office!="Whole Team" and r["Office"]!=office: 
        continue
    m = r["Team Member"]
    rem = remaining_for(m, year)
    row=[f"<td class='namecell'>{html.escape(m)}<div class='daysleft'>{rem} days left</div></td>"]
    md = df_days[df_days["Member"]==m]
    for d in dates:
        is_bh = is_bank_holiday(d)
        bg = WEEKEND if (d.weekday()>=5 or is_bh) else "#fff"
        border = f"2px dashed {MUTED}" if d==today else GRID
        rec = md[md["Date"]==d]
        if not rec.empty and (d.weekday()<5 and not is_bh):
            t=rec.iloc[0]["Type"]
            color=TYPE_COLORS.get(t,PRIMARY)
            label=TYPE_LABELS.get(t,"")
            row.append(f"<td style='background:{color};color:#fff;text-align:center'>{label}</td>")
        else:
            row.append(f"<td style='background:{bg};border:1px solid {border}'></td>")
    rows.append("<tr>"+"".join(row)+"</tr>")

html_table=f"<table><tr>{''.join(head)}</tr>{''.join(rows)}</table>"
st.markdown(html_table, unsafe_allow_html=True)

# ======= CANCEL FORM =========
st.markdown("### Cancel a Request")
with st.form("cancel_form"):
    c1,c2,c3,c4=st.columns(4)
    with c1: member=st.selectbox("Member", df_req["Team Member"].unique())
    with c2: type_=st.selectbox("Type", df_req["Type"].unique())
    with c3: from_=st.selectbox("From", sorted(df_req["From (Date)"].dt.strftime("%d/%m/%Y").unique()))
    with c4: until=st.selectbox("Until", sorted(df_req["Until (Date)"].dt.strftime("%d/%m/%Y").unique()))
    submitted=st.form_submit_button("Cancel")
    if submitted:
        payload={"token":CANCEL_TOKEN,"member":member,"type":type_,"from":from_,"until":until}
        try:
            r=requests.post(CANCELLATION_ENDPOINT,json=payload,timeout=10)
            st.write("Response:", r.text)
        except Exception as e:
            st.error(f"Failed: {e}")

# Legend
st.markdown(f"""
<div style='margin-top:10px;'>
  <b>Legend:</b>
  <span style='background:{PRIMARY};color:#fff;padding:2px 6px;border-radius:4px;'>AL</span> Annual Leave &nbsp;
  <span style='background:{SICK};color:#000;padding:2px 6px;border-radius:4px;'>S</span> Sickness &nbsp;
  <span style='display:inline-block;width:18px;height:14px;background:{WEEKEND};border:1px solid {GRID};border-radius:3px;vertical-align:middle'></span>
  Weekend / Bank holiday
</div>
""", unsafe_allow_html=True)
