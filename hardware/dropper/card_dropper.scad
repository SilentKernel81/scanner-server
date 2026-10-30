// Card dropper for the card scanner: a 3D-printed feeder that releases one card per pulse of
// the station's GPIO pin (station/dropper.py), plus the landing tray and camera arm under it.
//
// Design notes, the numbers behind every dimension, the damage tests and what was never tried:
// docs/plans/CARD_DROPPER_MECHANISM_PLAN.md. The short version:
//   - the cards lie face up in a magazine without a floor, on six wheels - two on each of three
//     axles - whose silicone O-ring tyres make the plane the cards lie on;
//   - axle 1 (rear) only rolls; axles 2 and 3 are each turned by their own servo through a
//     ONE-WAY BEARING: the servo's forward stroke turns the wheels, its return leaves them
//     standing, and a card pulled forward by the other axle turns them freely instead of sliding
//     over them. Axle 2 stops early, long before card 1's back edge reaches it; axle 3, just
//     behind the gate, carries the card until it has nearly left the stack. A wheel that stops
//     while card 1 still covers it never turns under card 2;
//   - only the bottom card passes under an adjustable gate (its gap set with a feeler gauge, never
//     printed to size); it leaves on a short table, tips onto a chute and slides, on its back,
//     into a tray under the camera. The face of a card touches only the back of the card above it.
//
// Only the wheels and the wheel block printed (2026-10-29), never assembled, never run. Checked in OpenSCAD (collisions, a card's path) and converted to
// FreeCAD (freecad/to_freecad.sh) - see the plan.
//
// Axes: x = the direction the card travels (toward the tray), y = across, z = up from the table.
// x = 0 is the inner face of the sleeved magazine's rear wall; y = 0 the feeder's centre line.
//
// Use: open in OpenSCAD, choose `part` (Customizer), F6, export STL. Or from a shell:
//   openscad -D 'part="wheel"' -o wheel.stl card_dropper.scad

part = "assembly"; // [assembly, bearing_test, wheel_block, wheel_plate, rail, wheel, clutch_hub, servo_bracket, magazine_sleeved, magazine_unsleeved, gate, chute, tray, landing_base, camera_post, camera_arm, pi_mount]

/* [Cards - measure yours with calipers] */
sleeved_l = 92;        // a sleeved card's length (standard sleeves: 91-92)
sleeved_w = 67;        // ... and width (66-67)
unsleeved_l = 88;      // a Magic card: 88 x 63
unsleeved_w = 63;
card_clear = 2;        // the magazine is this much longer and wider than the card

/* [Feeder] */
// The printed wheel block fixes these two (2026-10-29): it was drawn for a 51.4 mm wheel under a card
// plane at 90 mm. The card plane now follows the wheels as measured (rail_z, below), so a change of
// wheel_d moves the plate, the magazines, the gate and the chute - never the block or the bracket.
axle_z = 90 - 51.4 / 2;   // 64.3: the axles' height in the block, above the table
block_top = 86;        // the block's walls end here, the plate lies on them (measured on the print: 86)
rail_w = 4;            // the table's two rails (past the gate): bars of their own, in grooves in the plate
rail_h = 1;            // how far the card plane is above the plate
rail_drop = 0.2;       // the rails' tops this much UNDER the card plane (and a rail 2.0 mm tall: whole 0.2 layers): a rail above the wheels lifts a card
                       // off axle 3's wheels; one a little under them only lets it droop (sand a bar's
                       // underside to lower it, a strip of tape under it to raise it - never its top)
rail_groove = 1.2;     // the rails' grooves in the plate: this deep ...
rail_fit = 0.6;        // ... and this much wider than a rail (0.3 a side: the first layer's squish narrows
                       // the groove's mouth and widens the rail's top, both on the bed)
skirt_d = 1;           // the magazine's side walls (and the outer 3 mm of its rear wall) go on down this far,
                       // into a channel in the plate: that locates the magazine
skirt_fit = 0.3;       // the channel's room round them, a side (the squish again)
rear_lip = 3;          // the rear wall's lip: its outer 3 mm (the sleeved magazine's whole rear wall)
mag_wall = 3;          // the sleeved magazine's walls (the unsleeved one's are thicker inside)
mag_h = 46;            // the magazine's height above the plate: ~45 mm of cards
window_h = 1.5;        // the front wall's bottom edge above the card plane (the gate closes the rest)
table_end = 130;       // where the table after the gate ends and the chute begins: behind the card's
                       // centre when axle 3 stops, so the card tips (see the plan) - TO TUNE
plate_half_w = 46;     // the plate on the wheel block

/* [Wheels - the O-rings and the axles] */
ring_id = 44;          // the tyre: a silicone O-ring 50 x 44 x 3 mm (uxcell, 10 pack)
ring_cs = 3;           // its thickness
groove_d = 45.5;       // the groove's bottom: the ring stretched ~3% so it stays put
wheel_d = 50.5;        // the wheel with its ring on, MEASURED on the printed wheels (2026-10-30; drawn as
                       // 51.4: the groove + 2 x a ring stretched ~3%). It sets the card plane (rail_z) and
                       // mm per degree in the firmware (MM_PER_DEG): all six wheels are alike
wheel_w = 8;           // a wheel's width: flange, groove, flange
flange_d = 48;         // the flanges stay under the ring: only silicone touches a card
wheel_boss_d = 22;     // the boss of the grub screw: ~2 mm of wall around its nut on every side (at 16 mm,
                       // after the rod went from 6 to 8 mm, the nut's slot broke out of the boss's side)
nut_af = 5.5;          // an M3 nut across its flats ...
nut_t = 2.4;           // ... and its thickness
rod_d = 8;             // the axles: 8 mm smooth steel rod (silver steel) - the one-way bearings run on it
bearing_od = 22;       // each axle turns in two 608-2RS ball bearings (8 x 22 x 7), one in each side wall
bearing_w = 7;
bearing_fit = 22.05;   // their pocket: a light press fit - tried with part="bearing_test" (2026-10-29: snug,
                       // in and out by hand); TO TUNE again on another printer
axle_x = [12, 50, 95]; // axle 1 (idle, at the back), axle 2 (driven, starts the card), axle 3 (driven,
                       // just behind the gate: card 1 covers it until it has nearly left the stack)
axle_wheel_y = [24, 12, 24];   // each axle's two wheels at +-y; axle 2's sit inside the others' so the
                       // wheels of axles 2 and 3 can overlap along x without meeting
block_x0 = -20;        // the wheel block: from here ...
block_half_w = 40;     // ... and this wide (outer), side walls 4 mm
clutch_od = 12;        // HF0812 one-way bearing (drawn cup roller clutch): 8 bore, 12 OD, 12 long
clutch_l = 12;
clutch_fit = 11.95;    // its bore in the printed hub: a press fit - TO TUNE on your printer
hub_d = 35;            // the clutch hub: wide enough for the horn uncut (~1.5 mm of wall past its tips); the
                       // servo bracket's first leg is notched for it (it was 30, for a horn trimmed to 26 mm)

/* [Servo (MG90S) - measure yours] */
servo_body_l = 22.8;
servo_body_w = 12.2;
servo_shaft_offset = 5.5;   // from the body's centre to the shaft, along the body's length
servo_hole_spacing = 27.8;  // between the two mounting holes
servo_tab_t = 2.5;
shaft_above_tab = 11;       // from the top of the mounting tabs to the top of the output spline
// the double-arm horn that comes with it, MEASURED on the owner's MG90S (2026-10-30):
horn_len = 31.28;           // tip to tip - used uncut
horn_hub_d = 6.7;           // the round centre
horn_root_w = 5.03;         // an arm's width next to the centre ...
horn_tip_w = 4.0;           // ... and at its tip
horn_t = 2.09;              // its thickness
horn_screw_r = 10;          // the hole each of the hub's two screws goes through: the horn's holes are ~1 mm
                            // (for pushrods), 4, 6, 8 ... mm from the centre - this one is opened to 2 mm

/* [Pi mount: the station's Raspberry Pi and the servos' Pico, on the camera post] */
pi_holes = [58, 49];   // Raspberry Pi 4 and 5 alike: board 85 x 56, M2.5 holes 3.5 mm in from the edges
pi_board = [85, 56];
pi_stand = 5;          // its standoffs (the underside of a Pi 4 / 5 has nothing taller)
pi_height = 20;        // the board's parts above it, an Active Cooler included
pico_holes = [47, 11.4];   // Raspberry Pi Pico: board 51 x 21, M2 holes (2.1 mm)
pico_board = [51, 21];
pico_stand = 4;

/* [Landing tray and camera] */
chute_deg = 30;        // the chute's slope
chute_exit_z = 62;     // the chute's lower end: above the tray's full pile
tray_x0 = 181;         // the tray's inner near wall
tray_depth = 45;       // = the magazine's height: one load fills one tray
camera_z = 156;        // the camera's lens above the table (~150 mm above the tray floor, like the
                       // USB webcam's measured ~14.5 cm; a Pi Camera Module 3 Wide was at ~19 cm)

$fn = 48;
eps = 0.01;

// ---------------------------------------------------------------------------------------
// Values worked out from the parameters
// ---------------------------------------------------------------------------------------
rail_z = axle_z + wheel_d / 2;                   // 89.55: the card plane - the wheels' tops and the table's rails
gate_x = sleeved_l + card_clear;                 // 94: the magazine's front inner face
mag_in_w = sleeved_w + card_clear;               // 69
mag_y = mag_in_w / 2 + mag_wall;                 // 37.5: the magazine's outer half-width
mag_x0 = -mag_wall;                              // -3
mag_x1 = gate_x + mag_wall;                      // 97
plate_top = rail_z - rail_h;                     // 88.55: the plate's top, the magazine stands here
gate_gap_nominal = 0.6;                          // only for the assembly view: set it with a gauge
gate_t = 6;
gate_half_w = mag_in_w / 2 + 0.5;                // 35: the gate is wider than the sleeved magazine's inside
ledge_z = plate_top + mag_h;                     // the magazine's top
tray_in_l = sleeved_l + 5;                       // 97
tray_in_w = sleeved_w + 5;                       // 72
tray_wall = 2.4;
base_t = 4;
tray_floor = base_t + 2;                         // the tray's floor: the pile starts here
post_x = tray_x0 + tray_in_l + tray_wall + 20;   // the camera post, past the tray's far wall
post_s = 20;
post_h = 230;
// the Pi mount: a plate behind the post (away from the tray), on two sleeves around it
pm_sleeve = post_s + 0.6;                        // the sleeves' inside: they slide down over the post
pm_x0 = post_x + pm_sleeve / 2 + 3;              // the plate's back face, on the sleeves' outer face
pm_t = 3;
pm_half_w = 45;                                  // the plate's half-width (the Pi is 85 wide)
pm_z0 = base_t + 12;                             // it stands on the post's socket ...
pm_z1 = pm_z0 + 96;                              // ... and ends here: the camera arm's clamp stays above
pico_z0 = pm_z0 + 8;                             // the Pico's lower edge
pi_z1 = pm_z1 - 4;                               // the Pi's upper edge (its HDMI side; the GPIO header faces down)
base_x1 = pm_x0 + pm_t + pi_stand + 1.6 + pi_height + 2;   // where the landing base ends: the Pi stands on it
// the Pi's holes on the plate, as (y, z): the board turned so that its GPIO header is at the bottom,
// next to the Pico, and its USB / Ethernet end at -y
pi_holes_yz = [for (bx = [3.5, 3.5 + pi_holes[0]]) for (by = [3.5, 3.5 + pi_holes[1]]) [pi_board[0] / 2 - bx, pi_z1 - by]];
pico_holes_yz = [for (dy = [-1, 1]) for (bz = [4.8, 4.8 + pico_holes[1]]) [dy * pico_holes[0] / 2, pico_z0 + bz]];

plate_t = plate_top - block_top;                 // 2.55: the plate under the stack, 1 mm under the wheel tops
                                                 // (3 with the 51.4 mm wheel it was drawn for)
block_wall = 4;
chute_bolt_z = 80;                               // the chute's two bolts through the block's front wall: in the
                                                 // printed block, so fixed (10 mm under the card plane drawn)
housing_t = bearing_w + 2;                       // the side walls are this thick where a bearing sits:
housing_out = housing_t - block_wall;            // its pocket from outside, a 2 mm lip inside
horn_recess = horn_t + 0.4;                      // the horn's pocket in a clutch hub
hub_gap = 1;                                     // between a bearing housing and a clutch hub
hub_l = horn_recess + 3 + 2 + clutch_l;          // horn pocket, the horn screw's head, a web, the clutch
hub_y1 = -block_half_w - housing_out - hub_gap;  // the hub's face toward the block
hub_y0 = hub_y1 - hub_l;                         // ... and toward the servo (the horn sits in it)
servo_tab_face = hub_y0 + horn_recess - horn_t - shaft_above_tab - servo_tab_t;   // where the tabs rest
bracket_t = 3;
// the slot each wheel pokes through: the wheel's chord at the plate's underside, plus room
slot_half_l = sqrt(pow(wheel_d / 2, 2) - pow(wheel_d / 2 - (rail_z - block_top), 2)) + 1.5;
// the plate's screws into the block: the middle pair clear of axle 2's rod and axle 3's wheels, and
// merged into the side walls (0.5 mm off the wall, they were loose pillars - FreeCAD counted them)
block_bosses = [[-15, 31], [-15, -31], [table_end - 5, 31], [table_end - 5, -31], [62, 33], [62, -33]];
bracket_legs = [31, 72.5, 118];                  // the servo bracket's legs: in the gaps between the bearing housings

// the rods: the idle one from housing face to housing face; a driven one on through the clutch hub,
// ending 0.5 mm short of the clutch's far end (beyond it are the hub's web and the horn's screw)
function rod_length(i) = 2 * (block_half_w + housing_out) + (i == 0 ? 0 : hub_gap + clutch_l - 0.5);

echo(str("Axles at z ", axle_z, ", ", PI * wheel_d / 360, " mm of card per degree of wheel; rods ",
         rod_length(0), " and 2 x ", rod_length(1), " mm"));

// A box whose top is a different rectangle from its bottom (the tray's funnel). b and t are
// [x0, x1, y0, y1, z] of the bottom and the top face. (A polyhedron, not hull(): FreeCAD's
// OpenSCAD importer fails on hull.)
module frustum(b, t) {
    polyhedron(points = [[b[0], b[2], b[4]], [b[1], b[2], b[4]], [b[1], b[3], b[4]], [b[0], b[3], b[4]],
                         [t[0], t[2], t[4]], [t[1], t[2], t[4]], [t[1], t[3], t[4]], [t[0], t[3], t[4]]],
               faces = [[0, 1, 2, 3], [4, 7, 6, 5], [0, 4, 5, 1], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]]);
}

// ---------------------------------------------------------------------------------------
// The feeder
// ---------------------------------------------------------------------------------------

// One wheel: a hub with a groove for the O-ring between two flanges, and a boss with an M3 grub
// screw that fixes it to its rod. All six are this part. Print flat, boss up.
module wheel() {
    difference() {
        union() {
            cylinder(d = flange_d, h = wheel_w);
            translate([0, 0, wheel_w - eps]) cylinder(d = wheel_boss_d, h = 7);   // the grub screw's boss
        }
        // the groove: as wide as the ring, its bottom at groove_d
        translate([0, 0, (wheel_w - ring_cs - 0.2) / 2]) difference() {
            cylinder(d = flange_d + 1, h = ring_cs + 0.2);
            translate([0, 0, -1]) cylinder(d = groove_d, h = ring_cs + 2.2);
        }
        translate([0, 0, -1]) cylinder(d = rod_d + 0.2, h = wheel_w + 9);   // the rod
        // M3 grub screw through the boss, its nut dropped into a slot that is open only at the boss's
        // top face: halfway between the rod's bore and the boss's outside, ~2 mm of wall each side
        translate([0, 0, wheel_w + 3.5]) rotate([0, 90, 0]) cylinder(d = 3.2, h = wheel_boss_d / 2 + 1);
        nut_x = (rod_d / 2 + 0.1 + wheel_boss_d / 2) / 2 - (nut_t + 0.2) / 2;
        translate([nut_x, -(nut_af + 0.3) / 2, wheel_w + 0.3]) cube([nut_t + 0.2, nut_af + 0.3, 10]);
        // lighten
        // lighten: six holes between the boss (r 11) and the groove (r 22.75), ~1.5-2 mm from each
        for (k = [0 : 5]) rotate(k * 60) translate([16.75, 0, -1]) cylinder(d = 8, h = wheel_w + 2);
    }
}

// The clutch hub: joins the servo's horn to an axle through a one-way bearing pressed into it.
// Mind the bearing's arrow: it must grip when the servo turns the card FORWARD. Print standing
// on the horn's side. File a flat on the rod where the wheels' grub screws bear.
module clutch_hub() {
    difference() {
        cylinder(d = hub_d, h = hub_l);
        // the horn, uncut, in a pocket on one face (its outline: horn_outline, 0.2 mm of room all round)
        translate([0, 0, -eps]) linear_extrude(horn_recess) polygon(horn_outline(0.2));
        translate([0, 0, horn_recess - eps]) cylinder(d = 5.5, h = 3);       // the horn screw's head
        for (s = [-1, 1]) translate([s * horn_screw_r, 0, -1]) cylinder(d = 1.8, h = horn_recess + 6);   // M2 self-tapping, through the horn's holes
        translate([0, 0, hub_l - clutch_l]) cylinder(d = clutch_fit, h = clutch_l + 1);   // the one-way bearing
    }
}

// The servo horn seen from above, grown by c all round, as ONE polygon: the two arms, tapering from
// their root to square ends (a round tip and a square one both fit), joined by the arcs of the round
// centre where it stands out past them. One polygon and not a circle and a polygon together:
// FreeCAD's importer fails on the union of the two when their outlines cross ("Null input shape").
function horn_outline(c) = let(
    L = horn_len / 2 + c,                  // the tips
    rt = horn_tip_w / 2 + c,               // half an arm at its tip ...
    rr = horn_root_w / 2 + c,              // ... and at its root (the centre line of the horn)
    rh = horn_hub_d / 2 + c,               // the round centre
    k = (rr - rt) / L,                     // how fast an arm narrows: its edge is y = rr - k |x|
    // where an arm's edge meets the round centre: x^2 + (rr - k x)^2 = rh^2
    x0 = (rr * k + sqrt(pow(rr * k, 2) - (1 + k * k) * (rr * rr - rh * rh))) / (1 + k * k),
    a0 = atan2(rr - k * x0, x0),           // ... at this angle
    n = 12,                                // points on each arc
    arc = function(f, t) [for (i = [0 : n]) rh * [cos(f + (t - f) * i / n), sin(f + (t - f) * i / n)]]
) concat([[-L, -rt]], arc(180 + a0, 360 - a0), [[L, -rt], [L, rt]], arc(a0, 180 - a0), [[-L, rt]]);

// What is cut out of a side wall for one 608 bearing, along +z: z = 0 is the wall's inner face,
// z = housing_t its outer face. The pocket goes in from outside, bearing_w deep; the 2 mm left
// is the lip that holds the bearing, with a hole wider than its inner ring. One module for the
// block and for its test coupon, so the coupon tries exactly the block's pocket.
module bearing_pocket(fit) {
    translate([0, 0, housing_t - bearing_w]) cylinder(d = fit, h = bearing_w + 1);   // the bearing
    translate([0, 0, -1]) cylinder(d = 16, h = block_wall + 2);                      // the lip's hole
}

// A test coupon for the bearings' fit, before the block's long print: a piece of side wall with
// one pocket per tried size, standing as the block stands (the pockets' axes level, so their
// tops are the same overhang as in the block - a hole printed lying down would come out rounder
// and give the wrong size). Each 30 mm piece is one housing rib's width; the size is written on
// top. Press a 608 into each: the one that goes in by hand pressure and does not turn in its
// pocket is the bearing_fit for the block.
bearing_test_fits = [22.05, 22.20, 22.35];
module bearing_test() {
    pitch = 30;                        // one housing rib's width
    h = 30;                            // the pocket's centre 15 mm up: ~4 mm of wall above and below
    n = len(bearing_test_fits);
    difference() {
        union() {
            cube([n * pitch, housing_t, h]);
            translate([0, -6, 0]) cube([n * pitch, housing_t + 12, 2]);   // a foot: it stands 9 mm thin
        }
        for (i = [0 : n - 1]) {
            // the pocket from the +y face (outside), the lip toward -y (inside), as in the block
            translate([(i + 0.5) * pitch, 0, h / 2]) rotate([-90, 0, 0]) bearing_pocket(bearing_test_fits[i]);
            translate([(i + 0.5) * pitch, housing_t / 2, h - 0.6])
                linear_extrude(1) text(str(bearing_test_fits[i]), size = 3.5, halign = "center", valign = "center");
        }
    }
}

// The wheel block: walls only, open at the bottom. Each rod turns in two 608 bearings pressed
// into housings on the side walls from outside (a 2 mm lip inside holds them; its hole is wider
// than the bearing's inner ring, so only the outer ring touches it). Print upright.
module wheel_block() {
    w = block_wall;
    x1 = table_end;
    difference() {
        union() {
            difference() {
                translate([block_x0, -block_half_w, 0]) cube([x1 - block_x0, 2 * block_half_w, block_top]);
                translate([block_x0 + 3, -block_half_w + w, -1]) cube([x1 - block_x0 - 6, 2 * (block_half_w - w), block_top + 2]);
            }
            for (b = block_bosses) translate([b[0], b[1], 0]) cylinder(d = 7, h = block_top);
            // the bearing housings: ribs from the table up, outside the side walls (no overhang)
            for (x = axle_x) for (s = [-1, 1])
                translate([x - 15, s > 0 ? block_half_w - eps : -block_half_w - housing_out, 0])
                    cube([30, housing_out + eps, axle_z + 15]);
        }
        for (x = axle_x) for (s = [-1, 1]) translate([x, 0, axle_z]) rotate([s > 0 ? -90 : 90, 0, 0])
            translate([0, 0, block_half_w - block_wall]) bearing_pocket(bearing_fit);
        for (b = block_bosses) translate([b[0], b[1], block_top - 15]) cylinder(d = 2.8, h = 16);
        // the servo bracket's screws (M3 from inside, into its legs)
        for (x = bracket_legs) for (z = [axle_z - 14, axle_z + 14])
            translate([x, -block_half_w - 1, z]) rotate([-90, 0, 0]) cylinder(d = 3.4, h = w + 2);
        // the chute and the landing base bolt to the front wall (M3 + nut, reached from below)
        for (y = [-25, 25]) translate([x1 - 4, y, chute_bolt_z]) rotate([0, 90, 0]) cylinder(d = 3.4, h = 6);
        for (y = [-15, 15]) translate([x1 - 4, y, 14]) rotate([0, 90, 0]) cylinder(d = 3.4, h = 6);
    }
}

// The rails' y, and where a rail's 45 degree ramp starts and ends: the rails begin under the front
// wall (they pass under the gate's blade), rising from the plate to their top at the front inner face.
rails_y = [-10, 10];
rail_top = rail_z - rail_drop;
rail_x0 = gate_x;                                // the ramp's top end
rail_xs = rail_x0 - (rail_top - plate_top);      // the ramp's foot, on the plate

// One rail (2 of them), in place on y = 0: a bar standing in its groove, its top just under the card
// plane, a 45 degree ramp at its start. Print it on its top - the face the card slides on comes out as
// smooth as the bed.
module rail() rotate([90, 0, 0]) linear_extrude(rail_w, center = true)
    polygon([[rail_xs, plate_top - rail_groove], [table_end, plate_top - rail_groove], [table_end, rail_top],
             [rail_x0, rail_top], [rail_xs, plate_top]]);
module placed_rail(s) translate([0, rails_y[(s + 1) / 2], 0]) rail();   // s = -1, 1

// The magazine's lip, seen from above, grown by c: each side wall's whole thickness (the unsleeved one's
// is thicker inside - a lip of only its outer part would leave the rest hanging 1 mm over the bed) and
// the gate's guides, and the rear wall's outer 3 mm (as thick as the sleeved one's: the unsleeved one's
// rear wall reaches over axle 1's wheels, which its lip would meet). The side lips' two ends hold the
// magazine along x, their outer faces across. A gap at x = 62 for the plate's two countersunk screws
// there (their heads reach |y| = 36.2): a 9 mm bridge in the print.
skirt_gaps = [62];
module skirt_outline(sleeved, c) {
    wi = ((sleeved ? sleeved_w : unsleeved_w) + card_clear) / 2;      // the side walls' inner face
    gy = gate_half_w + 0.3;                                             // the gate's guides' inner face
    difference() {
        union() {
            for (s = [-1, 1]) {
                translate([mag_x0 - c, s > 0 ? wi - c : -mag_y - c]) square([mag_x1 - mag_x0 + 2 * c, mag_y - wi + 2 * c]);
                translate([mag_x1 - c, s > 0 ? gy - c : -mag_y - c]) square([gate_t + 2 + 2 * c, mag_y - gy + 2 * c]);
            }
            translate([mag_x0 - c, -mag_y - c]) square([rear_lip + 2 * c, 2 * (mag_y + c)]);
        }
        for (x = skirt_gaps) translate([x - 4.5 + c, -100]) square([9 - 2 * c, 200]);
    }
}
// The plate's channel: both magazines' lips with room round them, and room under the unsleeved one's
// thicker rear wall too (it overhangs its lip by 4 mm in the print: if it droops, it droops into this).
// Drawn as three pieces that do not touch - the rear U and the two front pieces past the gap at x = 62 -
// each one polygon extruded on its own: FreeCAD's importer fails on unions of several 2D shapes, and
// drops a polygon of several outlines. h: how deep.
module skirt_channel(h) {
    f = skirt_fit;
    x0 = mag_x0 - f;                                         // the rear lip's outer face
    xr = gate_x - unsleeved_l - card_clear + f;              // the unsleeved rear wall's inner face
    xs = mag_x1 + f;                                         // the side walls' front ...
    xg = mag_x1 + gate_t + 2 + f;                            // ... and the gate's guides' front
    yo = mag_y + f;                                          // the outer faces
    yi = (unsleeved_w + card_clear) / 2 - f;                 // the unsleeved side walls' inner faces
    yg = gate_half_w + 0.3 - f;                              // the guides' inner faces
    g0 = skirt_gaps[0] - 4.5 + f;                            // the gap
    g1 = skirt_gaps[0] + 4.5 - f;
    pts = [[x0, -yo], [g0, -yo], [g0, -yi], [xr, -yi], [xr, yi], [g0, yi], [g0, yo], [x0, yo],          // 0-7
           [g1, -yo], [xg, -yo], [xg, -yg], [xs, -yg], [xs, -yi], [g1, -yi],                             // 8-13
           [g1, yi], [xs, yi], [xs, yg], [xg, yg], [xg, yo], [g1, yo]];                                  // 14-19
    for (path = [[0, 1, 2, 3, 4, 5, 6, 7], [8, 9, 10, 11, 12, 13], [14, 15, 16, 17, 18, 19]])
        linear_extrude(h) polygon([for (i = path) pts[i]]);
}

// The plate on the block: under the stack it lies 1 mm below the wheel tops (a safety floor - the
// cards lie on the wheels), with a slot for each wheel; from the gate on, two rails (parts of their
// own, in grooves) carry the card to the table's end. The magazine's lip drops into a channel in it.
// Print it FACE DOWN on a smooth bed: the face the cards pass over comes out as smooth as the bed,
// and everything on that face is cut into it (the grooves, the channel, the screws' countersinks), so
// nothing needs support. Its six M3 screws are COUNTERSUNK, flush: a pan head stood ~2 mm above the
// plate, where the cards pass 1 mm above it.
module wheel_plate() {
    x0 = block_x0;
    x1 = table_end;
    difference() {
        translate([x0, -plate_half_w, block_top]) cube([x1 - x0, 2 * plate_half_w, plate_t]);
        // the rails' grooves: open at the table's end, closed just before the ramp's foot
        for (y = rails_y) translate([rail_xs - rail_fit, y - (rail_w + rail_fit) / 2, plate_top - rail_groove])
            cube([x1 - rail_xs + rail_fit + 1, rail_w + rail_fit, rail_groove + 1]);
        // the magazine's channel: 0.2 mm of room round its lip, 0.2 mm deeper than it
        // as deep as the lip is long: the magazine stands on its lip all round, not on the two pads at x = 62 alone
        translate([0, 0, plate_top - skirt_d]) skirt_channel(skirt_d + 1);
        for (i = [0 : 2]) for (s = [-1, 1]) {
            translate([axle_x[i] - slot_half_l, s * axle_wheel_y[i] - wheel_w / 2 - 1, block_top - 1]) cube([2 * slot_half_l, wheel_w + 2, plate_t + 3]);
            // the slot's far edge chamfered: a card drooping into it slides out of it, never against an edge
            translate([axle_x[i] + slot_half_l, s * axle_wheel_y[i], plate_top]) rotate([0, 45, 0]) cube([2, wheel_w + 2, 2], center = true);
        }
        for (b = block_bosses) translate([b[0], b[1], 0]) {
            translate([0, 0, block_top - 1]) cylinder(d = 3.4, h = plate_t + 2);
            // the countersink: a flat-head M3 (90 degrees, head 6 mm) sits flush with the plate's face
            translate([0, 0, plate_top - 1.5]) cylinder(d1 = 3.4, d2 = 6.4, h = 1.5 + eps);
        }
    }
}

// The bracket that holds both servos beside the block, each coaxial with its axle (axles 2 and 3),
// body hanging outside. Print lying on its mounting plate.
module servo_bracket() {
    xs = [axle_x[1], axle_x[2]];
    y1 = servo_tab_face;                         // the plate's face the servo tabs rest on
    z0 = axle_z - 22;
    z1 = axle_z + 22;
    difference() {
        union() {
            translate([bracket_legs[0] - 3, y1 - bracket_t, z0]) cube([bracket_legs[2] - bracket_legs[0] + 6, bracket_t, z1 - z0]);
            // three legs back to the block's wall, between the hubs
            for (x = bracket_legs) translate([x - 3, y1 - eps, axle_z - 20]) cube([6, -block_half_w - y1 + eps, 40]);
        }
        for (x = xs) {
            // the servo body through the plate, its shaft (at one end of its long side) on the axle
            translate([x - servo_body_w / 2 - 0.3, y1 - bracket_t - 1, axle_z - servo_shaft_offset - servo_body_l / 2 - 0.3])
                cube([servo_body_w + 0.6, bracket_t + 2, servo_body_l + 0.6]);
            for (s = [-1, 1]) translate([x, y1 - bracket_t - 1, axle_z - servo_shaft_offset + s * servo_hole_spacing / 2]) rotate([-90, 0, 0]) cylinder(d = 1.8, h = bracket_t + 2);
        }
        for (x = bracket_legs) for (z = [axle_z - 14, axle_z + 14])
            translate([x, -block_half_w - 15, z]) rotate([-90, 0, 0]) cylinder(d = 2.8, h = 16);
        // room for the hubs to turn, 1 mm all round: only the first leg reaches into it (axle 2's hub), and
        // only around the axle's height - its screws, 14 mm above and below, stay whole
        for (x = xs) translate([x, hub_y0 - 1, axle_z]) rotate([-90, 0, 0]) cylinder(r = hub_d / 2 + 1, h = hub_l + 2);
    }
}

// The magazine: walls only, no floor - the cards lie on the wheels. Both sizes have the same
// outside, and the same front inner face (x = gate_x); the unsleeved one's rear and side walls
// are thicker inside. Print upright.
module magazine(sleeved = true) {
    in_l = (sleeved ? sleeved_l : unsleeved_l) + card_clear;
    in_w = (sleeved ? sleeved_w : unsleeved_w) + card_clear;
    in_x0 = gate_x - in_l;
    z0 = plate_top;
    z1 = plate_top + mag_h;
    difference() {
        union() {
            translate([mag_x0, -mag_y, z0]) cube([mag_x1 - mag_x0, 2 * mag_y, mag_h]);
            // the lip under the walls, into the plate's channel (the side walls carried on down whole,
            // so they print without support; see skirt_outline for the rear wall)
            translate([0, 0, z0 - skirt_d]) linear_extrude(skirt_d + eps) skirt_outline(sleeved, 0);
            // the gate's guides: two strips on the front face, outside the magazine's inside width
            // (a sleeved card lying against a side wall reaches |y| = 34.5 and must pass them), with
            // lips over the gate's edges that stop above the card's way out
            for (s = [-1, 1]) {
                translate([mag_x1, s > 0 ? gate_half_w + 0.3 : -mag_y, z0]) cube([gate_t + 2, mag_y - gate_half_w - 0.3, mag_h]);
                translate([mag_x1 + gate_t + 0.5, s > 0 ? gate_half_w - 2 : -mag_y, rail_z + 4]) cube([1.5, mag_y - gate_half_w + 2, z1 - rail_z - 4]);
            }
            // the ledge the gate's adjusting screw hangs from: a bridge from one guide to the
            // other. The gate goes in from below, before the magazine is set on the plate.
            translate([gate_x, -mag_y, z1 - 4]) cube([mag_x1 - gate_x + gate_t + 2, 2 * mag_y, 4]);
        }
        // the inside, open at the top
        translate([in_x0, -in_w / 2, z0 - 1]) cube([in_l, in_w, mag_h + 2]);
        // the front wall's window: from the plate up to window_h over the card plane, the full inside width
        translate([gate_x - 1, -in_w / 2, z0 - 1]) cube([mag_wall + 2, in_w, rail_z + window_h - z0 + 1]);
        // the gate's screw (M3 x 20 from the top, a lock nut on top of the ledge)
        translate([mag_x1 + gate_t / 2, 0, z1 - 6]) cylinder(d = 3.4, h = 8);
        // a finger notch in each side wall to take a stack out
        for (s = [-1, 1]) translate([gate_x / 2, s * mag_y, z1]) rotate([90, 0, 0]) cylinder(d = 30, h = 20, center = true);
    }
}

// The gate: a blade across the magazine's front, in front of the window. Its bottom edge is
// what holds the second card back; the gap under it is set with a feeler gauge on the rails.
// The edge that a card's leading edge meets is rounded. Print lying on its back face.
module gate(gap = gate_gap_nominal) {
    gh = ledge_z - 9 - (rail_z + gap);           // its top stays 5 mm under the ledge
    difference() {
        translate([mag_x1, -gate_half_w, rail_z + gap]) union() {
            translate([0, 0, 1]) cube([gate_t, 2 * gate_half_w, gh - 1]);
            translate([1, 0, 0]) cube([gate_t - 1, 2 * gate_half_w, gh]);
            translate([1, 0, 1]) rotate([-90, 0, 0]) cylinder(r = 1, h = 2 * gate_half_w);   // the rounded back edge
        }
        translate([mag_x1 + gate_t / 2, 0, rail_z + gap + gh - 12]) cylinder(d = 2.6, h = 13);   // M3 self-tapping, from above
    }
}

// The chute: bolted to the wheel block's front, it takes the card from the end of the table down
// to the tray. The card slides on its BACK. Print on its side.
module chute() {
    // its top surface begins 1.3 mm under the card plane, so the two 0.8 mm ribs on it begin 0.5 mm
    // under it: a card leaving the table meets no edge (at 0.6 mm the ribs stood 0.2 mm proud)
    z0 = rail_z - 1.3;
    run = (z0 - chute_exit_z) / sin(chute_deg);
    w = tray_in_w + 1;
    difference() {
        union() {
            // the sloped plate, cut off where the table ends: tilted 30 degrees, its back-bottom
            // corner would reach 1.5 mm behind the table's end, into the wheel block
            difference() {
                translate([table_end, 0, z0]) rotate([0, chute_deg, 0]) {
                    translate([0, -w / 2 - 2, -3]) cube([run, w + 4, 3]);
                    for (s = [-1, 1]) translate([0, s > 0 ? w / 2 : -w / 2 - 2, -3]) cube([run, 2, 11]);
                    for (y = [-12, 12]) translate([0, y - 1, -eps]) cube([run, 2, 0.8]);   // two ribs: less contact
                }
                translate([table_end - 5, -w / 2 - 3, chute_exit_z]) cube([5, w + 6, rail_z + 10 - chute_exit_z]);   // only that
            }
            translate([table_end, -w / 2 - 2, z0 - 35]) cube([3, w + 4, 35]);           // the flange
            // a rib under it, from the flange's foot to 60% down the plate's underside
            u = run * 0.6;
            rotate([90, 0, 0]) linear_extrude(3, center = true)
                polygon([[table_end, z0 - 35], [table_end + 3, z0 - 35],
                         [table_end + u * cos(chute_deg) - 2.5 * sin(chute_deg), z0 - u * sin(chute_deg) - 2.5 * cos(chute_deg)],
                         [table_end, z0 - 1]]);
        }
        for (y = [-25, 25]) translate([table_end - 1, y, chute_bolt_z]) rotate([0, 90, 0]) cylinder(d = 3.4, h = 5);
    }
}

// ---------------------------------------------------------------------------------------
// Landing tray, base and camera (ideas taken from the Card Slinger: a funnel that centres the
// card, a removable tray, a stand over it - none of its geometry)
// ---------------------------------------------------------------------------------------

// The tray: a pocket a little larger than a sleeved card, with a 45 degree funnel on three
// sides (none on the chute's side). Line the far wall with 1-2 mm felt. Print upright, in a
// light matte colour: the outline detector was measured on a white box (see the plan).
module tray() {
    x0 = tray_x0 - tray_wall;
    x1 = tray_x0 + tray_in_l + tray_wall;
    y = tray_in_w / 2 + tray_wall;
    top = tray_floor + tray_depth;
    flare = 8;
    difference() {
        union() {
            translate([x0, -y, base_t]) cube([x1 - x0, 2 * y, top - base_t]);
            difference() {
                frustum([x0, x1, -y, y, top - eps], [x0, x1 + flare, -y - flare, y + flare, top + flare]);
                frustum([tray_x0, tray_x0 + tray_in_l, -tray_in_w / 2, tray_in_w / 2, top - 2 * eps],
                        [tray_x0, tray_x0 + tray_in_l + flare, -tray_in_w / 2 - flare, tray_in_w / 2 + flare, top + flare + eps]);
                translate([x0 - 1, -y - flare - 1, top - 1]) cube([tray_x0 - x0 + 1, 2 * (y + flare) + 2, flare + 2]);   // no funnel on the near side
            }
        }
        translate([tray_x0, -tray_in_w / 2, tray_floor]) cube([tray_in_l, tray_in_w, tray_depth + 1]);
    }
}

// The base: holds the tray in place, the camera post at its far end, and is bolted to the wheel
// block by a tab under the chute. Put soft feet under it and under the block.
module landing_base() {
    x0 = table_end;
    x1 = base_x1;
    y = 50;
    tx0 = tray_x0 - tray_wall - 0.4;
    tx1 = tray_x0 + tray_in_l + tray_wall + 0.4;
    ty = tray_in_w / 2 + tray_wall + 0.4;
    difference() {
        union() {
            translate([x0, -y, 0]) cube([x1 - x0, 2 * y, base_t]);
            // the tray's frame
            difference() {
                translate([tx0 - 1.6, -ty - 1.6, base_t - eps]) cube([tx1 - tx0 + 3.2, 2 * ty + 3.2, 4]);
                translate([tx0, -ty, base_t - 1]) cube([tx1 - tx0, 2 * ty, 6]);
                translate([(tx0 + tx1) / 2 - 15, -ty - 3, base_t]) cube([30, 2 * ty + 6, 5]);   // finger gaps to lift it
            }
            // the post's socket
            difference() {
                translate([post_x - post_s / 2 - 2.4, -post_s / 2 - 2.4, base_t - eps]) cube([post_s + 4.8, post_s + 4.8, 12]);
                translate([post_x - post_s / 2 - 0.2, -post_s / 2 - 0.2, base_t]) cube([post_s + 0.4, post_s + 0.4, 13]);
            }
            // the tab bolted to the wheel block's front wall
            translate([x0, -25, base_t - eps]) cube([4, 50, 20]);
        }
        for (yy = [-15, 15]) translate([x0 - 1, yy, 14]) rotate([0, 90, 0]) cylinder(d = 3.4, h = 6);
        translate([post_x, 0, base_t + 6]) rotate([90, 0, 0]) cylinder(d = 3.4, h = post_s + 10, center = true);

    }
}

// The Pi mount: the station's Raspberry Pi 4 or 5 (the camera's computer) and the Pico that drives
// the servos, on a plate standing behind the camera post - low, near its foot, where its weight adds
// little to the camera's shake, and close to the camera (a 200 mm ribbon reaches). Two sleeves slide
// down over the post before the camera arm goes on; the lower one rests on the post's socket and
// takes one M3 screw into the post. Both boards face away from the post:
//   Pi: four M2.5 standoffs (self-tapping), its GPIO header at the bottom, its USB / Ethernet end at -y;
//   Pico: four M2 standoffs (self-tapping), right under the Pi's GPIO header (a short jumper).
// Print upright, standing on the sleeves (as it stands on the post; the standoffs are short
// horizontal cylinders, printable without support).
module pi_mount() {
    difference() {
        union() {
            for (z = [pm_z0, pm_z1 - 12])
                translate([post_x - pm_sleeve / 2 - 3, -pm_sleeve / 2 - 3, z]) cube([pm_sleeve + 6, pm_sleeve + 6, 12]);
            translate([pm_x0 - eps, -pm_half_w, pm_z0]) cube([pm_t + eps, 2 * pm_half_w, pm_z1 - pm_z0]);
            for (h = pi_holes_yz) translate([pm_x0 + pm_t - eps, h[0], h[1]]) rotate([0, 90, 0]) cylinder(d = 6, h = pi_stand + eps);
            for (h = pico_holes_yz) translate([pm_x0 + pm_t - eps, h[0], h[1]]) rotate([0, 90, 0]) cylinder(d = 5, h = pico_stand + eps);
        }
        for (z = [pm_z0, pm_z1 - 12]) translate([post_x - pm_sleeve / 2, -pm_sleeve / 2, z - 1]) cube([pm_sleeve, pm_sleeve, 14]);
        for (h = pi_holes_yz) translate([pm_x0 + 1, h[0], h[1]]) rotate([0, 90, 0]) cylinder(d = 2.2, h = pm_t + pi_stand);
        for (h = pico_holes_yz) translate([pm_x0 + 1, h[0], h[1]]) rotate([0, 90, 0]) cylinder(d = 1.7, h = pm_t + pico_stand);
        // the lower sleeve's screw into the post (M3 self-tapping, below the post's slot)
        translate([post_x, -pm_sleeve / 2 - 4, pm_z0 + 6]) rotate([-90, 0, 0]) cylinder(d = 3.4, h = 5);
        // cable-tie slots down both sides of the plate
        for (z = [pm_z0 + 20, pm_z0 + 50, pm_z0 + 80]) for (s = [-1, 1])
            translate([pm_x0 - 1, s * (pm_half_w - 5) - 1.5, z - 4]) cube([pm_t + 2, 3, 8]);
    }
}

// The camera post: square, with a slot the arm's clamp bolt goes through. Print standing.
module camera_post() {
    difference() {
        translate([post_x - post_s / 2, -post_s / 2, base_t]) cube([post_s, post_s, post_h]);
        translate([post_x - 2.2, -post_s / 2 - 1, base_t + 100]) cube([4.4, post_s + 2, post_h - 110]);
        translate([post_x, 0, base_t + 6]) rotate([90, 0, 0]) cylinder(d = 2.8, h = post_s + 2, center = true);
        translate([post_x, -post_s / 2 - 1, pm_z0 + 6]) rotate([-90, 0, 0]) cylinder(d = 2.5, h = 12);   // the Pi mount's screw
    }
}

// The camera arm: a clamp around the post (one M4 bolt through the post's slot sets the
// height) and a plate over the tray's centre. The plate's 9 mm hole takes a 1/4"-20 tripod
// bolt for a webcam that has the thread, or is the lens hole of a Raspberry Pi Camera Module 3
// (its M2 holes, 21 x 12.5 mm, around it - check against your module). Print with the clamp
// standing on the bed.
module camera_arm() {
    cx = tray_x0 + tray_in_l / 2;                // over the tray's centre
    z = camera_z;
    sl = post_s + 0.6;
    difference() {
        union() {
            translate([post_x - sl / 2 - 3, -sl / 2 - 3, z]) cube([sl + 6, sl + 6, 24]);
            translate([cx, -10, z]) cube([post_x - sl / 2 - cx, 20, 6]);
            translate([cx - 20, -20, z]) cube([40, 40, 6]);
        }
        translate([post_x - sl / 2, -sl / 2, z - 1]) cube([sl, sl, 26]);
        translate([post_x, 0, z + 14]) rotate([90, 0, 0]) cylinder(d = 4.4, h = sl + 10, center = true);
        translate([cx, 0, z - 1]) cylinder(d = 9, h = 8);
        for (dx = [-10.5, 10.5]) for (dy = [-6.25, 6.25]) translate([cx + dx, dy, z - 1]) cylinder(d = 2.2, h = 8);
    }
}

// ---------------------------------------------------------------------------------------
// Where the loose parts sit, the assembly view and the part selector. Each part is modelled
// where it sits in the assembly; `printable` lays it down at the origin in its print orientation.
// ---------------------------------------------------------------------------------------

// axle i (0-2), side s (-1 / 1). Used by the assembly view and by freecad/to_freecad.sh.
module placed_wheel(i, s)
    translate([axle_x[i], s * axle_wheel_y[i] + (s > 0 ? -wheel_w / 2 : wheel_w / 2), axle_z])
        rotate([s > 0 ? -90 : 90, 0, 0]) wheel();
module placed_ring(i, s)                         // the O-ring, as a plain band (bought)
    translate([axle_x[i], s * axle_wheel_y[i], axle_z]) rotate([90, 0, 0])
        difference() { cylinder(d = wheel_d, h = ring_cs - 0.2, center = true); cylinder(d = groove_d - 0.5, h = ring_cs, center = true); }
module placed_rod(i)                             // bought: 8 mm silver steel
    translate([axle_x[i], block_half_w + housing_out, axle_z]) rotate([90, 0, 0]) cylinder(d = rod_d, h = rod_length(i));
module placed_pi()                              // bought: the boards, as boxes (the Pi with room for its
    translate([pm_x0 + pm_t + pi_stand, -pi_board[0] / 2, pi_z1 - pi_board[1]]) {   // parts and an Active Cooler)
        cube([1.6, pi_board[0], pi_board[1]]);
        translate([1.6, 2, 2]) cube([pi_height, pi_board[0] - 4, pi_board[1] - 4]);
    }
module placed_pico()
    translate([pm_x0 + pm_t + pico_stand, -pico_board[0] / 2, pico_z0]) cube([4, pico_board[0], pico_board[1]]);
module placed_hub(k)                             // k = 1, 2: on axle 2, axle 3
    translate([axle_x[k], hub_y0, axle_z]) rotate([-90, 0, 0]) clutch_hub();

module card(l, w, x, z, c = "white") {
    color(c, 0.9) translate([x, -w / 2, z]) cube([l, w, 0.3]);
}

// Everything in place. `at` = how far card 1 has gone (mm), to see it on its way.
module assembly(at = 40) {
    color("SteelBlue") wheel_plate();
    color("White") for (s = [-1, 1]) placed_rail(s);
    color("LightSteelBlue", 0.5) wheel_block();
    color("SlateGray") servo_bracket();
    for (i = [0 : 2]) {
        for (s = [-1, 1]) color(i == 0 ? "Gainsboro" : "Gold") placed_wheel(i, s);
        color("Silver") placed_rod(i);
        color("Red") for (s = [-1, 1]) placed_ring(i, s);
    }
    for (k = [1, 2]) color("Orange") placed_hub(k);
    color("Gainsboro", 0.6) magazine(true);
    color("DimGray") gate();
    color("SteelBlue") chute();
    color("WhiteSmoke") tray();
    color("SlateGray") landing_base();
    color("SlateGray") camera_post();
    color("SlateGray") camera_arm();
    color("SlateGray") pi_mount();
    color("DarkGreen") placed_pi();
    color("Green") placed_pico();
    // a stack of cards, and the bottom one on its way out
    for (i = [1 : 20]) card(sleeved_l, sleeved_w, mag_x1 - sleeved_l, rail_z + i * 0.6);
    card(sleeved_l, sleeved_w, mag_x1 - sleeved_l + at, rail_z, "Tomato");
}

module printable() {
    if (part == "bearing_test") bearing_test();
    else if (part == "wheel_block") translate([-block_x0, block_half_w, 0]) wheel_block();
    else if (part == "wheel_plate") translate([-block_x0, plate_half_w, plate_top]) rotate([180, 0, 0]) wheel_plate();   // face down
    else if (part == "rail") translate([-rail_xs, rail_w / 2, rail_top]) rotate([180, 0, 0]) rail();                  // on its top
    else if (part == "wheel") wheel();
    else if (part == "clutch_hub") clutch_hub();
    else if (part == "servo_bracket") rotate([90, 0, 0]) translate([0, -servo_tab_face + bracket_t, -axle_z]) servo_bracket();
    else if (part == "magazine_sleeved") translate([-mag_x0, mag_y, skirt_d - plate_top]) magazine(true);
    else if (part == "magazine_unsleeved") translate([-mag_x0, mag_y, skirt_d - plate_top]) magazine(false);
    else if (part == "gate") rotate([0, -90, 0]) translate([-mag_x1, 0, -rail_z]) gate(0);
    else if (part == "chute") translate([0, 0, (tray_in_w + 1) / 2 + 2]) rotate([90, 0, 0]) translate([-table_end, 0, 0]) chute();
    else if (part == "tray") translate([-tray_x0, 0, -base_t]) tray();
    else if (part == "landing_base") translate([-table_end, 0, 0]) landing_base();
    else if (part == "camera_post") translate([-post_x, 0, -base_t]) camera_post();
    else if (part == "camera_arm") translate([-post_x, 0, -camera_z]) camera_arm();
    else if (part == "pi_mount") translate([-post_x, 0, -pm_z0]) pi_mount();
}

if (part == "assembly") assembly();
else printable();
