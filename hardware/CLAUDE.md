# CLAUDE.md - the card dropper's mechanism

Loaded when working under this folder. Moved here from the root `CLAUDE.md` (2026-10-30) word for word; the
project-wide rules stay there. Module names are written bare, as in the root file.
The station's side of the dropper: `../src/card_scanner/station/CLAUDE.md`.

## Where things live

`hardware/dropper/card_dropper.scad` (OpenSCAD, every printed part - the source; `hardware/dropper/freecad/` is made from it by `to_freecad.sh`: a FreeCAD file and STEP files - avoid `hull()` and unions of many small 2D shapes there, FreeCAD's importer fails on them), `hardware/dropper/firmware/main.py` (a Pico turns the pulse into one card's feed by the wheels' two servos; its `Trigger` keeps a pulse that comes during a feed - or during the boot pause: `boot()` starts watching the pin BEFORE it (`start_watching`) - and never one already on at power-up (`Trigger.armed`: an interrupted feed is not replayed) - and carries it out after it, never drops it: `tests/test_dropper_firmware.py`, a simulated Pico, also run as `__main__` the way the Pico starts it), `hardware/dropper/assembly/` (the drive's assembly sheet, drawn from the .scad by `make_sheet.sh`: a change to the hub, the bracket or the assembly order means drawing it again), `docs/plans/CARD_DROPPER_MECHANISM_PLAN.md`.
