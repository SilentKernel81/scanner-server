# Card dropper controller: a Raspberry Pi Pico (MicroPython) between the station's GPIO pin and the
# feeder's two servos (card_dropper.scad). Copy it to the Pico as main.py (`mpremote cp main.py :`):
# the Pico runs it at power-up.
#
# Each servo turns its axle through a one-way bearing: a forward stroke turns the wheels, the return
# leaves them standing. So one card can take SEVERAL strokes, and a card pulled forward by one axle
# simply turns the other axle's wheels. One pulse from the station = one card:
#   axle 2 (behind the middle of the stack) helps the card start, and stops early - long before
#     card 1's back edge reaches it, so it never turns under card 2;
#   axle 3 (just behind the gate) carries the card until its back edge is about to pass it, and stops
#     there - short rather than long: a little short is a missed card (the station waits), a little
#     long is a wheel turning under card 2.
#
# Wiring, calibration and what was never tried: docs/plans/CARD_DROPPER_MECHANISM_PLAN.md.
# Never run on a Pico when it was written.

import machine
from machine import Pin, PWM, Timer
import math
import time

# --- Wiring -------------------------------------------------------------------------------
TRIGGER_PIN = 15        # GP15 <- 1 kOhm <- the station's dropper pin
AXLE2_PIN = 16          # GP16 -> 330 Ohm -> axle 2's servo signal
AXLE3_PIN = 17          # GP17 -> 330 Ohm -> axle 3's servo signal
TRIGGER_ACTIVE_LOW = False

# --- Calibration (calibrate() below, on YOUR servos, wheels and cards) --------------------------
# Each servo: the pulse width at rest, and how many microseconds make one degree - NEGATIVE if
# that servo turns the card forward with shorter pulses (the two sit on the same side, so usually
# both have the same sign).
AXLE2_REST_US = 600
AXLE3_REST_US = 600
US_PER_DEG = 11.1       # ~2000 us over ~180 degrees - check: calibrate() and a protractor
MM_PER_DEG = 0.4407     # card travel per degree of wheel: pi x 50.5 mm / 360 (the wheels as measured,
                        # 2026-10-30) - calibrate with a ruler on the rig (see the plan)
MAX_STROKE_DEG = 150    # one stroke at most: a margin inside the servo's ~180 degrees

# How far each axle moves the card, per card size (mm). Start SHORT and lengthen by test.
CARD = 'sleeved'        # 'sleeved' or 'unsleeved' - the magazine in use
TRAVEL_MM = {
    #             axle 2 (stops before the back edge reaches it)   axle 3 (stops just before)
    'sleeved':   (30, 86),
    'unsleeved': (30, 82),
}

STROKE_MS = 700         # one forward stroke, eased at its start
RETURN_MS = 400         # the servos back to rest: the wheels stand still meanwhile
COAST_END = True        # the LAST stroke ends at speed, not eased to zero: the card coasts on a few
                        # mm (the one-way bearing lets the wheels turn on with it) - see the plan

MIN_PULSE_MS = 8
BOOT_PAUSE_MS = 1500    # at power-up, a moment to break into the REPL for calibration (Ctrl+C)

axle2 = PWM(Pin(AXLE2_PIN))
axle3 = PWM(Pin(AXLE3_PIN))
for s in (axle2, axle3):
    s.freq(50)
trigger_pin = Pin(TRIGGER_PIN, Pin.IN, Pin.PULL_UP if TRIGGER_ACTIVE_LOW else Pin.PULL_DOWN)
led = Pin("LED", Pin.OUT)


class Trigger:
    """The station's pin, sampled every millisecond by a timer - also while a feed is moving the
    servo(s), which is when the station's next pulse can come: it pulses as soon as the card just
    released has been captured (and, with auto-add on, uploaded), and that can be before this board
    has finished bringing the mechanism back (a Codex review of 2026-10-23: a pulse then was lost
    and the feeding stopped for good, while the station counted the card as released).

    A pulse counts once it has been active for MIN_PULSE_MS (shorter is noise), and once only,
    however long it lasts (the station's pulses may last 2 s). A counted pulse is a REQUEST, kept
    until the main loop takes it - at most one: the station never asks for a card while another
    request is waiting, because it asks only after the previous card was captured, and that card is
    the one being fed. A second one while one waits is counted in `dropped` (it should stay 0) and
    not carried out: one card too few stops the feeding, which is safe; one too many is two cards on
    the pile (tests/test_dropper_firmware.py).

    A line that is ALREADY active when the board starts is not a request (a Codex review of
    2026-10-24): it is the pulse of a feed that a reset interrupted - a brown-out when both servos
    start, on the shared supply - and the one-way bearings kept the travel that feed already gave
    the card. Feeding it again in full would add a whole feed to that travel: axle 3 turning under
    the next card, maybe a second card out. So the trigger is ARMED only once it has seen the line
    inactive; a pulse that begins after that - also during the boot pause - counts as usual. A feed
    a reset interrupted is never replayed: that card stops short, the station waits for it, and
    someone clears the gate - one card too few, the safe side."""

    def __init__(self, pin, active_low, min_ms):
        self.pin = pin
        self.active_low = active_low
        self.min_ms = min_ms
        self.active_ms = 0       # how long the line has been active, in samples (1 ms each)
        self.pending = False     # a request not yet carried out
        self.dropped = 0         # requests that came while one was already waiting
        self.armed = False       # False until the line has been seen inactive once (see above)

    def sample(self, _timer=None):
        """The timer's callback, every millisecond."""
        active = self.pin.value() == (0 if self.active_low else 1)
        if not self.armed:
            # A line active from the start is an interrupted feed's pulse: wait for its end, count nothing
            self.armed = not active
            return
        if active:
            self.active_ms += 1
            if self.active_ms == self.min_ms:          # == : once per pulse
                if self.pending:
                    self.dropped += 1
                else:
                    self.pending = True
        else:
            self.active_ms = 0

    def take(self):
        """A waiting request, consumed: True once per counted pulse. With interrupts off, so the
        timer cannot count a pulse between the look and the clearing."""
        state = machine.disable_irq()
        try:
            wanted = self.pending
            self.pending = False
        finally:
            machine.enable_irq(state)
        return wanted

trigger = Trigger(trigger_pin, TRIGGER_ACTIVE_LOW, MIN_PULSE_MS)


def write(servo, rest_us, deg):
    """One servo to `deg` degrees forward of its rest position."""
    servo.duty_ns(int((rest_us + deg * US_PER_DEG) * 1000))


def limp():
    """No pulses: both servos go quiet while the camera waits for the card to lie still."""
    axle2.duty_ns(0)
    axle3.duty_ns(0)


def strokes(deg):
    """Split a turn into strokes of at most MAX_STROKE_DEG, all the same size."""
    n = max(1, math.ceil(deg / MAX_STROKE_DEG))
    return [deg / n] * n


def ease(f, coast):
    """How far along a stroke at time fraction f: a smooth start, and a smooth end unless the card
    is meant to coast off it (then the speed it reached is kept to the end)."""
    if not coast:
        return (1 - math.cos(math.pi * f)) / 2
    # the first half as the cosine curve, then straight on at its top speed
    if f < 0.5:
        return (1 - math.cos(math.pi * f)) / 2
    return 0.5 + (f - 0.5) * (math.pi / 2)  # slope pi/2 = the cosine curve's speed at its middle


def run_stroke(deg3, deg2, coast):
    """One forward stroke of both servos TOGETHER, at the same angular speed - so their wheels move
    the card at the same speed (a slower one would only freewheel). Axle 2 stops where its own
    turn ends; axle 3 goes on. `coast` scales the time so the end lands at the same angle."""
    span = ease(1.0, coast)                   # 1.0, or more when coasting: normalise it
    steps = max(1, STROKE_MS // 10)
    for i in range(steps + 1):
        a = deg3 * ease(i / steps, coast) / span
        write(axle3, AXLE3_REST_US, a)
        write(axle2, AXLE2_REST_US, min(a, deg2))
        time.sleep_ms(10)


def feed_one():
    """One card: the strokes, each followed by a return to rest with the wheels standing."""
    led.on()
    travel2, travel3 = TRAVEL_MM[CARD]
    left2 = travel2 / MM_PER_DEG                 # degrees axle 2 still has to turn
    plan = strokes(travel3 / MM_PER_DEG)
    for k, deg3 in enumerate(plan):
        deg2 = min(deg3, left2)
        left2 -= deg2
        run_stroke(deg3, deg2, COAST_END and k == len(plan) - 1)
        time.sleep_ms(80)
        # back to rest: the one-way bearings slip, the card and the wheels stay where they are
        write(axle3, AXLE3_REST_US, 0)
        write(axle2, AXLE2_REST_US, 0)
        time.sleep_ms(RETURN_MS)
    limp()
    led.off()


def calibrate(axle, deg):
    """From the REPL (Ctrl+C at start-up): calibrate(3, 0) holds axle 3's servo at rest,
    calibrate(3, 90) turns it 90 degrees forward. With a card on the wheels and a ruler beside it,
    the travel of a known turn gives MM_PER_DEG. limp() lets go."""
    if axle == 2:
        write(axle2, AXLE2_REST_US, deg)
    else:
        write(axle3, AXLE3_REST_US, deg)


watcher = None                   # the timer that samples the pin; kept: a timer nothing refers to may be collected and stop


def start_watching():
    """The station's pin is watched from here on - also during the boot pause and while the servos move. Once only."""
    global watcher
    if watcher is None:
        watcher = Timer(mode=Timer.PERIODIC, freq=1000, callback=trigger.sample)


def boot():
    """What the Pico does at power-up. The pin is watched BEFORE the pause, not after it (a Codex review of 2026-10-24):
    a Pico that resets while the station runs - a loose USB cable, a brown-out when both servos start - must not lose
    a pulse that falls in the pause. The station counts that card as released and waits for its capture, so a lost
    pulse stops the feeding for good. A pulse in the pause waits in `trigger` and is fed once the servos are at rest.
    A pulse that was already on when the board started is NOT fed (Trigger: it belongs to the feed the reset cut off)."""
    start_watching()
    time.sleep_ms(BOOT_PAUSE_MS)
    main()


def main():
    start_watching()             # already watched when boot() started it: main() alone is also safe
    # Power-up: both servos to rest. A jump at full speed, but harmless: going to rest is the
    # one-way bearings' free direction, so the wheels do not turn.
    write(axle3, AXLE3_REST_US, 0)
    write(axle2, AXLE2_REST_US, 0)
    time.sleep_ms(600)
    limp()
    while True:
        if trigger.take():
            feed_one()           # a pulse during it waits in `trigger` and is carried out next
        else:
            time.sleep_ms(1)


if __name__ == '__main__':       # on the Pico, main.py runs as __main__; the tests load it without, and run this too
    boot()
