// The film's design system is the product's own (secondlook/web.py): same paper, ink, kraft labels
// and check colours, same two typefaces. Film and product then read as one thing.
import {loadFont as loadSans} from '@remotion/google-fonts/SchibstedGrotesk';
import {loadFont as loadSerif} from '@remotion/google-fonts/Newsreader';

const sans = loadSans('normal', {weights: ['400', '500', '700'], subsets: ['latin']});
const serif = loadSerif('italic', {weights: ['400', '500'], subsets: ['latin']});

export const theme = {
  paper: '#F5F6F2',
  ink: '#1E2935',
  soft: '#5B6672',
  rule: '#D5D9D2',
  kraft: '#B5874F',
  kraftBg: '#F1E6D6',
  pass: '#2E6A4E',
  fail: '#7B3D6A',
  incon: '#B07418',
  sans: `${sans.fontFamily}, system-ui, sans-serif`,
  serif: `${serif.fontFamily}, Georgia, serif`,
} as const;

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
// Draft 3: the picture is the whole frame. No caption band: subtitles are ordinary burned-in cues
// (Subtitles.tsx), one at a time over the picture, and the same cues go to YouTube as an .srt (srt.mjs).
export const PICTURE_H = HEIGHT;
export const BAND_H = 0;

export const sec = (s: number) => Math.round(s * FPS);
