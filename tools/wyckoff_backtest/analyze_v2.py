"""v2 স্ক্যানারের walk-forward ফল: SIGNAL বনাম WATCH, আর গেটগুলো আসলে কিছু যোগ করছে কি না।

চালান:
  python3 tools/wyckoff_backtest/analyze_v2.py out_signals_v2.csv docs/data/prices.csv [পুরনো_v1_out_signals.csv] [খরচ%=0.5]

- net = গ্রস রিটার্ন − খরচ। 'অতি%' = ট্রেডের গ্রস − সেই দিনের *লিকুইড* কোডগুলোর গড় গ্রস (একই hold)।
  লিকুইড = SIGNAL-এর লিকুইডিটি-গেটের সমান শর্ত (২০ দিনের গড় লেনদেন ≥ ৩০ লাখ, শেষ ৪০ দিনে শূন্য-ভলিউম ≤ ৪, আজ ট্রেড হয়েছে)।
  সব কোডের (অলিকুইডসহ) গড়ের সঙ্গে তুলনা করলে অলিকুইড শেয়ারের লাফ বেসলাইন ফুলিয়ে দেয়, আবার সেগুলো বাস্তবে কেনা যায় না।
- t-মান সংকেত-সপ্তাহ ধরে ক্লাস্টার করা। n ছোট হলে (≈ ৩০-এর নিচে) t-কে গুরুত্ব দেবেন না।
"""
import math
import sys

import numpy as np
import pandas as pd

import re

sig = pd.read_csv(sys.argv[1], parse_dates=["date"])
old = pd.read_csv(sys.argv[3], parse_dates=["date"]) if len(sys.argv) > 3 and sys.argv[3].endswith(".csv") else None
COST = float(sys.argv[-1]) if sys.argv[-1].replace(".", "").isdigit() else 0.5
HOLDS = (10, 20, 40)
MF = re.compile(r"MF$|^1STMF|^2NDMF|^3RDMF|GROWTHFUND|INCOMEFUND|MUTUALFUND|BONDFUND|BOND$")

# ---- বেসলাইন: প্রতিদিন (ক) সব কোড, (খ) শুধু লিকুইড কোড কিনলে গড় গ্রস রিটার্ন (পরদিন OPEN → t+h CLOSE) ----
px = pd.read_csv(sys.argv[2])
px.columns = [x.lower() for x in px.columns]
px = px.rename(columns={"trading code": "sym", "openp": "open", "closep": "close"}).sort_values(["sym", "date"])
parts = []
for sym, g in px.groupby("sym"):
    if MF.search(sym.upper()) or len(g) < 262:
        continue
    g = g.reset_index(drop=True)
    o_next = g["open"].shift(-1)
    f = pd.DataFrame({"date": g["date"], "ok": (g["volume"] > 0) & (o_next > 0)})
    for h in HOLDS:
        f[f"r{h}"] = (g["close"].shift(-h) / o_next - 1) * 100
    f["liq"] = ((g["volume"] * g["close"]).rolling(20).mean() >= 3e6) & ((g["volume"] == 0).rolling(40).sum() <= 4)
    parts.append(f.iloc[259:])
F = pd.concat(parts, ignore_index=True)
F = F[F.ok]
F["date"] = pd.to_datetime(F["date"])
uni = F.groupby("date")[[f"r{h}" for h in HOLDS]].mean()                 # সব কোড
uniL = F[F.liq].groupby("date")[[f"r{h}" for h in HOLDS]].mean()         # শুধু লিকুইড


def prep(df):
    df = df.copy()
    df["week"] = df["date"].dt.strftime("%G-%V")
    for h in HOLDS:
        if f"r{h}" in df:
            df[f"x{h}"] = df[f"r{h}"] - df["date"].map(uniL[f"r{h}"])
    return df


def row(label, df, h):
    d = df.dropna(subset=[f"r{h}"])
    if len(d) == 0:
        return f"{label:44s} (ডেটা নেই)"
    net = d[f"r{h}"] - COST
    wk = d.assign(v=d[f"x{h}"]).groupby("week")["v"].mean()
    se = wk.std(ddof=1) / math.sqrt(len(wk)) if len(wk) > 1 else float("nan")
    t = d[f"x{h}"].mean() / se if se and se == se else float("nan")
    return (f"{label:44s} {len(d):5d} {d.week.nunique():5d} {net.mean():7.2f} {net.median():7.2f} {(net > 0).mean() * 100:5.1f} "
            f"| {d[f'x{h}'].mean():6.2f} {t:5.1f}")


sig = prep(sig)
H = f"{'গ্রুপ':44s} {'n':>5s} {'সপ্তাহ':>5s} {'net%':>7s} {'মধ্যক%':>7s} {'জয়%':>5s} | {'অতি%':>6s} {'t':>5s}"
S = sig[sig.tier == "SIGNAL"]
days = sig.date.nunique()
per_day = S.groupby("date").size().reindex(sorted(sig.date.unique()), fill_value=0)
print(f"খরচ {COST}% | তারিখ {sig.date.min().date()} থেকে {sig.date.max().date()} | ফেজ-সারি {len(sig)} | SIGNAL {len(S)} (WATCH {len(sig) - len(S)})")
print(f"প্রতিদিন গড়ে SIGNAL: {per_day.mean():.1f} | মধ্যক {per_day.median():.0f} | সর্বোচ্চ {per_day.max()} | সংকেতহীন দিন {(per_day == 0).mean() * 100:.0f}%")
print("SIGNAL ফেজ অনুযায়ী:", S.groupby(["phase", "bias"]).size().to_dict())

for h in HOLDS:
    print(f"\n===== hold {h} ট্রেডিং-দিন =====")
    print(H)
    print(row("SIGNAL বুলিশ (সব)", S[S.bias == "BULLISH"], h))
    for ph in ("Accumulation", "Re-accumulation", "Markup"):
        print(row(f"  {ph}", S[(S.bias == "BULLISH") & (S.phase == ph)], h))
    print(row("SIGNAL বেয়ারিশ (এড়ানোর) (সব)", S[S.bias == "BEARISH"], h))
    for ph in ("Distribution", "Re-distribution", "Markdown"):
        print(row(f"  {ph}", S[(S.bias == "BEARISH") & (S.phase == ph)], h))
    W = sig[sig.tier == "WATCH"]
    print(row("WATCH বুলিশ (সংকেত নয়)", W[W.bias == "BULLISH"], h))
    print(row("WATCH বেয়ারিশ", W[W.bias == "BEARISH"], h))
    print(f"{'(বেসলাইন, খরচ বাদে) সব কোড / লিকুইড কোড':44s} {'':5s} {'':5s} {uni[f'r{h}'].mean() - COST:7.2f} / {uniL[f'r{h}'].mean() - COST:.2f}")

print("\n===== গেটগুলো কি কিছু যোগ করছে? (শুধু ইভেন্ট-হওয়া Markup, বুলিশ; hold 20) =====")
M = sig[(sig.phase == "Markup")]
print(H)
print(row("Markup, সব গেট পাস (SIGNAL)", M[M.tier == "SIGNAL"], 20))
for key, lab in (("স্টপ", "শুধু ঝুঁকি-গেটে ফেল (স্টপ বেশি দূরে)"), ("ভলিউম", "ভলিউম-প্রমাণে ফেল"), ("লেনদেন", "লিকুইডিটিতে ফেল"), ("ক্যান্ডেল", "ক্যান্ডেল দুর্বল")):
    sel = M[(M.tier == "WATCH") & M.why_not.fillna("").str.contains(key)]
    print(row(f"Markup WATCH: {lab}", sel, 20))

if old is not None:
    old = prep(old)
    ob = old[(old.bias == "BULLISH") & old.entry]
    print("\n===== পুরনো (v1) বনাম নতুন (v2): বুলিশ Entry/SIGNAL, একই সময়কাল =====")
    for h in (x for x in HOLDS if f"r{x}" in old):
        print(f"-- hold {h}"); print(H)
        print(row("v1 বুলিশ Entry (পুরনো নিয়ম)", ob, h))
        print(row("v2 বুলিশ SIGNAL (নতুন নিয়ম)", S[S.bias == "BULLISH"], h))
    print(f"\nv1 বুলিশ Entry সারি {len(ob)} ({len(ob) / old.date.nunique():.1f}/দিন) → v2 বুলিশ SIGNAL {len(S[S.bias == 'BULLISH'])} ({len(S[S.bias == 'BULLISH']) / sig.date.nunique():.2f}/দিন)")
