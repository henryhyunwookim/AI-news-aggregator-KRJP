import urllib.parse
import urllib.request
import urllib.error
import feedparser
import calendar
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.config import KOREAN_QUERIES, JAPANESE_QUERIES

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0'
]

def clean_article_url(raw_url):
    """
    Extracts the underlying target URL if wrapped in a Bing or Google redirect.
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
    and removes duplicates. Returns a list of processed articles.
    """
    now = datetime.now(timezone.utc)
    time_threshold = now - timedelta(hours=hours_back)
    
    seen_urls = set()
    unique_articles = []
    
    # Helper to fetch single query
    def fetch_single_query(query, country_code):
        return query, country_code, get_feed_articles(query, country_code)

    all_tasks = []
    for query in KOREAN_QUERIES:
        all_tasks.append((query, 'KR'))
    for query in JAPANESE_QUERIES:
        all_tasks.append((query, 'JP'))
        
    print(f"Fetching news from Korea and Japan (within last {hours_back} hours) concurrently...")
    
    # Use max_workers=6 to avoid aggressive bursting on search endpoints
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
                    # Fallback if published_parsed not available
                    pub_time = now
                    
                if pub_time >= time_threshold:
                    seen_urls.add(url)
                    source_name = entry.get('news_source') or entry.get('source', {}).get('title', 'Unknown')
                    unique_articles.append({
                        'title': entry.get('title', 'No Title'),
                        'link': url,
                        'source': source_name,
                        'published': pub_time.isoformat(),
                        'country': country,
                        'query_matched': query,
                        'description': entry.get('summary', '')
                    })
                
    # Sort all unique articles by publication date, newest first
    unique_articles.sort(key=lambda x: x['published'], reverse=True)
    
    print(f"Fetched {len(unique_articles)} total unique articles from Korea and Japan (sorted by date).")
    return unique_articles

if __name__ == "__main__":
    # Quick debug run
    articles = parse_and_filter_articles(hours_back=48)
    print(f"Sample article: {articles[0] if articles else 'None'}")
