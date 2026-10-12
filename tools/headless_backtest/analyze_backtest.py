"""স্ক্যানারের ব্যাকটেস্ট ফল বিশ্লেষণ: ক্লাস্টার-সংশোধিত ত্রুটি, ত্রৈমাসিক ভাগ, বাজার-অবস্থা ও র‍্যান্ডম বেসলাইনের সঙ্গে তুলনা।
চালান:
  node harness.js <repo>/docs out_variants.json variants.json
  python3 analyze_backtest.py out_variants.json <repo>/docs/data/dsex.csv
"""
import csv, collections, datetime as dt, json, math, statistics as st, sys

R = {r['name']: r for r in json.load(open(sys.argv[1]))}
dsex = [(r['date'], float(r['dsex_close'])) for r in csv.DictReader(open(sys.argv[2]))]
dd = [d for d, _ in dsex]; dv = [v for _, v in dsex]


def mean(a): return sum(a) / len(a) if a else float('nan')
def se(a): return st.stdev(a) / math.sqrt(len(a)) if len(a) > 1 else float('nan')
def q(d): y, m = int(d[:4]), int(d[5:7]); return f"{y}Q{(m - 1) // 3 + 1}"


def idx_at(d):
    lo, hi, a = 0, len(dd) - 1, -1
    while lo <= hi:
        m = (lo + hi) // 2
        if dd[m] <= d: a = m; lo = m + 1
        else: hi = m - 1
    return a


def sma(i, n): return sum(dv[i - n + 1:i + 1]) / n if i >= n - 1 else None


print(f"{'variant':24s} {'n':>5s} {'mean%':>7s} {'se':>5s} {'t':>5s} {'win%':>5s} {'avgW':>6s} {'avgL':>6s} | {'rand%':>6s} | {'alpha':>6s}")
for r in R.values():
    x = [t['ret'] for t in r['trades']]; b = [t['ret'] for t in r['random']]
    w = [v for v in x if v > 0]; l = [v for v in x if v <= 0]
    print(f"{r['name']:24s} {len(x):5d} {mean(x):7.2f} {se(x):5.2f} {mean(x) / se(x):5.1f} {100 * len(w) / len(x):5.1f} "
          f"{mean(w):6.2f} {mean(l):6.2f} | {mean(b):6.2f} | {mean(x) - mean(b):6.2f}")

qs = collections.OrderedDict()
for d, v in dsex: qs.setdefault(q(d), []).append(v)

for name in ('default_h10', 'default_h20'):
    r = R[name]; T = r['trades']; RND = r['random']
    print(f"\n===== {name}: n={len(T)}")
    wk = collections.defaultdict(list)
    for t in T: wk[dt.date.fromisoformat(t['d']).isocalendar()[:2]].append(t['ret'])
    wm = [mean(v) for v in wk.values()]
    print(f"distinct signal weeks: {len(wk)} | naive SE {se([t['ret'] for t in T]):.2f} | week-cluster SE {se(wm):.2f}")
    byq = collections.defaultdict(list); rq = collections.defaultdict(list)
    for t in T: byq[q(t['d'])].append(t['ret'])
    for t in RND: rq[q(t['d'])].append(t['ret'])
    print(f"{'qtr':7s} {'n':>5s} {'mean%':>7s} {'win%':>5s} {'rand%':>7s} {'DSEX%':>7s}")
    for k in sorted(byq):
        v = byq[k]; d0 = qs.get(k)
        print(f"{k:7s} {len(v):5d} {mean(v):7.2f} {100 * sum(x > 0 for x in v) / len(v):5.1f} {mean(rq[k]):7.2f} {(d0[-1] / d0[0] - 1) * 100:7.1f}")
    for label, cond in (('DSEX>SMA50 ', lambda c, s: c > s), ('DSEX<=SMA50', lambda c, s: c <= s)):
        a = []; rr = []
        for t in T:
            i = idx_at(t['d']); s = sma(i, 50) if i >= 0 else None
            if s is not None and cond(dv[i], s): a.append(t['ret'])
        for t in RND:
            i = idx_at(t['d']); s = sma(i, 50) if i >= 0 else None
            if s is not None and cond(dv[i], s): rr.append(t['ret'])
        print(f"{label} n={len(a):5d} mean={mean(a):6.2f} se={se(a):4.2f} | random mean={mean(rr):6.2f}")
