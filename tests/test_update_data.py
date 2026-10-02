"""অফলাইন টেস্ট: নকল HTML দিয়ে পার্সার ও মার্জ যাচাই।  চালান: python tests/test_update_data.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
import update_data as U


def snapshot_html(n=60, ts='On  Sep 30, 2026 at 2:45 PM'):
    rows = ''.join(
        f'<tr><td>{i}</td><td>CO{i:03d}  </td><td>{10+i}.5</td><td>{11+i}</td><td>{9+i}</td><td>{10+i}.2</td>'
        f'<td>{10+i}</td><td>0.5</td><td>1,0{i}</td><td>1.2</td><td>{i*1000:,}</td></tr>' for i in range(1, n + 1))
    rows += '<tr><td>99</td><td>DEAD</td><td>0</td><td>0</td><td>0</td><td>0</td><td>27.4</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>'
    return (f'<html><body><h2>Latest Share Price by Last Trade Price {ts}</h2><table><tr><th>#</th><th>TRADING CODE</th>'
            f'<th>LTP*</th><th>HIGH</th><th>LOW</th><th>CLOSEP*</th><th>YCP*</th><th>CHANGE</th><th>TRADE</th>'
            f'<th>VALUE (mn)</th><th>VOLUME</th></tr>{rows}</table></body></html>')


def archive_html():
    return ('<table><tr><th>#</th><th>DATE</th><th>TRADING CODE</th><th>LTP*</th><th>HIGH</th><th>LOW</th><th>OPENP*</th>'
            '<th>CLOSEP*</th><th>YCP*</th><th>TRADE</th><th>VALUE (mn)</th><th>VOLUME</th></tr>'
            '<tr><td>1</td><td>2026-09-29</td><td>CO001</td><td>11</td><td>12</td><td>10</td><td>10.5</td><td>11</td>'
            '<td>10.4</td><td>5</td><td>1</td><td>5,000</td></tr></table>')


tmp = tempfile.mkdtemp()
U.DATA_DIR = tmp
U.CSV_PATH = os.path.join(tmp, 'prices.csv')
U.META_PATH = os.path.join(tmp, 'meta.json')

# 1) পার্সার
rows, text = U.extract(snapshot_html())
assert len(rows) == 61, len(rows)
ts = U.snapshot_time(text)
assert ts and ts.hour == 14 and ts.minute == 45 and ts.day == 30, ts
recs = [r for r in (U.to_record(d, '2026-09-30') for d in rows) if r]
assert len(recs) == 60, len(recs)  # DEAD (দাম ০) বাদ
assert recs[0]['VOLUME'] == '1000' and recs[0]['CLOSEP'] == '11.2' and recs[0]['OPENP'] == '', recs[0]


class A:
    force = False; cutoff = '14:30'; keep = 3; bootstrap = False; days = 400; codes = ''; sleep = 0


# 2) দৈনিক রান
U.http_get = lambda url, **k: snapshot_html() if 'latest_share' in url else archive_html()
assert U.run_daily(A) == 0
d = U.load_csv()
assert len(d) == 60

# 3) আর্কাইভের আসল OPENP স্ন্যাপশট মুছছে না
arch = U.fetch_archive('x', 'CO001', '2026-01-01', '2026-09-30')
assert arch[0]['OPENP'] == '10.5' and arch[0]['DATE'] == '2026-09-29'
d = U.load_csv()
U.merge(d, arch)
U.merge(d, [U.to_record(rows[0], '2026-09-29')])
assert d[('2026-09-29', 'CO001')]['OPENP'] == '10.5'

# 4) বাজার চলাকালীন আংশিক ডেটা বাদ
n = U.datetime.now(U.DHAKA)
U.http_get = lambda url, **k: snapshot_html(ts=f'On  {n:%b} {n.day}, {n.year} at 11:00 AM')
before = os.path.getmtime(U.CSV_PATH)
assert U.run_daily(A) == 0 and os.path.getmtime(U.CSV_PATH) == before

# 5) পুরনো দিন ছাঁটাই
d = U.load_csv()
for day in ('2026-09-20', '2026-09-21', '2026-09-22', '2026-09-23'):
    U.merge(d, [dict(r, DATE=day) for r in recs])
U.save(d, 3, 'x')
assert len({k[0] for k in U.load_csv()}) == 3

# 6) পেজ বদলে গেলে (খালি টেবিল) ব্যর্থ হয়, ভুল ডেটা লেখে না
U.http_get = lambda url, **k: '<html>404</html>'
try:
    U.fetch_snapshot(); raise SystemExit('ব্যর্থ হওয়ার কথা ছিল')
except RuntimeError:
    pass
print('সব টেস্ট পাস')
