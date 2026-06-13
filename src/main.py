import argparse
import sys
from datetime import datetime, timezone
import zoneinfo
from src.config import TIMEZONE
from src.rss_parser import parse_and_filter_articles
from src.llm_filter import NewsFilter
from src.email_sender import EmailSender
from src.auth import authenticate_gmail

def main(hours_back=24):
    execution_start = datetime.now()
    error_message = None
    stats = {
        'total_fetched': 0,
        'relevant_count': 0,
        'kr_count': 0,
        'jp_count': 0
    }
    
    try:
        # Determine current date string in local timezone
        try:
            tz = zoneinfo.ZoneInfo(TIMEZONE)
            local_now = datetime.now(tz)
        except Exception as tz_err:
            print(f"Warning: Could not load timezone {TIMEZONE} ({tz_err}). Falling back to local time.")
            local_now = datetime.now()
            
        date_str = local_now.strftime("%B %d, %Y")
        print(f"--- Starting AIFOD AI News Aggregator for {date_str} ---")
        
        # 1. Authenticate Gmail first to verify access before API processing
        print("Checking Gmail authentication...")
        creds = authenticate_gmail()
        
        # 2. Fetch articles from Korea & Japan RSS feeds
        print(f"Fetching RSS feeds for the last {hours_back} hours...")
        fetched_articles = parse_and_filter_articles(hours_back=hours_back)
        stats['total_fetched'] = len(fetched_articles)
        
        if not fetched_articles:
            print("No articles fetched from RSS feeds.")
            relevant_articles = []
        else:
            # 3. Filter and translate articles using Gemini
            print("Filtering and translating articles via Gemini...")
            news_filter = NewsFilter()
            relevant_articles = news_filter.filter_articles(fetched_articles)
            
        stats['relevant_count'] = len(relevant_articles)
        stats['kr_count'] = sum(1 for a in relevant_articles if a['country'] == 'KR')
        stats['jp_count'] = sum(1 for a in relevant_articles if a['country'] == 'JP')
        
        print(f"Filtering complete. Found {stats['relevant_count']} relevant articles.")
        for i, art in enumerate(relevant_articles, 1):
            print(f"  {i}. [{art['country']}] {art['english_title']} ({art['source']})")
            
        # 4. Format and send the daily digest email
        print("Constructing HTML digest and sending email...")
        sender = EmailSender(creds)
        sender.send_digest_email(relevant_articles, stats['total_fetched'], date_str)
        print("Aggregator run successfully completed!")
        
    except Exception as e:
        error_message = str(e)
        print(f"Error during aggregator execution: {error_message}")
        
    return {
        'success': error_message is None,
        'stats': stats,
        'error': error_message
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AIFOD AI News Aggregator - Korea & Japan")
    parser.add_argument("--auth", action="store_true", help="Run interactive Gmail authentication flow")
    parser.add_argument("--hours", type=int, default=24, help="Fetch news from the last N hours (default 24)")
    args = parser.parse_args()
    
    if args.auth:
        print("Starting interactive authentication...")
        authenticate_gmail()
        print("Authentication check complete.")
        sys.exit(0)
        
    result = main(hours_back=args.hours)
    if not result['success']:
        sys.exit(1)
