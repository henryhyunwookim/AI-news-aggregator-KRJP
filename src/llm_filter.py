"""
AIFOD Daily AI News Aggregator - LLM Filtering & Synthesis Module.

Purpose:
    Leverages Google Gemini Generative AI to evaluate candidate news stories against
    AIFOD's mission criteria, ensure geographical balance between South Korea and Japan,
    and generate rich English summaries, strategic insights, and practitioner Q&As.

Two-Stage AI Architecture:
    Stage 1: Country-Balanced Candidate Selection
        - Takes up to 35 deduplicated articles each from KR and JP pools.
        - Uses Gemini structured JSON mode to pick the top 3 KR and top 3 JP candidate stories
          (6 total) based on relevance to AI divide, ODA, capacity building, and policy.
    Enrichment Intermission:
        - Resolves canonical publisher URLs and scrapes full lead paragraphs / OpenGraph text.
    Stage 2: Deep Factual Synthesis
        - Prompts Gemini with rich source text to generate the final 5-story digest.
        - Strictly enforces country balance: 2-3 from KR and 2-3 from JP.
        - Generates dense factual summaries (actors, dates, venues), strategic "So What?" insights,
          and a practitioner policy dilemma with recommended stance.
    Post-Generation Guardrail:
        - Runs pairwise RapidFuzz similarity checks (< 55%) across final English titles to ensure
          no duplicate coverage slips through the synthesis phase.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import google.generativeai as genai
from rapidfuzz import fuzz

from src.config import GEMINI_API_KEY
from src.rss_parser import enrich_candidate_articles


# ===========================================================================
# NewsFilter Class Definition
# ===========================================================================

class NewsFilter:
    """
    Orchestrates the two-stage LLM evaluation, enrichment, and synthesis pipeline.
    """

    def __init__(self, api_key: str | None = None) -> None:
        """
        Initializes the Gemini model client.

        Args:
            api_key: Optional Gemini API key. Defaults to GEMINI_API_KEY from src.config.
        """
        self.api_key: str | None = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise ValueError(
                "Gemini API key is required. Set GEMINI_API_KEY or GOOGLE_API_KEY in .env "
                "or provide it to NewsFilter(api_key=...)."
            )

        genai.configure(api_key=self.api_key)
        # Using gemini-2.5-flash-lite for rapid latency, high reasoning quality, and structured JSON output
        self.model = genai.GenerativeModel(
            "gemini-2.5-flash-lite",
            generation_config={"response_mime_type": "application/json"}
        )

    # =======================================================================
    # Stage 1: Country-Balanced Candidate Selection
    # =======================================================================

    def select_candidates(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Stage 1: Evaluates candidate headlines and selects the top 3 stories from
        South Korea and top 3 stories from Japan (total 6 candidates).

        Args:
            articles: Deduplicated event stories from parse_and_filter_articles().

        Returns:
            List of 6 selected candidate article dictionaries (3 KR, 3 JP).
        """
        kr_pool = [a for a in articles if a.get("country") == "KR"][:35]
        jp_pool = [a for a in articles if a.get("country") == "JP"][:35]

        if not kr_pool and not jp_pool:
            return []

        kr_items = [{"id": f"KR_{i}", "title": a["title"], "source": a["source"]} for i, a in enumerate(kr_pool)]
        jp_items = [{"id": f"JP_{i}", "title": a["title"], "source": a["source"]} for i, a in enumerate(jp_pool)]

        prompt = f"""You are an expert news analyst for the **AI for Developing Countries Forum (AIFOD)**.
Your task is to analyze the candidate AI news headlines from South Korea and Japan and select the **top 3 most relevant, impactful, and distinct candidate stories from South Korea** and the **top 3 from Japan** (total 6 candidates).

### AIFOD Mission & Core Topics:
1. **Bridging the AI Gap**: Actions, policies, or projects addressing the AI digital divide between developed and developing nations (the Global South).
2. **AI Governance & Social Equity**: Ethical guidelines, regulatory frameworks, human rights, and social equity in AI.
3. **Capacity Building & Education**: AI education, skills development, or human resource initiatives with potential international applicability.
4. **International Cooperation & ODA**: Official Development Assistance (e.g. KOICA, JICA), bilateral/multilateral agreements, or development aid involving AI.
5. **AI for Social Good**: AI applications in healthcare, education, agriculture, climate mitigation, disaster prevention, or public service.

### Critical Rules:
- **Zero Duplicate Events**: Do not select multiple articles that report on the same underlying announcement, event, or press release.
- **Thematic Diversity**: Select stories representing different dimensions of AI (e.g. diplomacy/ODA, regulation, climate/social good, education).

South Korea Articles:
{json.dumps(kr_items, ensure_ascii=False, indent=1)}

Japan Articles:
{json.dumps(jp_items, ensure_ascii=False, indent=1)}

### Response Format:
Respond with ONLY a valid JSON object in this format:
{{
  "selected_ids": ["KR_0", "KR_1", "KR_2", "JP_0", "JP_1", "JP_2"]
}}
"""
        max_retries: int = 3
        for attempt in range(max_retries):
            try:
                resp = self.model.generate_content(prompt)
                data = json.loads(resp.text.strip())
                cand_ids: list[str] = data.get("selected_ids", [])

                candidates: list[dict[str, Any]] = []
                for cid in cand_ids:
                    if cid.startswith("KR_"):
                        idx = int(cid.split("_")[1])
                        if 0 <= idx < len(kr_pool):
                            candidates.append(kr_pool[idx])
                    elif cid.startswith("JP_"):
                        idx = int(cid.split("_")[1])
                        if 0 <= idx < len(jp_pool):
                            candidates.append(jp_pool[idx])

                if candidates:
                    return candidates
            except Exception as e:
                print(f"[LLM] Candidate selection attempt {attempt + 1} error: {e}")
                time.sleep(2)

        # Graceful fallback: take first 3 KR and first 3 JP if model call fails
        return kr_pool[:3] + jp_pool[:3]

    # =======================================================================
    # Stage 2: Deep Factual Synthesis & Strategic Analysis
    # =======================================================================

    def synthesize_articles(self, enriched_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Stage 2: Generates rich factual summaries, strategic insights, and practitioner Q&As
        for the top 5 articles, enforcing country balance (2-3 KR and 2-3 JP).

        Args:
            enriched_candidates: Candidates containing canonical URLs and full article snippets.

        Returns:
            List of 5 synthesized article dictionaries ready for the email template.
        """
        if not enriched_candidates:
            return []

        payload = []
        for i, c in enumerate(enriched_candidates):
            payload.append({
                "candidate_index": i,
                "country": c.get("country", ""),
                "original_title": c.get("title", ""),
                "source": c.get("source", ""),
                "article_text": c.get("full_snippet", "")
            })

        prompt = f"""You are an expert news analyst for the **AI for Developing Countries Forum (AIFOD)**.
From the {len(enriched_candidates)} enriched candidate articles below, select the **top 5 most impactful articles** of the day for AIFOD's mission.

### Country Balance Constraint (MANDATORY):
You MUST select a balanced representation: **2 or 3 articles from South Korea (KR)** and **2 or 3 articles from Japan (JP)**, totaling exactly 5 articles.

### Output Quality & Non-Overlap Rules:
1. **`english_title`**: Natural, accurate, professional English translation of the headline.
2. **`english_summary` (Dense & Factual)**: A high-quality 3-4 sentence factual summary in English highlighting WHAT happened. You MUST include concrete entities, dates, venues, partner nations, technical details, or policy specifics present in the source text. Do NOT use generic filler or merely repeat the title.
3. **`aifod_insight` (Strategic "So What?")**: A focused 2-3 sentence strategic analysis explaining the direct significance/implication specifically for AIFOD's mission and developing nations (Global South opportunities, equity, or policy impact). Must NOT rehash facts from the summary.
4. **`aifod_question` (Forward-Looking Dilemma)**: A critical, forward-looking strategic question that AIFOD practitioners should ask policymakers or international partners.
5. **`aifod_suggested_answer` (Actionable Stance)**: A concise, actionable 1-2 sentence recommendation or stance representing AIFOD's perspective on how to address the above question.

Candidate Articles:
{json.dumps(payload, ensure_ascii=False, indent=2)}

### Response Format:
Respond with ONLY a valid JSON object in this format:
{{
  "articles": [
    {{
      "candidate_index": 0,
      "english_title": "...",
      "english_summary": "...",
      "aifod_insight": "...",
      "aifod_question": "...",
      "aifod_suggested_answer": "..."
    }}
  ]
}}
"""
        max_retries: int = 3
        for attempt in range(max_retries):
            try:
                resp = self.model.generate_content(prompt)
                data = json.loads(resp.text.strip())
                items: list[dict[str, Any]] = data.get("articles", [])

                results: list[dict[str, Any]] = []
                seen_indices: set[int] = set()

                for item in items:
                    c_idx = item.get("candidate_index")
                    if c_idx is not None and 0 <= c_idx < len(enriched_candidates) and c_idx not in seen_indices:
                        seen_indices.add(c_idx)
                        orig = enriched_candidates[c_idx]

                        title_candidate = item.get("english_title", orig.get("title", ""))

                        # Post-generation guardrail: verify no duplicate English titles slip through
                        is_duplicate: bool = False
                        for existing in results:
                            if fuzz.token_set_ratio(title_candidate.lower(), existing["english_title"].lower()) > 55:
                                is_duplicate = True
                                break
                        if is_duplicate:
                            continue

                        results.append({
                            "original_title": orig.get("title", ""),
                            "english_title": title_candidate,
                            "english_summary": item.get("english_summary", ""),
                            "aifod_insight": item.get("aifod_insight", ""),
                            "aifod_question": item.get("aifod_question", ""),
                            "aifod_suggested_answer": item.get("aifod_suggested_answer", ""),
                            "link": orig.get("canonical_link") or orig.get("link", ""),
                            "source": orig.get("source", ""),
                            "country": orig.get("country", ""),
                            "published": orig.get("published", "")
                        })

                        if len(results) >= 5:
                            break

                if results:
                    return results
            except Exception as exc:
                print(f"[LLM] Deep synthesis attempt {attempt + 1} error: {exc}")
                time.sleep(2)

        return []

    # =======================================================================
    # Pipeline Orchestration
    # =======================================================================

    def filter_articles(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Coordinates the complete two-stage evaluation pipeline:
        Stage 1 Selection -> Content Enrichment -> Stage 2 Synthesis -> Guardrail.

        Args:
            articles: Ingested and deduplicated articles.

        Returns:
            List of 5 country-balanced, synthesized articles.
        """
        if not articles:
            return []

        print(f"[LLM Pipeline] Stage 1: Selecting top candidate stories with country balance from {len(articles)} deduplicated articles...")
        candidates = self.select_candidates(articles)
        kr_candidates = sum(1 for c in candidates if c.get("country") == "KR")
        jp_candidates = sum(1 for c in candidates if c.get("country") == "JP")
        print(f"[LLM Pipeline] Selected {len(candidates)} candidates ({kr_candidates} KR, {jp_candidates} JP).")

        print("[LLM Pipeline] Stage 2: Enriching candidate articles with canonical publisher URLs and lead text...")
        enriched = enrich_candidate_articles(candidates)

        print("[LLM Pipeline] Stage 3: Running deep synthesis with country balance and structured JSON...")
        final_articles = self.synthesize_articles(enriched)
        print(f"[LLM Pipeline] Deep synthesis complete: {len(final_articles)} articles produced.")

        return final_articles
