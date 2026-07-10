/* Copia game engine — dictionary parsing, trie solver, scoring, and the
 * deterministic board generator.
 *
 * This file is shared verbatim by two consumers:
 *   - copia.html loads it with <script src="engine.js"> (browser global
 *     `CopiaEngine`)
 *   - tools/board_stats.js require()s it as a Node module
 * so the game and the stats tool can never drift apart.
 *
 * The dictionary-dependent part is built by createEngine(dictText), where
 * dictText is the dictionary artifact produced by build/build_dict.py. The
 * page reads it from its embedded <script id="dict-data"> block; Node tools
 * extract that same block from copia.html.
 */
(function(global){
'use strict';

/* ================= scoring configuration =================
   ALL scoring knobs live here — the dict parser, generator, UI display, and
   tools/board_stats.js read this object; change values here and nowhere else.
   Any change alters board generation -> bump GEN_VERSION in the same commit.
   Formula per word (see wordScore/stemMult below):
     ((len-3)^LENGTH_EXP + log(rank)/log(RARITY_REF)*RARITY_SCALE) * stem */
const SCORING = {
  LENGTH_EXP: 1.5,       // length term = (len-3)^LENGTH_EXP
  RARITY_SCALE: 20,      // rarity term = log(rank)/log(RARITY_REF)*RARITY_SCALE
  RARITY_REF: 10000,
  STEM_PATTERN: 0,       // simple suffix pattern (s/ed/d/ing); only when base on board
};

/* Deterministic generation: the board name seeds a PRNG and the hill climb
   runs a FIXED number of iterations, so "4x4 curious elephant" is the same
   board on every device — but only within one GEN_VERSION.

   >>> BUMP GEN_VERSION whenever ANYTHING affecting board generation changes: <<<
   the embedded dictionary, the rank split, scoring (SCORING, wordScore,
   stemMult, scoreOf, STEM_BASES), GEN_ITERS, seedBoard, hashStr/mulberry32,
   or the mutation logic in startClimb. Saved games record the version they
   were played on; saves from other versions are shown greyed out and are not
   restored. */
const GEN_VERSION = 8;
const GEN_ITERS = {3:5200, 4:3600, 5:1500};

/* ================= seeded RNG ================= */
function hashStr(s){
  let h=2166136261>>>0;
  for(let i=0;i<s.length;i++){ h^=s.charCodeAt(i); h=Math.imul(h,16777619); }
  return h>>>0;
}
function mulberry32(a){
  return function(){
    a|=0; a=a+0x6D2B79F5|0;
    let t=Math.imul(a^a>>>15,1|a);
    t=t+Math.imul(t^t>>>7,61|t)^t;
    return ((t^t>>>14)>>>0)/4294967296;
  };
}

/* ================= board names ================= */
const NAME_ADJ=['amber','ancient','arctic','autumn','azure','bashful','blazing','bold','brave','breezy','bright','bronze','bubbly','calm','candid','cheerful','chilly','clever','coastal','copper','coral','cosmic','cozy','crafty','crimson','crystal','curious','dapper','daring','dizzy','dusky','dusty','eager','earnest','ebony','electric','elegant','emerald','fabled','faithful','fancy','feral','fierce','fiery','floral','fluffy','foggy','forest','frosty','gallant','gentle','giddy','gilded','gleeful','glowing','golden','graceful','grand','groovy','gusty','happy','hardy','hasty','hidden','hollow','honest','humble','indigo','iron','ivory','jade','jaunty','jolly','jovial','keen','kind','lanky','limber','lively','loud','lucky','lunar','marble','maroon','meadow','mellow','merry','midnight','mighty','misty','mossy','murky','mystic','nimble','noble','ochre','olive','onyx','opal','pearl','peppy','perky','plucky','plum','polite','prairie','prickly','primal','proud','pumpkin','quaint','quick','quiet','quirky','regal','river','roaming','robust','rogue','rosy','rowdy','ruby','rugged','rustic','rusty','sable','saffron','sandy','sapphire','sassy','savvy','scarlet','scrappy','shadow','sharp','shiny','silent','silly','silver','sincere','slate','sleek','sleepy','smoky','snappy','snowy','solar','spiced','spirited','spotted','spry','stately','steely','stormy','striped','sturdy','summer','sunny','swift','teal','tidal','tidy','timber','tiny','topaz','tranquil','tundra','twilight','umber','valiant','vast','velvet','verdant','vintage','vivid','wandering','wild','wintry','witty','zesty','zippy'];
const NAME_NOUN=['albatross','anteater','antelope','armadillo','axolotl','baboon','badger','barracuda','bear','beaver','beetle','bison','bittern','bobcat','bullfrog','buzzard','caiman','camel','capybara','caracal','cardinal','caribou','cassowary','catfish','chameleon','cheetah','chickadee','chinchilla','chipmunk','cicada','civet','cockatoo','condor','cormorant','cougar','coyote','crane','cricket','crow','cuckoo','curlew','dingo','dolphin','donkey','dormouse','dragon','dugong','eagle','egret','eland','elephant','ermine','falcon','ferret','finch','fox','gannet','gazelle','gecko','gerbil','gibbon','giraffe','goose','gopher','grackle','grouse','hamster','hare','harrier','hawk','hedgehog','heron','herring','hippo','hoopoe','hornet','hummingbird','hyena','ibex','ibis','iguana','impala','jackal','jackdaw','jackrabbit','jaguar','jay','kestrel','kingfisher','kite','kiwi','koala','lark','lemur','leopard','lion','llama','lobster','loon','lynx','macaque','macaw','mackerel','magpie','mallard','manatee','mandrill','mantis','marlin','marmot','marten','mastiff','mayfly','meerkat','minnow','mockingbird','mongoose','moose','moth','muskrat','narwhal','newt','nightingale','nuthatch','ocelot','octopus','opossum','orca','oriole','oryx','osprey','ostrich','otter','owl','oyster','panda','pangolin','panther','parrot','partridge','peacock','pelican','penguin','petrel','pheasant','pigeon','pika','pike','piranha','platypus','plover','polecat','porcupine','porpoise','puffin','python','quail','quetzal','quokka','rabbit','raccoon','raven','redstart','reindeer','rhino','roadrunner','robin','rooster','sailfish','salmon','sandpiper','seahorse','seal','serval','shrike','skink','skunk','sloth','snail','snipe','sparrow','squid','squirrel','starling','stingray','stoat','stork','sturgeon','swallow','swan','tamarin','tanager','tapir','tarpon','tern','terrapin','thrush','tiger','tortoise','toucan','trout','tuna','turtle','urchin','viper','vole','vulture','wallaby','wapiti','warbler','walrus','waxwing','weasel','whale','whippet','wolf','wolverine','wombat','woodcock','woodpecker','wren','yak','zebra'];
const randomName = ()=>{
  const a1=NAME_ADJ[Math.random()*NAME_ADJ.length|0];
  let a2=a1;
  while(a2===a1) a2=NAME_ADJ[Math.random()*NAME_ADJ.length|0];
  return a1+' '+a2+' '+NAME_NOUN[Math.random()*NAME_NOUN.length|0];
};
const normalizeName = s=>String(s).trim().toLowerCase().replace(/[-_]+/g,' ').replace(/\s+/g,' ');

/* ================= grid geometry ================= */
function neighborsTable(n){
  const tbl = [];
  for(let i=0;i<n*n;i++){
    const r=i/n|0, c=i%n, arr=[];
    for(let dr=-1;dr<=1;dr++)for(let dc=-1;dc<=1;dc++){
      if(!dr&&!dc)continue;
      const rr=r+dr, cc=c+dc;
      if(rr>=0&&rr<n&&cc>=0&&cc<n) arr.push(rr*n+cc);
    }
    tbl.push(arr);
  }
  return tbl;
}
// ALL self-avoiding placements of `word` on `board`, up to `cap` (default 64),
// in deterministic DFS order. Used by the hint optimizer; not by generation.
function findAllPaths(board, nbr, word, cap){
  cap = cap || 64;
  const out = [];
  const used = new Uint8Array(board.length);
  const path = [];
  function dfs(i,k){
    if(out.length>=cap) return;
    if(board[i]!==word[k]) return;
    used[i]=1; path.push(i);
    if(k===word.length-1) out.push(path.slice());
    else for(const j of nbr[i]) if(!used[j]) dfs(j,k+1);
    used[i]=0; path.pop();
  }
  for(let i=0;i<board.length;i++) dfs(i,0);
  return out;
}
// find one path spelling `word` on `board`, or null
function findPath(board, nbr, word){
  const used = new Uint8Array(board.length);
  let result = null;
  function dfs(i,k,path){
    if(result) return;
    if(board[i]!==word[k]) return;
    used[i]=1; path.push(i);
    if(k===word.length-1){ result = path.slice(); }
    else for(const j of nbr[i]) if(!used[j]) dfs(j,k+1,path);
    used[i]=0; path.pop();
  }
  for(let i=0;i<board.length && !result;i++) dfs(i,0,[]);
  return result;
}

/* ================= dictionary-dependent engine ================= */
function createEngine(dictText){

  /* ---- dictionary ----
     The artifact is generated by build/build_dict.py — versioned
     (dict/copia-dict.v<N>.txt) and checked into the repo, NOT built at deploy
     time. Header "copia-dict v<N>", then "#find" and "#bonus" sections in
     descending-frequency order.      Lines: "word" or "word:base1,base2" where the bases are simple suffix-
     pattern stems (s/ed/d/ing) from the find list; score x0 when base on board.
     RANK = 1-based global frequency rank across both sections.
     Changing the dictionary means a new DICT_VERSION artifact AND a
     GEN_VERSION bump above. See build/README.md. */
  const lines = String(dictText).trim().split('\n');
  const header = lines[0].match(/^copia-dict v(\d+)$/);
  if(!header) throw new Error('bad dictionary header');
  const DICT_VERSION = +header[1];
  const COMMON=[], BONUS=[], RANK=new Map(), STEM_BASES=new Map();
  {
    let section=null, rank=0;
    for(let i=1;i<lines.length;i++){
      const line=lines[i];
      if(line==='#find'){ section=COMMON; continue; }
      if(line==='#bonus'){ section=BONUS; continue; }
      const ci=line.indexOf(':');
      const w = ci<0 ? line : line.slice(0,ci);
      RANK.set(w, ++rank);
      section.push(w);
      if(ci>=0) STEM_BASES.set(w,
        line.slice(ci+1).split(',').map(b=>[b, SCORING.STEM_PATTERN]).sort((a,c)=>a[0].localeCompare(c[0])));
    }
  }

  /* Effective rank for the rarity term: a stemmed word inherits the best
     (most common, lowest) rank in its stem family, transitively
     (carriers -> carrier -> carry), so inflections never score as rarer than
     the word they derive from. */
  const EFF_RANK = new Map();
  function computeEffRank(w, seen){
    if(EFF_RANK.has(w)) return EFF_RANK.get(w);
    let r = RANK.get(w);
    const bases = STEM_BASES.get(w);
    if(bases){
      seen = seen || new Set([w]);
      for(const [b] of bases){
        if(seen.has(b) || !RANK.has(b)) continue;
        seen.add(b);
        r = Math.min(r, computeEffRank(b, seen));
      }
    }
    EFF_RANK.set(w, r);
    return r;
  }
  for(const w of RANK.keys()) computeEffRank(w);

  /* ---- trie: children in Map, flag 1 = common word end, 2 = bonus ---- */
  const TRIE = (()=>{
    const root = {c:new Map(), f:0};
    const add = (w,f)=>{
      let n = root;
      for(const ch of w){
        let nx = n.c.get(ch);
        if(!nx){ nx = {c:new Map(), f:0}; n.c.set(ch,nx); }
        n = nx;
      }
      n.f |= f;
    };
    for(const w of COMMON) add(w,1);
    for(const w of BONUS) add(w,2);
    return root;
  })();

  /* ---- letter pool weighted by frequency in the find list ---- */
  const LETTER_POOL = (()=>{
    const freq = {};
    for(const w of COMMON) for(const ch of w) freq[ch]=(freq[ch]||0)+1;
    const pool = [];
    for(const [ch,n] of Object.entries(freq)){
      const k = Math.max(1, Math.round(100*n/COMMON.length));
      for(let i=0;i<k;i++) pool.push(ch);
    }
    return pool;
  })();
  const randLetter = rng=>LETTER_POOL[rng()*LETTER_POOL.length|0];

  /* ---- scoring ----
     Stem-aware: a word scores x0 only when a simple suffix-pattern base of it
     is itself on the same board's "words to find" list; otherwise full weight.
     STEM_BASES comes from the dictionary artifact (pattern stems at build
     time). These three functions are the single implementation of scoring,
     used by generation, the UI, and tools. */
  function lengthScore(w){
    return Math.round(Math.pow(w.length-3, SCORING.LENGTH_EXP));
  }
  function rarityScore(w){
    return Math.round(Math.log(EFF_RANK.get(w))/Math.log(SCORING.RARITY_REF)*SCORING.RARITY_SCALE);
  }
  // both parts rounded to the nearest integer, so all word scores are integers
  function wordScore(w){
    return lengthScore(w) + rarityScore(w);
  }
  function stemMult(w, present){
    let m=1;
    const bases=STEM_BASES.get(w);
    if(bases) for(const [b,mm] of bases){ if(mm<m && present.has(b)) m=mm; }
    return m;
  }
  function scoreOf(found){
    let s=0;
    for(const w of found.common) s += wordScore(w)*stemMult(w, found.common);
    return s;
  }
  /* Words whose score is fully zeroed on this board (a stem base is present
     and the stem multiplier is 0). The UI drops these from the find/bonus
     lists entirely and shows a "stem extension" hint instead. Automatically
     empty if SCORING makes stem multipliers nonzero. Does not affect
     scoreOf/generation (these words already contribute 0). */
  function stemExtensions(found){
    const out = new Set();
    for(const w of found.common) if(stemMult(w, found.common)===0) out.add(w);
    for(const w of found.bonus)  if(stemMult(w, found.common)===0) out.add(w);
    return out;
  }

  /* ---- solver: all findable words, as {common:Set, bonus:Set} ---- */
  function solve(board, nbr){
    const found = {common:new Set(), bonus:new Set()};
    const N = board.length;
    const used = new Uint8Array(N);
    const path = [];
    function dfs(i, node){
      const nx = node.c.get(board[i]);
      if(!nx) return;
      used[i]=1; path.push(board[i]);
      if(path.length>=4 && nx.f){
        const w = path.join('');
        if(nx.f&1) found.common.add(w); else found.bonus.add(w);
      }
      for(const j of nbr[i]) if(!used[j]) dfs(j,nx);
      used[i]=0; path.pop();
    }
    for(let i=0;i<N;i++) dfs(i,TRIE);
    return found;
  }

  /* ---- board generator (hill climbing) ---- */
  function seedBoard(n, rng){
    const board = Array.from({length:n*n}, ()=>randLetter(rng));
    // lay a long common word along a random self-avoiding path
    const maxLen = Math.min(12, n*n);
    const cands = COMMON.filter(w=>w.length>=Math.min(8,maxLen-1) && w.length<=maxLen);
    if(cands.length){
      const w = cands[rng()*cands.length|0];
      const nbr = neighborsTable(n);
      const used = new Uint8Array(n*n);
      const path = [];
      function walk(i,k){
        used[i]=1; path.push(i);
        if(k===w.length-1) return true;
        const opts = nbr[i].filter(j=>!used[j]);
        for(let t=opts.length-1;t>0;t--){const s=rng()*(t+1)|0;[opts[t],opts[s]]=[opts[s],opts[t]];}
        for(const j of opts) if(walk(j,k+1)) return true;
        used[i]=0; path.pop(); return false;
      }
      if(walk(rng()*n*n|0, 0)) path.forEach((i,k)=>board[i]=w[k]);
    }
    return board;
  }

  /* One climb state per named board; step() runs a single
     mutate-solve-compare iteration. Both generateBoardSync (Node tools) and
     generateBoard (chunked, browser) drive this same loop, so the two paths
     cannot diverge. */
  function startClimb(n, name){
    const rng = mulberry32(hashStr(n+'x'+n+':'+normalizeName(name)));
    const nbr = neighborsTable(n);
    const g = {nbr, total:GEN_ITERS[n], iter:0};
    g.board = seedBoard(n, rng);
    g.best = solve(g.board, nbr);
    g.bestScore = scoreOf(g.best);
    g.step = ()=>{
      g.iter++;
      const trial = g.board.slice();
      if(rng()<0.7){
        trial[rng()*trial.length|0] = randLetter(rng);
      }else{
        const a=rng()*trial.length|0, b=rng()*trial.length|0;
        [trial[a],trial[b]]=[trial[b],trial[a]];
      }
      const res = solve(trial,nbr);
      const sc = scoreOf(res);
      if(sc>=g.bestScore){
        g.board=trial; g.best=res; g.bestScore=sc;
      }
    };
    return g;
  }
  // blocking; returns {board, best, bestScore, nbr}
  function generateBoardSync(n, name){
    const g = startClimb(n, name);
    while(g.iter<g.total) g.step();
    return g;
  }
  // cooperative: ~40ms chunks between progress callbacks, keeps the UI alive
  function generateBoard(n, name, onProgress, onDone){
    const g = startClimb(n, name);
    function chunk(){
      const stop = performance.now()+40;
      while(g.iter<g.total && performance.now()<stop) g.step();
      onProgress(g.best.common.size, g.bestScore, g.iter, g.total);
      if(g.iter<g.total) setTimeout(chunk,0);
      else onDone(g.board, g.best, g.nbr);
    }
    chunk();
  }

  return {
    DICT_VERSION, COMMON, BONUS, RANK, EFF_RANK, STEM_BASES,
    wordScore, lengthScore, rarityScore, stemMult, scoreOf, stemExtensions,
    solve, seedBoard, randLetter,
    generateBoard, generateBoardSync,
  };
}

/* ================= exports ================= */
const api = {SCORING, GEN_VERSION, GEN_ITERS,
             hashStr, mulberry32, normalizeName, randomName,
             neighborsTable, findPath, findAllPaths, createEngine};
if(typeof module!=='undefined' && module.exports) module.exports = api;
else global.CopiaEngine = api;
})(globalThis);
