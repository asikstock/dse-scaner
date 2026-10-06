#!/usr/bin/env python3
"""DSEX দৈনিক ক্লোজ নামিয়ে data/dsex.csv-তে জমা করে। শুধু Python stdlib লাগে।

ব্যবহার:
    python fetch_dsex.py          # CSV না থাকলে ৪০০ দিন, থাকলে শেষ ১০ দিন
    python fetch_dsex.py 800      # নিজে দিন সংখ্যা ঠিক করতে

অন্য স্ক্রিপ্ট থেকে:
    from fetch_dsex import get_latest_dsex
    date, value = get_latest_dsex()
"""
import csv
import datetime as dt
import json
import os
import re
import ssl
import sys
import time
import urllib.request

ARCHIVE_URL = ("https://www.dse.com.bd/api/live/data-archive/market-summary"
               "?from={f}&to={t}")
HOME_URL = "https://www.dse.com.bd/"
CSV_PATH = os.environ.get("DSEX_CSV", "docs/data/dsex.csv")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.dse.com.bd/",
}

SKIP_WORDS = ("change", "chg", "pct", "percent", "volume", "vol", "turnover",
              "trade", "open", "high", "low", "mcap", "cap", "value", "number")


def http_get(url, retries=5, timeout=30):
    ctx = ssl.create_default_context()
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    # SSL সমস্যা হলে শেষ চেষ্টায় verification বন্ধ
    try:
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"fetch failed for {url}: {last} / {e}")


def to_float(v):
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def to_date(v):
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y", "%d %b %Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def dsex_value_from_dict(d):
    """একটি dict থেকে DSEX ক্লোজ মান বের করে (না পেলে None)।"""
    # ১) সরাসরি কী, যেমন "dsex": 5424.9 / "dsexIndex" / "dsex_close"
    for k, v in d.items():
        kl = k.lower()
        if "dsex" in kl and not any(w in kl for w in SKIP_WORDS):
            if isinstance(v, (int, float, str)):
                f = to_float(v)
                if f is not None:
                    return f
            elif isinstance(v, dict):
                for kk in ("close", "closing", "index", "value", "current", "latest"):
                    for ik, iv in v.items():
                        if ik.lower() == kk:
                            f = to_float(iv)
                            if f is not None:
                                return f
    # ২) "index": "DSEX" ধরনের রো, মান আলাদা কী-তে
    names = [str(v).strip().lower() for v in d.values() if isinstance(v, str)]
    if "dsex" in names:
        for k, v in d.items():
            if k.lower() in ("close", "closing", "value", "index", "latest", "current"):
                f = to_float(v)
                if f is not None:
                    return f
    return None


def walk(obj, out):
    """নেস্টেড JSON ঘুরে (তারিখ, dsex) জোড়া জমা করে।"""
    if isinstance(obj, dict):
        date = None
        for k, v in obj.items():
            if "date" in k.lower() or k.lower() in ("time", "timestamp", "day"):
                date = to_date(v) or date
        val = dsex_value_from_dict(obj)
        if date and val is not None and 1000 < val < 20000:
            out[date] = val
        for v in obj.values():
            if isinstance(v, (dict, list)):
                walk(v, out)
    elif isinstance(obj, list):
        for item in obj:
            walk(item, out)


def from_archive(days_back):
    today = dt.date.today()
    url = ARCHIVE_URL.format(
        f=(today - dt.timedelta(days=days_back)).isoformat(),
        t=today.isoformat())
    text = http_get(url)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("archive: JSON নয়, শুরুর অংশ: " + text[:200])
    out = {}
    walk(data, out)
    if not out:
        raise RuntimeError("archive: DSEX মান পাওয়া যায়নি। JSON শুরু: "
                           + json.dumps(data, ensure_ascii=False)[:800])
    return out


def from_homepage():
    """ফলব্যাক: হোমপেজ HTML থেকে (শুধু আজকের/সর্বশেষ মান)।"""
    best = None
    for _ in range(6):  # শেল (~৫০০KB) এলে আবার চেষ্টা
        html = http_get(HOME_URL, retries=2)
        m = re.search(r"DSEX[^0-9]{0,300}?(\d{1,2},?\d{3}\.\d{1,2})", html,
                      re.S | re.I)
        if m:
            best = to_float(m.group(1))
            break
        time.sleep(3)
    if best is None:
        raise RuntimeError("homepage: DSEX মান পাওয়া যায়নি")
    return {dt.date.today().isoformat(): best}


def load_csv():
    rows = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                v = to_float(r.get("dsex_close"))
                if r.get("date") and v is not None:
                    rows[r["date"]] = v
    return rows


def save_csv(rows):
    os.makedirs(os.path.dirname(CSV_PATH) or ".", exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "dsex_close"])
        for d in sorted(rows):
            w.writerow([d, f"{rows[d]:.2f}"])
    # পোর্টাল data/index.csv নামে খোঁজে, তাই একই ডেটা সেই নামেও লেখা হয়
    idx_path = os.path.join(os.path.dirname(CSV_PATH) or ".", "index.csv")
    with open(idx_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "close"])
        for d in sorted(rows):
            w.writerow([d, f"{rows[d]:.2f}"])


def get_latest_dsex(days_back=None):
    """(তারিখ, মান) ফেরত দেয়। CSV-ও আপডেট করে।
    CSV না থাকলে নিজে থেকে ৪০০ দিনের ইতিহাস নামায়, থাকলে শেষ ১০ দিন।"""
    rows = load_csv()
    if days_back is None:
        days_back = 10 if rows else 400
    new, errors = {}, []
    try:
        new = from_archive(days_back)
    except Exception as e:  # noqa: BLE001
        errors.append(str(e))
        try:
            new = from_homepage()
        except Exception as e2:  # noqa: BLE001
            errors.append(str(e2))
    if new:
        rows.update(new)
        save_csv(rows)
    if not rows:
        raise RuntimeError("DSEX পাওয়া যায়নি:\n" + "\n".join(errors))
    if errors and not new:
        print("সতর্কতা: নতুন ডেটা আনা যায়নি, পুরনো CSV ব্যবহার হচ্ছে।\n"
              + "\n".join(errors), file=sys.stderr)
    d = max(rows)
    return d, rows[d], bool(new)


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else None
    date, value, fresh = get_latest_dsex(days)
    print(f"DSEX {date}: {value:.2f}  ({'নতুন' if fresh else 'পুরনো/ক্যাশ'})")
    sys.exit(0 if fresh else 1)
