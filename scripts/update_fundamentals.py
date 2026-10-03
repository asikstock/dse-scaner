#!/usr/bin/env python3
"""
DSE কোম্পানি-পেজ থেকে মার্কেট ক্যাটাগরি (A/B/N/Z) ও কোয়ার্টারভিত্তিক EPS সংগ্রহ করে
docs/data/fundamentals.csv ফাইলে রাখে। শুধু Python standard library লাগে।

ব্যবহার:
  python scripts/update_fundamentals.py                  # prices.csv-র সব কোম্পানি
  python scripts/update_fundamentals.py --codes GP,BPPL  # শুধু নির্দিষ্ট কোম্পানি
  python scripts/update_fundamentals.py --limit 10       # পরীক্ষার জন্য প্রথম ১০টি

প্রতিটি কোম্পানির পেজ আলাদাভাবে আনতে হয়, তাই ৩০০-৪০০ কোম্পানিতে ১০-১৫ মিনিট লাগে।
"""
import argparse, csv, os, re, sys, time
from datetime import datetime, timezone
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_data as U

BASES = list(U.BASES) + ['https://www.dse.com.bd']
FIELDS = ['CODE', 'CATEGORY', 'EPS_Q1', 'EPS_Q2', 'EPS_H1', 'EPS_Q3', 'EPS_9M', 'EPS_ANNUAL', 'PE', 'UPDATED']
NUM = re.compile(r'^\(?-?[\d,]*\.?\d+\)?$')


class Tokens(HTMLParser):
    """পেজের সব দৃশ্যমান লেখাকে ক্রমানুসারে ছোট ছোট টুকরোয় ভাঙে (টেবিল বা তালিকা, দুই ধরনেই কাজ করে)।"""

    def __init__(self):
        super().__init__()
        self.t, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            x = ' '.join(d.split())
            if x:
                self.t.append(x)


def to_num(x):
    x = (x or '').strip()
    if x in ('-', '–', '', 'n/a', 'N/A'):
        return None
    neg = x.startswith('(') and x.endswith(')')
    try:
        v = float(x.strip('()').replace(',', ''))
    except ValueError:
        return None
    return -abs(v) if neg else v


def is_cell(y):
    y = y.replace(' ', '')
    return y in ('-', '–') or y.lower() == 'n/a' or bool(NUM.match(y))


def parse_company(html):
    """{'CATEGORY': 'A', 'EPS': [Q1,Q2,H1,Q3,9M,Annual], 'PE': x} অথবা ক্যাটাগরি না পেলে None।"""
    p = Tokens()
    p.feed(html)
    t = p.t
    low = [x.lower() for x in t]
    out = {'CATEGORY': '', 'EPS': [None] * 6, 'PE': None}

    for i, x in enumerate(t):
        if low[i].startswith('market category'):
            m = re.search(r'market category\s*[:·\-]?\s*([A-Za-z])\b', x, re.I)
            if m:
                out['CATEGORY'] = m.group(1).upper()
            else:
                for y in t[i + 1:i + 4]:
                    y = y.strip(':·- ')
                    if re.fullmatch(r'[A-Za-z]', y):
                        out['CATEGORY'] = y.upper()
                        break
            if out['CATEGORY']:
                break

    start = next((i for i, x in enumerate(low) if x.startswith('interim financial performance')), None)
    if start is not None:
        j = next((k for k in range(start, len(t)) if low[k].startswith('earnings per share') and 'continuing' not in low[k]), None)
        if j is not None:
            b = next((k for k in range(j, min(j + 30, len(t))) if re.fullmatch(r'basic\W*', low[k])), None)
            if b is not None:
                vals = []
                for y in t[b + 1:b + 7]:
                    if is_cell(y):
                        vals.append(to_num(y))
                    else:
                        break
                for n, v in enumerate(vals):
                    out['EPS'][n] = v

    k = next((i for i, x in enumerate(low) if 'un-audited' in x and 'p/e' in x), None)
    if k is not None:
        m = next((q for q in range(k, min(k + 15, len(t))) if low[q].startswith('current p/e ratio using basic')), None)
        if m is not None:
            vs = []
            for y in t[m + 1:m + 7]:
                if not is_cell(y):
                    break
                vs.append(to_num(y))
            vs = [v for v in vs if v is not None]
            out['PE'] = vs[-1] if vs else None

    return out if out['CATEGORY'] else None


def fmt(v):
    return '' if v is None else ('%.3f' % v).rstrip('0').rstrip('.')


def load_existing(path):
    d = {}
    if os.path.exists(path):
        with open(path, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                d[r['CODE']] = r
    return d


def save(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for k in sorted(d):
            w.writerow({c: d[k].get(c, '') for c in FIELDS})


def codes_from_prices():
    path = U.CSV_PATH
    if not os.path.exists(path):
        raise RuntimeError(f'{path} পাওয়া যায়নি। আগে ডেটা-ইতিহাস নামান (bootstrap)।')
    last, codes = '', set()
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        last = max(last, r['DATE'])
    for r in rows:
        if r['DATE'] == last:
            codes.add(r['TRADING CODE'])
    return sorted(codes)


def fetch_company(code, bases):
    """চালু ঠিকানা আগে চেষ্টা করে; ব্যর্থ হলে বাকিগুলো। (পেজ HTML, চালু ঠিকানা) দেয়।"""
    err = None
    for base in bases:
        try:
            return U.http_get(f'{base}/displayCompany.php?name={code}', retries=2), base
        except Exception as e:
            err = e
    raise RuntimeError(str(err))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--codes', default='')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--sleep', type=float, default=1.2)
    ap.add_argument('--min-ok', type=float, default=0.5, help='এর চেয়ে কম সফল হলে ব্যর্থ ধরবে')
    a = ap.parse_args()
    path = os.path.join(U.DATA_DIR, 'fundamentals.csv')
    try:
        codes = [c.strip().upper() for c in a.codes.split(',') if c.strip()] or codes_from_prices()
    except Exception as e:
        U.log('ত্রুটি:', e)
        return 1
    if a.limit:
        codes = codes[:a.limit]
    data = load_existing(path)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    bases, ok, bad = list(BASES), 0, []
    U.log(f'{len(codes)}টি কোম্পানির ক্যাটাগরি ও EPS আনা হচ্ছে…')
    for i, code in enumerate(codes, 1):
        try:
            html, base = fetch_company(code, bases)
            bases = [base] + [b for b in bases if b != base]
            r = parse_company(html)
            if r is None:
                raise RuntimeError('ক্যাটাগরি খুঁজে পাওয়া যায়নি (পেজের গঠন বদলেছে?)')
            e = r['EPS']
            data[code] = {'CODE': code, 'CATEGORY': r['CATEGORY'], 'EPS_Q1': fmt(e[0]), 'EPS_Q2': fmt(e[1]), 'EPS_H1': fmt(e[2]),
                          'EPS_Q3': fmt(e[3]), 'EPS_9M': fmt(e[4]), 'EPS_ANNUAL': fmt(e[5]), 'PE': fmt(r['PE']), 'UPDATED': now}
            ok += 1
            U.log(f'[{i}/{len(codes)}] {code}: {r["CATEGORY"]}, EPS {[x for x in e]}')
        except Exception as ex:
            bad.append(code)
            U.log(f'[{i}/{len(codes)}] {code}: ব্যর্থ ({ex})')
        if i % 50 == 0:
            save(path, data)
        time.sleep(a.sleep)
    save(path, data)
    U.log(f'শেষ: {ok}টি সফল, {len(bad)}টি ব্যর্থ। ফাইলে মোট {len(data)}টি কোম্পানি।')
    if bad:
        U.log('ব্যর্থ: ' + ', '.join(bad[:60]) + (' …' if len(bad) > 60 else ''))
    if codes and ok / len(codes) < a.min_ok:
        U.log('ত্রুটি: অধিকাংশ কোম্পানির তথ্য আনা যায়নি। DSE সাইট বা পেজের গঠন বদলে থাকতে পারে।')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
