#!/usr/bin/env node
// Renders single frames of the film to check scenes by eye without a full render.
//   node stills.mjs <out-dir> <frame> [<frame> ...]
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';
import {join} from 'node:path';
import {rmSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {FILM_PUBLIC, makeFilmPublic} from './public-film.mjs';

const [out, ...frames] = process.argv.slice(2);
makeFilmPublic();
const serveUrl = await bundle({entryPoint: fileURLToPath(new URL('./src/index.ts', import.meta.url)), publicDir: FILM_PUBLIC});
try {
const composition = await selectComposition({serveUrl, id: 'Film'});
for (const f of frames.map(Number)) {
  await renderStill({serveUrl, composition, frame: f, output: join(out, `f${String(f).padStart(5, '0')}.png`), scale: 0.5, logLevel: process.env.LOG ?? 'info', offthreadVideoCacheSizeInBytes: 200 * 1024 * 1024});
  console.log('frame', f);
}
} finally {
  rmSync(serveUrl, {recursive: true, force: true}); // each bundle copies its public folder: never leave it behind
}
