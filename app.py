# app.py
import pandas as pd
import streamlit as st
import calendar, datetime as dt, html, re, requests

# ==============================
# ======= CONFIG / BRAND =======
# ==============================
REQUESTS_URL_EDIT = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=231607063"   # Requests
TEAM_URL_EDIT     = "https://docs.google.com/spreadsheets/d/1Ho_xH8iESP0HVTeXKFe2gyWOg18kcMFKrLvEi2wNyMs/edit?gid=1533771603"  # Team

# Cancellation endpoint (Google Apps Script)
CANCELLATION_ENDPOINT = "https://script.google.com/macros/s/AKfycbxD8IQ2_JU6ajKY4tFUrtGYVhTTRFklCZ2q4RY0ctOKGG3lGriHFH7vhXqTbmRljAH6/exec"
CANCEL_TOKEN          = "adfouehrgounvroung8168evs"

# Google Form for new bookings
BOOKING_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSeSPFiyFfHvlhNQLT3Lz9sZA29CIAlxR6FmxwPobNeG9DjzOw/viewform?usp=dialog"

LOGO_URL = "https://sitescdn.wearevennture.co.uk/public/bdi-resourcing/site/live/uploads/brandmark.png"

# ===== Brand / palette =====
PRIMARY   = "#a31fea"   # Annual Leave (brand purple)
SICK      = "#e5b3f3"   # Sickness (pale purple)
WEEKEND   = "#f7f8fb"
MUTED     = "#636672"
INK       = "#25262b"
GRID      = "#e5e6eb"
HEADER_BG = "#1b1b1b"
CARD_BG   = "#ffffff"
SHADOW    = "0 10px 30px rgba(16,17,20,.06), 0 2px 8px rgba(16,17,20,.06)"

TYPE_COLORS  = {"Annual Leave": PRIMARY, "Sickness": SICK}
TYPE_LABELS  = {"Annual Leave": "AL", "Sickness": "S"}
ALLOWANCE_DEFAULT = 25
ENG_WALES_KEY = "england-and-wales"

# ==============================
# =========== HELPERS ==========
# ==============================
def to_csv_export_url(edit_url: str) -> str:
    if "/edit?gid=" in edit_url:
        return edit_url.replace("/edit?gid=", "/export?format=csv&gid=")
    if "/edit#gid=" in edit_url:
        return edit_url.replace("/edit#gid=", "/export?format=csv&gid=")
    return edit_url.replace("/edit", "/export?format=csv")

def _normalize_slashes(s: str) -> str:
    # Replace common separators with "/"
    return re.sub(r"[.\-–—\s]+", "/", s)

def _smart_date(val):
    """
    UK-first parser with no blind swapping:
      - dd/mm/yyyy, dd/mm/yy (→ 20yy), dd/mm (→ current year)
      - yyyy-mm-dd or yyyy/mm/dd (parsed **as ISO**)
      - Excel serials
      - Fallback: dayfirst=True
    """
    if pd.isna(val):
        return pd.NaT
    s = str(val).strip()
    if not s:
        return pd.NaT

    s_norm = _normalize_slashes(s)

    # dd/mm/yyyy
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", s_norm)
    if m:
        dd, mm, yyyy = map(int, m.groups())
        try:
            return pd.Timestamp(year=yyyy, month=mm, day=dd)
        except Exception:
            return pd.NaT

    # dd/mm/yy
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2})\s*$", s_norm)
    if m:
        dd, mm, yy = map(int, m.groups())
        yyyy = 2000 + yy
        try:
            return pd.Timestamp(year=yyyy, month=mm, day=dd)
        except Exception:
            return pd.NaT

    # dd/mm  (assume current year)
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})\s*$", s_norm)
    if m:
        dd, mm = map(int, m.groups())
        yyyy = dt.datetime.now().year
        try:
            return pd.Timestamp(year=yyyy, month=mm, day=dd)
        except Exception:
            return pd.NaT

    # ISO yyyy-mm-dd or yyyy/mm/dd — parse as-is
    m = re.match(r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s_norm)
    if m:
        yyyy, mm, dd = map(int, m.groups())
        try:
            return pd.Timestamp(year=yyyy, month=mm, day=dd)
        except Exception:
            return pd.NaT

    # Excel serial (numeric)
    n = pd.to_numeric(s, errors="coerce")
    if pd.notna(n):
        return pd.to_datetime(n, unit="d", origin="1899-12-30", errors="coerce")

    # Fallback: UK preference
    return pd.to_datetime(s, dayfirst=True, errors="coerce", utc=False)

def _looks_iso_yyyy_mm_dd(s: str | None) -> bool:
    if s is None or (isinstance(s, float) and pd.isna(s)): return False
    return bool(re.match(r"^\s*\d{4}-\d{1,2}-\d{1,2}\s*$", str(s)))

def _iso_swap_if_valid(ts_str: str):
    """Return swapped yyyy-dd-mm as Timestamp if valid, else None."""
    m = re.match(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$", str(ts_str))
    if not m: return None
    yyyy, mm, dd = map(int, m.groups())
    try:
        return pd.Timestamp(year=yyyy, month=dd, day=mm)  # swap mm<->dd
    except Exception:
        return None

def _parse_time_str(s: str):
    """Return a time() if we can parse; else None."""
    if s is None or (isinstance(s, float) and pd.isna(s)): return None
    s = str(s).strip()
    if not s: return None
    try:
        t = pd.to_datetime(s, errors="coerce").time()
        return t
    except Exception:
        return None

# --- Half-day helpers (Form categories first) ---
def _clean_token(s: str | None) -> str | None:
    if s is None or (isinstance(s, float) and pd.isna(s)): return None
    # Lowercase, trim, strip trailing punctuation/dashes
    t = re.sub(r"[\s\-–—]+$", "", str(s).strip().lower())
    return t or None

def _norm_slot(s: str | None) -> str | None:
    """
    Normalise category text to one of: 'morning', 'afternoon', 'lunch', 'eod'.
    """
    t = _clean_token(s)
    if not t: return None

    # Exact options first
    EXACT = {
        "morning": "morning",
        "afternoon": "afternoon",
        "lunchtime": "lunch",
        "end of day": "eod",
        "eod": "eod",
    }
    if t in EXACT: return EXACT[t]

    # Common variants
    if re.search(r"\bmorn(ing)?\b", t): return "morning"
    if re.search(r"\bafternoon\b|\bafter\s*noon\b|\bpm\b", t): return "afternoon"
    if re.search(r"\blunch\s*time\b|\blunchtime\b|\bmid\s*day\b", t): return "lunch"
    if re.search(r"\bend\s*of\s*day\b|\beod\b|\bclose\b|\bend\b", t): return "eod"
    return None

def _half_hint(s: str | None):
    """Fallback: 'am'/'pm' if free text clearly indicates half-day."""
    t = _clean_token(s)
    if not t: return None
    if re.search(r"\b(am|morning|a\.m\.)\b", t): return "am"
    if re.search(r"\b(pm|afternoon|p\.m\.)\b", t): return "pm"
    return None

def _half_from_categories(start_slot: str | None, end_slot: str | None,
                          single_day: bool, is_first_day: bool, is_last_day: bool) -> str | None:
    # Single-day rules
    if single_day:
        if start_slot == "morning" and end_slot == "lunch":
            return "am"
        if start_slot == "afternoon" and end_slot == "eod":
            return "pm"
        if start_slot == "morning" and end_slot == "eod":
            return None  # full day
        if start_slot == "afternoon" and end_slot == "lunch":
            return "pm"
        return None
    # Multi-day edges
    if is_first_day and start_slot == "afternoon":
        return "pm"
    if is_last_day and end_slot == "lunch":
        return "am"
    return None

def hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

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
        return pd.DataFrame(columns=["Team Member","Office","Allowance"])
    out = raw.copy()

    # Team Member
    if "Team Member" not in out.columns:
        for alt in ["Name","Full Name","Member"]:
            if alt in out.columns:
                out["Team Member"] = out[alt]
                break
    out["Team Member"] = out["Team Member"].astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())

    # Office
    if "Office" not in out.columns:
        out["Office"] = "Unassigned"
    out["Office"] = out["Office"].fillna("Unassigned").astype(str).map(lambda s: s.strip().title())

    # Optional per-person Allowance override
    if "Allowance" in out.columns:
        out["Allowance"] = pd.to_numeric(out["Allowance"], errors="coerce").fillna(ALLOWANCE_DEFAULT)
    else:
        out["Allowance"] = ALLOWANCE_DEFAULT

    # Filter to active if an 'Active' style column exists
    for cand in ["Active","Is Active","Enabled"]:
        if cand in out.columns:
            mask = out[cand].astype(str).str.strip().str.lower().isin(["1","true","yes","y"])
            out = out[mask]
            break

    return (out[["Team Member","Office","Allowance"]]
            .dropna(subset=["Team Member"])
            .drop_duplicates("Team Member")
            .sort_values("Team Member")
            .reset_index(drop=True))

def _needs_iso_swap(from_raw, until_raw, from_ts, until_ts) -> bool:
    """
    Decide if we should reinterpret ISO strings with dd/mm intent.
    Criteria:
      - both raw look like 'yyyy-mm-dd'
      - both day and month <= 12 (otherwise the swap would be invalid)
      - current span is large (> 14 days)
      - swapped span is valid and strictly smaller
    """
    if not (_looks_iso_yyyy_mm_dd(from_raw) and _looks_iso_yyyy_mm_dd(until_raw)):
        return False
    # Extract ints
    try:
        fy, fm, fd = map(int, str(from_raw).split("-"))
        uy, um, ud = map(int, str(until_raw).split("-"))
    except Exception:
        return False
    if not (fm <= 12 and fd <= 12 and um <= 12 and ud <= 12):
        return False
    if pd.isna(from_ts) or pd.isna(until_ts):
        return False
    span = (until_ts - from_ts).days
    if span <= 14:
        return False
    sf = _iso_swap_if_valid(from_raw)
    su = _iso_swap_if_valid(until_raw)
    if sf is None or su is None:
        return False
    if su < sf:
        return False
    swapped_span = (su - sf).days
    return swapped_span < span

@st.cache_data(ttl=60)
def load_requests() -> pd.DataFrame:
    url = to_csv_export_url(REQUESTS_URL_EDIT)
    df = read_csv(url)
    if df.empty:
        return df
    df = df.rename(columns=lambda c: str(c).strip())

    # Ensure expected columns
    for c in ["Team Member","Type","From (Date)","Until (Date)","Start Time","End Time",
              "Office","Line Manager","Notes","Status"]:
        if c not in df.columns:
            df[c] = None

    # Keep raw strings for contextual correction
    df["From_raw"]  = df["From (Date)"].astype(str)
    df["Until_raw"] = df["Until (Date)"].astype(str)

    # Clean + parse
    df["Team Member"]  = df["Team Member"].astype(str).map(lambda s: re.sub(r"\s+"," ",s).strip())
    df["From (Date)"]  = df["From (Date)"].map(_smart_date)
    df["Until (Date)"] = df["Until (Date)"].map(_smart_date)

    # Contextual “shorter span” swap for ambiguous ISO rows
    swaps = []
    for i, r in df.iterrows():
        fr, ur = r["From_raw"], r["Until_raw"]
        ft, ut = r["From (Date)"], r["Until (Date)"]
        if _needs_iso_swap(fr, ur, ft, ut):
            sf = _iso_swap_if_valid(fr)
            su = _iso_swap_if_valid(ur)
            if sf is not None and su is not None:
                df.at[i, "From (Date)"]  = sf
                df.at[i, "Until (Date)"] = su
                swaps.append(i)
    # st.caption(f"Adjusted {len(swaps)} ambiguous ISO date pair(s).")

    # Normalise type (defensive)
    def norm_type(x):
        s = str(x).strip().lower()
        if "sick" in s: return "Sickness"
        if any(k in s for k in ["annual","holiday","leave","al"]): return "Annual Leave"
        return str(x).strip() if x is not None else ""
    df["Type"] = df["Type"].map(norm_type)

    # Normalise Status and default to Pending if blank
    df["Status"] = df["Status"].fillna("").astype(str).str.strip().str.title()
    df.loc[df["Status"]=="", "Status"] = "Pending"

    # Valid rows only
    df = df.dropna(subset=["Team Member","Type","From (Date)","Until (Date)"])
    df = df[df["Until (Date)"] >= df["From (Date)"]]
    return df.drop(columns=["From_raw","Until_raw"])

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

def classify_half_for_date(row, date_ts: pd.Timestamp):
    """
    Decide full vs half day for a given date in a booking.

    Priority:
      1) Form categories (Morning/Afternoon + Lunchtime/End of Day) — authoritative.
         If categories are present but don't imply a half-day, treat as FULL (no fallback).
      2) Only if BOTH category fields are missing, fall back to explicit times / hints,
         using edge-specific logic (first day uses start info; last day uses end info).
    """
    from_d = row["From (Date)"].normalize()
    until_d = row["Until (Date)"].normalize()

    st_raw = row.get("Start Time", None)
    en_raw = row.get("End Time", None)
    start_slot = _norm_slot(st_raw)
    end_slot   = _norm_slot(en_raw)

    single_day = (from_d == until_d)
    is_first   = (date_ts.normalize() == from_d)
    is_last    = (date_ts.normalize() == until_d)

    # 1) Categories first (final if decisive)
    cat_half = _half_from_categories(start_slot, end_slot, single_day, is_first, is_last)
    if cat_half in ("am", "pm"):
        return cat_half

    # If any category value is present but non-decisive, treat as FULL (do not fall back).
    if start_slot is not None or end_slot is not None:
        return None

    # 2) Fallback ONLY when both category fields are missing.
    st_t   = _parse_time_str(st_raw)
    en_t   = _parse_time_str(en_raw)
    st_hint = _half_hint(st_raw)  # 'am'/'pm'/None
    en_hint = _half_hint(en_raw)

    NOON   = dt.time(12, 0)
    ONE_PM = dt.time(13, 0)

    if single_day and is_first and is_last:
        # Single-day: use both ends
        am_by_end   = (en_t and en_t <= ONE_PM) or (en_hint == "am")
        pm_by_start = (st_t and st_t >= NOON)   or (st_hint == "pm")
        if am_by_end and not pm_by_start: return "am"
        if pm_by_start and not am_by_end: return "pm"
        return None

    # Multi-day edges: use edge-specific signals ONLY
    if is_first:
        if (st_t and st_t >= NOON) or (st_hint == "pm"):
            return "pm"
        return None
    if is_last:
        if (en_t and en_t <= ONE_PM) or (en_hint == "am"):
            return "am"
        return None

    # Middle days are full
    return None

def explode_days(df: pd.DataFrame) -> pd.DataFrame:
    """Per-day rows with fraction + half indicator + status."""
    if df.empty:
        return pd.DataFrame(columns=["Member","Date","Type","Status","Frac","Half"])
    out=[]
    for _, r in df.iterrows():
        cur = r["From (Date)"].date()
        end = r["Until (Date)"].date()
        while cur <= end:
            ts = pd.Timestamp(cur)
            half = classify_half_for_date(r, ts)
            frac = 0.5 if half in ("am","pm") else 1.0
            out.append({
                "Member": r["Team Member"],
                "Date": ts,
                "Type": r["Type"],
                "Status": r["Status"],
                "Frac": frac,
                "Half": half
            })
            cur += dt.timedelta(days=1)
    return pd.DataFrame(out)

def fmt_days(x):
    if isinstance(x, (int, float)):
        return int(x) if float(x).is_integer() else round(float(x), 1)
    return x

# ==============================
# ============ UI ==============
# ==============================
st.set_page_config(page_title="BDI Holiday & Sickness", layout="wide")

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
      .bdi-btn {{
        display:inline-block; padding:8px 12px; border-radius:10px; border:1px solid {GRID};
        font-weight:600; text-decoration:none; background:#fff;
      }}
      .bdi-btn:hover {{ filter:brightness(0.98); }}
    </style>
    """,
    unsafe_allow_html=True
)

# Header
st.markdown(
    f"""
    <div style="
      background:{HEADER_BG}; border-radius:16px; padding:14px 16px;
      display:flex; align-items:center; justify-content:space-between; gap:14px; margin:8px auto 14px; max-width:1120px;
      box-shadow:{SHADOW};
    ">
      <div style="display:flex; align-items:center; gap:14px;">
        <img src="{LOGO_URL}" style="height:36px;object-fit:contain">
        <div style="color:#fff; font:700 18px system-ui">BDI Holiday &amp; Sickness Tracker</div>
      </div>
      <a class="bdi-btn" href="{BOOKING_FORM_URL}" target="_blank" rel="noopener">+ New Booking</a>
    </div>
    """,
    unsafe_allow_html=True
)

# ==============================
# ============ DATA ============
# ==============================
df_req   = load_requests()
df_team  = load_team()
bank_holidays = fetch_govuk_bank_holidays_eng()

team_members = sorted(df_team["Team Member"].unique().tolist()) if not df_team.empty else []

# ==============================
# ========= CONTROLS ===========
# ==============================
now = dt.datetime.now()
years = list(range(now.year-1, now.year+2))
offices = ["Whole Team"] + sorted(df_team["Office"].unique()) if not df_team.empty else ["Whole Team"]

with st.container():
    c0, c1, c2, c3 = st.columns([1,1,1,2])
    with c0:
        show_pending = st.toggle("Show pending", value=True, help="Include Pending items in the grid (shown translucent with dashed outline)")
    with c1:
        year = st.selectbox("Year", years, index=years.index(now.year))
    with c2:
        month = st.selectbox("Month", list(calendar.month_name)[1:], index=now.month-1)
    with c3:
        office = st.selectbox("Office", offices)

# Filter Requests for view
if df_req.empty:
    df_req_view = df_req.copy()
    df_req_approved = df_req.copy()
else:
    df_req_approved = df_req[df_req["Status"] == "Approved"].copy()
    if not show_pending:
        df_req_view = df_req_approved.copy()
    else:
        df_req_view = df_req[df_req["Status"].isin(["Approved","Pending"])].copy()

# Derived per-day frames
df_days_view     = explode_days(df_req_view)
df_days_approved = explode_days(df_req_approved)

# Month index + helpers
month_index = list(calendar.month_name).index(month)
dates = pd.date_range(dt.date(year, month_index, 1), periods=calendar.monthrange(year, month_index)[1])
today = pd.Timestamp.now().normalize()

def is_bank_holiday(ts): return ts.normalize() in bank_holidays
def is_working_day(ts): return ts.weekday()<5 and not is_bank_holiday(ts)

def allowance_for(member, yr):
    # Per-person override if present
    if df_team.empty:
        base = ALLOWANCE_DEFAULT
    else:
        row = df_team[df_team["Team Member"] == member]
        base = (row["Allowance"].iloc[0] if not row.empty else ALLOWANCE_DEFAULT)

    if df_days_approved.empty:
        return base

    mask = ((df_days_approved["Member"]==member)
            & (df_days_approved["Type"]=="Annual Leave")
            & (df_days_approved["Date"].dt.year==yr))
    sub = df_days_approved.loc[mask]
    used = sum((r.Frac if is_working_day(pd.Timestamp(r.Date)) else 0.0) for r in sub.itertuples())
    return base - used

# ==============================
# ============ GRID ============
# ==============================
with st.container():
    st.markdown("<div class='bdi-card'>", unsafe_allow_html=True)

    scope_txt = "Approved only" if not show_pending else "Approved + Pending"
    st.markdown(
        f"<div style='margin:0 0 8px 0;color:{MUTED};font:12px system-ui'>Viewing: "
        f"<span class='badge' style='background:#fff'>{scope_txt}</span></div>",
        unsafe_allow_html=True
    )

    head_cells = ["<th style='min-width:260px;text-align:left'>Team member</th>"] + [
        f"<th style='padding:6px 4px; width:28px; background:{WEEKEND if (d.weekday()>=5 or is_bank_holiday(d)) else '#fff'}'>{d.day}</th>"
        for d in dates
    ]

    rows=[]
    render_team = df_team if (office == "Whole Team" or df_team.empty) else df_team[df_team["Office"]==office]
    type_priority = {"Sickness": 2, "Annual Leave": 1}

    for _, r in render_team.iterrows():
        m = r["Team Member"]
        rem = allowance_for(m, year)
        rem_txt = fmt_days(rem)
        name_html = (
            f"<div>{html.escape(m)}<span class='badge'>{html.escape(r['Office'])}</span></div>"
            f"<div class='daysleft'>{rem_txt} days left</div>"
        )
        row=[f"<td class='namecell'>{name_html}</td>"]
        md = df_days_view[df_days_view["Member"]==m]

        for d in dates:
            is_bh = is_bank_holiday(d)
            bg = WEEKEND if (d.weekday()>=5 or is_bh) else "#fff"
            border_css = f"2px dashed {MUTED}" if d==today else f"1px solid {GRID}"

            recs = md[md["Date"]==d]
            if not recs.empty and (d.weekday()<5 and not is_bh):
                recs = recs.copy()
                recs["prio"] = recs["Type"].map(lambda t: type_priority.get(t, 0))
                rec = recs.sort_values("prio", ascending=False).iloc[0]
                t = rec["Type"]
                status = rec["Status"]
                half = rec["Half"]

                color = TYPE_COLORS.get(t, PRIMARY)
                label = TYPE_LABELS.get(t,"")
                txt = "#fff" if (t=="Annual Leave" and status=="Approved" and (half is None)) else "#000"

                if status == "Pending":
                    rgba = hex_to_rgba(color, 0.18)
                    if half == "am":
                        bg_style = f"linear-gradient(135deg, {rgba} 0 50%, #fff 50% 100%)"
                    elif half == "pm":
                        bg_style = f"linear-gradient(135deg, #fff 0 50%, {rgba} 50% 100%)"
                    else:
                        bg_style = rgba
                    row.append(
                        f"<td style='background:{bg_style};border:2px dashed {color};width:28px;text-align:center;font-weight:800'>{label}</td>"
                    )
                else:
                    if half == "am":
                        bg_style = f"linear-gradient(135deg, {color} 0 50%, #fff 50% 100%)"
                        row.append(
                            f"<td style='background:{bg_style};border:{border_css};width:28px;text-align:center;font-weight:800;color:#000'>{label}</td>"
                        )
                    elif half == "pm":
                        bg_style = f"linear-gradient(135deg, #fff 0 50%, {color} 50% 100%)"
                        row.append(
                            f"<td style='background:{bg_style};border:{border_css};width:28px;text-align:center;font-weight:800;color:#000'>{label}</td>"
                        )
                    else:
                        row.append(
                            f"<td style='background:{color};color:{txt};text-align:center;width:28px;font-weight:800;border:{border_css}'>{label}</td>"
                        )
            else:
                row.append(f"<td style='background:{bg};border:{border_css};width:28px'></td>")
        rows.append("<tr>"+"".join(row)+"</tr>")

    table_html = f"""
    <table>
      <thead><tr>{''.join(head_cells)}</tr></thead>
      <tbody>{''.join(rows) if rows else ''}</tbody>
    </table>
    """
    st.markdown(table_html, unsafe_allow_html=True)

    # Legend
    pend_al_rgba = hex_to_rgba(PRIMARY, 0.18)
    pend_s_rgba  = hex_to_rgba(SICK, 0.18)
    st.markdown(
        f"""
        <div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
          <span class="legend-chip">
            <i class="legend-swatch" style="background:{PRIMARY}"></i>Annual Leave (AL)
          </span>
          <span class="legend-chip">
            <i class="legend-swatch" style="background:{SICK}"></i>Sickness (S)
          </span>
          <span class="legend-chip">
            <i class="legend-swatch" style="background:{pend_al_rgba}; border:2px dashed {PRIMARY}"></i>Pending (AL)
          </span>
          <span class="legend-chip">
            <i class="legend-swatch" style="background:{pend_s_rgba}; border:2px dashed {SICK}"></i>Pending (S)
          </span>
          <span class="legend-chip">
            <i class="legend-swatch" style="background:linear-gradient(135deg, {PRIMARY} 0 50%, #fff 50% 100%);"></i>Half-day AM
          </span>
          <span class="legend-chip">
            <i class="legend-swatch" style="background:linear-gradient(135deg, #fff 0 50%, {PRIMARY} 50% 100%);"></i>Half-day PM
          </span>
          <span class="legend-chip">
            <i class="legend-swatch" style="background:{WEEKEND}"></i>Weekend / Bank Holiday
          </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("</div>", unsafe_allow_html=True)

# ==============================
# ======= BULK CANCEL UI =======
# ==============================
st.markdown("### ❌ Cancel Booking(s)")
st.caption("Select a team member, tick the booking(s) to cancel, then press **Cancel Selected**.")

if not team_members:
    st.info("No team members found in the Team tab.")
else:
    sel_member = st.selectbox("Team member", team_members, index=0)

    today_norm = pd.Timestamp.now().normalize()
    member_reqs = pd.DataFrame(columns=df_req.columns)
    if not df_req.empty:
        # Allow cancelling anything in the future; use raw df_req (not the filtered view) so Pending can be cancelled too
        member_reqs = df_req[
            (df_req["Team Member"] == sel_member) &
            (df_req["Type"] == "Annual Leave") &
            (df_req["Until (Date)"] >= today_norm)
        ].copy()

    if member_reqs.empty:
        st.info(f"{sel_member} has no upcoming Annual Leave bookings.")
    else:
        member_reqs["Label"] = member_reqs.apply(
            lambda r: f"{r['From (Date)'].strftime('%d %b %Y')} → {r['Until (Date)'].strftime('%d %b %Y')} ({r['Status']})",
            axis=1
        )
        labels = member_reqs["Label"].tolist()
        picks = st.multiselect("Choose booking(s) to cancel", options=labels)

        if picks:
            preview = (member_reqs[member_reqs["Label"].isin(picks)]
                       [["Type","From (Date)","Until (Date)","Status"]]
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
