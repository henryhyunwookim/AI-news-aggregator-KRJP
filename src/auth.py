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

import os
import sys
from typing import Any
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from src.config import SCOPES


# ===========================================================================
# Gmail OAuth 2.0 Authentication Helper
# ===========================================================================

def authenticate_gmail() -> Credentials:
    """
    Authenticates with the Google Gmail API using credentials.json and token.json.

    Lifecycle:
        1. Loads existing credentials from 'token.json' if present.
        2. If credentials exist but are expired, attempts automated refresh via Request().
        3. If credentials are missing or unrefreshable:
           - In headless / Cloud Run environments (`K_SERVICE` set or non-interactive TTY),
             raises a RuntimeError detailing required local interactive re-auth.
           - In interactive workstations, launches local server flow using 'credentials.json'.
        4. Serializes updated credentials to 'token.json' for subsequent non-interactive runs.

    Returns:
        google.oauth2.credentials.Credentials: Valid authenticated Gmail credentials object.

    Raises:
        FileNotFoundError: If 'credentials.json' is missing when initial authorization is required.
        RuntimeError: If running in a cloud/headless environment with invalid or expired credentials.
    """
    creds: Credentials | None = None

    # Step 1: Attempt to load previously serialized credentials
    if os.path.exists("token.json"):
        try:
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        except Exception as e:
            print(f"[Auth] Warning: Could not parse existing token.json: {e}")
            creds = None

    # Step 2: Validate credentials and perform automated token refresh
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("[Auth] Access token expired. Attempting automatic refresh via Google Auth...")
                creds.refresh(Request())
                print("[Auth] Access token refreshed successfully.")
            except Exception as e:
                print(f"[Auth] Automated refresh failed: {e}")
                creds = None

        # Step 3: Handle authorization when credentials remain unavailable
        if not creds:
            is_cloud: bool = os.getenv("K_SERVICE") is not None
            is_interactive: bool = bool(sys.stdin and sys.stdin.isatty())

            # In headless cloud environments, browser-based OAuth cannot be performed
            if is_cloud or not is_interactive:
                if os.path.exists("token.json"):
                    try:
                        os.remove("token.json")
                        print("[Auth] Removed invalidated token.json.")
                    except Exception as rm_err:
                        print(f"[Auth] Could not remove token.json: {rm_err}")

                raise RuntimeError(
                    "GMAIL AUTHENTICATION ERROR: token.json is expired or missing and cannot be refreshed "
                    "automatically in a non-interactive/cloud environment. Please run the script locally in interactive "
                    "mode first (e.g., 'python -m src.main --auth') to generate a fresh token.json, then deploy."
                )

            if not os.path.exists("credentials.json"):
                raise FileNotFoundError(
                    "credentials.json not found in the workspace root. Download OAuth client credentials from "
                    "Google Cloud Console and save as credentials.json."
                )

            print("[Auth] Starting local server for Gmail OAuth authorization...")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        # Step 4: Persist credentials to token.json for future unattended runs
        with open("token.json", "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())
            print("[Auth] Successfully persisted refreshed credentials to token.json.")

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
