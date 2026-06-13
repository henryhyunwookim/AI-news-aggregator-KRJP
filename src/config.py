import os
from dotenv import load_dotenv

# Load env variables from .env if present
load_dotenv()

# Google Cloud Platform Configuration
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "gen-lang-client-0480639565")
GCP_REGION = os.getenv("GCP_REGION", "us-central1")
SERVICE_NAME = os.getenv("SERVICE_NAME", "ai-news-aggregator-krjp")
JOB_NAME = os.getenv("JOB_NAME", "ai-news-aggregator-daily-trigger")

# Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Email Settings
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "henry.hyunwookim@gmail.com")

# Gmail Scopes (Readonly for reading profile, Send for sending summary, Modify for labeling if needed)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send'
]

# Timezone settings for logging/scheduler
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tokyo")

# Google News RSS Search Queries
# Focused on AI development, international cooperation, policy, capacity building, digital divide, ODA, etc.
KOREAN_QUERIES = [
    "AI 개발도상국",
    "인공지능 개발도상국",
    "AI 국제협력",
    "인공지능 국제협력",
    "AI ODA",
    "AI 정보격차",
    "인공지능 정보격차",
    "AI 인재양성",
    "인공지능 정책"
]

JAPANESE_QUERIES = [
    "AI 途上国",
    "人工知能 途上国",
    "AI 国際協力",
    "人工知能 国際協力",
    "AI ODA",
    "AI デジタル格差",
    "人工知能 デジタル格差",
    "AI 人材育成",
    "人工知能 政策"
]
