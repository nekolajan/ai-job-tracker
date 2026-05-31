"""
dashboard/app.py

AI Job Tracker — Modern redesign with:
  • Kanban pipeline view
  • Interactive Plotly charts (score distribution, status funnel, source breakdown)
  • Polished card UI with animated hover effects
  • Sticky sidebar with smart filters
  • Quick-action status buttons
  • Color-coded score rings
  • Responsive layout

Run: streamlit run dashboard/app.py
"""

import os
import re
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

DEMO_MODE     = not os.environ.get("GCP_PROJECT_ID")
RAW_JOBS_PATH = Path(__file__).parent.parent / "data" / "raw_jobs.json"

STATUSES = ["new", "saved", "applied", "replied", "interview", "rejected", "ignored"]

STATUS_CONFIG = {
    "new":       {"emoji": "🆕", "color": "#6B7280", "bg": "#F3F4F6", "dark_bg": "#374151", "label": "New"},
    "saved":     {"emoji": "⭐", "color": "#D97706", "bg": "#FEF3C7", "dark_bg": "#451A03", "label": "Saved"},
    "applied":   {"emoji": "📤", "color": "#2563EB", "bg": "#DBEAFE", "dark_bg": "#1E3A5F", "label": "Applied"},
    "replied":   {"emoji": "💬", "color": "#7C3AED", "bg": "#EDE9FE", "dark_bg": "#3B0764", "label": "Replied"},
    "interview": {"emoji": "📅", "color": "#059669", "bg": "#D1FAE5", "dark_bg": "#064E3B", "label": "Interview"},
    "rejected":  {"emoji": "❌", "color": "#DC2626", "bg": "#FEE2E2", "dark_bg": "#450A0A", "label": "Rejected"},
    "ignored":   {"emoji": "🙈", "color": "#9CA3AF", "bg": "#F9FAFB", "dark_bg": "#1F2937", "label": "Ignored"},
}

SCORE_THRESHOLDS = {"high": 75, "medium": 50}


# ── CSS ───────────────────────────────────────────────────────────────────────

GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

:root {
    --radius-sm: 8px;
    --radius-md: 14px;
    --radius-lg: 20px;
    --shadow-sm: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06);
    --shadow-md: 0 4px 16px rgba(0,0,0,.10), 0 2px 6px rgba(0,0,0,.07);
    --transition: all 0.22s cubic-bezier(0.4,0,0.2,1);
    --accent: #6366F1;
    --accent-light: #EEF2FF;
}

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
.block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1400px !important;
}

#MainMenu, footer { visibility: hidden; }
.stDeployButton { display: none; }

/* ── Page header ── */
.page-header {
    background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 50%, #A78BFA 100%);
    border-radius: var(--radius-lg);
    padding: 1.8rem 2rem;
    margin-bottom: 1.5rem;
    color: white;
    position: relative;
    overflow: hidden;
}
.page-header::before {
    content: '';
    position: absolute;
    top: -40%; right: -10%;
    width: 350px; height: 350px;
    background: rgba(255,255,255,0.07);
    border-radius: 50%;
}
.page-header::after {
    content: '';
    position: absolute;
    bottom: -50%; right: 15%;
    width: 200px; height: 200px;
    background: rgba(255,255,255,0.05);
    border-radius: 50%;
}
.page-header h1 {
    font-size: 2rem !important;
    font-weight: 800 !important;
    margin: 0 !important;
    color: white !important;
    letter-spacing: -0.03em;
}
.page-header p {
    margin: 0.3rem 0 0 !important;
    opacity: 0.85;
    font-size: 0.95rem;
}

/* ── Demo banner ── */
.demo-banner {
    background: linear-gradient(90deg, #FEF3C7, #FDE68A);
    border: 1px solid #F59E0B;
    border-radius: var(--radius-sm);
    padding: 0.6rem 1rem;
    font-size: 0.85rem;
    color: #92400E;
    margin-bottom: 1rem;
}

/* ── Metric cards ── */
.metric-card {
    background: white;
    border: 1px solid #E5E7EB;
    border-radius: var(--radius-md);
    padding: 1rem 1.1rem;
    text-align: center;
    box-shadow: var(--shadow-sm);
    transition: var(--transition);
    position: relative;
    overflow: hidden;
}
.metric-card:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.metric-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--accent), #8B5CF6);
    border-radius: var(--radius-md) var(--radius-md) 0 0;
}
.metric-value { font-size: 1.8rem; font-weight: 800; color: #111827 !important; line-height: 1; margin-bottom: 0.25rem; }
.metric-label { font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: #9CA3AF !important; }
.metric-delta { font-size: 0.75rem; font-weight: 500; margin-top: 0.2rem; color: #6B7280; }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0.5rem;
    background: transparent !important;
    border-bottom: 2px solid #E5E7EB;
}
.stTabs [data-baseweb="tab"] {
    border-radius: var(--radius-sm) var(--radius-sm) 0 0 !important;
    padding: 0.6rem 1.2rem !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    color: #6B7280 !important;
    background: transparent !important;
    border: none !important;
    transition: var(--transition) !important;
}
.stTabs [aria-selected="true"] {
    color: var(--accent) !important;
    background: #EEF2FF !important;
    border-bottom: 2px solid var(--accent) !important;
}

/* ── Job card ── */
.job-card {
    background: white;
    border: 1px solid #E5E7EB;
    border-radius: var(--radius-md);
    padding: 1.1rem 1.3rem;
    margin-bottom: 0.8rem;
    transition: var(--transition);
    position: relative;
    overflow: hidden;
}
.job-card:hover { box-shadow: var(--shadow-md); border-color: #C7D2FE; transform: translateY(-1px); }
.job-card-accent {
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 4px;
    border-radius: var(--radius-md) 0 0 var(--radius-md);
}

/* ── Score ring ── */
.score-ring {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 52px; height: 52px;
    border-radius: 50%;
    font-size: 1rem;
    font-weight: 800;
    border: 3px solid;
    flex-shrink: 0;
}
.score-high   { color: #059669; border-color: #059669; background: #F0FDF4; }
.score-medium { color: #D97706; border-color: #D97706; background: #FFFBEB; }
.score-low    { color: #DC2626; border-color: #DC2626; background: #FFF5F5; }

/* ── Status pill ── */
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.73rem;
    font-weight: 700;
    white-space: nowrap;
}

/* ── Tag chips ── */
.tag-chip {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 0.72rem;
    font-weight: 600;
    margin: 2px;
}
.tag-skill  { background: #EEF2FF; color: #4338CA; border: 1px solid #C7D2FE; }
.tag-gap    { background: #FFF7ED; color: #C2410C; border: 1px solid #FED7AA; }
.tag-salary { background: #F0FDF4; color: #15803D; border: 1px solid #BBF7D0; }
.tag-remote { background: #F0F9FF; color: #0369A1; border: 1px solid #BAE6FD; }

/* ── Job title & meta ── */
.job-title   { font-size: 1rem; font-weight: 700; color: #111827 !important; line-height: 1.3; }
.job-company { font-size: 0.88rem; font-weight: 500; color: #6366F1 !important; }

/* Override Streamlit dark mode inheritance for custom HTML components */
.job-card, .job-card * { color: inherit; }
.job-title        { color: #111827 !important; }
.job-company      { color: #6366F1 !important; }
.job-meta         { color: #9CA3AF !important; }
.job-meta span    { color: #9CA3AF !important; }
.metric-card      { color-scheme: light; }
.metric-value     { color: #111827 !important; }
.metric-label     { color: #9CA3AF !important; }
.kanban-col       { color-scheme: light; }
.kanban-card-title   { color: #111827 !important; }
.kanban-card-company { color: #6B7280 !important; }
.score-high   { color: #059669 !important; }
.score-medium { color: #D97706 !important; }
.score-low    { color: #DC2626 !important; }
.section-divider-label { color: #9CA3AF !important; }
.empty-state-title { color: #6B7280 !important; }
.empty-state-sub   { color: #9CA3AF !important; }

/* Force light background on cards regardless of theme */
.job-card     { background: white !important; color-scheme: light; }
.metric-card  { background: white !important; }
.kanban-card  { background: white !important; }
.kanban-col   { background: #F9FAFB !important; }
.job-meta {
    font-size: 0.78rem; color: #9CA3AF;
    display: flex; flex-wrap: wrap; gap: 0.6rem;
    margin-top: 0.35rem; align-items: center;
}
.job-meta span { display: flex; align-items: center; gap: 3px; }

/* ── Kanban ── */
.kanban-col {
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: var(--radius-md);
    padding: 0.75rem;
    min-height: 200px;
}
.kanban-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 0.6rem; padding-bottom: 0.5rem; border-bottom: 2px solid;
}
.kanban-title { font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; }
.kanban-count { font-size: 0.75rem; font-weight: 700; padding: 1px 8px; border-radius: 999px; }
.kanban-card {
    background: white; border: 1px solid #E5E7EB;
    border-radius: var(--radius-sm); padding: 0.65rem 0.8rem;
    margin-bottom: 0.5rem; transition: var(--transition);
}
.kanban-card:hover { box-shadow: var(--shadow-sm); border-color: #C7D2FE; }
.kanban-card-title  { font-weight: 600; color: #111827 !important; font-size: 0.82rem; line-height: 1.3; margin-bottom: 2px; }
.kanban-card-company { color: #6B7280; font-size: 0.75rem; }
.kanban-card-score  { float: right; font-weight: 700; font-size: 0.78rem; padding: 1px 6px; border-radius: 4px; }

/* ── Section divider ── */
.section-divider { display: flex; align-items: center; gap: 0.75rem; margin: 1.2rem 0 1rem; }
.section-divider-line { flex: 1; height: 1px; background: #E5E7EB; }
.section-divider-label {
    font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.09em; color: #9CA3AF; white-space: nowrap;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] { background: #FAFAFA !important; border-right: 1px solid #E5E7EB !important; }
.sidebar-section-title {
    font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: #9CA3AF; margin-bottom: 0.5rem;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: var(--radius-sm) !important;
    font-weight: 600 !important; font-size: 0.8rem !important;
    transition: var(--transition) !important;
}
.stButton > button:hover { transform: translateY(-1px) !important; box-shadow: var(--shadow-sm) !important; }
.stLinkButton > a {
    border-radius: var(--radius-sm) !important; font-weight: 600 !important;
    background: linear-gradient(135deg, #6366F1, #8B5CF6) !important;
    border: none !important; color: white !important;
}

/* ── Empty state ── */
.empty-state { text-align: center; padding: 3rem 1rem; color: #9CA3AF; }
.empty-state-icon { font-size: 3rem; margin-bottom: 0.75rem; }
.empty-state-title { font-size: 1.1rem; font-weight: 600; color: #6B7280; margin-bottom: 0.3rem; }
.empty-state-sub { font-size: 0.85rem; }

/* ── Inputs ── */
div[data-testid="stTextInput"] input {
    border-radius: var(--radius-sm) !important;
    border-color: #E5E7EB !important; font-size: 0.88rem !important;
}
div[data-testid="stTextInput"] input:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.15) !important;
}
div[data-testid="stSelectbox"] > div { border-radius: var(--radius-sm) !important; border-color: #E5E7EB !important; }
div[data-testid="stAlert"] { border-radius: var(--radius-sm) !important; font-size: 0.85rem !important; }
</style>
"""


# ── salary parsing ────────────────────────────────────────────────────────────

def parse_salary(salary_str: str) -> dict | None:
    if not salary_str:
        return None
    s = salary_str.replace("\xa0", "").replace("\u200d", "").replace(" ", "")
    currency = "CZK" if "Kč" in s else ("EUR" if "€" in s else "USD")
    period   = "hour" if "/hr" in s.lower() or "/h" in s.lower() else "month"
    numbers  = [int(n.replace(" ", "")) for n in re.findall(r"[\d\s]{2,}", s) if n.strip()]
    if not numbers:
        return None
    return {
        "min": numbers[0],
        "max": numbers[1] if len(numbers) > 1 else numbers[0],
        "currency": currency,
        "period": period,
        "raw": salary_str,
    }


def enrich_salary(df: pd.DataFrame) -> pd.DataFrame:
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
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


# ── data loading ──────────────────────────────────────────────────────────────

def _mock_scores(jobs: list[dict]) -> list[dict]:
    random.seed(42)
    skills_pool = ["SQL", "Python", "BigQuery", "Tableau", "Power BI", "Airflow", "dbt", "Spark", "Looker"]
    gaps_pool   = ["Spark", "Kafka", "ML background", "Java", "Scala"]
    statuses    = ["new", "saved", "applied", "replied", "interview", "rejected"]
    weights     = [0.30, 0.20, 0.25, 0.10, 0.10, 0.05]
    out = []
    for j in jobs:
        score = random.randint(40, 95)
        out.append({
            **j,
            "score":           score,
            "match_summary":   "Demo mode — connect BigQuery to see real AI scoring.",
            "skills_match":    random.sample(skills_pool, k=random.randint(2, 5)),
            "gaps":            random.sample(gaps_pool, k=random.randint(0, 2)),
            "seniority_match": score > 60,
            "remote_match":    "remote" in j.get("location", "").lower()
                               or j.get("source") == "remotive",
            "status":          random.choices(statuses, weights=weights, k=1)[0],
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

    table    = f"{project}.{os.environ['BQ_DATASET']}.{os.environ['BQ_TABLE']}"
    ov_table = f"{project}.{os.environ['BQ_DATASET']}.status_overrides"

    # Check if status_overrides table exists
    try:
        client.get_table(ov_table)
        overrides_exist = True
    except Exception:
        overrides_exist = False

    if overrides_exist:
        # Merge latest status override per job_id at read time
        query = f"""
            SELECT
                j.job_id, j.title, j.company, j.location, j.url, j.source, j.salary,
                j.score, j.match_summary, j.skills_match, j.gaps,
                j.seniority_match, j.remote_match,
                COALESCE(o.status, j.status) AS status,
                DATE(j.scraped_at) AS date_scraped
            FROM `{table}` j
            LEFT JOIN (
                SELECT job_id, status
                FROM (
                    SELECT job_id, status,
                           ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY updated_at DESC) AS rn
                    FROM `{ov_table}`
                ) WHERE rn = 1
            ) o ON j.job_id = o.job_id
            ORDER BY j.score DESC, j.scraped_at DESC
        """
    else:
        query = f"""
            SELECT job_id, title, company, location, url, source, salary,
                   score, match_summary, skills_match, gaps,
                   seniority_match, remote_match, status,
                   DATE(scraped_at) AS date_scraped
            FROM `{table}`
            ORDER BY score DESC, scraped_at DESC
        """
    return client.query(query).to_dataframe()


def get_bq_client():
    from google.cloud import bigquery
    from google.oauth2 import service_account
    project    = os.environ["GCP_PROJECT_ID"]
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        import json
        info  = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return bigquery.Client(project=project, credentials=creds)
    return bigquery.Client(project=project)


def save_status(job_id: str, new_status: str) -> None:
    """
    Save status change to session state and to a status_overrides table in BigQuery.
    Uses load jobs (free-tier compatible) instead of DML UPDATE.
    The load_jobs() query merges overrides at read time via a LEFT JOIN.
    """
    st.session_state.status_overrides[job_id] = new_status
    if not DEMO_MODE:
        import tempfile, json as _json
        from google.cloud import bigquery
        project  = os.environ["GCP_PROJECT_ID"]
        dataset  = os.environ["BQ_DATASET"]
        client   = get_bq_client()
        ov_table = f"{project}.{dataset}.status_overrides"

        # Ensure status_overrides table exists
        schema = [
            bigquery.SchemaField("job_id",     "STRING",    mode="REQUIRED"),
            bigquery.SchemaField("status",     "STRING",    mode="REQUIRED"),
            bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
        ]
        try:
            client.get_table(ov_table)
        except Exception:
            client.create_table(bigquery.Table(ov_table, schema=schema))

        # Append the override row via load job (free-tier compatible)
        row = _json.dumps({
            "job_id":     job_id,
            "status":     new_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(row + "\n")
            tmp_path = f.name

        job_config = bigquery.LoadJobConfig(
            schema=schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        with open(tmp_path, "rb") as f:
            client.load_table_from_file(f, ov_table, job_config=job_config).result()
        os.unlink(tmp_path)


# ── helpers ───────────────────────────────────────────────────────────────────

def score_class(score) -> str:
    if pd.isna(score):
        return "score-medium"
    s = int(score)
    if s >= SCORE_THRESHOLDS["high"]:   return "score-high"
    if s >= SCORE_THRESHOLDS["medium"]: return "score-medium"
    return "score-low"


def score_ring_html(score) -> str:
    if pd.isna(score):
        return '<div class="score-ring score-medium">—</div>'
    s = int(score)
    return f'<div class="score-ring {score_class(score)}">{s}</div>'


def status_pill_html(status: str) -> str:
    cfg = STATUS_CONFIG.get(status, STATUS_CONFIG["new"])
    return (
        f'<span class="status-pill" style="background:{cfg["bg"]};color:{cfg["color"]}">'
        f'{cfg["emoji"]} {cfg["label"]}</span>'
    )


def tag_html(text: str, kind: str = "skill") -> str:
    icons = {"skill": "✓", "gap": "△", "salary": "💰", "remote": "🌐"}
    return f'<span class="tag-chip tag-{kind}">{icons.get(kind,"")} {text}</span>'


def section_divider(label: str) -> None:
    st.markdown(
        f'<div class="section-divider">'
        f'<div class="section-divider-line"></div>'
        f'<div class="section-divider-label">{label}</div>'
        f'<div class="section-divider-line"></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar(df: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.markdown("""
        <div style="padding:0.5rem 0 1rem; text-align:center;">
            <div style="font-size:1.8rem;">🎯</div>
            <div style="font-weight:800;font-size:1.1rem;color:#111827;">Job Tracker</div>
            <div style="font-size:0.75rem;color:#9CA3AF;margin-top:2px;">AI-powered job hunt</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="sidebar-section-title">🔍 Search</div>', unsafe_allow_html=True)
        search_query = st.text_input("Search jobs", placeholder="Title, company, skill…", label_visibility="collapsed")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">⚡ Match Score</div>', unsafe_allow_html=True)
        min_score = st.slider("Minimum score", 0, 100, 50, step=5, label_visibility="collapsed")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">📡 Source</div>', unsafe_allow_html=True)
        sources = ["All"] + sorted(df["source"].dropna().unique().tolist())
        source  = st.selectbox("Source", sources, label_visibility="collapsed")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">📋 Status</div>', unsafe_allow_html=True)
        status_filter = st.multiselect(
            "Status",
            options=STATUSES,
            default=["new", "saved", "applied", "replied", "interview"],
            format_func=lambda s: f"{STATUS_CONFIG[s]['emoji']} {STATUS_CONFIG[s]['label']}",
            label_visibility="collapsed",
        )

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">🎛️ Options</div>', unsafe_allow_html=True)
        remote_only = st.toggle("Remote only", value=False)
        salary_only = st.toggle("Has salary listed", value=False)

        st.markdown("<br>", unsafe_allow_html=True)
        czk_jobs = df[df["salary_currency"] == "CZK"]
        salary_range = None
        if not czk_jobs.empty:
            st.markdown('<div class="sidebar-section-title">💰 Salary Range (CZK/month)</div>', unsafe_allow_html=True)
            czk_min = int(czk_jobs["salary_min"].dropna().min())
            czk_max = int(czk_jobs["salary_max"].dropna().max())
            salary_range = st.slider(
                "CZK range", min_value=czk_min, max_value=czk_max,
                value=(czk_min, czk_max), step=5_000, format="%d Kč",
                label_visibility="collapsed",
            )
            st.markdown("<br>", unsafe_allow_html=True)

        st.markdown('<div class="sidebar-section-title">↕️ Sort By</div>', unsafe_allow_html=True)
        sort_by = st.selectbox(
            "Sort",
            ["Score (high→low)", "Score (low→high)", "Date (newest)", "Company (A→Z)"],
            label_visibility="collapsed",
        )

        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Refresh", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        with col2:
            if st.button("🗑️ Reset", use_container_width=True):
                st.session_state.status_overrides = {}
                st.rerun()

        st.markdown(
            f'<div style="text-align:center;font-size:0.72rem;color:#9CA3AF;margin-top:0.75rem;">'
            f'Updated {datetime.now(timezone.utc).strftime("%H:%M UTC")}</div>',
            unsafe_allow_html=True,
        )

    # ── Apply filters ──
    f = df.copy()

    if search_query:
        q = search_query.lower()
        mask = (
            f["title"].str.lower().str.contains(q, na=False) |
            f["company"].str.lower().str.contains(q, na=False) |
            f["location"].str.lower().str.contains(q, na=False)
        )
        f = f[mask]

    f = f[f["score"] >= min_score]
    if source != "All":         f = f[f["source"] == source]
    if status_filter:           f = f[f["status"].isin(status_filter)]
    if remote_only:             f = f[f["remote_match"] == True]
    if salary_only:             f = f[f["salary"].notna() & (f["salary"] != "")]

    if salary_range and not czk_jobs.empty:
        lo, hi = salary_range
        no_czk = f[f["salary_currency"] != "CZK"]
        in_czk = f[(f["salary_currency"] == "CZK") & (f["salary_min"] <= hi) & (f["salary_max"] >= lo)]
        f = pd.concat([no_czk, in_czk])

    sort_map = {
        "Score (high→low)": ("score", False),
        "Score (low→high)": ("score", True),
        "Date (newest)":    ("date_scraped", False),
        "Company (A→Z)":    ("company", True),
    }
    col, asc = sort_map.get(sort_by, ("score", False))
    f = f.sort_values(col, ascending=asc)

    return f.reset_index(drop=True)


# ── metrics bar ───────────────────────────────────────────────────────────────

def render_metrics(df: pd.DataFrame, filtered: pd.DataFrame) -> None:
    avg_score       = f"{filtered['score'].mean():.0f}" if len(filtered) else "—"
    with_salary     = int((filtered["salary"].fillna("") != "").sum())
    applied_count   = len(df[df["status"] == "applied"])
    interview_count = len(df[df["status"] == "interview"])

    metrics = [
        ("Total Jobs",  len(df),           None),
        ("Showing",     len(filtered),      f"{len(filtered)/max(len(df),1)*100:.0f}% of total"),
        ("Avg Score",   avg_score,          "match quality"),
        ("With Salary", with_salary,        "listed"),
        ("Applied",     applied_count,      "in pipeline"),
        ("Interviews",  interview_count,    "🎉" if interview_count > 0 else "keep going"),
    ]

    for col, (label, val, delta) in zip(st.columns(6), metrics):
        delta_html = f'<div class="metric-delta">{delta}</div>' if delta else ""
        col.markdown(
            f'<div class="metric-card">'
            f'<div class="metric-value">{val}</div>'
            f'<div class="metric-label">{label}</div>'
            f'{delta_html}</div>',
            unsafe_allow_html=True,
        )


# ── analytics ─────────────────────────────────────────────────────────────────

def render_analytics(df: pd.DataFrame, filtered: pd.DataFrame) -> None:
    section_divider("Analytics Overview")
    c1, c2, c3 = st.columns(3)

    # Score distribution
    with c1:
        fig = px.histogram(
            filtered, x="score", nbins=20, title="Score Distribution",
            color_discrete_sequence=["#6366F1"], labels={"score": "Match Score"},
        )
        fig.update_layout(
            plot_bgcolor="white", paper_bgcolor="white", font_family="Inter",
            title_font_size=14, title_font_color="#111827",
            margin=dict(l=10, r=10, t=40, b=10), height=240, showlegend=False,
            xaxis=dict(showgrid=False, color="#9CA3AF"),
            yaxis=dict(showgrid=True, gridcolor="#F3F4F6", color="#9CA3AF"),
        )
        if len(filtered):
            fig.add_vline(
                x=filtered["score"].mean(), line_dash="dash", line_color="#8B5CF6",
                annotation_text=f"avg {filtered['score'].mean():.0f}",
                annotation_font_color="#8B5CF6", annotation_font_size=11,
            )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # Pipeline status bar
    with c2:
        status_counts = df.groupby("status").size().reset_index(name="count")
        status_counts["label"] = status_counts["status"].apply(
            lambda s: f"{STATUS_CONFIG.get(s,{}).get('emoji','')} {s.title()}"
        )
        fig2 = px.bar(
            status_counts, x="label", y="count", title="Pipeline Status",
            color="status",
            color_discrete_map={s: STATUS_CONFIG[s]["color"] for s in STATUS_CONFIG},
            labels={"label": "", "count": "Jobs"},
        )
        fig2.update_layout(
            plot_bgcolor="white", paper_bgcolor="white", font_family="Inter",
            title_font_size=14, title_font_color="#111827",
            margin=dict(l=10, r=10, t=40, b=10), height=240, showlegend=False,
            xaxis=dict(showgrid=False, color="#9CA3AF", tickfont_size=11),
            yaxis=dict(showgrid=True, gridcolor="#F3F4F6", color="#9CA3AF"),
        )
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    # Source donut
    with c3:
        source_counts = filtered.groupby("source").size().reset_index(name="count")
        fig3 = px.pie(
            source_counts, values="count", names="source", title="Jobs by Source",
            color_discrete_sequence=px.colors.qualitative.Pastel, hole=0.55,
        )
        fig3.update_layout(
            font_family="Inter", title_font_size=14, title_font_color="#111827",
            margin=dict(l=10, r=10, t=40, b=10), height=240,
            legend=dict(font_size=11, orientation="v", x=1.0, y=0.5),
        )
        fig3.update_traces(textposition="inside", textinfo="percent", textfont_size=11)
        st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})


# ── job cards ─────────────────────────────────────────────────────────────────

def render_cards(filtered: pd.DataFrame) -> None:
    if filtered.empty:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-state-icon">🔍</div>
            <div class="empty-state-title">No jobs match your filters</div>
            <div class="empty-state-sub">Try adjusting the score threshold or status filters in the sidebar.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    section_divider(f"{len(filtered)} Jobs Found")

    for _, job in filtered.iterrows():
        job_id  = job["job_id"]
        current = st.session_state.status_overrides.get(job_id, job.get("status", "new"))
        salary  = job.get("salary", "") or ""
        s       = int(job["score"]) if not pd.isna(job.get("score")) else 0
        accent  = "#059669" if s >= 75 else ("#D97706" if s >= 50 else "#DC2626")

        with st.container():
            st.markdown(
                f'<div class="job-card"><div class="job-card-accent" style="background:{accent};"></div>',
                unsafe_allow_html=True,
            )

            c_score, c_main, c_status = st.columns([1, 7, 2])

            with c_score:
                st.markdown(score_ring_html(job["score"]), unsafe_allow_html=True)

            with c_main:
                st.markdown(
                    f'<div class="job-title">{job["title"]}</div>'
                    f'<div class="job-company">{job["company"]}</div>',
                    unsafe_allow_html=True,
                )
                meta_items = [f'<span>📍 {job["location"]}</span>', f'<span>📡 {job["source"]}</span>']
                if salary:
                    meta_items.append(f'<span class="tag-chip tag-salary">💰 {salary}</span>')
                if job.get("remote_match"):
                    meta_items.append('<span class="tag-chip tag-remote">🌐 Remote</span>')
                if job.get("date_scraped"):
                    meta_items.append(f'<span>🗓 {job["date_scraped"]}</span>')
                st.markdown(f'<div class="job-meta">{"".join(meta_items)}</div>', unsafe_allow_html=True)

            with c_status:
                st.markdown(status_pill_html(current), unsafe_allow_html=True)
                new_status = st.selectbox(
                    "Update status", STATUSES,
                    index=STATUSES.index(current) if current in STATUSES else 0,
                    key=f"sel_{job_id}", label_visibility="collapsed",
                    format_func=lambda s: f"{STATUS_CONFIG[s]['emoji']} {STATUS_CONFIG[s]['label']}",
                )
                if new_status != current:
                    save_status(job_id, new_status)
                    st.rerun()

            with st.expander("✦ View details & AI analysis"):
                d1, d2, d3 = st.columns(3)
                d1.metric("Match Score", f"{int(job['score'])}/100" if not pd.isna(job.get("score")) else "—")
                d2.metric("Remote Fit",    "✅ Yes" if job.get("remote_match")   else "❌ No")
                d3.metric("Seniority Fit", "✅ Yes" if job.get("seniority_match") else "❌ No")

                if job.get("match_summary"):
                    st.markdown(
                        f'<div style="background:#F9FAFB;border-left:3px solid #6366F1;'
                        f'padding:0.6rem 0.8rem;border-radius:0 6px 6px 0;'
                        f'font-size:0.85rem;color:#374151;margin:0.5rem 0;">'
                        f'<strong>AI Analysis:</strong> {job["match_summary"]}</div>',
                        unsafe_allow_html=True,
                    )

                sc_col, gap_col = st.columns(2)
                with sc_col:
                    skills = job.get("skills_match") or []
                    if isinstance(skills, str):
                        try: skills = json.loads(skills)
                        except: skills = []
                    if skills:
                        st.markdown("**Matching Skills**")
                        st.markdown(" ".join(tag_html(s, "skill") for s in skills), unsafe_allow_html=True)

                with gap_col:
                    gaps = job.get("gaps") or []
                    if isinstance(gaps, str):
                        try: gaps = json.loads(gaps)
                        except: gaps = []
                    if gaps:
                        st.markdown("**Skill Gaps**")
                        st.markdown(" ".join(tag_html(g, "gap") for g in gaps), unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                st.link_button("Open Job Posting ↗", job["url"], use_container_width=True)

            st.markdown("</div>", unsafe_allow_html=True)


# ── kanban ────────────────────────────────────────────────────────────────────

def render_kanban(df: pd.DataFrame) -> None:
    section_divider("Pipeline Board")
    cols = st.columns(len(STATUSES))

    for col, status in zip(cols, STATUSES):
        cfg   = STATUS_CONFIG[status]
        jobs  = df[df["status"] == status]
        count = len(jobs)

        with col:
            st.markdown(
                f'<div class="kanban-col">'
                f'<div class="kanban-header" style="border-color:{cfg["color"]}">'
                f'<span class="kanban-title" style="color:{cfg["color"]}">{cfg["emoji"]} {cfg["label"]}</span>'
                f'<span class="kanban-count" style="background:{cfg["bg"]};color:{cfg["color"]}">{count}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            if jobs.empty:
                st.markdown(
                    '<div style="text-align:center;padding:1rem;color:#D1D5DB;font-size:0.8rem;">Empty</div>',
                    unsafe_allow_html=True,
                )
            else:
                for _, job in jobs.head(8).iterrows():
                    s           = int(job["score"]) if not pd.isna(job.get("score")) else 0
                    score_color = "#059669" if s >= 75 else ("#D97706" if s >= 50 else "#DC2626")
                    score_bg    = "#F0FDF4" if s >= 75 else ("#FFFBEB" if s >= 50 else "#FFF5F5")
                    title       = job["title"][:35] + ("…" if len(job["title"]) > 35 else "")
                    company     = job["company"][:28] + ("…" if len(job["company"]) > 28 else "")
                    st.markdown(
                        f'<div class="kanban-card">'
                        f'<span class="kanban-card-score" style="color:{score_color};background:{score_bg}">{s}</span>'
                        f'<div class="kanban-card-title">{title}</div>'
                        f'<div class="kanban-card-company">{company}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                if count > 8:
                    st.markdown(
                        f'<div style="text-align:center;font-size:0.75rem;color:#9CA3AF;padding:0.3rem;">+{count-8} more</div>',
                        unsafe_allow_html=True,
                    )

            st.markdown("</div>", unsafe_allow_html=True)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if "status_overrides" not in st.session_state:
        st.session_state.status_overrides = {}

    st.markdown("""
    <div class="page-header">
        <h1>🎯 AI Job Tracker</h1>
        <p>Your intelligent job hunting command center — track, analyze, and win.</p>
    </div>
    """, unsafe_allow_html=True)

    if DEMO_MODE:
        st.markdown("""
        <div class="demo-banner">
            ⚠️ <strong>Demo Mode</strong> — Scores are illustrative.
            Add GCP credentials to <code>.env</code> to enable real AI scoring via Claude.
        </div>
        """, unsafe_allow_html=True)

    try:
        df = load_jobs()
    except Exception as e:
        st.error(f"Could not load jobs: {e}")
        st.stop()

    if df.empty:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-state-icon">📭</div>
            <div class="empty-state-title">No jobs yet</div>
            <div class="empty-state-sub">Run <code>python -m scraper.scrape</code> to fetch your first batch of jobs.</div>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    df = enrich_salary(df)

    if st.session_state.status_overrides:
        df["status"] = df.apply(
            lambda r: st.session_state.status_overrides.get(r["job_id"], r["status"]), axis=1
        )

    filtered = render_sidebar(df)
    render_metrics(df, filtered)

    tab_list, tab_kanban, tab_analytics = st.tabs([
        "📋  Job List",
        "🗂  Pipeline Board",
        "📊  Analytics",
    ])

    with tab_list:
        render_cards(filtered)

    with tab_kanban:
        render_kanban(df)

    with tab_analytics:
        render_analytics(df, filtered)


if __name__ == "__main__":
    main()