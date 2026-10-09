#!/usr/bin/env python3
import re
"""
Compute sector-level summary from prices.csv, sectors.csv, fundamentals.csv.
Output: docs/data/sector_summary.json and data/sector_summary.json
"""
import csv
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def read_csv_safe(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def to_float(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, AttributeError, TypeError):
        return None


def load_prices():
    """Return {symbol: {date: close}}"""
    rows = read_csv_safe("data/prices.csv") or read_csv_safe("docs/data/prices.csv")
    by_sym = defaultdict(dict)
    for r in rows:
        sym = (r.get("TRADING CODE") or r.get("CODE") or r.get("SYMBOL") or "").strip().upper()
        date = (r.get("DATE") or "").strip()
        close = to_float(r.get("CLOSEP") or r.get("LTP"))
        vol = to_float(r.get("VOLUME") or 0)
        if sym and date and close:
            by_sym[sym][date] = {"close": close, "vol": vol or 0}
    return by_sym


def load_sectors():
    rows = read_csv_safe("data/sectors.csv") or read_csv_safe("docs/data/sectors.csv")
    return {r["SYMBOL"].strip().upper(): r["SECTOR"].strip()
            for r in rows if r.get("SYMBOL")}


def load_fundamentals():
    rows = read_csv_safe("data/fundamentals.csv") or read_csv_safe("docs/data/fundamentals.csv")
    if not rows:
        return {}
    # হেডার normalize — space/case বাদ
    def norm(h):
        return re.sub(r"[^a-z0-9]", "", str(h).lower())
    header_map = {norm(k): k for k in rows[0].keys()}
    # খুঁজে বের করি EPS কলামগুলোর আসল নাম
    def find_col(*aliases):
        for a in aliases:
            if a in header_map:
                return header_map[a]
        return None
    col_q1 = find_col("epsq1")
    col_q2 = find_col("epsq2")
    col_h1 = find_col("epsh1")
    col_q3 = find_col("epsq3")
    col_9m = find_col("eps9m")
    col_ann = find_col("epsannual", "epsyearly", "epsannualized")
    col_cat = find_col("category", "cat")
    col_code = find_col("code", "symbol", "tradingcode")
    if not col_code:
        return {}
    eps_cols = [col_q1, col_q2, col_h1, col_q3, col_9m, col_ann]
    out = {}
    for r in rows:
        sym = (r.get(col_code) or "").strip().upper()
        if not sym:
            continue
        eps_vals = [to_float(r.get(c)) if c else None for c in eps_cols]
        last_eps = next((v for v in reversed(eps_vals) if v is not None), None)
        out[sym] = {
            "eps": last_eps,
            "cat": (r.get(col_cat) or "").strip().upper() if col_cat else "",
        }
    return out


def compute_sector_summary():
    prices = load_prices()
    sectors = load_sectors()
    fund = load_fundamentals()

    # Per-sector accumulation
    bucket = defaultdict(lambda: {
        "symbols": [],
        "changes_1d": [], "changes_5d": [], "changes_20d": [],
        "volumes": [], "eps": [], "cats": defaultdict(int),
    })

    for sym, bars in prices.items():
        sector = sectors.get(sym, "Unknown")
        dates = sorted(bars.keys())
        if len(dates) < 21:
            continue
        last = bars[dates[-1]]["close"]
        prev = bars[dates[-2]]["close"]
        d5 = bars[dates[-6]]["close"] if len(dates) >= 6 else None
        d20 = bars[dates[-21]]["close"] if len(dates) >= 21 else None

        ch1 = (last / prev - 1) * 100 if prev else 0
        ch5 = (last / d5 - 1) * 100 if d5 else None
        ch20 = (last / d20 - 1) * 100 if d20 else None

        # Average volume last 20 days
        vol20 = sum(bars[d]["vol"] for d in dates[-20:]) / 20

        b = bucket[sector]
        b["symbols"].append(sym)
        b["changes_1d"].append(ch1)
        if ch5 is not None:
            b["changes_5d"].append(ch5)
        if ch20 is not None:
            b["changes_20d"].append(ch20)
        b["volumes"].append(vol20)
        if sym in fund and fund[sym]["eps"] is not None:
            b["eps"].append(fund[sym]["eps"])
        if sym in fund:
            b["cats"][fund[sym]["cat"]] += 1

    def avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else None

    result = []
    for sector, b in bucket.items():
        n = len(b["symbols"])
        if n == 0:
            continue
        result.append({
            "sector": sector,
            "companies": n,
            "avg_change_1d": avg(b["changes_1d"]),
            "avg_change_5d": avg(b["changes_5d"]),
            "avg_change_20d": avg(b["changes_20d"]),
            "avg_volume": int(avg(b["volumes"]) or 0),
            "avg_eps": avg(b["eps"]),
            "eps_count": len(b["eps"]),
            "cat_a": b["cats"].get("A", 0),
            "cat_b": b["cats"].get("B", 0),
            "cat_z": b["cats"].get("Z", 0),
            "symbols": sorted(b["symbols"]),
        })

    # Sort by 20-day change desc
    result.sort(key=lambda x: (x["avg_change_20d"] is None, -(x["avg_change_20d"] or 0)))
    return result


def save(payload):
    txt = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for p in ("docs/data/sector_summary.json", "data/sector_summary.json"):
        path = Path(p)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(txt)
        tmp.replace(path)
        print(f"Saved {len(payload)} sectors → {p}")


if __name__ == "__main__":
    print("Computing sector summary...")
    save(compute_sector_summary())
