"""
dashboard/app.py

AI Job Tracker — modern card-based layout.
Run: streamlit run dashboard/app.py
"""

import os
import re
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

DEMO_MODE     = not os.environ.get("GCP_PROJECT_ID")
RAW_JOBS_PATH = Path(__file__).parent.parent / "data" / "raw_jobs.json"

STATUSES = ["new", "saved", "applied", "replied", "interview", "rejected"]

STATUS_STYLE = {
    "new":       ("🆕", "#6B7280", "#F3F4F6"),
    "saved":     ("⭐", "#92400E", "#FEF3C7"),
    "applied":   ("📤", "#1D4ED8", "#DBEAFE"),
    "replied":   ("💬", "#6D28D9", "#EDE9FE"),
    "interview": ("📅", "#065F46", "#D1FAE5"),
    "rejected":  ("❌", "#991B1B", "#FEE2E2"),
}

# ── salary parsing ───────────────────────────────────────────────────────────

def parse_salary(salary_str: str) -> dict | None:
    """
    Parse salary string into structured dict with min, max, currency, period.
    Returns None if unparseable.

    Handles:
      '60 000 – 85 000 Kč'   → {min:60000, max:85000, currency:'CZK', period:'month'}
      '$18 - $22/hr'          → {min:18, max:22, currency:'USD', period:'hour'}
    """
    if not salary_str:
        return None

    s = salary_str.replace("\xa0", "").replace("‍", "").replace(" ", "")

    # detect currency and period
    currency = "CZK" if "Kč" in s else ("EUR" if "€" in s else "USD")
    period   = "hour" if "/hr" in s.lower() or "/h" in s.lower() else "month"

    # extract all numbers
    numbers = [int(n.replace(" ", "")) for n in re.findall(r"[\d\s]{2,}", s) if n.strip()]
    if not numbers:
        return None

    return {
        "min":      numbers[0],
        "max":      numbers[1] if len(numbers) > 1 else numbers[0],
        "currency": currency,
        "period":   period,
        "raw":      salary_str,
    }


def enrich_salary(df: pd.DataFrame) -> pd.DataFrame:
    """Add salary_min, salary_max, salary_currency columns for filtering."""
    parsed = df["salary"].fillna("").apply(parse_salary)
    df["salary_min"]      = parsed.apply(lambda p: p["min"]      if p else None)
    df["salary_max"]      = parsed.apply(lambda p: p["max"]      if p else None)
    df["salary_currency"] = parsed.apply(lambda p: p["currency"] if p else None)
    df["salary_period"]   = parsed.apply(lambda p: p["period"]   if p else None)
    return df


# ── page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="AI Job Tracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* global */
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    h1 { font-size: 1.8rem !important; font-weight: 700 !important; }

    /* job card */
    .job-card {
        background: white;
        border: 1px solid #E5E7EB;
        border-radius: 12px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.75rem;
        transition: box-shadow 0.15s;
    }
    .job-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); }

    /* score badge */
    .score-badge {
        display: inline-block;
        font-size: 1.1rem;
        font-weight: 700;
        min-width: 3rem;
        text-align: center;
    }
    .score-high   { color: #059669; }
    .score-medium { color: #D97706; }
    .score-low    { color: #DC2626; }

    /* status pill */
    .status-pill {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
    }

    /* salary chip */
    .salary-chip {
        display: inline-block;
        background: #F0FDF4;
        color: #15803D;
        border: 1px solid #BBF7D0;
        border-radius: 6px;
        padding: 1px 8px;
        font-size: 0.78rem;
        font-weight: 600;
    }

    /* meta text */
    .meta { color: #6B7280; font-size: 0.82rem; }

    /* section header */
    .section-label {
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #9CA3AF;
        margin-bottom: 0.3rem;
    }

    /* hide streamlit branding */
    #MainMenu, footer { visibility: hidden; }

    /* tighter selectbox */
    div[data-testid="stSelectbox"] > div { min-height: 2rem; }
</style>
""", unsafe_allow_html=True)


# ── data loading ──────────────────────────────────────────────────────────────

def _mock_scores(jobs: list[dict]) -> list[dict]:
    random.seed(42)
    skills_pool = ["SQL", "Python", "BigQuery", "Tableau", "Power BI", "Airflow", "dbt"]
    gaps_pool   = ["Spark", "Kafka", "ML background", "Java"]
    out = []
    for j in jobs:
        score = random.randint(40, 95)
        out.append({
            **j,
            "score":           score,
            "match_summary":   "Demo mode — connect BigQuery to see real AI scoring.",
            "skills_match":    random.sample(skills_pool, k=random.randint(2, 4)),
            "gaps":            random.sample(gaps_pool, k=random.randint(0, 2)),
            "seniority_match": score > 60,
            "remote_match":    "remote" in j.get("location", "").lower()
                               or j.get("source") == "remotive",
            "status":          "new",
            "date_scraped":    j.get("scraped_at", "")[:10],
        })
    return out


@st.cache_data(ttl=300)
def load_jobs() -> pd.DataFrame:
    if DEMO_MODE:
        if not RAW_JOBS_PATH.exists():
            return pd.DataFrame()
        jobs = json.loads(RAW_JOBS_PATH.read_text(encoding="utf-8"))
        df = pd.DataFrame(_mock_scores(jobs))
        return df.sort_values("score", ascending=False).reset_index(drop=True)

    from google.cloud import bigquery
    from google.oauth2 import service_account
    project    = os.environ["GCP_PROJECT_ID"]
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        info  = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        client = bigquery.Client(project=project, credentials=creds)
    else:
        client = bigquery.Client(project=project)

    table = f"{project}.{os.environ['BQ_DATASET']}.{os.environ['BQ_TABLE']}"
    return client.query(f"""
        SELECT job_id, title, company, location, url, source, salary,
               score, match_summary, skills_match, gaps,
               seniority_match, remote_match, status,
               DATE(scraped_at) AS date_scraped
        FROM `{table}`
        ORDER BY score DESC, scraped_at DESC
    """).to_dataframe()


def save_status(job_id: str, new_status: str) -> None:
    """Persist in session_state (demo) or BigQuery (live)."""
    st.session_state.status_overrides[job_id] = new_status
    if not DEMO_MODE:
        from google.cloud import bigquery
        project = os.environ["GCP_PROJECT_ID"]
        client  = bigquery.Client(project=project)
        table   = f"{project}.{os.environ['BQ_DATASET']}.{os.environ['BQ_TABLE']}"
        client.query(
            f"UPDATE `{table}` SET status = '{new_status}' WHERE job_id = '{job_id}'"
        ).result()


# ── helpers ───────────────────────────────────────────────────────────────────

def score_html(score) -> str:
    if pd.isna(score):
        return '<span class="score-badge">—</span>'
    s = int(score)
    cls = "score-high" if s >= 75 else ("score-medium" if s >= 50 else "score-low")
    return f'<span class="score-badge {cls}">{s}</span>'


def status_pill(status: str) -> str:
    emoji, color, bg = STATUS_STYLE.get(status, ("", "#6B7280", "#F3F4F6"))
    return (
        f'<span class="status-pill" style="background:{bg};color:{color}">'
        f'{emoji} {status}</span>'
    )


# ── sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.markdown("## Filters")

    min_score = st.sidebar.slider("Min score", 0, 100, 50, step=5)

    sources = ["All"] + sorted(df["source"].dropna().unique().tolist())
    source  = st.sidebar.selectbox("Source", sources)

    status_filter = st.sidebar.multiselect(
        "Status", STATUSES, default=["new", "saved", "applied", "replied", "interview"]
    )

    remote_only = st.sidebar.checkbox("Remote only", value=False)

    st.sidebar.markdown("**Salary (CZK/month)**")
    czk_jobs = df[df["salary_currency"] == "CZK"]
    if not czk_jobs.empty:
        czk_min = int(czk_jobs["salary_min"].dropna().min())
        czk_max = int(czk_jobs["salary_max"].dropna().max())
        salary_range = st.sidebar.slider(
            "CZK range",
            min_value=czk_min,
            max_value=czk_max,
            value=(czk_min, czk_max),
            step=5_000,
            format="%d Kč",
            label_visibility="collapsed",
        )
    else:
        salary_range = None
    salary_only = st.sidebar.checkbox("Show only jobs with salary listed", value=False)

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.sidebar.caption(f"Updated {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

    f = df[df["score"] >= min_score].copy()
    if source != "All":
        f = f[f["source"] == source]
    if status_filter:
        f = f[f["status"].isin(status_filter)]
    if remote_only:
        f = f[f["remote_match"] == True]
    if salary_only:
        f = f[f["salary"].notna() & (f["salary"] != "")]
    if salary_range and not czk_jobs.empty:
        lo, hi = salary_range
        # keep jobs with no CZK salary (unaffected) + CZK jobs within range
        no_czk  = f[f["salary_currency"] != "CZK"]
        in_czk  = f[
            (f["salary_currency"] == "CZK") &
            (f["salary_min"] <= hi) &
            (f["salary_max"] >= lo)
        ]
        f = pd.concat([no_czk, in_czk]).sort_values("score", ascending=False)
    return f


# ── metrics bar ───────────────────────────────────────────────────────────────

def render_metrics(df: pd.DataFrame, filtered: pd.DataFrame) -> None:
    cols = st.columns(6)
    metrics = [
        ("Total",     len(df)),
        ("Showing",   len(filtered)),
        ("Avg score", f"{filtered['score'].mean():.0f}" if len(filtered) else "—"),
        ("w/ Salary", int((filtered["salary"].fillna("") != "").sum())),
        ("Applied",   len(df[df["status"] == "applied"])),
        ("Interview", len(df[df["status"] == "interview"])),
    ]
    for col, (label, val) in zip(cols, metrics):
        col.metric(label, val)


# ── job cards ─────────────────────────────────────────────────────────────────

def render_cards(filtered: pd.DataFrame) -> None:
    if filtered.empty:
        st.info("No jobs match the current filters.")
        return

    for _, job in filtered.iterrows():
        job_id  = job["job_id"]
        current = st.session_state.status_overrides.get(job_id, job.get("status", "new"))
        salary  = job.get("salary", "") or ""
        with st.container():
            st.markdown('<div class="job-card">', unsafe_allow_html=True)

            # — top row: score | title + company | status selector
            c_score, c_main, c_status = st.columns([1, 7, 2])

            with c_score:
                st.markdown(score_html(job["score"]), unsafe_allow_html=True)

            with c_main:
                st.markdown(
                    f"**{job['title']}** &nbsp;·&nbsp; {job['company']}",
                    unsafe_allow_html=True,
                )
                meta_parts = [f"📍 {job['location']}", f"🔗 {job['source']}"]
                if salary:
                    currency = job.get("salary_currency", "")
                    period   = job.get("salary_period", "")
                    period_label = "/hr" if period == "hour" else "/mo"
                    meta_parts.append(f"💰 {salary} {period_label}" if currency != "CZK" else f"💰 {salary}")
                if job.get("date_scraped"):
                    meta_parts.append(f"📅 {job['date_scraped']}")
                st.markdown(
                    '<span class="meta">' + " &nbsp;|&nbsp; ".join(meta_parts) + "</span>",
                    unsafe_allow_html=True,
                )

            with c_status:
                new_status = st.selectbox(
                    "Status",
                    STATUSES,
                    index=STATUSES.index(current) if current in STATUSES else 0,
                    key=f"sel_{job_id}",
                    label_visibility="collapsed",
                )
                if new_status != current:
                    save_status(job_id, new_status)
                    st.rerun()

            # — detail expander
            with st.expander("View details"):
                d1, d2, d3 = st.columns(3)
                d1.metric("Match score", f"{int(job['score'])}/100" if not pd.isna(job.get('score')) else "—")
                d2.metric("Remote", "✅ Yes" if job.get("remote_match") else "❌ No")
                d3.metric("Seniority", "✅ Yes" if job.get("seniority_match") else "❌ No")

                if job.get("match_summary"):
                    st.markdown("**Why it matches**")
                    st.write(job["match_summary"])

                sc_col, gap_col = st.columns(2)
                with sc_col:
                    skills = job.get("skills_match") or []
                    if isinstance(skills, str):
                        skills = json.loads(skills)
                    if skills:
                        st.markdown("**Matching skills**")
                        for s in skills:
                            st.markdown(f"- ✅ {s}")

                with gap_col:
                    gaps = job.get("gaps") or []
                    if isinstance(gaps, str):
                        gaps = json.loads(gaps)
                    if gaps:
                        st.markdown("**Gaps**")
                        for g in gaps:
                            st.markdown(f"- ⚠️ {g}")

                st.link_button("Open job posting ↗", job["url"], use_container_width=True)

            st.markdown('</div>', unsafe_allow_html=True)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if "status_overrides" not in st.session_state:
        st.session_state.status_overrides = {}

    st.markdown("# 🎯 AI Job Tracker")

    if DEMO_MODE:
        st.warning(
            "**Demo mode** — scores are illustrative. "
            "Add GCP credentials to `.env` to enable real Claude scoring.",
            icon="⚠️",
        )

    try:
        df = load_jobs()
    except Exception as e:
        st.error(f"Could not load jobs: {e}")
        st.stop()

    if df.empty:
        st.warning("No jobs yet. Run `python -m scraper.scrape` first.")
        st.stop()

    df = enrich_salary(df)

    # apply session_state status overrides so changes persist within session
    if st.session_state.status_overrides:
        df["status"] = df.apply(
            lambda r: st.session_state.status_overrides.get(r["job_id"], r["status"]),
            axis=1,
        )

    filtered = render_sidebar(df)
    render_metrics(df, filtered)
    st.markdown("---")
    render_cards(filtered)


if __name__ == "__main__":
    main()
