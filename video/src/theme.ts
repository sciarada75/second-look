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
// The picture sits above a caption band: judges may watch muted, and captions over a screen
// recording would cover the very words the film is showing.
export const PICTURE_H = 920;
export const BAND_H = HEIGHT - PICTURE_H;

export const sec = (s: number) => Math.round(s * FPS);
