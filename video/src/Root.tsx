import React from 'react';
import {AbsoluteFill, Audio, Composition, Sequence, staticFile} from 'remotion';
import {Caption} from './Pieces';
import {Busier, Connect, Costs, End2, Guard, Intro, Live, Moment, Today} from './Scenes2';
import {FILM_DURATION, LINES, TIMED} from './timeline';
import {FPS, HEIGHT, WIDTH, theme} from './theme';

// Draft 2 (21/10). Draft 1's scenes stay in Scenes.tsx and its script in lines-v1.json (git history
// has the composition). Product pages are loaded live from the app: run `python3 -m secondlook serve`
// before rendering.
const NO_CAPTION = new Set(['s8a']);

const Film: React.FC = () => (
  <AbsoluteFill style={{background: theme.ink}}>
    <Moment /><Costs /><Today /><Intro /><Live /><Busier /><Connect /><Guard /><End2 />
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
