import streamlit as st
import pandas as pd
import numpy as np
import datetime as dt
import calendar
import requests

# ---------------- CONFIG ----------------
st.set_page_config(page_title="BDI Holiday Tracker", layout="wide")

LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"
PRIMARY = "#a31fea"
SICK = "#1feabf"
WEEKEND = "#f7f8fb"
BANKHOL = "#ffe8e8"
TODAY = "#ffd24d"
TYPE_COLORS = {"Annual Leave": PRIMARY, "Sickness": SICK}
TYPE_LABELS = {"Annual Leave": "AL", "Sickness": "S"}
ANNUAL_ALLOWANCE = 25

# --- 🔗 Google Sheet URL (hard-coded for now)
SHEET_URL = "https://docs.google.com/spreadsheets/d/your-google-sheet-id/export?format=csv&gid=0"

# --- 📅 Fetch UK bank holidays (England & Wales)
@st.cache_data
def fetch_bank_holidays(year):
    try:
        url = "https://www.gov.uk/bank-holidays.json"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()["england-and-wales"]["events"]
        dates = [pd.to_datetime(ev["date"]) for ev in data]
        return pd.to_datetime([d for d in dates if d.year == year])
    except Exception as e:
        st.warning(f"Bank holiday fetch failed: {e}")
        return pd.to_datetime([])

# --- 📊 Load Data
@st.cache_data
def load_data():
    df = pd.read_csv(SHEET_URL)
    df = df.rename(columns=lambda c: c.strip())
    for col in ["From (Date)", "Until (Date)"]:
        df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
    df["Type"] = df["Type"].str.strip().replace(
        {"Holiday": "Annual Leave", "AL": "Annual Leave", "Sick": "Sickness"}
    )
    return df.dropna(subset=["Team Member", "Type", "From (Date)", "Until (Date)"])

# --- ⏳ Explode into daily rows
def explode_days(df, bank_holidays):
    out = []
    for _, r in df.iterrows():
        cur = r["From (Date)"].date()
        end = r["Until (Date)"].date()
        while cur <= end:
            # skip weekends & bank holidays
            if cur.weekday() < 5 and pd.Timestamp(cur) not in bank_holidays:
                out.append({
                    "Member": r["Team Member"],
                    "Date": pd.Timestamp(cur),
                    "Type": r["Type"],
                    "Load": 1.0,  # full day
                })
            cur += dt.timedelta(days=1)
    return pd.DataFrame(out)

# --- 📈 Compute allowances
def compute_allowances(days, members, year):
    used = days[(days["Type"] == "Annual Leave") & (days["Date"].dt.year == year)]
    usage = used.groupby("Member")["Load"].sum().to_dict()
    remaining = {m: ANNUAL_ALLOWANCE - usage.get(m, 0.0) for m in members}
    return usage, remaining

# --- 🎨 Render calendar
def render_month(df_days, members, year, month, bank_holidays, usage, remaining):
    idx = pd.date_range(
        dt.date(year, month, 1),
        dt.date(year, month, calendar.monthrange(year, month)[1]),
        freq="D"
    )
    today = pd.Timestamp.now().normalize()
    lookup = {(r["Member"], r["Date"]): r for _, r in df_days.iterrows()}

    # --- Header
    head_cells = "".join(
        f"<th style='padding:4px;background:{WEEKEND if d.weekday()>=5 else '#fff'}"
        f"{';background:'+BANKHOL if d in bank_holidays else ''}'>{d.day}</th>"
        for d in idx
    )

    # --- Rows
    rows_html = ""
    for m in members:
        bar = f"""
        <div style="font-size:11px;color:#555">
            {remaining.get(m, ANNUAL_ALLOWANCE)} days remaining
            <div style="height:6px;width:100px;background:#eee;border-radius:4px;overflow:hidden">
                <div style="height:100%;width:{usage.get(m,0)/ANNUAL_ALLOWANCE*100}%;
                    background:{PRIMARY};"></div>
            </div>
        </div>"""
        row = f"<tr><th style='text-align:left;padding:4px'>{m}{bar}</th>"
        for d in idx:
            cell = ""
            if (m, d) in lookup:
                typ = lookup[(m, d)]["Type"]
                color = TYPE_COLORS.get(typ, PRIMARY)
                label = TYPE_LABELS.get(typ, "")
                cell = f"<td style='background:{color};color:#fff;text-align:center'>{label}</td>"
            else:
                # weekends / bank holidays shading
                bg = "#fff"
                if d.weekday() >= 5:
                    bg = WEEKEND
                if d in bank_holidays:
                    bg = BANKHOL
                if d == today:
                    bg = TODAY
                cell = f"<td style='background:{bg}'></td>"
            row += cell
        row += "</tr>"
        rows_html += row

    # --- Table
    html = f"""
    <table border=1 cellspacing=0 cellpadding=0 style="border-collapse:collapse;font-size:12px">
        <thead><tr><th>Member</th>{head_cells}</tr></thead>
        <tbody>{rows_html}</tbody>
    </table>
    """
    return html


# ---------------- MAIN APP ----------------
st.image(LOGO_URL, use_container_width=True)
st.title("BDI Holiday & Sickness Calendar")

df = load_data()
members = sorted(df["Team Member"].dropna().unique())
now = dt.datetime.now()
year, month = now.year, now.month
bank_holidays = fetch_bank_holidays(year)
days = explode_days(df, bank_holidays)
usage, remaining = compute_allowances(days, members, year)

st.markdown(render_month(days, members, year, month, bank_holidays, usage, remaining), unsafe_allow_html=True)
