#!/usr/bin/env node
// Turns src/lines.json into one audio file per spoken block, and writes the
// measured duration of each back into src/narration.json.
//
// This is the step that makes the script the source of truth: edit a sentence,
// run `node narrate.mjs`, and every card, caption and hold in the film retimes
// itself. Nothing downstream holds a hand-typed duration.
//
//   node narrate.mjs            regenerate everything
//   node narrate.mjs s3a s3b    regenerate only those blocks

import {execFileSync} from 'node:child_process';
import {homedir} from 'node:os';
import {readFileSync, writeFileSync, existsSync, mkdirSync, rmSync} from 'node:fs';

// Since draft 9 the voice is Kokoro af_heart (Claudia, 24/10: every macOS voice sounded robotic); see
// kokoro.py. ENGINE=say brings back macOS say: Zoe (Premium) at 165 in draft 8, Jamie (Premium) at 160
// in drafts 4-7.
const ENGINE = process.env.ENGINE ?? 'kokoro';
const VOICE = process.env.VOICE ?? 'Zoe (Premium)'; // say only
const RATE = process.env.RATE ?? '165'; // say only
const KOKORO_HOME = process.env.KOKORO_HOME ?? `${homedir()}/.local/share/kokoro`;
const AUDIO = new URL('./public/audio/', import.meta.url).pathname;
const lines = JSON.parse(readFileSync(new URL('./src/lines.json', import.meta.url), 'utf8'));

// Words the voice gets wrong are respelled here, and ONLY here: lines.json stays
// the text that appears on screen. Without this split, fixing a pronunciation
// would corrupt the subtitle.
const dict = JSON.parse(readFileSync(new URL('./src/pronounce.json', import.meta.url), 'utf8'))[ENGINE];
const speakable = (text) =>
  Object.entries(dict)
    .filter(([k]) => !k.startsWith('_'))
    .reduce(
      (acc, [word, said]) =>
        acc.replace(new RegExp(`\\b${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'gi'), said),
      text
    );

if (!existsSync(AUDIO)) mkdirSync(AUDIO, {recursive: true});

const only = process.argv.slice(2);
const keys = only.length ? only : Object.keys(lines);

const durations = existsSync(new URL('./src/narration.json', import.meta.url))
  ? JSON.parse(readFileSync(new URL('./src/narration.json', import.meta.url), 'utf8'))
  : {};

for (const key of keys) if (!lines[key]) throw new Error(`no line called ${key} in src/lines.json`);

// The raw voice file per line: Kokoro loads its model once for all of them, say runs per line.
const raw = (key) => `${AUDIO}${key}.${ENGINE === 'say' ? 'aiff' : 'raw.wav'}`;
if (ENGINE === 'kokoro') {
  execFileSync(`${KOKORO_HOME}/venv/bin/python`, ['-I', new URL('./kokoro.py', import.meta.url).pathname], {
    input: JSON.stringify(keys.map((key) => ({text: speakable(lines[key]), out: raw(key)}))),
    stdio: ['pipe', 'inherit', 'inherit'],
  });
} else if (ENGINE !== 'say') throw new Error(`unknown ENGINE ${ENGINE}: kokoro or say`);

for (const key of keys) {
  const text = lines[key];
  const wav = `${AUDIO}${key}.wav`;
  if (ENGINE === 'say') execFileSync('say', ['-v', VOICE, '-r', RATE, '-o', raw(key), speakable(text)]);
  execFileSync('afconvert', ['-f', 'WAVE', '-d', 'LEI16@48000', '-c', '1', raw(key), wav]);
  rmSync(raw(key));

  const info = execFileSync('afinfo', [wav], {encoding: 'utf8'});
  const seconds = Number(/estimated duration:\s*([0-9.]+)/.exec(info)[1].trim());
  durations[key] = Number(seconds.toFixed(3));

  const words = text.trim().split(/\s+/).length;
  console.log(
    `${key.padEnd(6)} ${seconds.toFixed(2).padStart(6)}s  ${String(words).padStart(3)} words  ` +
      `${Math.round((words / seconds) * 60)} wpm`
  );
}

writeFileSync(
  new URL('./src/narration.json', import.meta.url),
  JSON.stringify(durations, null, 2) + '\n'
);

const total = Object.values(durations).reduce((a, b) => a + b, 0);
const mm = Math.floor(total / 60);
const ss = Math.round(total % 60);
console.log(`\nspoken total across all blocks: ${mm}:${String(ss).padStart(2, '0')}`);
