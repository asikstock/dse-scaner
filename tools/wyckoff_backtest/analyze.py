"""Wyckoff ব্যাকটেস্টের ফল বিশ্লেষণ: সপ্তাহ-ক্লাস্টার ত্রুটি, বাজার-সমন্বিত (universe-matched) অতিরিক্ত রিটার্ন, ত্রৈমাসিক ভাগ।

চালান:
  python3 tools/wyckoff_backtest/analyze.py out_signals.csv out_universe.csv docs/data/dsex.csv [খরচ%=0.5]

পড়ার নিয়ম:
- net = গ্রস রিটার্ন − খরচ। 'অতিরিক্ত' = ট্রেডের গ্রস − সেই দিনের সব কোডের গড় গ্রস (একই hold)।
- t-মান ক্লাস্টার-সংশোধিত: একই সংকেত-সপ্তাহের ট্রেডগুলো একসঙ্গে গড় করে তবে ত্রুটি।
- DSE-তে শর্ট সেল সাধারণ নয়, তাই BEARISH সারি শুধু "এড়ানোর সংকেত" হিসেবে দেখার জন্য: সেখানে কম/ঋণাত্মক রিটার্ন মানে ভালো।
"""
import math
import sys

import numpy as np
import pandas as pd

sig = pd.read_csv(sys.argv[1], parse_dates=["date"])
uni = pd.read_csv(sys.argv[2], parse_dates=["date"]).set_index("date")
dsex = pd.read_csv(sys.argv[3], parse_dates=["date"]).set_index("date")["dsex_close"]
COST = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
HOLDS = (5, 10, 20)

sig["week"] = sig["date"].dt.strftime("%G-%V")
sig["qtr"] = sig["date"].dt.year.astype(str) + "Q" + sig["date"].dt.quarter.astype(str)
for h in HOLDS:
    sig[f"u{h}"] = sig["date"].map(uni[f"r{h}"])
    sig[f"x{h}"] = sig[f"r{h}"] - sig[f"u{h}"]
sig["rlevels_net"] = sig["rlevels"] - COST


def stats(df, col, net=True):
    d = df.dropna(subset=[col])
    if d.empty:
        return None
    v = d[col] - (COST if net else 0)
    wk = d.assign(v=v).groupby("week")["v"].mean()
    se = wk.std(ddof=1) / math.sqrt(len(wk)) if len(wk) > 1 else float("nan")
    return len(d), wk.size, v.mean(), (v.mean() / se if se and se == se else float("nan")), (v > 0).mean() * 100


def row(label, df, h):
    a = stats(df, f"r{h}")
    x = stats(df, f"x{h}", net=False)
    if not a:
        return f"{label:34s} (ডেটা নেই)"
    return (f"{label:34s} {a[0]:6d} {a[1]:5d} {a[2]:7.2f} {a[3]:6.1f} {a[4]:5.1f} | {x[2]:7.2f} {x[3]:6.1f}")


HEAD = f"{'গ্রুপ':34s} {'n':>6s} {'সপ্তাহ':>5s} {'net%':>7s} {'t':>6s} {'win%':>5s} | {'অতি%':>7s} {'t':>6s}"

groups = [
    ("BULL entry (সব)", sig[(sig.bias == "BULLISH") & sig.entry]),
    ("  Accumulation entry", sig[(sig.phase == "Accumulation") & sig.entry]),
    ("  Re-accumulation entry", sig[(sig.phase == "Re-accumulation") & sig.entry]),
    ("  Markup (SOS) entry", sig[(sig.phase == "Markup") & sig.entry]),
    ("BULL watch (entry নয়)", sig[(sig.bias == "BULLISH") & ~sig.entry]),
    ("  Accumulation watch", sig[(sig.phase == "Accumulation") & ~sig.entry]),
    ("  Re-accumulation watch", sig[(sig.phase == "Re-accumulation") & ~sig.entry]),
    ("BEAR (এড়ানোর সংকেত) সব", sig[sig.bias == "BEARISH"]),
    ("  Distribution", sig[sig.phase == "Distribution"]),
    ("  Re-distribution", sig[sig.phase == "Re-distribution"]),
    ("  Markdown (SOW)", sig[sig.phase == "Markdown"]),
]

print(f"খরচ {COST}% | সংকেত-সারি {len(sig)} | তারিখ {sig.date.min().date()} থেকে {sig.date.max().date()}")
print("ফেজ অনুযায়ী মোট:", sig.groupby("phase").size().to_dict())
for h in HOLDS:
    print(f"\n===== hold {h} দিন (এন্ট্রি পরদিন ওপেন, এক্সিট t+{h} ক্লোজ) =====")
    print(HEAD)
    for label, df in groups:
        print(row(label, df, h))
    u = uni[f"r{h}"].dropna()
    print(f"{'(পুরো বাজারের গড়, প্রতিদিন)':34s} {'':6s} {'':5s} {u.mean() - COST:7.2f}")

print("\n===== স্ক্যানারের নিজের stop/target (সর্বোচ্চ ২০ দিন), শুধু BULLISH =====")
print(f"{'গ্রুপ':34s} {'n':>6s} {'সপ্তাহ':>5s} {'net%':>7s} {'t':>6s} {'win%':>5s}")
for label, df in groups[:7]:
    s = stats(df, "rlevels_net", net=False)
    print(f"{label:34s} {s[0]:6d} {s[1]:5d} {s[2]:7.2f} {s[3]:6.1f} {s[4]:5.1f}" if s else f"{label:34s} (ডেটা নেই)")

print("\n===== ত্রৈমাসিক ভাগ: BULL entry, hold 10 =====")
b = sig[(sig.bias == "BULLISH") & sig.entry]
ud = uni["r10"]
ds = dsex.groupby(dsex.index.year.astype(str) + "Q" + dsex.index.quarter.astype(str)).agg(lambda s: (s.iloc[-1] / s.iloc[0] - 1) * 100)
print(f"{'qtr':7s} {'n':>5s} {'net%':>7s} {'win%':>5s} {'বাজার%':>7s} {'অতি%':>7s} {'DSEX%':>7s}")
for q, g in b.groupby("qtr"):
    g = g.dropna(subset=["r10"])
    if g.empty:
        continue
    print(f"{q:7s} {len(g):5d} {g.r10.mean() - COST:7.2f} {(g.r10 - COST > 0).mean() * 100:5.1f} "
          f"{g.u10.mean() - COST:7.2f} {g.x10.mean():7.2f} {ds.get(q, float('nan')):7.1f}")

print("\n===== বাজার-অবস্থা (DSEX vs ৫০ দিনের গড়): BULL entry, hold 10 =====")
sma50 = dsex.rolling(50).mean()
regime = (dsex > sma50).reindex(b.date.values).values
for lab, m in (("DSEX>SMA50", regime == True), ("DSEX<=SMA50", regime == False)):  # noqa: E712
    g = b[m].dropna(subset=["r10"])
    if len(g):
        print(f"{lab:12s} n={len(g):5d} net={g.r10.mean() - COST:6.2f} অতিরিক্ত={g.x10.mean():6.2f} win={(g.r10 - COST > 0).mean() * 100:5.1f}")
