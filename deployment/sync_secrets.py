"""
AIFOD Daily AI News Aggregator - Secret Manager Synchronization Utility.

Purpose:
    Pushes local credentials (.env, token.json, credentials.json) to Google Cloud
    Secret Manager in one shot. Enables seamless multi-PC portability so any workstation
    logged in via 'gcloud auth login' can run the application immediately without local secret files.

Usage:
    python deployment/sync_secrets.py
    python deployment/sync_secrets.py --project YOUR_GCP_PROJECT_ID
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def get_gcp_project(cli_project: str | None = None) -> str:
    """Resolves GCP Project ID from CLI argument, environment, or gcloud CLI."""
    if cli_project:
        return cli_project.strip()

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


def ensure_and_update_secret(secret_id: str, secret_value: str, project_id: str) -> bool:
    """
    Ensures a secret exists in Google Cloud Secret Manager and adds a new version.
    Supports Python SDK with gcloud CLI fallback.
    """
    if not secret_id or not secret_value or not project_id:
        return False

    # Method 1: Google Cloud Secret Manager SDK
    try:
        from google.api_core.client_options import ClientOptions
        from google.api_core.exceptions import NotFound
        from google.cloud import secretmanager

        opts = ClientOptions(quota_project_id=project_id)
        client = secretmanager.SecretManagerServiceClient(client_options=opts)
        parent = f"projects/{project_id}"
        secret_name = f"{parent}/secrets/{secret_id}"

        # Check if secret exists; if not, create it
        try:
            client.get_secret(request={"name": secret_name}, timeout=5.0)
        except NotFound:
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_id,
                    "secret": {"replication": {"automatic": {}}},
                },
                timeout=8.0,
            )
            print(f"  [+] Created secret '{secret_id}' in project '{project_id}'")

        # Add new secret version
        client.add_secret_version(
            request={
                "parent": secret_name,
                "payload": {"data": secret_value.encode("utf-8")},
            },
            timeout=8.0,
        )
        print(f"  [OK] Successfully synced '{secret_id}' via Secret Manager SDK.")
        return True
    except Exception as sdk_err:
        print(f"  [!] SDK sync failed for '{secret_id}' ({sdk_err}). Trying gcloud CLI fallback...")

    # Method 2: gcloud CLI fallback
    try:
        is_win = sys.platform == "win32"
        # Check if secret exists
        describe_cmd = ["gcloud", "secrets", "describe", secret_id, f"--project={project_id}"]
        res = subprocess.run(describe_cmd, capture_output=True, text=True, shell=is_win)
        if res.returncode != 0:
            create_cmd = ["gcloud", "secrets", "create", secret_id, "--replication-policy=automatic", f"--project={project_id}"]
            subprocess.run(create_cmd, capture_output=True, text=True, check=True, timeout=15, shell=is_win)
            print(f"  [+] Created secret '{secret_id}' via gcloud CLI.")

        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
            tf.write(secret_value)
            temp_path = tf.name

        try:
            add_cmd = [
                "gcloud",
                "secrets",
                "versions",
                "add",
                secret_id,
                f"--data-file={temp_path}",
                f"--project={project_id}",
            ]
            subprocess.run(add_cmd, capture_output=True, text=True, check=True, timeout=15, shell=is_win)
            print(f"  [OK] Successfully synced '{secret_id}' via gcloud CLI.")
            return True
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except Exception as cli_err:
        print(f"  [ERROR] Failed to sync '{secret_id}': {cli_err}")

    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync local secrets to Google Cloud Secret Manager")
    parser.add_argument("--project", type=str, default=None, help="Google Cloud Project ID")
    args = parser.parse_args()

    project_id = get_gcp_project(args.project)
    if not project_id:
        print("[ERROR] GCP Project ID could not be determined. Pass --project <ID> or set GCP_PROJECT_ID.")
        sys.exit(1)

    print("===========================================================================")
    print(f" Syncing Local Credentials to Secret Manager (Project: {project_id})")
    print("===========================================================================")

    workspace_root = Path(__file__).resolve().parent.parent

    # 1. Parse .env if present
    env_file = workspace_root / ".env"
    env_vars: dict[str, str] = {}
    if env_file.exists():
        print(f"Found local .env at: {env_file}")
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    env_vars[key.strip()] = val.strip()

    # 2. Sync Gemini API Key
    gemini_key = env_vars.get("GEMINI_API_KEY") or env_vars.get("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        print("\n-> Syncing Gemini API Key...")
        ensure_and_update_secret("gemini-api-key", gemini_key, project_id)
    else:
        print("\n-> Gemini API Key not found in local .env or environment (skipping).")

    # 3. Sync Recipient Email if configured
    recipient_email = env_vars.get("RECIPIENT_EMAIL") or os.getenv("RECIPIENT_EMAIL")
    if recipient_email:
        print("\n-> Syncing Recipient Email...")
        ensure_and_update_secret("ai-news-recipient-email", recipient_email, project_id)

    # 4. Sync OAuth Client Credentials (credentials.json)
    creds_file = workspace_root / "credentials.json"
    if creds_file.exists():
        print("\n-> Syncing OAuth Client Credentials (credentials.json)...")
        with open(creds_file, "r", encoding="utf-8") as f:
            creds_data = f.read().strip()
        ensure_and_update_secret("gmail-oauth-credentials", creds_data, project_id)
    else:
        print("\n-> credentials.json not found locally (skipping).")

    # 5. Sync Gmail OAuth Token (token.json or temp cache)
    token_file = workspace_root / "token.json"
    temp_cache_file = Path(tempfile.gettempdir()) / "ai_news_gmail_token_cache.json"

    token_data: str | None = None
    if token_file.exists():
        print("\n-> Syncing Gmail OAuth Token (token.json)...")
        with open(token_file, "r", encoding="utf-8") as f:
            token_data = f.read().strip()
    elif temp_cache_file.exists():
        print(f"\n-> Syncing Gmail OAuth Token from temp cache ({temp_cache_file})...")
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            token_data = f.read().strip()

    if token_data:
        ensure_and_update_secret("gmail-agent-token", token_data, project_id)
    else:
        print("\n-> token.json not found locally (skipping).")

    print("\n===========================================================================")
    print(" Secret Synchronization Complete!")
    print(" You may now safely delete local secret files (.env, credentials.json, token.json).")
    print("===========================================================================")


if __name__ == "__main__":
    main()
