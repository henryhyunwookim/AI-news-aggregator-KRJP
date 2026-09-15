import json
import time
import re
import google.generativeai as genai
from rapidfuzz import fuzz
from src.config import GEMINI_API_KEY
from src.rss_parser import enrich_candidate_articles

class NewsFilter:
    def __init__(self, api_key=None):
        self.api_key = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key is required. Set GEMINI_API_KEY or GOOGLE_API_KEY in .env or pass it to NewsFilter.")
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(
            'gemini-2.5-flash-lite',
            generation_config={"response_mime_type": "application/json"}
        )

    def select_candidates(self, articles):
        """
        Stage 1: Country-balanced candidate selection.
        Picks the top 3 candidate stories from South Korea and top 3 from Japan
        (total 6 candidates) based on AIFOD relevance and diversity.
        """
        kr_pool = [a for a in articles if a.get('country') == 'KR'][:35]
        jp_pool = [a for a in articles if a.get('country') == 'JP'][:35]

        # If one country is empty or very low, fallback to combined pool
        if not kr_pool and not jp_pool:
            return []

        kr_items = [{"id": f"KR_{i}", "title": a['title'], "source": a['source']} for i, a in enumerate(kr_pool)]
        jp_items = [{"id": f"JP_{i}", "title": a['title'], "source": a['source']} for i, a in enumerate(jp_pool)]

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
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.model.generate_content(prompt)
                data = json.loads(resp.text.strip())
                cand_ids = data.get("selected_ids", [])
                
                candidates = []
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
                print(f"Candidate selection attempt {attempt+1} error: {e}")
                time.sleep(2)

        # Fallback: select first 3 KR and first 3 JP
        return kr_pool[:3] + jp_pool[:3]

    def synthesize_articles(self, enriched_candidates):
        """
        Stage 2: Deep synthesis of the top 5 articles with country balance
        (2-3 from Korea and 2-3 from Japan) using enriched real publisher text.
        """
        if not enriched_candidates:
            return []

        payload = []
        for i, c in enumerate(enriched_candidates):
            payload.append({
                "candidate_index": i,
                "country": c['country'],
                "original_title": c['title'],
                "source": c['source'],
                "article_text": c.get('full_snippet', '')
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
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.model.generate_content(prompt)
                data = json.loads(resp.text.strip())
                items = data.get("articles", [])
                
                results = []
                seen_indices = set()
                
                for item in items:
                    c_idx = item.get("candidate_index")
                    if c_idx is not None and 0 <= c_idx < len(enriched_candidates) and c_idx not in seen_indices:
                        seen_indices.add(c_idx)
                        orig = enriched_candidates[c_idx]
                        
                        # Post-guardrail: ensure no title duplication among selected items
                        title_candidate = item.get("english_title", orig["title"])
                        is_dup = False
                        for existing in results:
                            if fuzz.token_set_ratio(title_candidate.lower(), existing["english_title"].lower()) > 55:
                                is_dup = True
                                break
                        if is_dup:
                            continue
                            
                        results.append({
                            "original_title": orig["title"],
                            "english_title": title_candidate,
                            "english_summary": item.get("english_summary", ""),
                            "aifod_insight": item.get("aifod_insight", ""),
                            "aifod_question": item.get("aifod_question", ""),
                            "aifod_suggested_answer": item.get("aifod_suggested_answer", ""),
                            "link": orig.get("canonical_link") or orig["link"],
                            "source": orig["source"],
                            "country": orig["country"],
                            "published": orig["published"]
                        })
                        if len(results) >= 5:
                            break
                            
                if results:
                    return results
            except Exception as e:
                print(f"Deep synthesis attempt {attempt+1} error: {e}")
                time.sleep(2)
                
        return []

    def filter_articles(self, articles):
        """
        Orchestrates country-balanced candidate selection, real content enrichment,
        and deep LLM synthesis with deduplication guardrails.
        """
        if not articles:
            return []

        print(f"Stage 1: Selecting top candidate stories with country balance from {len(articles)} deduplicated articles...")
        candidates = self.select_candidates(articles)
        print(f"Selected {len(candidates)} candidate articles ({sum(1 for c in candidates if c['country']=='KR')} KR, {sum(1 for c in candidates if c['country']=='JP')} JP).")

        print("Stage 2: Enriching candidate articles with canonical URLs and lead content...")
        enriched = enrich_candidate_articles(candidates)

        print("Stage 3: Running deep synthesis with full source text and country balance...")
        final_articles = self.synthesize_articles(enriched)
        print(f"Deep synthesis complete: {len(final_articles)} articles produced.")

        return final_articles

