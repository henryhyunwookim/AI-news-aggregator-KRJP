"""
AIFOD Daily AI News Aggregator - RSS Ingestion & Deduplication Module.

Purpose:
    Retrieves, parses, deduplicates, and enriches multilingual news feeds from South Korea
    and Japan. Implements a resilient dual-engine retrieval pipeline (Google News + Bing News fallback)
    and algorithmic title clustering to collapse duplicate press coverage into distinct event stories.

Architecture & Algorithmic Strategy:
    1. Dual-Engine Retrieval:
       - Primary: Google News RSS via language-tailored XML search endpoints.
       - Resilient Fallback: Bing News RSS, which maintains high uptime on cloud datacenter IPs
         (e.g., Google Cloud Run) where Google egress may trigger rate limits or HTTP 503 blocks.
    2. Fuzzy Title Clustering (RapidFuzz):
       - Eliminates redundant press releases across competing media outlets by normalizing headlines
         (stripping outlet tags like '- 로이슈', brackets like '[포토]', punctuation) and clustering
         via token-set ratio similarity >= 65%.
       - For each cluster, the article with the longest real factual description is retained.
    3. Real Content Enrichment:
       - Resolves Google News 'CBMi...' redirect URLs into canonical publisher URLs using
         'googlenewsdecoder'.
       - Fetches OpenGraph metadata (og:description, meta description, and lead paragraphs)
         to ensure the LLM receives real article substance rather than truncated RSS snippets.
"""

from __future__ import annotations

import calendar
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup
from googlenewsdecoder import gnewsdecoder
from rapidfuzz import fuzz

from src.config import JAPANESE_QUERIES, KOREAN_QUERIES

# Desktop user-agents for realistic browser emulation and scraping resilience
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0"
]


# ===========================================================================
# 1. URL Sanitization & Canonical Resolution
# ===========================================================================

def clean_article_url(raw_url: str | None) -> str:
    """
    Extracts the underlying target article URL if wrapped in a Bing or search redirect.

    Args:
        raw_url: Raw URL string extracted from an RSS entry.

    Returns:
        Cleaned direct URL string.
    """
    if not raw_url:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw_url)
        # Bing News RSS frequently encodes the real destination inside a 'url' query parameter
        if "bing.com" in parsed.netloc and "url" in parsed.query:
            qs = urllib.parse.parse_qs(parsed.query)
            target = qs.get("url", [raw_url])[0]
            return target
    except Exception:
        pass
    return raw_url


def resolve_canonical_url(url: str | None) -> str:
    """
    Resolves Google News (CBMi...) or Bing redirect links into direct canonical publisher URLs.

    Args:
        url: Potentially redirected or obfuscated URL.

    Returns:
        Direct publisher article URL, or the cleaned original URL if decoding fails.
    """
    if not url:
        return ""
    clean_url: str = clean_article_url(url)
    if "news.google.com" in clean_url:
        try:
            # Decode Google News base64 CBMi protobuf redirects into the real destination
            res = gnewsdecoder(clean_url, interval=0.1)
            if res.get("status") and res.get("decoded_url"):
                return str(res["decoded_url"])
        except Exception:
            pass
    return clean_url


# ===========================================================================
# 2. Algorithmic Title Normalization & Fuzzy Event Clustering
# ===========================================================================

def normalize_title(title: str | None) -> str:
    """
    Normalizes an article headline for fuzzy event clustering.

    Normalization Pipeline:
        1. Strips bracketed metadata: '[포토]', '(종합)', '【속보】', '[단독]'.
        2. Strips trailing publisher attribution suffixes: '- 로이슈', '| 연합뉴스', '- 日本経済新聞'.
        3. Strips punctuation and special characters while preserving Korean, Japanese, and Latin words.
        4. Collapses redundant whitespace and converts to lowercase.

    Args:
        title: Raw headline string.

    Returns:
        Normalized title string for similarity comparison.
    """
    if not title:
        return ""

    # Step 1: Strip bracketed prefixes or tags
    t: str = re.sub(r"\[.*?\]|\(.*?\)|【.*?】", " ", title)

    # Step 2: Strip common trailing publisher suffixes (e.g., '- 연합뉴스', '| 매일경제')
    t = re.sub(r"[-|–—·]\s*[\w\.\s]+$", " ", t)

    # Step 3: Strip non-alphanumeric punctuation while retaining word characters and whitespace
    t = re.sub(r"[^\w\s]", " ", t)

    # Step 4: Normalize whitespace and case
    return re.sub(r"\s+", " ", t).strip().lower()


def cluster_and_deduplicate_articles(
    articles: list[dict[str, Any]],
    threshold: int = 65
) -> list[dict[str, Any]]:
    """
    Groups articles into distinct event clusters using normalized fuzzy title similarity.

    Algorithm Rationale:
        News agencies often syndicate the same government or corporate press release with minor
        headline alterations across multiple regional publications.
        RapidFuzz `token_set_ratio` calculates similarity based on intersection and remainder tokens:
            Score = (2 * |Tokens(A) ∩ Tokens(B)|) / (|Tokens(A)| + |Tokens(B)|)
        A threshold of 65% reliably pairs identical press releases while avoiding false mergers
        of distinct policy announcements. Within each cluster, the article with the longest
        clean textual description is preserved.

    Args:
        articles: List of parsed article dictionary objects.
        threshold: Minimum fuzzy similarity percentage (0-100) to merge into a cluster.

    Returns:
        List of representative article dictionaries (one per event cluster).
    """
    if not articles:
        return []

    clusters: list[list[dict[str, Any]]] = []

    for art in articles:
        norm_title: str = normalize_title(art.get("title", ""))
        matched_cluster: list[dict[str, Any]] | None = None

        # Compare against existing event clusters (restricted to same country)
        for cluster in clusters:
            for existing_art in cluster:
                if art.get("country") == existing_art.get("country"):
                    existing_norm: str = normalize_title(existing_art.get("title", ""))
                    similarity: float = fuzz.token_set_ratio(norm_title, existing_norm)
                    if similarity >= threshold:
                        matched_cluster = cluster
                        break
            if matched_cluster is not None:
                break

        if matched_cluster is not None:
            matched_cluster.append(art)
        else:
            clusters.append([art])

    # Select the single best article per cluster based on description depth
    deduped: list[dict[str, Any]] = []
    for cluster in clusters:
        def article_score(candidate: dict[str, Any]) -> int:
            clean_text = re.sub(r"<[^>]+>", "", candidate.get("description", "")).strip()
            return len(clean_text)

        best_article: dict[str, Any] = max(cluster, key=article_score)
        deduped.append(best_article)

    return deduped


# ===========================================================================
# 3. Dual-Engine Feed Ingestion (Google News RSS + Bing News Fallback)
# ===========================================================================

def fetch_google_rss(query: str, country_code: str) -> list[Any]:
    """
    Fetches raw RSS feed entries directly from Google News RSS.

    Args:
        query: Targeted search query.
        country_code: 'KR' (South Korea) or 'JP' (Japan).

    Returns:
        List of feedparser entry objects, or empty list on failure / block.
    """
    encoded_query: str = urllib.parse.quote(query)
    if country_code == "KR":
        hl, gl = "ko", "KR"
    elif country_code == "JP":
        hl, gl = "ja", "JP"
    else:
        raise ValueError(f"Invalid country_code: '{country_code}'. Must be 'KR' or 'JP'.")

    url: str = f"https://news.google.com/rss/search?q={encoded_query}&hl={hl}&gl={gl}&ceid={gl}:{hl}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENTS[0],
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,ja-JP,ja;q=0.8,en-US;q=0.7,en;q=0.6"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            feed = feedparser.parse(xml_data)
            if feed.entries:
                return feed.entries
    except Exception:
        # Expected on cloud datacenters when egress IP encounters temporary Google throttling
        pass

    return []


def fetch_bing_rss(query: str, country_code: str) -> list[Any]:
    """
    Fetches articles from Bing News RSS. Highly reliable across cloud datacenter egress IPs.

    Args:
        query: Targeted search query.
        country_code: 'KR' or 'JP' (for logging context).

    Returns:
        List of feedparser entry objects, or empty list on failure.
    """
    encoded_query: str = urllib.parse.quote(query)
    url: str = f"https://www.bing.com/news/search?q={encoded_query}&format=rss"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENTS[0],
            "Accept": "application/rss+xml, application/xml, text/xml, */*"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            feed = feedparser.parse(xml_data)
            if feed.entries:
                return feed.entries
    except Exception as e:
        print(f"[RSS] Bing RSS error for '{query}' [{country_code}]: {e}")

    return []


def get_feed_articles(query: str, country_code: str) -> list[Any]:
    """
    Retrieves entries using multi-engine fallback:
    1. Attempts primary Google News RSS.
    2. Seamlessly falls back to Bing News RSS if Google blocks or returns empty.

    Args:
        query: Search keyword string.
        country_code: 'KR' or 'JP'.

    Returns:
        List of valid feed entry objects.
    """
    # Attempt Primary: Google News
    entries = fetch_google_rss(query, country_code)
    if entries:
        return entries

    # Fallback: Bing News RSS
    entries = fetch_bing_rss(query, country_code)
    if entries:
        return entries

    return []


# ===========================================================================
# 4. Multi-Query Orchestration & Filtering
# ===========================================================================

def parse_and_filter_articles(hours_back: int = 24) -> list[dict[str, Any]]:
    """
    Concurrently fetches news articles for all Korean and Japanese search queries,
    applies time window filtering, eliminates duplicate URLs, and performs
    algorithmic fuzzy event clustering.

    Args:
        hours_back: Number of hours to look back for publication dates.

    Returns:
        Deduplicated list of distinct event story dictionaries.
    """
    now: datetime = datetime.now(timezone.utc)
    time_threshold: datetime = now - timedelta(hours=hours_back)

    seen_urls: set[str] = set()
    raw_articles: list[dict[str, Any]] = []

    def fetch_single_query(q: str, c: str) -> tuple[str, str, list[Any]]:
        return q, c, get_feed_articles(q, c)

    all_tasks: list[tuple[str, str]] = []
    for query in KOREAN_QUERIES:
        all_tasks.append((query, "KR"))
    for query in JAPANESE_QUERIES:
        all_tasks.append((query, "JP"))

    print(f"[RSS] Fetching news from KR & JP ({len(all_tasks)} queries, last {hours_back}h) concurrently...")

    max_workers: int = min(len(all_tasks), 6)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_query = {
            executor.submit(fetch_single_query, q, c): (q, c) for q, c in all_tasks
        }

        for future in as_completed(future_to_query):
            query, country, entries = future.result()
            for entry in entries:
                raw_url: str = entry.get("link", "")
                url: str = clean_article_url(raw_url)
                if not url or url in seen_urls:
                    continue

                # Parse publication timestamp safely
                published_parsed = entry.get("published_parsed")
                if published_parsed:
                    pub_time = datetime.fromtimestamp(calendar.timegm(published_parsed), tz=timezone.utc)
                else:
                    pub_time = now

                # Verify article falls within the requested lookback window
                if pub_time >= time_threshold:
                    seen_urls.add(url)
                    source_name: str = entry.get("news_source") or entry.get("source", {}).get("title", "Unknown")
                    raw_articles.append({
                        "title": entry.get("title", "No Title"),
                        "link": url,
                        "source": source_name,
                        "published": pub_time.isoformat(),
                        "country": country,
                        "query_matched": query,
                        "description": entry.get("summary", "")
                    })

    # Sort articles newest first
    raw_articles.sort(key=lambda x: x["published"], reverse=True)
    print(f"[RSS] Ingested {len(raw_articles)} unique URL articles across South Korea and Japan.")

    # Apply algorithmic fuzzy title deduplication
    deduped_articles = cluster_and_deduplicate_articles(raw_articles, threshold=65)
    print(f"[RSS] After algorithmic clustering: {len(deduped_articles)} distinct event stories remain.")

    return deduped_articles


# ===========================================================================
# 5. Publisher Content Scraping & Metadata Enrichment
# ===========================================================================

def enrich_single_article(art: dict[str, Any]) -> dict[str, Any]:
    """
    Enriches a candidate article with its canonical publisher URL and extracted lead content
    (OpenGraph description, meta description, and first 3 article paragraphs).

    Args:
        art: Candidate article dictionary.

    Returns:
        Enriched article dictionary containing 'canonical_link' and 'full_snippet'.
    """
    canonical_url: str = resolve_canonical_url(art.get("link", ""))
    enriched: dict[str, Any] = dict(art)
    enriched["canonical_link"] = canonical_url

    # Inspect existing description
    clean_desc: str = re.sub(r"<[^>]+>", "", art.get("description", "")).strip()

    # If the RSS description is already substantial and not truncated, reuse it
    if len(clean_desc) > 120 and not clean_desc.endswith("..."):
        enriched["full_snippet"] = clean_desc
        return enriched

    # Otherwise, fetch publisher page to extract high-density metadata and body paragraphs
    try:
        headers = {
            "User-Agent": USER_AGENTS[0],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,ja-JP,ja;q=0.8,en-US;q=0.7,en;q=0.6"
        }
        resp = requests.get(canonical_url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, "html.parser")
            snippets: list[str] = []

            og_desc = soup.find("meta", property="og:description")
            meta_desc = soup.find("meta", attrs={"name": "description"})

            if og_desc and og_desc.get("content"):
                snippets.append(str(og_desc["content"]).strip())
            elif meta_desc and meta_desc.get("content"):
                snippets.append(str(meta_desc["content"]).strip())

            paragraphs = [p.get_text().strip() for p in soup.find_all("p") if len(p.get_text().strip()) > 30]
            if paragraphs:
                snippets.extend(paragraphs[:3])

            combined: str = " ".join(snippets).strip()
            if len(combined) > 40:
                enriched["full_snippet"] = combined[:1000]
                return enriched
    except Exception:
        pass

    # Fallback to existing description or title
    enriched["full_snippet"] = clean_desc if clean_desc else art.get("title", "")
    return enriched


def enrich_candidate_articles(
    articles: list[dict[str, Any]],
    max_workers: int = 6
) -> list[dict[str, Any]]:
    """
    Enriches candidate articles concurrently while preserving original ordering.

    Args:
        articles: List of selected candidate article dictionaries.
        max_workers: Maximum concurrent HTTP requests.

    Returns:
        List of enriched article dictionaries with canonical links and full snippets.
    """
    if not articles:
        return []

    enriched_list: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(len(articles), max_workers)) as executor:
        futures = [executor.submit(enrich_single_article, art) for art in articles]
        for f in as_completed(futures):
            try:
                enriched_list.append(f.result())
            except Exception as e:
                print(f"[Enricher] Warning: Failed to enrich article: {e}")

    # Maintain original order of candidates
    order_map = {art["link"]: i for i, art in enumerate(articles)}
    enriched_list.sort(key=lambda x: order_map.get(x["link"], 999))
    return enriched_list


# ===========================================================================
# Standalone CLI Verification
# ===========================================================================

if __name__ == "__main__":
    sample_articles = parse_and_filter_articles(hours_back=24)
    print(f"[RSS Test] Extracted {len(sample_articles)} articles.")
    if sample_articles:
        print(f"[RSS Test] First article sample:\n  Title: {sample_articles[0]['title']}\n  Link: {sample_articles[0]['link']}")
