// Headless runner for the scanner's own JS (docs/index.html, from /*CORE_START*/ to the 'let SECTORS' line).
// Usage: node harness.js <repoDocsDir> <outJson> [variantsJson]
const fs = require('fs'), vm = require('vm'), path = require('path');
const docs = process.argv[2], outFile = process.argv[3];
const lines = fs.readFileSync(path.join(docs, 'index.html'), 'utf8').split('\n');
// CORE + add-ons + constants: from /*CORE_START*/ up to the 'let SECTORS' line (before DOM-heavy code)
const a = lines.findIndex(l => l.includes('/*CORE_START*/'));
const b = lines.findIndex(l => l.startsWith('let SECTORS='));
if (a < 0 || b < 0) throw new Error('markers not found in index.html');
const code = lines.slice(a, b + 1).join('\n');

const gateState = {};            // overrides for checkboxes read by gateOn()
const fakeEl = id => (id in gateState ? { checked: !!gateState[id] } : null);
const ctx = vm.createContext({
  console, Math, Date, Map, Set, Object, Array, JSON, parseFloat, isNaN, String, Number,
  document: { getElementById: fakeEl, querySelector: () => null, querySelectorAll: () => [], addEventListener() {} },
  window: {}, setTimeout, location: { protocol: 'file:' },
});
ctx.__gate = gateState;
vm.runInContext(code, ctx, { filename: 'core.js' });

const read = f => fs.readFileSync(path.join(docs, 'data', f), 'utf8');
vm.runInContext(`
  MAP = {};
  ingest(MAP, ${JSON.stringify(read('prices.csv'))}, 'prices.csv');
  DB = finalize(MAP);
  INDEX = null;
  loadIndex(${JSON.stringify(read('dsex.csv'))}, true);
  loadIndex(${JSON.stringify(read('index.csv'))}, true);
`, ctx);

const variants = process.argv[4] ? JSON.parse(fs.readFileSync(process.argv[4], 'utf8')) : [{ name: 'default', gates: {}, hold: 10 }];
const results = [];
for (const v of variants) {
  for (const k of Object.keys(gateState)) delete gateState[k];
  Object.assign(gateState, v.gates || {});
  const hold = v.hold || 10, cost = v.cost == null ? 0.5 : v.cost;
  const res = vm.runInContext(`
    (function(hold, cost, minPrice, minVol){
      const out = { trades: [], random: [], syms: 0 };
      for (const sym in DB) {
        const b = DB[sym]; if (b.length < 35) continue;
        if (/MF$|^1STMF|^2NDMF|^3RDMF|GROWTHFUND|INCOMEFUND|MUTUALFUND|BONDFUND|BOND$/.test(sym.toUpperCase())) continue;
        const I = compute(b);
        const bR = backtest(b, I, hold, 2);
        out.syms++;
        for (const t of bR.trades) out.trades.push({ sym, d: t.d, ret: t.ret - cost, score: t.score });
        for (let k = 0; k < bR.randomReturns.length; k++) out.random.push({ d: bR.randomDates[k], ret: bR.randomReturns[k] - cost });
      }
      return JSON.stringify(out);
    })(${hold}, ${cost})
  `, ctx);
  results.push({ name: v.name, hold, cost, ...JSON.parse(res) });
  process.stderr.write(`done ${v.name}\n`);
}
fs.writeFileSync(outFile, JSON.stringify(results));
