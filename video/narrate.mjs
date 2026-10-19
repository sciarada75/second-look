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
import {readFileSync, writeFileSync, existsSync, mkdirSync, rmSync} from 'node:fs';

const VOICE = process.env.VOICE ?? 'Jamie (Premium)';
const RATE = process.env.RATE ?? '150';
const AUDIO = new URL('./public/audio/', import.meta.url).pathname;
const lines = JSON.parse(readFileSync(new URL('./src/lines.json', import.meta.url), 'utf8'));

// Words the voice gets wrong are respelled here, and ONLY here: lines.json stays
// the text that appears on screen. Without this split, fixing a pronunciation
// would corrupt the subtitle.
const dict = JSON.parse(readFileSync(new URL('./src/pronounce.json', import.meta.url), 'utf8'));
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

for (const key of keys) {
  const text = lines[key];
  if (!text) throw new Error(`no line called ${key} in src/lines.json`);

  const aiff = `${AUDIO}${key}.aiff`;
  const wav = `${AUDIO}${key}.wav`;
  execFileSync('say', ['-v', VOICE, '-r', RATE, '-o', aiff, speakable(text)]);
  execFileSync('afconvert', ['-f', 'WAVE', '-d', 'LEI16@48000', '-c', '1', aiff, wav]);
  rmSync(aiff);

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
