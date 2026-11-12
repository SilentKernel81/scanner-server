#!/usr/bin/env python3
"""
Camera station: runs next to the camera, on any Linux machine. It finds the card, captures it
once it is still and keeps the focus (CardScanner - the same code and thresholds as ever), and
sends each captured card to the scanner server, which reads it, matches it and keeps the
collection. The server's scanner page shows this camera's live view and controls it.

    python station.py --server http://192.168.1.20:5000      (station.py, in the top folder, starts this)
    (or SCANNER_SERVER / SCANNER_STATION_ID / SCANNER_STATION_NAME / SCANNER_STATION_TOKEN)

or without any of that: the station then serves its setup page (station_setup.py,
http://<this machine>:8080), where the server, the station's name and the camera are chosen
and saved in data/station.json.

Little else is kept here: camera settings (focus, rotation, fixed area) are saved on the
server, and a captured image is deleted once the server has it. Until then it lies in
station_captures/ with a note beside it (<image>.upload.json) saying what it is and where it
goes, so that a capture taken while the server was away is still sent after this program -
or the whole machine - has been restarted. Resolution and the capture thresholds are in
config.yaml. See remote_scanner.py for the messages.
"""

import argparse
import contextlib
import json
import logging
import os
import queue
import re
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import cv2
import requests
import signal
import socketio

from card_scanner.station import station_setup
from card_scanner.station import dropper as dropper_module
from card_scanner.station.dropper import Dropper
from card_scanner.config import Config

NAMESPACE = '/station'
STATUS_INTERVAL = 0.2    # seconds between status reports
DROP_WAIT_FOR_FOCUS = 20.0  # seconds a card release waits for a focus check or a refocus sweep to end (a sweep takes ~8 s)
PREVIEW_INTERVAL = 0.08  # at most ~12 preview frames a second, while the page is watched
NOTE_SUFFIX = '.upload.json'  # the note beside a capture that is not on the server yet
# What the server may call and set (remote_scanner.py: METHODS, DECIDED, SENT)
METHODS = ('set_rotation', 'set_refocus_every', 'set_refocus_on_drop', 'set_fixed_area', 'set_detection_enabled',
           'set_continuous_autofocus', 'reset_focus', 'detected_area')
SETTABLE = ('fast_scan_mode', 'required_stable_frames', 'auto_capture_delay', 'debug_trace_enabled',
            'auto_capture_enabled', 'card_under_review', 'capture_pending', 'stable_frames')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger('station')
# CardScanner's lines for the page are logged here (send_log), not a second time by its own
# logger; what it writes to the log only (why a card waits, focus probes, saved debug frames)
# has no other way to this console
logging.getLogger('scanner').propagate = False
scanner_console = logging.StreamHandler()
scanner_console.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S'))
scanner_console.addFilter(lambda record: record.funcName != 'log')
logging.getLogger('scanner').addHandler(scanner_console)


class ServerSettings:
    """The camera's settings as CardScanner uses them (get / set): kept by the server"""

    def __init__(self, values, on_change):
        self.values = dict(values)
        self.on_change = on_change

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        self.on_change(key, value)


class Station:
    # Seconds between attempts at hello while the connection lasts (the last one repeats): a hello whose answer is lost is asked again,
    # or the card dropper - held until hello succeeds (dropper_synced) - would wait on a healthy connection for ever (a Codex review)
    HELLO_RETRY_DELAYS = (1, 2, 5, 10, 30)

    def __init__(self, server, station_id, name, token):
        self.server = server.rstrip('/')
        self.id = station_id
        self.name = name
        self.token = token
        self.setup_port = 0  # the port of this station's setup page (0: none): told to the server, which links to it
        self.scanner = None
        self.capture_number = 0
        self.last_capture_id = None  # of the capture before the one being queued
        self.preview_wanted = False
        self.stopping = False  # Set to leave run(): the setup page saved new settings (request_restart)
        self.uploads = queue.Queue()
        self.upload_idle = threading.Event()  # Clear while a capture is being sent (wait_for_upload)
        self.upload_idle.set()
        # Captures found at the start that were taken for another server or under another
        # station id: kept, not sent, until the setup page says what to do with them
        self.held = []
        self.held_lock = threading.Lock()
        # The card dropper (dropper.py): off until the server's settings switch it on. drop_owed: with auto-add off, (capture_id,
        # scanning session) of the capture whose next card is owed - released only when the server says THAT capture was added,
        # skipped or sent to the review queue (on_review_done), never on an error or a stop. Set, paid and cleared under release_lock
        self.dropper = Dropper()
        self.drop_owed = None
        # The releases (release_next_card): one runs at a time (wait for the focus, then the pulse); one more asked for meanwhile is
        # kept and runs right after - a card captured while the previous pulse was still on its way owes its next card all the same
        # (a Codex review of 2026-10-22: refusing it stalled the feeding for good). A third is refused: one card per capture
        self.release_lock = threading.Lock()
        # Held while the server's settings are applied - a hello's answer, or a live 'set' - so that they are applied one after the
        # other, in the order the server sent them: a hello whose connection has ended is refused under it BEFORE it changes anything
        # (a Codex review of 2026-10-22: a stale hello applied its settings first and checked after - its 'dropper on' undid a newer
        # 'off'). Reentrant: hello applies through on_set. Taken before release_lock, never the other way
        self.settings_lock = threading.RLock()
        # The newest number (remote_scanner: '_revision') applied, setting by setting, and the server start they belong to: an older
        # value - a hello's answer overtaken by a live change, a live change overtaken by a hello - is ignored (a Codex review of
        # 2026-10-22). Per setting: a delayed change of one setting must not hide a newer change of another. Under settings_lock
        self.settings_server = None
        self.settings_revisions = {}
        self.release_busy = False
        self.release_pending = None     # (reason, scanning session) of the release kept for after the current one
        # The scanning session: one more each time auto-scanning is switched on or off, and when the dropper is switched off. A release belongs to the session that asked
        # for it and is refused before its pulse once another has begun - a release still waiting for the focus when scanning was
        # stopped and started again would otherwise pulse beside the new session's first card: two cards, no capture between
        # (a Codex review of 2026-10-22)
        self.scan_session = 0
        self.last_capture_session = None   # the session the latest capture started in: the first card is owed only by a session that has none
        # Connected to the server and its hello applied: only then may a card be released. While the Socket.IO connection is down the
        # server's stop cannot reach this station (uploads may still get through over HTTP), so a release that comes up then is KEPT
        # (release_deferred) and decided after the next hello - by then a stop pressed meanwhile has been replayed and has made it
        # stale (a Codex review of 2026-10-22: a stop during an outage was followed by more cards)
        self.dropper_synced = False
        self.release_deferred = None
        # The connection's number: one more at every connect and disconnect. A hello belongs to the connection it was started for, and
        # marks the station in step only if that connection is still the current one - a disconnect while its answer is being applied
        # must not be undone by it (a Codex review of 2026-10-22). Changed and read under release_lock
        self.connection = 0       # (reason, session, first) of the release kept until the station is in step again
        self.sio = socketio.Client(reconnection=True, reconnection_delay=1, reconnection_delay_max=5)
        self.sio.on('connect', self.on_connect, namespace=NAMESPACE)
        self.sio.on('disconnect', self.on_disconnect, namespace=NAMESPACE)
        self.sio.on('command', self.on_command, namespace=NAMESPACE)
        self.sio.on('set', self.on_set, namespace=NAMESPACE)
        self.sio.on('review_done', self.on_review_done, namespace=NAMESPACE)

    # ------------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------------

    def run(self):
        self.load_pending()  # captures an earlier run could not send, before any new one
        threading.Thread(target=self.upload_loop, daemon=True, name="Uploads").start()
        while not self.stopping:
            try:
                self.sio.connect(self.server, namespaces=[NAMESPACE], wait_timeout=10,
                                 auth={'id': self.id, 'name': self.name, 'token': self.token,
                                       'setup_port': self.setup_port})
                break
            except socketio.exceptions.ConnectionError as e:
                logger.warning(f"Server {self.server} not reachable ({e}) - trying again in 3 s")
                time.sleep(3)
        try:
            self.report_loop()
        except KeyboardInterrupt:
            pass
        finally:
            if self.scanner:
                self.scanner.cleanup()
            self.dropper.close()   # the pin is let go (it was left inactive after the last pulse)
            self.sio.disconnect()

    def connected(self):
        return self.sio.connected and NAMESPACE in self.sio.namespaces

    def emit(self, event, data, callback=None):
        if self.connected():
            try:
                self.sio.emit(event, data, namespace=NAMESPACE, callback=callback)
            except socketio.exceptions.SocketIOError:
                pass  # the connection just went: the next report will find out

    def on_connect(self):
        logger.info(f"Connected to {self.server} as {self.name} ({self.id})")
        with self.release_lock:
            self.connection += 1
            connection = self.connection
        # Not from this handler's thread: hello waits for the server's answer
        threading.Thread(target=self.hello, args=(connection,), daemon=True).start()

    def on_disconnect(self, *_args):
        logger.warning("Connection to the server lost - scanning goes on, captures wait to be sent")
        self.preview_wanted = False
        with self.release_lock:
            self.connection += 1            # a hello still under way belongs to a connection that has ended (see hello)
            self.dropper_synced = False     # no card is released until the next hello (see dropper_synced)

    def hello(self, connection=None):
        """
        Take the camera's settings from the server; the first time, start the scanner with them. Asked again while the same connection
        lasts (HELLO_RETRY_DELAYS); only a hello of the connection still current puts the station in step (dropper_synced)
        """
        if connection is None:
            connection = self.connection
        delays = iter(self.HELLO_RETRY_DELAYS)
        delay = next(delays)
        while True:
            if self.stopping or connection != self.connection:
                return                      # that connection has ended: the next one asks for itself
            try:
                answer = self.sio.call('hello', {}, namespace=NAMESPACE, timeout=10) or {}
                break
            except Exception as e:
                logger.error(f"The server did not answer hello: {e} - asking again in {delay} s")
                time.sleep(delay)
                delay = next(delays, delay)
        with self.settings_lock:
            # Too late? A newer connection's hello - or a disconnect - came while this answer was on its way: it changes NOTHING
            if connection != self.connection:
                logger.warning("The server's answer to hello came for a connection that has ended - not applied")
                return
            if self.scanner is None:
                from card_scanner.station.scanner import CardScanner  # opens the camera
                settings = ServerSettings(answer.get('settings') or {},
                                          lambda key, value: self.emit('setting', {'key': key, 'value': value}))
                scanner = CardScanner(log_callback=self.send_log, settings=settings)
                scanner.fast_scan_mode = True
                scanner.auto_capture_callback = self.auto_captured
                values = self._newer_only(answer.get('set') or {})
                self.apply(scanner, values)
                self.scanner = scanner
                if 'dropper' in values:           # (not when a newer live value has set it already)
                    self.configure_dropper(values['dropper'])
            else:
                # Through on_set: a stop the server replays (pressed while this station was away) goes through the session's
                # bookkeeping - a new session, everything pending, kept or deferred cleared - as a stop does when it comes live. Never a
                # START by connecting: that would release a card (the server sends none; refused here all the same)
                values = dict(answer.get('set') or {})
                if values.get('auto_capture_enabled'):
                    values.pop('auto_capture_enabled')
                self.on_set(values)
            # In step with the server again: releases may go - if this hello's connection is still the current one (a disconnect
            # while its answer was being applied has made it stale: the station stays out of step until the next hello). Never a card
            # released by connecting itself - only ...
            with self.release_lock:
                if connection != self.connection:
                    logger.warning("Card dropper: the connection went while its hello was applied - not in step until the next one")
                    return
                self.dropper_synced = True
                deferred, self.release_deferred = self.release_deferred, None
        # ... the one owed for a capture the page settled while this station was away: the server repeats the last settled capture at
        # every connection, and on_review_done pays only a debt for exactly that capture, once ...
        if answer.get('review_done'):
            self.on_review_done({'capture_id': answer['review_done']})
        # ... and a release that came up during the outage, if its session still runs (a replayed stop has made it stale)
        if deferred:
            self.release_next_card(deferred[0], session=deferred[1], first=deferred[2])

    @staticmethod
    def apply(scanner, values):
        for name, value in values.items():
            if name in SETTABLE:
                setattr(scanner, name, value)

    def send_log(self, message, level="info"):
        getattr(logger, 'info' if level == 'success' else level, logger.info)(message)
        self.emit('log', {'message': message, 'level': level})

    # ------------------------------------------------------------------------
    # What the server asks for
    # ------------------------------------------------------------------------

    def state(self):
        """What the server shows and decides by (RemoteScanner: REPORTED and SENT names, the camera settings)"""
        s = self.scanner
        # Read BEFORE the switch: the number of the last scanning change applied, which the server's waiting stop is confirmed by
        # (RemoteScanner._take_state) - read first, a newer change can only make the state that follows newer, never older
        applied = self.settings_revisions.get('auto_capture_enabled')
        return {
            'auto_capture_revision': [self.settings_server, applied] if applied is not None else None,
            'camera_error': s.camera_error, 'camera_type': s.camera_type,
            'auto_capture_enabled': bool(s.auto_capture_enabled), 'card_under_review': bool(s.card_under_review),
            'capture_pending': bool(s.capture_pending), 'rotation': s.rotation, 'refocus_every': s.refocus_every,
            'refocus_on_drop': s.refocus_on_drop,
            'fixed_area': s.fixed_area, 'fixed_area_enabled': bool(s.fixed_area_enabled),
            'focus_locked_value': s.focus_locked_value, 'focus_sweep_running': bool(s.focus_sweep_running),
            'focus_probe_running': bool(s.focus_probe_running), 'enable_detection': bool(s.enable_detection),
            'dropper_state': self.dropper.state(),
        }

    def on_set(self, values):
        """The server's settings for this station (live, or from hello's answer): applied one at a time (settings_lock), newer only"""
        with self.settings_lock:
            self._apply_set(self._newer_only(values or {}))

    def _newer_only(self, values):
        """
        values without the settings this station has had a newer value of (settings_revisions); under settings_lock. A server
        that numbers nothing (an older one) has everything applied, as before
        """
        values = dict(values)
        revision = values.pop('_revision', None)
        if not (isinstance(revision, (list, tuple)) and len(revision) == 2):
            return values
        server, number = revision
        if server != self.settings_server:     # another server start: its numbers begin again
            self.settings_server, self.settings_revisions = server, {}
        newer = {}
        for name, value in values.items():
            if number < self.settings_revisions.get(name, -1):
                logger.info(f"An older value of {name} from the server - ignored, a newer one is applied")
                continue
            self.settings_revisions[name] = number
            newer[name] = value
        return newer

    def _apply_set(self, values):
        if 'dropper' in values:
            self.configure_dropper(values['dropper'])
        if self.scanner:
            scanner = self.scanner
            started = None                    # the session a start began (its first card belongs to it)
            if 'auto_capture_enabled' in values:
                # The whole switch under release_lock, from reading the old state to the new one - and nowhere else: a start paused
                # between its check and its write must not switch scanning back on after a stop that came meanwhile (a Codex review
                # of 2026-10-22: written again by apply outside the lock, a start undid the later stop and released a card).
                # Scanning switched on or off: the new session begins - everything asked for before is stale - and only THEN is the
                # switch itself made (the lock a capture reads its session under, _auto_captured): a capture that starts the moment
                # scanning is on can only see the new session (the review before: switched on first, a capture in that instant took
                # the old one, the new one refused its release - the feeding stopped)
                wanted = bool(values['auto_capture_enabled'])
                with self.release_lock:
                    if wanted != bool(scanner.auto_capture_enabled):
                        self.scan_session += 1
                        self.release_pending = None
                        self.release_deferred = None
                        self.drop_owed = None
                        scanner.auto_capture_enabled = wanted
                        if wanted:
                            started = self.scan_session
                values = {name: value for name, value in values.items() if name != 'auto_capture_enabled'}
            self.apply(scanner, values)       # the rest (the switch is made above, under the lock, only)
            self.after_set(started)

    def after_set(self, started):
        """
        What the server's settings change for the card dropper, once applied (the session moved already, in on_set). Auto-scanning
        switched on (started: the session that start began): the first card is released - for THAT session, so a stop that came
        meanwhile makes it stale - and only into an empty field (_still_wanted, first=True): a card already in view brings the
        next one by its own capture. card_under_review going back to False pays NOTHING: the server clears it on errors and stops
        too (on_review_done pays).
        """
        if started is not None:
            self.release_next_card('scanning started', session=started, first=True)

    def on_review_done(self, data=None):
        """
        The server: the live capture capture_id was added or skipped on the page, or went to the review queue by itself
        (desks.review_done). The card owed for exactly that capture is released; any other capture_id - a manual capture, an
        older one - releases nothing.
        """
        capture_id = (data or {}).get('capture_id')
        with self.release_lock:
            owed = self.drop_owed
            if not owed or owed[0] != capture_id:
                return
            self.drop_owed = None
        self.release_next_card('the card was added or skipped', session=owed[1])

    # ------------------------------------------------------------------------
    # The card dropper (dropper.py: what it does; here: when)
    # ------------------------------------------------------------------------

    def configure_dropper(self, config):
        """The dropper's settings from the server; wrong ones are refused (the server checks them first: dropper.checked)"""
        try:
            values = self.dropper.configure(config)
        except ValueError as e:
            logger.error(f"Card dropper: the server's settings are refused ({e}) - it stays as it was")
            return
        if not values['enabled']:
            # Off: everything asked for before is cancelled - the debt, the release kept for later, and the one waiting for the focus
            # (a new session: _release refuses it right before its pulse). Switched on again, nothing of before can come back
            # (a Codex review of 2026-10-22). Other changes (the pulse, the pin) while it stays on cancel nothing: a card waiting
            # for its release would then never come
            with self.release_lock:
                self.drop_owed = None
                self.release_pending = None
                self.scan_session += 1

    def release_next_card(self, reason, session=None, first=False):
        """
        Release the next card onto the pile (dropper on only), in the background: the caller is the capture's thread or the
        connection's. It first waits for a focus check or a refocus sweep to end (a card falling while the lens moves is a
        blurred card), at most DROP_WAIT_FOR_FOCUS; then, if auto-scanning is still on and the camera is there, one pulse.
        One release runs at a time; one more asked for meanwhile is kept and runs right after it (a card captured while the
        previous pulse was still on its way); a third is refused - one card per capture, never more.
        """
        if not self.dropper.enabled or self.scanner is None:
            return
        with self.release_lock:
            # The session asking: a capture's own (taken when it started), else the current one. A release outlives none
            session = self.scan_session if session is None else session
            if session != self.scan_session:
                logger.info(f"Card dropper: asked for in a scanning session that has ended - no card released ({reason})")
                return
            if self.release_busy:
                if self.release_pending is None:
                    self.release_pending = (reason, session, first)
                    logger.info(f"Card dropper: after the release under way ({reason})")
                else:
                    logger.warning(f"Card dropper: a release is already kept for later - not another one ({reason})")
                return
            self.release_busy = True
        threading.Thread(target=self._release_loop, args=(reason, session, first), daemon=True, name="Card dropper").start()

    def _release_loop(self, reason, session, first=False):
        """The releases, one after the other: this one, then the one kept meanwhile (if any), then the thread ends"""
        while True:
            try:
                self._release(reason, session, first)
            except Exception as e:
                logger.exception(f"Card dropper: the release failed ({reason}): {e}")
            with self.release_lock:
                kept, self.release_pending = self.release_pending, None
                if kept is None:
                    self.release_busy = False
                    return
            reason, session, first = kept

    def _release(self, reason, session, first=False):
        """One release: wait for the focus to settle, check the scanning still wants a card - in the same session - then one pulse"""
        scanner = self.scanner
        deadline = time.time() + DROP_WAIT_FOR_FOCUS
        while (scanner.focus_sweep_running or scanner.focus_probe_running) and time.time() < deadline:
            time.sleep(0.05)
        if scanner.focus_sweep_running or scanner.focus_probe_running:
            self.send_log("Card dropper: the focus is still being adjusted - drop the next card by hand", level="warning")
            return
        if not scanner.auto_capture_enabled:
            logger.info(f"Card dropper: auto-scanning was stopped meanwhile - no card released ({reason})")
            return
        if getattr(scanner, 'camera', None) is None:
            logger.info(f"Card dropper: the camera is not there - no card released ({reason})")
            return
        if session != self.scan_session:
            # Asked for in a scanning session that has ended (stopped, perhaps started again since): not this session's card
            logger.info(f"Card dropper: scanning was stopped meanwhile - no card released ({reason})")
            return
        # Checked again at the very last moment, atomically with the pin going active (the gate): the checks above are early answers
        if not self.dropper.pulse(reason, gate=lambda: self._still_wanted(session, first, reason)) and self.dropper.error:
            self.send_log(f"Card dropper: {self.dropper.error} - drop the next card by hand", level="error")

    @contextlib.contextmanager
    def _still_wanted(self, session, first=False, reason=''):
        """
        The dropper's gate (Dropper.pulse): held under release_lock - the lock every cancellation takes (on_set, configure_dropper) -
        while the pin goes active, so a stop, a restart or the dropper switched off cannot fall between this check and the pulse.
        first (the card released when scanning starts): only while this session has had no capture and none is coming - a capture
        under way, or a card in view not captured yet. Such a card brings the next one by its own capture; the start's card as
        well would be two cards for one capture, one of them dropped onto a card being captured. A card in view that was captured
        before (it lies on the pile: awaiting_new_card, another session) does not hold it back. A restart during a capture thus
        releases nothing - that capture is the old session's - and the feeding waits ("Drop one card" goes on): never two cards
        """
        scanner = self.scanner
        with self.release_lock:
            if not self.dropper_synced:
                # The server cannot be heard (a stop may be on its way): kept, decided after the next hello - never pulsed now
                if self.release_deferred is None:
                    self.release_deferred = (reason, session, first)
                logger.info(f"Card dropper: not connected to the server - the release waits for it ({reason})")
                yield False
                return
            wanted = (session == self.scan_session and scanner is not None and bool(scanner.auto_capture_enabled)
                      and getattr(scanner, 'camera', None) is not None)
            if wanted and first:
                coming = (self.last_capture_session == self.scan_session or bool(scanner.capture_pending)
                          or (scanner.is_card_detected() and not getattr(scanner, 'awaiting_new_card', False)))
                wanted = not coming
                if coming:
                    logger.info("Card dropper: a card is about to be captured - it brings the next one by its own capture")
            yield wanted

    def drop_card(self):
        """The Settings page's "Drop one card": one pulse now, whatever the scanning is doing - to try the mechanism"""
        if not self.dropper.enabled:
            raise ValueError('The card dropper is off')
        if not self.dropper.pulse('a test from the Settings page'):
            raise ValueError(self.dropper.error or 'A card is still being released')
        return self.dropper.pulses

    def on_command(self, data):
        """Run a CardScanner method for the server; the answer carries the state after it"""
        if self.scanner is None:
            return {'ok': False, 'error': 'The camera is still starting'}
        method = (data or {}).get('method')
        try:
            if method == 'capture':
                threading.Thread(target=self.manual_capture, daemon=True).start()
                result = True
            elif method == 'drop_card':       # the station's own, not CardScanner's: the dropper is the station's
                result = self.drop_card()
            elif method == 'find_feeders':    # a feeder over Wi-Fi is found from the station: it is on the station's network
                result = dropper_module.find_feeders()
            elif method == 'pair_feeder':     # (ip, config_key): the pair key goes back to the server, which keeps it
                result = dropper_module.pair_feeder(*data.get('args', [])[:2], station_name=self.name)
            elif method in METHODS:
                result = getattr(self.scanner, method)(*data.get('args', []), **data.get('kwargs', {}))
            else:
                return {'ok': False, 'error': f'Unknown command {method}'}
        except (TypeError, ValueError) as e:
            return {'ok': False, 'error': str(e)}
        return {'ok': True, 'result': result, 'state': self.state()}

    def report_loop(self):
        """Status several times a second; the preview while the scanner page is watched"""
        last_status = last_preview = 0.0
        last_frame = -1
        while not self.stopping:
            time.sleep(0.02)  # the two intervals below are checked 50 times a second
            scanner = self.scanner
            if scanner is None or not self.connected():
                continue  # still starting, or the server is away: scanning goes on without reports
            now = time.time()
            if now - last_status >= STATUS_INTERVAL:
                last_status = now
                self.emit('status', {'state': self.state(), 'detection': scanner.get_detection_status()},
                          callback=self.status_answered)
            if self.preview_wanted and now - last_preview >= PREVIEW_INTERVAL:
                frame_id, jpeg = scanner.get_stream_jpeg()
                if jpeg is not None and frame_id != last_frame:
                    last_frame, last_preview = frame_id, now
                    self.emit('preview', {'jpeg': jpeg})

    def status_answered(self, answer=None):
        self.preview_wanted = bool((answer or {}).get('preview'))

    # ------------------------------------------------------------------------
    # Captures
    # ------------------------------------------------------------------------

    def auto_captured(self):
        """CardScanner's auto-capture callback (its own thread): take the image, beep, send it"""
        scanner = self.scanner
        try:
            self._auto_captured(scanner)
        except Exception as e:
            # Whatever went wrong, the scanner must not stay "capturing" or "under review" - the
            # next card would never be taken (until the server sent a reset)
            logger.exception(f"Auto-capture failed: {e}")
            scanner.capture_pending = False
            scanner.card_under_review = False
            self.send_log(f"The capture failed ({e}) - ready for the next card", level="error")

    def _auto_captured(self, scanner):
        # The card dropper's scanning session as the capture STARTS: a capture still running when scanning was stopped and started
        # again belongs to the old session - its release, or the card it would owe, is refused (a Codex review of 2026-10-22).
        # Read under release_lock - the lock scanning is switched on under (on_set), so never "on, but the old session" - and so that
        # it cannot fail: nothing of the dropper may cost a card (a station built without it just releases nothing)
        session = self._capture_session()
        fast = bool(getattr(scanner, 'fast_scan_mode', True))  # as it is now, not when it is sent
        if not scanner.is_card_detected():
            logger.warning("Auto-capture triggered but no card detected")
            scanner.capture_pending = False
            scanner.card_under_review = False
            return
        self.capture_number += 1
        number = self.capture_number
        # The moment the scanner decided to capture (CardScanner._trigger_auto_capture): the beep's
        # delay is counted from it
        triggered = getattr(scanner, 'last_auto_capture_time', 0) or time.time()
        image_path, card_image, foil_image = scanner.capture_card_image_only(number, settle=0)
        if not image_path:
            # The picture could not be saved (the scanner said why): the card is not captured, and
            # the person is told - not left waiting for a beep
            scanner.capture_pending = False
            scanner.card_under_review = False
            self.send_log("The card was not captured: its picture could not be saved - check the station's disk", level="error")
            return
        image_taken = time.time()
        # The capture beep - the signal to drop the next card: once the image is taken and a
        # focus probe started by this capture (~1 s, every refocus_every cards) is done
        deadline = time.time() + 2.5
        while scanner.focus_probe_running and time.time() < deadline:
            time.sleep(0.05)
        scanner.capture_pending = False
        self.emit('captured', {'number': number})
        # Where the time between the capture and the beep went (log file only; the rest of the
        # way - the server, the page, the speakers - is not measured here)
        beep_sent = time.time()
        logger.info(f"Capture #{number}: image taken {(image_taken - triggered) * 1000:.0f} ms after the decision, "
                    f"beep sent {(beep_sent - triggered) * 1000:.0f} ms after it"
                    + (f" (waited {(beep_sent - image_taken) * 1000:.0f} ms for the focus probe)"
                       if beep_sent - image_taken > 0.15 else ""))
        if fast:
            scanner.card_under_review = False  # ready for the next drop; else until Add / Skip on the page
        # The capture's id made HERE, before the upload exists: with auto-add off the card dropper's debt for it is recorded
        # first, so the server's review_done for it - which may come as soon as the upload is sent - always finds it
        # (a Codex review of 2026-10-22: recorded after queue_upload, a quick answer was lost and the feeding stopped)
        capture_id = uuid.uuid4().hex
        if not fast:
            self.owe_drop(capture_id, session, number)
        # Auto-add on: the next card is released once the server has ANSWERED this upload, and not with "card back" (after_upload) -
        # the card-back check is the server's, and a release at queue time buried the face-down card meant to stop the stack, or went
        # on feeding for as long as the server was away (a Codex review of 2026-10-22). The upload carries the session it belongs to
        self.queue_upload(image_path, card_image, foil_image, 'auto' if fast else 'review',
                          getattr(scanner, 'last_capture_frame', None), capture_id=capture_id,
                          release_session=session if fast else None)

    def _capture_session(self):
        """The scanning session a capture starts in (None for a station built without the dropper's state: it releases nothing)"""
        lock = getattr(self, 'release_lock', None)
        if lock is None:
            return None
        with lock:
            self.last_capture_session = self.scan_session     # this session has a capture: it, not the start, brings the next card
            return self.scan_session

    def owe_drop(self, capture_id, session, number):
        """
        Auto-add off: the next card is owed for this capture until the server says it was added, skipped or queued for review
        (on_review_done) - only while the dropper is on and the session the capture started in still runs. Never raises.
        """
        try:
            with self.release_lock:
                if self.dropper.enabled and session == self.scan_session:
                    self.drop_owed = (capture_id, session)
        except Exception as e:
            logger.exception(f"Card dropper: no card owed for capture #{number}: {e}")

    def after_upload(self, item, status):
        """
        The server ANSWERED an auto-add capture's upload (send_until_settled, 'accepted'): the card-back check is behind it. A card back
        stops the stack - nothing is released (the server switches auto-capture off); anything else releases the next card, for the
        session the capture started in. A capture without release_session (auto-add off, a manual one, one sent again after a restart)
        releases nothing here. Never raises: the upload is settled whatever the dropper does.
        """
        session = item.get('release_session')
        if session is None:
            return
        name = item['image'].name if item.get('image') else 'a capture'
        try:
            if status == 'card_back':
                logger.info(f"Card dropper: {name} was a card back - no card released, the stack ends here")
                return
            self.release_next_card(f'after {name}', session=session)
        except Exception as e:
            logger.exception(f"Card dropper: nothing released after {name}: {e}")

    def manual_capture(self):
        """The page's Capture button: whatever is in view, shown on the page for Add / Skip"""
        scanner = self.scanner
        self.capture_number += 1
        image_path, card_image, foil_image = scanner.capture_card_image_only(self.capture_number)
        if image_path:
            self.queue_upload(image_path, card_image, foil_image, 'review', getattr(scanner, 'last_capture_frame', None))
        else:
            self.send_log("Failed to capture image", level="error")

    def queue_upload(self, image_path, card_image, foil_image, mode, frame=None, capture_id=None, release_session=None):
        """
        frame: {'jpeg', 'meta'} - the camera frame the card was cut from (debug trace on, see
        CardScanner._frame_snapshot): kept beside the picture and sent with it as training data.
        capture_id: the capture's id when the caller made it already (an auto-capture: the card dropper's debt is keyed by it).
        release_session: auto-add on - the card dropper releases the next card once the server answered this upload (after_upload),
        for this scanning session. Kept with the item only, never in its note: a capture sent again after a restart owes no card
        """
        foil_path = None
        if foil_image is not None and foil_image is not card_image:
            # Fixed area: the capture is the area, the foil check uses the outlined card
            foil_path = Path(image_path).with_name(f"{Path(image_path).stem}_foil.jpg")
            cv2.imwrite(str(foil_path), cv2.cvtColor(foil_image, cv2.COLOR_RGB2BGR))
        item = {'image': Path(image_path), 'foil': foil_path, 'mode': mode,
                'foil_is_image': foil_image is card_image, 'capture_id': capture_id or uuid.uuid4().hex,
                'frame': None, 'frame_meta': None, 'release_session': release_session}
        if frame and frame.get('jpeg'):
            frame_path = Path(image_path).with_name(f"{Path(image_path).stem}_frame.jpg")
            try:
                frame_path.write_bytes(frame['jpeg'])
                # previous_capture_id: with the seconds between, a double capture is found as a pair
                item['frame'] = frame_path
                item['frame_meta'] = {**frame['meta'], 'station': self.id, 'capture_id': item['capture_id'],
                                      'previous_capture_id': self.last_capture_id}
            except OSError as e:
                logger.warning(f"Could not keep the camera frame of {Path(image_path).name} ({e}) - sent without it")
        self.last_capture_id = item['capture_id']
        # The note first, then the queue: from here on the capture is on record on disk,
        # whatever happens to this program
        self.write_note(item)
        self.uploads.put(item)

    # ------------------------------------------------------------------------
    # Captures that are not on the server yet
    #
    # The queue above lives in memory only. If this program ends with captures in it - a
    # restart from the setup page, a power cut, `docker compose up --build` - they used to
    # stay behind as pictures nobody would ever send. So each queued capture also has a
    # small note on disk beside its picture, and a new start reads the notes back.
    #
    # The note holds the capture's capture_id. That id is what makes sending a capture
    # twice harmless: the server counts an id once (server/state.py: seen_captures; pending.py: settled_captures).
    # A capture that was being sent when the program ended may or may not have arrived - it
    # is sent again with the same id, and is one card either way.
    #
    # The note also holds where the capture was going: the server's address and this
    # station's id. A capture is only sent on its own if both are still the same. If the
    # setup page changed either, the capture is "held": it may belong to another server's
    # collection, and which one is not for this program to guess - the setup page shows the
    # held captures and asks (send_held / delete_held).
    # ------------------------------------------------------------------------

    @staticmethod
    def note_path(image):
        """card_3_1791754770.jpg -> card_3_1791754770.upload.json"""
        return Path(image).with_name(Path(image).stem + NOTE_SUFFIX)

    def write_note(self, item):
        """Put a capture on record on disk (written whole or not at all, as station_setup.save)"""
        note = {'capture_id': item['capture_id'], 'mode': item['mode'], 'foil_is_image': bool(item['foil_is_image']),
                'image': item['image'].name, 'foil': item['foil'].name if item['foil'] else None,
                'frame': item['frame'].name if item.get('frame') else None, 'frame_meta': item.get('frame_meta'),
                'server': self.server, 'station': self.id, 'taken': time.strftime('%Y-%m-%d %H:%M:%S')}
        path = self.note_path(item['image'])
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(note, indent=2))
        os.replace(temporary, path)

    @staticmethod
    def remove_capture(item, keep_pictures=False):
        """A capture is settled: its note goes, and its pictures unless they are to be kept"""
        Station.note_path(item['image']).unlink(missing_ok=True)
        if not keep_pictures:
            for path in (item['image'], item['foil'], item.get('frame')):
                if path:
                    path.unlink(missing_ok=True)

    def load_pending(self):
        """
        At the start: queue the captures an earlier run left behind, oldest first. Those
        taken for another server or under another station id are held instead (see above).
        """
        self.adopt_old_folder()
        notes = sorted(Config.STATION_CAPTURES_DIR.glob('*' + NOTE_SUFFIX), key=lambda path: path.stat().st_mtime)
        queued = 0
        for path in notes:
            try:
                note = json.loads(path.read_text())
                item = {'image': path.with_name(note['image']),
                        'foil': path.with_name(note['foil']) if note.get('foil') else None,
                        'frame': path.with_name(note['frame']) if note.get('frame') else None,
                        'frame_meta': note.get('frame_meta'),
                        'mode': note['mode'], 'foil_is_image': bool(note.get('foil_is_image')),
                        'capture_id': note['capture_id'],
                        'server': note.get('server'), 'station': note.get('station'), 'taken': note.get('taken')}
            except (OSError, ValueError, KeyError, TypeError) as e:
                logger.warning(f"{path.name} is not a capture's note ({e}) - left alone")
                continue
            if not item['image'].is_file():
                path.unlink(missing_ok=True)  # the picture is gone: nothing to send
                continue
            if (item['server'], item['station']) == (self.server, self.id):
                self.uploads.put(item)
                queued += 1
            else:
                with self.held_lock:
                    self.held.append(item)
        if queued:
            logger.info(f"{queued} captured card{'s' if queued != 1 else ''} from before the restart will be sent now")
        if self.held:
            logger.warning(f"{len(self.held)} captured cards were taken for {self.held[0]['server']} "
                           f"(station {self.held[0]['station']}) and are kept, not sent - the setup page asks what to do with them")

    @staticmethod
    def adopt_old_folder():
        """
        Until 2026-10-12 a station kept its waiting captures in scanned_cards/ - the folder
        the server keeps the captures it received in, and cleans old pictures out of. On a
        machine that runs both programs from one checkout, a capture that waited longer than
        the server keeps pictures (cleanup.days) would have been deleted before it was ever
        sent. Waiting captures now have a folder of their own, station_captures/.

        This moves over what an earlier version left in the old folder: every note, with its
        picture and foil picture. Notes mark what is the station's - the server never writes
        them - so nothing of the server's is touched. It runs at every start and finds
        nothing after the first.
        """
        Config.STATION_CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        for note_path in sorted(Config.IMAGES_DIR.glob('*' + NOTE_SUFFIX)):
            try:
                note = json.loads(note_path.read_text())
                names = [note['image']] + ([note['foil']] if note.get('foil') else [])
                for name in names:
                    picture = note_path.with_name(name)
                    if picture.is_file():
                        os.replace(picture, Config.STATION_CAPTURES_DIR / name)
                os.replace(note_path, Config.STATION_CAPTURES_DIR / note_path.name)  # the note last: until then it is found here again
                logger.info(f"Moved a waiting capture to {Config.STATION_CAPTURES_DIR.name}/: {note['image']}")
            except (OSError, ValueError, KeyError, TypeError) as e:
                logger.warning(f"{note_path.name} could not be moved to {Config.STATION_CAPTURES_DIR.name}/ ({e}) - left where it is")

    def pending_count(self):
        """Captures taken but not on the server yet (queued or being sent), for the setup page"""
        return self.uploads.qsize() + (0 if self.upload_idle.is_set() else 1)

    def held_summary(self):
        """What the setup page shows about held captures: how many, and where they were going"""
        with self.held_lock:
            if not self.held:
                return None
            return {'count': len(self.held), 'server': self.held[0]['server'], 'station': self.held[0]['station'],
                    'oldest': self.held[0]['taken'], 'parked': sum(1 for item in self.held if item.get('parked'))}

    def send_held(self):
        """The setup page's "Send them to this server": the held captures join the queue"""
        with self.held_lock:
            held, self.held = self.held, []
        for item in held:
            self.write_note(item)  # the note now names this server: sent on its own from here on
            self.uploads.put(item)
        return len(held)

    def delete_held(self):
        """The setup page's "Delete them": the held captures' pictures and notes are removed"""
        with self.held_lock:
            held, self.held = self.held, []
        for item in held:
            self.remove_capture(item)
        return len(held)

    def wait_for_upload(self, seconds):
        """
        Before a restart: give a capture that is being sent right now the time to arrive.
        Not required for safety (it would be sent again under the same capture_id), but it
        spares the server a duplicate to recognise.
        """
        return self.upload_idle.wait(seconds)

    def upload_loop(self):
        """Send captures in order; one that can't be sent is tried again until it is"""
        session = requests.Session()
        while not self.stopping:
            try:
                item = self.uploads.get(timeout=0.5)  # not forever: `stopping` is looked at twice a second
            except queue.Empty:
                continue
            self.upload_idle.clear()
            try:
                self.send_until_settled(session, item)
            finally:
                self.upload_idle.set()

    # A capture the server answers again and again with something that is neither "received" nor
    # "refused" (an error page, a 5xx for this picture, a wrong token) is set aside after this many
    # answers, so that the captures behind it are not held up for ever. Not counted: no answer at all
    # (the server is away) - that is retried for ever, "at least once"
    PARK_AFTER_ANSWERS = 20

    def send_until_settled(self, session, item):
        """
        Send one capture, again and again until the server has it or refuses it for good. Left
        early only when the station is stopping: the capture's note stays, and the next start
        sends it. Set aside (parked, see park) after PARK_AFTER_ANSWERS odd answers.
        """
        delay = 1.0
        while not self.stopping:
            verdict = self.send_once(session, item)
            if verdict == 'retry' and item.get('odd_answers', 0) >= self.PARK_AFTER_ANSWERS:
                self.park(item)
                return
            if verdict == 'accepted':
                self.remove_capture(item)
                self.after_upload(item, item.get('answer_status'))   # the card dropper: the next card, unless this was a card back
                return
            if verdict == 'refused':
                # The server will never take this picture (unreadable, too large): it is kept
                # here, but its note goes - it is not sent again, now or after a restart
                self.remove_capture(item, keep_pictures=True)
                return
            # Wait before the next try, in short steps so that a restart is not held up
            deadline = time.time() + delay
            while time.time() < deadline and not self.stopping:
                time.sleep(0.1)
            delay = min(delay * 2, 15.0)

    def park(self, item):
        """
        Set a capture aside that the server keeps answering oddly: it joins the held captures (the
        setup page shows them and offers to send them again), its picture and note stay on disk,
        and the next start tries it again. The captures behind it go on.
        """
        item['parked'] = True
        item['odd_answers'] = 0
        # An item queued during this run has no note's fields (those come from load_pending): where it was going is here
        item.setdefault('server', self.server)
        item.setdefault('station', self.id)
        item.setdefault('taken', time.strftime('%Y-%m-%d %H:%M:%S'))
        with self.held_lock:
            self.held.append(item)
        logger.error(f"{item['image'].name}: the server answered {self.PARK_AFTER_ANSWERS} times with something that is "
                     f"neither 'received' nor 'refused' - set aside (the setup page offers to send it again); the next ones go on")

    def send_once(self, session, item):
        """One attempt to send a capture: 'accepted', 'refused' or 'retry' (see upload_verdict)"""
        headers = {'X-Station-Token': self.token} if self.token else {}
        try:
            files = {'image': (item['image'].name, item['image'].read_bytes(), 'image/jpeg')}
            if item['foil']:
                files['foil_image'] = (item['foil'].name, item['foil'].read_bytes(), 'image/jpeg')
            frame = item.get('frame')
            if frame and frame.is_file():
                # Training data, not the capture: the server may ignore it (an older one does)
                files['frame'] = (frame.name, frame.read_bytes(), 'image/jpeg')
            response = session.post(
                f"{self.server}/api/stations/{self.id}/captures", files=files, headers=headers, timeout=90,
                # wait 0: the outcome is shown on the station's page, nobody waits for it here.
                # capture_id: this same capture sent again (no answer came) is still one card
                data={'name': self.name, 'camera': '1', 'mode': item['mode'], 'wait': '0',
                      'capture_id': item['capture_id'], 'foil_is_image': '1' if item['foil_is_image'] else '0',
                      **({'frame_meta': json.dumps(item['frame_meta'])} if item.get('frame_meta') else {})})
        except FileNotFoundError:
            logger.error(f"{item['image'].name} is gone - nothing to send")
            return 'refused'  # settled in the only way left: its note is removed
        except (requests.RequestException, OSError) as e:
            logger.warning(f"Could not send {item['image'].name} ({type(e).__name__}) - trying again")
            return 'retry'
        verdict = upload_verdict(response)
        if verdict == 'accepted':
            try:
                item['answer_status'] = response.json().get('status')   # 'card_back' stops the stack (after_upload)
            except ValueError:
                item['answer_status'] = None
        if verdict == 'refused':
            logger.error(f"The server refused {item['image'].name}: {response.text[:200]} - the picture is kept")
        elif verdict == 'retry':
            item['odd_answers'] = item.get('odd_answers', 0) + 1
            logger.warning(f"Unexpected answer {response.status_code} for {item['image'].name} - trying again "
                           f"({item['odd_answers']}/{self.PARK_AFTER_ANSWERS})")
        return verdict


def upload_verdict(response):
    """
    What the server's answer to an uploaded capture means for the picture here:
      'accepted'  the server has the capture on record (its answer names the capture's number):
                  only then is the picture deleted
      'refused'   the server answered that it will never take it (400 unreadable, 413 too large)
      'retry'     anything else - an error, a wrong token (401: it is tried again until the token
                  is put right), a proxy's page, an answer that is not the server's
    An answer below 500 used to count as "the server has it", whatever it said.
    """
    try:
        answer = response.json()
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        return 'retry'
    if response.status_code in (200, 202) and isinstance(answer.get('capture'), int):
        return 'accepted'
    if response.status_code in (400, 413) and answer.get('success') is False:
        return 'refused'
    return 'retry'


def main():
    # In a container the machine's name is the one mounted from the host (deploy/docker-compose.client.yml)
    host_file = Path('/etc/host_hostname')
    host = host_file.read_text().strip() if host_file.is_file() else socket.gethostname()
    host = re.sub(r'[^A-Za-z0-9_-]', '-', host)[:40] or 'station'
    # No defaults here: a value that is not given is looked for in the environment, then in
    # what the setup page saved (station_setup.resolve) - and the page must know which of
    # them were given here, to show those as fixed
    parser = argparse.ArgumentParser(description="Camera station for the card scanner server")
    parser.add_argument('--server', help="e.g. http://192.168.1.20:5000 (or SCANNER_SERVER, or the setup page)")
    parser.add_argument('--id', help="1-40 letters, digits, - or _ (default: this machine's name)")
    parser.add_argument('--name', help="shown on the server (default: the id)")
    parser.add_argument('--token', help="the server's station token, if it has one")
    parser.add_argument('--setup-port', type=int, default=int(os.getenv('SCANNER_SETUP_PORT') or station_setup.DEFAULT_PORT),
                        help=f"port of the setup page (default {station_setup.DEFAULT_PORT}; 0 = no setup page)")
    args = parser.parse_args()

    # Stopping. The station ends on Ctrl+C: Python turns that signal (SIGINT) into a
    # KeyboardInterrupt, which the loops below catch to let go of the camera first. But
    # Python only does so if nobody told the process to ignore the signal - and a shell that
    # starts a program in the background (`station_client.py &` in scripts/start.sh) does
    # exactly that, after which `kill -INT` did nothing and the station could not be stopped
    # short of killing it. So the signal is taken back here, explicitly. SIGTERM - what
    # systemd and `docker stop` send by default - ends the station the same orderly way.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, lambda number, frame: signal.default_int_handler(signal.SIGINT, frame))

    Config.create_directories()  # data/ must exist before the saved settings are read
    values, fixed = station_setup.resolve({'server': args.server, 'id': args.id, 'name': args.name, 'token': args.token},
                                          station_setup.load(), host)
    if not re.fullmatch(station_setup.ID_PATTERN, values['id']):
        parser.error("the station's id must be 1-40 letters, digits, - or _")
    station_setup.apply_camera(values, fixed)  # before a CardScanner exists: it opens the camera

    # Without a server address there is nothing to connect to yet: only the setup page runs
    station = Station(values['server'], values['id'], values['name'], values['token']) if values['server'] else None
    if station:
        station.setup_port = args.setup_port

    # A restart is asked for from the setup page's thread, but must happen in this main
    # thread (it replaces the whole program): the page only raises a flag, and the loops
    # below notice it
    restart = threading.Event()

    def request_restart():
        restart.set()
        if station:
            station.stopping = True

    if args.setup_port:
        if station_setup.SetupPage(station, values, fixed, request_restart, args.setup_port).start():
            logger.info(f"Setup page: http://<this machine's address>:{args.setup_port}")
    if station is None:
        if not args.setup_port:
            parser.error("--server (or SCANNER_SERVER) is needed, e.g. http://192.168.1.20:5000")
        logger.info("No server address yet - open the setup page to set this station up")
        try:
            restart.wait()  # until the page has saved settings
        except KeyboardInterrupt:
            return
    else:
        try:
            station.run()  # until Ctrl+C, or a restart is asked for
        except KeyboardInterrupt:
            pass  # stopped while still looking for the server: nothing was opened yet

    if restart.is_set():
        # Start afresh with the saved settings. The camera is released by now (run() cleans
        # up when it ends). os.execv replaces this program by a new copy of itself with the
        # same command line - in a container that keeps the container running, where simply
        # ending would rely on Docker to start it again.
        # Captures that are still waiting are not lost by this: each has its note on disk,
        # and the new copy sends them (Station.load_pending).
        if station:
            station.wait_for_upload(10)  # one that is on its way right now may finish
        time.sleep(0.5)  # let the page's "saved" answer go out first
        logger.info("Restarting")
        os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == "__main__":
    main()
