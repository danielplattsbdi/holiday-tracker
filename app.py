import streamlit as st
import pandas as pd
import numpy as np
import datetime as dt
import calendar, requests

# ============ CONFIG ============
st.set_page_config(layout="wide", page_title="BDI Holiday & Sickness")

LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"
PRIMARY  = "#a31fea"
SICK     = "#1feabf"
INK      = "#25262b"
GRID     = "#e5e6eb"
WEEKEND  = "#f7f8fb"
TODAY    = "#ffd24d"
BANKHOL  = "#e6f2ff"   # light blue shading

TYPE_COLORS = {"Annual Leave": PRIMARY, "Sickness": SICK}
TYPE_LABELS = {"Annual Leave": "AL", "Sickness": "S"}

TZ = "Europe/London"
DAY_START = dt.time(8,30)
DAY_END   = dt.time(17,30)
LUNCH     = dt.time(13,0)

# Replace with your Google Sheet CSV export
SHEET_URL = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/gviz/tq?tqx=out:csv&sheet=Requests"


# ============ FETCH GOV.UK BANK HOLIDAYS ============
@st.cache_data(ttl=86400)
def fetch_govuk_bank_holidays_eng() -> set[pd.Timestamp]:
    """Fetch England & Wales bank holidays from GOV.UK JSON feed."""
    try:
        r = requests.get("https://www.gov.uk/bank-holidays.json", timeout=10)
        r.raise_for_status()
        data = r.json()
        events = data.get("england-and-wales", {}).get("events", [])
        dates = pd.to_datetime([e["date"] for e in events], errors="coerce").dropna().dt.normalize()
        if not dates.empty:
            st.info(f"Fetched {len(dates)} England & Wales bank holidays "
                    f"(first: {dates.min().date()}, last: {dates.max().date()})")
        else:
            st.warning("Fetched GOV.UK feed but no dates parsed")
        return set(dates.tolist())
    except Exception as e:
        st.error(f"Bank holiday fetch failed: {e}")
        return set()

BANK_HOLS = fetch_govuk_bank_holidays_eng()

# ============ LOAD DATA ============
@st.cache_data(ttl=60)
def load_data():
    df = pd.read_csv(SHEET_URL)
    df = df.applymap(lambda v: v.strip() if isinstance(v, str) else v)
    # normalise dates
    for c in ["From (Date)", "Until (Date)"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df

df_requests = load_data()

# Team list (from Team tab if exists)
@st.cache_data(ttl=60)
def load_member_list():
    try:
        url_team = SHEET_URL.replace("Requests", "Team")
        team = pd.read_csv(url_team)
        if "Team Member" in team.columns:
            return sorted(team["Team Member"].dropna().astype(str).unique().tolist())
    except Exception:
        pass
    return sorted(df_requests["Team Member"].dropna().astype(str).unique().tolist())

member_list = load_member_list()

# ============ UTILITIES ============
def explode_days(df):
    out=[]
    for _, r in df.iterrows():
        if pd.isna(r["From (Date)"]) or pd.isna(r["Until (Date)"]):
            continue
        cur = r["From (Date)"].date()
        last = r["Until (Date)"].date()
        while cur <= last:
            load = 1.0
            out.append({
                "Member": r["Team Member"],
                "Date": pd.Timestamp(cur),
                "Type": r["Type"],
                "Office": r.get("Office"),
                "Manager": r.get("Line Manager"),
                "Notes": r.get("Notes"),
                "Load": load
            })
            cur += dt.timedelta(days=1)
    if not out:
        return pd.DataFrame(columns=["Member","Date","Type","Load"])
    return pd.DataFrame(out)

def month_days(year, month):
    first = dt.datetime(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    return pd.date_range(first, dt.datetime(year, month, last_day), freq="D")

def render_month(df, year, month):
    idx = month_days(year, month)
    today = pd.Timestamp.now(tz=TZ).normalize()

    lookup = {(r["Member"], r["Date"].normalize()): r for _, r in df.iterrows()}

    head_cells = "".join(
        f"<th style='padding:4px;color:{INK};border:1px solid {GRID};"
        f"background:{WEEKEND if d.weekday()>=5 else '#fff'}'>{d.strftime('%a %d')}</th>"
        for d in idx
    )

    rows_html = ""
    for m in member_list:
        row = f"<tr><th style='text-align:left;padding:4px;border:1px solid {GRID}'>{m}</th>"
        for d in idx:
            is_wk = d.weekday() >= 5
            is_td = (d.normalize() == today)
            is_bh = d.normalize() in BANK_HOLS
            r = lookup.get((m, d.normalize()))

            base = f"border:1px solid {GRID};height:28px;min-width:28px;text-align:center;font-size:11px;"
            if is_wk or is_bh:
                base += f"background:{WEEKEND};"
            if is_td:
                base += f"outline:2px dashed {PRIMARY};"
            label = ""
            if r is not None:
                color = TYPE_COLORS.get(r["Type"], PRIMARY)
                base += f"background:{color};color:#fff;"
                label = TYPE_LABELS.get(r["Type"], "")
            row += f"<td style='{base}'>{label}</td>"
        row += "</tr>"
        rows_html += row

    month_name = dt.date(year, month, 1).strftime("%B %Y")
    html_out = f"""
    <h3 style='color:{INK}'>{month_name}</h3>
    <div style='overflow-x:auto;'>
      <table style='border-collapse:collapse;'>
        <thead><tr><th style='min-width:140px;text-align:left;'>Team</th>{head_cells}</tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
    """
    return html_out

# ============ STREAMLIT APP ============
st.image(LOGO_URL, width=160)
st.title("BDI Holiday & Sickness Calendar")

yy = st.selectbox("Year", [2024,2025,2026], index=1)
mm = st.selectbox("Month", list(range(1,13)), format_func=lambda m: calendar.month_name[m],
                  index=dt.datetime.now().month-1)

data_exp = explode_days(df_requests)
st.markdown(render_month(data_exp, yy, mm), unsafe_allow_html=True)
