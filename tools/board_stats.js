#!/usr/bin/env node
/* Board statistics probe.
 *
 * Runs the real game engine (engine.js — dictionary, solver, generator,
 * scoring) against the dictionary embedded in copia.html, so it always
 * measures the CURRENT scoring — edit engine.js, rerun this, compare.
 *
 * Per board: find-word count, bonus count, generator score, histogram of
 * word lengths, histogram of rarity term (1..10, clamped), stem-penalty
 * counts (pattern stems x0). Aggregates mean ± sd over N boards.
 *
 * Board names are fixed ("probe 1".."probe N") so different scoring variants
 * are compared on the same seeds.
 *
 * Usage: node tools/board_stats.js [--size 4] [--boards 20] [--verbose]
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { performance } = require('perf_hooks');
const { SCORING, GEN_ITERS, GEN_VERSION, createEngine } = require('../engine.js');

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf('--' + name);
  return i >= 0 ? +args[i + 1] : dflt;
};
const SIZE = opt('size', 4);
const N = opt('boards', 20);
const VERBOSE = args.includes('--verbose');

/* ---- dictionary comes from the artifact embedded in copia.html ---- */
const html = fs.readFileSync(path.join(__dirname, '..', 'copia.html'), 'utf8');
const dict = html.match(/<script id="dict-data" type="text\/plain">([\s\S]*?)<\/script>/)[1];
const { COMMON, RANK, stemMult, generateBoardSync } = createEngine(dict);
const FIND_N = COMMON.length;

/* ---- per-board stats (scoring functions/constants come from the engine) ---- */
function boardStats(found) {
  const words = found.common;
  const s = {
    words: words.size, bonus: found.bonus.size,
    byLen: {}, byRarity: {}, stemPattern: 0,
  };
  for (const w of words) {
    s.byLen[w.length] = (s.byLen[w.length] || 0) + 1;
    // rank decile within the find list: 1 = most common 10%, 10 = rarest 10%
    const rb = Math.min(10, Math.max(1, Math.ceil(10 * RANK.get(w) / FIND_N)));
    s.byRarity[rb] = (s.byRarity[rb] || 0) + 1;
    const m = stemMult(w, words);
    if (m === SCORING.STEM_PATTERN) s.stemPattern++;
  }
  return s;
}

/* ---- run ---- */
console.log(`copia board stats — ${SIZE}x${SIZE}, ${N} boards, GEN_VERSION ${GEN_VERSION}, GEN_ITERS ${GEN_ITERS[SIZE]}`);
const all = [];
const t0 = performance.now();
for (let i = 1; i <= N; i++) {
  const name = 'probe ' + i;
  const g = generateBoardSync(SIZE, name);
  const s = boardStats(g.best);
  s.score = g.bestScore;
  all.push(s);
  if (VERBOSE) console.log(`  ${name}: ${s.words} words, score ${s.score.toFixed(0)}, ` +
    `stem ${s.stemPattern}, board ${g.board.join('')}`);
}
console.log(`generated in ${((performance.now() - t0) / 1000).toFixed(1)}s\n`);

const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))); };
const fmt = xs => `${mean(xs).toFixed(1)} ± ${sd(xs).toFixed(1)}`;
const col = (get) => all.map(get);

console.log(`find words      ${fmt(col(s => s.words))}`);
console.log(`bonus words     ${fmt(col(s => s.bonus))}`);
console.log(`gen score       ${fmt(col(s => s.score))}`);
console.log(`stem pattern (x${SCORING.STEM_PATTERN})   ${fmt(col(s => s.stemPattern))}`);

console.log('\nlength histogram (mean words per board)');
const lens = [...new Set(all.flatMap(s => Object.keys(s.byLen)))].map(Number).sort((a, b) => a - b);
for (const L of lens)
  console.log(`  ${String(L).padStart(2)}  ${fmt(col(s => s.byLen[L] || 0))}`);

console.log('\nrank-decile histogram (find list decile -> mean words per board)');
for (let b = 1; b <= 10; b++) {
  const lo = Math.round((b - 1) * FIND_N / 10) + 1, hi = Math.round(b * FIND_N / 10);
  const rarLo = Math.log(lo) / Math.log(SCORING.RARITY_REF) * SCORING.RARITY_SCALE,
        rarHi = Math.log(hi) / Math.log(SCORING.RARITY_REF) * SCORING.RARITY_SCALE;
  console.log(`  d${String(b).padStart(2)} rank ${String(lo).padStart(5)}-${String(hi).padEnd(5)}` +
    ` rarity ${rarLo.toFixed(1)}-${rarHi.toFixed(1)}  ${fmt(col(s => s.byRarity[b] || 0))}`);
}
