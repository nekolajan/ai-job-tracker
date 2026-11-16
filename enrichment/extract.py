"""
enrichment/extract.py

Reads job descriptions with a small local LLM (Ollama) and stores plain facts
about each job in data/extracted_jobs.json. No score is produced here: the model
only reports what the posting says, and the score is computed from these facts
in code, so weights can change without calling the model again.

Usage:
    python -m enrichment.extract                 # up to MAX_EXTRACTIONS_PER_RUN jobs
    python -m enrichment.extract --limit 3       # quick test
    python -m enrichment.extract --job-id 1a2b3c --show
    python -m enrichment.extract --show          # print what is stored

Requires Ollama running locally (`brew services start ollama`) and the model
pulled (`ollama pull qwen3.5:4b`). Nothing is sent to any outside service.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import (
    EXTRACTION_ENABLED, LLM_PROVIDER, OLLAMA_URL, OLLAMA_MODEL, OLLAMA_CONTEXT_TOKENS,
    OLLAMA_TIMEOUT_SECONDS, MAX_EXTRACTIONS_PER_RUN, EXTRACT_DESCRIPTION_MAX_CHARS,
    EXTRACTION_PROMPT_VERSION, EXTRACTED_JOBS_FILENAME, DATA_DIR, RAW_JOBS_FILENAME,
)

ROOT = Path(__file__).parent.parent
RAW_JOBS_PATH = ROOT / DATA_DIR / RAW_JOBS_FILENAME
EXTRACTED_PATH = ROOT / DATA_DIR / EXTRACTED_JOBS_FILENAME
MIN_DESCRIPTION_CHARS = 200     # shorter texts carry too little to extract from
MAX_ANSWER_TOKENS = 700
_LANGUAGES = {"english", "czech", "slovak", "german", "polish", "french", "spanish", "italian",
              "hungarian", "dutch", "angličtina", "čeština", "němčina", "slovenština"}


# ── what the model fills in ──────────────────────────────────────────────────

ENUMS = {
    "role_family": ["data_engineer", "analytics_engineer", "data_analyst", "bi_developer",
                    "product_analyst", "data_scientist", "ml_ai_engineer", "data_architect",
                    "data_manager", "software_engineer", "other"],
    "seniority":   ["junior", "medior", "senior", "lead", "unknown"],
    "work_mode":   ["onsite", "hybrid", "remote", "unknown"],
    "employment":  ["employee", "contractor", "either", "unknown"],
    "ai_focus":    ["none", "some", "core"],
    "work_type":   ["greenfield", "mixed", "maintenance", "unknown"],
}

SCHEMA = {
    "type": "object",
    "properties": {
        "role_family":          {"type": "string", "enum": ENUMS["role_family"]},
        "seniority":            {"type": "string", "enum": ENUMS["seniority"]},
        "people_management":    {"type": "boolean"},
        "work_mode":            {"type": "string", "enum": ENUMS["work_mode"]},
        "office_days_per_week": {"type": ["integer", "null"]},
        "city":                 {"type": ["string", "null"]},
        "residency_required":   {"type": "boolean"},
        "required_languages":   {"type": "array", "items": {"type": "string"}},
        "stack_required":       {"type": "array", "items": {"type": "string"}},
        "stack_nice_to_have":   {"type": "array", "items": {"type": "string"}},
        "employment":           {"type": "string", "enum": ENUMS["employment"]},
        "ai_focus":             {"type": "string", "enum": ENUMS["ai_focus"]},
        "work_type":            {"type": "string", "enum": ENUMS["work_type"]},
        "evidence":             {"type": "string"},
    },
    "required": ["role_family", "seniority", "people_management", "work_mode",
                 "office_days_per_week", "city", "residency_required", "required_languages",
                 "stack_required", "stack_nice_to_have", "employment", "ai_focus",
                 "work_type", "evidence"],
}

SYSTEM_PROMPT = """You extract facts from a job posting. Report only what the posting says.
Never guess: if something is not stated, use "unknown", null, false or an empty list.
The posting may be in Czech, Slovak, German or English. Always answer in English.

Fields:
- role_family: the main kind of work. data_manager = leads a data team or function.
  software_engineer = builds application or product software (backend, full-stack,
  AI features in a product) where data / analytics is not the main focus.
- seniority: from the title or required years (0-2 junior, 3-5 medior, 5+ senior,
  lead = team or tech lead). "unknown" if neither is stated.
- people_management: true only if managing people is part of the job, not just
  "working with a team" or "mentoring".
- work_mode: remote = fully remote; hybrid = mix of office and home; onsite = office only.
- office_days_per_week: only if a number of office days is stated, else null.
- city: city of the office, else null.
- residency_required: true only if the posting says you must live in, or have
  the right to work in, a specific country.
- required_languages: languages that are required (e.g. "english", "czech", "german").
  Leave out languages listed as an advantage.
- stack_required: tools and technologies listed as requirements.
- stack_nice_to_have: tools listed as an advantage / nice to have / plus /
  "experience with some of the following". Such tools never go to stack_required.
  Ignore tools that appear only in benefits, training offers or the company story.
  Use the usual names: "Power BI", "BigQuery", "dbt", "Airflow", "Python", "SQL".
- employment: contractor = freelance / B2B / IČO / contract; employee = permanent
  employment (HPP, full-time contract); either = both offered; "unknown" if the
  posting does not say.
- ai_focus: core = building AI/ML/LLM products or features is the main job;
  some = AI/ML is mentioned as part of the work; none = not mentioned.
- work_type: greenfield = building something new from scratch; maintenance =
  running and supporting existing reports or pipelines; mixed = both.
- evidence: one short sentence quoting the most telling part of the posting."""

# Shown to the model when the runtime cannot enforce the schema (Ollama's MLX
# runner on Apple Silicon answers "structured output is unavailable").
ANSWER_TEMPLATE = """Answer with one JSON object only, no markdown, no comments, exactly these keys:
{"role_family": "...", "seniority": "...", "people_management": false, "work_mode": "...",
 "office_days_per_week": null, "city": null, "residency_required": false,
 "required_languages": [], "stack_required": [], "stack_nice_to_have": [],
 "employment": "...", "ai_focus": "...", "work_type": "...", "evidence": "..."}
Allowed values:
""" + "\n".join(f"- {k}: {' | '.join(v)}" for k, v in ENUMS.items())


# ── input preparation ────────────────────────────────────────────────────────

def condense(text: str, max_chars: int = EXTRACT_DESCRIPTION_MAX_CHARS) -> str:
    """Collapse whitespace; if still too long keep the start and the end, where
    the role summary and the requirements / conditions usually are."""
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head - 5
    return text[:head] + "\n[…]\n" + text[-tail:]


def build_prompt(job: dict) -> str:
    return (
        f"Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Salary: {job.get('salary') or 'not stated'}\n\n"
        f"Posting:\n{condense(job.get('description', ''))}"
    )


def input_hash(job: dict) -> str:
    return hashlib.sha1(build_prompt(job).encode("utf-8")).hexdigest()[:16]


# ── model call ───────────────────────────────────────────────────────────────

class ExtractionError(Exception):
    pass


# Set to False the first time Ollama says it cannot enforce a JSON schema; the
# rest of the run then asks for JSON in the prompt and parses the answer leniently.
_schema_supported = True


def parse_json_answer(content: str) -> dict:
    """Take the JSON object out of a model answer – tolerates ```json fences and
    text around it."""
    text = re.sub(r"```(?:json)?", "", content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ExtractionError(f"model did not return JSON: {content[:200]!r}")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ExtractionError(f"model returned broken JSON: {content[:200]!r}") from e
    if not isinstance(data, dict):
        raise ExtractionError("model returned JSON that is not an object")
    return data


def _chat(messages: list[dict], use_schema: bool) -> requests.Response:
    body = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "think": False,
        "stream": False,
        "keep_alive": "10m",
        # the JSON answer needs ~200–450 tokens; without a cap a confused answer
        # can run on for many minutes until the context is full
        "options": {"temperature": 0, "num_ctx": OLLAMA_CONTEXT_TOKENS,
                    "num_predict": MAX_ANSWER_TOKENS},
    }
    if use_schema:
        body["format"] = SCHEMA
    return requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=OLLAMA_TIMEOUT_SECONDS)


def call_ollama(prompt: str) -> dict:
    global _schema_supported
    system = SYSTEM_PROMPT if _schema_supported else f"{SYSTEM_PROMPT}\n\n{ANSWER_TEMPLATE}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]

    resp = _chat(messages, use_schema=_schema_supported)
    if _schema_supported and resp.status_code == 501 and "structured output" in resp.text:
        _schema_supported = False
        print("(schema not supported by this Ollama runner – asking for JSON in the prompt) ",
              end="", flush=True)
        messages[0]["content"] = f"{SYSTEM_PROMPT}\n\n{ANSWER_TEMPLATE}"
        resp = _chat(messages, use_schema=False)
    resp.raise_for_status()

    content = resp.json().get("message", {}).get("content", "")
    try:
        return parse_json_answer(content)
    except ExtractionError:
        if _schema_supported:
            raise
        print("(answer was not JSON – asking once more) ", end="", flush=True)
        # one retry, reminding the model of the format (the bad answer is shortened
        # so a long rambling reply does not fill the context)
        messages += [{"role": "assistant", "content": content[:300]},
                     {"role": "user", "content": "Return only the JSON object, nothing else."}]
        resp = _chat(messages, use_schema=False)
        resp.raise_for_status()
        return parse_json_answer(resp.json().get("message", {}).get("content", ""))


# Canonical spelling of common tools (keys: lower-case, "_" and "-" read as spaces)
_TOOL_NAMES = {
    "python": "Python", "sql": "SQL", "r": "R", "excel": "Excel", "power bi": "Power BI",
    "powerbi": "Power BI", "pbi": "Power BI", "dax": "DAX", "tableau": "Tableau",
    "looker": "Looker", "looker studio": "Looker Studio", "qlik": "Qlik", "bigquery": "BigQuery",
    "google bigquery": "BigQuery", "snowflake": "Snowflake", "databricks": "Databricks",
    "dbt": "dbt", "airflow": "Airflow", "apache airflow": "Airflow", "keboola": "Keboola",
    "spark": "Spark", "pyspark": "PySpark", "kafka": "Kafka", "aws": "AWS", "azure": "Azure",
    "gcp": "GCP", "google cloud": "GCP", "docker": "Docker", "kubernetes": "Kubernetes",
    "k8s": "Kubernetes", "aks": "AKS", "terraform": "Terraform", "git": "Git",
    "postgresql": "PostgreSQL", "postgres": "PostgreSQL", "mongodb": "MongoDB",
    "mysql": "MySQL", "ms sql": "SQL Server", "mssql": "SQL Server", "sql server": "SQL Server",
    "redshift": "Redshift", "athena": "Athena", "fabric": "Microsoft Fabric",
    "microsoft fabric": "Microsoft Fabric", "fastapi": "FastAPI", "langchain": "LangChain",
    "langgraph": "LangGraph", "llamaindex": "LlamaIndex", "pandas": "pandas",
    "azure openai": "Azure OpenAI", "openai": "OpenAI", "llmops": "LLMOps", "mlops": "MLOps",
    "ssis": "SSIS", "ssas": "SSAS", "sap": "SAP", "alteryx": "Alteryx", "stata": "Stata",
    "google cloud platform": "GCP", "microsoft excel": "Excel", "ms excel": "Excel",
    "apache spark": "Spark", "apache kafka": "Kafka", "t sql": "T-SQL", "tsql": "T-SQL",
    "ms sql server": "SQL Server", "microsoft sql server": "SQL Server",
    "microsoft power bi": "Power BI", "amazon web services": "AWS", "microsoft azure": "Azure",
    "github": "GitHub", "github actions": "GitHub Actions", "gitlab": "GitLab",
    "power query": "Power Query", "google analytics": "Google Analytics",
}


def tool_name(name: str) -> str:
    """'azure_openai' → 'Azure OpenAI', 'powerbi' → 'Power BI'; unknown names keep
    their spelling, with '_' turned into spaces."""
    plain = re.sub(r"[_\-]+", " ", name).strip()
    return _TOOL_NAMES.get(plain.lower(), plain)


def _clean_list(values) -> list[str]:
    out, seen = [], set()
    for v in values if isinstance(values, list) else []:
        v = str(v).strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def validate(raw: dict) -> dict:
    """Coerce the model output into the schema; unknown enum values become a safe default."""
    facts = {}
    for key, allowed in ENUMS.items():
        value = str(raw.get(key, "")).strip().lower()
        default = "other" if key == "role_family" else ("none" if key == "ai_focus" else "unknown")
        facts[key] = value if value in allowed else default
    for key in ("people_management", "residency_required"):
        facts[key] = raw.get(key) is True
    days = raw.get("office_days_per_week")
    facts["office_days_per_week"] = days if isinstance(days, int) and 0 <= days <= 5 else None
    city = raw.get("city")
    facts["city"] = city.strip() if isinstance(city, str) and city.strip() else None
    facts["required_languages"] = [l.lower() for l in _clean_list(raw.get("required_languages"))]
    def tools(key):          # spoken languages sometimes end up in the stack lists
        return _clean_list([tool_name(str(t)) for t in raw.get(key) or []
                            if str(t).strip().lower() not in _LANGUAGES])
    facts["stack_required"] = tools("stack_required")
    facts["stack_nice_to_have"] = [s for s in tools("stack_nice_to_have")
                                   if s.lower() not in {r.lower() for r in facts["stack_required"]}]
    facts["evidence"] = str(raw.get("evidence") or "")[:300]
    return facts


def extract_job(job: dict) -> dict:
    if LLM_PROVIDER != "ollama":
        raise ExtractionError(f"provider '{LLM_PROVIDER}' is not supported yet")
    started = time.time()
    facts = validate(call_ollama(build_prompt(job)))
    return {
        **facts,
        "model": OLLAMA_MODEL,
        "prompt_version": EXTRACTION_PROMPT_VERSION,
        "input_hash": input_hash(job),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "seconds": round(time.time() - started, 1),
    }


# ── selection & storage ──────────────────────────────────────────────────────

def is_current(stored: dict | None, job: dict) -> bool:
    return bool(stored) and stored.get("prompt_version") == EXTRACTION_PROMPT_VERSION \
        and stored.get("input_hash") == input_hash(job)


def select_jobs(jobs: list[dict], extracted: dict, limit: int) -> tuple[list[dict], dict]:
    """Live jobs with a usable description whose facts are missing or outdated,
    newest first, at most `limit`. Returns (jobs, counts of what was skipped)."""
    skipped = {"expired": 0, "no_description": 0, "up_to_date": 0}
    todo = []
    for job in jobs:
        if job.get("expired_at"):
            skipped["expired"] += 1
        elif len((job.get("description") or "").strip()) < MIN_DESCRIPTION_CHARS:
            skipped["no_description"] += 1
        elif is_current(extracted.get(job["job_id"]), job):
            skipped["up_to_date"] += 1
        else:
            todo.append(job)
    todo.sort(key=lambda j: j.get("scraped_at", ""), reverse=True)
    skipped["over_limit"] = max(len(todo) - max(limit, 0), 0)
    return todo[:max(limit, 0)], skipped


def load_extracted(path: Path = EXTRACTED_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_extracted(data: dict, path: Path = EXTRACTED_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def ollama_ready() -> str | None:
    """None if Ollama answers and has the model, otherwise a message saying what to do."""
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).json()
    except Exception:
        return f"Ollama is not running at {OLLAMA_URL} – start it with `brew services start ollama`"
    names = {m.get("name") for m in tags.get("models", [])}
    if OLLAMA_MODEL not in names and f"{OLLAMA_MODEL}:latest" not in names:
        return f"model {OLLAMA_MODEL} is not pulled – run `ollama pull {OLLAMA_MODEL}`"
    return None


def _print_facts(job: dict, f: dict) -> None:
    print(f"\n— {job.get('title')} @ {job.get('company')}  [{job['job_id']}]")
    print(f"  role={f['role_family']} seniority={f['seniority']} mgmt={f['people_management']} "
          f"mode={f['work_mode']} office_days={f['office_days_per_week']} city={f['city']}")
    print(f"  languages={f['required_languages']} residency={f['residency_required']} "
          f"employment={f['employment']} ai={f['ai_focus']} work={f['work_type']}")
    print(f"  stack={f['stack_required']}  nice={f['stack_nice_to_have']}")
    print(f"  evidence: {f['evidence']}")


def _arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main() -> None:
    jobs = json.loads(RAW_JOBS_PATH.read_text(encoding="utf-8")) if RAW_JOBS_PATH.exists() else []
    extracted = load_extracted()
    by_id = {j["job_id"]: j for j in jobs}

    if "--show" in sys.argv and "--limit" not in sys.argv and "--job-id" not in sys.argv:
        for job_id, f in list(extracted.items())[-int(_arg("--last", 20)):]:
            if job_id in by_id:
                _print_facts(by_id[job_id], f)
        print(f"\n[extract] {len(extracted)} jobs extracted in total")
        return

    if not EXTRACTION_ENABLED:
        print("[extract] extraction is switched off (config.EXTRACTION_ENABLED = False)")
        return
    problem = ollama_ready()
    if problem:
        print(f"[extract] {problem}")
        sys.exit(1)

    if _arg("--job-id"):
        todo = [by_id[_arg("--job-id")]] if _arg("--job-id") in by_id else []
        skipped = {}
    else:
        todo, skipped = select_jobs(jobs, extracted, int(_arg("--limit", MAX_EXTRACTIONS_PER_RUN)))
    print(f"[extract] {len(todo)} jobs to extract with {OLLAMA_MODEL} | skipped {skipped}")

    done = failed = 0
    for i, job in enumerate(todo, 1):
        print(f"[extract] {i}/{len(todo)} {job.get('title', '')[:60]} @ {job.get('company', '')[:30]} ... ",
              end="", flush=True)
        try:
            facts = extract_job(job)
            extracted[job["job_id"]] = facts
            save_extracted(extracted)          # keep progress if the run is interrupted
            done += 1
            print(f"{facts['seconds']}s")
            if "--show" in sys.argv:
                _print_facts(job, facts)
        except Exception as e:
            failed += 1
            print(f"FAILED: {e}")
    print(f"[extract] done. extracted={done} failed={failed} total stored={len(extracted)}")


if __name__ == "__main__":
    main()
