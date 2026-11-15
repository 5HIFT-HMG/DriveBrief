from contextlib import closing
import json
import threading

from .news_repository import crawler


class NewsCollector:
    def __init__(self, repository, interval=300):
        if type(interval) is not int or interval < 300:
            raise ValueError('news_interval_must_be_at_least_300')
        self.repository = repository
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None
        self.last_error = None

    def collect_once(self):
        config = json.loads(self.repository.config_path.read_text(encoding='utf-8'))
        feeds = config.get('feeds', [])
        if not feeds or any(f.get('category') not in crawler.CATEGORIES or not f.get('source')
                            or not crawler.safe_url(f.get('url')) for f in feeds):
            raise ValueError('invalid_feed_configuration')
        self.repository.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(crawler.connect(self.repository.db_path)) as db:
            successes = crawler.collect(db, feeds)
        from .shared_backend import sync_local_reviews
        try:
            self.review_sync = sync_local_reviews()
        except Exception as error:
            self.review_sync = {'error': type(error).__name__}
        return successes

    def run(self):
        while not self.stop_event.is_set():
            try:
                successes = self.collect_once()
                self.last_error = None if successes else 'all_feeds_failed'
            except Exception as error:
                self.last_error = type(error).__name__
            if self.stop_event.wait(self.interval):
                break

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, name='drivebrief-rss', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1)

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive() and not self.stop_event.is_set()
