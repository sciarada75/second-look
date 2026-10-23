#!/usr/bin/env node
// Walks the film's path once in a real browser over the running apps, and keeps what the film needs:
// a sharp full-page screenshot of each step (public/captures/<id>.png) and the box of every element
// the film points at (src/captures.json). The film is then built from these, with no server running.
//
//   cd video && node capture.mjs
//
// Needs Second Look on :8765 (started with SECONDLOOK_NOTIFY_URL=http://127.0.0.1:8766/hooks/secondlook)
// and Ticketbook on :8766.
//
// It changes the demo state on purpose (Marta approves #2001, passes #2004, Giulia approves DEMO-034),
// so it backs those files up first and puts them back at the end, checked by SHA-1. All three actions
// are on the made-up demo shop: logged, never sent to PayPal. It never asks for an AI review: any POST
// other than those three is blocked in the browser.

import {createHash} from 'node:crypto';
import {copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync} from 'node:fs';
import {dirname, join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

const PW = '/Users/claudiamauri/.npm/_npx/361ceb562f3b3235/node_modules/playwright/index.mjs';
const SHELL = '/Users/claudiamauri/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell';
const {chromium} = await import(PW);

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const OUT = join(HERE, 'public', 'captures');
const BACKUP = join(HERE, '.capture-backup');
const SL = 'http://127.0.0.1:8765';
const TB = 'http://127.0.0.1:8766';

// ---------- the demo state: back up, restore, verify ----------
const STATE = [
  '.tmp/reviews/DEMO-031.json',
  '.tmp/reviews/DEMO-034.json',
  '.tmp/assignments-demo.json',
  '.tmp/helpdesk-events.jsonl',
  '.tmp/actions-demo.jsonl',
  '.tmp/actions.jsonl',
  '.tmp/notify.log',
];
const sha1 = (f) => createHash('sha1').update(readFileSync(f)).digest('hex');

// Every other file the apps could touch, to prove nothing else changed.
const WATCH = ['.tmp', 'records', 'demo', 'helpdesk/tickets.json', 'policy.json'];
const walk = (p) => {
  const abs = join(ROOT, p);
  if (!existsSync(abs)) return [];
  if (statSync(abs).isFile()) return [p];
  return readdirSync(abs).flatMap((n) => walk(join(p, n)));
};
const snapshot = () => Object.fromEntries(WATCH.flatMap(walk).map((f) => [f, sha1(join(ROOT, f))]));

function backup() {
  rmSync(BACKUP, {recursive: true, force: true});
  mkdirSync(BACKUP, {recursive: true});
  const sums = {};
  for (const f of STATE) {
    const src = join(ROOT, f);
    if (existsSync(src)) {
      const dst = join(BACKUP, f.replaceAll('/', '__'));
      copyFileSync(src, dst);
      sums[f] = sha1(src);
      if (sha1(dst) !== sums[f]) throw new Error(`backup of ${f} doesn't match the original`);
    } else sums[f] = null; // didn't exist: delete it at the end
  }
  writeFileSync(join(BACKUP, 'checksums.json'), JSON.stringify(sums, null, 2));
  return sums;
}

function restore(sums) {
  for (const [f, sum] of Object.entries(sums)) {
    const dst = join(ROOT, f);
    if (sum === null) rmSync(dst, {force: true});
    else copyFileSync(join(BACKUP, f.replaceAll('/', '__')), dst);
  }
  const bad = Object.entries(sums).filter(([f, sum]) =>
    sum === null ? existsSync(join(ROOT, f)) : !existsSync(join(ROOT, f)) || sha1(join(ROOT, f)) !== sum);
  if (bad.length) throw new Error(`restore failed for: ${bad.map(([f]) => f).join(', ')}`);
}

// ---------- the walk ----------
const ALLOWED_POSTS = [/^\/t\/2001\/approve$/, /^\/t\/2004\/approve$/, /^\/d\/DEMO-034\/approve$/];
const result = {errors: {}};
const missing = [];

async function boxes(page, spec) {
  const out = {};
  for (const [name, find] of Object.entries(spec)) {
    try {
      const loc = find(page).first();
      await loc.waitFor({state: 'attached', timeout: 4000});
      out[name] = await loc.evaluate((el) => {
        const r = el.getBoundingClientRect();
        return {x: Math.round(r.x + scrollX), y: Math.round(r.y + scrollY), w: Math.round(r.width), h: Math.round(r.height)};
      });
      if (!out[name].w || !out[name].h) throw new Error('zero size');
    } catch (err) {
      out[name] = null;
      missing.push(`${page.__id}.${name}`);
    }
  }
  return out;
}

async function shoot(page, id, spec) {
  page.__id = id;
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
  const size = await page.evaluate(() => ({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight}));
  const b = await boxes(page, spec);
  await page.screenshot({path: join(OUT, `${id}.png`), fullPage: true});
  result[id] = {file: `captures/${id}.png`, width: size.w, height: size.h, boxes: b};
  const nulls = Object.entries(b).filter(([, v]) => !v).map(([k]) => k);
  console.log(`  ${id.padEnd(16)} ${size.w}x${size.h}  ${Object.keys(b).length} boxes${nulls.length ? `  NULL: ${nulls.join(', ')}` : ''}`);
}

const go = async (page, url, timeout = 30000) => {
  const res = await page.goto(url, {waitUntil: 'load', timeout});
  if (!res || res.status() >= 400) throw new Error(`${url} answered ${res ? res.status() : 'nothing'}`);
};

// Locators: by role or visible text wherever the page offers it.
const css = (sel, hasText) => (p) => (hasText ? p.locator(sel, {hasText}) : p.locator(sel));
const ev = (label) => (p) => p.locator('div.ev', {has: p.locator('dt', {hasText: new RegExp(`^${label}$`)})});

async function walkThrough(page) {
  console.log('Ticketbook, as Marta');
  await go(page, `${TB}/?as=marta&film=1`);
  await shoot(page, 'tb-inbox', {'row-dario': css('a.row', 'Where is my apron?')});

  await go(page, `${TB}/t/2001?as=marta&film=1`);
  const tb2001 = {
    email: css('article.msg'),
    panel: css('section.sl'),
    verdict: css('section.sl p.rec'),
    approve: (p) => p.getByRole('button', {name: /^Approve as Marta/}),
    'open-sl': (p) => p.getByRole('link', {name: 'Open in Second Look'}),
  };
  await shoot(page, 'tb-2001', tb2001);

  console.log('Second Look, as Marta');
  await go(page, `${SL}/d/DEMO-031?as=marta&shop=demo&film=1`);
  await shoot(page, 'sl-031', {
    timeline: css('ol.ruler'),
    'ships-to': ev('Ships to'),
    delivery: ev('Tracking'),
    history: ev('This buyer'),
    costs: css('details.costs'),
    where: css('header.top'),
  });

  console.log('Marta approves #2001 in Ticketbook');
  await go(page, `${TB}/t/2001?as=marta&film=1`);
  await Promise.all([page.waitForURL(/\/t\/2001\?.*flash=/), page.getByRole('button', {name: /^Approve as Marta/}).click()]);
  await shoot(page, 'tb-2001-sent', {
    flash: css('p.flash'),
    'history-line': css('.history li', 'answer sent to PayPal by Marta'),
    panel: css('section.sl'),
  });

  console.log('Marta passes #2004 to Giulia');
  await go(page, `${TB}/t/2004?as=marta&film=1`);
  await shoot(page, 'tb-2004', {
    email: css('article.msg'),
    'your-call': css('section.sl p.rec', 'Your call'),
    'ai-says': css('section.sl p.soft', "The AI's own answer"),
    pass: (p) => p.getByRole('button', {name: 'Pass to Giulia'}),
    'pass-says': css('section.sl form p.note'),
    panel: css('section.sl'),
  });
  await Promise.all([page.waitForURL(/\/t\/2004\?.*flash=/), page.getByRole('button', {name: 'Pass to Giulia'}).click()]);
  await shoot(page, 'tb-2004-passed', {
    flash: css('p.flash'),
    'history-line': css('.history li', 'passed to Giulia by Marta'),
    panel: css('section.sl'),
  });

  console.log('Second Look, as Giulia');
  await go(page, `${SL}/?shop=demo&as=giulia&view=mine&film=1`);
  const row034 = (p) => p.locator('li', {has: p.locator('a[href="/d/DEMO-034"]')});
  await shoot(page, 'sl-list-giulia', {
    'row-034': row034,
    'owner-034': (p) => row034(p).locator('span.owner'),
    where: css('header.top'),
  });

  await go(page, `${SL}/d/DEMO-034?as=giulia&film=1`);
  const approve034 = (p) => p.getByRole('button', {name: 'Approve: refund in full (89.00 EUR)'});
  await shoot(page, 'sl-034-giulia', {
    note: css('section.look div.guard', 'Marta suggests'),
    reply: css('textarea#reply'),
    approve: approve034,
    where: css('header.top'),
  });
  console.log('Giulia approves DEMO-034');
  await Promise.all([page.waitForURL(/\/d\/DEMO-034$/), approve034(page).click()]);
  await go(page, `${SL}/d/DEMO-034?as=giulia&film=1`);
  await shoot(page, 'sl-034-sent', {
    sent: css('section.look div.sent', 'Sent by Giulia'),
  });

  await go(page, `${SL}/overview?shop=demo&as=giulia&film=1`);
  await shoot(page, 'sl-overview', {
    exposure: css('section.exposure'),
    meter: css('section.meter-box'),
    where: css('header.top'),
  });

  console.log('Live: PayPal sandbox (up to 60 s)');
  try {
    await go(page, `${SL}/d/PP-R-UCT-10193281?shop=live&film=1`, 60000);
    await shoot(page, 'sl-live', {
      where: css('header.top'),
      mode: css('header.top span.mode'),
      said: css('ol.talk'),
      reply: css('ol.talk li.you'),
      proof: css('ol.talk li.proof'),
    });
  } catch (err) {
    result.errors['sl-live'] = String(err.message || err);
    console.log(`  sl-live ERROR: ${result.errors['sl-live']}`);
  }
}

// ---------- run ----------
for (const [port, name] of [[8765, 'Second Look'], [8766, 'Ticketbook']]) {
  try {
    await fetch(`http://127.0.0.1:${port}/`, {signal: AbortSignal.timeout(5000)});
  } catch {
    console.error(`${name} isn't answering on :${port}. Start it first.`);
    process.exit(2);
  }
}

const before = snapshot();
const sums = backup();
console.log('Backed up (SHA-1):');
for (const [f, s] of Object.entries(sums)) console.log(`  ${s ?? '(absent)'.padEnd(40)}  ${f}`);
mkdirSync(OUT, {recursive: true});

let failed = null;
const browser = await chromium.launch({executablePath: SHELL});
try {
  const ctx = await browser.newContext({viewport: {width: 1536, height: 900}, deviceScaleFactor: 3});
  await ctx.route('**/*', (route) => {
    const req = route.request();
    if (req.method() !== 'GET') {
      const path = new URL(req.url()).pathname;
      if (!ALLOWED_POSTS.some((r) => r.test(path))) {
        console.error(`  BLOCKED ${req.method()} ${req.url()}`);
        return route.abort();
      }
      console.log(`  POST ${path}`);
    }
    return route.continue();
  });
  const page = await ctx.newPage();
  await walkThrough(page);
} catch (err) {
  failed = err;
  console.error(`The walk stopped: ${err.stack || err}`);
} finally {
  await browser.close();
  try {
    restore(sums);
    const after = snapshot();
    const changed = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((f) => before[f] !== after[f]);
    if (changed.length) {
      console.error(`\n!!! restored the backed-up files, but these other files differ from before: ${changed.join(', ')}`);
      process.exitCode = 1;
    } else console.log('\nrestored, checksums match (and nothing else under .tmp, records, demo, helpdesk changed)');
  } catch (err) {
    console.error(`\n!!!!!!!! RESTORE FAILED: ${err.message}. The backup is in ${relative(process.cwd(), BACKUP)}. Put it back by hand.`);
    process.exit(1);
  }
}

writeFileSync(join(HERE, 'src', 'captures.json'), JSON.stringify(result, null, 1) + '\n');
console.log(`\n${Object.keys(result).filter((k) => k !== 'errors').length} captures written to src/captures.json`);
if (missing.length) console.log(`NULL boxes: ${missing.join(', ')}`);
if (Object.keys(result.errors).length) console.log(`errors: ${JSON.stringify(result.errors)}`);
if (failed) process.exit(1);
