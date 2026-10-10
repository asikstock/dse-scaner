#!/usr/bin/env python3
"""
DSE দৈনিক ডেটা সংগ্রাহক। শুধু Python standard library লাগে, কিছু ইনস্টল করতে হয় না।

ব্যবহার:
  python scripts/update_data.py                 # আজকের (শেষ) বাজার-দিনের ডেটা যোগ করে
  python scripts/update_data.py --bootstrap     # প্রথমবার: সব কোম্পানির ইতিহাস নামায়
  python scripts/update_data.py --bootstrap --days 760 --codes GP,SQURPHARMA
  python scripts/update_data.py --bootstrap --backfill --days 760   # আগের ডেটা রেখে শুধু পুরনো অংশ (২ বছর পর্যন্ত) ভরে
  python scripts/update_data.py --force         # বাজার চলাকালীন আংশিক ডেটাও নেয় (সাধারণত দরকার নেই)

আউটপুট: docs/data/prices.csv,  docs/data/index.csv  এবং  docs/data/meta.json
"""
import argparse, csv, json, os, re, ssl, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

# DSE নতুন সাইটে গেছে; পুরনো পেজ আপাতত old.dsebd.org-এ চলছে। দুটোই পরপর চেষ্টা করা হয়।
BASES = ['https://old.dsebd.org', 'https://www.dsebd.org']
# নতুন DSE ডোমেইন (DSEX ইনডেক্সের জন্য)
DSE_NEW = 'https://www.dse.com.bd'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'docs', 'data')
CSV_PATH = os.path.join(DATA_DIR, 'prices.csv')
INDEX_CSV_PATH = os.path.join(DATA_DIR, 'index.csv')
META_PATH = os.path.join(DATA_DIR, 'meta.json')
FIELDS = ['DATE', 'TRADING CODE', 'OPENP', 'HIGH', 'LOW', 'CLOSEP', 'YCP', 'VOLUME']
DHAKA = timezone(timedelta(hours=6))


def log(*a):
    print(*a, flush=True)


# ---------- HTTP ----------
def http_get(url, retries=3, timeout=45):
    """সার্টিফিকেট যাচাই আগে চেষ্টা করে; old.dsebd.org মাঝের সার্টিফিকেট পাঠায় না বলে ব্যর্থ হলে যাচাই ছাড়া আবার চেষ্টা করে।
    এগুলো সবই পাবলিক ডেটা, কোনো গোপন তথ্য পাঠানো হয় না।"""
    last = None
    for k in range(retries):
        for verify in (True, False):
            ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
            try:
                req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en'})
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                    return r.read().decode('utf-8', 'replace')
            except urllib.error.HTTPError as e:
                last = e
                break
            except urllib.error.URLError as e:
                last = e
                if verify and isinstance(e.reason, ssl.SSLError):
                    continue
                break
            except ssl.SSLError as e:
                last = e
                if verify:
                    continue
                break
            except Exception as e:
                last = e
                break
        time.sleep(2 * (k + 1))
    raise RuntimeError(f'{url} আনা যায়নি: {last}')


# ---------- HTML table parsing ----------
class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.stack, self.text = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            t = {'rows': [], 'row': None, 'cell': None}
            self.stack.append(t)
            self.tables.append(t['rows'])
        elif self.stack:
            t = self.stack[-1]
            if tag == 'tr':
                t['row'] = []
                t['rows'].append(t['row'])
            elif tag in ('td', 'th') and t['row'] is not None:
                t['cell'] = []

    def handle_endtag(self, tag):
        if tag == 'table' and self.stack:
            self.stack.pop()
        elif self.stack:
            t = self.stack[-1]
            if tag in ('td', 'th') and t['cell'] is not None and t['row'] is not None:
                t['row'].append(' '.join(''.join(t['cell']).split()))
                t['cell'] = None
            elif tag == 'tr':
                t['row'] = None

    def handle_data(self, d):
        self.text.append(d)
        if self.stack and self.stack[-1]['cell'] is not None:
            self.stack[-1]['cell'].append(d)


def nk(s):
    return re.sub(r'[^A-Z0-9]', '', s.upper())


def extract(html):
    """হেডারে 'TRADING CODE' আছে এমন টেবিল থেকে সারিগুলো {হেডার: মান} আকারে দেয়।"""
    p = TableParser()
    p.feed(html)
    out = []
    for rows in p.tables:
        keys = None
        hdr = None
        for i, r in enumerate(rows[:6]):
            ks = [nk(c) for c in r]
            if 'TRADINGCODE' in ks:
                keys, hdr = ks, i
                break
        if keys is None:
            continue
        for r in rows[hdr + 1:]:
            if len(r) == len(keys):
                out.append(dict(zip(keys, r)))
    return out, ' '.join(p.text)


def fnum(x):
    try:
        return float(str(x).replace(',', '').strip())
    except Exception:
        return 0.0


def fmt(x):
    return ('%.2f' % x).rstrip('0').rstrip('.')


def parse_date(s):
    s = (s or '').strip()
    for f in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%b %d, %Y', '%d-%b-%Y'):
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    return None


def _mk(mon, day, year, hh=None, mi=None, ap=None):
    try:
        if hh is None:
            return datetime.strptime(f'{mon[:3]} {day} {year}', '%b %d %Y')
        return datetime.strptime(f'{mon[:3]} {day} {year} {hh}:{mi} {ap.upper()}', '%b %d %Y %I:%M %p')
    except ValueError:
        return None


def snapshot_dt(text):
    pats = [r'On\s+([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s*(\d{4})\s+at\s+(\d{1,2}):(\d{2})\s*([AaPp][Mm])',
            r'([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s*(\d{4})[,\s]+(?:at\s+)?(\d{1,2}):(\d{2})\s*([AaPp][Mm])']
    for pat in pats:
        m = re.search(pat, text)
        if m:
            dt = _mk(m[1], m[2], m[3], m[4], m[5], m[6])
            if dt:
                return dt, True
    m = re.search(r'([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s*(\d{4})', text)
    if m:
        dt = _mk(m[1], m[2], m[3])
        if dt:
            return dt, False
    m = re.search(r'(20\d{2})-(\d{2})-(\d{2})', text)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3])), False
        except ValueError:
            pass
    return None, False


def snapshot_time(text):
    return snapshot_dt(text)[0]


def now_dhaka():
    return datetime.now(DHAKA)


def to_record(d, date_str):
    code = (d.get('TRADINGCODE') or '').strip().upper()
    ltp = fnum(d.get('LTP'))
    close = fnum(d.get('CLOSEP')) or ltp
    if not code or close <= 0 or not date_str:
        return None
    openp = fnum(d.get('OPENP'))
    high = fnum(d.get('HIGH')) or close
    low = fnum(d.get('LOW')) or close
    ycp = fnum(d.get('YCP'))
    return {'DATE': date_str, 'TRADING CODE': code,
            'OPENP': fmt(openp) if openp > 0 else '', 'HIGH': fmt(high), 'LOW': fmt(low),
            'CLOSEP': fmt(close), 'YCP': fmt(ycp) if ycp > 0 else '', 'VOLUME': str(int(fnum(d.get('VOLUME'))))}


# ---------- storage ----------
def load_csv():
    data = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                data[(r['DATE'], r['TRADING CODE'])] = r
    return data


def merge(data, records):
    for r in records:
        k = (r['DATE'], r['TRADING CODE'])
        old = data.get(k)
        if old and not r['OPENP'] and old.get('OPENP'):
            r['OPENP'] = old['OPENP']
        data[k] = r


def save(data, keep, source):
    dates = sorted({k[0] for k in data})
    keep_dates = set(dates[-keep:])
    rows = [data[k] for k in sorted(data) if k[0] in keep_dates]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    meta = {'updated_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'last_date': max(keep_dates) if keep_dates else None,
            'first_date': min(keep_dates) if keep_dates else None,
            'symbols': len({r['TRADING CODE'] for r in rows}), 'rows': len(rows), 'source': source}
    with open(META_PATH, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log(f"সংরক্ষিত: {meta['rows']} সারি, {meta['symbols']} কোম্পানি, {meta['first_date']} থেকে {meta['last_date']}")


# ---------- index (DSEX) ----------
def load_index():
    """index.csv পড়ে {তারিখ: ক্লোজ} ডিকশনারি দেয়।"""
    data = {}
    if os.path.exists(INDEX_CSV_PATH):
        with open(INDEX_CSV_PATH, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                d = (r.get('DATE') or '').strip()
                c = (r.get('CLOSE') or '').strip()
                if d and c:
                    data[d] = c
    return data


def save_index(data):
    """index.csv-এ সেভ করে (তারিখ অনুযায়ী সাজানো)।"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(INDEX_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['DATE', 'CLOSE'])
        for d in sorted(data.keys()):
            w.writerow([d, data[d]])
    log(f"ইনডেক্স সংরক্ষিত: {len(data)} দিন")


def fetch_dsex_new_site():
    """নতুন DSE সাইটের হোমপেজ থেকে আজকের DSEX মান বের করে।"""
    for url in (DSE_NEW + '/', DSE_NEW, 'https://dse.com.bd/'):
        try:
            html = http_get(url)
            # DSEX-এর পাশে থাকা সংখ্যা খোঁজার কয়েকটি প্যাটার্ন
            pats = [
                r'DSEX[^\d]{0,150}?([4-9][,\.]?\d{3}\.\d{1,2})',
                r'([4-9][,\.]?\d{3}\.\d{1,2})[^\d]{0,150}?DSEX',
                r'"DSEX"[^\d]{0,50}?([\d,\.]+)',
                r'"DSEXIndex"[^\d]{0,50}?([\d,\.]+)',
                r'"dsex"[^\d]{0,50}?([\d,\.]+)',
            ]
            for pat in pats:
                m = re.findall(pat, html, re.IGNORECASE)
                if m:
                    v = fnum(m[0])
                    if 1000 < v < 20000:  # স্যানিটি চেক
                        log(f'হোমপেজ ({url}) থেকে DSEX = {v}')
                        return v
        except Exception as e:
            log(f'{url} ব্যর্থ: {e}')
    return None


def update_index(date_str):
    """prices আপডেটের পরপরই index.csv-এ DSEX যোগ করে।"""
    try:
        existing = load_index()
        if date_str in existing:
            log(f'ইনডেক্স: {date_str} তারিখের DSEX আগেই আছে ({existing[date_str]})')
            return
        v = fetch_dsex_new_site()
        if v:
            existing[date_str] = fmt(v)
            save_index(existing)
        else:
            log('ইনডেক্স: আজকের DSEX পাওয়া যায়নি। পরবর্তী run-এ আবার চেষ্টা হবে।')
    except Exception as e:
        log(f'ইনডেক্স নামানো ব্যর্থ: {e}')


# ---------- fetchers ----------
def fetch_snapshot():
    errs = []
    for base in BASES:
        url = base + '/latest_share_price_scroll_l.php'
        try:
            rows, text = extract(http_get(url))
            if len(rows) >= 50:
                log(f'{url}: {len(rows)} সারি পাওয়া গেছে')
                return base, rows, text
            errs.append(f'{url}: মাত্র {len(rows)} সারি (পেজের গঠন বদলে যেতে পারে)')
        except Exception as e:
            errs.append(str(e))
    raise RuntimeError('সব ঠিকানায় ব্যর্থ:\n  ' + '\n  '.join(errs))


def fetch_archive_once(base, code, start, end):
    qs = urllib.parse.urlencode({'startDate': start, 'endDate': end, 'inst': code, 'archive': 'data'})
    rows, _ = extract(http_get(f'{base}/day_end_archive.php?{qs}'))
    out = []
    for d in rows:
        r = to_record(d, parse_date(d.get('DATE')))
        if r:
            r['TRADING CODE'] = code
            out.append(r)
    return out


CHUNK_DAYS = 360  # DSE আর্কাইভে একবারে এর বেশি দিন চাওয়া হয় না (আগে ৪০০ দিন চলেছে)


def fetch_archive(base, code, start, end, chunk=CHUNK_DAYS):
    """লম্বা সময়কে ৩৬০ দিনের টুকরোয় ভেঙে আনে, যাতে ২ বছরের ডেটাও নিরাপদে আসে।"""
    s = datetime.strptime(start, '%Y-%m-%d').date()
    e = datetime.strptime(end, '%Y-%m-%d').date()
    out = []
    cur = s
    while cur <= e:
        nxt = min(cur + timedelta(days=chunk - 1), e)
        out.extend(fetch_archive_once(base, code, cur.isoformat(), nxt.isoformat()))
        cur = nxt + timedelta(days=1)
    return out


def run_daily(a):
    base, rows, text = fetch_snapshot()
    now = now_dhaka()
    today = now.date()
    force = getattr(a, 'force', False)
    ts, has_time = snapshot_dt(text)
    if ts is not None and (ts.date() > today or (today - ts.date()).days > 10):
        log(f'সতর্কতা: পেজে পাওয়া তারিখ {ts.date()} অস্বাভাবিক, তাই অগ্রাহ্য করা হলো।')
        ts = None
    if ts is None:
        hint = re.search(r'.{0,60}\b20\d\d\b.{0,40}', text)
        log('সতর্কতা: পেজ থেকে তারিখ পড়া যায়নি।' + (f' পেজে পাওয়া কাছাকাছি লেখা: "{hint.group(0).strip()}"' if hint else ''))
        if now.weekday() in (4, 5) and not force:
            log('আজ শুক্র বা শনিবার, বাজার বন্ধ। কিছু যোগ করা হচ্ছে না।')
            return 0
        if (now.hour, now.minute) < (14, 45) and not force:
            log('এখনও ১৪:৪৫ হয়নি, বাজারের চূড়ান্ত দাম আসেনি। কিছু যোগ করা হচ্ছে না।')
            return 0
        ts, has_time = datetime(today.year, today.month, today.day), False
        log(f'আজকের তারিখ ({today}) ধরে এগোচ্ছি।')
    else:
        log(f'পেজের তারিখ-সময়: {ts:%Y-%m-%d %H:%M}' + ('' if has_time else ' (সময় পাওয়া যায়নি)'))
    ch, cm = (int(x) for x in getattr(a, 'cutoff', '14:20').split(':'))
    if has_time and ts.date() == today and (ts.hour, ts.minute) < (ch, cm) and not force:
        log(f'পেজের সময় {ts:%H:%M}, যা {ch:02d}:{cm:02d} এর আগে। বাজারের চূড়ান্ত দাম এখনও আসেনি, এবার কিছু যোগ করা হচ্ছে না।')
        return 0
    date_str = ts.date().isoformat()
    recs = [r for r in (to_record(d, date_str) for d in rows) if r]
    if len(recs) < 50:
        log(f'ত্রুটি: বৈধ রেকর্ড মাত্র {len(recs)}টি। পেজের গঠন বদলেছে কি না দেখুন।')
        return 1
    data = load_csv()
    stored = {k[0] for k in data}
    prev_dates = sorted(d for d in stored if d < date_str)
    if date_str not in stored and prev_dates:
        prev, same, tot = prev_dates[-1], 0, 0
        for r in recs:
            o = data.get((prev, r['TRADING CODE']))
            if o:
                tot += 1
                if o['CLOSEP'] == r['CLOSEP'] and o['VOLUME'] == r['VOLUME']:
                    same += 1
        if tot >= 50 and same / tot >= 0.95:
            log(f'পেজের দাম ও ভলিউম {prev} তারিখের ডেটার হুবহু একই ({same}/{tot})। ছুটির দিন বা পেজ আপডেট হয়নি, তাই {date_str} যোগ করা হলো না।')
            return 0
    merge(data, recs)
    log(f'{date_str} তারিখের {len(recs)}টি কোম্পানির ডেটা যোগ হয়েছে')
    save(data, a.keep, base)

    # ========== DSEX ইনডেক্সও যোগ করা ==========
    update_index(date_str)

    return 0


def run_bootstrap(a):
    base, rows, _ = fetch_snapshot()
    codes = [c.strip().upper() for c in a.codes.split(',')] if a.codes else sorted(
        {(d.get('TRADINGCODE') or '').strip().upper() for d in rows if (d.get('TRADINGCODE') or '').strip()})
    end = datetime.now(DHAKA).date()
    start = end - timedelta(days=a.days)
    data = load_csv()
    # --backfill: যে কোম্পানির ডেটা আগে থেকে আছে তার শুধু পুরনো অংশ (প্রথম সংরক্ষিত দিনের আগে) আনা হয়
    first = {}
    if getattr(a, 'backfill', False):
        for (d, c) in data:
            if c not in first or d < first[c]:
                first[c] = d
    mode = 'শুধু পুরনো অংশ ভরা (backfill)' if first else 'পুরো ইতিহাস'
    log(f'{len(codes)}টি কোম্পানির ইতিহাস ({start} থেকে {end}) নামানো হচ্ছে [{mode}]। এতে বেশ কিছুক্ষণ লাগবে।')
    failed, skipped = [], 0
    for i, code in enumerate(codes, 1):
        c_start, c_end = start, end
        if code in first:
            c_end = datetime.strptime(first[code], '%Y-%m-%d').date() - timedelta(days=1)
            if c_end < c_start:
                skipped += 1
                continue
        try:
            recs = fetch_archive(base, code, c_start.isoformat(), c_end.isoformat())
            merge(data, recs)
            log(f'[{i}/{len(codes)}] {code}: {len(recs)} দিন ({c_start} থেকে {c_end})')
        except Exception as e:
            failed.append(code)
            log(f'[{i}/{len(codes)}] {code}: ব্যর্থ ({e})')
        if i % 40 == 0:
            save(data, a.keep, base)
        time.sleep(a.sleep)
    if skipped:
        log(f'{skipped}টি কোম্পানির ডেটা আগেই যথেষ্ট পুরনো পর্যন্ত আছে, বাদ দেওয়া হলো।')
    if failed:
        log(f'ব্যর্থ হয়েছে ({len(failed)}টি): ' + ', '.join(failed))
    save(data, a.keep, base)

    # ========== আজকের DSEX মান যোগ করা (ইতিহাস fetch_dsex.py আলাদা করে ভরে) ==========
    log('আজকের DSEX মান যোগ করা হচ্ছে...')
    try:
        update_index(end.isoformat())
    except Exception as e:
        log(f'ইনডেক্স ব্যর্থ: {e}')

    return 0 if len(failed) < len(codes) else 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--bootstrap', action='store_true', help='প্রথমবার ইতিহাস নামান')
    p.add_argument('--days', type=int, default=760, help='ইতিহাসের ক্যালেন্ডার-দিন (ডিফল্ট ৭৬০ ≈ ২ বছর)')
    p.add_argument('--backfill', action='store_true', help='আগের ডেটা না ছুঁয়ে শুধু পুরনো অংশ ভরে (--bootstrap-এর সাথে)')
    p.add_argument('--codes', default='', help='কমা দিয়ে নির্দিষ্ট কোম্পানির কোড')
    p.add_argument('--keep', type=int, default=560, help='সর্বাধিক কত ট্রেডিং-দিন রাখবে (ডিফল্ট ৫৬০ ≈ ২ বছর ২ মাস)')
    p.add_argument('--sleep', type=float, default=1.5, help='প্রতি কোম্পানির মাঝে বিরতি (সেকেন্ড)')
    p.add_argument('--cutoff', default='14:20', help='এর আগের (ঢাকা সময়) আংশিক ডেটা নেবে না')
    p.add_argument('--force', action='store_true')
    a = p.parse_args()
    try:
        sys.exit(run_bootstrap(a) if a.bootstrap else run_daily(a))
    except Exception as e:
        log('ত্রুটি:', e)
        sys.exit(1)


if __name__ == '__main__':
    main()
