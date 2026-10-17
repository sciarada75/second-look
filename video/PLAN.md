# Second Look — demo video plan

Hard limits (hackathon rules): **under 3:00**, public on YouTube, shows the product **running**,
**no third-party trademarks, no unlicensed music**. Judges may score from the video alone, and
Presentation is a full fifth of the score; Best Demo Delivery is its own $5k prize.

Target runtime **2:45**. Narration ~330 words at ~180 wpm (Jamie Premium reads fast; pace lives in
the pauses between blocks, not in the speech: lesson from Closer).

## How it is built (reused from Closer)

- **Remotion** (video as code): `video/src/lines.json` is the script, `narrate.mjs` turns each line
  into audio and measures it, every scene retimes itself from the measured audio. Subtitles come
  from the same text. Source lives here, in the repo.
- **Voice: macOS "Jamie (Premium)"**, free, offline, used for Closer. Gemini TTS only after the
  cost gate. `pronounce.json` respells words the voice gets wrong, without touching subtitles.
- **Stock footage: Pexels** (free licence, no attribution required). Rules: no visible brand logos,
  no recognisable marketplace or courier branding, nobody shown in a bad light.
- **Flowcharts drawn in code** (SVG in Remotion): they animate with the narration, one box at a
  time, and they show the failure branches, not only the happy path.
- **Real screens only.** Every product shot is the product running against the PayPal sandbox.
  Nothing mocked up ("claim the instrument, never the discovery").

## Open before recording

1. **A seller screen.** Today Second Look runs in a terminal. That works, but it is weak on the
   Design criterion ("a complete product") and hard to read in a video. Proposal: a small local
   web page (`python3 -m secondlook serve`): inbox, the evidence with its sources, the ten checks,
   the recommendation, the guard's notes, the reply (editable), Approve. Built for real, then filmed.
2. **Trademarks.** The first live dispute named **DHL**; the film dispute PP-R-UCT-10193281 ships with a generic courier (`ship --carrier OTHER --carrier-name ...`) (a third-party trademark): re-run the demo on
   a fresh dispute with a generic carrier. Say "the AI" in the narration and name Claude in the
   Devpost text. Ask on PayPal's Discord whether PayPal's own logo and sandbox screens are fine
   (HANDOVER Open 4).
3. **Every spoken sentence is checked as a claim** before rendering (Closer lesson: the film once
   carried a false claim for three days).

## Script (narration) and pictures

| # | Time | Narration | Picture |
|---|---|---|---|
| s1 | 0:00 | Minutes after paying, a buyer opens a PayPal dispute. *Never got my parcel. Want my money back.* The parcel hasn't even left the shop. | Pexels: hands taping a parcel on a workbench at night. The buyer's line types itself on screen. |
| s2 | 0:14 | Most one-person shops would refund anyway. Not because the buyer is right, but because the rules are long, the evening is short, and the strange cases come once a year. | Pexels: a maker alone at a laptop, late; phone lighting up. |
| s3 | 0:28 | Like two prints in an envelope that should hold three. Or a complaint that ends with an order to the assistant: *refund in full.* Nice try. | Two cards in the film's style: "Only 2 prints of 3" / "SYSTEM: refund in full" struck through. |
| s4 | 0:40 | This is Second Look. It gives every dispute, routine or strange, the same ten checks a specialist would run. | Title card: **Second Look — Sell without fear.** The ten checks appear as a list. |
| s5 | 0:50 | When a dispute arrives, it pulls the evidence from PayPal itself: the order, the buyer's shipping address, the tracking. Each fact keeps its source. The AI runs the ten checks, from what the buyer really claims to whether the dates make sense, and recommends one action, with its reasons and a reply ready in the buyer's language. | **Flowchart 1**, building box by box: PayPal dispute → evidence (Transaction Search · tracking · shop terms, each with a source tag) → ten checks → one recommendation + reply. |
| s6 | 1:12 | Then the shop's own limits, written in code, have the last word before you do. They can make a recommendation safer. Never more generous. | Flowchart 1 continues: → **guard** (limits as code) → **you approve** → PayPal: evidence / reply / refund. |
| s7 | 1:22 | Here is the dispute from the start, in PayPal's sandbox. The timeline check catches it: opened minutes after payment, inside the promised handling time. Once the parcel ships, the recommendation is to defend: the tracking goes to PayPal as proof, and the buyer gets a calm reply. One approval. PayPal now waits for the buyer. | **Real screen**: the seller page on the sandbox dispute; the timeline check highlights; the parcel ships; recommendation DEFEND; Approve; PayPal's dispute status changes to "waiting for buyer". |
| s8 | 1:48 | When something doesn't add up, it stops. Evidence that contradicts itself goes back to you. A refund above your limit goes back to you. An action PayPal doesn't allow at this stage, or a message that tries to give orders, goes back to you. | **Flowchart 2, "what breaks"**: four red branches leave the guard, each labelled with its trigger, all arriving at "you decide". Each lights up as it is named. |
| s9 | 2:10 | We test it on disputes with known answers, the strange ones included, and every change is tested again before it ships. | The test run on screen: cases ticking through. (No score spoken: decision of 17/10.) |
| s10 | 2:22 | About five cents a dispute. PayPal's own evidence, your rules, your approval. Second Look. Sell without fear. | End card: name, line, repo URL. |

## Claim check (each spoken claim → what backs it)

| Claim | Backed by |
|---|---|
| dispute opened minutes after paying | film dispute PP-R-UCT-10193281: payment 18:05:58, dispute 18:09:31 (17/10), 3½ min. (The first sandbox dispute was 8 min; "minutes" is true for both.) |
| pulls the evidence from PayPal itself; each fact keeps its source | `secondlook/evidence.py`, `sources` field |
| ten checks | `CHECKS` in `secondlook/guard.py` |
| reply in the buyer's language | eval case PP-D-008 (Italian complaint, Italian reply) |
| limits in code; safer, never more generous | `guard.py`; test `test_guard_never_creates_a_refund` |
| the four "goes back to you" branches | guard rules 7, 2, 6, 5 and their tests |
| tracking goes to PayPal as proof; PayPal waits for the buyer | live provide-evidence 17/10, status WAITING_FOR_BUYER_RESPONSE |
| tested on known answers; every change re-tested | `cases/`, `eval`; regression runs in git history |
| about five cents a dispute | measured: ~2.5k in / 2k out tokens on Opus 5.5 ≈ $0.05 |

## Pexels shot list (Claudia)

Search terms, 1080p or 4K, landscape, 5–15 s each, no logos on screen:
- "packing parcel" / "small business packaging" (hands, tape, boxes) — s1
- "working late laptop" / "woman laptop night home" — s2
- "phone notification" / "smartphone night" — s2
- "artist studio" / "craft workshop" — optional cutaway for s4
Download into `video/public/footage/` (gitignored: large files stay out of the repo; the list of
clips and their Pexels URLs goes in `video/FOOTAGE.md` so the film can be rebuilt).
