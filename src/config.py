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
    - GEMINI_MODEL: Gemini model name (default: gemini-3.8-flash)
    - STAGE1_CANDIDATES_PER_COUNTRY: Target candidate count per country in Stage 1 (default: 10)
    - RECIPIENT_EMAIL: Target email address for daily digest delivery
    - RECIPIENT_NAME: Target recipient name for report personalization (default: AIFOD Practitioner)
    - TIMEZONE: Timezone identifier for scheduling and report dates (default: Asia/Tokyo)
"""

from __future__ import annotations

import os
import subprocess
import sys
from dotenv import load_dotenv

# Load local environment variables from .env file if present in workspace root (optional local override)
load_dotenv()


# ===========================================================================
# 1. Dual-Mode Cloud Secret Resolution Helper
# ===========================================================================

def get_default_gcp_project() -> str:
    """Attempts to resolve the active GCP Project ID from env or gcloud CLI."""
    proj = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if proj:
        return proj.strip()
    try:
        is_win = sys.platform == "win32"
        res = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            check=True,
            timeout=8,
            shell=is_win,
        )
        val = res.stdout.strip()
        if val and "(unset)" not in val:
            return val
    except Exception:
        pass
    return ""


def resolve_cloud_secret(secret_id: str, project_id: str | None = None) -> str | None:
    """
    Resolves a secret from GCP Secret Manager via Python SDK or gcloud CLI.
    - Cloud Run (`K_SERVICE` set): Uses Secret Manager Python SDK with container IAM credentials.
    - Local Workstation: Uses `gcloud secrets versions access` CLI (authenticated via `gcloud auth login`),
      preventing hangs or auth failures from expired local ADC.
    """
    if not secret_id:
        return None

    proj = project_id or get_default_gcp_project()
    if not proj:
        return None

    is_cloud = os.getenv("K_SERVICE") is not None

    # Environment 1: Cloud Run (IAM service account)
    if is_cloud:
        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{proj}/secrets/{secret_id}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            secret_val = response.payload.data.decode("utf-8").strip()
            if secret_val:
                return secret_val
        except Exception:
            pass
        return None

    # Environment 2: Local workstation authenticated via gcloud CLI
    try:
        is_win = sys.platform == "win32"
        cmd = [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={secret_id}",
            f"--project={proj}",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=12, shell=is_win)
        if res.returncode == 0:
            secret_val = res.stdout.strip()
            if secret_val:
                return secret_val
        # If gcloud ran and secret was not found or error occurred, return None
        return None
    except Exception:
        pass

    return None


def save_cloud_secret(secret_id: str, payload: str, project_id: str | None = None) -> bool:
    """
    Updates or adds a new version to a secret in GCP Secret Manager.
    Dual-mode: uses Secret Manager SDK on Cloud Run and gcloud CLI on local workstations.
    """
    if not secret_id or not payload:
        return False

    proj = project_id or get_default_gcp_project()
    if not proj:
        return False

    is_cloud = os.getenv("K_SERVICE") is not None

    # Environment 1: Cloud Run (IAM service account)
    if is_cloud:
        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            parent = f"projects/{proj}/secrets/{secret_id}"
            client.add_secret_version(
                request={"parent": parent, "payload": {"data": payload.encode("utf-8")}}
            )
            return True
        except Exception:
            return False

    # Environment 2: Local workstation authenticated via gcloud CLI
    try:
        import tempfile

        is_win = sys.platform == "win32"
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
            tf.write(payload)
            temp_path = tf.name

        try:
            cmd = [
                "gcloud",
                "secrets",
                "versions",
                "add",
                secret_id,
                f"--data-file={temp_path}",
                f"--project={proj}",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15, shell=is_win)
            return res.returncode == 0
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except Exception:
        pass

    return False




# ===========================================================================
# 2. Google Cloud Platform & Serverless Configuration
# ===========================================================================
GCP_PROJECT_ID: str = get_default_gcp_project()
GCP_REGION: str = os.getenv("GCP_REGION", "us-central1")
SERVICE_NAME: str = os.getenv("SERVICE_NAME", "ai-news-aggregator-krjp")
JOB_NAME: str = os.getenv("JOB_NAME", "ai-news-aggregator-daily-trigger")

# Secret Manager Resource Identifiers
SECRET_GEMINI_API_KEY: str = os.getenv("SECRET_GEMINI_API_KEY", "gemini-api-key")
SECRET_GMAIL_TOKEN: str = os.getenv("SECRET_GMAIL_TOKEN", "gmail-agent-token")
SECRET_GMAIL_CREDENTIALS: str = os.getenv("SECRET_GMAIL_CREDENTIALS", "gmail-oauth-credentials")
SECRET_RECIPIENT_EMAIL: str = os.getenv("SECRET_RECIPIENT_EMAIL", "ai-news-recipient-email")

# Cloud Storage Persistence
GCS_BUCKET_NAME: str = os.getenv(
    "GCS_BUCKET_NAME",
    f"{GCP_PROJECT_ID}-ai-news-data" if GCP_PROJECT_ID else "ai-news-aggregator-data"
)
GCS_STATE_BLOB: str = os.getenv("GCS_STATE_BLOB", f"{SERVICE_NAME}/state.json")
GCS_LOG_BLOB: str = os.getenv("GCS_LOG_BLOB", f"{SERVICE_NAME}/run_log.json")

# ===========================================================================
# 3. Large Language Model (Gemini) Configurations
# ===========================================================================
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_API_KEY: str | None = (
    os.getenv("GEMINI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
    or resolve_cloud_secret(SECRET_GEMINI_API_KEY, GCP_PROJECT_ID)
)
# Number of candidates selected per country in Stage 1 candidate filtering (default: 10 KR + 10 JP = 20 total)
STAGE1_CANDIDATES_PER_COUNTRY: int = int(os.getenv("STAGE1_CANDIDATES_PER_COUNTRY", "10"))

# ===========================================================================
# 4. Email Delivery & OAuth Scopes
# ===========================================================================
RECIPIENT_EMAIL: str = (
    os.getenv("RECIPIENT_EMAIL")
    or resolve_cloud_secret(SECRET_RECIPIENT_EMAIL, GCP_PROJECT_ID)
    or ""
)
RECIPIENT_NAME: str = os.getenv("RECIPIENT_NAME", "AIFOD Practitioner")

# Gmail Scopes:
# - gmail.readonly: Verify authenticated user profile and identity
# - gmail.send: Transmit formatted MIME digest messages via Google Gmail API
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send"
]

# ===========================================================================
# 5. Scheduling & Localization
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
