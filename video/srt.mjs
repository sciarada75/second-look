#!/usr/bin/env node
// The film's subtitles, cut once and used twice:
//   - src/cues.json: the subtitles burned into the picture (src/Subtitles.tsx draws them);
//   - out/second-look-<draft>.srt: the same cues as a closed-caption file for YouTube.
// One cut, one timing: what the viewer reads on screen and in the .srt is the same text at the same frames.
//
// Timings are the film's own: the same measured narration (src/narration.json), the same beats and
// gaps (src/beats.json) and the same arithmetic as src/timeline.ts. Each line is cut into cues of at
// most two rows of 42 characters (sentence, then comma, then word breaks), timed by word count.
//
// Re-run after `node narrate.mjs`, and after any edit to src/lines.json or src/beats.json: the film
// refuses to render with stale cues (Subtitles.tsx checks them against the timeline and the lines).
//
//   node srt.mjs        (draft 4: out/second-look-v4.srt)
//   node srt.mjs v3

import {mkdirSync, readFileSync, writeFileSync} from 'node:fs';

const read = (p) => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const lines = read('./src/lines.json');
const durations = read('./src/narration.json');
const beats = read('./src/beats.json');

const DRAFT = process.argv[2] ?? 'v4';
const FPS = 30;
const sec = (s) => Math.round(s * FPS);
const LEAD = sec(0.6);
const MAX_LINE = 42;
const MAX_CUE = 2 * MAX_LINE;

// The same timing as timeline.ts.
let at = LEAD;
const timed = beats.map((b) => {
  const d = durations[b.key];
  if (d === undefined) throw new Error(`no measured duration for ${b.key}: run node narrate.mjs`);
  const from = at;
  const to = from + Math.round(d * FPS);
  at = to + sec(b.gap ?? 0.5);
  return {key: b.key, from, to};
});

/** Pieces no longer than a cue: sentences first, then commas, then words. */
function pieces(text) {
  const sentences = text.match(/[^.?!:]+[.?!:]*/g).map((s) => s.trim()).filter(Boolean);
  return sentences.flatMap((s) => {
    if (s.length <= MAX_CUE) return [s];
    const parts = s.split(/(?<=,)\s+/);
    return parts.flatMap((p) => {
      if (p.length <= MAX_CUE) return [p];
      const out = [];
      let cur = '';
      for (const w of p.split(/\s+/)) {
        if (cur && (cur + ' ' + w).length > MAX_CUE) { out.push(cur); cur = w; } else cur = cur ? `${cur} ${w}` : w;
      }
      return cur ? [...out, cur] : out;
    });
  });
}

/** Wrap a cue's text into at most two lines of MAX_LINE, as even as possible. */
function wrap(text) {
  if (text.length <= MAX_LINE) return [text];
  const words = text.split(' ');
  let best = null;
  for (let i = 1; i < words.length; i++) {
    const a = words.slice(0, i).join(' '), b = words.slice(i).join(' ');
    if (a.length > MAX_LINE || b.length > MAX_LINE) continue;
    const score = Math.abs(a.length - b.length);
    if (!best || score < best.score) best = {lines: [a, b], score};
  }
  return best ? best.lines : null;
}

/** Join neighbouring pieces while they still fit in one two-line cue. */
function cues(text) {
  const out = [];
  for (const p of pieces(text)) {
    const last = out[out.length - 1];
    if (last && wrap(`${last} ${p}`)) out[out.length - 1] = `${last} ${p}`;
    else out.push(p);
  }
  for (const c of out) if (!wrap(c)) throw new Error(`can't fit "${c}" in two lines of ${MAX_LINE}`);
  return out;
}

const stamp = (frame) => {
  const ms = Math.round((frame / FPS) * 1000);
  const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60;
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)},${pad(ms % 1000, 3)}`;
};

const words = (s) => s.split(/\s+/).length;
const all = []; // {key, from, to, lines}: frames, end exclusive
for (const t of timed) {
  const cs = cues(lines[t.key]);
  const total = cs.reduce((n, c) => n + words(c), 0);
  let acc = 0;
  for (const c of cs) {
    const from = t.from + Math.round(((t.to - t.from) * acc) / total);
    acc += words(c);
    const to = t.from + Math.round(((t.to - t.from) * acc) / total);
    all.push({key: t.key, from, to, lines: wrap(c)});
  }
}

const blocks = all.map((c, i) => `${i + 1}\n${stamp(c.from)} --> ${stamp(c.to)}\n${c.lines.join('\n')}\n`);
mkdirSync(new URL('./out/', import.meta.url), {recursive: true});
writeFileSync(new URL(`./out/second-look-${DRAFT}.srt`, import.meta.url), blocks.join('\n'));

// The line timings go in too, so the film can tell when narration.json or beats.json moved under the cues.
const json = {
  _: 'Written by srt.mjs: do not edit. Re-run node srt.mjs after node narrate.mjs.',
  lines: Object.fromEntries(timed.map((t) => [t.key, {from: t.from, to: t.to}])),
  cues: all,
};
// One cue per row, so a diff of cues.json reads like a diff of the subtitles.
const rows = (entries, open, close) => `${open}\n${entries.map((e) => `  ${e}`).join(',\n')}\n ${close}`;
writeFileSync(new URL('./src/cues.json', import.meta.url), `{
 "_": ${JSON.stringify(json._)},
 "lines": ${rows(Object.entries(json.lines).map(([k, v]) => `${JSON.stringify(k)}: ${JSON.stringify(v)}`), '{', '}')},
 "cues": ${rows(json.cues.map((c) => JSON.stringify(c)), '[', ']')}
}
`);

console.log(`out/second-look-${DRAFT}.srt and src/cues.json: ${all.length} cues, ${timed.length} lines, first at frame ${timed[0].from}, last ends at frame ${timed[timed.length - 1].to}`);
