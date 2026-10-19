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

## Script and claims (as built, 19/10)

The script is `src/lines.json` (23 lines, 2:41 with pauses); pictures are in `src/Scenes.tsx`.
Built from three real takes on the sandbox (`public/recordings/`, gitignored: full-screen, with
Chrome's tabs, so every shot is cropped below the browser bar — `Shot` throws if a region would
show it) plus a still of the rules page taken with Playwright. Edits that skip time say so on
screen ("40 seconds later").

| Spoken claim | Backed by |
|---|---|
| minutes after paying | PP-R-UCT-10193281: paid 18:05:58, opened 18:09:31 |
| pulls the evidence from PayPal itself… buyer's history with your shop; each fact keeps its source | `evidence.py` (dispute, Transaction Search, trackers, `_buyer_history`), `sources` |
| ten checks | `CHECKS` in `guard.py` |
| reply in the buyer's language | eval case PP-D-008 (Italian in, Italian out) |
| limits in code; more careful, never more generous | `guard.py`, `test_guard_never_creates_a_refund` |
| opened under four minutes after payment, inside handling time | page "4 minutes later"; review "3 minutes 33 seconds" |
| no refund, no fight, a calm reply approved with one click | take A-tote-reply, 52–70 s; reply in PayPal 18/10 15:10 |
| next day the parcel ships | tracker LC1810260042, shipment_date 2026-10-18 |
| out of date → fresh look → defend, tracking sent to PayPal as proof | take A-tote-defend; PayPal evidence PROOF_OF_FULFILLMENT 19/10 03:28 |
| PayPal now waits for the buyer | status WAITING_FOR_BUYER_RESPONSE |
| three prints, two in the envelope, six minutes after paying; slip says three, scale says two | PP-R-CEF-10193282 18:07:01 → 18:12:44; `records/` slip 3, 95 g |
| asks the buyer for a photo, leaves the call to you | take B, "Your call" + "Send this question" |
| the four things that come back to you | guard rules 7, 2/3, 6, 5 and their tests |
| learns from you: a rule once, every review follows it | `seller_preferences` → `judge._case_text`; `/rules` |
| tested on disputes with known answers, strange ones included | `cases/`, `.tmp/eval-claude-details.json` (17/10): rows shown are real, including the miss sent to the seller |
| a few cents a dispute | measured ~$0.05 on 17/10; inputs grew since (history, rules), so "a few cents", not a number |

Not said, on purpose: any score or case count (decision 17/10), any third-party name. Claude is
named in the Devpost text, not in the film.

## Pexels shot list (Claudia)

Search terms, 1080p or 4K, landscape, 5–15 s each, no logos on screen:
- "packing parcel" / "small business packaging" (hands, tape, boxes) — s1
- "working late laptop" / "woman laptop night home" — s2
- "phone notification" / "smartphone night" — s2
- "artist studio" / "craft workshop" — optional cutaway for s4
Download into `video/public/footage/` (gitignored: large files stay out of the repo; the list of
clips and their Pexels URLs goes in `video/FOOTAGE.md` so the film can be rebuilt).
