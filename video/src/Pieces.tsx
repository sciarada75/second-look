import React from 'react';
import {
  AbsoluteFill, Easing, Img, interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame,
} from 'remotion';
import {BAND_H, PICTURE_H, WIDTH, sec, theme} from './theme';

const EASE = Easing.bezier(0.4, 0, 0.2, 1);

/** Fade in over `up` frames from `from`, out over `down` frames before `to`. */
export const fade = (frame: number, from: number, to: number, up = 8, down = 8) =>
  interpolate(frame, [from, from + up, to - down, to], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE,
  });

/** The picture area: everything above the caption band. */
export const Picture: React.FC<{children: React.ReactNode; bg?: string}> = ({children, bg = theme.ink}) => (
  <div style={{position: 'absolute', left: 0, top: 0, width: WIDTH, height: PICTURE_H, overflow: 'hidden', background: bg}}>
    {children}
  </div>
);

/** Stock footage, covering the picture. */
export const Footage: React.FC<{file: string; startAt?: number; rate?: number; dim?: number}> = ({
  file, startAt = 0, rate = 1, dim = 0.25,
}) => (
  <AbsoluteFill>
    <OffthreadVideo
      src={staticFile(`footage/${file}`)}
      startFrom={sec(startAt)}
      playbackRate={rate}
      muted
      style={{width: '100%', height: '100%', objectFit: 'cover'}}
    />
    <AbsoluteFill style={{background: `rgba(10,14,20,${dim})`}} />
  </AbsoluteFill>
);

// ---------- screen recordings ----------
// Claudia's recordings are the whole Retina screen (3420x2214), Chrome's tabs and bookmarks bar
// included. Those carry other companies' logos, so a shot only ever shows a region BELOW the
// browser's chrome (y > 160 in the half-size coordinates used here), zoomed to fill the picture.
const SRC_W = 3420;
const SRC_H = 2214;
export type Region = {x: number; y: number; w: number}; // half-size pixels (frames measured at 1710 wide)
const CHROME_BOTTOM = 160;

export const Shot: React.FC<{
  file: string;
  at: number; // seconds into the recording where this shot starts
  region: Region;
  to?: Region; // pan/zoom towards this region over the shot
  duration: number; // frames
  rate?: number;
  still?: string; // a frame pulled from the same recording, where the moment is too short to play
}> = ({file, at, region, to, duration, rate = 1, still}) => {
  const frame = useCurrentFrame();
  const p = to ? interpolate(frame, [0, duration], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE}) : 0;
  const r = to ? {x: region.x + (to.x - region.x) * p, y: region.y + (to.y - region.y) * p, w: region.w + (to.w - region.w) * p} : region;
  if (r.y < CHROME_BOTTOM) throw new Error(`shot of ${file} at ${at}s would show the browser chrome`);
  const s = WIDTH / (r.w * 2);
  return (
    <AbsoluteFill style={{background: theme.paper}}>
      {still ? (
        <Img src={staticFile(`stills/${still}`)}
          style={{position: 'absolute', width: SRC_W * s, height: SRC_H * s, left: -r.x * 2 * s, top: -r.y * 2 * s, maxWidth: 'none'}} />
      ) : <OffthreadVideo
        src={staticFile(`recordings/${file}.mov`)}
        startFrom={sec(at)}
        playbackRate={rate}
        muted
        style={{position: 'absolute', width: SRC_W * s, height: SRC_H * s, left: -r.x * 2 * s, top: -r.y * 2 * s, maxWidth: 'none'}}
      />}
    </AbsoluteFill>
  );
};

/** A sequence of shots placed at absolute film frames. */
export type ShotSpec = {from: number; to: number; file: string; at: number; region: Region; pan?: Region; rate?: number; label?: string; still?: string};
export const Shots: React.FC<{shots: ShotSpec[]}> = ({shots}) => (
  <>
    {shots.map((s, i) => (
      <Sequence key={i} from={s.from} durationInFrames={s.to - s.from}>
        <Shot file={s.file} at={s.at} region={s.region} to={s.pan} duration={s.to - s.from} rate={s.rate} still={s.still} />
        {s.label ? <TimeLabel text={s.label} duration={s.to - s.from} /> : null}
      </Sequence>
    ))}
  </>
);

/** Said plainly wherever the edit skips time, so a cut never pretends the product is faster than it is. */
const TimeLabel: React.FC<{text: string; duration: number}> = ({text, duration}) => {
  const frame = useCurrentFrame();
  const o = fade(frame, 0, Math.min(duration, sec(3)), 4, 10);
  return (
    <div style={{position: 'absolute', right: 48, top: 40, opacity: o, background: theme.incon, color: '#fff',
      font: `700 40px ${theme.sans}`, padding: '14px 26px', boxShadow: '0 6px 24px rgba(0,0,0,0.25)'}}>{text}</div>
  );
};

// ---------- captions ----------
export const Caption: React.FC<{text: string; from: number; to: number}> = ({text, from, to}) => {
  const frame = useCurrentFrame();
  const o = fade(frame, from - 4, to + 10, 6, 8);
  if (o <= 0) return null;
  const size = text.length > 120 ? 34 : text.length > 70 ? 38 : 42;
  return (
    <div style={{position: 'absolute', left: 0, top: PICTURE_H, width: WIDTH, height: BAND_H, display: 'flex',
      alignItems: 'center', justifyContent: 'center', padding: '0 140px', boxSizing: 'border-box', opacity: o,
      color: theme.paper, font: `400 ${size}px/1.3 ${theme.sans}`, textAlign: 'center'}}>
      {text}
    </div>
  );
};
