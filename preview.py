"""
preview.py

Quick browse of raw_jobs.json — shows unscored jobs in a simple Streamlit table.
Run: streamlit run preview.py
"""

import json
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Raw Jobs Preview", layout="wide")

ROOT = Path(__file__).parent
RAW  = ROOT / "data" / "raw_jobs.json"
SCORED = ROOT / "data" / "scored_jobs.json"

st.title("📋 Raw Jobs Preview")

if not RAW.exists():
    st.error("No raw_jobs.json found. Run the scraper first.")
    st.stop()

jobs   = json.loads(RAW.read_text(encoding="utf-8"))
scored_ids = set()
if SCORED.exists():
    scored_ids = {j["job_id"] for j in json.loads(SCORED.read_text(encoding="utf-8"))}

df = pd.DataFrame(jobs)
df["scored"] = df["job_id"].isin(scored_ids)

# ── Sidebar filters ──
with st.sidebar:
    show_only_new = st.toggle("Show only unscored", value=True)
    sources = ["All"] + sorted(df["source"].unique().tolist())
    source  = st.selectbox("Source", sources)
    search  = st.text_input("Search title / company")
    st.markdown(f"**Total:** {len(df)} jobs")
    st.markdown(f"**Unscored:** {len(df[~df['scored']])} jobs")

# ── Apply filters ──
f = df.copy()
if show_only_new:
    f = f[~f["scored"]]
if source != "All":
    f = f[f["source"] == source]
if search:
    q = search.lower()
    f = f[f["title"].str.lower().str.contains(q, na=False) |
          f["company"].str.lower().str.contains(q, na=False)]

st.markdown(f"**Showing {len(f)} jobs**")

# ── Table ──
for _, job in f.iterrows():
    col1, col2, col3, col4 = st.columns([4, 2, 2, 1])
    with col1:
        st.markdown(f"**{job['title']}**")
        st.caption(job.get("company", ""))
    with col2:
        st.caption(f"📍 {job.get('location', '')}")
        st.caption(f"📡 {job.get('source', '')}")
    with col3:
        st.caption(f"💰 {job.get('salary', '') or '—'}")
        st.caption(f"🗓 {str(job.get('scraped_at', ''))[:10]}")
    with col4:
        st.link_button("Open ↗", job["url"])
    st.divider()
