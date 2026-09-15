"""
AIFOD Daily AI News Aggregator - Configuration Module.

Purpose:
    Centralizes all application environment variables, GCP infrastructure settings,
    Gemini API configurations, Gmail OAuth scopes, and multilingual search query matrices.

Environment Variables:
    - GCP_PROJECT_ID: Google Cloud Platform Project ID
    - GCP_REGION: Cloud Run and Scheduler region (default: us-central1)
    - SERVICE_NAME: Cloud Run service name (default: ai-news-aggregator-krjp)
    - JOB_NAME: Cloud Scheduler job name (default: ai-news-aggregator-daily-trigger)
    - GEMINI_API_KEY / GOOGLE_API_KEY: Authentication key for Google Gemini Generative AI
    - RECIPIENT_EMAIL: Target email address for daily digest delivery
    - RECIPIENT_NAME: Target recipient name for report personalization (default: AIFOD Practitioner)
    - TIMEZONE: Timezone identifier for scheduling and report dates (default: Asia/Tokyo)
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

# Load local environment variables from .env file if present in workspace root
load_dotenv()

# ===========================================================================
# 1. Google Cloud Platform & Serverless Configuration
# ===========================================================================
GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")
GCP_REGION: str = os.getenv("GCP_REGION", "us-central1")
SERVICE_NAME: str = os.getenv("SERVICE_NAME", "ai-news-aggregator-krjp")
JOB_NAME: str = os.getenv("JOB_NAME", "ai-news-aggregator-daily-trigger")

# ===========================================================================
# 2. Large Language Model (Gemini) API Key
# ===========================================================================
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

# ===========================================================================
# 3. Email Delivery & OAuth Scopes
# ===========================================================================
RECIPIENT_EMAIL: str = os.getenv("RECIPIENT_EMAIL", "")
RECIPIENT_NAME: str = os.getenv("RECIPIENT_NAME", "AIFOD Practitioner")

# Gmail Scopes:
# - gmail.readonly: Verify authenticated user profile and identity
# - gmail.send: Transmit formatted MIME digest messages via Google Gmail API
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send"
]

# ===========================================================================
# 4. Scheduling & Localization
# ===========================================================================
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Tokyo")

# ===========================================================================
# 5. Multilingual News RSS Search Query Matrix
# ===========================================================================
# Korean queries targeting AI capacity building, ODA, international cooperation,
# digital divide, policy, and social inclusion.
KOREAN_QUERIES: list[str] = [
    "AI 개발도상국",
    "인공지능 개발도상국",
    "AI 국제협력",
    "인공지능 국제협력",
    "AI ODA",
    "AI 정보격차",
    "인공지능 정보격차",
    "AI 인재양성",
    "인공지능 정책",
    "AI 윤리",
    "인공지능 윤리",
    "AI 규제",
    "인공지능 규제",
    "AI 교육",
    "인공지능 교육",
    "디지털 ODA",
    "디지털 포용",
    "AI 포용"
]

# Japanese queries targeting AI in developing nations, ODA (JICA), digital divide,
# human resource development, policy governance, and social inclusion.
JAPANESE_QUERIES: list[str] = [
    "AI 途上国",
    "人工知能 途上国",
    "AI 国際協力",
    "人工知能 国際協力",
    "AI ODA",
    "AI デジタル格差",
    "人工知能 デジタル格差",
    "AI 人材育成",
    "人工知能 政策",
    "AI 倫理",
    "人工知能 倫理",
    "AI 規制",
    "人工知能 規制",
    "AI 教育",
    "人工知能 教育",
    "デジタル ODA",
    "デジタル包摂",
    "AI 包摂"
]
