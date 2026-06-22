import json
import time
import google.generativeai as genai
from src.config import GEMINI_API_KEY

class NewsFilter:
    def __init__(self, api_key=None):
        self.api_key = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key is required. Set GEMINI_API_KEY in .env or pass it to NewsFilter.")
        genai.configure(api_key=self.api_key)
        # Using gemini-2.5-flash-lite as used in the user's other workspace, or fallback
        self.model = genai.GenerativeModel('gemini-2.5-flash-lite')

    def filter_and_translate_batch(self, articles):
        """
        Filters articles for AIFOD relevance, translates them to English,
        deduplicates similar stories, and selects the top 5.
        Articles is a list of dicts.
        """
        if not articles:
            return []

        # Prepare articles list for the prompt
        simplified_articles = []
        for idx, art in enumerate(articles):
            simplified_articles.append({
                "index": idx,
                "title": art["title"],
                "source": art["source"],
                "country": art["country"],
                "query": art["query_matched"],
                "snippet": art["description"][:300] if art.get("description") else ""
            })

        prompt = f"""You are an expert news analyst for the **AI for Developing Countries Forum (AIFOD)**.
Your task is to analyze the following list of AI-related articles from South Korea and Japan, filter them for relevance to AIFOD's mission, aggressively deduplicate similar stories, and select the **top 5 most impactful articles** of the day, translating and summarizing them in English.

### AIFOD Mission & Relevant Topics:
1. **Bridging the AI Gap**: Actions, policies, or projects addressing the AI accessibility/digital divide between developed and developing nations (the Global South).
2. **AI Governance & Social Equity**: Regulatory, ethical, or policy frameworks that emphasize inclusivity, human-centric AI, and equity in emerging economies.
3. **Capacity Building & Education**: AI education, skills training, or human resource initiatives in Korea/Japan, particularly those with international outreach or applicability to emerging regions.
4. **International Cooperation & Partnerships**: Official Development Assistance (ODA), cooperation programs (e.g., via KOICA, JICA), university/research exchanges, or joint public/private ventures between Korea/Japan and developing nations regarding AI.
5. **AI for Social Good**: AI applications in healthcare, education, agriculture, disaster mitigation, or climate change that could be applied to or support developing countries.

### Articles to Analyze:
{json.dumps(simplified_articles, ensure_ascii=False, indent=2)}

### Response Format:
You MUST respond with ONLY a valid JSON object in the exact format shown below (no other text, markdown blocks, or commentary).
{{
  "relevant_articles": [
    {{
      "index": 0,
      "relevance_explanation": "A one-sentence explanation of why this article is relevant to AIFOD.",
      "english_title": "Clean, natural English translation of the article's title",
      "english_summary": "A high-quality 2-3 sentence summary in English highlighting the core information, especially details about international cooperation, policy impacts, or technologies used.",
      "aifod_insight": "An analytical paragraph explaining the significance/implication of this news specifically for AIFOD's mission, capacity building, or Global South advocacy.",
      "aifod_question": "A critical, analytical question that AIFOD practitioners should ask policymakers or stakeholders regarding this development.",
      "aifod_suggested_answer": "A suggested stance, strategy, or response representing AIFOD's perspective on how to address the above question."
    }}
  ]
}}

### Rules:
1. **Ultra-Strict Deduplication & Topic Diversity** (CRITICAL — apply BEFORE ranking):
   - **Identical Events & Announcements (Zero Tolerance)**: If multiple articles cover the exact same event, press release, announcement, university program completion, or corporate partnership (even if reported by different publishers, written in different styles, or utilizing different translations), you MUST keep ONLY the single most comprehensive article. Keep the one that contains the most detail and discard the rest.
   - **Substantially Overlapping Content**: If two articles discuss the same underlying story, trend, or initiative (e.g., multiple outlets reporting on a new government funding round, the same AI guidelines, or different details of the same conference), treat them as duplicates. Keep only the best one.
   - **Thematic Redundancy & Diversity Constraint**: Even if two articles are technically about different events or different entities (e.g., two different universities launching similar AI training programs, two different local governments adopting AI chatbots, or two different companies launching similar AI translation tools), if their core theme and application scenario are highly similar, treat them as duplicates/redundant topics. Keep only the single most impactful or representative article of that type to ensure the 5 selected articles represent 5 completely different facets of AI news.
   - **Cross-country/Cross-language duplicates (Optional/Gentle)**: A Korean article and a Japanese article about the exact same international event or policy (e.g., a G7 AI agreement, a UN resolution, a bilateral cooperation) are duplicates. Keep only one. However, national/local developments in Korea and Japan that have similar themes but occur independently (e.g., a Korean agency launching an AI education program and a Japanese agency launching a different AI education program) are NOT duplicates and both may be included if they are highly impactful.
   - When in doubt, always err on the side of deduplicating and diversifying. The final list of 5 articles must have zero conceptual, thematic, or event-based repetition.
2. **Limit Output**: You MUST return a maximum of 5 articles in the `relevant_articles` array. Select the **top 5 most significant and impactful** articles for AIFOD's mission.
3. **Relevance Threshold**: Prioritize articles that strictly align with core AIFOD mission topics (international cooperation, ODA, digital divide). However, if fewer than 3 highly relevant articles exist, you should include articles that are moderately relevant to AIFOD's broader themes (such as general AI policy, ethical guidelines, AI education, or AI applications for social good in Korea/Japan that could serve as models or reference points for developing nations). Avoid returning 0 articles unless there is absolutely no AI policy, education, or social good news in the batch.
4. **Translate & Summarize**: All titles, summaries, insights, questions, and answers MUST be in English.
5. Output ONLY the raw JSON object. Do not include markdown code block syntax (like ```json).
"""

        max_retries = 5
        retry_delay = 3
        
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
                text = response.text.strip()
                
                # Attempt to extract JSON
                extracted_json = text
                if '```json' in text:
                    extracted_json = text.split('```json')[1].split('```')[0].strip()
                elif '```' in text:
                    extracted_json = text.split('```')[1].split('```')[0].strip()
                
                # Try parsing JSON
                try:
                    result = json.loads(extracted_json)
                except json.JSONDecodeError:
                    # Fallback using regex to find first '{' and last '}'
                    import re
                    json_match = re.search(r'(\{[\s\S]*\})', text)
                    if json_match:
                        result = json.loads(json_match.group(1))
                    else:
                        raise ValueError("No JSON object found in response.")

                # Match index back to original articles
                filtered_articles = []
                for item in result.get("relevant_articles", []):
                    idx = item.get("index")
                    if idx is not None and 0 <= idx < len(articles):
                        orig = articles[idx]
                        filtered_articles.append({
                            "original_title": orig["title"],
                            "english_title": item["english_title"],
                            "english_summary": item["english_summary"],
                            "relevance_explanation": item["relevance_explanation"],
                            "aifod_insight": item.get("aifod_insight", ""),
                            "aifod_question": item.get("aifod_question", ""),
                            "aifod_suggested_answer": item.get("aifod_suggested_answer", ""),
                            "link": orig["link"],
                            "source": orig["source"],
                            "country": orig["country"],
                            "published": orig["published"]
                        })
                return filtered_articles

            except Exception as e:
                error_msg = str(e)
                print(f"Filtering attempt {attempt+1} failed: {error_msg}")
                if attempt < max_retries - 1:
                    if "429" in error_msg or "Resource exhausted" in error_msg:
                        print("Rate limit reached. Waiting 60 seconds before retrying...")
                        time.sleep(60)
                    else:
                        time.sleep(retry_delay * (attempt + 1))
                else:
                    print(f"Failed to process batch after {max_retries} attempts.")
                    return []

    def filter_articles(self, articles):
        """
        Process the list of articles, globally deduplicating and selecting the top 5.
        """
        if not articles:
            return []
            
        # To avoid exceeding tokens or output limits, cap at first 100 articles
        if len(articles) > 100:
            print(f"Large harvest: capping evaluation at 100 articles (out of {len(articles)}).")
            articles = articles[:100]
            
        print(f"Sending {len(articles)} unique articles to Gemini for deduplication, relevance filtering, and ranking...")
        return self.filter_and_translate_batch(articles)
