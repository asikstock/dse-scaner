"""docs/index.html-এর JS wyckoffAnalyze() আর রুটের Python analyze() একই ফল দেয় কি না মেলায়।
ডেটার প্রতিটি কোডের ৪টি করে শেষ-বার (শেষ দিন, -37, -113, -251) নিয়ে ফেজ, স্কোর, স্তর (SIGNAL/WATCH), কারণ-বার্তা, ভলিউম অনুপাত, ঝুঁকি ও লেভেল তুলনা করে।
চালান:  python3 tools/wyckoff_backtest/check_js_parity.py
"""
import json, os, subprocess, sys, tempfile
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from wyckoff_scanner import analyze  # noqa: E402

d = pd.read_csv(os.path.join(ROOT, "docs/data/prices.csv"))
d.columns = [x.lower() for x in d.columns]
d = d.rename(columns={"trading code": "sym", "openp": "open", "closep": "close"}).sort_values(["sym", "date"])
# পেজের ingest()-এর মতো: ট্রেড-না-হওয়া দিনে OPENP খালি থাকে, তখন ওপেন = আগের ক্লোজ (YCP), না থাকলে ক্লোজ
d["open"] = d["open"].fillna(d["ycp"]).fillna(d["close"])
d["high"] = d[["high", "open", "close"]].max(axis=1)
d["low"] = d[["low", "open", "close"]].min(axis=1)
frames = {s: g[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True) for s, g in d.groupby("sym")}

samples = [(s, len(g) - 1 - back) for s, g in frames.items() for back in (0, 37, 113, 251) if len(g) - back >= 215]
js = r"""
const fs=require('fs');const html=fs.readFileSync(process.argv[2],'utf8');
const a=html.indexOf('/*WYCKOFF_START*/'),b=html.indexOf('/*WYCKOFF_END*/');
eval(html.slice(a,b)+';globalThis.wyckoffAnalyze=wyckoffAnalyze;');
const F=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));const out=[];
for(const [sym,end] of F.samples){const bars=F.frames[sym].slice(0,end+1);out.push(wyckoffAnalyze(bars));}
fs.writeFileSync(process.argv[4],JSON.stringify(out));
"""
need = {s: [{"d": r.date, "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": r.volume} for r in frames[s].itertuples()] for s in {x for x, _ in samples}}
tmp = tempfile.mkdtemp()
open(f"{tmp}/p.js", "w").write(js)
json.dump({"samples": samples, "frames": need}, open(f"{tmp}/in.json", "w"))
r = subprocess.run(["node", f"{tmp}/p.js", os.path.join(ROOT, "docs/index.html"), f"{tmp}/in.json", f"{tmp}/out.json"], capture_output=True, text=True)
if r.returncode:
    sys.exit("node ব্যর্থ: " + r.stderr[-400:])
J = json.load(open(f"{tmp}/out.json"))

# pandas rolling().mean() ও সরাসরি গড়ে ১e-14 পর্যন্ত তফাত হয়। দাম একই জায়গায় আটকে থাকা (ফ্লোর প্রাইস) কোডে
# close == SMA50 হলে "close < SMA50" শর্ত দুই দিকে ভিন্ন আসে; তাতে ঠিক ১৫ পয়েন্টের (একটি শর্তের) অমিল হয়, ফেজ একই থাকে।
close = lambda a, b, tol: (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= tol)
bad, edge = 0, 0
for (s, end), j in zip(samples, J):
    p = analyze(frames[s].iloc[:end + 1])
    if p.get("phase") != j.get("phase"):
        # ফ্লোট-এজে ১৫ পয়েন্টের তফাত ফেজের সীমা (৬০) পেরিয়ে একদিকে "ফেজ নেই" করে দিতে পারে
        sc = [x for x in (p.get("score"), j.get("score")) if x is not None]
        if (p.get("phase") is None or j.get("phase") is None) and len(sc) == 1 and sc[0] == 60:
            edge += 1
            continue
        ok = False
    elif not p.get("phase"):
        ok = True
    else:
        ok = (p["score"] == j["score"] and p["tier"] == j["tier"] and p["bias"] == j["bias"]
              and p["why_not"] == j["whyNot"]
              and close(p["ud"], j["ud"], 0.011) and close(p["rr"], j["rr"], 0.011) and abs(p["risk_pct"] - j["riskPct"]) <= 0.11
              and all(abs(p[k] - j[m]) < 0.011 for k, m in (("support", "support"), ("resistance", "resistance"),
                      ("stop_loss", "stop"), ("target", "target"), ("close", "close"))))
        if not ok and abs(p["score"] - j["score"]) == 15 and p["phase"] == j["phase"]:
            edge += 1
            continue
    if not ok:
        bad += 1
        if bad <= 5:
            print("MISMATCH", s, end, p.get("phase"), p.get("score"), p.get("tier"), "| js:", j.get("phase"), j.get("score"), j.get("tier"))
phases = {}
for j in J:
    phases[j.get("phase")] = phases.get(j.get("phase"), 0) + 1
print(f"{len(samples)} নমুনা, আসল অমিল {bad}, ফ্লোট-এজ (±১৫ স্কোর, ফেজ একই) {edge}; JS ফেজ বণ্টন: {phases}")
sys.exit(1 if bad or edge > 0.01 * len(samples) else 0)
