"""
The card dropper: a mechanism under the station's control that releases the next card onto the pile, so nobody has to drop
cards by hand (docs/plans/PRODUCT_PLAN.md, phase 5 - the owner's idea of 2026-10-22; the mechanism itself is not designed yet).

This module PULSES ONE GPIO PIN for a moment - or, since 2026-11-12, asks a feeder on the network for one card (WifiFeeder,
below: the card-dropper's sideways feeder, paired with the station from the Settings page). What the pin drives - a servo's driver, a relay, a solenoid's transistor, a
stepper driver's step input - is the mechanism's business, not this module's: one pulse means "release one card".

WHEN a pulse is sent is the station's decision (station_client.py: Station.release_next_card and its callers), never this
module's: after the capture beep (the picture taken and any focus probe it started done), with auto-add off only once the card
was added or skipped on the page, and the first card when auto-scanning is switched on. One pulse per card and never more: a
card that is not captured (jammed, the magazine empty, the camera lost) releases nothing, so the stack can never run on by itself.

The pin is reached through the kernel's GPIO character device with libgpiod 2 (the `gpiod` package, LGPL-2.1). It is imported
only when a pulse is due: a station without the package, or a PC with no GPIO at all, runs exactly as before, and the dropper
says why it cannot work (`Dropper.error`, shown on the Settings page). On a Raspberry Pi 4 and 5 the 40-pin header is
/dev/gpiochip0 and a pin's GPIO number (the BCM number, "GPIO17") is its line offset there - checked on 2026-10-22 on both
(pinctrl-bcm2711, 58 lines; pinctrl-rp1, 54 lines; /dev/gpiochip4 is the same chip under its older name). The chip stays a
setting in case a later kernel numbers them otherwise.

Its settings live on the server with the camera's others (remote_scanner.CAMERA_SETTINGS 'dropper'), like every scanning
setting; `checked` below is the one place their rules are written, used by the server before saving and by the station
before using them.
"""
import ipaddress
import json
import logging
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger('station')

# The dropper's settings and what they are until someone changes them. Off: a station without a dropper never pulses a pin
DEFAULTS = {
    'enabled': False,
    'transport': 'gpio',        # 'gpio': this station's pin; 'wifi': a feeder on the network (WifiFeeder), paired from the page
    'chip': '/dev/gpiochip0',   # the GPIO chip's device (the Pi's 40-pin header on a Pi 4 and 5)
    'pin': None,                # the GPIO number (BCM) of the pin, as printed on Pi pinout charts: GPIO17 -> 17
    'pulse_ms': 150,            # how long the pin stays active for one card
    'active_low': False,        # True: "active" is the pin LOW (a relay board that switches on a low input)
    'feeder': None,             # 'wifi': the paired feeder, {'ip', 'name', 'mac'} - set by pairing (pair_feeder), never typed
    'pair_key': None,           # 'wifi': the key the feeder gave this station at pairing - kept on the server, never shown
}
PIN_RANGE = (0, 63)             # the header's GPIOs are 0-27; the chips have up to 58 lines - beyond 63 is a typing error
PULSE_RANGE = (10, 2000)        # milliseconds: shorter is lost in the driver's own reaction time, longer is a mechanism stuck open
TRANSPORTS = ('gpio', 'wifi')
PAIR_KEY_LEN = (16, 64)         # the feeder's rule (card-dropper: sideways/firmware/tuning.py check_pair)
FEEDER_NAME_MAX = 40


def checked(config):
    """
    The dropper's settings with every value checked, the missing ones from DEFAULTS - or ValueError naming the wrong one,
    before anything is used or saved. None (never set) is the defaults: off.
    """
    if config is None:
        return dict(DEFAULTS)
    if not isinstance(config, dict):
        raise ValueError('The card dropper\'s settings are not a set of values')
    unknown = sorted(set(config) - set(DEFAULTS))
    if unknown:
        raise ValueError(f'Unknown card dropper setting: {", ".join(unknown)}')
    values = dict(DEFAULTS, **config)
    if values['transport'] not in TRANSPORTS:
        raise ValueError('The card dropper is driven by a GPIO pin or a feeder over Wi-Fi')
    feeder = values['feeder']
    if feeder is not None:
        if not isinstance(feeder, dict) or set(feeder) - {'ip', 'name', 'mac'}:
            raise ValueError('The paired feeder is not a feeder')
        try:
            ipaddress.IPv4Address(feeder.get('ip'))
        except (ValueError, TypeError):
            raise ValueError('The paired feeder\'s address is not an IPv4 address') from None
        for key in ('name', 'mac'):
            if feeder.get(key) is not None and (not isinstance(feeder[key], str) or len(feeder[key]) > FEEDER_NAME_MAX):
                raise ValueError(f'The paired feeder\'s {key} is not a short text')
    key = values['pair_key']
    if key is not None and (not isinstance(key, str) or not PAIR_KEY_LEN[0] <= len(key) <= PAIR_KEY_LEN[1]
                            or any(not 33 <= ord(c) <= 126 for c in key)):
        raise ValueError('The feeder\'s pair key is not one a feeder gives')
    for flag in ('enabled', 'active_low'):
        if not isinstance(values[flag], bool):
            raise ValueError(f'The card dropper\'s {flag} is on or off (true / false)')
    chip = values['chip']
    # A device of the GPIO chips and nothing else: the setting is typed on a web page and opened on the station
    if not isinstance(chip, str) or not chip.startswith('/dev/gpiochip') or not chip[len('/dev/gpiochip'):].isdigit():
        raise ValueError('The GPIO chip is a device like /dev/gpiochip0')
    pin = values['pin']
    # isinstance(True, int) is true in Python: a switch's value sent where a number belongs is refused, not taken as GPIO 1
    if pin is not None and (isinstance(pin, bool) or not isinstance(pin, int) or not PIN_RANGE[0] <= pin <= PIN_RANGE[1]):
        raise ValueError(f'The GPIO pin is a number from {PIN_RANGE[0]} to {PIN_RANGE[1]} (GPIO17 is 17)')
    pulse = values['pulse_ms']
    if isinstance(pulse, bool) or not isinstance(pulse, int) or not PULSE_RANGE[0] <= pulse <= PULSE_RANGE[1]:
        raise ValueError(f'The pulse lasts {PULSE_RANGE[0]} to {PULSE_RANGE[1]} ms')
    if values['enabled'] and values['transport'] == 'gpio' and pin is None:
        raise ValueError('Choose the GPIO pin before switching the card dropper on')
    if values['enabled'] and values['transport'] == 'wifi' and (feeder is None or key is None):
        raise ValueError('Pair a feeder before switching the card dropper on')
    return values


class GpiodPin:
    """
    One output line through libgpiod 2 (`gpiod`), requested when the first pulse is due and kept until the settings change or
    the station stops. Requested INACTIVE: asking for the line must never release a card by itself.
    """

    def __init__(self, chip, pin, active_low):
        try:
            import gpiod                                   # only here: a station that never pulses never needs it
            from gpiod.line import Direction, Value
        except ImportError:
            raise RuntimeError('the GPIO library (gpiod) is not installed on this station') from None
        self._active, self._inactive = Value.ACTIVE, Value.INACTIVE
        self.pin = pin
        settings = gpiod.LineSettings(direction=Direction.OUTPUT, active_low=active_low, output_value=Value.INACTIVE)
        try:
            self._request = gpiod.request_lines(chip, consumer='card-scanner-dropper', config={pin: settings})
        except FileNotFoundError:
            raise RuntimeError(f'{chip} does not exist on this machine (no GPIO, or the container was not given it)') from None
        except PermissionError:
            raise RuntimeError(f'no permission to use {chip} (in Docker: deploy/docker-compose.client-gpio.yml)') from None
        except OSError as e:     # the line is used by something else, or the chip has no such line
            raise RuntimeError(f'GPIO{pin} on {chip} cannot be used: {e.strerror or e}') from None

    def set(self, active):
        self._request.set_value(self.pin, self._active if active else self._inactive)

    def close(self):
        try:
            self._request.release()
        except Exception:
            pass        # the line goes when the process goes anyway


# -- A feeder over Wi-Fi (card-dropper's sideways feeder: sideways/firmware - the owner, 2026-11-12: "for the ESP32 it will be
#    either wifi or bluetooth"). Its rules, the feeder's: ONE REQUEST IS ONE CARD. The station numbers its requests; the feeder
#    answers a number it has seen with that card's state and never feeds it twice (a retry after a lost reply asks again with
#    the SAME number); every request carries the feeder's boot id (new at its every power-up), so one from before a restart
#    is refused, never fed; one card at a time (another number while one is under way: refused, never queued). The card is
#    released when the feeder answers 'done' - it lies still - waited for FEEDER_WAIT_S at most (the owner's limit, 10 s),
#    after which the release has failed and the scanning waits, saying why.
FEEDER_WAIT_S = 10              # the owner's limit (2026-11-12)
# The request for a card is sent INSIDE the caller's gate, which holds the station's release_lock (station_client:
# _still_wanted) - a stop from the page waits for it. So what runs there is bounded: FEEDER_TRIES requests of
# FEEDER_HTTP_S each, then one "was it taken?" of FEEDER_HTTP_S - 6 s at most, a dead feeder; ~0.1 s a healthy one.
# The boot id is read before the gate (when the feeder is opened). These three numbers and DISCOVERY_S: SUGGESTED, NOT
# YET AGREED WITH THE OWNER (2026-11-12).
FEEDER_HTTP_S = 2               # one request's answer
FEEDER_TRIES = 2                # a request whose answer was lost: asked again (the same number) this many times in all
DISCOVERY_PORT = 50505          # the feeder's auto-find (tuning.py: DISCOVERY_PORT, DISCOVERY_ASK)
DISCOVERY_ASK = b'card-dropper?'
DISCOVERY_S = 1.5               # answers waited for after the last question


def feeder_http(url, form=None, timeout=FEEDER_HTTP_S):
    """(HTTP code, JSON) of one request to a feeder - its refusals (4xx) carry JSON too. OSError when there is no answer"""
    body = urllib.parse.urlencode(form).encode() if form is not None else None
    try:
        with urllib.request.urlopen(url, body, timeout=timeout) as answer:
            return answer.status, json.load(answer)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {}
    except ValueError as e:      # an answer that is not JSON: not a feeder
        raise OSError(f'not a feeder\'s answer ({e})') from None


class WifiFeeder:
    """
    A feeder on the network, as a pin: set(True) asks it for one card (the card is on its way once it took the request),
    set(False) waits until that card is done. The same three calls as GpiodPin, so Dropper.pulse - its lock, the caller's
    gate, the pin set inside it - is unchanged. Raises RuntimeError saying why, as the pin does.
    """

    def __init__(self, ip, pair_key, http=feeder_http, clock=time.monotonic, sleep=time.sleep):
        self.base = f'http://{ip}'
        self.ip, self.key = ip, pair_key
        self._http, self._clock, self._sleep = http, clock, sleep
        self.number = 0
        self.under_way = None            # the number asked for and not yet done
        self.boot = self._status_boot()  # here, when opened - before the caller's gate, never inside it

    def _status_boot(self):
        try:
            code, answer = self._http(self.base + '/status')
            return answer['status']['boot']
        except (OSError, KeyError, TypeError) as e:
            raise RuntimeError(f'the feeder at {self.ip} does not answer ({e})') from None

    def set(self, active):
        if active:
            self._ask()
        elif self.under_way is not None:
            try:
                self._wait()
            finally:
                self.under_way = None

    def _ask(self):
        # A number never used before by this station: the time in ms, and always more than the last one
        self.number = max(self.number + 1, int(time.time() * 1000))
        n = self.number
        tries, boot_read = 0, False
        while True:
            tries += 1
            try:
                code, answer = self._http(self.base + '/feed', {'key': self.key, 'boot': self.boot, 'n': n})
            except OSError as e:          # no answer: it may or may not have arrived - the same number again
                if tries < FEEDER_TRIES:
                    continue
                # Did it take the number after all? Then the card is on its way: never "not released" for a card that is
                try:
                    code, answer = self._http(f'{self.base}/feed?n={n}')
                except OSError:
                    code = None
                if code == 200:
                    self.under_way = n
                    return
                raise RuntimeError(f'the feeder at {self.ip} did not answer the request ({e})') from None
            if code in (200, 202):        # taken now, or taken before (a retry): set(False) waits for it, or says it failed
                self.under_way = n
                return
            if code == 409 and answer.get('refused') == 'boot' and answer.get('boot') and not boot_read:
                self.boot, boot_read = answer['boot'], True   # it restarted: nothing was fed - its new id is in the refusal
                continue
            if code == 409 and answer.get('refused') == 'busy':
                raise RuntimeError('the feeder is still busy with a card - nothing asked')
            if code == 403:
                raise RuntimeError('the feeder refused this station\'s key - pair it again')
            raise RuntimeError(f'the feeder refused the card ({code}: {answer.get("error") or answer})')

    def _wait(self):
        n, until = self.under_way, self._clock() + FEEDER_WAIT_S
        while True:
            try:
                code, answer = self._http(f'{self.base}/feed?n={n}')
            except OSError:
                code, answer = None, {}
            if code == 404 or (answer.get('boot') and answer['boot'] != self.boot):
                raise RuntimeError('the feeder restarted while releasing the card - look at the pile before going on')
            state = answer.get('state')
            if state == 'done':
                return
            if state == 'failed':
                raise RuntimeError(f'the feeder could not release the card ({answer.get("error")})')
            if self._clock() > until:
                raise RuntimeError(f'the feeder did not finish the card within {FEEDER_WAIT_S} s')
            self._sleep(0.2)

    def close(self):
        pass                             # nothing held between cards


def _way_out():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.0.2.1', 9))
            return probe.getsockname()[0]
    except OSError:
        return None


def station_addresses():
    """This machine's IPv4 addresses on its networks (not loopback): where to look for feeders - the way out first (the home
    network, usually; a PC also has Docker's and virtual machines' networks)"""
    found, out = set(), None
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    out = _way_out()                      # the address of the way out (no packet is sent by a UDP connect)
    rest = sorted(a for a in found if a != out and not ipaddress.IPv4Address(a).is_loopback)
    return ([out] if out and not ipaddress.IPv4Address(out).is_loopback else []) + rest


def find_feeders(addresses=None, wait=DISCOVERY_S, make_socket=None):
    """
    The feeders on this station's networks: [{'ip', 'name', 'mac', 'paired', 'station'}]. Asked by broadcast AND by asking
    every address of each /24 directly: a firewall (ufw on the owner's PC, 2026-11-12) lets in the answer to a direct
    question but not the answer to a broadcast, which comes from another address than the one asked.
    """
    if addresses is None:
        # The network the way out is on - the home network a feeder joins. Not Docker's or virtual machines' (asking all of
        # them took 14 s on the owner's PC, 2026-11-12, against 1.5): all of them only when there is no way out
        addresses = station_addresses()[:1] if _way_out() else station_addresses()
    nets = list(dict.fromkeys(ipaddress.IPv4Interface(f'{a}/24').network for a in addresses))   # in order, once each
    try:
        sock = make_socket() if make_socket else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError as e:
        raise ValueError(f'The station cannot look for feeders ({e})') from None
    found = {}
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        for net in nets:
            for target in [str(net.broadcast_address)] + [str(h) for h in net.hosts()]:
                for _ in range(50):       # the socket's buffer full (~1300 questions on a PC with Docker): wait, never skip
                    try:
                        sock.sendto(DISCOVERY_ASK, (target, DISCOVERY_PORT))
                        break
                    except (BlockingIOError, InterruptedError):
                        time.sleep(0.002)
                    except OSError:       # that address cannot be reached from here
                        break
        until = time.monotonic() + wait
        while time.monotonic() < until:
            try:
                data, (ip, _port) = sock.recvfrom(1024)
            except (BlockingIOError, InterruptedError):
                time.sleep(0.02)
                continue
            except OSError:
                break
            try:
                me = json.loads(data)
            except ValueError:
                continue
            if isinstance(me, dict) and me.get('feeder'):
                found[ip] = {'ip': ip, 'name': str(me['feeder'])[:FEEDER_NAME_MAX], 'mac': me.get('mac'),
                             'paired': bool(me.get('paired')), 'station': me.get('station')}
    finally:
        sock.close()
    return sorted(found.values(), key=lambda f: f['ip'])


def pair_feeder(ip, config_key, station_name, http=feeder_http):
    """
    Pair the feeder at ip with this station: its config key (the owner's, typed once on the page - not kept) lets this
    station give it a pair key of its own, which then feeds the cards. {'feeder': {...}, 'pair_key'}, or ValueError why not.
    """
    try:
        ipaddress.IPv4Address(ip)
    except (ValueError, TypeError):
        raise ValueError('Not a feeder\'s address') from None
    if not config_key:
        raise ValueError('Type the feeder\'s key (the one set on its Wi-Fi page)')
    pair_key = secrets.token_urlsafe(24)           # 32 printable characters, no spaces
    try:
        code, answer = http(f'http://{ip}/pair', {'config_key': config_key, 'pair_key': pair_key,
                                                  'station': str(station_name)[:FEEDER_NAME_MAX] or 'station'})
    except OSError as e:
        raise ValueError(f'The feeder at {ip} does not answer ({e})') from None
    if code != 200 or not answer.get('paired'):
        raise ValueError(answer.get('error') or f'The feeder did not pair ({code})')
    feeder = {'ip': ip, 'name': str(answer.get('feeder') or 'feeder')[:FEEDER_NAME_MAX], 'mac': answer.get('mac')}
    return {'feeder': feeder, 'pair_key': pair_key}


class Dropper:
    """
    The station's card dropper: its settings (configure) and one pulse at a time (pulse). Thread-safe: the capture's thread,
    the server's commands and the review's answer may all ask for a pulse; a second one while the first is still on its way is
    refused, never queued - one card per pulse.
    """

    def __init__(self, open_pin=GpiodPin, sleep=time.sleep, open_feeder=WifiFeeder):
        self.config = dict(DEFAULTS)
        self._open_pin = open_pin          # tests hand in a stand-in for the pin
        self._open_feeder = open_feeder    # ... and for the feeder over Wi-Fi
        self._sleep = sleep
        self._pin = None
        self._lock = threading.Lock()      # held for the whole pulse
        self.pulses = 0                    # cards released since the station started
        self.error = None                  # why the last pulse could not be sent (None: it was, or none was asked for)
        self.last_pulse = None             # time.time() of the last pulse sent

    @property
    def enabled(self):
        return bool(self.config['enabled'])

    def configure(self, config):
        """New settings (ValueError when they are wrong: the old ones stay). The pin is let go when it is no longer the same pin"""
        values = checked(config)
        with self._lock:
            same_pin = all(values[key] == self.config[key] for key in ('transport', 'chip', 'pin', 'active_low', 'feeder', 'pair_key'))
            if not same_pin or not values['enabled']:
                self._close_pin()
            self.config = values
            if not values['enabled']:
                self.error = None          # an old error says nothing about a dropper that is off
        return values

    def pulse(self, reason='', gate=None):
        """
        Release one card: the pin active for pulse_ms, then inactive again. True when it was sent; False when the dropper is off,
        a pulse is still under way, the gate said no, or the pin cannot be used (then `error` says why). Never raises: a dropper
        that fails must not stop the scanning, which goes on by hand.
        gate: the caller's last word, a context manager factory whose value says whether the card is still wanted. It is entered
        AFTER the line is opened and the pin is set active INSIDE it: the caller holds its own lock there, so whatever could cancel
        the release (scanning stopped, the dropper switched off) happens wholly before the check - refused - or after the pin is
        active - the card already on its way (a Codex review of 2026-10-22: a check, then the line opened, then the pin, left a
        gap a stop and restart fell into: two cards, no capture between).
        """
        if not self.enabled:
            return False
        if not self._lock.acquire(blocking=False):
            logger.warning(f"Card dropper: still releasing the previous card - not another one ({reason})")
            return False
        try:
            # Again, now under the lock configure() changes the settings under: switched off between the check above and here,
            # nothing is opened or activated (a Codex review of 2026-10-22). From here on the settings cannot change
            if not self.config['enabled']:
                return False
            if self._pin is None:
                try:
                    if self.config['transport'] == 'wifi':
                        self._pin = self._open_feeder(self.config['feeder']['ip'], self.config['pair_key'])
                    else:
                        self._pin = self._open_pin(self.config['chip'], self.config['pin'], self.config['active_low'])
                except Exception as e:
                    self._fail(e)
                    return False
            try:
                if gate is None:
                    self._pin.set(True)
                else:
                    with gate() as wanted:
                        if not wanted:
                            logger.info(f"Card dropper: no longer wanted at the last moment - no card released ({reason})")
                            return False          # (the finally below sets the pin inactive: it already is - harmless)
                        self._pin.set(True)
                if self.config['transport'] == 'gpio':
                    self._sleep(self.config['pulse_ms'] / 1000)   # (a feeder: set(False) below waits until the card is done)
            finally:
                # Inactive again whatever happened: a pin left active would hold the mechanism open
                try:
                    self._pin.set(False)
                except Exception as e:
                    self._fail(e)
                    self._close_pin()
                    return False
            self.pulses += 1
            self.last_pulse = time.time()
            self.error = None
            logger.info(f"Card dropper: card released ({reason}) - {self.pulses} since the start")
            return True
        except Exception as e:
            self._fail(e)
            self._close_pin()
            return False
        finally:
            self._lock.release()

    def state(self):
        """What the server shows on the Settings page"""
        return {'enabled': self.enabled, 'pulses': self.pulses, 'error': self.error, 'last_pulse': self.last_pulse}

    def close(self):
        with self._lock:
            self._close_pin()

    # -- inside ---------------------------------------------------------------------------------------------------------------

    def _fail(self, error):
        message = str(error) or error.__class__.__name__
        if message != self.error:          # said once, not at every card
            logger.error(f"Card dropper: {message}")
        self.error = message

    def _close_pin(self):
        if self._pin is not None:
            self._pin.close()
            self._pin = None
