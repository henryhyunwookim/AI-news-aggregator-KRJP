"""
AIFOD Daily AI News Aggregator - State Memory & Operational Logging Module.

Purpose:
    Provides cloud-native persistent state management and execution audit logging
    backed by Google Cloud Storage (GCS) with dual-mode fallback (Python SDK + gcloud CLI)
    and safe OS temporary directory fallbacks.

Key Principles:
    1. Single Source of Truth: State is persisted in GCS:
       `gs://<bucket>/<service-name>/state.json`
    2. Zero Workspace Pollution: Offline/local fallbacks write strictly to the OS temp
       directory (`tempfile.gettempdir()`), never touching the workspace git root.
    3. Decoupled Execution Logs: Operational run metrics, error traces, and execution
       summaries are recorded separately in `gs://<bucket>/<service-name>/run_log.json`
       and emitted as structured JSON logs to stdout for Cloud Logging.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

from src.config import (
    GCP_PROJECT_ID,
    GCP_REGION,
    GCS_BUCKET_NAME,
    GCS_LOG_BLOB,
    GCS_STATE_BLOB,
    SERVICE_NAME,
)

# Local cache paths in OS temporary directory to guarantee zero workspace pollution
LOCAL_STATE_CACHE: str = os.path.join(tempfile.gettempdir(), f"{SERVICE_NAME}_state_cache.json")
LOCAL_LOG_CACHE: str = os.path.join(tempfile.gettempdir(), f"{SERVICE_NAME}_run_log_cache.json")


# ===========================================================================
# 1. Bucket Verification & Creation Helper
# ===========================================================================

def ensure_gcs_bucket_exists(bucket_name: str = GCS_BUCKET_NAME, region: str = GCP_REGION) -> bool:
    """
    Checks if the GCS bucket exists. If not, attempts to create it automatically.
    """
    if not bucket_name:
        return False

    is_cloud = os.getenv("K_SERVICE") is not None

    # On Cloud Run, use SDK
    if is_cloud:
        try:
            from google.cloud import storage

            client = storage.Client(project=GCP_PROJECT_ID) if GCP_PROJECT_ID else storage.Client()
            bucket = client.bucket(bucket_name)
            if bucket.exists():
                return True
            client.create_bucket(bucket, location=region)
            print(f"[Memory] Created GCS bucket: gs://{bucket_name} in {region}")
            return True
        except Exception:
            pass

    # On local workstation, use gcloud CLI
    try:
        is_win = sys.platform == "win32"
        check_cmd = ["gcloud", "storage", "buckets", "describe", f"gs://{bucket_name}"]
        res = subprocess.run(check_cmd, capture_output=True, text=True, timeout=8, shell=is_win)
        if res.returncode == 0:
            return True

        create_cmd = ["gcloud", "storage", "buckets", "create", f"gs://{bucket_name}", f"--location={region}"]
        res_create = subprocess.run(create_cmd, capture_output=True, text=True, check=True, timeout=20, shell=is_win)
        print(f"[Memory] Created GCS bucket via CLI: gs://{bucket_name}")
        return True
    except Exception:
        pass

    # Fallback to SDK for non-CloudRun if CLI was absent
    if not is_cloud:
        try:
            from google.cloud import storage

            client = storage.Client(project=GCP_PROJECT_ID) if GCP_PROJECT_ID else storage.Client()
            bucket = client.bucket(bucket_name)
            if bucket.exists():
                return True
            client.create_bucket(bucket, location=region)
            return True
        except Exception:
            pass

    return False


# ===========================================================================
# 2. State & Memory Persistence (Cloud Storage)
# ===========================================================================

def load_cloud_state() -> dict[str, Any]:
    """
    Loads persistent state from Google Cloud Storage.
    On Cloud Run: SDK -> CLI -> Temp Cache -> Default
    On Local: CLI -> SDK -> Temp Cache -> Default
    """
    is_cloud = os.getenv("K_SERVICE") is not None

    if is_cloud:
        try:
            from google.cloud import storage

            client = storage.Client(project=GCP_PROJECT_ID) if GCP_PROJECT_ID else storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(GCS_STATE_BLOB)
            if blob.exists():
                content = blob.download_as_text(encoding="utf-8")
                state_data = json.loads(content)
                try:
                    with open(LOCAL_STATE_CACHE, "w", encoding="utf-8") as f:
                        f.write(content)
                except Exception:
                    pass
                return state_data
        except Exception:
            pass

    # Local CLI
    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "cat", f"gs://{GCS_BUCKET_NAME}/{GCS_STATE_BLOB}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=is_win)
        if res.returncode == 0:
            state_data = json.loads(res.stdout)
            try:
                with open(LOCAL_STATE_CACHE, "w", encoding="utf-8") as f:
                    f.write(res.stdout)
            except Exception:
                pass
            return state_data
    except Exception:
        pass

    # Secondary SDK fallback for non-CloudRun
    if not is_cloud:
        try:
            from google.cloud import storage

            client = storage.Client(project=GCP_PROJECT_ID) if GCP_PROJECT_ID else storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(GCS_STATE_BLOB)
            if blob.exists():
                content = blob.download_as_text(encoding="utf-8")
                return json.loads(content)
        except Exception:
            pass

    # Local OS temp cache
    if os.path.exists(LOCAL_STATE_CACHE):
        try:
            with open(LOCAL_STATE_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {
        "service": SERVICE_NAME,
        "last_updated": None,
        "sent_article_urls": [],
        "total_dispatched_articles": 0,
        "run_count": 0,
    }


def save_cloud_state(data: dict[str, Any]) -> bool:
    """
    Persists application state directly to GCS and OS temp cache.
    """
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    data_str = json.dumps(data, ensure_ascii=False, indent=2)

    # Always persist to safe local temp cache first
    try:
        with open(LOCAL_STATE_CACHE, "w", encoding="utf-8") as f:
            f.write(data_str)
    except Exception as cache_err:
        print(f"[Memory] Warning: Could not write to temp cache: {cache_err}")

    # Ensure bucket exists
    ensure_gcs_bucket_exists()

    is_cloud = os.getenv("K_SERVICE") is not None

    if is_cloud:
        try:
            from google.cloud import storage

            client = storage.Client(project=GCP_PROJECT_ID) if GCP_PROJECT_ID else storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(GCS_STATE_BLOB)
            blob.upload_from_string(data_str, content_type="application/json")
            return True
        except Exception:
            pass

    # Local CLI
    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "cp", LOCAL_STATE_CACHE, f"gs://{GCS_BUCKET_NAME}/{GCS_STATE_BLOB}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=12, shell=is_win)
        if res.returncode == 0:
            return True
    except Exception:
        pass

    # Secondary SDK fallback
    if not is_cloud:
        try:
            from google.cloud import storage

            client = storage.Client(project=GCP_PROJECT_ID) if GCP_PROJECT_ID else storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(GCS_STATE_BLOB)
            blob.upload_from_string(data_str, content_type="application/json")
            return True
        except Exception:
            pass

    return False


# ===========================================================================
# 3. Decoupled Operational & Execution Logs
# ===========================================================================

def load_run_logs(max_entries: int = 100) -> list[dict[str, Any]]:
    """
    Loads execution run log entries from GCS or temp cache.
    """
    is_cloud = os.getenv("K_SERVICE") is not None

    if is_cloud:
        try:
            from google.cloud import storage

            client = storage.Client(project=GCP_PROJECT_ID) if GCP_PROJECT_ID else storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(GCS_LOG_BLOB)
            if blob.exists():
                content = blob.download_as_text(encoding="utf-8")
                logs = json.loads(content)
                if isinstance(logs, list):
                    return logs[-max_entries:]
        except Exception:
            pass

    # Local CLI
    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "cat", f"gs://{GCS_BUCKET_NAME}/{GCS_LOG_BLOB}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=is_win)
        if res.returncode == 0:
            logs = json.loads(res.stdout)
            if isinstance(logs, list):
                return logs[-max_entries:]
    except Exception:
        pass

    if os.path.exists(LOCAL_LOG_CACHE):
        try:
            with open(LOCAL_LOG_CACHE, "r", encoding="utf-8") as f:
                logs = json.load(f)
                if isinstance(logs, list):
                    return logs[-max_entries:]
        except Exception:
            pass

    return []



def append_run_log(log_entry: dict[str, Any], max_history: int = 100) -> bool:
    """
    Appends an operational execution summary to GCS run_log.json
    and prints a structured log JSON to stdout (streamed to Cloud Logging).

    Args:
        log_entry: Dictionary containing run timestamp, status, stats, and errors.
        max_history: Maximum number of recent log entries to retain in GCS.
    """
    if "timestamp" not in log_entry:
        log_entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    if "service" not in log_entry:
        log_entry["service"] = SERVICE_NAME

    # Emit structured JSON log to stdout for Google Cloud Logging ingestion
    try:
        structured_log = {
            "severity": "ERROR" if log_entry.get("error") else "INFO",
            "message": f"Execution finished: {log_entry.get('status', 'unknown')} (Relevant: {log_entry.get('stats', {}).get('relevant_count', 0)})",
            "execution": log_entry,
        }
        print(f"[CloudLogging] {json.dumps(structured_log, ensure_ascii=False)}")
    except Exception:
        pass

    # Read previous entries, append, and prune
    existing_logs = load_run_logs(max_entries=max_history)
    existing_logs.append(log_entry)
    trimmed_logs = existing_logs[-max_history:]

    logs_str = json.dumps(trimmed_logs, ensure_ascii=False, indent=2)

    # Save to temp log cache
    try:
        with open(LOCAL_LOG_CACHE, "w", encoding="utf-8") as f:
            f.write(logs_str)
    except Exception:
        pass

    # Ensure bucket exists
    ensure_gcs_bucket_exists()

    is_cloud = os.getenv("K_SERVICE") is not None

    # Environment 1: Cloud Run (IAM service account)
    if is_cloud:
        try:
            from google.cloud import storage

            client = storage.Client(project=GCP_PROJECT_ID) if GCP_PROJECT_ID else storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(GCS_LOG_BLOB)
            blob.upload_from_string(logs_str, content_type="application/json")
            return True
        except Exception:
            pass

    # Environment 2: Local workstation CLI
    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "cp", LOCAL_LOG_CACHE, f"gs://{GCS_BUCKET_NAME}/{GCS_LOG_BLOB}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=12, shell=is_win)
        if res.returncode == 0:
            return True
    except Exception:
        pass

    # Secondary SDK fallback
    if not is_cloud:
        try:
            from google.cloud import storage

            client = storage.Client(project=GCP_PROJECT_ID) if GCP_PROJECT_ID else storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(GCS_LOG_BLOB)
            blob.upload_from_string(logs_str, content_type="application/json")
            return True
        except Exception:
            pass

    return False
