#!/usr/bin/env python3
"""Collect stock-related headlines from configured RSS feeds into docs/data/news.json."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser

# Add/remove RSS feeds as needed. Feed URLs may be overridden via NEWS_RSS_FEEDS.
RSS_FEEDS = [
    url.strip() for url in os.getenv(
        "NEWS_RSS_FEEDS",
        "https://businessbarta.net/feed/,https://www.ittefaq.com.bd/feed/",
    ).split(",") if url.strip()
]
# Keep this list aligned with the symbols relevant to your scanner.
TRACKED_SYMBOLS = [
    "GP", "BEXIMCO", "SQURPHARMA",
]
OUTPUT_PATH = Path("docs/data/news.json")
MAX_ITEMS_PER_FEED = 100


def clean_text(value):
    """Strip HTML and normalize whitespace from RSS text fields."""
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def entry_date(entry):
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            return str(value)
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            from time import mktime
            return datetime.fromtimestamp(mktime(parsed), timezone.utc).isoformat()
        except (OverflowError, TypeError, ValueError):
            pass
    return datetime.now(timezone.utc).isoformat()


def fetch_from_rss():
    items = {}
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url, request_headers={"User-Agent": "DSE-News-Scanner/1.0"})
            if getattr(feed, "bozo", False) and not feed.entries:
                print(f"Warning: unable to parse feed {feed_url}: {getattr(feed, 'bozo_exception', 'unknown error')}")
                continue
            source_name = clean_text(feed.feed.get("title")) or urlparse(feed_url).netloc
            for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
                title = clean_text(entry.get("title"))
                link = str(entry.get("link") or "").strip()
                if not title or not link:
                    continue
                summary = clean_text(entry.get("summary") or entry.get("description"))
                searchable = f"{title} {summary}".upper()
                matched = [sym for sym in TRACKED_SYMBOLS if re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])", searchable)]
                for sym in matched:
                    item = {
                        "date": entry_date(entry),
                        "symbol": sym,
                        "title": title,
                        "summary": summary[:600],
                        "source": feed_url,
                        "source_name": source_name,
                        "link": link,
                    }
                    items[(sym, link)] = item
        except Exception as exc:  # One broken feed should not prevent other feeds from being read.
            print(f"Error fetching {feed_url}: {exc}")
    return sorted(items.values(), key=lambda item: item["date"], reverse=True)


def save_news(news_list):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = OUTPUT_PATH.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(news_list, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp_path.replace(OUTPUT_PATH)
    print(f"Saved {len(news_list)} news items to {OUTPUT_PATH}.")


if __name__ == "__main__":
    save_news(fetch_from_rss())
