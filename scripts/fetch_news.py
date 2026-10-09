#!/usr/bin/env python3
"""Collect stock-related headlines from configured RSS feeds into docs/data/news.json."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser

# ── ১. কাজ করা বাংলাদেশি নিউজ RSS (NEWS_RSS_FEEDS env দিয়ে override করা যাবে) ──
DEFAULT_FEEDS = ",".join([
    "https://www.thedailystar.net/business/rss.xml",
    "https://www.dhakatribune.com/feed",
    "https://bdnews24.com/?widgetName=rssfeed&widgetId=1150&getXmlFeed=true",
    "https://www.newagebd.net/feed",
    "https://en.prothomalo.com/feed",
    "https://www.tbsnews.net/rss.xml",
    "https://www.dailystar.net/business/banks/rss.xml",
])
RSS_FEEDS = [
    url.strip()
    for url in os.getenv("NEWS_RSS_FEEDS", DEFAULT_FEEDS).split(",")
    if url.strip()
]

# ── ২. prices.csv থেকে সব সিম্বল অটো লোড ──
def _load_symbols_from_prices():
    syms = set()
    for p in ("data/prices.csv", "docs/data/prices.csv"):
        path = Path(p)
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as fh:
                header = [h.strip().strip('"').upper() for h in fh.readline().split(",")]
                idx = next(
                    (i for i, h in enumerate(header)
                     if h in ("TRADING CODE", "CODE", "SYMBOL")),
                    None,
                )
                if idx is None:
                    continue
                for line in fh:
                    parts = line.split(",")
                    if len(parts) > idx:
                        s = parts[idx].strip().strip('"').upper()
                        if s and 1 < len(s) <= 20 and re.fullmatch(r"[A-Z0-9]+", s):
                            syms.add(s)
            break
        except Exception as exc:
            print(f"warn: {p}: {exc}")
    return sorted(syms)

TRACKED_SYMBOLS = _load_symbols_from_prices() or ["GP", "BEXIMCO", "SQURPHARMA"]

# ── ৩. বাংলা + ইংরেজি alias ──
SYMBOL_ALIASES = {
    "GP":         ["Grameenphone", "গ্রামীণফোন", "গ্রামীণ ফোন"],
    "BEXIMCO":    ["বেক্সিমকো"],
    "SQURPHARMA": ["Square Pharma", "স্কয়ার ফার্মা", "স্কয়ার ফার্মাসিউটিক্যাল"],
    "BRACBANK":   ["BRAC Bank", "ব্র্যাক ব্যাংক"],
    "CITYBANK":   ["City Bank", "সিটি ব্যাংক"],
    "ISLAMIBANK": ["Islami Bank", "ইসলামী ব্যাংক"],
    "RENATA":     ["Renata", "রেনাটা"],
    "BXPHARMA":   ["Beacon Pharma", "বিকন ফার্মা"],
    "WALTONHIL":  ["Walton", "ওয়ালটন"],
    "BERGERPBL":  ["Berger", "বার্জার"],
    "OLYMPIC":    ["Olympic", "অলিম্পিক"],
    "MARICO":     ["Marico", "ম্যারিকো"],
    "ROBI":       ["Robi", "রবি"],
    "BATBC":      ["British American Tobacco", "ব্রিটিশ আমেরিকান টোব্যাকো"],
    "UPGDCL":     ["United Power", "ইউনাইটেড পাওয়ার"],
    "SUMITPOWER": ["Summit Power", "সামিট পাওয়ার"],
    "TITASGAS":   ["Titas Gas", "তিতাস গ্যাস"],
    "POWERGRID":  ["Power Grid", "পাওয়ার গ্রিড"],
    "BSCCL":      ["Bangladesh Submarine", "বাংলাদেশ সাবমেরিন"],
}

# ── ৪. আউটপুট (দুই জায়গায় সেভ হবে) ──
OUTPUT_PATHS = [Path("docs/data/news.json"), Path("data/news.json")]
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

def _match_symbols(title, summary):
    """ইংরেজি সিম্বল ও alias (বাংলা/ইংরেজি) — দুইভাবে ম্যাচ করি।"""
    searchable = f"{title} {summary}".upper()
    raw_blob = f"{title} {summary}"
    matched = []
    for sym in TRACKED_SYMBOLS:
        # ক. ইংরেজি সিম্বল word-boundary তে
        if re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])", searchable):
            matched.append(sym)
            continue
        # খ. alias ম্যাচ
        for alias in SYMBOL_ALIASES.get(sym, []):
            if alias.upper() in searchable or alias in raw_blob:
                matched.append(sym)
                break
    return matched

def fetch_from_rss():
    items = {}
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(
                feed_url,
                request_headers={"User-Agent": "DSE-News-Scanner/1.0"},
            )
            if getattr(feed, "bozo", False) and not feed.entries:
                print(f"Warning: unable to parse feed {feed_url}: "
                      f"{getattr(feed, 'bozo_exception', 'unknown error')}")
                continue
            source_name = clean_text(feed.feed.get("title")) or urlparse(feed_url).netloc
            print(f"{feed_url} → {len(feed.entries)} entries")
            for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
                title = clean_text(entry.get("title"))
                link = str(entry.get("link") or "").strip()
                if not title or not link:
                    continue
                summary = clean_text(entry.get("summary") or entry.get("description"))
                for sym in _match_symbols(title, summary):
                    items[(sym, link)] = {
                        "date": entry_date(entry),
                        "symbol": sym,
                        "title": title,
                        "summary": summary[:600],
                        "source": feed_url,
                        "source_name": source_name,
                        "link": link,
                    }
        except Exception as exc:
            print(f"Error fetching {feed_url}: {exc}")
    return sorted(items.values(), key=lambda item: item["date"], reverse=True)

def save_news(news_list):
    payload = json.dumps(news_list, ensure_ascii=False, indent=2) + "\n"
    for path in OUTPUT_PATHS:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".json.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
        temp_path.replace(path)
        print(f"Saved {len(news_list)} news items to {path}.")

if __name__ == "__main__":
    print(f"Tracked symbols: {len(TRACKED_SYMBOLS)}")
    save_news(fetch_from_rss())
