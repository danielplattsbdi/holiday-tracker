import re, html, calendar, pandas as pd, datetime as dt
import streamlit as st
from streamlit_autorefresh import st_autorefresh  # <-- for timed refresh

# --------------- CONFIG ---------------
st.set_page_config(page_title="BDI Holiday & Sickness", layout="wide")

# Put your tab URLs in Streamlit Secrets (recommended)
# Settings → Secrets:
# SHEET_URL_REQUESTS="https://docs.google.com/.../edit?gid=231607063"
# SHEET_URL_TEAM="https://docs.google.com/.../edit?gid=1533771603"
SHEET_URL_REQUESTS = st.secrets.get("SHEET_URL_REQUESTS", "")
SHEET_URL_TEAM     = st.secrets.get("SHEET_URL_TEAM", "")

PRIMARY  = "#a31fea"   # Annual Leave
SICK     = "#1feabf"   # Sickness
DARK     = "#101114"
INK      = "#25262b"
MUTED    = "#636672"
GRID     = "#e5e6eb"
BG       = "#ffffff"
HEADER_BG= "#f5f6f8"
WEEKEND  = "#f7f8fb"

TYPE_COLORS = {"Annual Leave": PRIMARY, "Sickness": SICK}
TYPE_LABELS = {"Annual Leave": "AL", "Sickness": "S"}
TZ = "Europe/London"
DAY_START=dt.time(8,30); LUNCH=dt.time(13,0); DAY_END=dt.time(17,30)
COLS={"member":"Team Member","type":"Type","from_date":"From (Date)","start_time":"Start Time",
      "until_date":"Until (Date)","end_time":"End Time","office":"Office","manager":"Line Manager","notes":"Notes"}
LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"

# --------------- HELPERS ---------------
def to_csv_export_url(url: str) -> str:
    if not url: return ""
    url = url.strip()
    if "/edit?gid=" in url:  return url.replace("/edit?gid=", "/export?format=csv&gid=")
    if "/edit#gid=" in url:  return url.replace("/edit#gid=", "/export?format=csv&gid=")
    return url.replace("/edit", "/export?format=csv")

def norm_text(x): 
    return re.sub(r"\s+"," ",str(x)).strip().lower() if pd.notna(x) else ""

def normalise_type(x):
    t = norm_text(x)
    if "sick" in t: return "Sickness"
    if "annual" in t or "holiday" in t or "leave" in t: return "Annual Leave"
    return str(x)

MORNING={"morning","am","a.m.","start"}
AFTERNOON={"afternoon","pm","p.m."}
LUNCH_SET={"lunch","lunchtime","noon","midday","12","12:00"}
EOD={"end of day","eod","close","finish","17","17:30","5:30"}

def norm_start(x):
    t=norm_text(x)
    if t in MORNING or "morning" in t or "am" in t: return "morning"
    if t in AFTERNOON or "pm" in t or "afternoon" in t: return "afternoon"
    return "morning" if not t else t

def norm_end(x):
    t=norm_text(x)
    if t in LUNCH_SET or "lunch" in t or "noon" in t or "midday" in t: return "lunchtime"
    if t in EOD or "end" in t or "eod" in t or "finish" in t or "17" in t: return "end of day"
    return "end of day" if not t else t

def _smart_date(val):
    if pd.isna(val): return pd.NaT
    s = str(val).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):  # ISO
        d = pd.to_datetime(s, errors="coerce")
        if pd.notna(d): return d
    d = pd.to_datetime(s, dayfirst=True, errors="coerce")  # UK
    if pd.notna(d): return d
    n = pd.to_numeric(s, errors="coerce")                  # Excel serial
    if pd.notna(n):
        d = pd.to_datetime(n, unit="d", origin="1899-12-30", errors="coerce")
        if pd.notna(d): return d
    return pd.NaT

@st.cache_data(ttl=60)
def read_sheet_tab(url: str) -> pd.DataFrame:
    if not url: return pd.DataFrame()
    try:
        return pd.read_csv(to_csv_export_url(url))
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_data_from_gsheet(requests_url: str) -> pd.DataFrame:
    df = read_sheet_tab(requests_url)
    if df.empty: return df
    df = df.rename(columns=lambda c: re.sub(r"\s+"," ",str(c)).strip())
    # pandas >=2.2: DataFrame.map applies elementwise
    df = df.map(lambda v: v.strip() if isinstance(v, str) else v)
    for c in [COLS["member"], COLS["type"], COLS["from_date"], COLS["until_date"], COLS["start_time"], COLS["end_time"], COLS["office"], COLS["manager"], COLS["notes"]]:
        if c not in df.columns: df[c] = None
    df[COLS["type"]] = df[COLS["type"]].map(normalise_type)
    df[COLS["start_time"]] = df[COLS["start_time"]].fillna("Morning")
    df[COLS["end_time"]]   = df[COLS["end_time"]].fillna("End of Day")

    starts, ends = [], []
    for _, r in df.iterrows():
        sd = _smart_date(r[COLS["from_date"]])
        ed = _smart_date(r[COLS["until_date"]])
        if pd.isna(sd) or pd.isna(ed): 
            starts.append(pd.NaT); ends.append(pd.NaT); continue
        sd, ed = sd.date(), ed.date()
        s = dt.datetime.combine(sd, DAY_START if norm_start(r[COLS["start_time"]])=="morning" else LUNCH)
        e = dt.datetime.combine(ed,  LUNCH     if norm_end  (r[COLS["end_time"]])=="lunchtime" else DAY_END)
        starts.append(pd.Timestamp(s, tz=TZ)); ends.append(pd.Timestamp(e, tz=TZ))

    df["Start"] = pd.to_datetime(starts)
    df["End"]   = pd.to_datetime(ends)
    df = df.dropna(subset=[COLS["member"], COLS["type"], "Start", "End"])
    df = df[df["End"] > df["Start"]].copy()
    return df

@st.cache_data(ttl=60)
def load_member_list(team_url: str, fallback_df: pd.DataFrame):
    tdf = read_sheet_tab(team_url)
    if not tdf.empty:
        tdf = tdf.rename(columns=lambda c: re.sub(r"\s+"," ",str(c)).strip())
        for col in ["Team Member","Name","Full Name"]:
            if col in tdf.columns:
                names = (tdf[col].dropna().astype(str)
                         .map(lambda s: re.sub(r"\s+"," ",s).strip())
                         .unique().tolist())
                names = sorted(names)
                if names: return names
    if fallback_df.empty: return []
    return sorted(fallback_df[COLS["member"]].dropna().astype(str).unique().tolist())

def explode_days(df):
    out=[]
    for _,r in df.iterrows():
        cur=r["Start"].date(); last=r["End"].date()
        while cur<=last:
            day_start=pd.Timestamp.combine(cur,DAY_START).tz_localize(TZ)
            day_end  =pd.Timestamp.combine(cur,DAY_END).tz_localize(TZ)
            seg_start=max(r["Start"],day_start); seg_end=min(r["End"],day_end)
            hours=max((seg_end-seg_start).total_seconds()/3600,0)
            load=0.5 if 0<hours<=4.5 else (1.0 if hours>4.5 else 0.0)
            if load>0:
                out.append({
                    "Member": r[COLS["member"]],
                    "Date": pd.Timestamp(cur, tz=TZ),
                    "Load": load,
                    "Type": r[COLS["type"]],
                    "Office": r.get(COLS["office"]),
                    "Manager": r.get(COLS["manager"]),
                    "Notes": r.get(COLS["notes"]),
                })
            cur+=dt.timedelta(days=1)
    if not out: return pd.DataFrame(columns=["Member","Date","Load","Type","Office","Manager","Notes"])
    dd=pd.DataFrame(out)
    typ_rank=lambda t: 2 if str(t)=="Sickness" else 1
    dd["Rank"]=dd["Load"].map({0.5:1,1.0:2})+dd["Type"].map(typ_rank)
    dd=dd.sort_values(["Member","Date","Rank"], ascending=[True,True,False]).drop_duplicates(["Member","Date"])
    return dd.drop(columns=["Rank"])

def compute_allowances(exploded_df, year, member_list):
    used = exploded_df[(exploded_df["Type"]=="Annual Leave") & (exploded_df["Date"].dt.year==year)]
    usage = used.groupby("Member")["Load"].sum().to_dict()
    remaining = {m: 25 - usage.get(m, 0.0) for m in member_list}
    useddays  = {m: usage.get(m, 0.0) for m in member_list}
    return remaining, useddays

def month_days(year, month):
    first=dt.datetime(year, month, 1)
    last_day=calendar.monthrange(year, month)[1]
    return pd.date_range(first, dt.datetime(year, month, last_day), freq="D", tz=TZ)

def fmt_days(x): 
    return f"{int(x)}" if abs(x - round(x)) < 1e-9 else f"{x:.1f}"

# --------------- UI HEADER ---------------
col_logo, col_title = st.columns([1,6])
with col_logo:
    st.image(LOGO_URL, use_container_width=True)  # <- updated param
with col_title:
    st.markdown(f"""
    <div style="font:600 24px system-ui; color:{INK}; margin-top:4px">BDI Holiday & Sickness Calendar</div>
    <div style="font:500 13px system-ui; color:{PRIMARY}; margin-top:2px">Reach. Recruit. Relocate.</div>
    """, unsafe_allow_html=True)

# Auto-refresh every 60s so new form entries appear
st_autorefresh(interval=60 * 1000, key="auto_refresh")

# --------------- LOAD DATA ---------------
df_requests = load_data_from_gsheet(SHEET_URL_REQUESTS)
member_list = load_member_list(SHEET_URL_TEAM, df_requests)

# --------------- CONTROLS ---------------
now = pd.Timestamp.now(tz=TZ)
years = [now.year - 1, now.year, now.year + 1]
c1,c2,c3,c4,c5,c6 = st.columns([1,1,1,1,1,1])

with c1:
    yy = st.selectbox("Year", years, index=years.index(now.year))
with c2:
    mm = st.selectbox("Month", list(range(1,13)), index=now.month-1, format_func=lambda m: calendar.month_name[m])
with c3:
    office_opts  = ["All"] + (sorted(df_requests[COLS["office"]].dropna().astype(str).unique()) if not df_requests.empty else [])
    office = st.selectbox("Office", office_opts, index=0)
with c4:
    manager_opts = ["All"] + (sorted(df_requests[COLS["manager"]].dropna().astype(str).unique()) if not df_requests.empty else [])
    manager = st.selectbox("Manager", manager_opts, index=0)
with c5:
    type_opts    = ["All","Annual Leave","Sickness"]
    typ = st.selectbox("Type", type_opts, index=0)
with c6:
    st.write("")  # spacer
    if st.button("Refresh data"):
        load_data_from_gsheet.clear()
        load_member_list.clear()
        st.experimental_rerun()

# --------------- RENDER GRID ---------------
def render_month_board(df_requests, year, month, office, manager, typ, member_list):
    data=explode_days(df_requests)
    rem, used = compute_allowances(data, year, member_list)
    fdata=data.copy()
    if office!="All":  fdata=fdata[fdata["Office"]==office]
    if manager!="All": fdata=fdata[fdata["Manager"]==manager]
    if typ!="All":     fdata=fdata[fdata["Type"]==typ]

    idx=month_days(year, month)
    today=pd.Timestamp.now(tz=TZ).normalize()
    lookup={(r["Member"], r["Date"].normalize()): r for _,r in fdata.iterrows()}

    # header cells
    head_cells="".join(
        f"<th class='th-day{' wk' if d.weekday()>=5 else ''}'><div class='dow'>{d.strftime('%a')}</div><div class='th-date'>{d.day}</div></th>"
        for d in idx
    )

    # rows
    rows_html=""
    for m in member_list:
        rem_days = rem.get(m, 25.0)
        used_days = used.get(m, 0.0)
        pct = max(0.0, min(1.0, used_days/25.0))
        rem_txt = f"{fmt_days(rem_days)} days remaining"
        name_cell = f"""
        <div class='name'>
          <div class='who'>{html.escape(str(m))}</div>
          <div class='meta'>
            <span class='rem'>{rem_txt}</span>
            <span class='bar'><i style="width:{int(pct*100)}%"></i></span>
          </div>
        </div>"""
        row=f"<tr><th class='th-name'>{name_cell}</th>"
        for d in idx:
            is_wk=d.weekday()>=5; is_td=(d.normalize()==today)
            r = lookup.get((m, d.normalize()))
            def cell_style(load, typ, is_weekend, is_today):
                base=f"position:relative;border:1px solid {GRID};height:32px;min-width:32px;font-size:11px;font-weight:700;text-align:center;vertical-align:middle;"
                if is_weekend: base+=f" background:{WEEKEND};"
                if is_today:   base+=f" outline:2px dashed {MUTED}; outline-offset:-3px;"
                if load>0:
                    color=TYPE_COLORS.get(typ, PRIMARY)
                    if load==1.0: base+=f" background:{color}; color:#fff;"
                    else:         base+=f" background:linear-gradient(135deg, {color} 50%, transparent 50%); color:{DARK};"
                return base
            if r is not None:
                style=cell_style(r['Load'], r['Type'], is_wk, is_td)
                label=TYPE_LABELS.get(r['Type'],"")
                bits=[]
                bits.append(f"{r['Type']} {'(½ day)' if r['Load']==0.5 else ''}")
                if r.get("Office"):  bits.append(f"Office: {r['Office']}")
                if r.get("Manager"): bits.append(f"Manager: {r['Manager']}")
                if r.get("Notes") and str(r["Notes"]).strip(): bits.append(f"Notes: {html.escape(str(r['Notes']))}")
                tip = f"{html.escape(m)} • {pd.Timestamp(d).strftime('%a %d %b %Y')} — " + " | ".join(bits)
                row+=f"<td class='cell' style='{style}' title='{html.escape(tip)}'>{label}</td>"
            else:
                style=cell_style(0,None,is_wk,is_td)
                row+=f"<td class='cell' style='{style}'></td>"
        row+="</tr>"
        rows_html+=row

    # legend
    legend = "".join([
        f"<span class='chip' style='--c:{TYPE_COLORS[k]}'><i style='background:var(--c)'></i>{k}</span>"
        for k in ["Annual Leave","Sickness"]
    ]) + "<span class='chip'><i style='background:linear-gradient(135deg,#9aa1b2 50%,transparent 50%)'></i>Half day</span>" \
        + f"<span class='chip'><i style='background:{WEEKEND}'></i>Weekend</span>" \
        + f"<span class='chip'><i style='border:2px dashed {MUTED};background:transparent'></i>Today</span>"

    css=f"""
    <style>
      :root {{
        --ink:{INK}; --muted:{MUTED}; --grid:{GRID}; --bg:{BG}; --primary:{PRIMARY};
      }}
      .toolbar {{
        position:sticky; top:0; z-index:5;
        display:flex; align-items:center; justify-content:space-between; gap:14px;
        padding:10px 12px; border:1px solid {GRID}; border-radius:12px; background:{BG};
        box-shadow:0 8px 20px rgba(16,17,20,.04), 0 2px 6px rgba(16,17,20,.06);
        margin:10px 0 12px 0;
      }}
      .title {{ font:700 18px system-ui, -apple-system, Segoe UI, Roboto; color:{INK}; }}
      .legend {{ display:flex; gap:10px; flex-wrap:wrap; }}
      .chip {{
        display:flex; align-items:center; gap:8px;
        font:12px/1.2 system-ui; color:{INK};
        background:#fff; border:1px solid {GRID}; border-radius:18px;
        padding:6px 10px; box-shadow:0 1px 2px rgba(0,0,0,.04);
      }}
      .chip i {{ display:inline-block; width:18px; height:14px; border:1px solid {GRID}; border-radius:4px; }}
      .board {{
        border:1px solid {GRID}; border-radius:14px; overflow:auto; background:{BG};
        box-shadow:0 8px 20px rgba(16,17,20,.04), 0 2px 6px rgba(16,17,20,.06);
      }}
      table.calendar {{ border-collapse:separate; border-spacing:0; width:max-content; }}
      th, td {{ font:12px/1.45 system-ui, -apple-system, Segoe UI, Roboto; color:{INK}; text-align:center; }}
      thead th {{ position: sticky; top:0; background:#fff; z-index:3; border-bottom:2px solid {GRID}; }}
      .th-day {{ padding:6px 6px; border-left:1px solid {GRID}; border-right:1px solid {GRID}; min-width:32px; }}
      .th-day .dow {{ color:{MUTED}; font-weight:600; }}
      .th-day .th-date {{ font-weight:800; color:{INK}; }}
      .th-day.wk {{ background:{WEEKEND}; }}
      .th-name {{
        position: sticky; left:0; z-index:2; background:#fff;
        border-right:2px solid {GRID}; width:260px; min-width:260px; padding:6px 10px; text-align:left;
      }}
      tbody tr:nth-child(odd) .th-name {{ background:#fcfdff; }}
      .name {{ display:flex; flex-direction:column; gap:4px; }}
      .name .who {{ font-weight:700; color:{INK}; }}
      .name .meta {{ display:flex; align-items:center; gap:8px; color:{MUTED}; font-weight:600; }}
      .name .meta .bar {{ position:relative; width:80px; height:6px; border-radius:999px; background:#f1f2f5; border:1px solid {GRID}; overflow:hidden; }}
      .name .meta .bar i {{ display:block; height:100%; background:linear-gradient(90deg, {PRIMARY}, #7f57f1); }}
      .cell {{ position:relative; }}
    </style>
    """

    month_name=dt.date(year, month, 1).strftime("%B %Y")
    html_out=f"""
    <div class='toolbar'>
      <div class='title'>{month_name}</div>
      <div class='legend'>{legend}</div>
    </div>
    <div class='board'>
      <table class='calendar'>
        <thead>
          <tr>
            <th class='th-name'>Team member</th>
            {head_cells}
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>
    """
    return css + html_out

html_board = render_month_board(df_requests, yy, mm, office, manager, typ, member_list)

# Height heuristic: 56px per member + header space
rows = max(1, len(member_list))
height = min(900, 120 + rows * 36)

st.components.v1.html(html_board, height=height, scrolling=True)

# Small footer
st.caption("Data source: Google Sheet (CSV export). Updates every ~60 seconds or on Refresh.")
