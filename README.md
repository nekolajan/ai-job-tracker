# AI Job Tracker

> Automated job discovery and AI-powered matching pipeline built with Claude API, BigQuery, and Streamlit.

![Dashboard](docs/dashboard.png)

## What it does

Scrapes job postings daily from multiple sources, scores each one against your CV using the Claude API, stores results in BigQuery, and surfaces the best matches in an interactive Streamlit dashboard — fully automated via GitHub Actions.

## Architecture

![Architecture](docs/architecture.png)

```
Job Boards          Claude API          BigQuery            Streamlit
(LinkedIn,    →     AI Scoring    →     Storage       →     Dashboard
 Remotive,          Match score         Deduplication       Filters
 Pracuj.cz)         Gap analysis        History             Status tracking
```

## Tech Stack

| Layer | Tool |
|---|---|
| Scraping | Python (requests, BeautifulSoup) |
| AI Matching | Claude API (Anthropic) |
| Storage | Google BigQuery |
| Dashboard | Streamlit |
| Orchestration | GitHub Actions (daily cron) |
| Language | Python 3.11+ |

## Features

- Daily automated job scraping from multiple sources
- AI-powered match scoring (0–100) against your CV
- Gap analysis — what you have vs. what the role requires
- Interactive dashboard with filters (score, location, remote, date)
- Job status tracking (New / Applied / Interview / Rejected)
- Deduplication — never see the same job twice

## Project Structure

```
ai-job-tracker/
├── .github/workflows/      # GitHub Actions cron schedule
├── scraper/                # Job board scrapers
├── enrichment/             # Claude API scoring logic
├── storage/                # BigQuery read/write
├── dashboard/              # Streamlit app
├── cv/                     # Your CV/profile used by Claude
├── docs/                   # Architecture diagram, screenshots
├── tests/                  # Unit tests
├── config.py               # Job sources, thresholds, settings
├── .env.example            # Environment variable template
└── requirements.txt        # Python dependencies
```

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/nekolajan/ai-job-tracker.git
cd ai-job-tracker
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment variables
```bash
cp .env.example .env
# Fill in your API keys and BigQuery project details
```

### 4. Update your CV profile
Edit `cv/profile.md` with your skills, experience, and job preferences.

### 5. Run manually
```bash
python -m scraper.scrape
python -m enrichment.score
python -m storage.bigquery
```

### 6. Launch dashboard
```bash
streamlit run dashboard/app.py
```

## Automated Pipeline

The pipeline runs automatically every day at 8:00 AM UTC via GitHub Actions.
See `.github/workflows/daily_scrape.yml` for configuration.

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `GCP_PROJECT_ID` | Google Cloud project ID |
| `BQ_DATASET` | BigQuery dataset name |
| `BQ_TABLE` | BigQuery table name |

## Author

Jan Nekola — [LinkedIn](https://www.linkedin.com/in/jan-nekola-02b96468) · [GitHub](https://github.com/nekolajan)
