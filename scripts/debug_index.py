#!/usr/bin/env python3
"""DSEX ইনডেক্স কোথা থেকে পাওয়া যায় সেটা পরীক্ষা করার স্ক্রিপ্ট।"""
import re, ssl, urllib.request

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
URLS = [
    # old.dsebd.org-এ নেভিগেশনে দেখা লিংক
    'https://old.dsebd.org/dseX_share.php',
    'https://old.dsebd.org/dse30_share.php',
    'https://old.dsebd.org/index.php',
    'https://old.dsebd.org/dse_index.php',
    # নতুন ডোমেইন dse.com.bd
    'https://www.dse.com.bd/',
    'https://www.dse.com.bd/indices',
    'https://www.dse.com.bd/market-data',
    'https://dse.com.bd/',
    'https://dse.com.bd/indices',
    # API-style endpoints
    'https://www.dse.com.bd/api/indices',
    'https://www.dse.com.bd/api/v1/indices',
    'https://api.dse.com.bd/indices',
    'https://www.dsebd.org/api/indices',
    # পুরনো index page
    'https://old.dsebd.org/php_file/home_index_data.php',
    'https://old.dsebd.org/home_index_data.php',
]

def fetch(url):
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/json,*/*'})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.read().decode('utf-8', 'replace')

def find_dsex(html):
    patterns = [
        r'DSEX[^\d]{0,150}?([4-9][,\.]?\d{3}\.\d{1,2})',
        r'([4-9][,\.]?\d{3}\.\d{1,2})[^\d]{0,150}?DSEX',
        r'"DSEX"[^\d]{0,50}?([\d,\.]+)',
        r'"DSEXIndex"[^\d]{0,50}?([\d,\.]+)',
        r'"dsex"[^\d]{0,50}?([\d,\.]+)',
    ]
    for pat in patterns:
        m = re.findall(pat, html, re.IGNORECASE)
        if m:
            return m[:5]
    return None

for url in URLS:
    print(f'\n=== {url} ===')
    try:
        html = fetch(url)
        print(f'  HTML দৈর্ঘ্য: {len(html)}')
        # JSON হলে সরাসরি দেখাই
        is_json = html.strip().startswith('{') or html.strip().startswith('[')
        if is_json:
            print(f'  JSON-like content — প্রথম ৫০০ অক্ষর:')
            print(f'     {html[:500]}')
        values = find_dsex(html)
        if values:
            print(f'  ✅ সম্ভাব্য DSEX মান: {values}')
        else:
            hits = list(re.finditer(r'DSEX', html, re.IGNORECASE))
            if hits:
                print(f'  ⚠️ DSEX {len(hits)} বার পাওয়া গেছে কিন্তু মান নেই')
                for m in hits[:2]:
                    start = max(0, m.start() - 30)
                    end = min(len(html), m.start() + 200)
                    snippet = re.sub(r'\s+', ' ', html[start:end])
                    print(f'     → {snippet[:220]}')
            else:
                print(f'  ❌ DSEX শব্দই নেই')
    except Exception as e:
        print(f'  ❌ ত্রুটি: {type(e).__name__}: {e}')
