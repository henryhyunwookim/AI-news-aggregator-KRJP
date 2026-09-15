import urllib.parse
import urllib.request
import urllib.error
import feedparser
import calendar
import time
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from rapidfuzz import fuzz
from googlenewsdecoder import gnewsdecoder
from src.config import KOREAN_QUERIES, JAPANESE_QUERIES

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0'
]

def clean_article_url(raw_url):
    """
    Extracts the underlying target URL if wrapped in a Bing or basic redirect.
    """
    if not raw_url:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw_url)
        if "bing.com" in parsed.netloc and "url" in parsed.query:
            qs = urllib.parse.parse_qs(parsed.query)
            target = qs.get("url", [raw_url])[0]
            return target
    except Exception:
        pass
    return raw_url

def resolve_canonical_url(url):
    """
    Resolves Google News (CBMi...) or Bing redirect links into direct publisher URLs.
    """
    if not url:
        return ""
    clean_url = clean_article_url(url)
    if "news.google.com" in clean_url:
        try:
            res = gnewsdecoder(clean_url, interval=0.1)
            if res.get("status") and res.get("decoded_url"):
                return res["decoded_url"]
        except Exception:
            pass
    return clean_url

def normalize_title(title):
    """
    Normalizes article title for fuzzy event clustering.
    Strips brackets, trailing publisher tags (- 로이슈, | 연합뉴스), and punctuation.
    """
    if not title:
        return ""
    # Strip bracketed prefixes/tags like [포토], (종합), 【速報】
    t = re.sub(r'\[.*?\]|\(.*?\)|【.*?】', ' ', title)
    # Strip common trailing publisher suffixes: - 로이슈, | 연합뉴스, - 日本経済新聞
    t = re.sub(r'[-|–—·]\s*[\w\.\s]+$', ' ', t)
    # Strip special punctuation
    t = re.sub(r'[^\w\s]', ' ', t)
    # Normalize whitespace and case
    return re.sub(r'\s+', ' ', t).strip().lower()

def cluster_and_deduplicate_articles(articles, threshold=65):
    """
    Groups articles into event clusters using normalized fuzzy title similarity.
    For each cluster, retains the single most representative article (prioritizing
    real content length and recent publication date).
    """
    if not articles:
        return []
        
    clusters = [] # list of article lists
    
    for art in articles:
        norm_title = normalize_title(art.get('title', ''))
        matched_cluster = None
        
        for cluster in clusters:
            for existing_art in cluster:
                # Group only within the same country
                if art['country'] == existing_art['country']:
                    existing_norm = normalize_title(existing_art.get('title', ''))
                    sim = fuzz.token_set_ratio(norm_title, existing_norm)
                    if sim >= threshold:
                        matched_cluster = cluster
                        break
            if matched_cluster:
                break
                
        if matched_cluster:
            matched_cluster.append(art)
        else:
            clusters.append([art])
            
    # For each cluster, pick the article with the longest real (non-HTML) description
    deduped = []
    for cluster in clusters:
        def article_score(a):
            desc_clean = re.sub(r'<[^>]+>', '', a.get('description', '')).strip()
            # prefer articles with real description and reputable publisher
            return len(desc_clean)
        best_art = max(cluster, key=article_score)
        deduped.append(best_art)
        
    return deduped

def fetch_google_rss(query, country_code):
    """
    Fetches articles directly from Google News RSS feed.
    """
    encoded_query = urllib.parse.quote(query)
    if country_code == 'KR':
        hl, gl = 'ko', 'KR'
    elif country_code == 'JP':
        hl, gl = 'ja', 'JP'
    else:
        raise ValueError("Invalid country_code. Must be 'KR' or 'JP'.")
        
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl={hl}&gl={gl}&ceid={gl}:{hl}"
    
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': USER_AGENTS[0],
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'Accept-Language': 'ko-KR,ko;q=0.9,ja-JP,ja;q=0.8,en-US;q=0.7,en;q=0.6'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            feed = feedparser.parse(xml_data)
            if feed.entries and not getattr(feed, 'bozo', False):
                return feed.entries
            if feed.entries:
                return feed.entries
    except Exception:
        # Expected when running on cloud datacenters (e.g. GCP 503)
        pass
    return []

def fetch_bing_rss(query, country_code):
    """
    Fetches articles from Bing News RSS feed. Highly reliable on Cloud Run and datacenter IPs.
    """
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.bing.com/news/search?q={encoded_query}&format=rss"
    
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': USER_AGENTS[0],
            'Accept': 'application/rss+xml, application/xml, text/xml, */*'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            feed = feedparser.parse(xml_data)
            if feed.entries:
                return feed.entries
    except Exception as e:
        print(f"Bing RSS fetch error for '{query}' in {country_code}: {e}")
    return []

def get_feed_articles(query, country_code):
    """
    Fetches articles using a multi-engine fallback:
    1. Attempts direct Google News RSS
    2. Seamlessly falls back to Bing News RSS if Google blocks or returns empty
    """
    # 1. Try Google News RSS
    entries = fetch_google_rss(query, country_code)
    if entries:
        return entries
        
    # 2. Resilient fallback: Bing News RSS
    entries = fetch_bing_rss(query, country_code)
    if entries:
        return entries
        
    return []

def parse_and_filter_articles(hours_back=24):
    """
    Fetches articles for all Korean and Japanese queries, filters by time window,
    removes duplicate URLs, and clusters duplicate press releases/events via RapidFuzz.
    """
    now = datetime.now(timezone.utc)
    time_threshold = now - timedelta(hours=hours_back)
    
    seen_urls = set()
    raw_articles = []
    
    # Helper to fetch single query
    def fetch_single_query(query, country_code):
        return query, country_code, get_feed_articles(query, country_code)

    all_tasks = []
    for query in KOREAN_QUERIES:
        all_tasks.append((query, 'KR'))
    for query in JAPANESE_QUERIES:
        all_tasks.append((query, 'JP'))
        
    print(f"Fetching news from Korea and Japan (within last {hours_back} hours) concurrently...")
    
    max_workers = min(len(all_tasks), 6)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_query = {
            executor.submit(fetch_single_query, q, c): (q, c) for q, c in all_tasks
        }
        
        for future in as_completed(future_to_query):
            query, country, entries = future.result()
            for entry in entries:
                raw_url = entry.get('link')
                url = clean_article_url(raw_url)
                if not url or url in seen_urls:
                    continue
                    
                # Parse published date
                published_parsed = entry.get('published_parsed')
                if published_parsed:
                    pub_time = datetime.fromtimestamp(calendar.timegm(published_parsed), tz=timezone.utc)
                else:
                    pub_time = now
                    
                if pub_time >= time_threshold:
                    seen_urls.add(url)
                    source_name = entry.get('news_source') or entry.get('source', {}).get('title', 'Unknown')
                    raw_articles.append({
                        'title': entry.get('title', 'No Title'),
                        'link': url,
                        'source': source_name,
                        'published': pub_time.isoformat(),
                        'country': country,
                        'query_matched': query,
                        'description': entry.get('summary', '')
                    })
                
    # Sort by publication date, newest first
    raw_articles.sort(key=lambda x: x['published'], reverse=True)
    print(f"Fetched {len(raw_articles)} raw unique URL articles from Korea and Japan.")
    
    # Algorithmic clustering deduplication (eliminate identical press releases across outlets)
    deduped_articles = cluster_and_deduplicate_articles(raw_articles, threshold=65)
    print(f"After algorithmic title deduplication: {len(deduped_articles)} distinct event stories remain.")
    
    return deduped_articles

def enrich_single_article(art):
    """
    Enriches candidate article with canonical publisher URL and real text
    (meta description / og:description / lead paragraphs).
    """
    canonical_url = resolve_canonical_url(art['link'])
    enriched = dict(art)
    enriched['canonical_link'] = canonical_url
    
    # Extract clean existing description
    clean_desc = re.sub(r'<[^>]+>', '', art.get('description', '')).strip()
    
    # If existing description is already substantial (> 120 chars), keep it
    if len(clean_desc) > 120 and not clean_desc.endswith('...'):
        enriched['full_snippet'] = clean_desc
        return enriched
        
    # Otherwise, fetch publisher page to extract og:description and lead text
    try:
        headers = {
            'User-Agent': USER_AGENTS[0],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,ja-JP,ja;q=0.8,en-US;q=0.7,en;q=0.6'
        }
        resp = requests.get(canonical_url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'html.parser')
            snippets = []
            
            og_desc = soup.find('meta', property='og:description')
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            
            if og_desc and og_desc.get('content'):
                snippets.append(og_desc['content'].strip())
            elif meta_desc and meta_desc.get('content'):
                snippets.append(meta_desc['content'].strip())
                
            paras = [p.get_text().strip() for p in soup.find_all('p') if len(p.get_text().strip()) > 30]
            if paras:
                snippets.extend(paras[:3])
                
            combined = " ".join(snippets).strip()
            if len(combined) > 40:
                enriched['full_snippet'] = combined[:1000]
                return enriched
    except Exception:
        pass
        
    enriched['full_snippet'] = clean_desc if clean_desc else art.get('title', '')
    return enriched

def enrich_candidate_articles(articles, max_workers=6):
    """
    Enriches a batch of candidate articles concurrently.
    """
    if not articles:
        return []
    enriched_list = []
    with ThreadPoolExecutor(max_workers=min(len(articles), max_workers)) as executor:
        futures = [executor.submit(enrich_single_article, art) for art in articles]
        for f in as_completed(futures):
            try:
                enriched_list.append(f.result())
            except Exception as e:
                print(f"Error enriching candidate article: {e}")
    # Maintain original order
    order_map = {art['link']: i for i, art in enumerate(articles)}
    enriched_list.sort(key=lambda x: order_map.get(x['link'], 999))
    return enriched_list

if __name__ == "__main__":
    # Quick debug run
    articles = parse_and_filter_articles(hours_back=24)
    print(f"Sample article: {articles[0] if articles else 'None'}")

