import urllib.parse
import urllib.request
import urllib.error
import feedparser
import calendar
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.config import KOREAN_QUERIES, JAPANESE_QUERIES

def get_feed_articles(query, country_code):
    """
    Fetches articles from Google News RSS feed for a specific query and country.
    Uses rotating User-Agents and falls back to CORS proxies if direct requests are blocked (e.g. by Google Cloud IP restrictions).
    country_code: 'KR' (Korea) or 'JP' (Japan)
    """
    encoded_query = urllib.parse.quote(query)
    
    if country_code == 'KR':
        hl, gl = 'ko', 'KR'
    elif country_code == 'JP':
        hl, gl = 'ja', 'JP'
    else:
        raise ValueError("Invalid country_code. Must be 'KR' or 'JP'.")
        
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl={hl}&gl={gl}&ceid={gl}:{hl}"
    
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0'
    ]
    
    # 1. Try direct fetching
    ua = user_agents[0]
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read()
            feed = feedparser.parse(xml_data)
            # Check for standard Google block responses parsed as HTML
            if feed.entries:
                return feed.entries
            # If we parsed it but got 0 entries, it might be due to 503 block page parsed as empty feed
            status_code = getattr(feed, 'status', 200)
            if status_code in (403, 429, 503) or feed.bozo:
                print(f"Direct fetch got blocked/empty (status: {status_code}, bozo: {feed.bozo}) for query '{query}'. Trying proxies...")
            else:
                # Valid response but actually no search results matching the query in the time window
                return []
    except urllib.error.HTTPError as e:
        print(f"Direct fetch failed with HTTPError {e.code} for query '{query}' in {country_code}. Trying proxies...")
    except Exception as e:
        print(f"Direct fetch failed with error '{e}' for query '{query}' in {country_code}. Trying proxies...")
            
    # 2. Try via corsproxy.io proxy fallback
    print(f"Attempting fallback via corsproxy.io for query '{query}'...")
    try:
        proxy_url = f"https://corsproxy.io/?{urllib.parse.quote(url)}"
        req = urllib.request.Request(
            proxy_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            xml_data = response.read()
            feed = feedparser.parse(xml_data)
            if feed.entries:
                print(f"Successfully fetched query '{query}' via corsproxy.io!")
                return feed.entries
    except Exception as e:
        print(f"Fallback via corsproxy.io failed: {e}")
        
    # 3. Try via allorigins.win proxy fallback
    print(f"Attempting fallback via allorigins.win for query '{query}'...")
    try:
        proxy_url = f"https://api.allorigins.win/raw?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(
            proxy_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            xml_data = response.read()
            feed = feedparser.parse(xml_data)
            if feed.entries:
                print(f"Successfully fetched query '{query}' via allorigins.win!")
                return feed.entries
    except Exception as e:
        print(f"Fallback via allorigins.win failed: {e}")
        
    print(f"Error: All attempts failed to fetch RSS feed for query '{query}' in {country_code}.")
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
    
    max_workers = min(len(all_tasks), 15)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_query = {
            executor.submit(fetch_single_query, q, c): (q, c) for q, c in all_tasks
        }
        
        for future in as_completed(future_to_query):
            query, country, entries = future.result()
            for entry in entries:
                url = entry.get('link')
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
                    unique_articles.append({
                        'title': entry.get('title', 'No Title'),
                        'link': url,
                        'source': entry.get('source', {}).get('title', 'Unknown'),
                        'published': pub_time.isoformat(),
                        'country': country,
                        'query_matched': query,
                        'description': entry.get('summary', '') # summary often contains description in RSS
                    })
                
    # Sort all unique articles by publication date, newest first
    unique_articles.sort(key=lambda x: x['published'], reverse=True)
    
    print(f"Fetched {len(unique_articles)} total unique articles from Korea and Japan (sorted by date).")
    return unique_articles

if __name__ == "__main__":
    # Quick debug run
    articles = parse_and_filter_articles(hours_back=48)
    print(f"Sample article: {articles[0] if articles else 'None'}")
