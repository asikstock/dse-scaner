"""
Wyckoff Phase Scanner (v2: কড়া সংকেত)
ফেজ: Accumulation, Re-accumulation, Markup, Distribution, Re-distribution, Markdown

ইনপুট: DataFrame, কলাম: open, high, low, close, volume (পুরনো -> নতুন, ডেইলি বা যেকোনো টাইমফ্রেম)
ব্যবহার:
    from wyckoff_scanner import analyze
    result = analyze(df)
    CLI:  python wyckoff_scanner.py data/*.csv        (শুধু যাচাইকৃত সংকেত)
          python wyckoff_scanner.py --all data/*.csv  (নজরে-রাখার তালিকাসহ)

দুই স্তর:
  SIGNAL = ফেজ + ইভেন্ট (Spring/Upthrust/SOS/SOW) + ক্যান্ডেল + ভলিউমের প্রমাণ + লিকুইডিটি + ঝুঁকি সীমা, সবগুলো একসঙ্গে মিলেছে।
  WATCH  = ফেজের কাঠামো আছে, কিন্তু উপরের কোনো শর্ত মেলেনি (কারণ why_not-এ লেখা)। এটা সংকেত নয়।

v1-এর ত্রুটি যা ঠিক করা হয়েছে:
  * Markup/Markdown ফেজ ব্রেকআউট/ব্রেকডাউন (SOS/SOW) ছাড়াই স্কোর ৬৫ পেয়ে "Entry" হয়ে যেত।
  * Re-accumulation/Re-distribution শুধু কাঠামো (আগের ট্রেন্ড + রেঞ্জ) দেখে লাগত, ভলিউম কোন দিকে সেটা দেখা হতো না।
  * ওপেন ফাঁকা (ট্রেড-না-হওয়া) দিন ও আটকে-থাকা কম-লেনদেনের শেয়ারে ভুল রেঞ্জ ধরা পড়ত; স্টপ ২০%+ দূরে থাকলেও সংকেত আসত।
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
    min_score: int = 60        # ফেজ চেনার ন্যূনতম স্কোর (এর নিচে ফেজই নেই)
    # ---- সংকেতের (SIGNAL) গেট ----
    min_ud: float = 1.0        # রেঞ্জে আপ-ডে ভলিউম ÷ ডাউন-ডে ভলিউম: বুলিশে ≥ এটি, বেয়ারিশে ≤ এর উল্টো
    min_value: float = 3e6     # ২০ দিনের গড় দৈনিক লেনদেন (টাকা), পেজের swing নিয়মের (SW.minValue) সমান
    max_zero_days: int = 4     # শেষ ৪০ দিনে ভলিউম-শূন্য দিন সর্বোচ্চ কয়টি (≈১০%)
    max_risk_pct: float = 8.0  # ক্লোজ থেকে স্টপ সর্বোচ্চ কত % দূরে (পেজের SW.maxRisk-এর সমান)
    close_pos: float = 0.5     # ব্রেকআউট/ব্রেকডাউন ক্যান্ডেলের ক্লোজ দিনের রেঞ্জের কোন অংশে (বুলিশে ওপরের অর্ধেক)


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


def _clean(df):
    """ট্রেড-না-হওয়া দিনে OPEN খালি থাকে: ওপেন = আগের ক্লোজ ধরা হয় (পেজের ingest-এর মতো), High/Low ওপেন-ক্লোজ ছুঁতে বাধ্য।"""
    df = df.reset_index(drop=True).copy()
    df["open"] = df["open"].fillna(df["close"].shift()).fillna(df["close"])
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"] = df[["low", "open", "close"]].min(axis=1)
    df["volume"] = df["volume"].fillna(0)
    return df


# ---------------- মূল বিশ্লেষণ ----------------
def analyze(df: pd.DataFrame, cfg: Config = Config()):
    need = cfg.range_len + cfg.recent + cfg.trend_len + 5
    if len(df) < max(need, 210):
        return {"phase": None, "reason": f"ডেটা কম (কমপক্ষে {max(need, 210)} বার দরকার)"}

    df = _clean(df)
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
    # আপ/ডাউন ভলিউম অনুপাত: আগের ক্লোজের সাপেক্ষে দাম বাড়লে আপ-ডে, কমলে ডাউন-ডে; অপরিবর্তিত দিন বাদ।
    # (v1-এ close>open ধরা হতো, তাতে দাম অপরিবর্তিত দিনও "ডাউন" গোনা হতো, অনুপাত নিচের দিকে ঝুঁকে যেত)
    pc = df.close.shift().loc[base.index]
    up_v = base.volume[base.close > pc].sum()
    dn_v = base.volume[base.close < pc].sum()
    ud = up_v / max(dn_v, 1e-9) if (up_v + dn_v) > 0 else float("nan")
    pos = (last.close - sup) / max(res - sup, 1e-9)             # রেঞ্জের ভেতরে অবস্থান (০-১)

    # ইভেন্ট (ফেজ সি ইত্যাদি)
    spring = bool(((recent.low < sup) & (recent.close > sup)).any()) and last.close > sup
    upthrust = bool(((recent.high > res) & (recent.close < res)).any()) and last.close < res
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

    # Markup/Markdown ইভেন্ট (SOS/SOW) ছাড়া হতেই পারে না। v1-এ ইভেন্ট ছাড়া ৬৫ স্কোরেই এরা "Entry" হয়ে যেত।
    if sos:
        S = {"Markup": S["Markup"]}
    elif sow:
        S = {"Markdown": S["Markdown"]}
    else:
        S.pop("Markup")
        S.pop("Markdown")

    phase, score = max(S.items(), key=lambda kv: kv[1])
    if score < cfg.min_score:
        return {"phase": None, "scores": S, "reason": "স্পষ্ট ওয়াইকফ ফেজ নেই"}

    # ---------------- দিক, ট্রিগার, লেভেল ----------------
    bias, trigger = "WATCH", ""
    if phase in ("Accumulation", "Re-accumulation"):
        bias = "BULLISH"
        if spring and (c["bull_engulf"] or c["hammer"]):
            trigger = "Spring/Liquidity Sweep + বুলিশ রিভার্সাল ক্যান্ডেল"
        elif spring:
            trigger = "Spring হয়েছে, বুলিশ ক্যান্ডেলের কনফার্মেশনের অপেক্ষা"
        else:
            trigger = "রেঞ্জ গঠন চলছে; Spring বা SOS-এর অপেক্ষা"
    elif phase in ("Distribution", "Re-distribution"):
        bias = "BEARISH"
        if upthrust and (c["bear_engulf"] or c["shooting_star"]):
            trigger = "Upthrust + বেয়ারিশ রিভার্সাল ক্যান্ডেল"
        elif upthrust:
            trigger = "Upthrust হয়েছে, বেয়ারিশ ক্যান্ডেলের কনফার্মেশনের অপেক্ষা"
        else:
            trigger = "রেঞ্জ গঠন চলছে; Upthrust বা SOW-এর অপেক্ষা"
    elif phase == "Markup":
        bias, trigger = "BULLISH", "রেঞ্জ ব্রেকআউট + ভলিউম স্পাইক (SOS)"
    elif phase == "Markdown":
        bias, trigger = "BEARISH", "সাপোর্ট ব্রেকডাউন + ভলিউম স্পাইক (SOW)"

    if bias == "BULLISH":
        stop = (min(recent.low.min(), sup) if phase != "Markup" else res) - 0.5 * atr
        target = res + height
        risk_pct = (last.close - stop) / last.close * 100
        rr = (target - last.close) / (last.close - stop) if last.close > stop else float("nan")
    else:
        stop = (max(recent.high.max(), res) if phase != "Markdown" else sup) + 0.5 * atr
        target = sup - height
        risk_pct = (stop - last.close) / last.close * 100
        rr = (last.close - target) / (stop - last.close) if stop > last.close else float("nan")

    # ---------------- সংকেত (SIGNAL) যাচাই: সব শর্ত একসঙ্গে ----------------
    bull = bias == "BULLISH"
    rng = last.high - last.low
    cpos = (last.close - last.low) / rng if rng > 0 else float("nan")   # ক্লোজ দিনের রেঞ্জের কোথায় (০ = সর্বনিম্ন)
    val20 = float((df.volume * df.close).tail(20).mean())
    zero_days = int((df.volume.tail(40) == 0).sum())
    if phase in ("Accumulation", "Re-accumulation"):
        event_ok = spring and (c["bull_engulf"] or c["hammer"])
        event_msg = "Spring + বুলিশ ক্যান্ডেল হয়নি"
    elif phase in ("Distribution", "Re-distribution"):
        event_ok = upthrust and (c["bear_engulf"] or c["shooting_star"])
        event_msg = "Upthrust + বেয়ারিশ ক্যান্ডেল হয়নি"
    elif phase == "Markup":
        event_ok = bool(last.close > last.open and cpos >= cfg.close_pos)
        event_msg = "ব্রেকআউট ক্যান্ডেল দুর্বল (বুলিশ নয় বা ক্লোজ দিনের নিচের অর্ধেকে)"
    else:
        event_ok = bool(last.close < last.open and cpos <= 1 - cfg.close_pos)
        event_msg = "ব্রেকডাউন ক্যান্ডেল দুর্বল (বেয়ারিশ নয় বা ক্লোজ দিনের ওপরের অর্ধেকে)"
    if ud != ud:
        ud_ok, ud_msg = False, "রেঞ্জে ভলিউমের দিক মাপা যায়নি"
    elif bull:
        ud_ok, ud_msg = ud >= cfg.min_ud, f"রেঞ্জে ক্রেতার ভলিউম কম (আপ/ডাউন {ud:.2f} < {cfg.min_ud})"
    else:
        ud_ok, ud_msg = ud <= 1 / cfg.min_ud, f"রেঞ্জে বিক্রেতার ভলিউম কম (আপ/ডাউন {ud:.2f} > {1 / cfg.min_ud:.2f})"
    liquid = bool(val20 >= cfg.min_value and zero_days <= cfg.max_zero_days and last.volume > 0)
    risk_ok = bool(risk_pct > 0 and risk_pct <= cfg.max_risk_pct)
    checks = [
        (event_ok, event_msg),
        (ud_ok, ud_msg),
        (liquid, "লেনদেন কম বা ঘন ঘন ট্রেড হয় না"),
        (risk_ok, f"স্টপ {risk_pct:.1f}% দূরে (সীমা {cfg.max_risk_pct:g}%)" if risk_pct > 0 else "স্টপ ক্লোজের ভুল পাশে"),
    ]
    why_not = [m for ok, m in checks if not ok]
    tier = "SIGNAL" if not why_not else "WATCH"

    return {
        "phase": phase, "score": score, "bias": bias, "tier": tier, "entry_signal": tier == "SIGNAL",
        "trigger": trigger, "why_not": "; ".join(why_not), "support": round(sup, 2), "resistance": round(res, 2),
        "stop_loss": round(stop, 2), "target": round(target, 2), "close": round(last.close, 2),
        "risk_pct": round(float(risk_pct), 1), "rr": None if rr != rr else round(float(rr), 2),
        "ud": None if ud != ud else round(float(ud), 2), "scores": S,
        "flags": {"spring": bool(spring), "upthrust": bool(upthrust), "SOS": bool(sos), "SOW": bool(sow),
                  "vol_contraction": bool(contraction), "liquid": liquid,
                  "pre_trend_pct": round(float(pre_ret) * 100, 1)},
    }


def scan(frames: dict, cfg: Config = Config(), only_signal: bool = True):
    """frames = {symbol: DataFrame}. only_signal=True হলে শুধু যাচাইকৃত সংকেত, নইলে নজরে-রাখার তালিকাসহ।"""
    rows = []
    for sym, df in frames.items():
        try:
            r = analyze(df, cfg)
        except Exception:  # খারাপ ডেটা এড়াতে
            continue
        if r.get("phase") and (r["tier"] == "SIGNAL" or not only_signal):
            rows.append({"symbol": sym, **{k: r[k] for k in
                         ("phase", "tier", "score", "bias", "trigger", "why_not", "close", "support",
                          "resistance", "stop_loss", "target", "risk_pct", "rr", "ud")}})
    out = pd.DataFrame(rows)
    if not len(out):
        return out
    return out.assign(_w=(out.tier != "SIGNAL")).sort_values(["_w", "score"], ascending=[True, False]).drop(columns="_w")


if __name__ == "__main__":
    import glob
    args = [a for a in sys.argv[1:] if a != "--all"]
    frames = {}
    for pattern in args:
        for f in glob.glob(pattern):
            d = pd.read_csv(f)
            d.columns = [x.lower() for x in d.columns]
            frames[f.split("/")[-1].rsplit(".", 1)[0]] = d
    res = scan(frames, only_signal="--all" not in sys.argv)
    print(res.to_string(index=False) if len(res) else "কোনো সংকেত নেই")
