#!/usr/bin/env python3
"""
Collect stock-related headlines from Bangladesh financial RSS feeds.
Saves symbol-matched news AND market-wide news (symbol="MARKET").
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser

# ═══════════════════════════════════════════════════════════════
# ১. RSS ফিড — বেশি উৎস, বেশি খবর
# ═══════════════════════════════════════════════════════════════

DEFAULT_FEEDS = ",".join([
    # ── বাংলা — পুঁজিবাজার বিভাগ ──
    "https://orthosongbad.com/sharemarket/feed/",
    "https://orthosongbad.com/feed/",
    "https://businessbarta.net/feed/",
    "https://businessbarta.net/tag/%E0%A6%B6%E0%A7%87%E0%A6%AF%E0%A6%BC%E0%A6%BE%E0%A6%B0%E0%A6%AC%E0%A6%BE%E0%A6%9C%E0%A6%BE%E0%A6%B0/feed/",
    "https://www.ittefaq.com.bd/feed/",
    "https://www.bd-pratidin.com/economy/feed/",
    "https://www.jugantor.com/economics/feed/",
    "https://www.kalerkantho.com/online/economics/rss.xml",
    "https://www.prothomalo.com/business/feed",
    "https://www.samakal.com/rss/economy",

    # ── ইংরেজি ──
    "https://www.thedailystar.net/business/rss.xml",
    "https://www.thedailystar.net/business/banks/rss.xml",
    "https://www.thedailystar.net/business/economy/rss.xml",
    "https://www.thedailystar.net/business/stock/rss.xml",
    "https://www.dhakatribune.com/feed",
    "https://www.newagebd.net/feed",
    "https://en.prothomalo.com/feed",
    "https://www.tbsnews.net/rss.xml",
    "https://bdnews24.com/?widgetName=rssfeed&widgetId=1150&getXmlFeed=true",
    "https://www.daily-sun.com/rss.xml",
    "https://www.financialexpress-bd.com/rss.xml",
])
RSS_FEEDS = [
    u.strip() for u in os.getenv("NEWS_RSS_FEEDS", DEFAULT_FEEDS).split(",")
    if u.strip()
]

# ═══════════════════════════════════════════════════════════════
# ২. prices.csv থেকে সিম্বল লোড
# ═══════════════════════════════════════════════════════════════

def _load_symbols_from_prices():
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
# ৩. Alias
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
    "SHAHJABANK": ["Shahjalal Bank", "শাহজালাল ব্যাংক", "শাহজালাল ইসলামী"],
    "DUTCHBANGL": ["Dutch-Bangla", "ডাচ্-বাংলা", "ডাচ বাংলা"],
    "PUBALIBANK": ["Pubali Bank", "পূবালী ব্যাংক"],
    "DHAKABANK":  ["Dhaka Bank", "ঢাকা ব্যাংক"],
    "UTTARABANK": ["Uttara Bank", "উত্তরা ব্যাংক"],
    "PRIMEBANK":  ["Prime Bank", "প্রাইম ব্যাংক"],
    "SOUTHEASTB": ["Southeast Bank", "সাউথইস্ট ব্যাংক"],
    "BANKASIA":   ["Bank Asia", "ব্যাংক এশিয়া"],
    "MERCANBANK": ["Mercantile Bank", "মার্কেন্টাইল ব্যাংক"],
    "NBL":        ["National Bank", "ন্যাশনাল ব্যাংক"],
    "UCB":        ["United Commercial Bank"],
    "EXIMBANK":   ["EXIM Bank", "এক্সিম ব্যাংক"],
}

GENERIC_ALIASES_TO_SKIP = {
    "OLYMPIC":   {"Olympic", "অলিম্পিক"},
    "MARICO":    {"Marico", "ম্যারিকো"},
    "RENATA":    {"Renata", "রেনাটা"},
    "ROBI":      {"Robi", "রবি"},
    "BERGERPBL": {"Berger", "বার্জার"},
}

# ═══════════════════════════════════════════════════════════════
# ৪. কি-ওয়ার্ড
# ═══════════════════════════════════════════════════════════════

# ফাইন্যান্স-সম্পর্কিত শব্দ (কোম্পানি-নিউজের জন্য)
FINANCE_KEYWORDS = [
    "share", "stock", "shares", "stocks", "equity", "dividend", "profit",
    "loss", "revenue", "earnings", "quarter", "annual", "agm", "egm",
    "board", "bonus", "rights", "ipo", "eps", "nav", "loan", "credit",
    "bank", "insurance", "mutual fund", "investment", "investor", "broker",
    "securities", "finance", "financial", "capital market", "listed",
    "শেয়ার", "স্টক", "মুনাফা", "লাভ", "ক্ষতি", "লভ্যাংশ",
    "বোনাস", "ডিভিডেন্ড", "বিনিয়োগ", "আয়", "কোয়ার্টার", "বার্ষিক",
    "আর্থিক", "নিট লাভ", "নিট ক্ষতি", "পর্ষদ", "বোর্ড", "এজিএম", "ইজিএম",
    "ব্রোকারেজ", "আইপিও",
]

# শক্তিশালী মার্কেট-ওয়াইড শব্দ (সিম্বল না থাকলেও MARKET হিসেবে সেভ হবে)
STRONG_MARKET_KEYWORDS = [
    "পুঁজিবাজার", "পুঁজি বাজার", "শেয়ারবাজার", "শেয়ার বাজার",
    "স্টক এক্সচেঞ্জ", "স্টক মার্কেট", "স্টক এক্সচেঞ্জ",
    "ডিএসই", "সিএসই", "ডিএসইএক্স", "ডিএস৩০", "বিএসইসি",
    "মূল্য সূচক", "সূচক বেড়েছে", "সূচক কমেছে",
    "লেনদেন কমেছে", "লেনদেন বেড়েছে",
    "শেয়ার দর", "শেয়ারের দাম", "দর বেড়েছে", "দর কমেছে",
    "বাজার পর্যালোচনা", "বাজার পর্যালোচনা",
    "dse", "cse", "bsec", "dsex", "ds30",
    "stock exchange", "bourse", "capital market",
    "dhaka stock", "chittagong stock", "stock market",
    "share market", "share price", "market review",
]

# ═══════════════════════════════════════════════════════════════
# ৫. সহায়ক ফাংশন
# ═══════════════════════════════════════════════════════════════

def clean_text(value):
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


def _has_finance(title, summary):
    blob = f"{title} {summary}".lower()
    return any(kw.lower() in blob for kw in FINANCE_KEYWORDS)


def _has_strong_market(title, summary):
    blob = f"{title} {summary}".lower()
    return any(kw.lower() in blob for kw in STRONG_MARKET_KEYWORDS)


def _match_symbols(title, summary):
    """শুধু সিম্বল/alias ম্যাচ (ফাইন্যান্স চেক বাদ দিয়ে)।"""
    searchable = f"{title} {summary}".upper()
    raw_blob = f"{title} {summary}"
    matched = []
    for sym in TRACKED_SYMBOLS:
        if re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])", searchable):
            matched.append(sym)
            continue
        aliases = SYMBOL_ALIASES.get(sym, [])
        skip = GENERIC_ALIASES_TO_SKIP.get(sym, set())
        for alias in aliases:
            if alias in skip:
                continue
            if alias.upper() in searchable or alias in raw_blob:
                matched.append(sym)
                break
    return matched


def classify_news(title, summary):
    """
    রিটার্ন করে সিম্বল লিস্ট। খবর কোনো কোম্পানির না হলে ['MARKET']।
    কিছুই না মিললে [].
    """
    # ১. ফাইন্যান্স কি-ওয়ার্ড না থাকলে বাদ
    if not _has_finance(title, summary):
        return []

    # ২. কোম্পানি-নির্দিষ্ট?
    symbols = _match_symbols(title, summary)
    if symbols:
        return symbols

    # ३. মার্কেট-ওয়াইড?
    if _has_strong_market(title, summary):
        return ["MARKET"]

    return []

# ═══════════════════════════════════════════════════════════════
# ৬. আউটপুট
# ═══════════════════════════════════════════════════════════════

OUTPUT_PATHS = [Path("docs/data/news.json"), Path("data/news.json")]
MAX_ITEMS_PER_FEED = 100

# ═══════════════════════════════════════════════════════════════
# ৭. মূল ফাংশন
# ═══════════════════════════════════════════════════════════════

def fetch_from_rss():
    items = {}
    stats = {"feeds_ok": 0, "feeds_fail": 0, "entries_total": 0,
             "symbol_matches": 0, "market_matches": 0}

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(
                feed_url,
                request_headers={"User-Agent": "DSE-News-Scanner/1.0"},
            )
            if getattr(feed, "bozo", False) and not feed.entries:
                print(f"❌ {feed_url} → parse error")
                stats["feeds_fail"] += 1
                continue

            source_name = clean_text(feed.feed.get("title")) or urlparse(feed_url).netloc
            n_entries = len(feed.entries)
            stats["feeds_ok"] += 1
            stats["entries_total"] += n_entries

            symbol_count = 0
            market_count = 0

            for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
                title = clean_text(entry.get("title"))
                link = str(entry.get("link") or "").strip()
                if not title or not link:
                    continue
                summary = clean_text(entry.get("summary") or entry.get("description"))

                for sym in classify_news(title, summary):
                    if sym == "MARKET":
                        market_count += 1
                    else:
                        symbol_count += 1
                    items[(sym, link)] = {
                        "date": entry_date(entry),
                        "symbol": sym,
                        "title": title,
                        "summary": summary[:600],
                        "source": feed_url,
                        "source_name": source_name,
                        "link": link,
                    }

            stats["symbol_matches"] += symbol_count
            stats["market_matches"] += market_count
            print(f"✅ {feed_url} → {n_entries} entries, {symbol_count} symbol + {market_count} market")

        except Exception as exc:
            print(f"❌ {feed_url} → {exc}")
            stats["feeds_fail"] += 1

    print(f"\n📊 সারসংক্ষেপ:")
    print(f"   সফল ফিড: {stats['feeds_ok']}, ব্যর্থ: {stats['feeds_fail']}")
    print(f"   মোট entry: {stats['entries_total']}")
    print(f"   symbol match: {stats['symbol_matches']}, market match: {stats['market_matches']}")
    return sorted(items.values(), key=lambda x: x["date"], reverse=True)


def save_news(news_list):
    payload = json.dumps(news_list, ensure_ascii=False, indent=2) + "\n"
    for path in OUTPUT_PATHS:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".json.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
        temp_path.replace(path)
        print(f"Saved {len(news_list)} items → {path}")


if __name__ == "__main__":
    print(f"Tracked symbols: {len(TRACKED_SYMBOLS)}")
    print(f"RSS feeds: {len(RSS_FEEDS)}")
    save_news(fetch_from_rss())
