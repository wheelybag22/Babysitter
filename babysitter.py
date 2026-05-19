import uuid
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, date, timedelta, time

RATE = 5.00
SITTER = "Shawna"

SHEET_COLS = ["id", "logged_at", "work_date", "sitter",
              "dropoff_time", "pickup_time", "num_kids", "hours", "pay", "notes"]

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# 5-minute increment options between 6:30 AM and 7:00 PM
_TIME_OPTIONS = []
for _h in range(24):
    for _m in range(0, 60, 5):
        _value = time(_h, _m)
        if _value < time(6, 30) or _value > time(19, 0):
            continue
        _label = datetime(2000, 1, 1, _h, _m).strftime("%-I:%M %p")
        _TIME_OPTIONS.append((_label, _value))


def time_select(label: str, default: time) -> time:
    labels = [t[0] for t in _TIME_OPTIONS]
    values = [t[1] for t in _TIME_OPTIONS]
    idx = next((i for i, v in enumerate(values) if v == default), 0)
    chosen = st.selectbox(label, labels, index=idx)
    return values[labels.index(chosen)]


# ─── GOOGLE SHEETS CLIENT ────────────────────────────────────────────────────

@st.cache_resource
def get_sheet():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=_SCOPES,
    )
    client = gspread.authorize(creds)
    return client.open_by_key(st.secrets["SHEET_ID"]).worksheet("sessions")


# ─── DATABASE ────────────────────────────────────────────────────────────────

def init_db():
    sheet = get_sheet()
    header = sheet.row_values(1)
    if not header:
        sheet.append_row(SHEET_COLS)
    elif header != SHEET_COLS:
        sheet.update("A1", [SHEET_COLS])


def add_session(work_date, dropoff: time, pickup: time, num_kids: int, notes=""):
    dt_drop = datetime.combine(work_date, dropoff)
    dt_pick = datetime.combine(work_date, pickup)
    if dt_pick <= dt_drop:
        dt_pick += timedelta(days=1)
    hours = round((dt_pick - dt_drop).total_seconds() / 3600, 4)
    pay = round(hours * RATE * num_kids, 2)
    session_id = str(uuid.uuid4())
    logged_at = datetime.now().isoformat(timespec="seconds")
    get_sheet().append_row([
        session_id,
        logged_at,
        work_date.isoformat(),
        SITTER,
        dropoff.strftime("%H:%M"),
        pickup.strftime("%H:%M"),
        num_kids,
        hours,
        pay,
        notes,
    ])
    return hours, pay


def delete_session(session_id):
    sheet = get_sheet()
    cell = sheet.find(str(session_id), in_column=1)
    if cell:
        sheet.delete_rows(cell.row)


def load_all() -> pd.DataFrame:
    records = get_sheet().get_all_records()
    if not records:
        df = pd.DataFrame(columns=SHEET_COLS)
        df["work_date"] = pd.to_datetime(df["work_date"])
        return df
    df = pd.DataFrame(records)
    for c in SHEET_COLS:
        if c not in df.columns:
            df[c] = None
    df["hours"] = pd.to_numeric(df["hours"], errors="coerce")
    df["pay"] = pd.to_numeric(df["pay"], errors="coerce")
    df["work_date"] = pd.to_datetime(df["work_date"])
    return df.sort_values(["work_date", "id"], ascending=[False, False]).reset_index(drop=True)


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def week_range(d: date):
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def fmt_time(t_str):
    if not t_str:
        return "—"
    try:
        return datetime.strptime(t_str, "%H:%M").strftime("%-I:%M %p")
    except Exception:
        return t_str


def session_label(row):
    drop = fmt_time(row.get("dropoff_time"))
    pick = fmt_time(row.get("pickup_time"))
    kids = int(row.get("num_kids") or 1)
    kids_str = f"  •  {kids} kid{'s' if kids > 1 else ''}"
    return (
        f"{row['work_date'].strftime('%a %b %d')}  •  "
        f"drop-off {drop} → pick-up {pick}  •  "
        f"{row['hours']:.2f} hrs{kids_str}  •  ${row['pay']:.2f}"
    )


# ─── APP ─────────────────────────────────────────────────────────────────────

init_db()

st.set_page_config(page_title="Babysitter Tracker", page_icon="👶", layout="centered")
st.title("👶 Babysitter Tracker")

tab_log, tab_week, tab_history, tab_analytics = st.tabs(
    ["Log Hours", "This Week", "History", "Analytics"]
)

df_all = load_all()

# ── LOG HOURS ────────────────────────────────────────────────────────────────
with tab_log:
    st.subheader(f"Log a session for {SITTER}")

    work_date = st.date_input("Date", value=date.today())

    col1, col2 = st.columns(2)
    with col1:
        dropoff = time_select("Drop-off time", time(7, 0))
    with col2:
        pickup = time_select("Pick-up time", time(15, 30))

    num_kids = st.selectbox("Number of kids", [1, 2, 3], index=2)

    dt_drop = datetime.combine(work_date, dropoff)
    dt_pick = datetime.combine(work_date, pickup)
    if dt_pick <= dt_drop:
        dt_pick += timedelta(days=1)
        overnight_note = " *(next day)*"
    else:
        overnight_note = ""
    preview_hours = (dt_pick - dt_drop).total_seconds() / 3600
    preview_pay = round(preview_hours * RATE * num_kids, 2)

    st.info(
        f"**{preview_hours:.2f} hrs{overnight_note}  →  ${preview_pay:.2f}**  "
        f"({fmt_time(dropoff.strftime('%H:%M'))} – {fmt_time(pickup.strftime('%H:%M'))} @ ${RATE:.0f}/hr × {num_kids} kid{'s' if num_kids > 1 else ''})"
    )

    notes = st.text_input("Notes (optional)", placeholder="e.g. overnight, extra chores")

    if st.button("✅ Save Session", use_container_width=True):
        hours_saved, pay_saved = add_session(work_date, dropoff, pickup, num_kids, notes)
        st.success(f"Saved! {SITTER} earned **${pay_saved:.2f}** for {hours_saved:.2f} hrs on {work_date}.")
        st.rerun()

# ── THIS WEEK ────────────────────────────────────────────────────────────────
with tab_week:
    if "week_offset" not in st.session_state:
        st.session_state.week_offset = 0

    col_prev, col_label, col_next = st.columns([1, 3, 1])
    with col_prev:
        if st.button("◀", use_container_width=True):
            st.session_state.week_offset -= 1
            st.rerun()
    with col_next:
        if st.button("▶", use_container_width=True):
            st.session_state.week_offset += 1
            st.rerun()

    offset_date = date.today() + timedelta(weeks=st.session_state.week_offset)
    mon, sun = week_range(offset_date)
    is_current = st.session_state.week_offset == 0
    week_label = "This Week" if is_current else mon.strftime("%b %d") + " – " + sun.strftime("%b %d, %Y")
    with col_label:
        st.markdown(f"<div style='text-align:center;padding-top:6px'><b>{week_label}</b></div>", unsafe_allow_html=True)

    if not df_all.empty:
        mask = (df_all["work_date"].dt.date >= mon) & (df_all["work_date"].dt.date <= sun)
        df_week = df_all[mask]
    else:
        df_week = df_all

    if df_week.empty:
        st.info("No sessions logged this week yet.")
    else:
        week_hours = df_week["hours"].sum()
        week_pay = df_week["pay"].sum()

        col1, col2, col3 = st.columns(3)
        col1.metric("Hours", f"{week_hours:.2f} hrs")
        col2.metric("Total payout", f"${week_pay:.2f}")
        col3.metric("Morgan's share (1/3)", f"${week_pay / 3:.2f}")

        st.divider()
        st.caption("Sessions")
        for _, row in df_week.iterrows():
            with st.expander(session_label(row)):
                if row["notes"]:
                    st.write(f"Notes: {row['notes']}")
                if st.button("🗑 Delete", key=f"del_week_{row['id']}"):
                    delete_session(row["id"])
                    st.rerun()

# ── HISTORY ──────────────────────────────────────────────────────────────────
with tab_history:
    st.subheader("History")

    if df_all.empty:
        st.info("No sessions logged yet.")
    else:
        weeks_back = st.slider("Weeks back", 1, 52, 8)
        cutoff = date.today() - timedelta(weeks=weeks_back)
        df_hist = df_all[df_all["work_date"].dt.date >= cutoff]

        for _, row in df_hist.iterrows():
            with st.expander(session_label(row)):
                if row["notes"]:
                    st.write(f"Notes: {row['notes']}")
                st.caption(f"Logged at {row['logged_at']}")
                if st.button("🗑 Delete", key=f"del_hist_{row['id']}"):
                    delete_session(row["id"])
                    st.rerun()

        st.divider()
        dl = df_hist[["work_date", "dropoff_time", "pickup_time", "num_kids", "hours", "pay", "notes"]].copy()
        dl["work_date"] = dl["work_date"].dt.strftime("%Y-%m-%d")
        st.download_button("⬇ Download CSV", dl.to_csv(index=False), "babysitter_history.csv", "text/csv")

# ── ANALYTICS ────────────────────────────────────────────────────────────────
with tab_analytics:
    st.subheader("Analytics")

    if df_all.empty:
        st.info("Log some sessions to see analytics.")
    else:
        df_all["week"] = df_all["work_date"].dt.to_period("W").dt.start_time
        weekly = (
            df_all.groupby("week")
            .agg(hours=("hours", "sum"), pay=("pay", "sum"))
            .reset_index()
            .sort_values("week")
        )

        st.markdown("**Weekly spend**")
        st.bar_chart(weekly.set_index("week")["pay"], use_container_width=True)

        col1, col2, col3 = st.columns(3)
        col1.metric("Total paid (all time)", f"${df_all['pay'].sum():.2f}")
        col2.metric("Total hours (all time)", f"{df_all['hours'].sum():.1f} hrs")
        col3.metric("Sessions logged", len(df_all))

        avg_weekly = weekly["pay"].mean()
        st.metric("Avg weekly spend", f"${avg_weekly:.2f}")
