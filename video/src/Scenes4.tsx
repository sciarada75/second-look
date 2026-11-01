// Draft 10 (script-v4.md): every channel, one morning. Eleven scenes, each answering one question; the
// screen shows only what the voice names. The flowchart of scene 3 is the film's map: from the morning on,
// a small copy rides in the "where you are" chip and lights the step each shot is in (Stage.WhereLabel).
// App scenes are built on the captured walk (capture.mjs, Stage.tsx); the helpers come from draft 9.
import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {Arrow} from './Scenes';
import {at, Backdrop, clamp, CUT, fadeIn, grow, MARK, rightCol, Scene, Shots, ShotSpec} from './Scenes3';
import {beat, sentenceStarts} from './timeline';
import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import {HEIGHT, WIDTH, theme} from './theme';
import {box, Box, Cam, camOn, camTop, union} from './Stage';

// ---------- 1. What happens? Every channel, one morning ----------
// Each card quotes the customer's own words, as the demo has them.
const PhoneIcon: React.FC<{c: string}> = ({c}) => (
  <svg width={30} height={30} viewBox="0 0 24 24"><path fill={c} d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1z" /></svg>
);
const MailIcon: React.FC<{c: string}> = ({c}) => (
  <svg width={30} height={30} viewBox="0 0 24 24"><path fill="none" stroke={c} strokeWidth={2} d="M3 5h18v14H3z M3 6l9 7 9-7" /></svg>
);
const CHANNELS = [
  {icon: 'phone', channel: 'Phone call', name: 'Sophie', quote: '“I ordered a linen tablecloth. And it still hasn’t arrived.”', tone: theme.kraft},
  {icon: 'mail', channel: 'Email', name: 'Pablo', quote: '“I sent the shirt back on 5 October. I still have no refund.”', tone: theme.kraft},
  {icon: 'paypal', channel: 'PayPal dispute · 58.00 EUR', name: 'Dario', quote: '“Never received the apron. Refund me or I go to PayPal.”', tone: theme.fail},
];
const Channels: React.FC = () => {
  const frame = useCurrentFrame();
  const from = beat('s1a').from, to = beat('s1b').next;
  const ons = sentenceStarts('s1a');
  const W = 540, GAP = 36, X0 = (WIDTH - (3 * W + 2 * GAP)) / 2;
  return (
    <Scene from={from} to={to} under={theme.ink}>
      <Backdrop src="footage/web/shipping 3.jpg" from={from} to={to} blur={16} />
      {CHANNELS.map((c, i) => {
        const o = fadeIn(frame, ons[i], 12);
        return (
          <div key={c.name} style={{position: 'absolute', left: X0 + i * (W + GAP), top: 300, width: W, minHeight: 360, opacity: o,
            transform: `translateY(${(1 - o) * 18}px)`, background: '#fff', borderTop: `8px solid ${c.tone}`, padding: '30px 34px',
            boxSizing: 'border-box', boxShadow: '0 24px 70px rgba(0,0,0,0.35)'}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 12, font: `500 26px ${theme.sans}`, color: theme.soft}}>
              {c.icon === 'phone' ? <PhoneIcon c={theme.soft} /> : c.icon === 'mail' ? <MailIcon c={theme.soft} /> : null}
              <span style={c.icon === 'paypal' ? {background: theme.kraftBg, color: '#6E4F27', borderLeft: `5px solid ${theme.kraft}`, padding: '4px 12px'} : {}}>{c.channel}</span>
            </div>
            <div style={{font: `700 40px ${theme.sans}`, color: theme.ink, marginTop: 22}}>
              {c.name}<span style={{font: `400 32px ${theme.serif}`, color: theme.soft}}>, customer</span>
            </div>
            <div style={{font: `400 40px/1.3 ${theme.serif}`, color: theme.ink, marginTop: 14}}>{c.quote}</div>
          </div>
        );
      })}
    </Scene>
  );
};

// ---------- 2. What does it cost? Four tiles, each with its source ----------
// Draft 9's tiles, four in a row; the first is PayPal's fee ladder, a step lit as the voice names it.
const T_W = 404, T_GAP = 30, T_H = 440, T_TITLE = 132, T_ROW = 48, T_SRC = 76;
const T_TOP = Math.round((HEIGHT - (T_TITLE + T_ROW + T_H + T_SRC)) / 2) - 20;
const Costs: React.FC = () => {
  const frame = useCurrentFrame();
  const from = beat('s2a').from, to = beat('s2d').next;
  const steps = sentenceStarts('s2a');
  const ons = [steps[0], beat('s2b').from, beat('s2c').from, beat('s2d').from];
  const lit = ons.filter((o) => frame >= o).length - 1;
  const rowW = 4 * T_W + 3 * T_GAP;
  const ladder = [
    {big: '0 EUR', sub: 'answered early', tone: theme.pass},
    {big: '14 EUR', sub: 'lost as a claim', tone: theme.fail},
    {big: '28 EUR', sub: 'busy shop, even when it wins', tone: theme.fail},
  ];
  const tiles = [
    {src: 'PayPal fees, 7 Sep 2026 · PayPal User Agreement, 14 Sep 2026', tone: theme.ink},
    {prefix: 'US$', big: '8.01', sub: 'per live customer-care contact', tone: theme.ink, src: 'Gartner, 2019'},
    {prefix: 'US$', big: '4.61', sub: 'lost for every US$1 of fraud', tone: theme.fail, src: 'LexisNexis True Cost of Fraud, 2025 · US retail & e-commerce'},
    {big: '46%', sub: 'of card chargebacks accepted without a fight', tone: theme.incon, src: 'Mastercard / Datos 2025 · midsize & large merchants'},
  ];
  const t0 = fadeIn(frame, from, 12);
  return (
    <Scene from={from} to={to} under={theme.ink}>
      <Backdrop src="footage/money flow.mp4" video from={from} to={to} rate={0.85} />
      <div style={{position: 'absolute', left: 0, right: 0, top: T_TOP, height: T_TITLE, textAlign: 'center', opacity: t0,
        transform: `translateY(${(1 - t0) * 12}px)`, textShadow: '0 2px 18px rgba(0,0,0,0.45)'}}>
        <div style={{font: `700 60px/1.15 ${theme.sans}`, color: theme.paper, letterSpacing: -1}}>What a customer’s problem costs</div>
        <div style={{font: `400 32px/1.3 ${theme.sans}`, color: '#D3D9DE', marginTop: 12}}>public figures, each with its source</div>
      </div>
      {tiles.map((t, i) => {
        const o = fadeIn(frame, ons[i], 12);
        if (o <= 0) return null;
        // the tile being named is lit; the ones before it dim slightly, and stay
        const dim = i < lit ? interpolate(frame, [ons[lit], ons[lit] + 10], [1, 0.62], clamp) : 1;
        const ring = i === lit ? fadeIn(frame, ons[i], 10) : i === lit - 1 ? 1 - fadeIn(frame, ons[lit], 10) : 0;
        return (
          <div key={i} style={{position: 'absolute', left: (WIDTH - rowW) / 2 + i * (T_W + T_GAP), top: T_TOP + T_TITLE + T_ROW,
            width: T_W, opacity: o * dim, transform: `translateY(${(1 - o) * 20}px)`}}>
            <div style={{height: T_H, background: '#fff', borderTop: `10px solid ${t.tone}`, padding: '26px 30px', boxSizing: 'border-box',
              boxShadow: `0 20px 60px rgba(0,0,0,0.35), 0 0 0 ${4 * ring}px ${theme.kraft}`}}>
              {i === 0 ? (
                <>
                  <div style={{font: `500 30px/1.2 ${theme.sans}`, color: theme.soft}}>PayPal dispute fee</div>
                  {ladder.map((l, j) => (
                    <div key={j} style={{opacity: fadeIn(frame, steps[j], 10), marginTop: 18}}>
                      <div style={{font: `700 58px/1 ${theme.sans}`, color: l.tone, letterSpacing: -2}}>{l.big}</div>
                      <div style={{font: `500 24px/1.25 ${theme.sans}`, color: theme.ink, marginTop: 4}}>{l.sub}</div>
                    </div>
                  ))}
                </>
              ) : (
                <>
                  <div style={{font: `700 112px/1.05 ${theme.sans}`, color: t.tone, letterSpacing: -4, whiteSpace: 'nowrap', marginTop: 30}}>
                    {t.prefix ? <span style={{fontSize: 56, letterSpacing: -1, marginRight: 4}}>{t.prefix}</span> : null}{t.big}
                  </div>
                  <div style={{font: `500 32px/1.25 ${theme.sans}`, color: theme.ink, marginTop: 18}}>{t.sub}</div>
                </>
              )}
            </div>
            <div style={{font: `400 23px/1.35 ${theme.sans}`, color: '#E3E7EA', marginTop: 14, textShadow: '0 1px 8px rgba(0,0,0,0.6)'}}>{t.src}</div>
          </div>
        );
      })}
    </Scene>
  );
};

// ---------- 3. So what helps? Second Look, and the flowchart (the film's map) ----------
const FlowCard: React.FC<{x: number; w: number; on: number; title: string; tone?: string; children?: React.ReactNode}> = ({x, w, on, title, tone = theme.ink, children}) => {
  const frame = useCurrentFrame();
  const o = fadeIn(frame, on, 12);
  return (
    <div style={{position: 'absolute', left: x, top: FLOW_Y, width: w, height: FLOW_H, opacity: o, background: '#fff',
      border: `2px solid ${theme.rule}`, borderTop: `10px solid ${tone}`, padding: '26px 28px', boxSizing: 'border-box',
      transform: `translateY(${(1 - o) * 16}px)`}}>
      <div style={{font: `700 40px/1.15 ${theme.sans}`, color: theme.ink}}>{title}</div>
      <div style={{marginTop: 16}}>{children}</div>
    </div>
  );
};
const Item: React.FC<{on: number; strong?: boolean; children: React.ReactNode}> = ({on, strong, children}) => {
  const frame = useCurrentFrame();
  const o = fadeIn(frame, on, 10);
  return (
    <div style={{opacity: o, transform: `translateY(${(1 - o) * 8}px)`, font: `${strong ? 700 : 400} 28px/1.3 ${theme.sans}`,
      color: strong ? '#6E4F27' : theme.ink, padding: '8px 0', borderTop: `1px solid ${theme.rule}`}}>{children}</div>
  );
};
const FLOW_Y = 360, FLOW_H = 470;
const FLOW_W = [360, 560, 340, 380], FLOW_GAP = 70;
const FLOW_X = (() => {
  let x = (WIDTH - (FLOW_W.reduce((a, b) => a + b, 0) + 3 * FLOW_GAP)) / 2;
  return FLOW_W.map((w) => { const at0 = x; x += w + FLOW_GAP; return at0; });
})();
const Flow: React.FC = () => {
  const frame = useCurrentFrame();
  const from = beat('s3a').from, to = beat('s3c').next;
  const [, a2] = sentenceStarts('s3a');
  const [b1, b2, b3] = sentenceStarts('s3b');
  const c1 = beat('s3c').from, c2 = at('s3c', 0.3); // "and everything is updated"
  const head = fadeIn(frame, from + 2, 14);
  const ons = [a2, b1, c1, c2];
  const mid = FLOW_Y + FLOW_H / 2;
  return (
    <Scene from={from} to={to}>
      <div style={{position: 'absolute', left: 0, right: 0, top: 150, display: 'flex', alignItems: 'center', justifyContent: 'center',
        gap: 26, opacity: head, transform: `translateY(${(1 - head) * 14}px)`}}>
        {MARK(80)}
        <div style={{font: `700 96px/1 ${theme.sans}`, color: theme.ink, letterSpacing: -3}}>Second Look</div>
      </div>
      <FlowCard x={FLOW_X[0]} w={FLOW_W[0]} on={a2} title="Every request">
        {['Phone call', 'Email', 'Web form', 'PayPal dispute'].map((t, i) => <Item key={t} on={a2 + 6 + 5 * i}>{t}</Item>)}
      </FlowCard>
      <FlowCard x={FLOW_X[1]} w={FLOW_W[1]} on={b1} title="Second Look" tone={theme.kraft}>
        <Item on={b1 + 4}>Finds its order</Item>
        <Item on={b2}>Second Look’s AI checks the evidence and drafts the answer</Item>
        <Item on={b3} strong>Your limits, in code, have the last word</Item>
      </FlowCard>
      <FlowCard x={FLOW_X[2]} w={FLOW_W[2]} on={c1} title="A person approves" tone={theme.pass}>
        <Item on={c1 + 6}>within their own limit</Item>
      </FlowCard>
      <FlowCard x={FLOW_X[3]} w={FLOW_W[3]} on={c2} title="Everything updated">
        {['The reply', 'PayPal', 'The helpdesk', 'The accounts'].map((t, i) => <Item key={t} on={c2 + 8 + 6 * i}>{t}</Item>)}
      </FlowCard>
      {[0, 1, 2].map((i) => (
        <Arrow key={i} x1={FLOW_X[i] + FLOW_W[i] + 8} y1={mid} x2={FLOW_X[i + 1] - 8} y2={mid} on={ons[i + 1] - 8} />
      ))}
    </Scene>
  );
};

// ---------- 4. Who are we following? ----------
const PEOPLE = [
  {name: 'Marta', initials: 'M', role: 'Customer care assistant', note: 'refunds up to 30 EUR', color: theme.kraft},
  {name: 'Giulia', initials: 'G', role: 'Head of customer care', note: 'decides above that', color: theme.ink},
  {name: 'Luca', initials: 'L', role: 'Customer care assistant', note: '', color: theme.soft},
  {name: 'Sara', initials: 'S', role: 'Customer care assistant', note: '', color: theme.soft},
];
const Team: React.FC = () => {
  const frame = useCurrentFrame();
  const from = beat('s4a').from, to = beat('s4b').next;
  const [m, g] = sentenceStarts('s4b');
  const ons = [m, g, m + 30, m + 30];
  const card = fadeIn(frame, from, 12);
  return (
    <Scene from={from} to={to}>
      {/* the shop itself: a light paper veil, so the ink type reads as on the product's own pages */}
      <Backdrop src="footage/web/linen and paper store.jpg" from={from} to={to} blur={5} veil="rgba(245,246,242,0.80)" />
      <div style={{position: 'absolute', left: 0, right: 0, top: 150, textAlign: 'center', opacity: card}}>
        <div style={{font: `700 92px/1.1 ${theme.sans}`, color: theme.ink, letterSpacing: -2}}>Linen &amp; Paper</div>
        <div style={{font: `500 40px ${theme.sans}`, color: theme.ink, opacity: 0.8, marginTop: 18}}>a made-up shop · about 2,000 orders a month</div>
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: 500, display: 'flex', justifyContent: 'center', gap: 70}}>
        {PEOPLE.map((p, i) => {
          const full = i < 2 ? 1 : 0.45;
          const o = fadeIn(frame, ons[i], 12) * full;
          return (
            <div key={p.name} style={{width: 340, textAlign: 'center', opacity: o, transform: `translateY(${(1 - o / full) * 16}px)`}}>
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

// ---------- the app scenes ----------
// Every camera sits a little high: the bottom of the frame is the subtitles' and the chip's, so what the
// voice names is framed above them.
const LIFT = 140;
const lift = (c: Cam): Cam => ({...c, y: c.y + LIFT / c.z});
const camUp = (b: Box, z: number) => lift(camOn(b, z));
const rightUp = (b: Box, z?: number) => lift(rightCol(b, z));
const DEMO = 'demo shop, made-up data';
const GIULIA = {sub: `Giulia, head of customer care · ${DEMO}`};
const MARTA = {sub: `Marta, customer care assistant · ${DEMO}`};
const MARTA_TB = {sub: 'Marta · Ticketbook, a made-up helpdesk'};
// The map's steps (Stage.MAP): 0 request, 1 Second Look, 2 a person approves, 3 everything updated.

// ---------- 5. What came in this morning? ----------
const Morning: React.FC = () => {
  const from = beat('s5a').from;
  const [, a2] = sentenceStarts('s5a');
  const orders = at('s5a', 0.8);                   // "beside the day's orders"
  const [, b2] = sentenceStarts('s5b');            // "And who has what."
  const [c1, c2, c3] = sentenceStarts('s5c');
  const back = at('s5c', 0.79);                    // "and steps back when it isn't sure"
  const clickRules = c2 - 4, cut = clickRules + CUT;
  const id = 'today';
  const top = union(box(id, 'orders'), box(id, 'chips'));
  const shots: ShotSpec[] = [
    {id, from, to: cut,
      cams: [{at: from, cam: camTop()}, {at: a2 - 4, cam: camUp(top, 1.45), dur: 26},
        {at: beat('s5b').from, cam: camUp(box(id, 'list'), 1.2), dur: 28}, {at: b2 - 4, cam: camUp(box(id, 'team'), 1.5), dur: 26},
        {at: c1 - 10, cam: camTop(), dur: 24}],
      spots: [{at: from + 10, box: box(id, 'hello')}, {at: a2 + 6, box: box(id, 'chips')}, {at: orders, box: box(id, 'orders')},
        {at: beat('s5b').from + 10, box: box(id, 'list')}, {at: b2 + 6, box: box(id, 'team')}, {at: c1 + 8, box: box(id, 'ai-check')}],
      cursor: [{at: c1 + 10, pos: {x: 1300, y: 640}}, {at: clickRules, box: box(id, 'rules-nav'), click: true, move: 18}],
      where: {text: 'Second Look › Today', ...GIULIA, map: [1]}, labelIn: true},
    {id: 'rules', from: cut, to: beat('s5c').next,
      cams: [{at: cut, cam: camUp(box('rules', 'own'), 1.45)}],
      spots: [{at: cut + 2, box: box('rules', 'kind')}, {at: c3, box: box('rules', 'intro')}, {at: back, box: box('rules', 'sure')}],
      where: {text: 'Second Look › Your rules', ...GIULIA, map: [1]}, labelOut: true},
  ];
  return <Scene from={from} to={beat('s5c').next}><Shots shots={shots} /></Scene>;
};

// ---------- 6. A phone call: Sophie's case ----------
const Call: React.FC = () => {
  const from = beat('s6a').from, to = beat('s6b').next;
  const [a1, , , a4] = sentenceStarts('s6a');
  const email = at('s6a', 0.78);                   // "and her email joins it"
  const [, b2] = sentenceStarts('s6b');            // "Marta sends the reply and closes the case"
  const clickSend = b2 + 14, cutSent = clickSend + CUT;
  const clickClose = at('s6b', 0.74), cutClosed = clickClose + CUT;
  const [id, sent, closed] = ['c001', 'c001-sent', 'c001-closed'];
  const left = union(box(id, 'came'), box(id, 'email'));
  const shots: ShotSpec[] = [
    {id, from, to: cutSent,
      cams: [{at: from, cam: camUp(left, 1.3)}, {at: beat('s6b').from - 6, cam: camUp(grow(box(id, 'tracked'), 30), 1.7), dur: 22},
        {at: b2 - 6, cam: rightUp(union(box(id, 'verdict'), box(id, 'approve')), 1.5), dur: 20}],
      spots: [{at: a1 + 6, box: box(id, 'call')}, {at: email, box: box(id, 'email')}, {at: a4, box: box(id, 'came')},
        {at: beat('s6b').from + 4, box: box(id, 'neighbour')}, {at: b2, box: box(id, 'approve')}],
      cursor: [{at: b2 - 4, pos: {x: 1500, y: 950}}, {at: clickSend, box: box(id, 'approve'), click: true, move: 14}],
      where: {text: 'Second Look › Case DEMO-C001', ...MARTA, map: [0, 1]}, labelIn: true},
    {id: sent, from: cutSent, to: cutClosed,
      cams: [{at: cutSent, cam: rightUp(union(box(sent, 'done'), box(sent, 'close')), 1.5)}],
      spots: [{at: cutSent + 2, box: box(sent, 'done')}, {at: clickClose - 12, box: box(sent, 'close')}],
      cursor: [{at: cutSent + 2, pos: {x: 1500, y: 900}}, {at: clickClose, box: box(sent, 'close-btn'), click: true, move: 12}],
      where: {text: 'Second Look › Case DEMO-C001', ...MARTA, map: [2]}},
    {id: closed, from: cutClosed, to,
      cams: [{at: cutClosed, cam: camUp(union(box(closed, 'closed-tag'), box(closed, 'came')), 1.7)}],
      spots: [{at: cutClosed + 2, box: box(closed, 'closed-tag')}],
      where: {text: 'Second Look › Case DEMO-C001', ...MARTA, map: [2]}, labelOut: true},
  ];
  return <Scene from={from} to={to}><Shots shots={shots} /></Scene>;
};

// ---------- 7. A PayPal dispute: Dario's case ----------
const Dispute: React.FC = () => {
  const from = beat('s7a').from, to = beat('s7c').next;
  const [, a2, a3] = sentenceStarts('s7a');        // "In Marta's helpdesk, Second Look's AI says:" "defend."
  const clickOpen = beat('s7a').to + 8, cutOpen = clickOpen + CUT;
  const four = at('s7b', 0.47);                    // "and he has disputed four of his five orders"
  const [, c2] = sentenceStarts('s7c');            // "Marta defends:"
  const clickDefend = c2 + 10, cutDone = clickDefend + CUT;
  const [tb, id, sent] = ['tb-2001', 'd031', 'd031-sent'];
  const shots: ShotSpec[] = [
    {id: tb, from, to: cutOpen,
      cams: [{at: from, cam: camTop()}, {at: a2 - 4, cam: camUp(box(tb, 'panel'), 1.45), dur: 26}],
      spots: [{at: from + 8, box: box(tb, 'email')}, {at: a2 + 4, box: box(tb, 'panel')}, {at: a3, box: box(tb, 'verdict')}],
      cursor: [{at: a3 + 4, box: box(tb, 'verdict'), ax: 0.8, ay: 1.8}, {at: clickOpen, box: box(tb, 'open-sl'), click: true, move: 16}],
      where: {text: 'Ticketbook › Ticket #2001', ...MARTA_TB, map: [1]}, labelIn: true},
    {id, from: cutOpen, to: cutDone,
      cams: [{at: cutOpen, cam: rightUp(box(id, 'paypal-address'), 1.9)}, {at: four - 6, cam: camUp(box(id, 'buyer'), 1.7), dur: 24},
        {at: beat('s7c').from - 4, cam: rightUp(union(box(id, 'approve'), box(id, 'costs')), 1.45), dur: 26}],
      spots: [{at: cutOpen + 2, box: box(id, 'paypal-address')}, {at: four + 4, box: box(id, 'buyer')},
        {at: beat('s7c').from + 10, box: box(id, 'costs')}, {at: c2 - 4, box: box(id, 'approve')}],
      cursor: [{at: c2 - 10, pos: {x: 1500, y: 980}}, {at: clickDefend, box: box(id, 'approve'), click: true, move: 14}],
      where: {text: 'Second Look › Case DEMO-031', ...MARTA, map: [1]}},
    {id: sent, from: cutDone, to,
      cams: [{at: cutDone, cam: rightUp(box(sent, 'done'), 1.8)}],
      spots: [{at: cutDone + 2, box: box(sent, 'done')}],
      where: {text: 'Second Look › Case DEMO-031', ...MARTA, map: [2]}, labelOut: true},
  ];
  return <Scene from={from} to={to}><Shots shots={shots} /></Scene>;
};

// ---------- 8. When the customer is right: Pablo's case ----------
const Right: React.FC = () => {
  const from = beat('s8a').from, to = beat('s8b').next;
  const opened = at('s8a', 0.45);                  // "then opened a PayPal dispute"
  const [, a2] = sentenceStarts('s8a');            // "Still one case."
  const [b1, , b3] = sentenceStarts('s8b');        // "He's right:" … "Eighty-nine euros is over Marta's limit"
  const clickPass = at('s8b', 0.74), cutGiulia = clickPass + CUT;  // "so Giulia"
  const clickApprove = beat('s8b').to + 6, cutDone = clickApprove + CUT;
  const [id, g, done] = ['c003', 'c003-giulia', 'c003-refunded'];
  const left = union(box(id, 'came'), box(id, 'paypal-in'));
  const shots: ShotSpec[] = [
    {id, from, to: cutGiulia,
      cams: [{at: from, cam: camUp(left, 1.45)}, {at: b1 - 4, cam: rightUp(box(id, 'right'), 1.7), dur: 24},
        {at: b3 - 4, cam: rightUp(box(id, 'pass-row'), 1.7), dur: 24}],
      spots: [{at: from + 8, box: box(id, 'email')}, {at: opened, box: box(id, 'opened')}, {at: a2, box: box(id, 'came')},
        {at: b1 + 4, box: box(id, 'right')}, {at: b3, box: box(id, 'pass-row')}],
      cursor: [{at: b3 + 4, pos: {x: 1500, y: 900}}, {at: clickPass, box: box(id, 'pass'), click: true, move: 16}],
      where: {text: 'Second Look › Case DEMO-C003', ...MARTA, map: [1]}, labelIn: true},
    {id: g, from: cutGiulia, to: cutDone,
      cams: [{at: cutGiulia, cam: rightUp(union(box(g, 'note'), box(g, 'approve-row')), 1.3)}],
      spots: [{at: cutGiulia + 2, box: box(g, 'note')}, {at: clickApprove - 16, box: box(g, 'approve-row')}],
      cursor: [{at: cutGiulia + 4, pos: {x: 1500, y: 950}}, {at: clickApprove, box: box(g, 'approve'), click: true, move: 16}],
      where: {text: 'Second Look › Case DEMO-C003', ...GIULIA, map: [2]}},
    {id: done, from: cutDone, to,
      cams: [{at: cutDone, cam: rightUp(box(done, 'done'), 1.8)}],
      spots: [{at: cutDone + 2, box: box(done, 'done')}],
      where: {text: 'Second Look › Case DEMO-C003', ...GIULIA, map: [2]}, labelOut: true},
  ];
  return <Scene from={from} to={to}><Shots shots={shots} /></Scene>;
};

// ---------- 9. I know: the month, and the books ----------
const Month: React.FC = () => {
  const from = beat('s9a').from, to = beat('s9b').next;
  const words = [['requests', 0.39], ['solved', 0.43], ['staff', 0.7], ['money', 0.78], ['fees', 0.91]] as const;
  const toBooks = beat('s9b').from - 6;
  const id = 'numbers';
  const shots: ShotSpec[] = [
    {id, from, to: toBooks,
      cams: [{at: from, cam: camUp(box(id, 'table'), 1.15)}],
      spots: [{at: from + 10, box: box(id, 'table')}, ...words.map(([k, f]) => ({at: at('s9a', f), box: box(id, k)}))],
      where: {text: 'Second Look › Numbers', ...GIULIA, map: [3]}, labelIn: true},
    {id: 'bookbox', from: toBooks, to,
      cams: [{at: toBooks, cam: camUp(union(box('bookbox', 'title'), box('bookbox', 'row-1')), 1.25)}],
      spots: [{at: toBooks + 12, box: box('bookbox', 'row-1')}],
      where: {text: 'Bookbox › What it received', sub: 'a made-up bookkeeping stand-in', map: [3]}, labelOut: true},
  ];
  return <Scene from={from} to={to}><Shots shots={shots} /></Scene>;
};

// ---------- 10. Is it real? ----------
// The live sandbox dispute, then the refund made through PayPal's refund API on 26 Oct (LOG): a card, since
// that refund was called directly, not from a case page, and the voice doesn't claim the page.
const Live: React.FC = () => {
  const frame = useCurrentFrame();
  const from = beat('s10a').from, to = beat('s10a').next;
  const [, s2] = sentenceStarts('s10a');
  const reply = at('s10a', 0.36), proof = at('s10a', 0.46), refund = at('s10a', 0.56);
  const id = 'live';
  const card = fadeIn(frame, refund, 12);
  const shots: ShotSpec[] = [
    {id, from, to, strength: 0.7,
      cams: [{at: from, cam: camTop()}, {at: s2 - 4, cam: camUp(union(box(id, 'reply'), box(id, 'proof')), 1.45), dur: 28}],
      spots: [{at: from + 8, box: box(id, 'mode')}, {at: reply, box: box(id, 'reply')}, {at: proof, box: box(id, 'proof')}],
      where: {text: 'Live · PayPal sandbox', sub: 'Second Look on a one-person test shop', live: true}, labelIn: true, labelOut: true},
  ];
  return (
    <Scene from={from} to={to}>
      <Shots shots={shots} />
      {card > 0 ? (
        <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', background: `rgba(30,41,53,${0.55 * card})`}}>
          <div style={{opacity: card, transform: `translateY(${(1 - card) * 16}px)`, width: 1060, background: '#fff',
            borderTop: `10px solid ${theme.pass}`, padding: '40px 52px 44px', boxSizing: 'border-box', boxShadow: '0 24px 70px rgba(0,0,0,0.35)'}}>
            <div style={{font: `500 26px ${theme.sans}`, color: theme.pass}}>Live · PayPal sandbox · 26 Oct 2026</div>
            <div style={{font: `700 64px/1.15 ${theme.sans}`, color: theme.ink, marginTop: 16, letterSpacing: -1}}>Refunded 1.00 EUR of 12.00</div>
            <div style={{font: `400 36px/1.3 ${theme.serif}`, color: theme.soft, marginTop: 10}}>through PayPal’s own refund API</div>
            <div style={{font: `500 24px ${theme.sans}`, color: theme.soft, marginTop: 26, letterSpacing: 0.5}}>refund 7WT94554XS657562E · COMPLETED</div>
          </div>
        </AbsoluteFill>
      ) : null}
    </Scene>
  );
};

// ---------- 11. Can I trust it? ----------
const Trust: React.FC = () => {
  const frame = useCurrentFrame();
  const from = beat('s11a').from, to = beat('s11b').next;
  const [t1, t2, t3] = sentenceStarts('s11a');
  const end = beat('s11b').from - 6;
  const Y = 380, H = 300, W = 380, GAP = 76, X0 = (WIDTH - (4 * W + 3 * GAP)) / 2;
  const x = (i: number) => X0 + i * (W + GAP);
  const flow = 1 - fadeIn(frame, end, 12);
  const card = fadeIn(frame, end + 6, 14);
  const [, n] = sentenceStarts('s11b');
  const boxes = [
    {on: t1, title: 'Second Look’s AI recommends', body: 'An answer and a drafted reply.', tone: theme.ink},
    {on: t2, title: 'Your limits, in code', body: 'They have the last word.', tone: theme.kraft},
    {on: t3, title: 'A person approves', body: 'Within their own limit.', tone: theme.pass},
    {on: t3 + 14, title: 'PayPal and your systems', body: 'The reply, PayPal, the helpdesk, the accounts.', tone: theme.ink},
  ];
  return (
    <Scene from={from} to={to}>
      {flow > 0 ? (
        <AbsoluteFill style={{opacity: flow}}>
          {boxes.map((b, i) => {
            const o = fadeIn(frame, b.on, 10);
            return (
              <div key={i} style={{position: 'absolute', left: x(i), top: Y, width: W, height: H, opacity: o, background: '#fff',
                border: `2px solid ${theme.rule}`, borderTop: `10px solid ${b.tone}`, padding: '26px 28px', boxSizing: 'border-box',
                transform: `translateY(${(1 - o) * 16}px)`}}>
                <div style={{font: `700 40px/1.15 ${theme.sans}`, color: theme.ink}}>{b.title}</div>
                <div style={{marginTop: 16, font: `400 30px/1.35 ${theme.sans}`, color: theme.soft}}>{b.body}</div>
              </div>
            );
          })}
          {[0, 1, 2].map((i) => <Arrow key={i} x1={x(i) + W + 8} y1={Y + H / 2} x2={x(i + 1) - 8} y2={Y + H / 2} on={boxes[i + 1].on - 4} />)}
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
// As draft 9 (see Scenes3): "ClaudiaOnClaude", thin and faint, centred at the bottom of every screen but
// the end card; paper on the dark scenes, ink with a solid paper halo over the app captures.
const inter = loadInter('normal', {weights: ['300'], subsets: ['latin']});
const Signature: React.FC = () => {
  const frame = useCurrentFrame();
  const endCard = beat('s11b').from - 6;
  if (frame >= endCard) return null;
  const dark = frame < beat('s3a').from; // scenes 1 and 2
  const app = frame >= beat('s5a').from && frame < beat('s11a').from;
  const o = Math.min(fadeIn(frame, 0, 12), 1 - fadeIn(frame, endCard - 10, 10));
  return (
    <>
      {app ? <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 60, opacity: o,
        background: 'linear-gradient(to bottom, rgba(245,246,242,0), rgba(245,246,242,0.15))'}} /> : null}
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 28, textAlign: 'center', opacity: (app ? 1 : 0.45) * o,
        font: `300 18px ${inter.fontFamily}, ${theme.sans}`, letterSpacing: '0.15em',
        color: dark ? theme.paper : app ? 'rgba(30,41,53,0.6)' : theme.ink,
        textShadow: app ? '0 0 2px rgb(245,246,242), 0 0 4px rgb(245,246,242), 0 0 6px rgb(245,246,242)' : undefined}}>
        ClaudiaOnClaude
      </div>
    </>
  );
};

export const Scenes4: React.FC = () => (
  <>
    <Channels /><Costs /><Flow /><Team /><Morning /><Call /><Dispute /><Right /><Month /><Live /><Trust />
    <Signature />
  </>
);
