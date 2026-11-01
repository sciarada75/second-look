#!/usr/bin/env node
// The film's own public folder: hard links to only the files draft 10 uses (no extra disk space).
// Every render bundles its public folder into a temp copy; the whole public/ (old recordings and unused
// footage included) made that copy ~700 MB, and on a nearly full disk renders failed (01/11).
//   node public-film.mjs      then render with --public-dir=.public-film (stills.mjs does it itself)
import {existsSync, linkSync, mkdirSync, readFileSync, rmSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const FILM_PUBLIC = join(HERE, '.public-film');
const FOOTAGE = ['footage/web/shipping 3.jpg', 'footage/money flow.mp4', 'footage/web/linen and paper store.jpg',
  'footage/seller daylight.mp4'];
const read = (f) => JSON.parse(readFileSync(join(HERE, 'src', f), 'utf8'));

export function makeFilmPublic() {
  rmSync(FILM_PUBLIC, {recursive: true, force: true});
  // Only what the film reads: one narration clip per beat (Root.tsx), one capture per screen captures.json holds.
  // public/audio keeps clips of earlier drafts, which no beat names: they stay out of every bundle.
  const files = [...FOOTAGE, ...read('beats.json').map((b) => `audio/${b.key}.wav`),
    ...Object.keys(read('captures.json')).filter((k) => k !== 'errors').map((k) => `captures/${k}.png`)];
  for (const f of files) {
    const src = join(HERE, 'public', f);
    if (!existsSync(src)) throw new Error(`missing ${src}`);
    mkdirSync(dirname(join(FILM_PUBLIC, f)), {recursive: true});
    linkSync(src, join(FILM_PUBLIC, f));
  }
  return files.length;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) console.log(`${makeFilmPublic()} files linked into .public-film`);
