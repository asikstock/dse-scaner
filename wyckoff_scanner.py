"""
Wyckoff Phase Scanner
ফেজ: Accumulation, Re-accumulation, Markup, Distribution, Re-distribution, Markdown

ইনপুট: DataFrame, কলাম: open, high, low, close, volume (পুরনো -> নতুন, ডেইলি বা যেকোনো টাইমফ্রেম)
ব্যবহার:
    from wyckoff_scanner import analyze
    result = analyze(df)
    CLI:  python wyckoff_scanner.py data/*.csv
"""
from dataclasses import dataclass
import sys
import numpy as np
import pandas as pd


@dataclass
class Config:
    range_len: int = 40        # রেঞ্জ শনাক্তের বার সংখ্যা
    recent: int = 5            # সাম্প্রতিক বার (স্প্রিং/আপথ্রাস্ট/ব্রেকআউট খোঁজার জন্য)
    trend_len: int = 60        # রেঞ্জের আগের ট্রেন্ড মাপার বার সংখ্যা
    trend_pct: float = 0.15    # আগের ট্রেন্ড কমপক্ষে ১৫%
    max_width: float = 0.30    # রেঞ্জের প্রস্থ সর্বোচ্চ ৩০%
    vol_spike: float = 1.5     # ব্রেকআউট/ব্রেকডাউনে ভলিউম গড়ের ১.৫ গুণ
    min_score: int = 60        # সংকেতের ন্যূনতম স্কোর


# ---------------- ইন্ডিকেটর ও ক্যান্ডেল ----------------
def _atr(df, n=14):
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _candles(df):
    o1, c1 = df.open.iloc[-2], df.close.iloc[-2]
    o2, c2, h2, l2 = df.open.iloc[-1], df.close.iloc[-1], df.high.iloc[-1], df.low.iloc[-1]
    body = abs(c2 - o2)
    lower = min(o2, c2) - l2
    upper = h2 - max(o2, c2)
    rng = h2 - l2
    ok = rng > 0
    return {
        "bull_engulf": c1 < o1 and c2 > o2 and c2 >= o1 and o2 <= c1,
        "bear_engulf": c1 > o1 and c2 < o2 and c2 <= o1 and o2 >= c1,
        "hammer": ok and lower >= 2 * body and upper <= max(body, 1e-9) * 0.7,
        "shooting_star": ok and upper >= 2 * body and lower <= max(body, 1e-9) * 0.7,
    }


# ---------------- মূল বিশ্লেষণ ----------------
def analyze(df: pd.DataFrame, cfg: Config = Config()):
    need = cfg.range_len + cfg.recent + cfg.trend_len + 5
    if len(df) < max(need, 210):
        return {"phase": None, "reason": f"ডেটা কম (কমপক্ষে {max(need, 210)} বার দরকার)"}

    df = df.reset_index(drop=True).copy()
    df["sma50"] = df.close.rolling(50).mean()
    df["sma200"] = df.close.rolling(200).mean()
    df["atr"] = _atr(df)
    vol_avg20 = df.volume.rolling(20).mean().iloc[-1]

    n = len(df)
    base = df.iloc[n - cfg.range_len - cfg.recent: n - cfg.recent]
    recent = df.iloc[n - cfg.recent:]
    pre = df.iloc[n - cfg.range_len - cfg.recent - cfg.trend_len: n - cfg.range_len - cfg.recent]

    sup, res = base.low.min(), base.high.max()
    mid = (sup + res) / 2
    width = (res - sup) / mid
    height = res - sup
    last = df.iloc[-1]
    atr = df.atr.iloc[-1]

    # আগের ট্রেন্ড
    pre_ret = pre.close.iloc[-1] / pre.close.iloc[0] - 1
    pre_up, pre_down = pre_ret >= cfg.trend_pct, pre_ret <= -cfg.trend_pct

    # রেঞ্জ আছে কি? (প্রস্থ সীমিত + নেট ড্রিফট কম)
    drift = abs(base.close.iloc[-1] / base.close.iloc[0] - 1)
    is_range = width <= cfg.max_width and drift <= 0.5 * width

    # ভলিউম আচরণ
    half = cfg.range_len // 2
    v1, v2 = base.volume.iloc[:half].mean(), base.volume.iloc[half:].mean()
    contraction = v2 / v1 < 0.85 if v1 > 0 else False          # ভলিউম কমছে
    vol_vs_pre = base.volume.mean() / max(pre.volume.mean(), 1e-9)
    heavy_vol = vol_vs_pre > 1.1                                # আগের চেয়ে বেশি ভলিউম
    up_v = base.volume[base.close > base.open].sum()
    dn_v = base.volume[base.close <= base.open].sum()
    ud = up_v / max(dn_v, 1e-9)                                 # আপ/ডাউন ভলিউম অনুপাত
    pos = (last.close - sup) / max(res - sup, 1e-9)             # রেঞ্জের ভেতরে অবস্থান (০-১)

    # ইভেন্ট (ফেজ সি ইত্যাদি)
    spring = bool(((recent.low < sup) & (recent.close > sup)).any()) and last.close > sup
    upthrust = bool(((recent.high > res) & (recent.close < res)).any()) and last.close < res
    spring_low_vol = spring and recent.volume.mean() <= vol_avg20 * 1.2
    sos = last.close > res and last.volume >= cfg.vol_spike * vol_avg20     # Sign of Strength
    sow = last.close < sup and last.volume >= cfg.vol_spike * vol_avg20     # Sign of Weakness

    up_struct = last.sma50 > last.sma200 and last.close > last.sma50
    dn_struct = last.sma50 < last.sma200 and last.close < last.sma50
    k = df.iloc[-20:]
    hh_hl = k.high.iloc[10:].max() > k.high.iloc[:10].max() and k.low.iloc[10:].min() > k.low.iloc[:10].min()
    ll_lh = k.low.iloc[10:].min() < k.low.iloc[:10].min() and k.high.iloc[10:].max() < k.high.iloc[:10].max()
    hold_sup = recent.low.min() >= sup * 0.99
    hold_res = recent.high.max() <= res * 1.01
    c = _candles(df)

    # ---------------- স্কোরিং ----------------
    S = {}
    S["Accumulation"] = (25 * pre_down + 20 * is_range + 15 * contraction + 25 * spring
                         + 10 * (ud >= 1) + 5 * (pos < 0.5))
    S["Re-accumulation"] = (25 * pre_up + 20 * is_range + 15 * contraction + 15 * up_struct
                            + 10 * (pos >= 0.5) + 15 * hold_sup)
    S["Distribution"] = (25 * pre_up + 20 * is_range + 15 * heavy_vol + 25 * upthrust
                         + 10 * (ud < 1) + 5 * (pos > 0.5))
    S["Re-distribution"] = (25 * pre_down + 20 * is_range + 15 * dn_struct + 15 * hold_res
                            + 15 * (ud < 1) + 10 * (pos < 0.5))
    S["Markup"] = (35 * sos + 15 * (up_struct) + 20 * hh_hl + 15 * is_range + 15 * (last.close > last.sma50))
    S["Markdown"] = (35 * sow + 15 * (dn_struct) + 20 * ll_lh + 15 * is_range + 15 * (last.close < last.sma50))
    S = {k_: int(v) for k_, v in S.items()}

    # প্রাইস রেঞ্জ ভেঙে বেরিয়ে গেলে (SOS/SOW) রেঞ্জ-ভিত্তিক ফেজ আর প্রযোজ্য নয়
    if sos:
        S = {"Markup": S["Markup"]}
    elif sow:
        S = {"Markdown": S["Markdown"]}

    phase, score = max(S.items(), key=lambda kv: kv[1])
    if score < cfg.min_score:
        return {"phase": None, "scores": S, "reason": "স্পষ্ট ওয়াইকফ ফেজ নেই"}

    # ---------------- সংকেত ও লেভেল ----------------
    bias, trigger, entry = "WATCH", "", False
    if phase in ("Accumulation", "Re-accumulation"):
        bias = "BULLISH"
        if spring and (c["bull_engulf"] or c["hammer"]):
            trigger, entry = "Spring/Liquidity Sweep + বুলিশ রিভার্সাল ক্যান্ডেল", True
        elif spring:
            trigger = "Spring হয়েছে, বুলিশ ক্যান্ডেলের কনফার্মেশনের অপেক্ষা"
        else:
            trigger = "রেঞ্জ গঠন চলছে; Spring বা SOS-এর অপেক্ষা"
    elif phase in ("Distribution", "Re-distribution"):
        bias = "BEARISH"
        if upthrust and (c["bear_engulf"] or c["shooting_star"]):
            trigger, entry = "Upthrust + বেয়ারিশ রিভার্সাল ক্যান্ডেল", True
        elif upthrust:
            trigger = "Upthrust হয়েছে, বেয়ারিশ ক্যান্ডেলের কনফার্মেশনের অপেক্ষা"
        else:
            trigger = "রেঞ্জ গঠন চলছে; Upthrust বা SOW-এর অপেক্ষা"
    elif phase == "Markup":
        bias, entry, trigger = "BULLISH", True, "রেঞ্জ ব্রেকআউট + ভলিউম স্পাইক (SOS)"
    elif phase == "Markdown":
        bias, entry, trigger = "BEARISH", True, "সাপোর্ট ব্রেকডাউন + ভলিউম স্পাইক (SOW)"

    if bias == "BULLISH":
        stop = (min(recent.low.min(), sup) if phase != "Markup" else res) - 0.5 * atr
        target = res + height
    else:
        stop = (max(recent.high.max(), res) if phase != "Markdown" else sup) + 0.5 * atr
        target = sup - height

    return {
        "phase": phase, "score": score, "bias": bias, "entry_signal": entry,
        "trigger": trigger, "support": round(sup, 2), "resistance": round(res, 2),
        "stop_loss": round(stop, 2), "target": round(target, 2),
        "close": round(last.close, 2), "scores": S,
        "flags": {"spring": spring, "upthrust": upthrust, "SOS": sos, "SOW": sow,
                  "vol_contraction": contraction, "pre_trend_pct": round(pre_ret * 100, 1)},
    }


def scan(frames: dict, cfg: Config = Config()):
    """frames = {symbol: DataFrame}. সংকেত পাওয়া সিম্বলগুলোর টেবিল ফেরত দেয়।"""
    rows = []
    for sym, df in frames.items():
        try:
            r = analyze(df, cfg)
        except Exception as e:  # খারাপ ডেটা এড়াতে
            continue
        if r.get("phase"):
            rows.append({"symbol": sym, **{k: r[k] for k in
                         ("phase", "score", "bias", "entry_signal", "trigger",
                          "close", "support", "resistance", "stop_loss", "target")}})
    out = pd.DataFrame(rows)
    return out.sort_values(["entry_signal", "score"], ascending=False) if len(out) else out


if __name__ == "__main__":
    import glob
    frames = {}
    for pattern in sys.argv[1:]:
        for f in glob.glob(pattern):
            d = pd.read_csv(f)
            d.columns = [x.lower() for x in d.columns]
            frames[f.split("/")[-1].rsplit(".", 1)[0]] = d
    res = scan(frames)
    print(res.to_string(index=False) if len(res) else "কোনো সংকেত নেই")
