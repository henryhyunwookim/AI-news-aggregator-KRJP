"""
AIFOD Daily AI News Aggregator - Flask Web Service.

Purpose:
    Serves as the HTTP entry point for Google Cloud Run, triggered by Google Cloud Scheduler
    via recurring OIDC-authenticated HTTP POST requests.

Endpoints:
    - POST /: Triggers the news aggregator pipeline. Accepts optional query param `?hours=N`
      or JSON payload `{"hours": N}` to customize the news harvest lookback window.
    - GET /: Health check / manual invocation endpoint supporting `?hours=N`.

Deployment Note:
    In production on Cloud Run, this service is executed via Gunicorn:
    `gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 src.app:app`
"""

from __future__ import annotations

import os
from typing import Any
from flask import Flask, jsonify, request, Response
from src.main import main

# Initialize Flask application instance
app: Flask = Flask(__name__)


# ===========================================================================
# HTTP Trigger Route (Cloud Scheduler & Webhook Entry Point)
# ===========================================================================

@app.route("/", methods=["POST", "GET"])
def run_aggregator() -> tuple[Response, int]:
    """
    Triggers the end-to-end news aggregator execution.

    Query Parameters:
        hours (int, optional): Lookback window in hours. Defaults to 24.

    JSON Body (optional):
        {"hours": int}: Overrides lookback window.

    Returns:
        tuple[Response, int]: JSON response payload with HTTP 200 on success or 500 on error.
    """
    try:
        # Step 1: Parse lookback hours and dry_run from query parameters
        hours: int = request.args.get("hours", default=24, type=int)
        dry_run_param: str | None = request.args.get("dry_run")
        dry_run: bool = dry_run_param is not None and dry_run_param.lower() in ("true", "1", "yes")

        # Step 2: Allow JSON request body override if present
        if request.is_json:
            data: dict[str, Any] | None = request.get_json(silent=True)
            if data:
                if "hours" in data:
                    hours = int(data["hours"])
                if "dry_run" in data:
                    dry_run = bool(data["dry_run"])

        print(f"[WebService] Received trigger request (lookback: {hours}h, dry_run: {dry_run})...")

        # Step 3: Execute the core orchestration pipeline
        result: dict[str, Any] = main(hours_back=hours, dry_run=dry_run)

        if result and result.get("success"):
            return jsonify({
                "status": "success",
                "message": "News aggregator ran successfully",
                "stats": result.get("stats", {})
            }), 200
        else:
            error_detail = result.get("error", "Unknown execution error")
            return jsonify({
                "status": "error",
                "message": f"Aggregator encountered an error: {error_detail}",
                "stats": result.get("stats", {})
            }), 500

    except Exception as exc:
        print(f"[WebService] Unhandled error during trigger execution: {exc}")
        return jsonify({
            "status": "error",
            "message": f"Server error: {exc}"
        }), 500


# ===========================================================================
# Local Development Entry Point
# ===========================================================================

if __name__ == "__main__":
    # Google Cloud Run injects the PORT environment variable dynamically (defaults to 8080)
    server_port: int = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=server_port)
