"""২০–৪০ দিনের ট্রেডের জন্য বিকল্প নিয়মের train/test পরীক্ষা (v3)।

প্রশ্ন: স্টপ-সীমা শিথিল করা, বাজার-অবস্থা ফিল্টার বা শক্তি (RS) ফিল্টার যোগ করলে কি
লিকুইড বাজারের গড়ের চেয়ে বেশি রিটার্ন মেলে, আর সেটা কি দুই অর্ধেই টেকে?

চালান:
  python3 tools/wyckoff_backtest/backtest.py docs/data/prices.csv out_signals.csv out_universe.csv
  python3 tools/wyckoff_backtest/experiments_v3.py out_signals.csv docs/data/prices.csv docs/data/dsex.csv [খরচ%=0.5]

- সংকেত-সময়কাল (~১১ মাস) তারিখের মধ্যমা ধরে দুই ভাগ: TRAIN (আগের অর্ধ), TEST (পরের অর্ধ)।
  নিয়ম বাছাই শুধু TRAIN দেখে; TEST-এ একবারই দেখা হয়। দুই অর্ধে একই দিকে না এলে নিয়মকে প্রমাণিত ধরা হয় না।
- 'অতি%' = ট্রেডের গ্রস − সেই দিনের লিকুইড কোডগুলোর গড় গ্রস (একই hold)। t সংকেত-সপ্তাহ ধরে ক্লাস্টার করা।
- 'net%' = গ্রস − খরচ। বাজার-ফিল্টার কম ঝুঁকিতে নামালে net বাড়তে পারে, কিন্তু 'অতি%' না বাড়লে সেটা আলফা নয়।
"""
import math
import re
import sys

import numpy as np
import pandas as pd

sig_csv, px_csv, dsex_csv = sys.argv[1:4]
COST = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
HOLDS = (20, 40)
MF = re.compile(r"MF$|^1STMF|^2NDMF|^3RDMF|GROWTHFUND|INCOMEFUND|MUTUALFUND|BONDFUND|BOND$")

# ---------- দাম থেকে: ফরওয়ার্ড রিটার্ন, লিকুইডিটি, ৬০ দিনের শক্তি ----------
px = pd.read_csv(px_csv)
px.columns = [x.lower() for x in px.columns]
px = px.rename(columns={"trading code": "sym", "openp": "open", "closep": "close"})
px = px[~px.sym.str.upper().map(lambda s: bool(MF.search(s)))]
px["date"] = pd.to_datetime(px["date"])
C = px.pivot(index="date", columns="sym", values="close").sort_index()
O = px.pivot(index="date", columns="sym", values="open").reindex_like(C)
V = px.pivot(index="date", columns="sym", values="volume").reindex_like(C).fillna(0)
O = O.fillna(C.shift(1)).fillna(C)
nxt = O.shift(-1)
fwd = {h: (C.shift(-h) / nxt - 1) * 100 for h in HOLDS}
liq = ((V * C).rolling(20).mean() >= 3e6) & ((V == 0).rolling(40).sum() <= 4) & (V > 0)
ret60 = (C / C.shift(60) - 1) * 100

dx = pd.read_csv(dsex_csv, parse_dates=["date"]).set_index("date")["dsex_close"].sort_index()
dx = dx.reindex(C.index).ffill()
mkt_up = dx > dx.rolling(50).mean()
dx60 = (dx / dx.shift(60) - 1) * 100

base = {h: fwd[h].where(liq).mean(axis=1) for h in HOLDS}        # প্রতিদিন লিকুইড কোডের গড় গ্রস

# ---------- সংকেত ----------
sig = pd.read_csv(sig_csv, parse_dates=["date"])
sig = sig[~sig.sym.str.upper().map(lambda s: bool(MF.search(s)))].copy()
sig["why_not"] = sig["why_not"].fillna("")
sig["mkt_up"] = sig["date"].map(mkt_up)
sig["rs60"] = [ret60.at[d, s] - dx60.at[d] if s in ret60.columns else np.nan for d, s in zip(sig.date, sig.sym)]
sig["liq"] = [bool(liq.at[d, s]) if s in liq.columns else False for d, s in zip(sig.date, sig.sym)]
sig["week"] = sig["date"].dt.strftime("%G-%V")
mid = sig.date.sort_values().iloc[len(sig) // 2]
sig["half"] = np.where(sig.date < mid, "TRAIN", "TEST")


def other_ok(w):
    """স্টপ ছাড়া বাকি সব গেট পাস (ইভেন্ট, ভলিউমের প্রমাণ, লিকুইডিটি)।"""
    parts = [p.strip() for p in w.split(";") if p.strip()]
    return all(p.startswith("স্টপ") for p in parts)


sig["only_stop_fail"] = sig.why_not.map(other_ok) & (sig.why_not != "")
bull = sig[sig.bias == "BULLISH"]
S = bull[bull.tier == "SIGNAL"]
stop_relax = lambda x: bull[(bull.tier == "SIGNAL") | (bull.only_stop_fail & (bull.risk_pct > 0) & (bull.risk_pct <= x))]


def stats(df, h, label):
    d = df.dropna(subset=[f"r{h}"]).copy()
    if len(d) == 0:
        return f"{label:48s} (ডেটা নেই)"
    d["x"] = d[f"r{h}"] - d["date"].map(base[h])
    net = d[f"r{h}"] - COST
    wk = d.groupby("week")["x"].mean()
    se = wk.std(ddof=1) / math.sqrt(len(wk)) if len(wk) > 1 else float("nan")
    t = d["x"].mean() / se if se and se == se else float("nan")
    return (f"{label:48s} {len(d):5d} {d.week.nunique():4d} {net.mean():7.2f} {net.median():7.2f} "
            f"{(net > 0).mean() * 100:5.1f} | {d['x'].mean():6.2f} {t:5.1f}")


HDR = f"{'গ্রুপ':48s} {'n':>5s} {'সপ্ত':>4s} {'net%':>7s} {'মধ্যক':>7s} {'জয়%':>5s} | {'অতি%':>6s} {'t':>5s}"


def block(title, df):
    print(f"\n### {title}")
    for h in HOLDS:
        print(f"-- hold {h} দিন")
        print(HDR)
        for half in ("TRAIN", "TEST"):
            print(stats(df[df.half == half], h, f"{half}"))
        print(stats(df, h, "সব"))


print(f"সংকেত-সময়কাল {sig.date.min().date()} → {sig.date.max().date()} | ভাগের তারিখ {mid.date()} | খরচ {COST}%")
for h in HOLDS:
    for half, a, b in (("TRAIN", sig.date.min(), mid), ("TEST", mid, sig.date.max())):
        r = base[h].loc[a:b]
        print(f"বেসলাইন (লিকুইড গড়) hold {h} {half}: গ্রস {r.mean():.2f}% → net {r.mean() - COST:.2f}%")

block("A. বর্তমান v2 SIGNAL বুলিশ", S)
for x in (12, 15, 20):
    block(f"B. স্টপ-গেট {x}% (বাকি সব গেট একই)", stop_relax(x))
block("C. v2 SIGNAL + বাজার ঊর্ধ্বমুখী (DSEX > SMA50)", S[S.mkt_up == True])
block("D. v2 SIGNAL + RS60 > ০ (ইনডেক্সের চেয়ে ৬০ দিনে বেশি)", S[S.rs60 > 0])
block("E. স্টপ-গেট ১৫% + বাজার ঊর্ধ্বমুখী + RS60 > ০", stop_relax(15)[lambda d: (d.mkt_up == True) & (d.rs60 > 0)])

block("G1. v2 SIGNAL + RS60 < ০ (ইনডেক্সের চেয়ে দুর্বল; অনুমান TRAIN থেকে)", S[S.rs60 < 0])
block("G2. স্টপ-গেট ১৫% + RS60 < ০", stop_relax(15)[lambda d: d.rs60 < 0])

# ---------- Wyckoff ছাড়া: শুধু-শক্তি ও শুধু-বাজার-ফিল্টার ----------
print("\n### F. Wyckoff ছাড়া তুলনা (প্রতিদিন লিকুইড কোডের মধ্যে)")
rows = []
for d in sig.date.sort_values().unique():
    d = pd.Timestamp(d)
    if d not in C.index:
        continue
    L = liq.loc[d]
    r = (ret60.loc[d] - dx60.loc[d]).where(L).dropna()
    if len(r) < 30:
        continue
    top = r[r >= r.quantile(0.9)].index
    bot = r[r <= r.quantile(0.1)].index
    for h in HOLDS:
        rows.append({"date": d, "h": h, "grp": "শক্তি-শীর্ষ ১০%", "g": fwd[h].loc[d, top].mean(), "mkt": bool(mkt_up.loc[d])})
        rows.append({"date": d, "h": h, "grp": "শক্তি-তলানি ১০%", "g": fwd[h].loc[d, bot].mean(), "mkt": bool(mkt_up.loc[d])})
        rows.append({"date": d, "h": h, "grp": "সব লিকুইড কোড", "g": base[h].loc[d], "mkt": bool(mkt_up.loc[d])})
R = pd.DataFrame(rows).dropna()
R["half"] = np.where(R.date < mid, "TRAIN", "TEST")
R["week"] = R.date.dt.strftime("%G-%V")
for h in HOLDS:
    print(f"-- hold {h} দিন (প্রতিদিনের গড় গ্রস, ওভারল্যাপিং, খরচ {COST}% বাদে)")
    print(f"{'গ্রুপ / ভাগ':40s} {'দিন':>4s} {'net%':>7s}")
    for grp in ("সব লিকুইড কোড", "শক্তি-শীর্ষ ১০%"):
        for half in ("TRAIN", "TEST"):
            q = R[(R.h == h) & (R.grp == grp) & (R.half == half)]
            print(f"{grp + ' ' + half:40s} {len(q):4d} {q.g.mean() - COST:7.2f}")
        q = R[(R.h == h) & (R.grp == "সব লিকুইড কোড")]
        for half in ("TRAIN", "TEST"):
            for m in (True, False):
                z = q[(q.half == half) & (q.mkt == m)]
                if grp == "সব লিকুইড কোড":
                    print(f"  বাজার {'ঊর্ধ্ব' if m else 'নিম্ন'} {half:5s} (সব লিকুইড কোড, দিন {len(z)})  net {z.g.mean() - COST:7.2f}")
        break
    for gname in ("শক্তি-শীর্ষ ১০%", "শক্তি-তলানি ১০%"):
        for half in ("TRAIN", "TEST"):
            a = R[(R.h == h) & (R.grp == gname) & (R.half == half)]
            b = R[(R.h == h) & (R.grp == "সব লিকুইড কোড") & (R.half == half)].set_index("date").g
            ex = a.set_index("date").g - b
            wk = ex.groupby(ex.index.strftime("%G-%V")).mean()
            t = ex.mean() / (wk.std(ddof=1) / math.sqrt(len(wk))) if len(wk) > 1 else float("nan")
            print(f"  {gname} বনাম সব-লিকুইড অতিরিক্ত {half}: {ex.mean():.2f}% (t≈{t:.1f}, সপ্তাহ {len(wk)}), net {a.g.mean() - COST:.2f}%")
