import React from 'react';
import {AbsoluteFill, Audio, Composition, Sequence, staticFile} from 'remotion';
import {Caption} from './Pieces';
import {End, Evening, Flow1, Flow2, LiveA, LiveB, Opening, Rules, Strange, Tests, Title} from './Scenes';
import {FILM_DURATION, LINES, TIMED} from './timeline';
import {FPS, HEIGHT, WIDTH, theme} from './theme';

// Lines the picture already shows as words get no caption underneath (the buyer's quote, the end line).
const NO_CAPTION = new Set(['s1b', 's10b']);

const Film: React.FC = () => (
  <AbsoluteFill style={{background: theme.ink}}>
    <Opening /><Evening /><Strange /><Title /><Flow1 /><LiveA /><LiveB /><Flow2 /><Rules /><Tests /><End />
    {TIMED.map((t) => (
      <Sequence key={t.key} from={t.from} durationInFrames={t.next - t.from}>
        <Audio src={staticFile(`audio/${t.key}.wav`)} />
      </Sequence>
    ))}
    {TIMED.filter((t) => !NO_CAPTION.has(t.key)).map((t) => (
      <Caption key={t.key} text={LINES[t.key]} from={t.from} to={t.to} />
    ))}
  </AbsoluteFill>
);

export const RemotionRoot: React.FC = () => (
  <Composition id="Film" component={Film} durationInFrames={FILM_DURATION} fps={FPS} width={WIDTH} height={HEIGHT} />
);
