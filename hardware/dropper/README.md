# Card dropper (3D-printed)

A feeder that releases one card each time a Raspberry Pi station pulses its dropper pin
(`src/card_scanner/station/dropper.py`), with the landing tray and camera arm under it. The cards
lie face up in a magazine on six wheels with silicone O-ring tyres - three axles of two, in 608
bearings on 8 mm rods. The rear axle only rolls; the other two are each turned by a servo through a
one-way bearing, so a wheel never turns under a card it is not moving. Only the bottom card passes
under an adjustable gate; it tips onto a chute and slides on its back into the tray under the camera.
The station's Raspberry Pi 4/5 (the camera's computer) and the Pico that drives the servos stand on a
plate behind the camera post, low down, the Pico right under the Pi.

**Designed and checked in CAD; only the wheels and the wheel block printed (2026-10-29: rod, nut,
O-ring and bearings fit by hand), never assembled, never run, no card has gone through it.** Its
finish - the card's last millimetres under the next one, then down the ramp by gravity - is the open
question. The design, every number behind it, what to print and buy, how to set it up and how to
test it for card damage before trusting it with valuable cards:
[docs/plans/CARD_DROPPER_MECHANISM_PLAN.md](../../docs/plans/CARD_DROPPER_MECHANISM_PLAN.md).

| File | What it is |
|---|---|
| `card_dropper.scad` | Every printed part, parametric (OpenSCAD 2021.01 or newer). Card, servo, O-ring and camera sizes are parameters at the top: measure yours first. |
| `firmware/main.py` | MicroPython for a Raspberry Pi Pico: turns the station's pulse into one card's feed by the two servos. A pulse that comes during a feed is kept and carried out next; `tests/test_dropper_firmware.py` runs it on a simulated Pico. |
| `freecad/card_dropper.FCStd` | The same parts in FreeCAD (1.x), each a solid of its own, in its place (the unsleeved magazine set beside the other). Made from the .scad - see below. |
| `stl/*.stl` | The 15 parts to print (and `bearing_test`, a coupon), as STL for a slicer, each lying as it is printed (exported by the loop below; checked: closed meshes, on the bed, the same volumes as the STEP files). Print six `wheel`, two `clutch_hub` and two `rail`; the `wheel_plate` face down on a smooth bed. |
| `freecad/step/*.step` | The same 15 parts as STEP, for any CAD program or slicer. |
| `assembly/dropper_drive_assembly.png` | How a servo drives its 8 mm axle, in assembly order (six steps and the drive cut along its axle, labelled), rendered from the .scad. |
| `assembly/make_sheet.sh` | Draws it again: OpenSCAD exports each step's parts (`drive.scad`), Blender renders them (`render_steps.py`), Pillow lays out the sheet (`compose.py`, which holds its texts). Run it after a change to the .scad. |
| `freecad/to_freecad.sh` | Makes the two above from `card_dropper.scad` (OpenSCAD + `freecadcmd`); `conversion_report.json` is its check (one valid solid per object, the volumes). |

**The .scad is the source.** The FreeCAD file is a conversion: FreeCAD's OpenSCAD importer rebuilds
each part from the same boxes, cylinders, extrusions, unions and cuts, so its faces are real planes
and cylinders (not triangles) and the operations stay in the tree - but the named parameters
become plain numbers, and the colours are not set (the conversion runs without FreeCAD's window).
Inside a part, an object like `union001` is the importer's own step: FreeCAD's Cut takes one tool,
so everything cut out of a part (holes, slots) is first fused into one; a `polygon` is the flat outline
a shape was extruded from (a rail's side, the horn's arms, the chute's rib). The conversion moves
every OpenSCAD move and turn down onto the pieces themselves, so each object of the tree, shown on
its own, sits where it is in the part (the importer leaves them in their own coordinates - the
gate's boxes appeared at the magazine's rear wall); `to_freecad.py` checks that no part changed. Change a size in the .scad
and run `freecad/to_freecad.sh` again; a change made only in FreeCAD is lost at the next conversion.

Exporting the parts as STL:

```bash
# OpenSCAD 2021.01 or newer, the distribution's package (openscad)
for p in bearing_test wheel_block wheel_plate rail wheel clutch_hub servo_bracket magazine_sleeved magazine_unsleeved \
         gate chute tray landing_base camera_post camera_arm pi_mount; do
  openscad -D "part=\"$p\"" -o "stl/$p.stl" card_dropper.scad
done
```

Print six `wheel`, two `clutch_hub` and two `rail`. The `wheel_plate` and the rails lie face down in their files:
print them so on a smooth bed - the face the cards slide over comes out as smooth as the bed. Before the `wheel_block`, print `bearing_test` (`stl/bearing_test.stl`,
90 x 21 x 30, standing as in the file): three pieces of its side wall with the 608's pocket at 22.05,
22.20 and 22.35 mm, the size written on top. The pocket that takes a bearing by hand pressure and holds it still is
`bearing_fit` for the block - set it, then export the block. `part = "assembly"` shows everything in place, a card on
its way out.

Own design. Ideas taken from the Card Slinger 3.0 (a funnel that centres the card under the
camera, a removable tray, a stand above it) - none of its geometry.
