// Burned-in subtitles (open captions): drawn into the picture, so they show wherever the film plays.
// They look like ordinary film and YouTube subtitles on purpose: one cue at a time, white on a dark
// box that hugs the text, centred low, shown only while the voice says it. Draft 2's fixed caption band
// read as part of the script (Claudia, 24/10); these must read as subtitles, not as design.
//
// The cues come from src/cues.json, written by srt.mjs together with the YouTube .srt: one cut, one
// timing for both. Run `node srt.mjs` after `node narrate.mjs`; if the cues are stale this file throws.
import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import cuesFile from './cues.json';
import {LINES, TIMED} from './timeline';

type Cue = {key: string; from: number; to: number; lines: string[]};
const FILE = cuesFile as unknown as {lines: Record<string, {from: number; to: number}>; cues: Cue[]};
const CUES = FILE.cues;

// Stale cues fail loudly: the same timing as the timeline, and the same words as lines.json.
const norm = (s: string) => s.replace(/\s+/g, ' ').trim();
for (const t of TIMED) {
  const l = FILE.lines[t.key];
  if (!l || l.from !== t.from || l.to !== t.to)
    throw new Error(`cues.json is out of date for ${t.key} (timing): run node srt.mjs`);
  const said = CUES.filter((c) => c.key === t.key).map((c) => c.lines.join(' ')).join(' ');
  if (norm(said) !== norm(LINES[t.key])) throw new Error(`cues.json is out of date for ${t.key} (text): run node srt.mjs`);
}

const inter = loadInter('normal', {weights: ['500'], subsets: ['latin']});
const FADE = 4;      // frames, only where a cue starts or ends in silence; back-to-back cues just swap
const BOTTOM = 96;   // px from the bottom to the box: well above the signature (bottom 28, ~22 px tall),
                     // and low enough that a two-row cue stays under the tiles and lists of the cards

export const Subtitles: React.FC = () => {
  const frame = useCurrentFrame();
  const i = CUES.findIndex((c) => frame >= c.from && frame < c.to);
  if (i < 0) return null;
  const c = CUES[i];
  const joinsPrev = i > 0 && CUES[i - 1].to === c.from;
  const joinsNext = i < CUES.length - 1 && CUES[i + 1].from === c.to;
  const fadeIn = joinsPrev ? 1 : interpolate(frame, [c.from, c.from + FADE], [0, 1], {extrapolateRight: 'clamp'});
  const fadeOut = joinsNext ? 1 : interpolate(frame, [c.to - FADE, c.to], [1, 0], {extrapolateLeft: 'clamp'});
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: BOTTOM, display: 'flex', justifyContent: 'center',
      opacity: Math.min(fadeIn, fadeOut), pointerEvents: 'none'}}>
      <div style={{background: 'rgba(12,16,20,0.86)', borderRadius: 8, padding: '6px 18px 8px', textAlign: 'center',
        font: `500 36px/1.3 ${inter.fontFamily}, system-ui, sans-serif`, color: '#fff'}}>
        {c.lines.map((l, j) => <div key={j}>{l}</div>)}
      </div>
    </div>
  );
};
