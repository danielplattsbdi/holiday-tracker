import pandas as pd
import streamlit as st
import calendar, datetime as dt, html

# ============ CONFIG ============
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/export?format=csv&gid=231607063"
LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"

PRIMARY  = "#a31fea"   # Annual Leave
SICK     = "#1feabf"   # Sickness
WEEKEND  = "#f7f8fb"
MUTED    = "#636672"
INK      = "#25262b"
GRID     = "#e5e6eb"

TYPE_COLORS = {"Annual Leave": PRIMARY, "Sickness": SICK}
TYPE_LABELS = {"Annual Leave": "AL", "Sickness": "S"}

# ============ LOAD DATA ============
@st.cache_data(ttl=60)
def load_data():
    df = pd.read_csv(SPREADSHEET_URL)
    df = df.rename(columns=lambda c: c.strip())
    df["From (Date)"] = pd.to_datetime(df["From (Date)"], errors="coerce")
    df["Until (Date)"] = pd.to_datetime(df["Until (Date)"], errors="coerce")
    df["Type"] = df["Type"].fillna("").str.title()
    return df.dropna(subset=["Team Member", "Type", "From (Date)", "Until (Date)"])

df = load_data()
members = sorted(df["Team Member"].dropna().unique())

# ============ HEADER ============
col_logo, col_title = st.columns([1,4])
with col_logo:
    st.markdown(
        f'<img src="{LOGO_URL}" style="width:100%;max-height:60px;object-fit:contain;">',
        unsafe_allow_html=True
    )
with col_title:
    st.markdown("### **BDI Holiday & Sickness Tracker**")
    st.caption("Reach. Recruit. Relocate.")

# ============ CONTROLS ============
years = list(range(df["From (Date)"].dt.year.min()-1, df["Until (Date)"].dt.year.max()+2))
year = st.selectbox("Year", years, index=years.index(dt.datetime.now().year))
month = st.selectbox("Month", list(calendar.month_name)[1:], index=dt.datetime.now().month-1)

# ============ EXPLODE ============
def explode(df):
    out = []
    for _, r in df.iterrows():
        cur = r["From (Date)"].date()
        end = r["Until (Date)"].date()
        while cur <= end:
            out.append({
                "Member": r["Team Member"],
                "Date": pd.Timestamp(cur),
                "Type": r["Type"]
            })
            cur += dt.timedelta(days=1)
    return pd.DataFrame(out)

df_days = explode(df)

# ============ ALLOWANCES ============
ALLOWANCE = 25
def remaining(m):
    used = df_days[(df_days["Member"]==m) & 
                   (df_days["Type"]=="Annual Leave") & 
                   (df_days["Date"].dt.year==year)].shape[0]
    return ALLOWANCE - used

# ============ RENDER ============
dates = pd.date_range(dt.date(year, list(calendar.month_name).index(month), 1),
                      periods=calendar.monthrange(year, list(calendar.month_name).index(month))[1])
today = pd.Timestamp.now().normalize()

# Header row
head = ["<th>Member</th>"] + [
    f"<th style='padding:4px; background:{WEEKEND if d.weekday()>=5 else '#fff'}'>{d.day}</th>"
    for d in dates
]
rows = []
for m in members:
    rem = remaining(m)
    row = [f"<td style='font-weight:600;text-align:left'>{html.escape(m)}<br><small>{rem} days left</small></td>"]
    for d in dates:
        rec = df_days[(df_days["Member"]==m) & (df_days["Date"]==d)]
        if not rec.empty:
            t = rec.iloc[0]["Type"]
            color = TYPE_COLORS.get(t, PRIMARY)
            label = TYPE_LABELS.get(t,"")
            row.append(f"<td style='background:{color};color:#fff;text-align:center'>{label}</td>")
        else:
            bg = WEEKEND if d.weekday()>=5 else "#fff"
            border = f"2px dashed {MUTED}" if d==today else GRID
            row.append(f"<td style='background:{bg};border:1px solid {border}'></td>")
    rows.append("<tr>" + "".join(row) + "</tr>")

html_table = f"""
<style>
  table {{ border-collapse:collapse; font-family:system-ui; font-size:12px; }}
  th,td {{ border:1px solid {GRID}; padding:4px; }}
  th {{ background:#fafafa; font-weight:700; }}
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
