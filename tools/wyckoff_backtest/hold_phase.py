"""একটি Wyckoff ফেজের সংকেতে কিনে ২০/৩০/৪০ ট্রেডিং-দিন (≈ ১–২ মাস) ধরে রাখলে ফল কেমন হতো।

আগের backtest.py-এর সংকেত-তালিকা (out_signals.csv) থেকে ফেজ বেছে নেয়, প্রতিটি সংকেতের পরদিন OPEN-এ কিনে t+hold ক্লোজে বেচে।
ইউনিভার্স-বেসলাইন: সেই দিন সব কোড (সংকেত থাকুক বা না থাকুক) একই নিয়মে কিনলে গড় রিটার্ন।

চালান:
  python3 tools/wyckoff_backtest/hold_phase.py out_signals.csv docs/data/prices.csv Accumulation [খরচ%=0.5]
"""
import math
import re
import sys

import numpy as np
import pandas as pd

sig_csv, prices_csv, PHASE = sys.argv[1:4]
COST = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
HOLDS = (20, 30, 40)
W = 260
MF = re.compile(r"MF$|^1STMF|^2NDMF|^3RDMF|GROWTHFUND|INCOMEFUND|MUTUALFUND|BONDFUND|BOND$")

d = pd.read_csv(prices_csv)
d.columns = [x.lower() for x in d.columns]
d = d.rename(columns={"trading code": "sym", "openp": "open", "closep": "close"}).sort_values(["sym", "date"])
d["open"] = d["open"].fillna(d["ycp"]).fillna(d["close"])  # ট্রেড-না-হওয়া দিনে ওপেন = আগের ক্লোজ

# ---- প্রতিটি (কোড, দিন)-এর জন্য ফরওয়ার্ড রিটার্ন: পরদিন OPEN-এ কিনে t+h ক্লোজে বেচা ----
parts = []
for s, g in d.groupby("sym"):
    if MF.search(s.upper()) or len(g) < W + 2:
        continue
    g = g.reset_index(drop=True)
    o_next = g["open"].shift(-1)
    out = pd.DataFrame({"sym": s, "date": g["date"], "vol": g["volume"], "o_next": o_next, "idx": np.arange(len(g))})
    for h in HOLDS:
        out[f"r{h}"] = (g["close"].shift(-h) / o_next - 1) * 100
    parts.append(out[out.idx >= W - 1])
F = pd.concat(parts, ignore_index=True)
F = F[(F.vol > 0) & (F.o_next > 0)]
uni = F.groupby("date")[[f"r{h}" for h in HOLDS]].mean()

sig = pd.read_csv(sig_csv, parse_dates=["date"])
sig["date"] = sig["date"].dt.strftime("%Y-%m-%d")
S = sig[sig.phase == PHASE][["sym", "date", "score", "entry", "spring"]].merge(F[["sym", "date"] + [f"r{h}" for h in HOLDS]], on=["sym", "date"], how="left")
for h in HOLDS:
    S[f"u{h}"] = S["date"].map(uni[f"r{h}"])
S["ts"] = pd.to_datetime(S["date"])
S["week"] = S["ts"].dt.strftime("%G-%V")
S["qtr"] = S["ts"].dt.year.astype(str) + "Q" + S["ts"].dt.quarter.astype(str)


def non_overlap(df, h):
    """একই কোডে আগের ট্রেড চলাকালীন নতুন সংকেত ধরা হয় না (প্রায় h ট্রেডিং-দিন = h*1.45 ক্যালেন্ডার-দিন)।"""
    keep, last = [], {}
    for i, r in df.sort_values(["sym", "ts"]).iterrows():
        if r.sym not in last or (r["ts"] - last[r.sym]).days >= h * 1.45:
            keep.append(i)
            last[r.sym] = r["ts"]
    return df.loc[keep]


def summ(df, h, label):
    x = df.dropna(subset=[f"r{h}"])
    if x.empty:
        return f"{label:28s} (ডেটা নেই)"
    net = x[f"r{h}"] - COST
    ex = x[f"r{h}"] - x[f"u{h}"]
    wk = x.assign(v=net).groupby("week")["v"].mean()
    se = wk.std(ddof=1) / math.sqrt(len(wk)) if len(wk) > 1 else float("nan")
    wkx = x.assign(v=ex).groupby("week")["v"].mean()
    sex = wkx.std(ddof=1) / math.sqrt(len(wkx)) if len(wkx) > 1 else float("nan")
    win = net[net > 0]
    los = net[net <= 0]
    return (f"{label:28s} {len(x):5d} {x.sym.nunique():5d} {net.mean():7.2f} {net.median():7.2f} {(net > 0).mean() * 100:5.1f} "
            f"{win.mean() if len(win) else float('nan'):6.1f} {los.mean() if len(los) else float('nan'):7.1f} {net.min():7.1f} "
            f"| {ex.mean():6.2f} {ex.mean() / sex if sex == sex and sex else float('nan'):5.1f}")


H = f"{'গ্রুপ':28s} {'n':>5s} {'কোড':>5s} {'গড়%':>7s} {'মধ্যক%':>7s} {'জয়%':>5s} {'গড়জয়':>6s} {'গড়লোকসান':>7s} {'সবচেয়ে খারাপ':>7s} | {'অতি%':>6s} {'t':>5s}"
print(f"ফেজ: {PHASE} | খরচ {COST}% | মোট সংকেত-সারি {len(S)} | তারিখ {S.date.min()} থেকে {S.date.max()}")
print("(গড়/মধ্যক/জয়% সব খরচ বাদে। 'অতি%' = বাজারের সেই দিনের গড়ের চেয়ে বেশি। t সংকেত-সপ্তাহ ধরে ক্লাস্টার করা।)")
for h in HOLDS:
    print(f"\n===== {h} ট্রেডিং-দিন ধরে রাখলে (≈ {h / 20:.1f} মাস) =====")
    print(H)
    print(summ(S, h, f"{PHASE} (সব সারি)"))
    print(summ(non_overlap(S, h), h, f"{PHASE} (ওভারল্যাপ বাদে)"))
    print(summ(S[S.entry], h, "  Spring+ক্যান্ডেল (Entry)"))
    print(summ(S[~S.entry], h, "  শুধু ফেজ, Entry নয়"))
    print(summ(S[S.score >= 70], h, "  স্কোর ≥ ৭০"))
    u = uni[f"r{h}"].dropna()
    print(f"{'(পুরো বাজার, প্রতিদিন গড়)':28s} {'':5s} {'':5s} {u.mean() - COST:7.2f}")

h = 30
print(f"\n===== ত্রৈমাসিক ভাগ ({PHASE}, ওভারল্যাপ বাদে, {h} দিন) =====")
N = non_overlap(S, h).dropna(subset=[f"r{h}"])
print(f"{'qtr':7s} {'n':>5s} {'গড়%':>7s} {'জয়%':>5s} {'বাজার%':>7s}")
for q, g in N.groupby("qtr"):
    print(f"{q:7s} {len(g):5d} {g[f'r{h}'].mean() - COST:7.2f} {(g[f'r{h}'] - COST > 0).mean() * 100:5.1f} {g[f'u{h}'].mean() - COST:7.2f}")
print(f"\nসবচেয়ে বেশি সংকেত দেওয়া কোড ({h} দিন, ওভারল্যাপ বাদে): {N.sym.value_counts().head(5).to_dict()}")
