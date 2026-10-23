// Every frame number in the film comes from the measured narration (narrate.mjs writes
// narration.json). Edit a line, re-run narrate, and the whole film retimes itself.
import narration from './narration.json';
import lines from './lines.json';
import beats from './beats.json';
import {sec} from './theme';

const durations = narration as Record<string, number>;
export const LINES = lines as Record<string, string>;

// gap = silence after the line, in seconds (beats.json, also read by srt.mjs). Inside a scene the
// lines just follow; between scenes, or after a click, the picture needs a breath.
type Beat = {key: string; gap?: number};
export const BEATS = beats as Beat[];

export type Timed = {key: string; from: number; to: number; next: number};

const LEAD = sec(0.6);
export const TIMED: Timed[] = (() => {
  let at = LEAD;
  return BEATS.map((b) => {
    const d = durations[b.key];
    if (d === undefined) throw new Error(`no measured duration for ${b.key}: run node narrate.mjs`);
    const from = at;
    const to = from + Math.round(d * 30);
    at = to + sec(b.gap ?? 0.5);
    return {key: b.key, from, to, next: at};
  });
})();

export const FILM_DURATION = TIMED[TIMED.length - 1].next;
export const beat = (key: string) => {
  const t = TIMED.find((x) => x.key === key);
  if (!t) throw new Error(`no beat ${key}`);
  return t;
};
/** A scene runs from its first line to the moment the line after its last one starts. */
export const span = (first: string, last: string) => ({from: beat(first).from, to: beat(last).next});

/** Where inside a line a given sentence starts, by word count: the voice speaks at an even pace. */
export const sentenceStarts = (key: string) => {
  const t = beat(key);
  const sentences = LINES[key].match(/[^.?!:]+[.?!:]*/g)?.map((s) => s.trim()).filter(Boolean) ?? [LINES[key]];
  const counts = sentences.map((s) => s.split(/\s+/).length);
  const total = counts.reduce((a, b) => a + b, 0);
  let acc = 0;
  return counts.map((c) => {
    const f = t.from + Math.round(((t.to - t.from) * acc) / total);
    acc += c;
    return f;
  });
};
