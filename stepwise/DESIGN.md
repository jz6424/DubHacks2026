# Stepwise — design ideas

The user's hands are busy and messy, and they're standing about 1–2 m from the screen.
So the UI has to **read from across the room** and work **without touch**.

## Three layout directions

### A. "Split Kitchen" (the default in the scaffold)
```
┌──────────┬──────────────────────────────────────────┐
│ ✓ Step 1 │  Step 3 of 8 · Whisk the eggs            │
│ ✓ Step 2 │ ┌──────────────────┐ ┌──────────────────┐│
│ ● Step 3 │ │ tutorial segment │ │  your camera     ││
│ ○ Step 4 │ │ (looping 1:42–   │ │  [bowl] ◯ 70%    ││
│ ○ Step 5 │ │  2:05)           │ │ "a few lumps left"│
│          │ └──────────────────┘ └──────────────────┘│
│          │  ← Back    Skip           [ Done ✓ ]     │
└──────────┴──────────────────────────────────────────┘
```
The safest choice and easy to demo, since judges see the "match the video" idea right away.

### B. "Mirror"
The camera fills the screen. The tutorial clip is a picture-in-picture in a corner,
and the current step title is overlaid in large type at the top. The checklist is a thin
progress rail along the bottom. It feels like a smart mirror or fitness app and is the
most immersive option. Best for crafts like origami, knots, or makeup.

### C. "Recipe Card"
Typography first, warm and editorial. A big step card in the center, with the
video and camera as smaller tiles underneath. Best for written recipes that have no
video. Steps flip like cards when completed.

**Recommendation:** build A, and borrow B's large overlaid title and C's card flip as
transitions. That gives one solid layout plus some flair.

## Interaction details that make it feel magical
- **Confidence ring.** When the first positive check arrives, a ring around the
  step fills over about 2 s. If confirmed, it bursts into a ✓ with a soft chime. If not, it
  drains. Users see the AI "thinking" instead of nothing happening.
- **Grounding boxes.** Isaac draws thin labeled boxes on the objects it's judging
  (`bowl`, `whisk`). This is the clearest visual proof that the vision model is working.
- **Gentle hints.** Hints are framed as what's left, not what's wrong ("a few lumps left —
  keep whisking"). Show at most one every 8 s.
- **Ahead-of-you detection.** If the user does step 5 while on step 4, auto-complete
  step 4 with an "inferred" marker (hollow check) instead of insisting.
- **Hands-free controls.** Say "next" / "back" / "replay" (Web Speech API), or hold an
  open palm to the camera for 1 s to mark Done (stretch goal).
- **Video scrubber with step ticks.** The tutorial's timeline is colored by step.
  Done segments turn green. Tapping a tick jumps to that step.
- **Timer steps.** Non-verifiable "wait 10 min" steps become a large countdown that
  auto-advances.
- **Recap screen.** Time spent per step against the video's pacing ("you were 2×
  faster at chopping!"), plus a share card.

## Visual language
- Warm off-white `#faf7f2` background with ink `#1d1b18`. Dark mode for workshops and
  garages.
- One accent color (tomato `#e8562a`) for "active", and green `#2f9e6b` for "done".
- Step titles at 28–40 px, readable at 2 m. Body text at 16 px.
- Rounded 16 px tiles and a soft shadow on only the active card.
- Motion: 200 ms ease-out for state changes. Celebrations are reserved for ✓.

## Demo tutorials to pre-bake (steps with large visual changes)
1. PB&J or a wrap: bread, spread, spread, close, cut. Visual, fast, and judges get it.
2. An origami crane or paper airplane: every fold is a clear shape change.
3. A tie or a bowline knot.
Avoid anything where the key step is a quantity (spices) or happens off-camera (oven).
