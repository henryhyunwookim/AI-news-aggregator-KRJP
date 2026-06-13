import urllib.parse
import feedparser
import calendar
import time
from datetime import datetime, timezone, timedelta
from src.config import KOREAN_QUERIES, JAPANESE_QUERIES

def get_feed_articles(query, country_code):
    """
    Fetches articles from Google News RSS feed for a specific query and country.
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
    
    try:
        feed = feedparser.parse(url)
        return feed.entries
    except Exception as e:
        print(f"Error fetching feed for query '{query}' in {country_code}: {e}")
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
    
    # Process Korean feeds
    print(f"Fetching news from Korea (within last {hours_back} hours)...")
    for query in KOREAN_QUERIES:
        entries = get_feed_articles(query, 'KR')
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
                    'country': 'KR',
                    'query_matched': query,
                    'description': entry.get('summary', '') # summary often contains description in RSS
                })
                
    # Process Japanese feeds
    print(f"Fetching news from Japan (within last {hours_back} hours)...")
    for query in JAPANESE_QUERIES:
        entries = get_feed_articles(query, 'JP')
        for entry in entries:
            url = entry.get('link')
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
                unique_articles.append({
                    'title': entry.get('title', 'No Title'),
                    'link': url,
                    'source': entry.get('source', {}).get('title', 'Unknown'),
                    'published': pub_time.isoformat(),
                    'country': 'JP',
                    'query_matched': query,
                    'description': entry.get('summary', '')
                })
                
    print(f"Fetched {len(unique_articles)} total unique articles from Korea and Japan.")
    return unique_articles

if __name__ == "__main__":
    # Quick debug run
    articles = parse_and_filter_articles(hours_back=48)
    print(f"Sample article: {articles[0] if articles else 'None'}")
