"""
AIFOD Daily AI News Aggregator - Main Orchestration Pipeline.

Purpose:
    Coordinates the end-to-end execution of the news aggregator:
    1. Pre-flight verification of Google Gmail OAuth credentials.
    2. Concurrently retrieves and algorithmically deduplicates RSS feeds from KR and JP.
    3. Evaluates, enriches, and synthesizes top country-balanced stories via Google Gemini.
    4. Compiles a responsive HTML digest and transmits it to the practitioner via Gmail API.

CLI Usage:
    # Run standard daily harvest (24h lookback):
    python -m src.main

    # Run custom lookback window (e.g., 48 hours):
    python -m src.main --hours 48

    # Run interactive Gmail OAuth flow to refresh/generate token.json:
    python -m src.main --auth
"""

from __future__ import annotations

import argparse
import sys
import zoneinfo
from datetime import datetime, timezone
from typing import Any

# Ensure UTF-8 console output for Korean/Japanese characters across all operating systems
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.auth import authenticate_gmail
from src.config import RECIPIENT_EMAIL, TIMEZONE
from src.email_sender import EmailSender
from src.llm_filter import NewsFilter
from src.memory import append_run_log, load_cloud_state, save_cloud_state
from src.rss_parser import parse_and_filter_articles



# ===========================================================================
# Core Orchestration Function
# ===========================================================================

def main(hours_back: int = 24, dry_run: bool = False) -> dict[str, Any]:
    """
    Executes the full news aggregation, synthesis, and delivery workflow.

    Pipeline Steps:
        Step 1: Date and Timezone Resolution & Cloud State Loading
        Step 2: Pre-Flight Gmail Authentication Check
        Step 3: Multilingual Ingestion, Algorithmic Deduplication & State Filter
        Step 4: Two-Stage Gemini Candidate Selection, Enrichment & Synthesis
        Step 5: HTML Digest Generation & (Optional) Email Dispatch
        Step 6: Cloud State Persistence & Decoupled Operational Run Logging

    Args:
        hours_back: Publication lookback window in hours. Defaults to 24.
        dry_run: If True, executes harvest, evaluation, and HTML compilation but
                 skips Gmail delivery and state modification. Defaults to False.

    Returns:
        dict[str, Any]: Execution summary containing 'success', 'stats', and 'error'.
    """
    error_message: str | None = None
    stats: dict[str, int] = {
        "total_fetched": 0,
        "new_candidates": 0,
        "relevant_count": 0,
        "kr_count": 0,
        "jp_count": 0
    }

    try:
        # Step 1: Resolve current date string in targeted operational timezone
        try:
            tz = zoneinfo.ZoneInfo(TIMEZONE)
            local_now: datetime = datetime.now(tz)
        except Exception as tz_err:
            print(f"[Orchestrator] Warning: Could not load timezone '{TIMEZONE}' ({tz_err}). Falling back to system time.")
            local_now = datetime.now()

        date_str: str = local_now.strftime("%B %d, %Y")
        mode_str: str = " [DRY-RUN MODE]" if dry_run else ""
        print(f"===========================================================================")
        print(f" AIFOD Daily AI News Aggregator - {date_str} (Lookback: {hours_back}h){mode_str}")
        print(f"===========================================================================")

        # Step 2: Load persistent state from Google Cloud Storage
        cloud_state: dict[str, Any] = load_cloud_state()
        sent_urls: set[str] = set(cloud_state.get("sent_article_urls", []))
        print(f"[Orchestrator] Loaded cloud state (Previously delivered articles tracked: {len(sent_urls)}).")

        # Step 3: Pre-flight Gmail OAuth credential validation
        print("[Step 1/4] Verifying Gmail authentication...")
        creds = authenticate_gmail()

        # Step 4: Fetch RSS feeds concurrently and apply RapidFuzz deduplication
        print(f"[Step 2/4] Fetching and clustering news feeds (last {hours_back} hours)...")
        fetched_articles: list[dict[str, Any]] = parse_and_filter_articles(hours_back=hours_back)
        stats["total_fetched"] = len(fetched_articles)

        # Filter out articles that were already delivered in recent digests
        fresh_articles = [a for a in fetched_articles if a.get("link") not in sent_urls]
        stats["new_candidates"] = len(fresh_articles)
        if len(fresh_articles) < len(fetched_articles):
            print(f"[Step 2/4] State deduplication: {len(fetched_articles) - len(fresh_articles)} previously sent stories ignored.")

        if not fresh_articles:
            print("[Step 2/4] No new un-sent articles found within the lookback window.")
            relevant_articles: list[dict[str, Any]] = []
        else:
            # Step 5: Run two-stage candidate selection, enrichment, and synthesis
            print(f"[Step 3/4] Evaluating and synthesizing {len(fresh_articles)} stories via Google Gemini...")
            news_filter = NewsFilter()
            relevant_articles = news_filter.filter_articles(fresh_articles)

        stats["relevant_count"] = len(relevant_articles)
        stats["kr_count"] = sum(1 for a in relevant_articles if a.get("country") == "KR")
        stats["jp_count"] = sum(1 for a in relevant_articles if a.get("country") == "JP")

        print(f"[Step 3/4] Evaluation complete. Produced {stats['relevant_count']} balanced stories ({stats['kr_count']} KR, {stats['jp_count']} JP):")
        for i, art in enumerate(relevant_articles, 1):
            print(f"   {i}. [{art.get('country')}] {art.get('english_title')} ({art.get('source')})")

        # Step 6: Format digest and handle delivery
        sender = EmailSender(creds)
        if dry_run:
            print("[Step 4/4] [DRY-RUN] Compiling HTML digest template for verification (Email dispatch skipped)...")
            html_content = sender.build_html_digest(relevant_articles, stats["total_fetched"], date_str)
            print(f"[Step 4/4] [DRY-RUN] HTML template compiled successfully ({len(html_content)} characters). Recipient: {RECIPIENT_EMAIL}")
        else:
            print("[Step 4/4] Compiling HTML digest and dispatching via Gmail API...")
            sender.send_digest_email(relevant_articles, stats["total_fetched"], date_str)
            print("[Orchestrator] Email digest dispatched successfully!")

            # Update persistent cloud state
            new_urls = [a.get("link") for a in relevant_articles if a.get("link")]
            cloud_state["sent_article_urls"] = list(sent_urls.union(new_urls))[-500:]
            cloud_state["total_dispatched_articles"] = cloud_state.get("total_dispatched_articles", 0) + len(relevant_articles)
            cloud_state["run_count"] = cloud_state.get("run_count", 0) + 1
            save_cloud_state(cloud_state)
            print("[Orchestrator] Persistent cloud state updated in GCS.")

        print("[Orchestrator] Pipeline executed successfully!")

    except Exception as exc:
        error_message = str(exc)
        print(f"[Orchestrator] Execution encountered an error: {error_message}")

    # Decoupled operational run logging
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "success" if error_message is None else "error",
        "dry_run": dry_run,
        "hours_back": hours_back,
        "stats": stats,
        "error": error_message,
    }
    append_run_log(log_entry)

    return {
        "success": error_message is None,
        "stats": stats,
        "error": error_message
    }


# ===========================================================================
# CLI Argument Parsing & Entry Point
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AIFOD Daily AI News Aggregator - South Korea & Japan Edition"
    )
    parser.add_argument(
        "--auth",
        action="store_true",
        help="Run interactive Gmail OAuth 2.0 flow to create/refresh token in Secret Manager"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Lookback window in hours for article publication date (default: 24)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run end-to-end pipeline (fetch, filter, LLM synthesis, HTML build) without sending email or saving state"
    )
    cli_args = parser.parse_args()

    if cli_args.auth:
        print("[CLI] Initiating interactive Gmail OAuth setup...")
        authenticate_gmail()
        print("[CLI] Gmail credentials verified successfully.")
        sys.exit(0)

    exec_result: dict[str, Any] = main(hours_back=cli_args.hours, dry_run=cli_args.dry_run)
    if not exec_result["success"]:
        sys.exit(1)
