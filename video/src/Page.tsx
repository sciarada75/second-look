import React from 'react';
import {AbsoluteFill, Easing, IFrame, interpolate, Sequence, useCurrentFrame} from 'remotion';
import {WIDTH, theme} from './theme';

// The product's own pages, loaded live from the running app while the film renders: real screens,
// crisp at any zoom, and no browser around them. `?film=1` switches the pages' fade-ins off.
// Coordinates are CSS pixels of the page laid out 1536 wide (measured 21/10).
const APP = 'http://127.0.0.1:8765';
const LAYOUT_W = 1536;
const EASE = Easing.bezier(0.4, 0, 0.2, 1);
export type Cam = {x: number; y: number; z: number}; // top-left of the view, and zoom

const View: React.FC<{url: string; cam: Cam; to?: Cam; duration: number}> = ({url, cam, to, duration}) => {
  const frame = useCurrentFrame();
  const p = to ? interpolate(frame, [0, duration], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE}) : 0;
  const c = to ? {x: cam.x + (to.x - cam.x) * p, y: cam.y + (to.y - cam.y) * p, z: cam.z + (to.z - cam.z) * p} : cam;
  const src = `${APP}${url}${url.includes('?') ? '&' : '?'}film=1`;
  return (
    <AbsoluteFill style={{background: theme.paper, overflow: 'hidden'}}>
      <IFrame src={src} style={{position: 'absolute', left: 0, top: 0, width: LAYOUT_W, height: 4200, border: 0,
        transformOrigin: '0 0', transform: `scale(${c.z}) translate(${-c.x}px, ${-c.y}px)`}} />
    </AbsoluteFill>
  );
};

export type PageShot = {from: number; to: number; url: string; cam: Cam; pan?: Cam};
export const Pages: React.FC<{shots: PageShot[]}> = ({shots}) => (
  <>
    {shots.map((s, i) => (
      <Sequence key={i} from={s.from} durationInFrames={s.to - s.from}>
        <View url={s.url} cam={s.cam} to={s.pan} duration={s.to - s.from} />
      </Sequence>
    ))}
  </>
);

/** zoom that fits a page width w (css px) into the film's width */
export const fit = (w: number) => WIDTH / w;
