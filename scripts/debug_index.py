#!/usr/bin/env python3
"""DSEX ইনডেক্স কোথা থেকে পাওয়া যায় সেটা পরীক্ষা করার স্ক্রিপ্ট।"""
import re, ssl, urllib.request

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
URLS = [
    # DSE-র নতুন সাইটে "scroll" প্যাটার্ন (prices যেভাবে কাজ করছে)
    'https://www.dsebd.org/latest_index_scroll_l.php',
    'https://www.dsebd.org/latest_indices_scroll_l.php',
    'https://www.dsebd.org/index_scroll_l.php',
    'https://old.dsebd.org/latest_index_scroll_l.php',
    'https://old.dsebd.org/latest_indices_scroll_l.php',
    # সাধারণ index পেজ
    'https://www.dsebd.org/dse_indices.php',
    'https://old.dsebd.org/dse_indices.php',
    'https://www.dsebd.org/all_share_indices.php',
    'https://old.dsebd.org/all_share_indices.php',
    # market summary পেজ
    'https://www.dsebd.org/market_information.php',
    'https://old.dsebd.org/market_information.php',
    # index archive
    'https://www.dsebd.org/index_archive.php',
    'https://old.dsebd.org/index_archive.php',
    # market statistic
    'https://www.dsebd.org/market-statistics',
    'https://www.dsebd.org/indices',
    # পুরনো প্যাটার্ন (archive)
    'https://old.dsebd.org/day_end_archive.php?startDate=2026-09-25&endDate=2026-10-06&archive=index',
    'https://old.dsebd.org/day_end_archive.php?startDate=2026-09-25&endDate=2026-10-06&archive=dsex',
    'https://old.dsebd.org/index_data_archive.php?startDate=2026-09-25&endDate=2026-10-06',
]

def fetch(url):
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.read().decode('utf-8', 'replace')

def find_dsex(html):
    """HTML-এ DSEX-এর পাশে সংখ্যা খোঁজার চেষ্টা।"""
    # সব ধরনের HTML ট্যাগের ভেতর থেকে DSEX + কাছাকাছি সংখ্যা
    patterns = [
        r'DSEX[^\d]{0,100}?([4-9][,\.]?\d{3}\.\d{1,2})',   # DSEX 5234.56 বা DSEX, 5,234.56
        r'DSEX[^\d]{0,50}?(\d{1,2}[,\.]?\d{3}\.?\d{0,2})',
        r'([4-9][,\.]?\d{3}\.\d{1,2})[^\d]{0,100}?DSEX',   # 5234.56 DSEX
    ]
    for pat in patterns:
        m = re.findall(pat, html, re.IGNORECASE)
        if m:
            return m[:3]
    return None

for url in URLS:
    print(f'\n=== {url} ===')
    try:
        html = fetch(url)
        print(f'  HTML দৈর্ঘ্য: {len(html)}')
        values = find_dsex(html)
        if values:
            print(f'  ✅ DSEX মান পাওয়া গেছে: {values}')
        else:
            # DSEX শব্দ আছে কিনা
            hits = list(re.finditer(r'DSEX', html, re.IGNORECASE))
            if hits:
                print(f'  ⚠️ DSEX {len(hits)} বার পাওয়া গেছে কিন্তু মান নেই')
                # প্রথম ৩টি DSEX থেকে 300 অক্ষর প্রেক্ষাপট
                for m in hits[:3]:
                    start = max(0, m.start() - 10)
                    end = min(len(html), m.start() + 300)
                    snippet = re.sub(r'\s+', ' ', html[start:end])
                    print(f'     → {snippet[:220]}')
            else:
                print(f'  ❌ DSEX শব্দই নেই')
    except Exception as e:
        print(f'  ❌ ত্রুটি: {type(e).__name__}: {e}')
