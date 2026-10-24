// Draft 3 (23/10): one morning, one journey. Ten scenes, each answering one question; the screen shows
// only what the voice names. App scenes are built on the captured journey (capture.mjs, Stage.tsx);
// graphic scenes are cards in the product's own design. Script: video/script-v3.md.
import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame} from 'remotion';
import {Arrow, Box as FlowBox} from './Scenes';
import {beat, sentenceStarts} from './timeline';
import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import {HEIGHT, WIDTH, theme} from './theme';
import {
  box, Box, camAt, camOn, camTop, Cam, CamKey, Cursor, CursorPoint, Screen, Spot, Spotlight, union, WhereLabel,
} from './Stage';

const EASE = Easing.bezier(0.4, 0, 0.2, 1);
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
/** A frame a fraction of the way through a line. */
const at = (key: string, f: number) => {
  const b = beat(key);
  return b.from + Math.round((b.to - b.from) * f);
};
const fadeIn = (frame: number, on: number, d = 10) => interpolate(frame, [on, on + d], [0, 1], {...clamp, easing: EASE});

/** A scene: shown in [from, to), fades in over 8 frames from `under` (paper; ink for the dark scenes,
 *  so two dark scenes in a row never flash pale between them). */
const Scene: React.FC<{from: number; to: number; children: React.ReactNode; bg?: string; under?: string}> = ({from, to, children, bg = theme.paper, under = theme.paper}) => {
  const frame = useCurrentFrame();
  if (frame < from || frame >= to) return null;
  return (
    <AbsoluteFill style={{background: under}}>
      <AbsoluteFill style={{opacity: fadeIn(frame, from, 8), background: bg}}>{children}</AbsoluteFill>
    </AbsoluteFill>
  );
};

// ---------- app shots ----------
type Where = {text: string; sub?: string; live?: boolean};
type ShotSpec = {
  id: string; from: number; to: number; cams: CamKey[]; spots?: Spot[]; cursor?: CursorPoint[];
  where: Where; labelIn?: boolean; labelOut?: boolean; strength?: number;
};
const AppShot: React.FC<{s: ShotSpec}> = ({s}) => {
  const frame = useCurrentFrame();
  if (frame < s.from || frame >= s.to) return null;
  const cam: Cam = camAt(s.cams, frame, s.id);
  return (
    <AbsoluteFill>
      <Screen id={s.id} cam={cam} />
      <Spotlight spots={s.spots ?? []} cam={cam} name={`${s.id}-${s.from}`} strength={s.strength} />
      {s.cursor ? <Cursor path={s.cursor} cam={cam} until={s.to} /> : null}
      <WhereLabel {...s.where} from={s.from} to={s.to} fadeIn={s.labelIn ? 8 : 0} fadeOut={s.labelOut ? 8 : 0} />
    </AbsoluteFill>
  );
};
const Shots: React.FC<{shots: ShotSpec[]}> = ({shots}) => <>{shots.map((s) => <AppShot key={`${s.id}-${s.from}`} s={s} />)}</>;

const MARTA_TB = {sub: 'Marta · a made-up helpdesk'};
const MARTA_SL = {sub: 'Marta · demo shop, made-up data'};
const GIULIA_SL = {sub: 'Giulia · demo shop, made-up data'};
const CUT = 8; // frames between a click and the page it opens
/** On a Second Look case page: only the right column, zoomed so the left column (with the big buyer
 *  quote) stays entirely out of frame instead of being sliced at the edge. */
const rightCol = (b: Box, z = 2.3): Cam => ({...camOn(b, z), x: 1536 - WIDTH / z});
/** A measured box with room around it: the timeline's labels spill a little outside its own box. */
const grow = (b: Box, px: number): Box => ({x: b.x - px, y: b.y - px, w: b.w + 2 * px, h: b.h + 2 * px});

// The moments where one scene's last click opens the next scene's page.
const click45 = () => beat('s5a').from + 6;          // "She opens the case."
const cut45 = () => click45() + CUT;
const click6 = () => beat('s6a').from + 16;          // "She approves."
const cut6 = () => click6() + CUT;
const giuliaOpens = () => beat('s8a').from - 36;     // the case arrives in Giulia's list before the voice names her

// ---------- backgrounds ----------
// Claudia's pictures and reels behind the graphic scenes (draft 4: "make the presentation taste more
// real"): cover-cropped, blurred, under a veil, with a slow push-in. Every clip used here was checked
// frame by frame for logos (HANDOVER, Video). Text never sits on the picture itself: on white cards and
// tiles, or in light type over a dark veil.
const Backdrop: React.FC<{
  src: string; from: number; to: number; video?: boolean; startAt?: number; rate?: number;
  veil?: string; blur?: number; push?: number;
}> = ({src, from, to, video, startAt = 0, rate = 1, veil = 'rgba(30,41,53,0.66)', blur = 10, push = 0.06}) => {
  const frame = useCurrentFrame();
  if (frame < from || frame >= to) return null;
  const s = 1.06 + push * interpolate(frame, [from, to], [0, 1], clamp); // overscan hides the blur's soft edge
  const style: React.CSSProperties = {position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover',
    filter: `blur(${blur}px)`, transform: `scale(${s})`};
  return (
    <AbsoluteFill style={{overflow: 'hidden', background: theme.ink}}>
      {video ? (
        <Sequence from={from} durationInFrames={to - from}>
          <OffthreadVideo src={staticFile(src)} startFrom={Math.round(startAt * 30)} playbackRate={rate} muted style={style} />
        </Sequence>
      ) : <Img src={staticFile(src)} style={style} />}
      <AbsoluteFill style={{background: veil}} />
    </AbsoluteFill>
  );
};

// ---------- 1. What happens? ----------
// The buyer's words are not spoken: they type out in the silence after "A buyer has opened a PayPal dispute."
const MESSAGE = '“Never received the apron. Refund me or I go to PayPal.”';
const Moment: React.FC = () => {
  const frame = useCurrentFrame();
  const a = beat('s1a');
  const from = a.from, to = beat('s1b').next;
  const shown = Math.round(interpolate(frame, [a.to + 2, a.next - 4], [0, MESSAGE.length], clamp));
  const card = fadeIn(frame, from + 4, 12);
  return (
    <Scene from={from} to={to} under={theme.ink}>
      <Backdrop src="footage/web/shipping 3.jpg" from={from} to={to} blur={16} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
        <div style={{opacity: card, transform: `translateY(${(1 - card) * 16}px)`, width: 1180, background: '#fff',
          borderLeft: `8px solid ${theme.fail}`, padding: '44px 56px 50px', boxSizing: 'border-box',
          boxShadow: '0 24px 70px rgba(0,0,0,0.35)'}}>
          <div style={{font: `500 26px ${theme.sans}`, color: theme.soft}}>A buyer writes</div>
          <div style={{font: `400 66px/1.25 ${theme.serif}`, color: theme.ink, marginTop: 18, minHeight: 166}}>
            {MESSAGE.slice(0, shown)}<span style={{opacity: 0}}>{MESSAGE.slice(shown)}</span>
          </div>
        </div>
        <div style={{opacity: card, marginTop: 30, background: theme.kraftBg, color: '#6E4F27', borderLeft: `5px solid ${theme.kraft}`,
          font: `500 30px ${theme.sans}`, padding: '10px 20px'}}>PayPal dispute · 58.00 EUR</div>
      </AbsoluteFill>
    </Scene>
  );
};

// ---------- 2 and 2b: tiles that land, stay and build a benchmark ----------
// One fixed layout for both screens: a title block and a row of three tiles, centred together in the
// frame. Every tile has its final slot from the start (same size, same place); landing is a fade and a
// 20 px rise, nothing else moves. `big` may start with a currency prefix, set smaller ("US$").
type Tile = {on: number; label?: string; prefix?: string; big: string; sub: string; extra?: string; extraOn?: number; tone: string; src: string};
const TILE_W = 456, TILE_GAP = 36, TILE_H = 352;      // the row spans 1440 px, 75% of the width
const TITLE_H = 132, ROW_GAP = 48, SRC_H = 76;
const BLOCK_TOP = Math.round((HEIGHT - (TITLE_H + ROW_GAP + TILE_H + SRC_H)) / 2);
const Tiles: React.FC<{tiles: Tile[]; title: string; subtitle: string; titleOn: number}> = ({tiles, title, subtitle, titleOn}) => {
  const frame = useCurrentFrame();
  const lit = tiles.filter((t) => frame >= t.on).length - 1;
  const rowW = 3 * TILE_W + 2 * TILE_GAP;
  const t0 = fadeIn(frame, titleOn, 12);
  return (
    <AbsoluteFill>
      <div style={{position: 'absolute', left: 0, right: 0, top: BLOCK_TOP, height: TITLE_H, textAlign: 'center',
        opacity: t0, transform: `translateY(${(1 - t0) * 12}px)`, textShadow: '0 2px 18px rgba(0,0,0,0.45)'}}>
        <div style={{font: `700 60px/1.15 ${theme.sans}`, color: theme.paper, letterSpacing: -1}}>{title}</div>
        <div style={{font: `400 32px/1.3 ${theme.sans}`, color: '#D3D9DE', marginTop: 12}}>{subtitle}</div>
      </div>
      {tiles.map((t, i) => {
        const o = fadeIn(frame, t.on, 12);
        if (o <= 0) return null;
        // the tile being named is lit; the ones before it dim slightly, and stay
        const dim = i < lit ? interpolate(frame, [tiles[lit].on, tiles[lit].on + 10], [1, 0.62], clamp) : 1;
        const ring = i === lit ? fadeIn(frame, t.on, 10) : i === lit - 1 ? 1 - fadeIn(frame, tiles[lit].on, 10) : 0;
        return (
          <div key={i} style={{position: 'absolute', left: (WIDTH - rowW) / 2 + i * (TILE_W + TILE_GAP), top: BLOCK_TOP + TITLE_H + ROW_GAP,
            width: TILE_W, opacity: o * dim, transform: `translateY(${(1 - o) * 20}px)`}}>
            <div style={{height: TILE_H, background: '#fff', borderTop: `10px solid ${t.tone}`, padding: '28px 32px', boxSizing: 'border-box',
              boxShadow: `0 20px 60px rgba(0,0,0,0.35), 0 0 0 ${4 * ring}px ${theme.kraft}`}}>
              {t.label ? <div style={{font: `500 30px/1.25 ${theme.sans}`, color: theme.soft, marginBottom: 6}}>{t.label}</div> : null}
              <div style={{font: `700 120px/1.05 ${theme.sans}`, color: t.tone, letterSpacing: -4, whiteSpace: 'nowrap'}}>
                {t.prefix ? <span style={{fontSize: 60, letterSpacing: -1, marginRight: 4}}>{t.prefix}</span> : null}{t.big}
              </div>
              <div style={{font: `500 32px/1.25 ${theme.sans}`, color: theme.ink, marginTop: 12}}>{t.sub}</div>
              {t.extra ? <div style={{font: `400 28px/1.3 ${theme.sans}`, color: theme.soft, marginTop: 10,
                opacity: t.extraOn ? fadeIn(frame, t.extraOn, 10) : 1}}>{t.extra}</div> : null}
            </div>
            <div style={{font: `400 24px/1.35 ${theme.sans}`, color: '#E3E7EA', marginTop: 14, textShadow: '0 1px 8px rgba(0,0,0,0.6)'}}>{t.src}</div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

// 2. What does a dispute cost?
const Costs: React.FC = () => {
  const from = beat('s2a').from, to = beat('s2c').next;
  const tiles: Tile[] = [
    {on: beat('s2a').from + 16, label: 'Settled in the dispute', big: '0 EUR', sub: 'PayPal fee', tone: theme.pass, src: 'PayPal User Agreement, 14 Sep 2026'},
    {on: beat('s2b').from, label: 'A claim, lost', big: '14 EUR', sub: 'PayPal fee', tone: theme.fail, src: 'PayPal fees, 7 Sep 2026'},
    {on: beat('s2c').from, label: 'A busy shop, any claim', big: '28 EUR', sub: 'even when you win', tone: theme.fail, src: 'PayPal fees + User Agreement'},
  ];
  return (
    <Scene from={from} to={to} under={theme.ink}>
      <Backdrop src="footage/money flow.mp4" video from={from} to={to} rate={0.85} />
      <Tiles tiles={tiles} title="What a dispute costs the shop" subtitle="PayPal's own fees" titleOn={from} />
    </Scene>
  );
};

// 2b. What does it do to a business? Currency as the sources give it.
const Business: React.FC = () => {
  const from = beat('s2e').from, to = beat('s2g').next;
  const [, e2] = sentenceStarts('s2e'); // "a single customer-care contact", after "And disputes cost more than fees:"
  const tiles: Tile[] = [
    {on: e2, prefix: 'US$', big: '8.01', sub: 'per live customer-care contact', extra: 'vs US$0.10 self-service', tone: theme.ink, src: 'Gartner, 2019'},
    {on: beat('s2f').from, prefix: 'US$', big: '4.61', sub: 'lost for every US$1 of fraud', tone: theme.fail,
      src: 'LexisNexis True Cost of Fraud, 2025 · US retail & e-commerce'},
    {on: beat('s2g').from, big: '46%', sub: 'of card chargebacks accepted without a fight', extra: 'won 1 in 5 when fought',
      extraOn: at('s2g', 0.55), tone: theme.incon, src: 'Mastercard / Datos 2025 · midsize & large merchants'},
  ];
  return (
    <Scene from={from} to={to} under={theme.ink}>
      <Backdrop src="footage/late night answer 3.mp4" video from={from} to={to} rate={0.9} />
      <Tiles tiles={tiles} title="What disputes cost a business" subtitle="public figures, each with its source" titleOn={from} />
    </Scene>
  );
};

// ---------- 2c. So what helps? Second Look, before we meet the shop ----------
// The product's own mark (two rings: kraft and ink) and name; then what it does, each item as the voice
// names it; then "You approve", lit in kraft, on the last sentence.
const MARK = (size: number) => (
  <svg width={size * 30 / 22} height={size} viewBox="0 0 30 22" aria-hidden="true">
    <circle cx="11" cy="11" r="9" fill={theme.kraft} />
    <circle cx="19" cy="11" r="9" fill="none" stroke={theme.ink} strokeWidth={3} />
  </svg>
);
const Enter: React.FC = () => {
  const frame = useCurrentFrame();
  const from = beat('s2h').from, to = beat('s2h').next;
  // Where the voice says each word, as a share of the line (whisper word timestamps on s2h.wav, draft 8,
  // Zoe): "It's" 0.143, "reads" 0.234, "runs" 0.533, "drafts" 0.734, "Nothing" 0.838.
  const w2 = at('s2h', 0.143), w3 = at('s2h', 0.838);
  const items = [
    {on: at('s2h', 0.234), text: 'Reads the dispute and PayPal’s evidence'},
    {on: at('s2h', 0.533), text: 'Runs a specialist’s ten checks'},
    {on: at('s2h', 0.734), text: 'Drafts the answer'},
  ];
  const head = fadeIn(frame, from + 2, 14);
  const person = fadeIn(frame, w3, 12);
  return (
    <Scene from={from} to={to}>
      <div style={{position: 'absolute', left: 0, right: 0, top: 190, display: 'flex', alignItems: 'center', justifyContent: 'center',
        gap: 30, opacity: head, transform: `translateY(${(1 - head) * 14}px)`}}>
        {MARK(96)}
        <div style={{font: `700 112px/1 ${theme.sans}`, color: theme.ink, letterSpacing: -3}}>Second Look</div>
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: 340, textAlign: 'center', font: `400 46px ${theme.serif}`,
        color: theme.soft, opacity: fadeIn(frame, w2, 12)}}>an AI for PayPal disputes</div>
      <div style={{position: 'absolute', left: (WIDTH - 1000) / 2, width: 1000, top: 470}}>
        {items.map((it, i) => {
          const o = fadeIn(frame, it.on, 12);
          return (
            <div key={i} style={{display: 'flex', alignItems: 'center', gap: 26, padding: '16px 0', borderTop: `1px solid ${theme.rule}`,
              opacity: o * (1 - 0.35 * person), transform: `translateY(${(1 - o) * 14}px)`}}>
              <span style={{width: 46, font: `700 36px ${theme.sans}`, color: theme.kraft}}>{i + 1}</span>
              <span style={{font: `500 46px/1.2 ${theme.sans}`, color: theme.ink}}>{it.text}</span>
            </div>
          );
        })}
        <div style={{marginTop: 26, display: 'flex', alignItems: 'center', gap: 26, padding: '22px 30px', background: theme.kraftBg,
          borderLeft: `8px solid ${theme.kraft}`, opacity: person, transform: `translateY(${(1 - person) * 14}px)`}}>
          <span style={{font: `700 54px/1.15 ${theme.sans}`, color: '#6E4F27'}}>You approve</span>
          <span style={{font: `400 34px ${theme.sans}`, color: '#6E4F27'}}>Nothing is sent before.</span>
        </div>
      </div>
    </Scene>
  );
};

// ---------- 3. Who are we following? ----------
const PEOPLE = [
  {name: 'Marta', initials: 'M', role: 'Customer care agent', note: 'refunds up to 30 EUR', color: theme.kraft},
  {name: 'Giulia', initials: 'G', role: 'Customer care manager', note: '', color: theme.ink},
  {name: 'Luca', initials: 'L', role: 'Customer care agent', note: '', color: theme.soft},
  {name: 'Sara', initials: 'S', role: 'Customer care agent', note: '', color: theme.soft},
];
const Team: React.FC = () => {
  const frame = useCurrentFrame();
  const from = beat('s3a').from, to = beat('s3b').next;
  const [m, g] = sentenceStarts('s3b');
  const ons = [m, g, g + 24, g + 24];
  const card = fadeIn(frame, from, 12);
  return (
    <Scene from={from} to={to}>
      {/* the shop itself: a light paper veil, so the ink type reads as on the product's own pages */}
      <Backdrop src="footage/web/linen and paper store.jpg" from={from} to={to} blur={5} veil="rgba(245,246,242,0.80)" />
      <div style={{position: 'absolute', left: 0, right: 0, top: 150, textAlign: 'center', opacity: card}}>
        <div style={{font: `700 92px/1.1 ${theme.sans}`, color: theme.ink, letterSpacing: -2}}>Linen &amp; Paper</div>
        <div style={{font: `500 40px ${theme.sans}`, color: theme.ink, opacity: 0.8, marginTop: 18}}>a made-up shop · about 2,000 orders a month</div>
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: 520, display: 'flex', justifyContent: 'center', gap: 70}}>
        {PEOPLE.map((p, i) => {
          const o = fadeIn(frame, ons[i], 12) * (i < 2 ? 1 : 0.45);
          return (
            <div key={p.name} style={{width: 340, textAlign: 'center', opacity: o, transform: `translateY(${(1 - Math.min(1, o / (i < 2 ? 1 : 0.45))) * 16}px)`}}>
              <div style={{width: 150, height: 150, borderRadius: 75, background: p.color, color: '#fff', margin: '0 auto',
                display: 'flex', alignItems: 'center', justifyContent: 'center', font: `700 64px ${theme.sans}`}}>{p.initials}</div>
              <div style={{font: `700 40px ${theme.sans}`, color: theme.ink, marginTop: 22}}>{p.name}</div>
              <div style={{font: `500 27px/1.35 ${theme.sans}`, color: theme.ink, opacity: 0.75, marginTop: 6}}>{p.role}</div>
              {p.note ? <div style={{font: `700 27px ${theme.sans}`, color: '#6E4F27', marginTop: 4}}>{p.note}</div> : null}
            </div>
          );
        })}
      </div>
    </Scene>
  );
};

// ---------- 4. Where does the case reach the team? ----------
const Helpdesk: React.FC = () => {
  const from = beat('s4a').from, to = cut45();
  const a = beat('s4a'), b = beat('s4b');
  const [b1, b2, b3] = sentenceStarts('s4b');
  const clickRow = a.to + 10; // in the silence after "Marta opens her helpdesk." (short since draft 8)
  const panelCam = camOn(box('tb-2001', 'panel'), 1.6);
  const shots: ShotSpec[] = [
    {id: 'tb-inbox', from, to: clickRow + CUT, cams: [{at: from, cam: camTop()}],
      cursor: [{at: at('s4a', 0.3), pos: {x: 1560, y: 820}}, {at: clickRow, box: box('tb-inbox', 'row-dario'), ax: 0.4, click: true, move: 34}],
      spots: [{at: clickRow - 16, box: box('tb-inbox', 'row-dario')}],
      where: {text: 'Ticketbook › Inbox', ...MARTA_TB}, labelIn: true},
    {id: 'tb-2001', from: clickRow + CUT, to,
      cams: [{at: from, cam: camTop()}, {at: b2, cam: panelCam, dur: 30}],
      spots: [{at: b1, box: box('tb-2001', 'email')}, {at: b2, box: box('tb-2001', 'panel')}, {at: b3, box: box('tb-2001', 'verdict')},
        {at: click45() - 14, box: box('tb-2001', 'open-sl')}],
      cursor: [{at: b.to, box: box('tb-2001', 'verdict'), ax: 0.75, ay: 1.6}, {at: click45(), box: box('tb-2001', 'open-sl'), click: true, move: 24}],
      where: {text: 'Ticketbook › Ticket #2001', ...MARTA_TB}},
  ];
  return <Scene from={from} to={to}><Shots shots={shots} /></Scene>;
};

// ---------- 5. How does she know? ----------
const TheCase: React.FC = () => {
  const from = cut45(), to = beat('s6a').from;
  const [, a2] = sentenceStarts('s5a');
  const addr = at('s5a', 0.7); // ", to the address on Dario's PayPal account"
  const id = 'sl-031';
  const where = union(box(id, 'ships-to'), box(id, 'delivery'));
  const shots: ShotSpec[] = [
    {id, from, to,
      cams: [{at: from, cam: camTop()}, {at: a2, cam: camOn(box(id, 'timeline'), 1.6), dur: 26},
        {at: addr, cam: camOn(where, 1.6), dur: 26}, {at: beat('s5b').from, cam: camOn(box(id, 'history'), 1.6), dur: 26},
        {at: beat('s5c').from, cam: rightCol(box(id, 'costs')), dur: 30}],
      spots: [{at: a2 + 10, box: grow(box(id, 'timeline'), 24)}, {at: addr + 10, box: where}, {at: beat('s5b').from + 10, box: box(id, 'history')},
        {at: beat('s5c').from + 12, box: box(id, 'costs')}],
      where: {text: 'Second Look › Case DEMO-031', ...MARTA_SL}},
  ];
  return <Scene from={from} to={to}><Shots shots={shots} /></Scene>;
};

// ---------- 6. What happens when she approves? ----------
const Approve: React.FC = () => {
  const from = beat('s6a').from, to = beat('s6a').next;
  const records = at('s6a', 0.74); // "and the ticket records who sent it" (whisper, Zoe: "ticket" at 0.785)
  const sent = 'tb-2001-sent';
  const shots: ShotSpec[] = [
    {id: 'tb-2001', from, to: cut6(), cams: [{at: from, cam: camOn(box('tb-2001', 'panel'), 1.6)}],
      spots: [{at: from, box: box('tb-2001', 'approve')}],
      cursor: [{at: from, box: box('tb-2001', 'verdict'), ax: 0.75, ay: 1.6}, {at: click6(), box: box('tb-2001', 'approve'), ax: 0.5, click: true, move: 14}],
      where: {text: 'Ticketbook › Ticket #2001', ...MARTA_TB}, labelIn: true},
    {id: sent, from: cut6(), to,
      cams: [{at: cut6(), cam: camOn(box(sent, 'flash'), 1.6)}, {at: records - 10, cam: camOn(box(sent, 'panel'), 1.6), dur: 24}],
      spots: [{at: cut6() + 2, box: box(sent, 'flash')}, {at: records + 6, box: box(sent, 'history-line')}],
      where: {text: 'Ticketbook › Ticket #2001', ...MARTA_TB}, labelOut: true},
  ];
  return <Scene from={from} to={to}><Shots shots={shots} /></Scene>;
};

// ---------- 7. What if it's more than she may give? ----------
const OverLimit: React.FC = () => {
  const from = beat('s7a').from, to = giuliaOpens();
  const [, a2] = sentenceStarts('s7a'); // "Pablo sent a shirt back" (whisper: 0.437 of the line)
  const [, b2] = sentenceStarts('s7b');
  const id = 'tb-2004', after = 'tb-2004-passed';
  const passBlock = union(box(id, 'pass'), box(id, 'pass-says'));
  const aiCall = union(box(id, 'your-call'), box(id, 'ai-says'));
  const clickPass = at('s7b', 0.7); // "goes to Giulia" (whisper, Zoe: "Giulia" at 0.713)
  const shots: ShotSpec[] = [
    {id, from, to: clickPass + CUT,
      cams: [{at: from, cam: camOn(aiCall, 1.6)}, {at: a2 - 6, cam: camTop(), dur: 26},
        {at: beat('s7b').from, cam: camOn(passBlock, 1.6), dur: 26}],
      spots: [{at: from + 8, box: aiCall}, {at: a2 + 4, box: box(id, 'email')},
        {at: beat('s7b').from + 8, box: box(id, 'pass-says')}, {at: b2, box: passBlock}],
      cursor: [{at: b2 - 4, pos: {x: 1500, y: 980}}, {at: clickPass, box: box(id, 'pass'), click: true, move: 22}],
      where: {text: 'Ticketbook › Ticket #2004', ...MARTA_TB}, labelIn: true},
    {id: after, from: clickPass + CUT, to, cams: [{at: from, cam: camOn(box(after, 'flash'), 1.6)}],
      spots: [{at: clickPass + CUT + 2, box: box(after, 'flash')}],
      where: {text: 'Ticketbook › Ticket #2004', ...MARTA_TB}, labelOut: true},
  ];
  return <Scene from={from} to={to}><Shots shots={shots} /></Scene>;
};

// ---------- 8. Who decides, and what's the big picture? ----------
const Giulia: React.FC = () => {
  const from = giuliaOpens(), to = beat('s8b').next;
  const a = beat('s8a');
  const clickRow = at('s8a', 0.16);   // "Giulia sees" 
  const note = clickRow + CUT;
  const reply = at('s8a', 0.5);    // "and her reply"
  const clickApprove = at('s8a', 0.9); // "approves the refund"
  const list = 'sl-list-giulia', page = 'sl-034-giulia', sent = 'sl-034-sent', ov = 'sl-overview';
  const replyBlock = union(box(page, 'reply'), box(page, 'approve'));
  const [, o2] = sentenceStarts('s8b');
  const meter = at('s8b', 0.5); // "and how far the shop is from PayPal's busy-shop line"
  const shots: ShotSpec[] = [
    // The list is framed below its header: the header marks the wrong tab on this page (a Second Look bug, reported).
    {id: list, from, to: note, cams: [{at: from, cam: {x: 24, y: 241, z: 1.65}}],
      spots: [{at: from + 8, box: box(list, 'owner-034')}, {at: clickRow - 12, box: box(list, 'row-034')}],
      cursor: [{at: a.from - 4, pos: {x: 1400, y: 900}}, {at: clickRow, box: box(list, 'row-034'), ax: 0.3, click: true, move: 22}],
      where: {text: 'Second Look › Disputes', ...GIULIA_SL}, labelIn: true},
    {id: page, from: note, to: clickApprove + CUT,
      cams: [{at: note, cam: rightCol(box(page, 'note'))}, {at: reply - 8, cam: rightCol(replyBlock), dur: 22}],
      spots: [{at: note + 2, box: box(page, 'note')}, {at: reply, box: box(page, 'reply')}, {at: clickApprove - 14, box: box(page, 'approve')}],
      cursor: [{at: reply + 6, pos: {x: 1500, y: 950}}, {at: clickApprove, box: box(page, 'approve'), click: true, move: 18}],
      where: {text: 'Second Look › Case DEMO-034', ...GIULIA_SL}},
    {id: sent, from: clickApprove + CUT, to: a.next, cams: [{at: from, cam: rightCol(box(sent, 'sent'))}],
      spots: [{at: clickApprove + CUT + 2, box: box(sent, 'sent')}],
      where: {text: 'Second Look › Case DEMO-034', ...GIULIA_SL}},
    {id: ov, from: a.next, to,
      cams: [{at: a.next, cam: camTop()}, {at: o2 - 4, cam: camOn(box(ov, 'exposure'), 1.4), dur: 30}, {at: meter - 4, cam: camOn(box(ov, 'meter'), 1.6), dur: 30}],
      spots: [{at: o2 + 12, box: box(ov, 'exposure')}, {at: meter + 10, box: box(ov, 'meter')}],
      where: {text: 'Second Look › Overview', ...GIULIA_SL}, labelOut: true},
  ];
  return <Scene from={from} to={to}><Shots shots={shots} /></Scene>;
};

// ---------- 9. Is it real? ----------
const Live: React.FC = () => {
  const from = beat('s9a').from, to = beat('s9a').next;
  const [, s2, s3, s4] = sentenceStarts('s9a');
  const proof = at('s9a', 0.8); // "and the tracking went to PayPal as proof"
  const id = 'sl-live';
  const shots: ShotSpec[] = [
    {id, from, to, strength: 0.7,
      // Close on "What's been said": at this zoom the right column, whose "Reply not sent" is about a later
      // step, stays out of frame and can't be misread against "the reply went to the buyer".
      cams: [{at: from, cam: camTop()}, {at: s3 - 4, cam: camOn(box(id, 'said'), 2.15), dur: 30},
        {at: s4 - 4, cam: camOn(union(box(id, 'reply'), box(id, 'proof')), 2.15), dur: 24}],
      spots: [{at: s2, box: box(id, 'where')}, {at: s3 + 8, box: box(id, 'said')}, {at: s4, box: box(id, 'reply')}, {at: proof, box: box(id, 'proof')}],
      where: {text: 'Live · PayPal sandbox', sub: 'Second Look on a one-person test shop', live: true}, labelIn: true, labelOut: true},
  ];
  return <Scene from={from} to={to}><Shots shots={shots} /></Scene>;
};

// ---------- 10. Can I trust it? ----------
const Trust: React.FC = () => {
  const frame = useCurrentFrame();
  const from = beat('s10a').from, to = beat('s10b').next;
  const [t1, t2, t3] = sentenceStarts('s10a');
  const end = beat('s10b').from - 6;
  // Laid out at 1/1.2 and scaled up as a group: draft 2's boxes, at a size that reads at 1080p.
  const Y = 420, H = 240, W = 320, GAP = 80, X0 = (WIDTH - (4 * W + 3 * GAP)) / 2;
  const x = (i: number) => X0 + i * (W + GAP);
  const flow = 1 - fadeIn(frame, end, 12);
  const card = fadeIn(frame, end + 6, 14);
  const [, n] = sentenceStarts('s10b');
  return (
    <Scene from={from} to={to}>
      {flow > 0 ? (
        <AbsoluteFill style={{opacity: flow, transform: 'scale(1.2)', transformOrigin: '50% 45%'}}>
          <FlowBox x={x(0)} y={Y} w={W} h={H} on={t1} title="The AI recommends">An answer and a drafted reply.</FlowBox>
          <Arrow x1={x(0) + W + 8} y1={Y + H / 2} x2={x(1) - 8} y2={Y + H / 2} on={t2 - 4} />
          <FlowBox x={x(1)} y={Y} w={W} h={H} on={t2} title="Your limits, in code" tone={theme.kraft}>They have the last word.</FlowBox>
          <Arrow x1={x(1) + W + 8} y1={Y + H / 2} x2={x(2) - 8} y2={Y + H / 2} on={t3 - 4} />
          <FlowBox x={x(2)} y={Y} w={W} h={H} on={t3} title="You approve" tone={theme.pass}>Nothing is sent before.</FlowBox>
          <Arrow x1={x(2) + W + 8} y1={Y + H / 2} x2={x(3) - 8} y2={Y + H / 2} on={t3 + 10} />
          <FlowBox x={x(3)} y={Y} w={W} h={H} on={t3 + 14} title="PayPal">Evidence, reply or refund.</FlowBox>
        </AbsoluteFill>
      ) : null}
      {card > 0 ? (
        <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', opacity: card, textAlign: 'center'}}>
          <Backdrop src="footage/seller daylight.mp4" video from={end} to={to} startAt={1} blur={9} veil="rgba(30,41,53,0.70)" />
          <div style={{font: `700 120px/1 ${theme.sans}`, color: theme.paper, letterSpacing: -3, position: 'relative'}}>Second Look</div>
          <div style={{font: `400 56px/1.2 ${theme.serif}`, color: '#D9B27F', marginTop: 22, opacity: fadeIn(frame, n - 4, 12), position: 'relative'}}>Sell without fear.</div>
          <div style={{font: `400 34px/1.6 ${theme.sans}`, color: '#E3E7EA', marginTop: 70, opacity: fadeIn(frame, n + 14, 14), position: 'relative'}}>
            claudiaonclaude.com<br />github.com/sciarada75/second-look
          </div>
        </AbsoluteFill>
      ) : null}
    </Scene>
  );
};

// ---------- signature ----------
// "ClaudiaOnClaude", as on the footers of Claudia's client sites: thin (Inter 300, loaded for this
// only), widely spaced, faint, centred at the bottom of every screen but the end card (which carries
// claudiaonclaude.com). Paper on the dark scenes, ink elsewhere; over the app captures a very soft
// paper gradient at the bottom keeps it clear of busy page text, with nothing boxed.
const inter = loadInter('normal', {weights: ['300'], subsets: ['latin']});
const Signature: React.FC = () => {
  const frame = useCurrentFrame();
  const endCard = beat('s10b').from - 6;
  if (frame >= endCard) return null;
  const dark = frame < beat('s2h').from; // scenes 1, 2 and 2b
  const app = frame >= beat('s4a').from && frame < beat('s10a').from;
  const o = Math.min(fadeIn(frame, 0, 12), 1 - fadeIn(frame, endCard - 10, 10));
  return (
    <>
      {app ? <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 60, opacity: o,
        background: 'linear-gradient(to bottom, rgba(245,246,242,0), rgba(245,246,242,0.15))'}} /> : null}
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 28, textAlign: 'center', opacity: 0.45 * o,
        font: `300 18px ${inter.fontFamily}, ${theme.sans}`, letterSpacing: '0.15em', color: dark ? theme.paper : theme.ink}}>
        ClaudiaOnClaude
      </div>
    </>
  );
};

export const Scenes3: React.FC = () => (
  <>
    <Moment /><Costs /><Business /><Enter /><Team /><Helpdesk /><TheCase /><Approve /><OverLimit /><Giulia /><Live /><Trust />
    <Signature />
  </>
);
void HEIGHT;
