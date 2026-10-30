#!/bin/sh
# Rebuilds the FreeCAD files in this folder from ../card_dropper.scad (the source - edit that,
# then run this). Needs OpenSCAD (a program `openscad`, or the Flathub one: org.openscad.OpenSCAD)
# and FreeCAD's command-line program `freecadcmd`.
#
#   card_dropper.FCStd         every part in its place (the unsleeved magazine set beside the other)
#   step/<part>.step           each part to print, alone, lying as it is printed
#   conversion_report.json     the check: one valid solid per object, its volume
set -e
here=$(cd "$(dirname "$0")" && pwd)
top=$(cd "$here/.." && pwd)
scad="$top/card_dropper.scad"
work=$(mktemp -d)
trap '[ -n "$KEEP" ] || rm -rf "$work"' EXIT

# OpenSCAD: the installed program (FreeCAD calls it too)
osc=$(command -v openscad) || { echo "OpenSCAD is not installed (the openscad package)" >&2; exit 1; }

# Every object of the document: its name | where it sits (OpenSCAD: the placements of assembly() in
# the .scad) | the part printed for its STEP file (- for a bought part: none). The six wheels are one
# printed part, so are the two hubs.
cat > "$work/manifest.txt" <<'EOF'
wheel_block|wheel_block();|wheel_block
wheel_plate|wheel_plate();|wheel_plate
rail_left|placed_rail(-1);|rail
rail_right|placed_rail(1);|rail
servo_bracket|servo_bracket();|servo_bracket
wheel_axle1_left|placed_wheel(0, -1);|wheel
wheel_axle1_right|placed_wheel(0, 1);|wheel
wheel_axle2_left|placed_wheel(1, -1);|wheel
wheel_axle2_right|placed_wheel(1, 1);|wheel
wheel_axle3_left|placed_wheel(2, -1);|wheel
wheel_axle3_right|placed_wheel(2, 1);|wheel
clutch_hub_axle2|placed_hub(1);|clutch_hub
clutch_hub_axle3|placed_hub(2);|clutch_hub
rod_axle1|placed_rod(0);|-
rod_axle2|placed_rod(1);|-
rod_axle3|placed_rod(2);|-
magazine_sleeved|magazine(true);|magazine_sleeved
magazine_unsleeved|translate([0,160,0]) magazine(false);|magazine_unsleeved
gate|gate();|gate
chute|chute();|chute
tray|tray();|tray
landing_base|landing_base();|landing_base
camera_post|camera_post();|camera_post
camera_arm|camera_arm();|camera_arm
pi_mount|pi_mount();|pi_mount
raspberry_pi_standin|placed_pi();|-
pico_standin|placed_pico();|-
EOF

done_print=" "
while IFS='|' read -r name expr print; do
    printf 'include <%s>\n%s\n' "$scad" "$expr" > "$work/w.scad"
    "$osc" -D 'part="none"' -o "$work/asm_$name.csg" "$work/w.scad" > "$work/osc.log" 2>&1 || { cat "$work/osc.log"; exit 1; }
    # each printed part once (the six wheels are one part)
    if [ "$print" != "-" ] && [ "${done_print#* $print }" = "$done_print" ]; then
        "$osc" -D "part=\"$print\"" -o "$work/print_$print.csg" "$scad" > "$work/osc.log" 2>&1 || { cat "$work/osc.log"; exit 1; }
        done_print="$done_print$print "
    fi
    echo "exported $name"
done < "$work/manifest.txt"

rm -f "$here/conversion_report.json" "$here"/step/*.step   # a part that no longer exists leaves no file
DROPPER_CSG="$work" DROPPER_OUT="$here" DROPPER_OPENSCAD="$osc" freecadcmd "$here/to_freecad.py" > "$work/freecad.log" 2>&1 \
    || { tail -20 "$work/freecad.log"; exit 1; }
# freecadcmd ends with 0 even when the script raised: the report is written last, so it is the proof
[ -f "$here/conversion_report.json" ] || { grep -i -E "exception|error" "$work/freecad.log" | tail -5; exit 1; }
rm -f "$here"/*.FCBak     # FreeCAD keeps the previous file when it saves over one
cat "$here/conversion_report.json"
