import React from 'react';
import {AbsoluteFill, interpolate, Sequence, useCurrentFrame} from 'remotion';
import {Footage, Picture, Shots, ShotSpec, fade} from './Pieces';
import {Pages, PageShot} from './Page';
import {Arrow, Box} from './Scenes';
import {beat, sentenceStarts, span} from './timeline';
import {sec, theme} from './theme';
import api from './api-sample.json';

const Scene: React.FC<{from: number; to: number; children: React.ReactNode; bg?: string}> = ({from, to, children, bg}) => {
  const frame = useCurrentFrame();
  if (frame < from || frame >= to) return null;
  const o = interpolate(frame, [from, from + 8], [0, 1], {extrapolateRight: 'clamp'});
  return <Picture bg={bg}><AbsoluteFill style={{opacity: o}}>{children}</AbsoluteFill></Picture>;
};
const at = (key: string, f: number) => {
  const b = beat(key);
  return b.from + Math.round((b.to - b.from) * f);
};

// ---------- 1. the moment ----------
export const Moment: React.FC = () => {
  const frame = useCurrentFrame();
  const {from, to} = span('s1a', 's1b');
  const [, q] = sentenceStarts('s1a');
  const text = '“Never got my parcel.”';
  const shown = Math.round(interpolate(frame, [q - 2, beat('s1a').to], [0, text.length], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}));
  return (
    <Scene from={from} to={to}>
      <Sequence from={from} durationInFrames={to - from}><Footage file="parcel at night.mp4" rate={0.9} dim={0.35} /></Sequence>
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', opacity: fade(frame, q - 4, to, 6, 10)}}>
        <div style={{font: `400 100px/1.15 ${theme.serif}`, color: theme.paper, textShadow: '0 2px 30px rgba(0,0,0,0.85)'}}>
          {text.slice(0, shown)}<span style={{opacity: 0}}>{text.slice(shown)}</span>
        </div>
      </AbsoluteFill>
    </Scene>
  );
};

// ---------- 2. what each way out costs ----------
export const Costs: React.FC = () => {
  const frame = useCurrentFrame();
  const {from, to} = span('s2a', 's2c');
  const cards = [
    {on: beat('s2a').from, title: 'Refund now', big: 'Item, postage, PayPal’s fee', sub: 'The money goes back. PayPal keeps its fee on the payment.', tone: theme.incon},
    {on: beat('s2b').from, title: 'Settle it in the dispute', big: '0 EUR', sub: 'No PayPal dispute fee while it stays a dispute.', tone: theme.pass},
    {on: beat('s2c').from, title: 'It becomes a claim, and you lose', big: '+14 EUR', sub: '28 EUR for a high-volume shop, even when it wins.', tone: theme.fail},
  ];
  return (
    <Scene from={from} to={to} bg={theme.paper}>
      <div style={{position: 'absolute', left: 120, top: 90, font: `700 54px ${theme.sans}`, color: theme.ink}}>What each way out costs</div>
      <div style={{position: 'absolute', left: 120, right: 120, top: 230, display: 'flex', gap: 40}}>
        {cards.map((c) => {
          const o = interpolate(frame, [c.on, c.on + 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          return (
            <div key={c.title} style={{flex: 1, opacity: o, transform: `translateY(${(1 - o) * 20}px)`, background: '#fff',
              border: `2px solid ${theme.rule}`, borderTop: `10px solid ${c.tone}`, padding: '36px 36px 40px', minHeight: 470}}>
              <div style={{font: `700 36px/1.2 ${theme.sans}`, color: theme.ink}}>{c.title}</div>
              <div style={{font: `700 60px/1.1 ${theme.sans}`, color: c.tone, margin: '40px 0 26px'}}>{c.big}</div>
              <div style={{font: `400 30px/1.35 ${theme.sans}`, color: theme.soft}}>{c.sub}</div>
            </div>
          );
        })}
      </div>
      <div style={{position: 'absolute', left: 120, bottom: 50, font: `400 24px ${theme.sans}`, color: theme.soft}}>
        PayPal’s fee pages and User Agreement, September–October 2026. EUR figures.
      </div>
    </Scene>
  );
};

// ---------- 3. how it's handled today ----------
export const Today: React.FC = () => {
  const frame = useCurrentFrame();
  const {from, to} = span('s3a', 's3b');
  const b = beat('s3b').from;
  const o = fade(frame, b - 4, to + 20, 10, 1);
  return (
    <Scene from={from} to={to}>
      <Sequence from={from} durationInFrames={to - from}><Footage file="late night answer.mp4" startAt={1} dim={0.3} /></Sequence>
      <div style={{position: 'absolute', right: 110, bottom: 110, width: 760, opacity: o, background: theme.paper, padding: '34px 40px',
        borderLeft: `8px solid ${theme.kraft}`, color: theme.ink}}>
        <div style={{font: `700 34px/1.25 ${theme.sans}`}}>The tools that exist are built for card chargebacks.</div>
        <div style={{font: `400 30px/1.35 ${theme.sans}`, color: theme.soft, marginTop: 14}}>Many take 25% of what they win back.</div>
      </div>
    </Scene>
  );
};

// ---------- 4. Second Look ----------
const D31 = '/d/DEMO-031';
export const Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const {from, to} = span('s4a', 's4c');
  const a = beat('s4a'), b = beat('s4b'), c = beat('s4c');
  const title = from + sec(2.6);
  const shots: PageShot[] = [
    {from: title, to: at('s4a', 0.45), url: D31, cam: {x: 0, y: 60, z: 1.25}},                                   // the case
    {from: at('s4a', 0.45), to: at('s4a', 0.75), url: D31, cam: {x: 30, y: 880, z: 1.5}, pan: {x: 30, y: 1180, z: 1.5}}, // evidence, with sources
    {from: at('s4a', 0.75), to: b.from, url: D31, cam: {x: 760, y: 720, z: 1.55}},                               // what each way out costs
    {from: b.from, to: c.from, url: D31, cam: {x: 760, y: 360, z: 1.55}, pan: {x: 760, y: 420, z: 1.6}},          // the reply, specific to this buyer
    {from: c.from, to, url: D31, cam: {x: 30, y: 440, z: 1.6}},                                                   // what's been said
  ];
  void a;
  return (
    <Scene from={from} to={to}>
      <Pages shots={shots} />
      {frame < title + 8 ? (
        <AbsoluteFill style={{background: theme.paper, alignItems: 'center', justifyContent: 'center', opacity: interpolate(frame, [title, title + 8], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>
          <div style={{font: `700 140px/1 ${theme.sans}`, color: theme.ink, letterSpacing: -3}}>Second Look</div>
          <div style={{font: `400 72px/1.2 ${theme.serif}`, color: theme.kraft, marginTop: 20}}>Sell without fear.</div>
        </AbsoluteFill>
      ) : null}
    </Scene>
  );
};

// ---------- 5. live on PayPal's sandbox (draft-1 recordings) ----------
const A1 = 'A-tote-reply';
const A2 = 'A-tote-defend';
const A_TIMELINE = {x: 0, y: 470, w: 860};
const RIGHT = (y: number) => ({x: 858, y, w: 812});
export const Live: React.FC = () => {
  const {from, to} = span('s5a', 's5b');
  const a = beat('s5a'), b = beat('s5b');
  const [, a2] = sentenceStarts('s5a');
  const shots: ShotSpec[] = [
    {from: a.from, to: a2, file: A1, at: 4.2, region: {x: 13, y: 168, w: 1683}},
    {from: a2, to: at('s5a', 0.7), file: A1, at: 56, region: A_TIMELINE},
    {from: at('s5a', 0.7), to: b.from, file: A1, at: 63.6, region: RIGHT(520)},
    {from: b.from, to: at('s5b', 0.4), file: A2, at: 5, region: RIGHT(640)},
    {from: at('s5b', 0.4), to: at('s5b', 0.8), file: A2, at: 68.5, region: RIGHT(390), label: '40 seconds later'},
    {from: at('s5b', 0.8), to, file: A2, at: 101, region: RIGHT(172)},
  ];
  return (
    <Scene from={from} to={to}>
      <Shots shots={shots} />
      <div style={{position: 'absolute', right: 40, bottom: 28, background: theme.pass, color: '#fff', font: `700 30px ${theme.sans}`, padding: '10px 18px'}}>
        Live: PayPal sandbox
      </div>
    </Scene>
  );
};

// ---------- 6. a busier shop (the demo shop, live pages) ----------
export const Busier: React.FC = () => {
  const {from, to} = span('s6a', 's6e');
  const [, , d2] = sentenceStarts('s6d'); // "A parcel stuck for two weeks"
  const shots: PageShot[] = [
    {from: beat('s6a').from, to: beat('s6b').from, url: '/?shop=demo', cam: {x: 0, y: 70, z: 1.25}, pan: {x: 0, y: 200, z: 1.25}},
    {from: beat('s6b').from, to: at('s6b', 0.5), url: D31, cam: {x: 30, y: 1290, z: 1.6}},                       // this buyer's record
    {from: at('s6b', 0.5), to: beat('s6c').from, url: D31, cam: {x: 760, y: 80, z: 1.55}},                       // defend with evidence
    {from: beat('s6c').from, to: at('s6c', 0.55), url: '/d/DEMO-034', cam: {x: 760, y: 80, z: 1.5}},             // your call: the buyer is right
    {from: at('s6c', 0.55), to: beat('s6d').from, url: '/d/DEMO-034', cam: {x: 760, y: 300, z: 1.5}},            // your limit stopped the refund
    {from: beat('s6d').from, to: d2, url: '/d/DEMO-033', cam: {x: 760, y: 400, z: 1.6}},                         // the napkin: a photo first
    {from: d2, to: beat('s6e').from, url: '/d/DEMO-039', cam: {x: 760, y: 80, z: 1.6}},                          // stuck parcel: refund
    {from: beat('s6e').from, to, url: '/overview?shop=demo', cam: {x: 30, y: 330, z: 1.3}, pan: {x: 30, y: 1040, z: 1.3}},
  ];
  return (
    <Scene from={from} to={to}>
      <Pages shots={shots} />
      <div style={{position: 'absolute', right: 40, bottom: 28, background: theme.kraft, color: '#fff', font: `700 30px ${theme.sans}`, padding: '10px 18px'}}>
        Demo shop: made-up data
      </div>
    </Scene>
  );
};

// ---------- 6f–g. connects both ways ----------
const Code: React.FC<{title: string; sub: string; text: string; on: number}> = ({title, sub, text, on}) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [on, on + 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div style={{flex: 1, opacity: o, transform: `translateY(${(1 - o) * 16}px)`}}>
      <div style={{font: `700 34px ${theme.sans}`, color: theme.ink}}>{title}</div>
      <div style={{font: `400 26px ${theme.sans}`, color: theme.soft, margin: '6px 0 16px'}}>{sub}</div>
      <pre style={{margin: 0, background: theme.ink, color: '#E8ECEF', font: `400 23px/1.45 ui-monospace, Menlo, monospace`,
        padding: '24px 28px', whiteSpace: 'pre-wrap', minHeight: 430}}>{text}</pre>
    </div>
  );
};
export const Connect: React.FC = () => {
  const frame = useCurrentFrame();
  const {from, to} = span('s6f', 's6g');
  const g = beat('s6g').from;
  const [, , f3] = sentenceStarts('s6f');
  const [, g2] = sentenceStarts('s6g');
  const tools = ['Helpdesk', 'Team chat', 'CRM', 'Your shop'];
  const diagram = frame < g;
  const req = `GET /api/disputes/DEMO-031\n\n${JSON.stringify(api, null, 1)}`;
  const event = `POST  your address\n\n{\n "event": "answer.sent",\n "dispute_id": "PP-D-001",\n "action": "DEFEND",\n "what_happened": "Evidence submitted\n   and reply sent."\n}`;
  return (
    <Scene from={from} to={to} bg={theme.paper}>
      {diagram ? (
        <>
          <Box x={110} y={300} w={460} h={240} on={from} title="Second Look" tone={theme.kraft}>Its own screen: disputes, overview, your rules.</Box>
          {tools.map((t, i) => (
            <React.Fragment key={t}>
              <Arrow x1={580} y1={380} x2={1180} y2={150 + i * 170} on={f3 + i * 4} color={theme.pass} />
              <Arrow x1={1180} y1={190 + i * 170} x2={580} y2={460} on={f3 + 10 + i * 4} color={theme.ink} />
              <Box x={1190} y={110 + i * 170} w={560} h={120} on={from + 20 + i * 8} title={t} />
            </React.Fragment>
          ))}
        </>
      ) : (
        <div style={{position: 'absolute', left: 110, right: 110, top: 70, display: 'flex', gap: 60}}>
          <Code on={g} title="Your systems → Second Look" sub="Read a case, ask for a review, approve: same limits as the screen." text={req} />
          <Code on={g2} title="Second Look → your systems" sub="An event when an answer has gone out (from a test run)." text={event} />
        </div>
      )}
    </Scene>
  );
};

// ---------- 7. the guard and you ----------
export const Guard: React.FC = () => {
  const {from, to} = span('s7a', 's7a');
  const [s1, s2, s3] = sentenceStarts('s7a');
  const Y = 290, H = 260;
  return (
    <Scene from={from} to={to} bg={theme.paper}>
      <Box x={80} y={Y} w={380} h={H} on={from} title="The AI’s answer">Ten checks, one recommendation, a drafted reply.</Box>
      <Arrow x1={465} y1={Y + H / 2} x2={535} y2={Y + H / 2} on={s1 + 6} />
      <Box x={540} y={Y} w={420} h={H} on={s1 + 8} title="Your limits, in code" tone={theme.kraft}>Caps, confidence, PayPal’s allowed steps, hidden orders.</Box>
      <Arrow x1={965} y1={Y + H / 2} x2={1035} y2={Y + H / 2} on={s2} />
      <Box x={1040} y={Y} w={380} h={H} on={s2 + 2} title="You approve" tone={theme.pass}>The exact answer you saw. Once.</Box>
      <Arrow x1={1425} y1={Y + H / 2} x2={1495} y2={Y + H / 2} on={s3} />
      <Box x={1500} y={Y} w={340} h={H} on={s3 + 2} title="PayPal">Evidence, reply, or refund.</Box>
    </Scene>
  );
};

// ---------- 8. end ----------
export const End2: React.FC = () => {
  const frame = useCurrentFrame();
  const {from, to} = span('s8a', 's8a');
  const [, n] = sentenceStarts('s8a');
  return (
    <Scene from={from} to={to}>
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', color: theme.paper}}>
        <div style={{font: `700 140px/1 ${theme.sans}`, letterSpacing: -3}}>Second Look</div>
        <div style={{font: `400 78px/1.2 ${theme.serif}`, color: theme.kraft, marginTop: 24, opacity: fade(frame, n, to + 60, 10, 1)}}>Sell without fear.</div>
        <div style={{font: `400 32px/1.6 ${theme.sans}`, color: '#AEB6BF', marginTop: 70, textAlign: 'center', opacity: fade(frame, n + 10, to + 60, 10, 1)}}>
          claudiaonclaude.com<br />github.com/sciarada75/second-look
        </div>
      </AbsoluteFill>
    </Scene>
  );
};
