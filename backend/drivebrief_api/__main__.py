import argparse
import os
import uvicorn
from .app import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local-only DriveBrief demo API")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--news-interval", type=int, default=300)
    parser.add_argument("--no-news-collection", action="store_true")
    args = parser.parse_args()
    if args.news_interval < 300:
        parser.error('--news-interval must be at least 300 seconds')
    # No host switch: this command never publishes the server externally.
    api = create_app(demo_enabled=os.getenv('DRIVEBRIEF_DEMO_ENABLED') == '1',
                     collect_news=not args.no_news_collection, news_interval=args.news_interval)
    uvicorn.run(api, host="127.0.0.1", port=args.port,
                access_log=False, log_level="warning")
