import React from 'react';
import {AbsoluteFill, Audio, Composition, Sequence, staticFile} from 'remotion';
import {Scenes3} from './Scenes3';
import {Subtitles} from './Subtitles';
import {FILM_DURATION, TIMED} from './timeline';
import {FPS, HEIGHT, WIDTH, theme} from './theme';

// Draft 3 (23/10): one morning, one journey (script-v3.md). The app scenes are built from screens
// captured by capture.mjs, so rendering needs no server. Subtitles are burned in over every scene
// (Subtitles.tsx), from the same cues srt.mjs writes to the YouTube .srt. Drafts 1 and 2 keep their scenes
// in Scenes.tsx and Scenes2.tsx, their lines in lines-v1.json and lines-v2.json; git history has their
// compositions.
const Film: React.FC = () => (
  <AbsoluteFill style={{background: theme.paper}}>
    <Scenes3 />
    <Subtitles />
    {TIMED.map((t) => (
      <Sequence key={t.key} from={t.from} durationInFrames={t.next - t.from}>
        <Audio src={staticFile(`audio/${t.key}.wav`)} />
      </Sequence>
    ))}
  </AbsoluteFill>
);

export const RemotionRoot: React.FC = () => (
  <Composition id="Film" component={Film} durationInFrames={FILM_DURATION} fps={FPS} width={WIDTH} height={HEIGHT} />
);
