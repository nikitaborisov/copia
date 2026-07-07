#!/usr/bin/env node
/* Board statistics probe.
 *
 * Extracts the game engine straight out of copia.html (dictionary, solver,
 * generator, scoring) so it always measures the CURRENT scoring — edit the
 * scoring in copia.html, rerun this, compare.
 *
 * Per board: find-word count, bonus count, generator score, histogram of
 * word lengths, histogram of rarity term (1..10, clamped), stem-penalty
 * counts (1/8 direct, 1/4 variation). Aggregates mean ± sd over N boards.
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

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf('--' + name);
  return i >= 0 ? +args[i + 1] : dflt;
};
const SIZE = opt('size', 4);
const N = opt('boards', 20);
const VERBOSE = args.includes('--verbose');

/* ---- load engine from copia.html ---- */
const html = fs.readFileSync(path.join(__dirname, '..', 'copia.html'), 'utf8');
const dict = html.match(/<script id="dict-data" type="text\/plain">([\s\S]*?)<\/script>/)[1];
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
let code = scripts[scripts.length - 1][1];
code = code.slice(0, code.indexOf('/* ================= game state & UI'));

global.document = { getElementById: id => (id === 'dict-data' ? { textContent: dict } : undefined) };
const engine = new Function(code + `
  return {COMMON, BONUS, RANK, STEM_BASES, GEN_ITERS, GEN_VERSION,
          hashStr, mulberry32, normalizeName, randLetter,
          neighborsTable, solve, seedBoard, scoreOf};`)();
const { RANK, STEM_BASES, GEN_ITERS, GEN_VERSION,
        hashStr, mulberry32, normalizeName, randLetter,
        neighborsTable, solve, seedBoard, scoreOf } = engine;

/* ---- synchronous generation (same algorithm as generateBoard) ---- */
function genSync(n, name) {
  const rng = mulberry32(hashStr(n + 'x' + n + ':' + normalizeName(name)));
  const nbr = neighborsTable(n);
  let board = seedBoard(n, rng);
  let best = solve(board, nbr);
  let bestScore = scoreOf(best);
  for (let i = 0; i < GEN_ITERS[n]; i++) {
    const trial = board.slice();
    if (rng() < 0.7) trial[rng() * trial.length | 0] = randLetter(rng);
    else {
      const a = rng() * trial.length | 0, b = rng() * trial.length | 0;
      [trial[a], trial[b]] = [trial[b], trial[a]];
    }
    const res = solve(trial, nbr), sc = scoreOf(res);
    if (sc >= bestScore) { board = trial; best = res; bestScore = sc; }
  }
  return { board, best, bestScore };
}

/* ---- per-board stats ---- */
const rarity = w => Math.log(RANK.get(w)) / Math.log(10000) * 10;
function stemMult(w, present) {
  let m = 1;
  const bases = STEM_BASES.get(w);
  if (bases) for (const [b, mm] of bases) if (mm < m && present.has(b)) m = mm;
  return m;
}
function boardStats(found) {
  const words = found.common;
  const s = {
    words: words.size, bonus: found.bonus.size,
    byLen: {}, byRarity: {}, stemEighth: 0, stemQuarter: 0,
  };
  for (const w of words) {
    s.byLen[w.length] = (s.byLen[w.length] || 0) + 1;
    const rb = Math.min(10, Math.max(1, Math.ceil(rarity(w))));
    s.byRarity[rb] = (s.byRarity[rb] || 0) + 1;
    const m = stemMult(w, words);
    if (m === 0.125) s.stemEighth++;
    else if (m === 0.25) s.stemQuarter++;
  }
  return s;
}

/* ---- run ---- */
console.log(`copia board stats — ${SIZE}x${SIZE}, ${N} boards, GEN_VERSION ${GEN_VERSION}, GEN_ITERS ${GEN_ITERS[SIZE]}`);
const all = [];
const t0 = performance.now();
for (let i = 1; i <= N; i++) {
  const name = 'probe ' + i;
  const g = genSync(SIZE, name);
  const s = boardStats(g.best);
  s.score = g.bestScore;
  all.push(s);
  if (VERBOSE) console.log(`  ${name}: ${s.words} words, score ${s.score.toFixed(0)}, ` +
    `stem ${s.stemEighth}+${s.stemQuarter}, board ${g.board.join('')}`);
}
console.log(`generated in ${((performance.now() - t0) / 1000).toFixed(1)}s\n`);

const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))); };
const fmt = xs => `${mean(xs).toFixed(1)} ± ${sd(xs).toFixed(1)}`;
const col = (get) => all.map(get);

console.log(`find words      ${fmt(col(s => s.words))}`);
console.log(`bonus words     ${fmt(col(s => s.bonus))}`);
console.log(`gen score       ${fmt(col(s => s.score))}`);
console.log(`stem 1/8        ${fmt(col(s => s.stemEighth))}`);
console.log(`stem 1/4        ${fmt(col(s => s.stemQuarter))}`);
console.log(`stem any        ${fmt(col(s => s.stemEighth + s.stemQuarter))}`);

console.log('\nlength histogram (mean words per board)');
const lens = [...new Set(all.flatMap(s => Object.keys(s.byLen)))].map(Number).sort((a, b) => a - b);
for (const L of lens)
  console.log(`  ${String(L).padStart(2)}  ${fmt(col(s => s.byLen[L] || 0))}`);

console.log('\nrarity histogram (rarity term bucket -> mean words per board)');
for (let b = 1; b <= 10; b++)
  console.log(`  ${b <= 1 ? '<=1' : ' ' + (b === 10 ? '>9' : '=' + b)}  ${fmt(col(s => s.byRarity[b] || 0))}`);
