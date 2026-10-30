# The card dropper's mechanism

*Plan and design, 2026-10-22/23; the wheels and the wheel block printed 2026-10-29. The station's side was written on 2026-10-22 (`station/dropper.py`,
PROGRAM_DOCUMENTATION.md, "The card dropper"). The mechanism is drawn in `hardware/dropper/card_dropper.scad` (also
as FreeCAD and STEP files, `hardware/dropper/freecad/`), its controller is `hardware/dropper/firmware/main.py`.
**Checked in CAD and the controller on a simulated Pico; only the wheels and the wheel block printed (2026-10-29), never assembled, never
run; no card has gone through it.** Every size marked *to measure* is a guess until it has been measured.*

## What it is for

A Raspberry Pi station (`station/dropper.py`) pulses one GPIO pin when the next card may come: after the capture
beep, with auto-add off only once the card was added or skipped, and the first card when auto-scanning starts.
One pulse means one card, and a card that is not captured releases nothing, so the stack never runs on by itself.
What the pin drives "is the mechanism's business". This is that mechanism.

The owner's requirements (2026-10-22/23):
- **it must not damage the cards** - the first concern, before speed (PRODUCT_PLAN.md, §4 phase 5);
- 3D-printed (a 256 x 256 mm bed, a 0.4 mm nozzle), of the project's own design; the landing tray may take *ideas*
  from the Card Slinger 3.0, not its geometry (patent pending, and a remixer reports it may not be modified -
  PRODUCT_PLAN.md, §3a);
- **sleeved and unsleeved cards**, with an adjustable gate;
- **wheels under the pile** (the owner's design): three axles of two wheels, the rear axle only rolling, the other two
  driven - silicone O-rings as tyres (50 x 44 x 3 mm, uxcell) and 608-2RS ball bearings (8 x 22 x 7), both the
  owner's choice; hobby servos with a small controller board.

A first design pushed the bottom card out with a servo-driven sled and a rack (2026-10-22). It was dropped on
2026-10-23 for the wheels: it was ~520 mm long against ~340, and needed a 0.2 mm pusher height set by hand.

## The design in one picture

```
 side view, cards travel left to right                                      camera arm
                                                                            ┌──[cam]──┐
            magazine (cards face up)            gate (screw)                │         │ post
          ┌──────────────────────────────────┐ ┃                            │         │
          │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ┃                            │         │
          │▓▓▓▓▓▓▓▓▓▓▓ card 1 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│═┻══ table ══╗ chute          │         │
 ─────────(1)─────────────(2)──────────────(3)─────────────╲               │         │
          idle            driven (servo A)  driven (servo B) ╲  ┌──────────────┐
          x = 12          x = 50            x = 95, just       ╲ │     tray     │
                          stops after 30 mm behind the gate      └──────────────┘
```

- The cards lie **face up** in a magazine without a floor, on **six wheels, two per axle** (a left and a right one:
  the card runs straight). Their tyres are the O-rings, stretched ~3% into a 45.5 mm groove: a wheel of ~51.4 mm as drawn - **50.5 mm as printed** (measured 2026-10-30;
  the card plane follows it, see "What was checked").
  **The tops of the six tyres are the card's plane**; a plate 1 mm below is only a floor.
- **Every axle is an 8 mm steel rod turning in two 608-2RS bearings**, pressed into housings on the block's side
  walls. The wheels are fixed to the rods with M3 grub screws.
- **Axle 1 (rear) only rolls**: it holds the card level and turns with it - rolling, not sliding, on its back.
- **Axles 2 and 3 are each turned by their own MG90S through a one-way bearing** (HF0812: 8 bore, 12 OD, 12 long)
  pressed into a hub on the servo's horn:
  - the servo's forward stroke turns the axle; its return slips, so **the wheels stand still while the servo swings
    back** - and one card can take several strokes (a card length needs ~190° of wheel, a servo turns ~180°);
  - a card pulled forward by the other axle **turns these wheels on freely** instead of sliding over them; and if the
    two servos run at slightly different speeds, the slower one's wheels just freewheel - neither can drag on the card.
- **Axle 2 stops early** (30 mm), long before card 1's back edge reaches it (41-48 mm): it helps the card break free
  under the full weight of the stack, then stands still. **Axle 3 stops just before card 1's back edge passes it**:
  until then card 1 lies between it and card 2, so neither driven axle ever turns under card 2. Axle 2's wheels sit
  at ±12 mm, the others' at ±24, so axles 2 and 3 (45 mm apart, wheels 51 mm across) can overlap along the card
  without meeting.
- Only the bottom card passes **under the gate**, whose gap lets one card through and holds the second back.
- **The finish is gravity** (the owner's wish: "it would just move down the ramp"): no wheel past the gate and no
  roller on top. When axle 3 stops, ~6 mm of card 1's tail is still under card 2's front edge (which rests against the
  gate); the last stroke ends at speed (`COAST_END`), so the card coasts on, and its centre is already past the end of
  the table (x = 130), so once the tail is free it tips onto the chute and slides **on its back** into the tray.
  **This is the untested heart of the design.**
- From the Card Slinger, three *ideas* (no geometry): a pocket with a funnel that centres the card under the camera,
  a removable tray for both card sizes, and a stand that holds the camera over it.

## Where a card is touched

Every surface a card meets, which side of the card, under what load, and whether it slides. Each damage test below
is a row of this table.

| Where | Side of the card | Load | Sliding? | Note |
|---|---|---|---|---|
| The card above it, while it moves out | **its face** (against the back of the card above) | the stack's weight, at most ~150 cards (~2.6 N, *to weigh*) | yes, one card length | The same contact as dealing a card off the bottom of a deck. **The one face-on-face slide of the whole path** - capped by the magazine's height (45 mm). The prime suspect for foils: test first. |
| Six silicone tyres | its back | the stack's weight | **rolling** | the one-way bearings and the free rear axle let every wheel turn with the card. Silicone is less likely to mark than nitrile - still to try on a junk card left under load for a day |
| A tyre of axle 3 if it overshoots | card 2's back, near its front edge | the stack's weight | **yes - the case to avoid** | why axle 3's travel errs short; the stop cannot be exact without a sensor |
| The plate, 1 mm under the tyres | its back, only if it sags | - | - | a floor, not a support; the wheel slots' far edges are chamfered |
| The gate's lower edge | the SECOND card's leading edge | the drag passed up | it rests against it | Rounded (r 1 mm) and lined with PTFE tape. A few cards can creep forward 3 mm under the front wall to it (the window is 1.5 mm high). |
| The table's rails, then the chute | its back | its own weight (1.8 g) | yes | the rails begin with a 45° ramp under the front wall; the chute's ribs start 0.5 mm under the card plane - no edge in the way |
| The end of the table | its back | its own weight | it pivots | a tail of a few mm may lift against card 2's front edge as it tips |
| The tray / the pile | its back on the previous card's face | its own weight, landing | yes, a few cm | The fall: up to the tray's depth (45 mm) for the first cards; at 30° the leading EDGE meets the floor first, not a corner. Like a toss by hand - but **never measured**. |
| The tray's far wall | its leading edge | its speed (~0.5 m/s, estimate) | stops it | 1-2 mm felt on that wall. Never measured. |

## The numbers

| | Value | From |
|---|---|---|
| Cards | sleeved 92 x 67 mm, unsleeved 88 x 63 mm; thickness ~0.30 mm unsleeved, ~0.6 mm sleeved | **to measure** with calipers on the owner's cards and sleeves; all are parameters at the top of the .scad |
| Magazine inside | 94 x 69 (sleeved), 90 x 65 (unsleeved), 45 mm of cards | card + 2 mm; two magazines with the same outside and the same front inner face |
| Capacity of one load | ~150 unsleeved, ~75 sleeved | 45 mm / thickness - **to measure**; the tray is as deep, so one load fills one tray |
| Wheel | Ø **50.5 mm with its ring, measured** on the printed wheels (2026-10-30) | drawn as 51.4: ring 44 ID stretched 3.4% into a 45.5 groove, its 3 mm section thinning to ~2.95 |
| Card plane | 89.55 mm above the table | the axles at 64.3 (the printed block) + half the wheel; 90 as first drawn |
| Card per degree of wheel | 0.441 mm | π x 50.5 / 360 (`MM_PER_DEG`); to calibrate against a ruler on the rig |
| Axle 3's travel | 86 mm sleeved, 82 unsleeved: 2 strokes of ~98° / ~93° | card 1's back edge passes axle 3 (x = 95) after 90 mm (a sleeved card at the gate) to 93 (one that stopped at the front wall); 4 mm short of the nearest - **short rather than long**: short is a missed card, long is a wheel turning under card 2 |
| Axle 2's travel | 30 mm, the first stroke only | its back edge reaches x = 50 after 41-48 mm |
| Table end | x = 130 | between two limits: in front of card 1's centre when axle 3 stops (x ≈ 135 unsleeved, 137 sleeved - otherwise it lies on the table and never tips), and not so far back that it tips with a long tail pinned under card 2 (it begins to tip when its back edge is at ~84-86, held flat by card 2's edge until free). **To tune on the rig** (`table_end`) |
| Grip | the stack's weight on six tyres; least on the last cards | a light weight on the stack would help them - and press the faces together harder (row 1 above) |
| One feed | ~2.4 s: two strokes of 0.7 s, two returns of 0.4 s | `firmware/main.py`, measured on the simulation only |
| Rods | one of 90 mm (idle), two of 102.5 mm (reaching 11.5 mm into their one-way bearing) | |
| Length | ~365 mm, from the wheel block's back to the landing base's end (the Pi stands on it, behind the post) | |

## The gate's gap

It cannot be printed: 0.4 mm is two layers, and it decides everything - too little and nothing feeds, too much and
two cards come out. It is set, and set again for the other card size, with feeler gauges (0.05-1.0 mm) and the
owner's cards: with the magazine on the plate, lay a gauge of the wanted gap (start: 1.4 x a card - 0.40-0.45 mm
unsleeved, 0.8-0.9 mm sleeved) across the rails under the gate, turn the gate's screw (M3, from the top of the
magazine: 0.5 mm a turn) until the gate rests on it, pull the gauge out, lock with the nut on top.

The rule it keeps: **one card < gate gap < two cards**.

**Then by test**, one card at a time with "Drop one card" (Settings > Cameras): two cards out -> a smaller gap;
nothing out -> a larger gap (the card stops at the gate), or the tyres slip (see "Jams and failures"). Write the
values that work, per card size, next to the printer's settings.

## Parts to print

All fit a 256 x 256 bed. `part = "..."` in the .scad, or the STEP file of the same name.

| Part | How many | Size, mm | Print | Notes |
|---|---|---|---|---|
| `bearing_test` | 1 | 90 x 21 x 30 | upright, as in the file | **before the block**: three pieces of its side wall, the 608's pocket at 22.05 / 22.20 / 22.35 mm (written on top), printed standing as the block is, so the pockets' tops are the same overhang. The size that takes a bearing by hand pressure and holds it still becomes `bearing_fit` |
| `wheel_block` | 1 | 150 x 90 x 86 | upright | walls only, open at the bottom; the bearing housings are ribs from the table up, no overhang |
| `wheel_plate` | 1 | 150 x 92 x 4.5 (2.55 under the rails; 5 / 3 for the 51.4 mm wheel) | flat, rails up | ironing on; the rails bare (the owner's choice, 2026-10-30: ironed rails first, PTFE tape only if the tests ask for it - see "Jams and failures") |
| `wheel` | 6 | Ø 48 x 15 | flat, boss up | an O-ring on each |
| `clutch_hub` | 2 | Ø 35 x 19.5 | on the horn's face | for the horn **uncut** (31.3 mm, measured 2026-10-30); the servo bracket's first leg is notched for its width |
| `servo_bracket` | 1 | 93 x 44 x 41 | on its mounting plate | holds both servos |
| `magazine_sleeved`, `magazine_unsleeved` | 1 each | 108 x 75 x 46 | upright | the gate's guides and screw ledge are part of it; the gate goes in from below. The front wall's bottom edge is a 69 mm bridge 2.5 mm over the bed: support under it, or file it straight |
| `gate` | 1 | 70 x 36 x 6 | on its back | round off its lower back edge if the print left a lip; PTFE tape on it |
| `chute` | 1 | 77 x 53 x 42 | on its side | |
| `tray` | 1 | 110 x 93 x 55 | upright | light, **matte** colour - see "The camera and the detector" |
| `landing_base` | 1 | 188 x 100 x 24 | flat | |
| `camera_post` | 1 | 20 x 20 x 230 | standing | |
| `camera_arm` | 1 | 104 x 40 x 24 | the clamp on the bed | |
| `pi_mount` | 1 | 96 x 90 x 35 | upright, standing on its sleeves | a plate behind the camera post for the Raspberry Pi 4 or 5 (the same holes) with the Pico right under it; two sleeves slide down over the post before the camera arm, the lower one resting on the post's socket with one M3 screw into the post |

## To buy

- 6 silicone O-rings 50 x 44 x 3 mm (uxcell, a pack of 10);
- 6 ball bearings 608-2RS (8 x 22 x 7);
- 2 one-way bearings **HF0812** (8 x 12 x 12) - mind the arrow: they must grip when the servo turns the card forward;
- 8 mm silver-steel rod, ~300 mm (cut to 90, 102.5, 102.5; file a flat where each grub screw bears);
- 2 MG90S servos (metal gears);
- a Raspberry Pi Pico (or Pico W); a 5 V supply of 2 A or more for the servos (not the Pi's 5 V pin: two stalling
  servos draw ~1.4 A and their spikes reach the Pi); a 470-1000 µF capacitor across the servos' supply; a 1 kΩ and two
  330 Ω resistors;
- 6 M3 grub screws (M3 x 6) and nuts; 4 M2 x 6 self-tapping screws for the horns; M3 screws (plate 6, bracket 6, chute 2, base 2, Pi mount 1) and nuts; one M4 bolt and nut
  for the camera arm; 4 M2.5 x 8 screws for the Pi, 4 M2 x 6 for the Pico (both self-tapping into the mount's
  standoffs);
- 2 servo extension cables, 50 cm (the servos are on the feeder, the Pico on the camera post);
- for a Raspberry Pi Camera Module: the 200 mm ribbon that comes with it reaches (camera -> arm -> down the post to
  the Pi: ~150 mm) - for a Pi 5, the 22-pin-to-15-pin "standard-mini" one, also 200 mm;
- PTFE tape (0.1 mm, self-adhesive) for the gate's edge - and the plate's rails, if bare ones fail (below); self-adhesive felt, soft feet, feeler gauges.

## Electronics and the controller

A hobby servo cannot read the station's pulse: it wants a 0.5-2.5 ms pulse every 20 ms, and the station sends one
pulse of 10-2000 ms per card. A Pico in between turns each pulse into one card's feed (`firmware/main.py`). The
station's code is unchanged: it pulses a pin, as it was written to.

| From | To |
|---|---|
| Pi GPIO17 (header pin 11) - or any free GPIO: the station has no default pin | 1 kΩ -> Pico GP15 |
| Pi GND (pin 9) | Pico GND |
| Pico GP16 | 330 Ω -> axle 2's servo signal |
| Pico GP17 | 330 Ω -> axle 3's servo signal |
| 5 V supply + | both servos + (red), Pico VSYS (pin 39) |
| 5 V supply − | both servos − (brown), Pico GND |

**Where they sit** (the owner's choice, 2026-10-23: the smallest footprint): both boards on a plate standing behind
the camera post, the Pi above with its GPIO header facing down, the Pico right under it. Low on the post - from its
foot to 112 mm - so their weight adds little to the camera's shake (the detector needs a still camera: to watch when
the stillness is measured again, see "The camera and the detector"). The jumper from the Pi's GPIO17 to the Pico is a
few centimetres; the servos reach the Pico through 50 cm extensions; the camera reaches the Pi with its own 200 mm
ribbon or its USB cable. The camera arm's clamp must stay above the plate (its lowest: the lens at ~115 mm above
the table, ~110 over the tray's floor; 156 is the default). The Pi has its own supply (a Pi 5:
the 27 W one); the servos and the Pico share the 5 V supply above.

Both boards work at 3.3 V on their pins: no level shifter. The station's settings (Settings > Cameras > This camera >
Card dropper): the pin (17), pulse 150 ms (the default; the Pico needs ≥ 8 ms), active low off.

What the firmware does, and why:
- **one pulse = one card**: both servos stroke together at the same angular speed (axle 2 stops at its 30 mm, axle 3
  goes on), both return to rest with the wheels standing, axle 3 strokes again, both go limp;
- **the pin is sampled every millisecond by a timer** (`Trigger`), also while the servos move, and a pulse counts once
  it has been active for 8 ms (noise on a long wire is not a card) - once per pulse, however long it lasts;
- **a pulse during a feed is KEPT and carried out right after it** (at most one). The station pulses as soon as the
  card just released has been captured - with auto-add on, as soon as its upload was answered - and that can come
  before the servos are back: the card is out and lying still before the last return ends. A first version dropped
  such a pulse, and the feeding stopped for good while the station counted the card as released (a Codex review of
  2026-10-23). A second request while one waits cannot come from the station (it asks only after the previous card's
  capture, and that card is the one being fed): it is counted (`Trigger.dropped`) and not carried out - a card too
  few stops the feeding, a card too many is two on the pile. Pinned by `tests/test_dropper_firmware.py` (a simulated
  Pico). The one thing the station can no longer take back: a stop made after a pulse went out is too late for that
  card - as for any mechanism already moving (`station/dropper.py` checks its gate before the pin goes active);
- **eased motion** (a cosine curve: no jolt at the start); the last stroke ends at speed so the card coasts on;
- **limp at rest** (`duty 0`): no hum, no jitter while the camera waits for the card to lie still;
- **the pin is watched from the first moment** (`boot()`: `start_watching()`, then the 1.5 s pause for the REPL, then
  `main()`; a Codex review of 2026-10-24 - it was watched only after the pause, so a Pico that reset while the station
  ran lost a pulse in it, and the station, which counted that card as released, waited for it for good). A pulse in the
  pause is fed once the servos are at rest; `tests/test_dropper_firmware.py` runs the file as `__main__` for it;
- **a pulse already on at power-up is not fed** (`Trigger.armed`: the trigger counts only after it has seen the line
  inactive; a second Codex review of 2026-10-24). Such a pulse belongs to a feed a reset cut off - a brown-out as both
  servos start, on the shared supply - and the one-way bearings kept the travel the card already got: a whole feed on
  top of it would turn axle 3 under the next card. An interrupted feed is never replayed: the card stops short in the
  gate, the station waits for its capture, and someone clears it and starts again - one card too few, the safe side.
  Never tried on a real Pico: whether a brown-out happens at all, and where the card stops then
- **at power-up both servos go to rest** - a jump at full speed, harmless: rest is the one-way bearings' free
  direction, so the wheels do not turn.

## Assembly and calibration (in this order)

How a servo drives its axle, step by step, drawn from the .scad: `hardware/dropper/assembly/dropper_drive_assembly.png`
(steps 1, 2 and 4 below, for one driven axle, and the drive cut along its axle).

1. Print `bearing_test` first and set `bearing_fit` from it (above). Press the 608 bearings into the block's housings (from outside), the HF0812s into the hubs (arrow: gripping when
   the card goes forward - check by hand first: a piece of rod in it turns freely one way and locks the other). Open
   each horn's hole 10 mm from its centre to 2 mm, on both arms (the horn's holes are ~1 mm, for pushrods); lay the
   horn, uncut, in its hub's pocket and drive two M2 x 6 self-tapping screws through those holes into the hub. **The horn's centre screw stays out**: once the horn is in the hub nothing can reach it (the hub's recess for
   its head is unused). Without it the hub can slide only 1 mm along its rod before it touches the bearing housing,
   so the horn cannot come off the servo's shaft - whether it grips the spline well enough is untested.
2. Slide the rods through the bearings, threading the wheels on inside the block (axle 2's at ±12 mm, the others' at
   ±24 mm from the centre line); O-rings on the wheels; tighten the grub screws on the filed flats. Each axle must turn
   freely by hand.
3. Plate on the block (6 x M3 self-tapping), its rails bare (ironed); chute and landing base on the block's front wall
   (2 x M3 + nuts each, reached from below); tray in the base, post in its socket, arm on the post.
4. Servos into the bracket **from inside** - the body goes out through the window, the tabs rest on the bracket's inner
   face (2 x M2 each). **Each hub onto its rod, horn facing out, BEFORE the bracket goes on**: with the bracket on,
   there are 19.6 mm between a servo's shaft and the bearing housing for the 19 mm hub, and the rod stands 12.5 mm
   into that gap (a correction of 2026-10-24, found by drawing the steps: this step first put the bracket on, then the
   hubs). Then the bracket with both servos up to the block's side, each shaft into its horn's centre hole (turn a hub
   by hand to line its horn up), and 6 x M3 from inside the block.
5. Load `main.py` on the Pico; in its REPL (Ctrl+C at start-up) `calibrate(3, 0)` / `calibrate(3, 90)`: find each
   servo's rest (`AXLE2_REST_US`, `AXLE3_REST_US`) and its microseconds per degree (`US_PER_DEG`, negative if that
   servo turns the card forward with shorter pulses). With a card on the wheels and a ruler beside it, the travel of a
   known turn gives `MM_PER_DEG`.
6. Gate gap (above); then single cards with "Drop one card", lengthening `TRAVEL_MM` for axle 3 a millimetre at a time
   only while card 2's back stays unmarked.
7. Camera: on the arm, lens down over the tray's centre; sideways if the image is rotated (PROGRAM_DOCUMENTATION,
   "Rotation": the card's long side along the frame's long side gives room for ~270 cards at the same height).

## Testing for damage - before anything else

The owner's concern, in the order of the contact table. On **commons and on sleeved cards first**; no foil and no
card of value until a row has passed.

1. **The tyres alone**: a junk card left under a loaded wheel for a day - does the silicone leave a mark?
2. **Feeding alone, no camera**: a marked set of 20 commons (a pencil dot on the back), 50 passes each (a loop of
   "Drop one card" and putting the tray back in the magazine). After 10 and 50: faces under a raking light and a
   loupe (scuffs), backs (the tyres, an overshooting axle 3), leading edges and corners (the gate, the far wall), and
   the bow of the card (bending at the table's end).
3. **The same with sleeves**, where the sleeve takes the wear: look at the sleeves too, and at the grip (sleeves are
   slipperier).
4. **Foils** (commons): foil curl is the case a bottom feeder handles worst - a bowed bottom card can lose its tyres or
   wedge under the gate. Measure how often, and whether it marks the foil's face.
5. **Doubles, misses and the finish** over 500 drops per card size: how often a card stops short under card 2, and
   what fixes it (below).
6. **The landing**: watch it slowly (a phone's slow-motion video): does a corner strike first, does the pile slide.

Write what was measured, with numbers, into this plan and PROGRAM_DOCUMENTATION - and keep "never tried" on whatever
was not.

## The camera and the detector

- **Auto-capture's thresholds were measured with cards dropped by hand** (CLAUDE.md, PROGRAM_DOCUMENTATION
  "Auto-capture"); a mechanism drops differently - more regularly, with servos moving. Re-measure the stillness wait
  on this rig before trusting it, and watch for the last return (it ends ~2.4 s after the pulse) shaking a card that
  is already lying still. The servos go limp after each feed for that reason.
- **Vibration**: the block and the base are bolted together for alignment, which also carries the servos' shake to
  the camera's post. Soft feet under both, and if it shows in the frames, replace the bolts between the base and the
  block by two loose pins.
- **The tray's colour**: the outline detector was measured on a white box (PROGRAM_DOCUMENTATION, "Card detection"
  step 4, `_card_inside_box`) and is known to miss **white-bordered cards on a white background** (Known
  limitations). A light matte tray is what was measured; a darker one may suit white-bordered cards and is untested.
  Matte either way: a glossy floor reflects the light into the camera.
- **Camera height**: 150 mm over the tray's floor by default (the USB webcam measured ~14.5 cm over the box floor; the
  Camera Module 3 Wide ran at ~19 cm); the arm slides on the post (z 100-225).

## Jams and failures

- **A card that does not come out** (a miss, or one stopped short under card 2) is never captured: the station
  releases nothing more and the page shows why it waits - the feeding stops, nothing breaks. "Drop one card" tries
  again.
- **If the finish by gravity is not reliable**, in this order, each measured before the next: PTFE tape (0.1 mm) on
  the plate's rails, which are bare at first (2026-10-30) - the card slides on them on its own weight, and an ironed
  print is still rougher than PTFE; it also answers marks the rails leave on the backs (damage test 2); a longer `TRAVEL_MM` for
  axle 3 by a millimetre at a time, watching card 2's back for marks; a shorter table (`table_end`); a light hinged
  flap resting on the card past the gate (gravity only, rolling or PTFE-faced - it touches the face); an infra-red
  sensor past the gate so axle 3 stops on the card's back edge rather than on a count.
- **A card wedged under the gate**: the tyres then slip on its back for the rest of the strokes - silicone rubbing a
  card held still, the one thing the design otherwise avoids. The firmware cannot feel it. If the tests show marks, a
  sensor past the gate (as above) can stop the feed when the card does not arrive.
- **Two cards out at once**: both land on the pile, the camera captures the top one, the other is under it - **lost to
  the scan**. That is why the doubles count in test 5 matters more than speed.

## What was checked, and what never was

Checked on 2026-10-22/23, with OpenSCAD 2021.01 (Flathub), FreeCAD 1.1.4 and Blender:
- every part renders without warnings, lies on the bed and fits 256 x 256 mm;
- no wheel, rod, bearing, hub, servo (a stand-in box), the bracket, the plate, the magazines or the landing parts
  overlap another part; the joints only touch;
- a card lying on the plane touches all six tyres; a card of either size, centred and 1 mm to either side, from its
  start to past the table, touches no part (168 positions); a card drooping 0.3 mm over the table meets only the
  rails' tops, never a face ahead of it; the SECOND card does meet the gate's lower edge at a gap of 1.5 x its
  thickness, for both sizes and off-centre;
- the conversion to FreeCAD (`hardware/dropper/freecad/to_freecad.sh`): every object one valid solid, the STEP files
  read back the same - which also caught two screw bosses standing 0.5 mm off a wall (loose pillars OpenSCAD rendered
  without a word);
- faults found and fixed on the way: the gate's guides caught a sleeved card lying against a side wall; the chute's ribs
  stood 0.2 mm above the card plane; the clutch hub (Ø 20) was smaller than the servo horn it holds (now Ø 30, the horn
  trimmed); the table's rails began with a square face in the card's path; the driven rods were drawn through the
  one-way bearing into the hub's web; grub-screw bosses against a wall; two of the plate's bosses in axle 2's path; the
  wheel's grub-screw boss, left at 16 mm when the rod went to 8 mm: its nut's slot broke out of the side and 0.9 mm was
  left to the bore (the owner saw the gap in the STL; now 22 mm, ~2 mm of wall all round the nut);
- the controller on a simulated Pico (`tests/test_dropper_firmware.py`): one feed per pulse, a pulse during a feed
  carried out once after it, a long pulse once, noise ignored.

**Printed, 2026-10-29** (the owner): the six `wheel`s with their O-rings. Checked by hand: the 8 mm rod slides
through a wheel, the grub screw's nut sits in its slot, the ring stays in its groove. The ring went on **without
stretching** - the printed groove is likely a little under its 45.5 mm, so the ~3% stretch the design counts on to
hold the tyre may not be there; it held in the hand test, but a tyre that creeps under load points here (`groove_d`).
The diameter with the ring is **still to measure** (`wheel_d`, `MM_PER_DEG`). Then `bearing_test`, with the owner's
608-2RS bearings: **22.05 mm is snug** - the bearing goes in and comes out by hand - so `bearing_fit` stays at 22.05
for the block. The `wheel_block` printed the same day (upright, as in the file): the six 608s press into its
housings and fit well; measured 86 mm high, as drawn. Still to see once the rods are in: that an outer ring does not
turn in its pocket with the rod spinning.

**2026-10-30: the first `wheel_plate` (3 mm, as drawn then) did not fit the wheels.** The wheels measured **50.5 mm**
across the tyres (two wheels), not the 51.4 drawn - why (the groove, the ring's section) was not measured. On the
block's axles (64.3 mm) their tops were at 89.55: 0.55 mm above the plate instead of 1, and the rails, drawn at the
wheels' 90, stood 0.45 mm above wheel 3 - a card laid there rested on the rails and not on that wheel. The block and
the wheels were kept and the card plane made to follow the wheels: in the .scad `axle_z` and `block_top` are now the
printed block's (fixed), `rail_z = axle_z + wheel_d / 2`, the plate 2.55 mm. Of the parts exported again, only the
plate and the chute changed (the chute's top follows the card plane; its bolts through the block, `chute_bolt_z`, do
not move); the block, the bracket, the hubs, the wheels, the gate, the tray, the landing base, the camera parts and
the Pi mount came out the same (their STL compared triangle by triangle); the magazines differ only in rounding.
The firmware's `MM_PER_DEG` follows (0.4407). The second plate: not printed yet.

**2026-10-30: the first `clutch_hub` (Ø 30, as drawn then) did not take the owner's MG90S horn**, which was not
trimmed to the 26 mm the plan asked. Measured: 31.28 mm tip to tip, a round centre of 6.7, arms 5.03 wide at the
root and 4.0 at the tips, 2.09 thick (1.6 drawn), holes of ~1 mm at 4, 6, 8 ... mm from the centre. The hub was
drawn again for the horn uncut: Ø 35, its pocket 2.49 deep (the hub 0.49 longer, the bracket's tab face 0.49 further
out), two M2 screws at 10 mm; the bracket's first leg notched around axle 2's hub (1 mm of room, its screws 14 mm
above and below the axle untouched). Checked in OpenSCAD: neither hub meets the bracket, the block, the other hub or
its rod, and 0.5 mm all round is clear of the bracket - the same check on the old bracket finds the overlap. Only
the hub and the bracket changed. The pocket is ONE polygon (`horn_outline`): FreeCAD's importer failed on a circle
and the arms together once their outlines crossed. The second hub: not printed yet; the bracket still has the
servo's body, tabs and shaft height as typical values, not measured.

**Never**: the other parts printed, the one-way bearings tried, assembled, calibrated, run on
a Pico, driven by the station, fed a card - so the grip, the slip, the stop's accuracy, the finish by gravity, the
timing, the landing and every row of the contact table are unmeasured. The servo's sizes (MG90S tabs, shaft height,
horn) are typical values: **measure the servo before printing the bracket and the hubs** (parameters at the top of
the .scad).

## Alternatives considered

- **A pusher**: a servo-driven sled with a printed rack and pinion caught only the bottom card's back edge and slid it
  out (designed 2026-10-22, dropped 2026-10-23 for the wheels - ~520 mm long, and a 0.2 mm pusher height to set by
  hand; never printed).
- **A suction cup lifting the top card** touches only one face, with no sliding at all - the gentlest, and what
  industrial sorters do. Left for later: a pump, a valve and a two-axis motion. If the face-on-face slide (the first
  row of the table) marks foils, this is the way out.
- **A roller with a retard pad** (a printer's paper feed): rubs the faces of the card fed and the card above. Out. (Not
  the same as these wheels: no wheel here ever turns against a card that is held still - except a jam.)
- **A solenoid off the pin**: no board in between, but the stroke is a slam of a few millimetres. Out.
- **Tilting the deck** so the card slides out on its own: it would also slide the bottom card before the pulse. Out.
