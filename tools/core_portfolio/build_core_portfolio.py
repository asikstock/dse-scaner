"""প্রতিষ্ঠান-ধাঁচের "মূল পোর্টফোলিও" (core portfolio) প্রার্থী তালিকা বানায়।

চালান:  python3 tools/core_portfolio/build_core_portfolio.py docs/data out_candidates.json

নিয়ম (সবই দাম ও ফান্ডামেন্টাল ফাইল থেকে, কোনো চার্ট-সংকেত নয়):
 1. মিউচুয়াল ফান্ড/বন্ড বাদ। ক্যাটাগরি A বা B।
 2. লিকুইড: ২০ দিনের গড় লেনদেন ≥ ৩০ লাখ টাকা, শেষ ৪০ দিনে শূন্য-ভলিউম ≤ ৪, শেষ দিনে ট্রেড হয়েছে।
 3. ইপিএস: রিপোর্ট হওয়া ত্রৈমাসিকগুলোর (Q1, Q2, Q3) সবকটি ধনাত্মক, অন্তত ২টি রিপোর্ট করা।
 4. কম-অস্থির: লিকুইড কোডগুলোর মধ্যে ৬০ দিনের দৈনিক রিটার্নের স্ট্যান্ডার্ড ডেভিয়েশন সবচেয়ে কম ৩০%-এর মধ্যে
    (tools/wyckoff_backtest-এর পাশের পরীক্ষায় এই গ্রুপ দুই অর্ধেই গড়ের চেয়ে ভালো ও কম ঝুঁকির ছিল; অতিরিক্ত রিটার্ন ছোট, t ≈ ১–১.৭)।
 5. কম অস্থিরতা আগে; এক সেক্টরে সর্বোচ্চ ২টি; সর্বোচ্চ N টি।
 6. ওজন ∝ ১ / অস্থিরতা (inverse-volatility), এক শেয়ারে সর্বোচ্চ ১৫%।
P/E এখানে শুধু তথ্য হিসেবে দেখানো হয় (বাছাইয়ে ব্যবহৃত নয়), কারণ এটি ব্যাকটেস্ট করা যায়নি।
"""
import json
import os
import re
import sys

import numpy as np
import pandas as pd

MF = re.compile(r"MF$|^1STMF|^2NDMF|^3RDMF|GROWTHFUND|INCOMEFUND|MUTUALFUND|BONDFUND|BOND$")
N_MAX, PER_SECTOR, CAP_W, VOL_Q = 12, 2, 0.15, 0.30


def weights(vols, cap):
    w = 1 / np.array(vols, float)
    w = w / w.sum()
    for _ in range(50):
        over = w > cap
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        free = ~over
        if not free.any():
            break
        w[free] += excess * w[free] / w[free].sum()
    return w / w.sum()


def main(data_dir, out):
    px = pd.read_csv(os.path.join(data_dir, "prices.csv"))
    px.columns = [x.lower() for x in px.columns]
    px = px.rename(columns={"trading code": "sym", "openp": "open", "closep": "close"})
    px = px[~px.sym.str.upper().map(lambda s: bool(MF.search(s)))]
    px["date"] = pd.to_datetime(px["date"])
    C = px.pivot(index="date", columns="sym", values="close").sort_index()
    V = px.pivot(index="date", columns="sym", values="volume").reindex_like(C).fillna(0)
    last = C.index[-1]
    liq = ((V * C).rolling(20).mean() >= 3e6) & ((V == 0).rolling(40).sum() <= 4) & (V > 0)
    vol60 = C.pct_change().rolling(60).std() * 100
    ret60 = (C / C.shift(60) - 1) * 100
    fund = pd.read_csv(os.path.join(data_dir, "fundamentals.csv")).set_index("CODE")
    sec = pd.read_csv(os.path.join(data_dir, "sectors.csv")).set_index("SYMBOL")["SECTOR"]

    u = vol60.loc[last].where(liq.loc[last]).dropna()
    cut = u.quantile(VOL_Q)
    pool, why = [], {"ক্যাটাগরি A/B নয়": 0, "ইপিএস শর্ত ফেল": 0}
    for s in u[u <= cut].sort_values().index:
        f = fund.loc[s] if s in fund.index else None
        if f is None or f["CATEGORY"] not in ("A", "B"):
            why["ক্যাটাগরি A/B নয়"] += 1
            continue
        q = [f[k] for k in ("EPS_Q1", "EPS_Q2", "EPS_Q3") if pd.notna(f[k])]
        if len(q) < 2 or min(q) <= 0:
            why["ইপিএস শর্ত ফেল"] += 1
            continue
        cum = f["EPS_9M"] if pd.notna(f["EPS_9M"]) else f["EPS_H1"] if pd.notna(f["EPS_H1"]) else f["EPS_Q1"]
        k = 4 / 3 if pd.notna(f["EPS_9M"]) else 2 if pd.notna(f["EPS_H1"]) else 4
        pool.append(dict(sym=s, cat=f["CATEGORY"], sector=str(sec.get(s, "Unknown")), close=float(C.at[last, s]),
                         vol=float(u[s]), r60=float(ret60.at[last, s]), eps_cum=float(cum), eps_q=[float(x) for x in q],
                         pe=float(C.at[last, s] / (cum * k)) if cum > 0 else None,
                         turnover_lakh=float((V[s] * C[s]).tail(20).mean() / 1e5)))
    picks, cnt = [], {}
    for p in pool:
        if cnt.get(p["sector"], 0) >= PER_SECTOR:
            continue
        cnt[p["sector"]] = cnt.get(p["sector"], 0) + 1
        picks.append(p)
        if len(picks) == N_MAX:
            break
    if picks:
        for p, w in zip(picks, weights([p["vol"] for p in picks], CAP_W)):
            p["w"] = float(w)
    json.dump(dict(asof=str(last.date()), universe=int(len(u)), vol_cut=float(cut), pool=len(pool), why=why,
                   n_max=N_MAX, per_sector=PER_SECTOR, cap_w=CAP_W, picks=picks), open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{last.date()} | লিকুইড {len(u)} | কম-অস্থির সীমা {cut:.2f}% | যোগ্য {len(pool)} | নির্বাচিত {len(picks)}")
    for p in picks:
        print(f"{p['sym']:12s} {p['cat']} {p['sector'][:22]:22s} দাম {p['close']:8.1f} অস্থিরতা {p['vol']:.2f}% ওজন {p['w']*100:5.1f}% P/E~{p['pe']:.1f} r60 {p['r60']:6.1f}%")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
