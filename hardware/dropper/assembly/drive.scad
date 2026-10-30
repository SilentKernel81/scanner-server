// One driven axle (axle 3) of the card dropper, step by step: the parts of each step, exported one by one
// (`only`) for Blender to colour and render. The printed parts come from card_dropper.scad; the bought ones
// (servo, horn, bearings, rod, screws) are simple stand-ins.
include <../card_dropper.scad>
part = "none";              // card_dropper.scad draws nothing by itself
panel = 1;                  // which step
only = "";                  // which item of it ("" = all)
$fn = 64;

X = axle_x[2];              // axle 3
Z = axle_z;
spline_top = hub_y0 + horn_recess - horn_t;
housing_face = -block_half_w - housing_out;
rod_y0 = housing_face - (hub_gap + clutch_l - 0.5);   // the rod's end, inside the hub
far_608 = block_half_w + housing_out - bearing_w;     // the other wall's bearing

// an item: its name is echoed (the exporter lists them), and drawn when it is the one asked for
module it(name) { echo(str("ITEM:", name)); if (only == "" || only == name) children(); }

module along_y(y) translate([X, y, Z]) rotate([-90, 0, 0]) children();
module tube(od, id, l) difference() { cylinder(d = od, h = l); translate([0, 0, -1]) cylinder(d = id, h = l + 2); }

// --- bought parts ----------------------------------------------------------------------------
module hf0812(y) {
    it("clutch") along_y(y) tube(clutch_od, rod_d, clutch_l);
    it("clutch_arrow") along_y(y + clutch_l) linear_extrude(0.4)        // the arrow printed on its face
        union() { difference() { circle(d = 11.4); circle(d = 9.2); translate([-6, -6]) square([6, 12]); }
                  translate([0, -5.1]) polygon([[0, -1.6], [0, 1.6], [-2.2, 0]]); }
}
module b608(y, n) it(str("bearing", n)) along_y(y) tube(bearing_od, rod_d, bearing_w);
module rod(y0) it("rod") along_y(y0) cylinder(d = rod_d, h = rod_length(2));

module horn(y) it("horn") along_y(y) difference() {                 // the double arm, uncut
    a = horn_len / 2 - horn_tip_w / 2;
    union() {
        cylinder(d = horn_hub_d, h = horn_t);
        for (s = [-1, 1]) translate([s * a, 0, 0]) cylinder(d = horn_tip_w, h = horn_t);
        linear_extrude(horn_t) polygon([[-a, -horn_tip_w / 2], [0, -horn_root_w / 2], [a, -horn_tip_w / 2], [a, horn_tip_w / 2], [0, horn_root_w / 2], [-a, horn_tip_w / 2]]);
    }
    translate([0, 0, -3]) cylinder(d = 4.8, h = 10);                 // the spline's hole
    for (s = [-1, 1]) translate([s * horn_screw_r, 0, -1]) cylinder(d = 2, h = 5);   // the hole opened for a screw
}

module small_screws(y) it("screws_horn") for (s = [-1, 1])          // the horn's two small screws, going in along +y
    translate([X + s * horn_screw_r, y, Z]) rotate([-90, 0, 0]) { cylinder(d = 3.8, h = 1); cylinder(d = 2, h = 7); }

module servo(dy = 0) translate([0, dy, 0]) {        // an MG90S: tabs on the bracket's face, shaft on the axle
    y1 = servo_tab_face;
    zc = Z - servo_shaft_offset;
    it("servo") {
        translate([X - servo_body_w / 2, y1 - 18, zc - servo_body_l / 2]) cube([servo_body_w, 18 + servo_tab_t + 6, servo_body_l]);
        translate([X - servo_body_w / 2, y1, zc - 16]) cube([servo_body_w, servo_tab_t, 32]);       // the tabs
        along_y(y1 + servo_tab_t + 6) cylinder(d = 11.8, h = 2.5);                                 // the top boss
    }
    it("spline") along_y(y1 + servo_tab_t + 8.5) cylinder(d = 4.8, h = spline_top - (y1 + servo_tab_t + 8.5));
}
module m2_screws(dy) it("screws_servo") for (s = [-1, 1])
    translate([X, servo_tab_face + servo_tab_t + dy, Z - servo_shaft_offset + s * servo_hole_spacing / 2]) rotate([90, 0, 0]) {
        translate([0, 0, -1.2]) cylinder(d = 3.5, h = 1.2); cylinder(d = 2, h = 10);
    }
module m3_screws(dy) it("screws_block") for (x = [bracket_legs[1], bracket_legs[2]]) for (z = [Z - 14, Z + 14])   // the two legs beside axle 3, from inside the block
    translate([x, -block_half_w + block_wall + dy, z]) rotate([90, 0, 0]) {
        translate([0, 0, -2]) cylinder(d = 5.5, h = 2); cylinder(d = 3, h = 12);
    }

// --- printed parts, cut down to what is around axle 3 ----------------------------------------
module hub(dy = 0) it("hub") translate([0, dy, 0]) placed_hub(2);
module block_piece() it("block") intersection() { wheel_block(); translate([X - 26, -60, Z - 30]) cube([52, 120, 60]); }
module bracket_piece(dy = 0) it("bracket") translate([0, dy, 0]) intersection() { servo_bracket(); translate([X - 28, -120, Z - 40]) cube([56, 120, 80]); }
module wheels() { it("wheels") for (s = [-1, 1]) placed_wheel(2, s); it("rings") for (s = [-1, 1]) placed_ring(2, s); }

module arrow(from, to, n = 1) it(str("arrow", n)) {               // what moves where
    v = to - from; l = norm(v);
    translate(from) rotate([0, acos(v[2] / l), atan2(v[1], v[0])]) {
        cylinder(d = 1.8, h = l - 6);
        translate([0, 0, l - 6]) cylinder(d1 = 5, d2 = 0, h = 6);
    }
}
function at_axle(y, dx = 0, dz = 0) = [X + dx, y, Z + dz];
module cut() translate([X, -200, Z - 100]) cube([100, 400, 200]);   // takes away the half x > X, to see inside

// --- the steps -------------------------------------------------------------------------------
if (panel == 1) {               // the one-way bearing into the hub (the hub cut in half), arrow facing out
    difference() { hub(); cut(); }
    hf0812(hub_y1 + 22);
    arrow(at_axle(hub_y1 + 40, 0, 11), at_axle(hub_y1 + 3, 0, 11));
}
if (panel == 2) {               // the horn, trimmed, into the hub's pocket; two small screws
    hub();
    horn(spline_top - 14);
    small_screws(spline_top - 28);
    arrow(at_axle(spline_top - 44, 0, 10), at_axle(spline_top - 4, 0, 10));
}
if (panel == 3) {               // the 608s into the housings, the rod through, the wheels on it inside
    block_piece();
    b608(housing_face, 1);       // already pressed in, from outside
    b608(far_608, 2);
    rod(rod_y0 - 70);
    wheels();
    arrow(at_axle(rod_y0 - 75, 0, 14), at_axle(rod_y0 - 25, 0, 14));
}
if (panel == 4) {               // the servo through the bracket, its tabs on the bracket's face, two screws
    bracket_piece();
    servo(30);                   // from inside the bracket: the body goes out through the window, the tabs stay
    m2_screws(55);
    arrow(at_axle(servo_tab_face + 50, 0, 26), at_axle(servo_tab_face + 8, 0, 26));
}
if (panel == 5) {               // the hub (horn in it) onto the rod's end, BEFORE the bracket
    block_piece(); b608(housing_face, 1); b608(far_608, 2); rod(rod_y0); wheels();
    hub(-30); horn(spline_top - 30);
    arrow(at_axle(hub_y0 - 42, 0, 21), at_axle(hub_y0 - 6, 0, 21));
}
if (panel == 6) {               // the bracket with its servo: the spline into the horn, then M3 screws from inside
    block_piece(); b608(housing_face, 1); b608(far_608, 2); rod(rod_y0); wheels();
    hub(); horn(spline_top);
    bracket_piece(-26); servo(-26);
    m3_screws(14);
    arrow(at_axle(servo_tab_face - 66, 0, 30), at_axle(servo_tab_face - 30, 0, 30));
}
if (panel == 7) difference() {  // done, cut along the axle
    union() {
        block_piece(); b608(housing_face, 1); b608(far_608, 2); rod(rod_y0); wheels();
        hub(); horn(spline_top); hf0812(hub_y1 - clutch_l);
        bracket_piece(); servo();
    }
    cut();
}
