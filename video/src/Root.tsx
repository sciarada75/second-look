import React from 'react';
import {AbsoluteFill, Audio, Composition, Sequence, staticFile} from 'remotion';
import {Scenes4} from './Scenes4';
import {Subtitles} from './Subtitles';
import {FILM_DURATION, TIMED} from './timeline';
import {FPS, HEIGHT, WIDTH, theme} from './theme';

// Draft 10 (01/11): every channel, one morning (script-v4.md). The app scenes are built from screens
// captured by capture.mjs, so rendering needs no server. Subtitles are burned in over every scene
// (Subtitles.tsx), from the same cues srt.mjs writes to the YouTube .srt. Earlier drafts keep their scenes
// in Scenes.tsx, Scenes2.tsx and Scenes3.tsx (drafts 3-9), their lines in lines-v1/v2/v3.json; git history
// has their compositions and captures.
const Film: React.FC = () => (
  <AbsoluteFill style={{background: theme.paper}}>
    <Scenes4 />
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
