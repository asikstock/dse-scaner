"""Wyckoff স্ক্যানারের walk-forward ব্যাকটেস্ট (শুধু সেই দিনের পর্যন্ত ডেটা দেখে সংকেত, ভবিষ্যৎ দেখা নেই)।

প্রতিটি কোডের প্রতিটি দিন t-তে শেষ W বারে wyckoff_scanner.analyze() চালায়।
- এন্ট্রি: t+1 দিনের OPEN। এক্সিট: t+hold দিনের CLOSE (hold দিন ধরে রাখা)।
- 'levels' বিকল্প: স্ক্যানারের নিজের stop_loss/target ধরে সর্বোচ্চ ২০ দিন; একই দিনে দুটোই ছুঁলে স্টপ আগে ধরা হয়।
- সব দিনের (সংকেত না থাকলেও) ফরওয়ার্ড রিটার্নও রাখা হয়, যাতে প্রতিদিনের "পুরো বাজারের গড়" বেসলাইন হিসাব করা যায়।

চালান:
  python3 tools/wyckoff_backtest/backtest.py docs/data/prices.csv out_signals.csv out_universe.csv
"""
import os
import re
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from wyckoff_scanner import Config, analyze  # noqa: E402

W = 260                      # প্রতি বিশ্লেষণে বার সংখ্যা (SMA200 + রেঞ্জ + ট্রেন্ডের জন্য যথেষ্ট)
HOLDS = (5, 10, 20)
LEVEL_MAX = 20
MF = re.compile(r"MF$|^1STMF|^2NDMF|^3RDMF|GROWTHFUND|INCOMEFUND|MUTUALFUND|BONDFUND|BOND$")


def _levels_exit(o, h, l, c, t, stop, target):
    """t+1 ওপেনে কিনে স্টপ/টার্গেট/টাইম-এক্সিটের রিটার্ন (গ্রস, %)।"""
    n = len(c)
    entry = o[t + 1]
    last = min(t + LEVEL_MAX, n - 1)
    if last < t + LEVEL_MAX:
        return np.nan
    for j in range(t + 1, last + 1):
        lo, hi = l[j], h[j]
        if j == t + 1 and o[j] <= stop:
            return (o[j] / entry - 1) * 100
        if lo <= stop:
            return (stop / entry - 1) * 100
        if hi >= target:
            return (target / entry - 1) * 100
    return (c[last] / entry - 1) * 100


def run_symbol(args):
    sym, df = args
    df = df.reset_index(drop=True)
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    dates = df["date"].to_numpy()
    n = len(df)
    sig, uni = [], []
    for t in range(W - 1, n - 1):
        if v[t] <= 0 or v[t - 19:t + 1].mean() <= 0 or o[t + 1] <= 0:
            continue
        win = df.iloc[t - W + 1:t + 1]
        try:
            r = analyze(win, Config())
        except Exception:
            continue
        fwd = {hd: ((c[t + hd] / o[t + 1] - 1) * 100 if t + hd < n else np.nan) for hd in HOLDS}
        uni.append({"date": dates[t], **{f"r{hd}": fwd[hd] for hd in HOLDS}})
        if not r.get("phase"):
            continue
        row = {
            "sym": sym, "date": dates[t], "phase": r["phase"], "score": r["score"], "bias": r["bias"],
            "entry": bool(r["entry_signal"]), "spring": r["flags"]["spring"], "upthrust": r["flags"]["upthrust"],
            "sos": r["flags"]["SOS"], "sow": r["flags"]["SOW"],
            "close": r["close"], "support": r["support"], "resistance": r["resistance"],
            "stop": r["stop_loss"], "target": r["target"],
            **{f"r{hd}": fwd[hd] for hd in HOLDS},
        }
        row["rlevels"] = (_levels_exit(o, h, l, c, t, r["stop_loss"], r["target"])
                          if r["bias"] == "BULLISH" else np.nan)
        sig.append(row)
    return sig, uni


def main(prices_csv, out_sig, out_uni):
    d = pd.read_csv(prices_csv)
    d.columns = [x.lower() for x in d.columns]
    d = d.rename(columns={"trading code": "sym", "openp": "open", "closep": "close"})
    d = d.sort_values(["sym", "date"])
    jobs = [(s, g[["date", "open", "high", "low", "close", "volume"]]) for s, g in d.groupby("sym")
            if not MF.search(s.upper()) and len(g) >= W + 2]
    print(f"{len(jobs)} কোড, প্রতিটি W={W} বার", file=sys.stderr)
    sig, uni = [], []
    with Pool(max(1, os.cpu_count() or 1)) as p:
        for i, (s, u) in enumerate(p.imap_unordered(run_symbol, jobs, chunksize=4), 1):
            sig += s
            uni += u
            if i % 50 == 0:
                print(f"{i}/{len(jobs)}", file=sys.stderr)
    pd.DataFrame(sig).to_csv(out_sig, index=False)
    u = pd.DataFrame(uni).groupby("date").agg(n=("r5", "size"), **{f"r{hd}": (f"r{hd}", "mean") for hd in HOLDS})
    u.to_csv(out_uni)
    print(f"সংকেত-সারি {len(sig)}, ইউনিভার্স-দিন {len(u)}", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:4])
