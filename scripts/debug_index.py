#!/usr/bin/env python3
"""DSEX ইনডেক্স কোথা থেকে পাওয়া যায় সেটা পরীক্ষা করার স্ক্রিপ্ট।"""
import re, ssl, urllib.request

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
URLS = [
    'https://www.dsebd.org/',
    'https://old.dsebd.org/',
    'https://www.dsebd.org/market_summary.php',
    'https://old.dsebd.org/market_summary.php',
    'https://www.dsebd.org/index_data.php',
    'https://www.dsebd.org/recent_market_information.php',
    'https://www.dsebd.org/day_end_archive.php?startDate=2026-09-25&endDate=2026-10-06&archive=index',
    'https://www.dsebd.org/day_end_archive.php?startDate=2026-09-25&endDate=2026-10-06&archive=dsex',
]

def fetch(url):
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.read().decode('utf-8', 'replace')

for url in URLS:
    print(f'\n=== {url} ===')
    try:
        html = fetch(url)
        print(f'  HTML দৈর্ঘ্য: {len(html)}')
        # DSEX-এর কাছে থাকা সংখ্যা খোঁজা
        matches = re.findall(r'DSEX[^\d]{0,50}([\d,]+\.\d{1,2})', html, re.IGNORECASE)
        if matches:
            print(f'  ✅ DSEX মান পাওয়া গেছে: {matches[:3]}')
        else:
            # DSEX লেখা আছে কিনা দেখা
            if re.search(r'DSEX', html, re.IGNORECASE):
                # DSEX-এর পরবর্তী ২০০ অক্ষর প্রিন্ট করা
                for m in re.finditer(r'DSEX', html, re.IGNORECASE):
                    start = max(0, m.start() - 20)
                    end = min(len(html), m.start() + 200)
                    snippet = re.sub(r'\s+', ' ', html[start:end])
                    print(f'  ⚠️ DSEX পাওয়া গেছে কিন্তু সংখ্যা নেই। প্রেক্ষাপট: {snippet[:150]}')
                    break
            else:
                print(f'  ❌ DSEX পাওয়া যায়নি')
    except Exception as e:
        print(f'  ❌ ত্রুটি: {type(e).__name__}: {e}')
