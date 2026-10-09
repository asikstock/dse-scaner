#!/usr/bin/env python3
"""
Collect stock-related headlines from Bangladesh financial RSS feeds
into docs/data/news.json.

Sources include:
  - DSE-নির্দিষ্ট ও ব্রোকারেজ research feeds
  - বাংলাদেশি ফাইন্যান্সিয়াল নিউজ সাইট (বাংলা + ইংরেজি)
  - আন্তর্জাতিক নিউজ সাইটের Bangladesh business section
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser

# ═══════════════════════════════════════════════════════════════
# ১. RSS ফিড — DSE-নির্দিষ্ট, ব্রোকারেজ, বাংলাদেশি ফাইন্যান্স
# ═══════════════════════════════════════════════════════════════

DEFAULT_FEEDS = ",".join([
    # ── DSE-নির্দিষ্ট / স্টক এক্সচেঞ্জ ──
    "https://www.dsebd.org/news_feed.php",              # DSE নিজের feed (থাকলে)
    "https://orthosongbad.com/sharemarket/feed/",       # Orthosongbad — পুঁজিবাজার বিভাগ
    "https://orthosongbad.com/feed/",                   # Orthosongbad — সব

    # ── বাংলাদেশি ফাইন্যান্সিয়াল নিউজ (বাংলা) ──
    "https://businessbarta.net/feed/",                  # Business Barta
    "https://businessbarta.net/tag/শেয়ারবাজার/feed/",   # শুধু শেয়ারবাজার ট্যাগ
    "https://www.ittefaq.com.bd/feed/",                 # ইত্তেফাক (ব্যবসা-বাণিজ্য)
    "https://www.bd-pratidin.com/economy/feed/",        # বাংলাদেশ প্রতিদিন — অর্থনীতি

    # ── বাংলাদেশি ফাইন্যান্সিয়াল নিউজ (ইংরেজি) ──
    "https://www.thedailystar.net/business/rss.xml",    # Daily Star Business
    "https://www.thedailystar.net/business/banks/rss.xml",  # Daily Star Banks
    "https://www.dhakatribune.com/feed",                # Dhaka Tribune
    "https://www.newagebd.net/feed",                    # New Age BD
    "https://en.prothomalo.com/feed",                   # Prothom Alo English
    "https://www.tbsnews.net/rss.xml",                  # The Business Standard
    "https://bdnews24.com/?widgetName=rssfeed&widgetId=1150&getXmlFeed=true",  # bdnews24 Business

    # ── ব্রোকারেজ হাউস research (থাকলে) ──
    "https://www.bracepl.com/feed/",                    # BRAC EPL (থাকলে)
    "https://securities.idlc.com/feed/",                # IDLC Securities (থাকলে)
    "https://islamibanksecurities.com/feed/",           # Islami Bank Securities (থাকলে)
])

RSS_FEEDS = [
    url.strip()
    for url in os.getenv("NEWS_RSS_FEEDS", DEFAULT_FEEDS).split(",")
    if url.strip()
]

# ═══════════════════════════════════════════════════════════════
# ২. prices.csv থেকে অটো সিম্বল লোড
# ═══════════════════════════════════════════════════════════════

def _load_symbols_from_prices():
    """data/prices.csv থেকে সব সিম্বল পড়ি। না পেলে fallback।"""
    syms = set()
    for p in ("data/prices.csv", "docs/data/prices.csv"):
        path = Path(p)
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as fh:
                header = [h.strip().strip('"').upper()
                          for h in fh.readline().split(",")]
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

# ═══════════════════════════════════════════════════════════════
# ৩. বাংলা + ইংরেজি alias (কোম্পানির পূর্ণ নাম)
# ═══════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════
# ৪. ফাইন্যান্স কি-ওয়ার্ড (না থাকলে খবর নেওয়া হবে না)
# ═══════════════════════════════════════════════════════════════

FINANCE_KEYWORDS = [
    # ইংরেজি
    "share", "stock", "shares", "stocks", "equity", "dividend", "profit",
    "loss", "revenue", "earnings", "quarter", "annual", "agm", "egm",
    "board", "bonus", "rights", "ipo", "dse", "cse", "bsec",
    "stock exchange", "market cap", "market capitalization", "trading",
    "listed", "eps", "nav", "loan", "credit", "interest rate", "bank",
    "insurance", "mutual fund", "investment", "investor", "broker",
    "securities", "finance", "financial", "capital market",
    # বাংলা
    "শেয়ার", "স্টক", "বাজার", "মুনাফা", "লাভ", "ক্ষতি", "লভ্যাংশ",
    "বোনাস", "ডিভিডেন্ড", "বিনিয়োগ", "পুঁজিবাজার", "শেয়ারবাজার",
    "সূচক", "লেনদেন", "আয়", "কোয়ার্টার", "বার্ষিক", "আর্থিক",
    "নিট লাভ", "নিট ক্ষতি", "পর্ষদ", "বোর্ড", "এজিএম", "ইজিএম",
    "ব্রোকারেজ", "আইপিও", "ডিএসই", "সিএসই", "বিএসইসি",
]


def _has_finance_context(title, summary):
    """টাইটেল/সামারিতে ফাইন্যান্স-সম্পর্কিত শব্দ আছে কি?"""
    blob = f"{title} {summary}".lower()
    return any(kw.lower() in blob for kw in FINANCE_KEYWORDS)


# খুব সাধারণ শব্দ যেগুলো alias হিসেবে false positive দেয়
GENERIC_ALIASES_TO_SKIP = {
    "OLYMPIC":   {"Olympic", "অলিম্পিক"},
    "MARICO":    {"Marico", "ম্যারিকো"},
    "RENATA":    {"Renata", "রেনাটা"},
    "ROBI":      {"Robi", "রবি"},
    "BERGERPBL": {"Berger", "বার্জার"},
}

# ═══════════════════════════════════════════════════════════════
# ৫. আউটপুট পাথ
# ═══════════════════════════════════════════════════════════════

OUTPUT_PATHS = [Path("docs/data/news.json"), Path("data/news.json")]
MAX_ITEMS_PER_FEED = 100

# ═══════════════════════════════════════════════════════════════
# ৬. সহায়ক ফাংশন
# ═══════════════════════════════════════════════════════════════

def clean_text(value):
    """HTML স্ট্রিপ করে ও হোয়াইটস্পেস নরমালাইজ করে।"""
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def entry_date(entry):
    """entry থেকে তারিখ বের করে ISO ফরম্যাটে দেয়।"""
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
    """
    ইংরেজি সিম্বল ও alias (বাংলা/ইংরেজি) — দুইভাবে ম্যাচ করি।
    তবে শুধু ফাইন্যান্সিয়াল কনটেক্সট থাকলে।
    """
    # ১. ফাইন্যান্স কি-ওয়ার্ড না থাকলে সম্পূর্ণ বাদ
    if not _has_finance_context(title, summary):
        return []

    searchable = f"{title} {summary}".upper()
    raw_blob = f"{title} {summary}"
    matched = []

    for sym in TRACKED_SYMBOLS:
        # ক. ইংরেজি সিম্বল word-boundary তে
        if re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])", searchable):
            matched.append(sym)
            continue

        # খ. alias ম্যাচ — তবে জেনেরিক শব্দ বাদ
        aliases = SYMBOL_ALIASES.get(sym, [])
        skip = GENERIC_ALIASES_TO_SKIP.get(sym, set())
        for alias in aliases:
            if alias in skip:
                continue
            if alias.upper() in searchable or alias in raw_blob:
                matched.append(sym)
                break

    return matched


# ═══════════════════════════════════════════════════════════════
# ৭. মূল ফাংশন
# ═══════════════════════════════════════════════════════════════

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
    print(f"RSS feeds configured: {len(RSS_FEEDS)}")
    save_news(fetch_from_rss())
