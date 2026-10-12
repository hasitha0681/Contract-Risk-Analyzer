"""Central settings for the AtliQ Contract Risk Analyzer.

Every path, model name and tunable lives here (PRD section 13). Secrets come
from `.env` locally, or from Streamlit secrets when deployed.
"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
# The dataset folder ships as "Data"; the PRD asks us not to rename anything.
DATA_DIR = BASE_DIR / "Data"
INCOMING_DIR = DATA_DIR / "incoming"
TEST_CONTRACTS_DIR = DATA_DIR / "test_contracts"
SIGNED_DIR = DATA_DIR / "signed_contracts"
MEETING_NOTES_DIR = DATA_DIR / "meeting_notes"
NEGOTIATION_NOTES = DATA_DIR / "negotiation_notes.md"
PRINCIPLES_FILE = DATA_DIR / "principles.md"
ENTITIES_FILE = DATA_DIR / "atliq_entities.md"
TRACKER_CSV = DATA_DIR / "contract_tracker.csv"
COMMITMENTS_FILE = DATA_DIR / "commitments.json"

CHROMA_DIR = BASE_DIR / "chroma_db"
LOG_DIR = BASE_DIR / "logs"
AUDIT_LOG = LOG_DIR / "audit.jsonl"
DECISIONS_CSV = LOG_DIR / "decisions.csv"

# --- Review date -------------------------------------------------------------
# The dataset README fixes "today" as 2026-09-28. Commitment end dates are
# compared against this, not the machine clock, so the demo is reproducible.
TODAY = date(2026, 9, 28)

# --- LLM ---------------------------------------------------------------------
def _secret(name: str) -> str | None:
    """Read from the environment, falling back to Streamlit Cloud secrets."""
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st

        return st.secrets.get(name)  # type: ignore[no-any-return]
    except Exception:
        return None


GROQ_API_KEY = _secret("GROQ_API_KEY")
# The PRD names Qwen3.6-27B; Groq has retired it, and qwen3.8-27b is its
# direct successor. Override with GROQ_MODEL in .env if needed.
LLM_MODEL = _secret("GROQ_MODEL") or "qwen/qwen3.8-27b"
LLM_TEMPERATURE = 0
LLM_REASONING_EFFORT = "none"

# Groq's free tier allows 8,000 tokens per minute (input + reserved output).
# llm.py paces calls against this budget instead of tripping 429 errors.
TOKENS_PER_MINUTE = 8000
TOKEN_BUDGET_SAFETY = 0.9

MAX_TOKENS_BASICS = 900
MAX_TOKENS_REVIEW = 1600
MAX_TOKENS_EXPLAIN = 700
MAX_TOKENS_QA = 600
MAX_TOKENS_REGISTER = 900

# Contract text sent to the clause review per call. ~9,000 characters is
# ~2,600 tokens, leaving room for the principles and the JSON answer.
REVIEW_CHUNK_CHARS = 9000
BASICS_FULL_TEXT_CHARS = 16000

# --- Retrieval ---------------------------------------------------------------
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_SIZE = 600
CHUNK_OVERLAP = 100
TOP_K = 5

COLLECTION_SIGNED = "signed_contracts"
COLLECTION_HISTORY = "negotiation_history"
COLLECTION_PRINCIPLES = "principles"
COLLECTION_COMMITMENTS = "commitments"
COLLECTIONS = [
    COLLECTION_SIGNED,
    COLLECTION_HISTORY,
    COLLECTION_PRINCIPLES,
    COLLECTION_COMMITMENTS,
]

# --- Business rules (run in code, never by the LLM) -------------------------
PROPORTION_THRESHOLD = 2.0   # liability cap > 2x contract value -> High
LONG_NON_SOLICIT_MONTHS = 12  # NDA non-solicit longer than this -> one-sided

ENTITY_US = "AtliQ Inc"
ENTITY_ROW = "AtliQ Technologies Pvt Ltd"

QA_HISTORY_EXCHANGES = 5

# --- Controlled vocabularies -------------------------------------------------
# The LLM tags a contract from these lists; code compares tags with the
# register. A fixed vocabulary is what makes commitment matching a
# deterministic set comparison rather than a fuzzy judgement.
INDUSTRY_TAGS = {
    "hospitality": "hotels, resorts, serviced apartments, or any business that ranks, distributes or sells hotel stays",
    "travel": "travel agencies, trip planning, airlines, booking apps",
    "retail": "retail stores and e-commerce",
    "grocery": "grocery and supermarkets",
    "food": "food production and restaurants",
    "healthcare": "hospitals, clinics, health systems, patient data",
    "pharma": "pharmaceuticals and life sciences",
    "financial_services": "banks, NBFCs, lenders, payments, fintech, capital markets",
    "insurance": "insurers and insurance brokers",
    "logistics": "logistics, shipping, warehousing, fleet",
    "cloud_data_platform": "the counterparty itself sells a cloud data warehouse, lakehouse or unified analytics platform as a service (not a customer that merely uses one)",
    "manufacturing": "manufacturing and industrial",
    "technology": "software and IT companies not covered above",
    "other": "anything else",
}

SERVICE_TAGS = {
    "data_analytics": "analytics, dashboards, insights, sentiment or guest analytics",
    "artificial_intelligence": "AI, machine learning, predictive or recommendation models",
    "revenue_management": "pricing, yield or revenue-management systems",
    "data_engineering": "data pipelines, ingestion, data platforms, warehouse or lakehouse builds and migrations",
    "business_intelligence": "BI reporting and dashboard development (Power BI, Tableau)",
    "software_development": "application or product development",
    "platform_partnership": "AtliQ acts as an implementation, reseller or referral partner for a software platform",
    "staff_augmentation": "placing individual engineers with a client",
    "design": "UX, UI or graphic design",
    "consulting": "advisory work",
    "confidentiality_only": "an NDA with no services",
    "other": "anything else",
}

GCC = ["UAE", "Saudi Arabia", "Qatar", "Kuwait", "Bahrain", "Oman"]
EU = ["Germany", "France", "Netherlands", "Ireland", "Spain", "Italy", "Belgium",
      "Sweden", "Denmark", "Austria", "Poland", "Finland", "Portugal"]

# Place names -> canonical country. Used to normalise LLM output and to scan
# contract text for where the work actually happens.
REGION_ALIASES = {
    "uae": "UAE", "united arab emirates": "UAE", "dubai": "UAE", "abu dhabi": "UAE",
    "sharjah": "UAE", "ras al khaimah": "UAE",
    "saudi arabia": "Saudi Arabia", "kingdom of saudi arabia": "Saudi Arabia", "ksa": "Saudi Arabia",
    "saudi": "Saudi Arabia", "riyadh": "Saudi Arabia", "jeddah": "Saudi Arabia", "dammam": "Saudi Arabia",
    "qatar": "Qatar", "doha": "Qatar",
    "kuwait": "Kuwait",
    "bahrain": "Bahrain", "manama": "Bahrain",
    "oman": "Oman", "muscat": "Oman", "sultanate of oman": "Oman",
    "india": "India", "mumbai": "India", "bengaluru": "India", "bangalore": "India",
    "delhi": "India", "hyderabad": "India", "chennai": "India",
    "usa": "USA", "united states": "USA", "us": "USA", "u.s.": "USA", "u.s.a.": "USA",
    "united kingdom": "UK", "uk": "UK", "england": "UK", "london": "UK",
    "germany": "Germany", "munich": "Germany", "berlin": "Germany",
    "singapore": "Singapore",
}
REGION_GROUPS = {
    "gcc": GCC,
    "gulf cooperation council": GCC,
    "middle east": GCC,
    "europe": EU + ["UK"],
    "eu": EU,
    "european union": EU,
}

# Words that tie a contract to the hospitality industry. Applied in code on
# top of the LLM's tags so that, for example, an app ranking "Partner Hotels"
# is never missed.
HOSPITALITY_WORDS = ["hotel", "hotels", "resort", "resorts", "serviced apartment", "hospitality"]

# Rate-card role names -> the canonical role used by the MFN check.
ROLE_PATTERNS = [
    (r"\b(senior|sr\.?|lead)\s+data\s+engineer", "senior data engineer"),
    (r"\bdata\s+engineer", "data engineer"),
    (r"\b(power\s+)?bi\s+developer|business\s+intelligence\s+developer", "bi developer"),
]
