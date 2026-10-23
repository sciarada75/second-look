// Draft 3's stage: the captured screens (capture.mjs) with a camera, a spotlight that lights only what
// the voice names, a drawn cursor that makes every click, and a "where you are" label.
//
// Coordinates are CSS px of the captured page, laid out 1536 wide; the screenshots are 3x, so they stay
// sharp up to a zoom of 3. Every component takes absolute film frames, like the rest of the film.
import React from 'react';
import {Easing, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {HEIGHT, WIDTH, theme} from './theme';
import captures from './captures.json';

const EASE = Easing.bezier(0.4, 0, 0.2, 1);
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const ease = (v: number) => EASE(clamp01(v));
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;

export type Box = {x: number; y: number; w: number; h: number};
export type Cam = {x: number; y: number; z: number}; // top-left of the view in page px, and zoom

type Capture = {file: string; width: number; height: number; boxes: Record<string, Box | null>};
const CAPS = captures as unknown as Record<string, Capture>;

export const cap = (id: string): Capture => {
  const c = CAPS[id];
  if (!c || !c.file) throw new Error(`no capture ${id}: run node capture.mjs`);
  return c;
};
/** A named element's box on a capture. Fails loudly: a film never points at a guessed place. */
export const box = (id: string, name: string): Box => {
  const b = cap(id).boxes[name];
  if (!b) throw new Error(`capture ${id} has no box ${name}`);
  return b;
};
/** The smallest box around several. */
export const union = (...bs: Box[]): Box => {
  const x = Math.min(...bs.map((b) => b.x)), y = Math.min(...bs.map((b) => b.y));
  const r = Math.max(...bs.map((b) => b.x + b.w)), btm = Math.max(...bs.map((b) => b.y + b.h));
  return {x, y, w: r - x, h: btm - y};
};

/** Centre a box at zoom z. */
export const camOn = (b: Box, z: number, W = WIDTH, H = HEIGHT): Cam =>
  ({x: b.x + b.w / 2 - W / (2 * z), y: b.y + b.h / 2 - H / (2 * z), z});
/** The whole page width, from a given page y. */
export const camTop = (y = 0): Cam => ({x: 0, y, z: WIDTH / 1536});

/** Keep the view inside the image: no empty edges. */
export const clampCam = (c: Cam, id: string): Cam => {
  const {width, height} = cap(id);
  const vw = WIDTH / c.z, vh = HEIGHT / c.z;
  const x = vw >= width ? (width - vw) / 2 : Math.min(Math.max(c.x, 0), width - vw);
  const y = vh >= height ? (height - vh) / 2 : Math.min(Math.max(c.y, 0), height - vh);
  return {x, y, z: c.z};
};

/** A camera move: from the previous key's view, travel to `cam` starting at `at`, over `dur` frames. */
export type CamKey = {at: number; cam: Cam; dur?: number};
export const camAt = (keys: CamKey[], frame: number, id: string): Cam => {
  // Interpolate the view's centre and the zoom (not the corner), so the thing we travel to stays put.
  const centre = (c: Cam) => ({cx: c.x + WIDTH / (2 * c.z), cy: c.y + HEIGHT / (2 * c.z), z: c.z});
  let c = centre(clampCam(keys[0].cam, id));
  for (const k of keys.slice(1)) {
    if (frame <= k.at) break;
    const p = ease((frame - k.at) / (k.dur ?? 24));
    const t = centre(clampCam(k.cam, id));
    c = {cx: lerp(c.cx, t.cx, p), cy: lerp(c.cy, t.cy, p), z: Math.exp(lerp(Math.log(c.z), Math.log(t.z), p))};
  }
  return clampCam({x: c.cx - WIDTH / (2 * c.z), y: c.cy - HEIGHT / (2 * c.z), z: c.z}, id);
};

/** Page px -> film px. */
export const toFrame = (b: Box, c: Cam): Box => ({x: (b.x - c.x) * c.z, y: (b.y - c.y) * c.z, w: b.w * c.z, h: b.h * c.z});

// ---------- the screen ----------
export const Screen: React.FC<{id: string; cam: Cam}> = ({id, cam}) => {
  const c = cap(id);
  return (
    <div style={{position: 'absolute', inset: 0, overflow: 'hidden', background: theme.paper}}>
      <Img src={staticFile(c.file)} style={{position: 'absolute', left: -cam.x * cam.z, top: -cam.y * cam.z,
        width: c.width * cam.z, height: c.height * cam.z, maxWidth: 'none'}} />
    </div>
  );
};

// ---------- the spotlight ----------
/** From frame `at`, the light moves to `box` (null: the veil lifts). Moves and fades take 10 frames. */
export type Spot = {at: number; box: Box | null};
export const Spotlight: React.FC<{spots: Spot[]; cam: Cam; name: string; strength?: number}> = ({spots, cam, name, strength = 0.55}) => {
  const frame = useCurrentFrame();
  let rect: Box | null = null;
  let o = 0;
  for (const s of spots) {
    if (frame < s.at) break;
    const p = ease((frame - s.at) / 10);
    if (s.box && rect) rect = {x: lerp(rect.x, s.box.x, p), y: lerp(rect.y, s.box.y, p), w: lerp(rect.w, s.box.w, p), h: lerp(rect.h, s.box.h, p)};
    else if (s.box) rect = s.box;
    o = lerp(o, s.box ? 1 : 0, p);
  }
  if (!rect || o <= 0.001) return null;
  const PAD = 10;
  const r = toFrame(rect, cam);
  const hole = {x: r.x - PAD, y: r.y - PAD, w: r.w + 2 * PAD, h: r.h + 2 * PAD};
  const id = `spot-${name}`;
  return (
    <svg width={WIDTH} height={HEIGHT} style={{position: 'absolute', left: 0, top: 0}}>
      <defs>
        <mask id={id}>
          <rect width={WIDTH} height={HEIGHT} fill="white" />
          <rect x={hole.x} y={hole.y} width={hole.w} height={hole.h} rx={12} fill="black" />
        </mask>
      </defs>
      <rect width={WIDTH} height={HEIGHT} fill={`rgba(30,41,53,${strength * o})`} mask={`url(#${id})`} />
      <rect x={hole.x} y={hole.y} width={hole.w} height={hole.h} rx={12} fill="none" stroke={theme.kraft} strokeWidth={3} opacity={o} />
    </svg>
  );
};

// ---------- the cursor ----------
/** A point on the cursor's path: over `box` (at ax/ay of it, default its centre) or at a film position. */
export type CursorPoint = {at: number; box?: Box; ax?: number; ay?: number; pos?: {x: number; y: number}; click?: boolean; move?: number};
export const Cursor: React.FC<{path: CursorPoint[]; cam: Cam; until: number}> = ({path, cam, until}) => {
  const frame = useCurrentFrame();
  if (!path.length || frame < path[0].at || frame >= until) return null;
  const where = (p: CursorPoint) => {
    if (p.box) {
      const b = toFrame(p.box, cam);
      return {x: b.x + b.w * (p.ax ?? 0.5), y: b.y + b.h * (p.ay ?? 0.5)};
    }
    return p.pos ?? {x: WIDTH / 2, y: HEIGHT / 2};
  };
  let i = 0;
  while (i + 1 < path.length && frame >= path[i + 1].at) i++;
  let pos = where(path[i]);
  const next = path[i + 1];
  if (next) {
    const start = Math.max(path[i].at, next.at - (next.move ?? 20));
    const p = ease((frame - start) / Math.max(1, next.at - start));
    const b = where(next);
    pos = {x: lerp(pos.x, b.x, p), y: lerp(pos.y, b.y, p)};
  }
  const appear = clamp01((frame - path[0].at) / 6);
  const clicked = path.filter((p) => p.click && frame >= p.at && frame < p.at + 14).pop();
  const k = clicked ? (frame - clicked.at) / 14 : 1;
  const press = clicked ? interpolate(frame - clicked.at, [0, 3, 8], [1, 0.88, 1], {extrapolateRight: 'clamp'}) : 1;
  return (
    <>
      {clicked ? (
        <div style={{position: 'absolute', left: pos.x, top: pos.y, width: 0, height: 0}}>
          <div style={{position: 'absolute', left: -(12 + 34 * k), top: -(12 + 34 * k), width: 2 * (12 + 34 * k), height: 2 * (12 + 34 * k),
            borderRadius: '50%', border: `4px solid ${theme.kraft}`, opacity: 1 - k, boxSizing: 'border-box'}} />
        </div>
      ) : null}
      <svg width={30} height={40} viewBox="0 0 30 40"
        style={{position: 'absolute', left: pos.x - 3, top: pos.y - 2, opacity: appear, overflow: 'visible',
          transform: `scale(${press})`, transformOrigin: '3px 2px', filter: 'drop-shadow(0 3px 6px rgba(0,0,0,0.35))'}}>
        <path d="M3 2 L3 32 L10.5 25 L15.5 37 L21 34.5 L16 23 L26 23 Z" fill={theme.ink} stroke="#fff" strokeWidth={2} strokeLinejoin="round" />
      </svg>
    </>
  );
};

// ---------- where you are ----------
// Bottom-left, like a lower third: the top of every captured page is its own header (brand, who is signed
// in, the made-up labels), and the chip must never cover it. The chip carries the made-up note itself.
/** fadeIn/fadeOut 0: the label switches with a cut instead of blinking. */
export const WhereLabel: React.FC<{text: string; sub?: string; from: number; to: number; live?: boolean; fadeIn?: number; fadeOut?: number}> = ({
  text, sub, from, to, live, fadeIn = 8, fadeOut = 8,
}) => {
  const frame = useCurrentFrame();
  if (frame < from || frame >= to) return null;
  const o = Math.min(fadeIn ? ease((frame - from) / fadeIn) : 1, fadeOut ? ease((to - frame) / fadeOut) : 1);
  const parts = text.split(' › ');
  return (
    <div style={{position: 'absolute', left: 32, bottom: 32, opacity: o, background: '#fff', padding: '12px 22px 13px',
      border: `1px solid ${live ? theme.pass : theme.rule}`, borderLeft: `6px solid ${live ? theme.pass : theme.kraft}`,
      boxShadow: '0 6px 22px rgba(30,41,53,0.16)', color: theme.ink}}>
      <div style={{font: `500 26px/1.2 ${theme.sans}`, whiteSpace: 'nowrap'}}>
        {parts.map((p, i) => (
          <React.Fragment key={i}>
            {i ? <span style={{color: theme.soft, margin: '0 10px'}}>›</span> : null}
            <span style={{fontWeight: i === parts.length - 1 ? 700 : 500, color: live && i === 0 ? theme.pass : theme.ink}}>{p}</span>
          </React.Fragment>
        ))}
      </div>
      {sub ? <div style={{font: `400 19px/1.3 ${theme.sans}`, color: theme.soft, marginTop: 3}}>{sub}</div> : null}
    </div>
  );
};
