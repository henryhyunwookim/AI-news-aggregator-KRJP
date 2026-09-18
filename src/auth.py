"""
AIFOD Daily AI News Aggregator - Authentication Module.

Purpose:
    Manages OAuth 2.0 user credentials for the Google Gmail API. Handles automated
    token refreshes using stored refresh tokens and provides an interactive browser flow
    for initial workstation onboarding.

Security & Environment Flow:
    - Interactive Environments (Local CLI):
        Launches an ephemeral local HTTP server to capture user authorization codes
        and writes 'token.json' with valid access and refresh tokens.
    - Cloud Environments (Google Cloud Run / headless container):
        Validates existing credentials and refreshes access tokens silently. If the
        refresh token is missing or permanently revoked, raises a descriptive
        RuntimeError instead of attempting an impossible headless browser launch.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from src.config import (
    GCP_PROJECT_ID,
    SCOPES,
    SECRET_GMAIL_CREDENTIALS,
    SECRET_GMAIL_TOKEN,
    resolve_cloud_secret,
    save_cloud_secret,
)

# Cache path in OS temporary directory to guarantee zero workspace pollution
LOCAL_TOKEN_CACHE: str = os.path.join(tempfile.gettempdir(), "ai_news_gmail_token_cache.json")


# ===========================================================================
# Gmail OAuth 2.0 Authentication Helper
# ===========================================================================

def authenticate_gmail() -> Credentials:
    """
    Authenticates with the Google Gmail API using Secret Manager or local cache.

    Lifecycle:
        1. Checks for serialized token in Secret Manager, OS temp cache, or local token.json.
        2. If credentials exist but are expired, automatically refreshes them via Request().
        3. Persists refreshed tokens back to Secret Manager and OS temp cache.
        4. If credentials are missing or revoked:
           - In headless/cloud environments, raises a descriptive RuntimeError.
           - In interactive environments, auto-downloads OAuth client config from Secret Manager
             (or local credentials.json) and launches the authorization flow.
        5. Saves resulting credentials to Secret Manager and OS temp cache.

    Returns:
        google.oauth2.credentials.Credentials: Valid authenticated Gmail credentials object.

    Raises:
        FileNotFoundError: If OAuth client configuration cannot be found in Secret Manager or disk.
        RuntimeError: If running in a cloud/headless environment with invalid or expired credentials.
    """
    creds: Credentials | None = None
    token_source: str = ""

    # Step 1: Attempt to load credentials from (a) Secret Manager, (b) temp cache, (c) local token.json
    # Check 1a: Google Cloud Secret Manager
    cloud_token_str = resolve_cloud_secret(SECRET_GMAIL_TOKEN, GCP_PROJECT_ID)
    if cloud_token_str:
        try:
            token_info = json.loads(cloud_token_str)
            creds = Credentials.from_authorized_user_info(token_info, SCOPES)
            token_source = "Google Cloud Secret Manager"
            print(f"[Auth] Successfully loaded Gmail credentials from Secret Manager ({SECRET_GMAIL_TOKEN}).")
        except Exception as sm_err:
            print(f"[Auth] Warning: Could not parse token from Secret Manager: {sm_err}")
            creds = None

    # Check 1b: OS temp cache
    if not creds and os.path.exists(LOCAL_TOKEN_CACHE):
        try:
            creds = Credentials.from_authorized_user_file(LOCAL_TOKEN_CACHE, SCOPES)
            token_source = f"temp cache ({LOCAL_TOKEN_CACHE})"
            print(f"[Auth] Loaded Gmail credentials from {token_source}.")
        except Exception as cache_err:
            print(f"[Auth] Warning: Could not parse temp cache token: {cache_err}")
            creds = None

    # Check 1c: Local token.json in workspace (legacy fallback)
    if not creds and os.path.exists("token.json"):
        try:
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
            token_source = "local workspace token.json"
            print(f"[Auth] Loaded Gmail credentials from {token_source}.")
        except Exception as local_err:
            print(f"[Auth] Warning: Could not parse workspace token.json: {local_err}")
            creds = None

    # Step 2: Validate credentials and perform automated token refresh
    token_refreshed: bool = False
    if creds and not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                print("[Auth] Access token expired. Attempting automatic refresh via Google Auth...")
                creds.refresh(Request())
                token_refreshed = True
                print("[Auth] Access token refreshed successfully.")
            except Exception as ref_err:
                print(f"[Auth] Automated refresh failed: {ref_err}")
                creds = None

    # Step 3: Handle initial authorization when credentials remain unavailable
    if not creds:
        is_cloud: bool = os.getenv("K_SERVICE") is not None
        is_interactive: bool = bool(sys.stdin and sys.stdin.isatty())

        if is_cloud or not is_interactive:
            raise RuntimeError(
                f"GMAIL AUTHENTICATION ERROR: Secret '{SECRET_GMAIL_TOKEN}' is missing, invalid, or expired "
                "and cannot be refreshed automatically in a non-interactive/cloud environment. Please run "
                "the interactive authorization workflow locally (e.g., 'python -m src.main --auth') or run "
                "'python deployment/sync_secrets.py' to upload credentials to Google Cloud Secret Manager."
            )

        print("[Auth] Resolving OAuth client credentials for interactive setup...")
        client_config_str = resolve_cloud_secret(SECRET_GMAIL_CREDENTIALS, GCP_PROJECT_ID)

        flow: InstalledAppFlow
        if client_config_str:
            try:
                client_config = json.loads(client_config_str)
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
                print(f"[Auth] Loaded OAuth client secrets from Secret Manager ({SECRET_GMAIL_CREDENTIALS}).")
            except Exception as cfg_err:
                print(f"[Auth] Warning: Could not parse client secrets from Secret Manager: {cfg_err}")
                flow = None  # type: ignore[assignment]
        else:
            flow = None  # type: ignore[assignment]

        if not flow:
            if os.path.exists("credentials.json"):
                print("[Auth] Using local workspace credentials.json.")
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            else:
                raise FileNotFoundError(
                    f"OAuth client credentials not found in Secret Manager ('{SECRET_GMAIL_CREDENTIALS}') "
                    "or local 'credentials.json'. Please configure in Secret Manager or place credentials.json locally."
                )

        print("[Auth] Starting local web server for Gmail OAuth authorization...")
        creds = flow.run_local_server(port=0)
        token_refreshed = True

    # Step 4: Persist credentials to Secret Manager & OS temp cache (never leave in workspace)
    if creds and (token_refreshed or token_source == "local workspace token.json"):
        token_json_str = creds.to_json()

        # Cache in OS temp dir
        try:
            with open(LOCAL_TOKEN_CACHE, "w", encoding="utf-8") as f:
                f.write(token_json_str)
        except Exception as cache_write_err:
            print(f"[Auth] Warning: Could not cache token to temp dir: {cache_write_err}")

        # Update Secret Manager if possible
        if GCP_PROJECT_ID:
            updated = save_cloud_secret(SECRET_GMAIL_TOKEN, token_json_str, GCP_PROJECT_ID)
            if updated:
                print(f"[Auth] Successfully synced refreshed token to Secret Manager ({SECRET_GMAIL_TOKEN}).")

    return creds



# ===========================================================================
# Standalone CLI Entry Point
# ===========================================================================

if __name__ == "__main__":
    try:
        print("[Auth] Re-authenticating Gmail credentials...")
        authenticate_gmail()
        print("[Auth] Gmail authenticated successfully.")
    except Exception as exc:
        print(f"[Auth] Authentication failed: {exc}")
        sys.exit(1)
