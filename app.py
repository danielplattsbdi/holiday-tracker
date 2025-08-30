import pandas as pd
import streamlit as st
import calendar, datetime as dt, html, re, requests

# ================= CONFIG =================
REQUESTS_URL_EDIT = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=231607063"   # Requests
TEAM_URL_EDIT     = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=1533771603"  # Team

# Cancellation endpoint (Google Apps Script)
CANCELLATION_ENDPOINT = "https://script.google.com/macros/s/AKfycbxD8IQ2_JU6ajKY4tFUrtGYVhTTRFklCZ2q4RY0ctOKGG3lGriHFH7vhXqTbmRljAH6/exec"
CANCEL_TOKEN          = "adfouehrgounvroung8168evs"

LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"

# ===== Brand / palette =====
PRIMARY   = "#a31fea"   # Annual Leave (brand purple)
SICK      = "#e5b3f3"   # Sickness (pale purple variant)
WEEKEND   = "#f7f8fb"
MUTED     = "#636672"
INK       = "#25262b"
GRID      = "#e5e6eb"
HEADER_BG = "#1b1b1b"
CARD_BG   = "#ffffff"
SHADOW    = "0 10px 30px rgba(16,17,20,.06), 0 2px 8px rgba(16,17,20,.06)"

TYPE_COLORS  = {"Annual Leave": PRIMARY, "Sickness": SICK}
TYPE_LABELS  = {"Annual Leave": "AL", "Sickness": "S"}
ALLOWANCE    = 25
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
    # ISO or text
    d = pd.to_datetime(s, errors="coerce")
    if pd.notna(d): return d
    # UK style
    d = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if pd.notna(d): return d
    # Excel serial
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

@st.cache_data(ttl=300)
def load_team() -> pd.DataFrame:
    url = to_csv_export_url(TEAM_URL_EDIT)
    raw = read_csv(url).copy().rename(columns=lambda c: str(c).strip())
    if raw.empty:
        return pd.DataFrame(columns=["Team Member","Office"])
    # Keep just the roster + office, normalise
    out = raw.copy()
    if "Team Member" not in out.columns:
        # try fallbacks
        for alt in ["Name","Full Name","Member"]:
            if alt in out.columns:
                out["Team Member"] = out[alt]
                break
    out["Team Member"] = out["Team Member"].astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())
    if "Office" not in out.columns:
        out["Office"] = "Unassigned"
    out["Office"] = out["Office"].fillna("Unassigned").astype(str).map(lambda s: s.strip().title())
    # Optional Active flag
    for cand in ["Active","Is Active","Enabled"]:
        if cand in out.columns:
            mask = out[cand].astype(str).str.strip().str.lower().isin(["1","true","yes","y"])
            out = out[mask]
            break
    return (out[["Team Member","Office"]]
            .dropna(subset=["Team Member"])
            .drop_duplicates("Team Member")
            .sort_values("Team Member")
            .reset_index(drop=True))

@st.cache_data(ttl=60)
def load_requests() -> pd.DataFrame:
    url = to_csv_export_url(REQUESTS_URL_EDIT)
    df = read_csv(url)
    if df.empty: 
        return df
    df = df.rename(columns=lambda c: str(c).strip())

    for c in ["Team Member","Type","From (Date)","Until (Date)","Start Time","End Time","Office","Line Manager","Notes"]:
        if c not in df.columns: df[c] = None

    df["Team Member"]  = df["Team Member"].astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())
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

@st.cache_data(ttl=86400)
def fetch_govuk_bank_holidays_eng() -> set[pd.Timestamp]:
    try:
        r = requests.get("https://www.gov.uk/bank-holidays.json", timeout=10)
        r.raise_for_status()
        events = r.json().get(ENG_WALES_KEY, {}).get("events", [])
        idx = pd.to_datetime([e["date"] for e in events], errors="coerce").dropna().dt.normalize()
        return set(idx.tolist())
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

# ================= UI (header + layout) =================
st.set_page_config(page_title="BDI Holiday & Sickness", layout="wide")

# Branded header card
st.markdown(
    f"""
    <div style="
      background:{HEADER_BG}; border-radius:16px; padding:14px 16px;
      display:flex; align-items:center; gap:14px; margin:8px auto 14px; max-width:1120px;
      box-shadow:{SHADOW};
    ">
      <img src="{LOGO_URL}" style="height:36px;object-fit:contain">
      <div style="color:#fff; font:700 18px system-ui">BDI Holiday &amp; Sickness Tracker</div>
    </div>
    """,
    unsafe_allow_html=True
)

# Global CSS
st.markdown(
    f"""
    <style>
      .main > div {{max-width: 1120px; margin-left: auto; margin-right: auto;}}
      .bdi-card {{
        background:{CARD_BG}; border:1px solid {GRID}; border-radius:14px; padding:12px;
        box-shadow:{SHADOW};
      }}
      table {{ border-collapse:collapse; font-family:system-ui, -apple-system, Segoe UI, Roboto; font-size:12px; }}
      th,td {{ border:1px solid {GRID}; padding:3px 6px; }}
      thead th {{ background:#fafafa; font-weight:800; position:sticky; top:0; z-index:2; }}
      td:first-child, th:first-child {{ position:sticky; left:0; background:#fff; z-index:3; }}
      .namecell {{ font-weight:700; color:{INK}; text-align:left; }}
      .daysleft {{ color:{MUTED}; font-size:11px; font-weight:600; }}
      .badge {{
        display:inline-block; background:#f1f2f5; border:1px solid {GRID}; border-radius:999px;
        padding:2px 8px; font-size:11px; color:{MUTED}; margin-left:8px;
      }}
      .legend-chip {{
        display:inline-flex; align-items:center; gap:8px; padding:4px 10px; border:1px solid {GRID};
        border-radius:999px; background:#fff; font-size:12px; margin-right:8px;
        box-shadow:0 1px 2px rgba(0,0,0,.04);
      }}
      .legend-swatch {{ width:18px; height:12px; border-radius:4px; border:1px solid {GRID}; display:inline-block; }}
    </style>
    """,
    unsafe_allow_html=True
)

# ================= DATA =================
df_req   = load_requests()
df_team  = load_team()
df_days  = explode_days(df_req)
bank_holidays = fetch_govuk_bank_holidays_eng()

team_members = sorted(df_team["Team Member"].unique().tolist()) if not df_team.empty else []

# ================= CONTROLS =================
now = dt.datetime.now()
years = list(range(now.year-1, now.year+2))
offices = ["Whole Team"] + sorted(df_team["Office"].unique()) if not df_team.empty else ["Whole Team"]

with st.container():
    c1, c2, c3 = st.columns([1,1,2])
    with c1:
        year = st.selectbox("Year", years, index=years.index(now.year))
    with c2:
        month = st.selectbox("Month", list(calendar.month_name)[1:], index=now.month-1)
    with c3:
        office = st.selectbox("Office", offices)

# Month index + helpers
month_index = list(calendar.month_name).index(month)
dates = pd.date_range(dt.date(year, month_index, 1), periods=calendar.monthrange(year, month_index)[1])
today = pd.Timestamp.now().normalize()

def is_bank_holiday(ts): return ts.normalize() in bank_holidays
def is_working_day(ts): return ts.weekday()<5 and not is_bank_holiday(ts)

def remaining_for(member, yr):
    if df_days.empty: return ALLOWANCE
    mask = ((df_days["Member"]==member) & (df_days["Type"]=="Annual Leave") & (df_days["Date"].dt.year==yr))
    days = df_days.loc[mask, "Date"]
    used = sum(1 for d in days if is_working_day(pd.Timestamp(d)))
    return ALLOWANCE - used

# ================= GRID =================
with st.container():
    st.markdown("<div class='bdi-card'>", unsafe_allow_html=True)

    head_cells = ["<th style='min-width:260px;text-align:left'>Team member</th>"] + [
        f"<th style='padding:6px 4px; width:28px; background:{WEEKEND if (d.weekday()>=5 or is_bank_holiday(d)) else '#fff'}'>{d.day}</th>"
        for d in dates
    ]

    rows=[]
    render_team = df_team if office == "Whole Team" else df_team[df_team["Office"]==office]
    for _, r in render_team.iterrows():
        m = r["Team Member"]
        rem = remaining_for(m, year)
        name_html = (
            f"<div>{html.escape(m)}<span class='badge'>{html.escape(r['Office'])}</span></div>"
            f"<div class='daysleft'>{int(rem) if rem.is_integer() if isinstance(rem,float) else rem} days left</div>"
        ) if isinstance(rem, float) else (
            f"<div>{html.escape(m)}<span class='badge'>{html.escape(r['Office'])}</span></div>"
            f"<div class='daysleft'>{rem} days left</div>"
        )
        row=[f"<td class='namecell'>{name_html}</td>"]
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
                txt = "#000" if t=="Sickness" else "#fff"
                row.append(f"<td style='background:{color};color:{txt};text-align:center;width:28px;font-weight:800'>{label}</td>")
            else:
                row.append(f"<td style='background:{bg};border:1px solid {border};width:28px'></td>")
        rows.append("<tr>"+"".join(row)+"</tr>")

    table_html = f"""
    <table>
      <thead><tr>{''.join(head_cells)}</tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """
    st.markdown(table_html, unsafe_allow_html=True)

    # Legend
    st.markdown(
        f"""
        <div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;">
          <span class="legend-chip"><i class="legend-swatch" style="background:{PRIMARY}"></i>Annual Leave</span>
          <span class="legend-chip"><i class="legend-swatch" style="background:{SICK}"></i>Sickness</span>
          <span class="legend-chip"><i class="legend-swatch" style="background:{WEEKEND}"></i>Weekend / Bank Holiday</span>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("</div>", unsafe_allow_html=True)

# ================= BULK CANCEL (checkboxes) =================
st.markdown("### ❌ Cancel Booking(s)")
st.caption("Select a team member, tick the booking(s) to cancel, then press **Cancel Selected**.")

if not team_members:
    st.info("No team members found in the Team tab.")
else:
    sel_member = st.selectbox("Team member", team_members, index=0)

    today_norm = pd.Timestamp.now().normalize()
    member_reqs = pd.DataFrame(columns=df_req.columns)
    if not df_req.empty:
        member_reqs = df_req[
            (df_req["Team Member"] == sel_member) &
            (df_req["Type"] == "Annual Leave") &
            (df_req["Until (Date)"] >= today_norm)
        ].copy()

    if member_reqs.empty:
        st.info(f"{sel_member} has no upcoming Annual Leave bookings.")
    else:
        # Labels + map back to rows
        member_reqs["Label"] = member_reqs.apply(
            lambda r: f"{r['From (Date)'].strftime('%d %b %Y')} → {r['Until (Date)'].strftime('%d %b %Y')}",
            axis=1
        )
        labels = member_reqs["Label"].tolist()
        picks = st.multiselect("Choose booking(s) to cancel", options=labels)

        # Small preview table (optional, nice touch)
        if picks:
            preview = (member_reqs[member_reqs["Label"].isin(picks)]
                       [["Type","From (Date)","Until (Date)"]]
                       .rename(columns={"Type":"Type","From (Date)":"From","Until (Date)":"Until"}))
            st.dataframe(preview, use_container_width=True, hide_index=True)

        col_a, col_b = st.columns([1,4])
        with col_a:
            pressed = st.button("Cancel Selected", type="primary", use_container_width=True)
        with col_b:
            st.caption("This will remove the selected row(s) from the **Requests** sheet and update the board immediately.")

        if pressed and picks:
            errors = []
            for _, r in member_reqs[member_reqs["Label"].isin(picks)].iterrows():
                payload = {
                    "token": CANCEL_TOKEN,
                    "member": r["Team Member"],
                    "type": "Annual Leave",
                    "from": r["From (Date)"].strftime("%d/%m/%Y"),
                    "until": r["Until (Date)"].strftime("%d/%m/%Y"),
                }
                try:
                    resp = requests.post(CANCELLATION_ENDPOINT, json=payload, timeout=10)
                    ok = resp.ok and resp.headers.get("content-type","").startswith("application/json") and resp.json().get("ok")
                    if not ok:
                        errors.append(resp.text)
                except Exception as e:
                    errors.append(str(e))

            if errors:
                st.error("Some cancellations failed:\n\n" + "\n".join(errors))
            else:
                st.toast("Cancelled ✅ Updating…", icon="✅")
                st.cache_data.clear()
                st.rerun()
