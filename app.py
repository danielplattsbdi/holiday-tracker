import streamlit as st
import pandas as pd
import datetime as dt
import calendar
import requests

# --- CONFIG ---
st.set_page_config(page_title="BDI Holiday Tracker", layout="wide")

LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"
PRIMARY = "#a31fea"
SICK = "#1feabf"
INK = "#25262b"
GRID = "#e5e6eb"
WEEKEND = "#f7f8fb"
TODAY = "#ffd24d"
TYPE_COLORS = {"Annual Leave": PRIMARY, "Sickness": SICK}
TYPE_LABELS = {"Annual Leave": "AL", "Sickness": "S"}

DAY_START = dt.time(8, 30)
DAY_END = dt.time(17, 30)

# --- BANK HOLIDAYS (England & Wales only) ---
@st.cache_data(ttl=86400)
def fetch_bank_holidays():
    url = "https://www.gov.uk/bank-holidays.json"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        events = data["england-and-wales"]["events"]
        dates = pd.to_datetime([e["date"] for e in events])
        return dates.normalize()
    except Exception as e:
        st.warning(f"Bank holiday fetch failed: {e}")
        return pd.DatetimeIndex([])

BANK_HOLS = fetch_bank_holidays()

def is_bank_holiday(date: pd.Timestamp):
    return date.normalize() in BANK_HOLS


# --- LOAD GOOGLE SHEET ---
@st.cache_data(ttl=300)
def load_data():
    url = st.secrets["google_sheet_url"]
    df = pd.read_csv(url)
    df = df.applymap(lambda v: v.strip() if isinstance(v, str) else v)
    for col in ["From (Date)", "Until (Date)"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df = df.dropna(subset=["Team Member", "Type", "From (Date)", "Until (Date)"])
    return df

df = load_data()


# --- EXPLODE TO DAILY ROWS ---
def explode_days(df):
    out = []
    for _, r in df.iterrows():
        start_date = r["From (Date)"].date()
        end_date = r["Until (Date)"].date()
        cur = start_date
        while cur <= end_date:
            d = pd.Timestamp(cur)
            if d.weekday() < 5 and not is_bank_holiday(d):  # only weekdays, not bank hols
                load = 1.0
                out.append({
                    "Member": r["Team Member"],
                    "Date": d,
                    "Load": load,
                    "Type": r["Type"],
                    "Office": r.get("Office", ""),
                    "Manager": r.get("Line Manager", ""),
                    "Notes": r.get("Notes", ""),
                })
            cur += dt.timedelta(days=1)
    return pd.DataFrame(out)


exploded = explode_days(df)

# --- ALLOWANCES ---
def compute_allowances(exploded_df, year, member_list):
    used = exploded_df[(exploded_df["Type"] == "Annual Leave") & (exploded_df["Date"].dt.year == year)]
    usage = used.groupby("Member")["Load"].sum().to_dict()
    remaining = {m: 25 - usage.get(m, 0.0) for m in member_list}
    return remaining, usage

members = sorted(df["Team Member"].unique())
now = dt.date.today()
year, month = now.year, now.month
remaining, used = compute_allowances(exploded, year, members)

# --- RENDER ---
st.image(LOGO_URL, use_container_width=True)
st.markdown(f"## Holiday & Sickness — {calendar.month_name[month]} {year}")

month_days = pd.date_range(dt.date(year, month, 1), dt.date(year, month, calendar.monthrange(year, month)[1]))

# Build table
rows = []
for m in members:
    rem_days = remaining.get(m, 25)
    used_days = used.get(m, 0.0)
    pct = min(1.0, used_days / 25.0)
    bar_html = f"""
        <div style='flex:1; height:6px; background:#f1f2f5; border-radius:4px; overflow:hidden;'>
            <div style='width:{pct*100}%; background:linear-gradient(90deg, {PRIMARY}, #7f57f1); height:100%'></div>
        </div>
    """
    row = f"<tr><th style='text-align:left; padding:6px 8px; border-right:1px solid {GRID}; white-space:nowrap'>{m}<br><span style='font-size:11px; color:{INK}'>{rem_days:.0f} days remaining</span>{bar_html}</th>"
    for d in month_days:
        is_wk = d.weekday() >= 5
        is_td = (d.date() == now)
        is_bh = is_bank_holiday(d)

        style = f"border:1px solid {GRID}; width:28px; height:28px; font-size:11px; text-align:center;"
        if is_wk or is_bh:
            style += f" background:{WEEKEND};"
        if is_td:
            style += f" outline:2px dashed {INK}; outline-offset:-2px;"

        rec = exploded[(exploded["Member"] == m) & (exploded["Date"] == d)]
        if not rec.empty:
            typ = rec.iloc[0]["Type"]
            color = TYPE_COLORS.get(typ, PRIMARY)
            label = TYPE_LABELS.get(typ, "")
            style += f" background:{color}; color:white;"
            row += f"<td style='{style}'>{label}</td>"
        else:
            row += f"<td style='{style}'></td>"
    row += "</tr>"
    rows.append(row)

table_html = f"""
<table style='border-collapse:collapse;'>
<thead><tr><th style='width:200px;'></th>{"".join([f"<th style='width:28px; font-size:11px'>{d.day}</th>" for d in month_days])}</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
"""

st.markdown(table_html, unsafe_allow_html=True)
