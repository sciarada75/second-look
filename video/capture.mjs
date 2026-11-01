#!/usr/bin/env node
// Walks the film's path once in a real browser over the running apps, and keeps what the film needs:
// a sharp full-page screenshot of each step (public/captures/<id>.png) and the box of every element
// the film points at (src/captures.json). The film is then built from these, with no server running.
//
//   cd video && node capture.mjs
//
// Draft 10 (script-v4.md). Best run against a fresh copy of the repo, as a judge would first open it
// (the morning's state is the demo's first load): Second Look started with SECONDLOOK_NOTIFY_URL pointing
// at Ticketbook's /hooks/secondlook and SECONDLOOK_BOOKS_URL at Bookbox's, Ticketbook pointed at Second
// Look, Bookbox running. Where they run: SL, TB, BB (default :8765, :8766, :8767) and APP_ROOT, the
// folder the apps run from (default this repo).
//
// It changes the demo state on purpose (Marta answers and closes Sophie's case, defends DEMO-031 and
// passes Pablo's case up; Giulia refunds it), so it backs up the apps' whole .tmp first and puts it back
// at the end, checked by SHA-1. Every action is on the made-up demo shop: logged, never sent to PayPal.
// It never asks for an AI review: any POST other than those is blocked in the browser.

import {createHash} from 'node:crypto';
import {cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync} from 'node:fs';
import {dirname, join, relative, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const PW = '/Users/claudiamauri/.npm/_npx/361ceb562f3b3235/node_modules/playwright/index.mjs';
const SHELL = '/Users/claudiamauri/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell';
const {chromium} = await import(PW);

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(process.env.APP_ROOT ?? join(HERE, '..'));
const OUT = join(HERE, 'public', 'captures');
const BACKUP = join(HERE, '.capture-backup');
const SL = process.env.SL ?? 'http://127.0.0.1:8765';
const TB = process.env.TB ?? 'http://127.0.0.1:8766';
const BB = process.env.BB ?? 'http://127.0.0.1:8767';

// ---------- the demo state: back up, restore, verify ----------
const sha1 = (f) => createHash('sha1').update(readFileSync(f)).digest('hex');
// Every file the apps could touch, to prove nothing changed once the backup is back.
const WATCH = ['.tmp', 'records', 'demo', 'helpdesk/tickets.json', 'policy.json'];
const walkFiles = (p) => {
  const abs = join(ROOT, p);
  if (!existsSync(abs)) return [];
  if (statSync(abs).isFile()) return [p];
  return readdirSync(abs).flatMap((n) => walkFiles(join(p, n)));
};
const snapshot = () => Object.fromEntries(WATCH.flatMap(walkFiles).map((f) => [f, sha1(join(ROOT, f))]));

// Files under a folder, relative to it (the backup copy is outside ROOT, so walkFiles can't list it).
const walkDir = (abs, rel = '') => readdirSync(abs).flatMap((n) =>
  statSync(join(abs, n)).isFile() ? [join(rel, n)] : walkDir(join(abs, n), join(rel, n)));

function backup() {
  rmSync(BACKUP, {recursive: true, force: true});
  mkdirSync(BACKUP, {recursive: true});
  const copy = join(BACKUP, 'tmp');
  if (existsSync(join(ROOT, '.tmp'))) cpSync(join(ROOT, '.tmp'), copy, {recursive: true});
  // Checksums of the copy, not of the live files: the apps are running and may write .tmp between the copy and
  // the hashing, and restore() must be checked against what the backup actually holds.
  const sums = existsSync(copy) ? Object.fromEntries(walkDir(copy).map((f) => [join('.tmp', f), sha1(join(copy, f))])) : {};
  writeFileSync(join(BACKUP, 'checksums.json'), JSON.stringify(sums, null, 2));
  return sums;
}

function restore(sums) {
  rmSync(join(ROOT, '.tmp'), {recursive: true, force: true});
  if (existsSync(join(BACKUP, 'tmp'))) cpSync(join(BACKUP, 'tmp'), join(ROOT, '.tmp'), {recursive: true});
  const now = Object.fromEntries(walkFiles('.tmp').map((f) => [f, sha1(join(ROOT, f))]));
  const bad = [...new Set([...Object.keys(sums), ...Object.keys(now)])].filter((f) => sums[f] !== now[f]);
  if (bad.length) throw new Error(`restore failed for: ${bad.join(', ')}`);
}

// ---------- the walk ----------
// The only forms the walk may submit. Pablo's case DEMO-C003 is answered on its PayPal dispute, DEMO-034 (the
// email joined the dispute's case), so his pass and refund post to /d/DEMO-034/approve, not to /c/DEMO-C003.
const ALLOWED_POSTS = [/^\/d\/DEMO-C001\/approve$/, /^\/c\/DEMO-C001\/close$/, /^\/d\/DEMO-031\/approve$/, /^\/d\/DEMO-034\/approve$/];
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
  console.log(`  ${id.padEnd(18)} ${size.w}x${size.h}  ${Object.keys(b).length} boxes${nulls.length ? `  NULL: ${nulls.join(', ')}` : ''}`);
}

const go = async (page, url, timeout = 30000) => {
  const res = await page.goto(url, {waitUntil: 'load', timeout});
  if (!res || res.status() >= 400) throw new Error(`${url} answered ${res ? res.status() : 'nothing'}`);
};
/** Click a form's button and wait for the page it leads to. */
const submit = async (page, button) => {
  await Promise.all([page.waitForNavigation({waitUntil: 'load'}), button.click()]);
};

// Locators: by role or visible text wherever the page offers it.
const css = (sel, hasText) => (p) => (hasText ? p.locator(sel, {hasText}) : p.locator(sel));
const ev = (label) => (p) => p.locator('div.ev', {has: p.locator('dt', {hasText: new RegExp(`^${label}$`)})});
const btn = (name) => (p) => p.getByRole('button', {name});
const said = (hasText) => css('ol.talk > li', hasText);
const tracked = (hasText) => css('ul.tracked > li', hasText);
const caseBoxes = {
  where: css('header.top'),
  came: css('p', 'Came in by'),
  tracked: css('ul.tracked'),
  talk: css('ol.talk'),
  state: css('div.state-box'),
  verdict: css('section.verdict'),
  reply: css('textarea'),
};

async function walkThrough(page) {
  const demo = 'shop=demo&film=1';

  console.log('Second Look, Today, as Giulia');
  await go(page, `${SL}/today?${demo}&as=giulia`);
  await shoot(page, 'today', {
    where: css('header.top'),
    hello: css('h1.page'),
    morning: css('div.morning'),
    orders: css('p.who', 'new orders'),
    chips: css('p.chips'),
    new: css('section.new'),
    list: css('section.new ol.see'),
    'row-sophie': css('section.new ol.see > li', 'Sophie Durand'),
    team: css('section.team'),
    needs: css('section.needs'),
    'ai-check': css('section.needs li.ai-check'),
    'rules-nav': (p) => p.locator('header.top nav a', {hasText: 'Your rules'}),
  });

  await go(page, `${SL}/rules?${demo}&as=giulia`);
  await shoot(page, 'rules', {
    where: css('header.top'),
    own: css('section.rules', "Second Look's AI on its own"),
    intro: css('section.rules p', 'Everything it sends is signed'),
    kind: css('section.rules li', '10 of the last 10'),
    sure: css('section.rules li', 'at least 90% sure'),
  });

  console.log("Sophie's case, as Marta");
  await go(page, `${SL}/c/DEMO-C001?${demo}&as=marta`);
  await shoot(page, 'c001', {
    ...caseBoxes,
    call: said('Call in'),
    email: said('Email in'),
    neighbour: tracked('neighbour'),
    approve: btn('Approve: reply only'),
  });
  await submit(page, page.getByRole('button', {name: 'Approve: reply only'}));
  await go(page, `${SL}/c/DEMO-C001?${demo}&as=marta`);
  await shoot(page, 'c001-sent', {
    ...caseBoxes,
    done: css('div.done-line'),
    out: said('Email out'),
    close: css('form[action$="/close"]'),
    'close-btn': btn('Close it'),
  });
  await submit(page, page.getByRole('button', {name: 'Close it'}));
  await go(page, `${SL}/c/DEMO-C001?${demo}&as=marta`);
  await shoot(page, 'c001-closed', {...caseBoxes, done: css('div.done-line'), 'closed-tag': css('span', 'Closed: solved before any dispute')});

  console.log("Ticketbook #2001, as Marta");
  await go(page, `${TB}/t/2001?as=marta&film=1`);
  await shoot(page, 'tb-2001', {
    email: css('article.msg'),
    panel: css('section.sl'),
    verdict: css('section.sl p.rec'),
    'open-sl': (p) => p.getByRole('link', {name: 'Open in Second Look'}),
  });

  console.log("Dario's dispute, as Marta");
  await go(page, `${SL}/d/DEMO-031?${demo}&as=marta`);
  await shoot(page, 'd031', {
    ...caseBoxes,
    delivered: tracked('delivered'),
    'ships-to': ev('Ships to'),
    'paypal-address': css('li.check', "Delivered to the buyer's PayPal address"),
    buyer: ev('This buyer'),
    costs: css('details.costs'),
    approve: btn('Approve: defend with evidence'),
  });
  await submit(page, page.getByRole('button', {name: 'Approve: defend with evidence'}));
  await go(page, `${SL}/d/DEMO-031?${demo}&as=marta`);
  await shoot(page, 'd031-sent', {...caseBoxes, done: css('div.done-line')});

  console.log("Pablo's case, as Marta, then Giulia");
  await go(page, `${SL}/c/DEMO-C003?${demo}&as=marta`);
  await shoot(page, 'c003', {
    ...caseBoxes,
    email: said('Email in'),
    opened: said('PayPal dispute opened'),
    'paypal-in': said('PayPal in'),
    right: css('section.verdict p', 'The buyer is right'),
    pass: btn('Pass to Giulia'),
    'pass-row': css('div.approve', 'Pass to Giulia'),
  });
  await submit(page, page.getByRole('button', {name: 'Pass to Giulia'}));
  await go(page, `${SL}/c/DEMO-C003?${demo}&as=marta`);
  await shoot(page, 'c003-passed', {...caseBoxes, done: css('div.done-line')});
  await go(page, `${SL}/c/DEMO-C003?${demo}&as=giulia`);
  const approve034 = btn('Approve: refund in full (89.00 EUR)');
  await shoot(page, 'c003-giulia', {
    ...caseBoxes,
    approve: approve034,
    'approve-row': css('div.approve', 'Approve: refund in full'),
    note: css('section.look div.guard', 'Marta'),
  });
  await submit(page, approve034(page));
  await go(page, `${SL}/c/DEMO-C003?${demo}&as=giulia`);
  await shoot(page, 'c003-refunded', {...caseBoxes, done: css('div.done-line')});

  console.log('Numbers, as Giulia');
  await go(page, `${SL}/numbers?${demo}&as=giulia`);
  const row = (t) => css('table.compare tr', t);
  await shoot(page, 'numbers', {
    where: css('header.top'),
    table: css('table.compare'),
    requests: row('Requests, every channel'),
    solved: row('Solved before any PayPal dispute'),
    staff: row('Staff time'),
    money: row('Money given back'),
    fees: row('PayPal dispute fees'),
    export: css('a.export'),
  });

  console.log('Bookbox');
  await page.waitForTimeout(1500);   // the books are posted in the background
  await go(page, `${BB}/`);
  await shoot(page, 'bookbox', {
    head: css('header'),
    title: css('h1'),
    table: css('table'),
    'row-1': css('tbody tr'),
  });

  console.log('Live: PayPal sandbox (up to 60 s)');
  try {
    await go(page, `${SL}/d/PP-R-UCT-10193281?shop=live&film=1`, 60000);
    await shoot(page, 'live', {
      where: css('header.top'),
      mode: css('header.top span.mode'),
      said: css('ol.talk'),
      reply: css('ol.talk li.you'),
      proof: css('ol.talk li.proof'),
      done: css('div.done-line'),
    });
  } catch (err) {
    result.errors['live'] = String(err.message || err);
    console.log(`  live ERROR: ${result.errors['live']}`);
  }
}

// ---------- run ----------
for (const [url, name] of [[SL, 'Second Look'], [TB, 'Ticketbook'], [BB, 'Bookbox']]) {
  try {
    await fetch(`${url}/`, {signal: AbortSignal.timeout(5000)});
  } catch {
    console.error(`${name} isn't answering on ${url}. Start it first.`);
    process.exit(2);
  }
}

const before = snapshot();
const sums = backup();
console.log(`Backed up ${Object.keys(sums).length} files of ${relative(HERE, join(ROOT, '.tmp')) || '.tmp'} (SHA-1)`);
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
  page.on('dialog', (d) => d.accept());
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
