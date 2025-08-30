import pandas as pd
import streamlit as st
import calendar, datetime as dt, html, re, requests

# ================= CONFIG =================
# Google Sheets (edit URLs – we convert them to CSV export)
REQUESTS_URL_EDIT = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=231607063"   # Requests
TEAM_URL_EDIT     = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=1533771603"  # Team
BANK_URL_EDIT     = ""  # optional extra BH tab; leave blank to use only GOV.UK

# Optional overrides via Streamlit Secrets (not required)
REQUESTS_URL_EDIT = st.secrets.get("SHEET_URL_REQUESTS", REQUESTS_URL_EDIT)
TEAM_URL_EDIT     = st.secrets.get("SHEET_URL_TEAM", TEAM_URL_EDIT)
BANK_URL_EDIT     = st.secrets.get("SHEET_URL_BANKHOLIDAYS", BANK_URL_EDIT)

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

# --------- Team roster (authoritative for who appears + their Office) ---------
@st.cache_data(ttl=300)
def load_team_df() -> pd.DataFrame:
    url = to_csv_export_url(TEAM_URL_EDIT)
    raw = read_csv(url).copy()
    raw = raw.rename(columns=lambda c: str(c).strip())

    if raw.empty:
        # No team sheet -> empty roster (UI will show no members)
        return pd.DataFrame(columns=["Member","Office"])

    name_col = next((c for c in ["Team Member","Name","Full Name","Member"] if c in raw.columns), None)
    if name_col is None:
        return pd.DataFrame(columns=["Member","Office"])

    # Office (optional)
    office_col = "Office" if "Office" in raw.columns else None

    out = pd.DataFrame({
        "Member": raw[name_col].astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())
    })
    if office_col:
        out["Office"] = raw[office_col].fillna("Unassigned").astype(str).map(lambda s: s.strip().title())
    else:
        out["Office"] = "Unassigned"

    # Optional Active flag: if present, filter to truthy
    for cand in ["Active","Is Active","Enabled"]:
        if cand in raw.columns:
            mask = raw[cand].astype(str).str.strip().str.lower().isin(["1","true","yes","y"])
            out = out[mask.reindex(raw.index, fill_value=True).values]
            break

    return (out.dropna(subset=["Member"])
               .drop_duplicates("Member")
               .sort_values("Member")
               .reset_index(drop=True))

# --------- Requests (merge Office from Team sheet; form does NOT need Office) ---------
@st.cache_data(ttl=60)
def load_requests() -> pd.DataFrame:
    url = to_csv_export_url(REQUESTS_URL_EDIT)
    df = read_csv(url)
    if df.empty: 
        return df

    df = df.rename(columns=lambda c: str(c).strip())
    for c in ["Team Member","Type","From (Date)","Until (Date)","Line Manager","Notes"]:
        if c not in df.columns: 
            df[c] = None

    # Dates + normalised names/types
    df["From (Date)"]  = df["From (Date)"].map(_smart_date)
    df["Until (Date)"] = df["Until (Date)"].map(_smart_date)
    df["Team Member"]  = df["Team Member"].astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())

    def norm_type(x):
        s = str(x).strip().lower()
        if "sick" in s: return "Sickness"
        if any(k in s for k in ["annual","holiday","leave"]): return "Annual Leave"
        return str(x)
    df["Type"] = df["Type"].map(norm_type)

    # Keep sensible rows
    df = df.dropna(subset=["Team Member","Type","From (Date)","Until (Date)"])
    df = df[df["Until (Date)"] >= df["From (Date)"]]

    # ---- Map Office from Team sheet (authoritative) ----
    team_df = load_team_df()
    df = df.merge(team_df, how="left", left_on="Team Member", right_on="Member")
    df.drop(columns=["Member"], inplace=True, errors="ignore")  # keep 'Office' from team_df
    return df

# ---------- GOV.UK bank holidays (England & Wales only) ----------
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
    if not BANK_URL_EDIT:
        return {pd.Timestamp(d) for d in gov}
    # Optional extra dates from a sheet tab (e.g., company days)
    url = to_csv_export_url(BANK_URL_EDIT)
    df = read_csv(url)
    if df.empty:
        return {pd.Timestamp(d) for d in gov}
    col = next((c for c in df.columns if str(c).strip().lower() in {"date","dates"}), df.columns[0])
    sheet_idx = pd.to_datetime(df[col], dayfirst=True, errors="coerce").dropna().dt.normalize()
    sheet = set(sheet_idx.to_pydatetime())
    return {pd.Timestamp(d) for d in (gov.union(sheet))}

def explode_days(df_req: pd.DataFrame) -> pd.DataFrame:
    """Row per member/day with Type + Office (from Team sheet)."""
    if df_req.empty:
        return pd.DataFrame(columns=["Member","Date","Type","Office"])
    out=[]
    for _, r in df_req.iterrows():
        member = r["Team Member"]
        office = r.get("Office", "Unassigned")
        cur = r["From (Date)"].date()
        end = r["Until (Date)"].date()
        while cur <= end:
            out.append({
                "Member": member,
                "Date": pd.Timestamp(cur),
                "Type": r["Type"],
                "Office": office
            })
            cur += dt.timedelta(days=1)
    return pd.DataFrame(out)

# ================= UI HEADER & LAYOUT =================
st.set_page_config(page_title="BDI Holiday & Sickness", layout="wide")

st.markdown(f"""
<style>
  .main > div {{max-width: 1100px; margin-left: auto; margin-right: auto;}}
  .bdi-header {{
    background:{DARK_HDR}; border-radius:12px; padding:12px 16px;
    display:flex; align-items:center; gap:14px; margin-bottom:12px;
  }}
  .bdi-title {{ color:#fff; font:700 16px system-ui; }}
  table {{ border-collapse:collapse; font-family:system-ui, -apple-system, Segoe UI, Roboto; font-size:12px; }}
  th,td {{ border:1px solid {GRID}; padding:3px 6px; }}
  th {{ background:#fafafa; font-weight:700; position:sticky; top:0; z-index:2; }}
  td:first-child, th:first-child {{ position:sticky; left:0; background:#fff; z-index:3; }}
  .namecell {{ font-weight:600; text-align:left; }}
  .daysleft {{ color:{MUTED}; font-size:11px; }}
  .badge {{ display:inline-block; background:#f1f2f5; border:1px solid {GRID}; border-radius:999px; padding:2px 6px; font-size:11px; color:{MUTED}; margin-left:6px; }}
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

# ================= DATA & CONTROLS =================
df_req  = load_requests()
df_days = explode_days(df_req)
team_df = load_team_df()
bank_holidays = load_bank_holidays()

now = dt.datetime.now()
years = list(range(now.year-1, now.year+2))

# Office options from Team sheet; keep London/Bristol prominent
known = ["London","Bristol"]
team_offices = sorted([o for o in team_df["Office"].dropna().unique() if o not in known and o != "Unassigned"])
office_options = ["Whole Team"] + known + team_offices + (["Unassigned"] if "Unassigned" in team_df["Office"].values else [])

c1, c2, c3 = st.columns([1,1,1])
with c1:
    year = st.selectbox("Year", years, index=years.index(now.year))
with c2:
    month = st.selectbox("Month", list(calendar.month_name)[1:], index=now.month-1)
with c3:
    office_choice = st.selectbox("Office", office_options, index=0)

def is_bank_holiday(ts: pd.Timestamp) -> bool:
    return ts.normalize() in bank_holidays

def is_working_day(ts: pd.Timestamp) -> bool:
    return ts.weekday() < 5 and not is_bank_holiday(ts)

def remaining_for(member: str, yr: int) -> float:
    if df_days.empty: return float(ALLOWANCE)
    mask = ((df_days["Member"] == member) &
            (df_days["Type"] == "Annual Leave") &
            (df_days["Date"].dt.year == yr))
    days = df_days.loc[mask, "Date"]
    used = sum(1 for d in days if is_working_day(pd.Timestamp(d)))
    return float(ALLOWANCE) - used

# Build the month date index
month_index = list(calendar.month_name).index(month)
num_days = calendar.monthrange(year, month_index)[1]
dates = pd.date_range(dt.date(year, month_index, 1), periods=num_days)
today = pd.Timestamp.now().normalize()

# Filter roster by office (from Team sheet)
if office_choice != "Whole Team":
    roster = team_df[team_df["Office"].str.lower() == office_choice.lower()]
else:
    roster = team_df

# Final member list (always from Team sheet)
members = roster["Member"].tolist()

# Fast lookups
days_lookup = {(r["Member"], r["Date"]): r for _, r in df_days.iterrows()}
office_lookup = dict(zip(team_df["Member"], team_df["Office"]))

# ================= RENDER TABLE =================
# header
head = ["<th style='min-width:260px;text-align:left'>Member</th>"] + [
    f"<th style='padding:6px 4px; width:28px; background:{WEEKEND if (d.weekday()>=5 or is_bank_holiday(d)) else '#fff'}'>{d.day}</th>"
    for d in dates
]

rows=[]
for m in members:
    rem = remaining_for(m, year)
    office_badge = office_lookup.get(m, "Unassigned")
    name_html = (
        f"<div style='font-weight:700;color:{INK}'>{html.escape(m)}"
        f"<span class='badge'>{html.escape(office_badge)}</span></div>"
        f"<div class='daysleft'>{rem:.0f} days left</div>"
    )
    row = [f"<td class='namecell'>{name_html}</td>"]

    for d in dates:
        is_bh = is_bank_holiday(d)
        bg = WEEKEND if (d.weekday()>=5 or is_bh) else "#fff"
        border = f"2px dashed {MUTED}" if d==today else GRID
        rec = days_lookup.get((m, d))
        if rec is not None and (d.weekday() < 5 and not is_bh):
            t = rec["Type"]
            color = TYPE_COLORS.get(t, PRIMARY)
            text_color = INK if t=="Sickness" else "#fff"
            label = TYPE_LABELS.get(t, "")
            row.append(f"<td style='background:{color};color:{text_color};text-align:center;width:28px'>{label}</td>")
        else:
            row.append(f"<td style='background:{bg};border:1px solid {border};width:28px'></td>")
    rows.append("<tr>"+"".join(row)+"</tr>")

st.markdown(f"<table><tr>{''.join(head)}</tr>{''.join(rows)}</table>", unsafe_allow_html=True)

# Legend
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
