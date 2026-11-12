"""
The card dropper's feeder over Wi-Fi (station/dropper.py: checked's 'transport' / 'feeder' / 'pair_key', WifiFeeder, find_feeders,
pair_feeder, Dropper with transport 'wifi'; station_client.py: the find_feeders / pair_feeder commands; the server's settings_events:
dropper_payload, set_dropper, find_feeders, pair_feeder, forget_feeder). The feeder is card-dropper's sideways feeder
(sideways/firmware: main.py request_feed / feed_state, tuning.py handle_feed / pair_form / answer_finders): FakeFeeder below
follows its rules - one request is one card, a number seen is never fed twice, another boot's id refused, one card at a time.
No network is touched.

    venv/bin/python -m unittest discover tests -p test_station_dropper_wifi.py
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))  # the code is in src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from card_scanner.station import dropper as dropper_module  # noqa: E402
from card_scanner.station.dropper import DEFAULTS, Dropper, WifiFeeder, checked  # noqa: E402

KEY = 'k' * 32
FEEDER = {'ip': '192.168.51.108', 'name': 'card-dropper-sw', 'mac': '3c:0f:02:e0:63:80'}
WIFI_ON = {'enabled': True, 'transport': 'wifi', 'feeder': FEEDER, 'pair_key': KEY}


class FakeFeeder:
    """
    The feeder's HTTP answers, by its rules. done_after: polls of GET /feed before a card is 'done'; lose: answers lost
    (the request arrives, its answer does not: OSError) for the next POSTs; down: nothing answers at all
    """

    def __init__(self, done_after=2, key=KEY):
        self.boot = 'b007b007'
        self.key = key
        self.results = {}                 # n -> state
        self.polls = {}
        self.fed = []                     # the numbers actually fed, in order
        self.done_after = done_after
        self.lose = 0
        self.down = False
        self.fail_next = False
        self.requests = []

    def restart(self):
        self.boot = 'feedfeed'
        self.results, self.polls = {}, {}

    def __call__(self, url, form=None, timeout=None):
        self.requests.append((url, form))
        if self.down:
            raise OSError('timed out')
        path = url.split('/', 3)[3] if url.count('/') >= 3 else ''
        if path == 'status':
            return 200, {'status': {'boot': self.boot}}
        if path.startswith('feed?n='):
            n = int(path.split('=')[1])
            if n not in self.results:
                return 404, {'state': 'unknown', 'boot': self.boot}
            if self.results[n] == 'queued':
                self.polls[n] += 1
                if self.polls[n] >= self.done_after:
                    self.results[n] = 'failed' if self.fail_next else 'done'
                    self.fed.append(n)
            return 200, {'n': n, 'state': self.results[n], 'boot': self.boot, 'error': 'jammed' if self.results[n] == 'failed' else None}
        if path == 'feed':
            if form['key'] != self.key:
                return 403, {'error': 'wrong key - nothing fed', 'boot': self.boot}
            if form['boot'] != self.boot:
                return 409, {'refused': 'boot', 'error': 'restarted', 'boot': self.boot}
            n = int(form['n'])
            if n in self.results:
                answer = (200, {'n': n, 'state': self.results[n], 'boot': self.boot})
            elif any(state == 'queued' for state in self.results.values()):
                return 409, {'refused': 'busy', 'error': 'busy', 'boot': self.boot}
            else:
                self.results[n], self.polls[n] = 'queued', 0
                answer = (202, {'n': n, 'state': 'queued', 'boot': self.boot})
            if self.lose:
                self.lose -= 1
                raise OSError('the answer was lost')
            return answer
        if path == 'pair':
            if form['config_key'] != 'owner-key':
                return 403, {'error': 'wrong config key - not paired'}
            return 200, {'feeder': 'card-dropper-sw', 'ip': '192.168.51.108', 'mac': FEEDER['mac'], 'paired': True,
                         'station': form['station']}
        return 404, {}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def feeder_for(fake, clock=None):
    clock = clock or Clock()
    return WifiFeeder(FEEDER['ip'], KEY, http=fake, clock=clock, sleep=clock.sleep)


class TheSettings(unittest.TestCase):
    def test_a_feeder_is_a_transport_beside_the_pin(self):
        self.assertEqual(checked(None)['transport'], 'gpio')                  # as before: off, a pin
        self.assertEqual(checked(dict(WIFI_ON))['feeder'], FEEDER)             # on without a pin: the feeder needs none
        with self.assertRaisesRegex(ValueError, 'Pair a feeder'):
            checked({'enabled': True, 'transport': 'wifi'})                    # on, but not paired
        checked({'enabled': False, 'transport': 'wifi'})                       # off and not paired: allowed (chosen, then paired)
        with self.assertRaisesRegex(ValueError, 'GPIO pin'):
            checked({'enabled': True, 'transport': 'gpio', 'feeder': FEEDER, 'pair_key': KEY})   # the pin's rule stays
        for wrong in ({'transport': 'bluetooth'}, {'feeder': {'ip': 'not.an.ip'}}, {'feeder': {'ip': '1.2.3.4', 'x': 1}},
                      {'feeder': 'x'}, {'pair_key': 'short'}, {'pair_key': 'k' * 20 + ' spaced'}, {'pair_key': 5}):
            with self.assertRaises(ValueError, msg=wrong):
                checked(wrong)


class TheFeeder(unittest.TestCase):
    """WifiFeeder: one card per request, whatever the network does"""

    def test_one_card_asked_then_waited_for(self):
        fake = FakeFeeder(done_after=3)
        feeder = feeder_for(fake)
        feeder.set(True)
        self.assertEqual(len(fake.results), 1)
        self.assertEqual(fake.fed, [])                       # on its way, not done yet
        feeder.set(False)
        self.assertEqual(len(fake.fed), 1)                   # done: the card lies still
        feeder.set(False)                                    # nothing under way: nothing asked
        self.assertEqual(len(fake.fed), 1)

    def test_a_lost_answer_is_asked_again_with_the_same_number(self):
        fake = FakeFeeder()
        fake.lose = 2
        feeder = feeder_for(fake)
        feeder.set(True)
        feeder.set(False)
        numbers = {form['n'] for url, form in fake.requests if form}
        self.assertEqual(len(numbers), 1)                    # three tries, one number
        self.assertEqual(len(fake.fed), 1)                   # one card

    def test_every_answer_lost_but_the_number_taken_is_a_card_on_its_way(self):
        fake = FakeFeeder()
        fake.lose = dropper_module.FEEDER_TRIES
        feeder = feeder_for(fake)
        feeder.set(True)                                     # not "not released": the feeder has it
        feeder.set(False)
        self.assertEqual(len(fake.fed), 1)

    def test_a_feeder_that_does_not_answer_releases_nothing_and_says_so(self):
        fake = FakeFeeder()
        feeder = feeder_for(fake)
        feeder.set(True)
        feeder.set(False)
        fake.down = True
        with self.assertRaisesRegex(RuntimeError, 'did not answer'):
            feeder.set(True)
        feeder.set(False)                                    # nothing under way: nothing waited for

    def test_a_restart_before_the_request_asks_again_with_the_new_boot(self):
        fake = FakeFeeder()
        feeder = feeder_for(fake)
        feeder.set(True)
        feeder.set(False)
        fake.restart()                                       # the feeder powered off and on between two cards
        feeder.set(True)
        feeder.set(False)
        self.assertEqual(len(fake.fed), 2)
        self.assertEqual(feeder.boot, 'feedfeed')

    def test_a_restart_during_the_card_stops_and_says_look(self):
        fake = FakeFeeder(done_after=5)
        feeder = feeder_for(fake)
        feeder.set(True)
        fake.restart()
        with self.assertRaisesRegex(RuntimeError, 'restarted'):
            feeder.set(False)

    def test_refusals(self):
        fake = FakeFeeder(key='another')
        with self.assertRaisesRegex(RuntimeError, 'pair it again'):
            feeder_for(fake).set(True)
        fake = FakeFeeder(done_after=99)
        first = feeder_for(fake)
        first.set(True)
        other = feeder_for(fake)
        other.number = first.number + 1000                   # (a number of its own: the two were made in the same millisecond)
        with self.assertRaisesRegex(RuntimeError, 'busy'):
            other.set(True)                                  # another request while a card is under way
        self.assertEqual(len(fake.results), 1)

    def test_a_failed_card_and_the_wait_limit(self):
        fake = FakeFeeder()
        fake.fail_next = True
        feeder = feeder_for(fake)
        feeder.set(True)
        with self.assertRaisesRegex(RuntimeError, 'jammed'):
            feeder.set(False)
        clock = Clock()
        fake = FakeFeeder(done_after=10 ** 6)
        feeder = feeder_for(fake, clock)
        feeder.set(True)
        with self.assertRaisesRegex(RuntimeError, f'within {dropper_module.FEEDER_WAIT_S} s'):
            feeder.set(False)
        self.assertGreater(clock.now, dropper_module.FEEDER_WAIT_S)
        self.assertEqual(dropper_module.FEEDER_WAIT_S, 10)   # the owner's limit (2026-11-12)

    def test_what_runs_inside_the_gate_is_bounded(self):
        """set(True) runs under the station's release_lock: no boot id read there, few requests, short timeouts"""
        fake = FakeFeeder()
        fake.down = False
        feeder = feeder_for(fake)                            # the boot id read here, before any gate
        fake.requests.clear()
        fake.down = True                                     # the worst: nothing answers
        with self.assertRaises(RuntimeError):
            feeder.set(True)
        self.assertFalse(any(url.endswith('/status') for url, _ in fake.requests))
        self.assertLessEqual(len(fake.requests), dropper_module.FEEDER_TRIES + 1)
        self.assertLessEqual((dropper_module.FEEDER_TRIES + 1) * dropper_module.FEEDER_HTTP_S, 6)
        fake.down = False
        fake.restart()                                       # a restart refused: its new id taken from the refusal itself
        fake.requests.clear()
        feeder.set(True)
        self.assertFalse(any(url.endswith('/status') for url, _ in fake.requests))
        self.assertEqual(feeder.boot, 'feedfeed')

    def test_drop_one_card_is_waited_for_long_enough(self):
        from card_scanner.core import remote_scanner
        remote = remote_scanner.RemoteScanner(mock.Mock(), FakeSettings())
        with mock.patch.object(remote, '_call', return_value=1) as call:
            remote.drop_card()
        self.assertGreaterEqual(call.call_args.kwargs['timeout'], dropper_module.FEEDER_WAIT_S + 6)

    def test_numbers_only_grow(self):
        fake = FakeFeeder(done_after=1)
        feeder = feeder_for(fake)
        seen = []
        for _ in range(5):
            feeder.set(True)
            seen.append(feeder.number)
            feeder.set(False)
        self.assertEqual(seen, sorted(set(seen)))


class TheDropper(unittest.TestCase):
    """Dropper.pulse with a feeder: the same lock, the same gate - the request sent inside it"""

    def setUp(self):
        self.fake = FakeFeeder()
        self.opened = []
        self.clock = Clock()

        def open_feeder(ip, key):
            feeder = WifiFeeder(ip, key, http=self.fake, clock=self.clock, sleep=self.clock.sleep)
            self.opened.append(feeder)
            return feeder

        self.sleeps = []
        self.dropper = Dropper(open_pin=mock.Mock(side_effect=AssertionError('no pin for a feeder')), sleep=self.sleeps.append,
                               open_feeder=open_feeder)

    def test_one_pulse_is_one_card(self):
        self.dropper.configure(dict(WIFI_ON))
        self.assertTrue(self.dropper.pulse('a test'))
        self.assertEqual(len(self.fake.fed), 1)
        self.assertEqual(self.dropper.pulses, 1)
        self.assertEqual(self.sleeps, [])                    # no GPIO pulse length for a feeder

    def test_the_gate_says_no_and_nothing_is_asked(self):
        self.dropper.configure(dict(WIFI_ON))

        class No:
            def __enter__(self):
                return False

            def __exit__(self, *exc):
                return False

        self.assertFalse(self.dropper.pulse('stale', gate=No))
        self.assertEqual(self.fake.results, {})

    def test_a_failure_is_no_card_and_its_reason(self):
        self.dropper.configure(dict(WIFI_ON))
        self.fake.down = True
        self.assertFalse(self.dropper.pulse('a test'))       # not even opened: its boot id cannot be read
        self.assertIn('does not answer', self.dropper.error)
        self.assertEqual(self.fake.results, {})
        self.fake.down = False
        self.assertTrue(self.dropper.pulse('again'))         # opened again, the next time
        self.assertIsNone(self.dropper.error)

    def test_a_new_pairing_opens_a_new_feeder(self):
        self.dropper.configure(dict(WIFI_ON))
        self.dropper.pulse('one')
        self.dropper.configure(dict(WIFI_ON, pair_key='p' * 32))
        self.fake.key = 'p' * 32
        self.dropper.pulse('two')
        self.assertEqual([f.key for f in self.opened], [KEY, 'p' * 32])


class FakeUdp:
    """A UDP socket: what was asked, and the feeders' answers"""

    def __init__(self, answers):
        self.sent, self.answers, self.closed = [], list(answers), False

    def setsockopt(self, *args):
        pass

    def setblocking(self, flag):
        pass

    def sendto(self, data, target):
        self.sent.append((data, target))

    def recvfrom(self, size):
        if not self.answers:
            raise BlockingIOError
        return self.answers.pop(0)

    def close(self):
        self.closed = True


class FindingAndPairing(unittest.TestCase):
    def test_found_by_asking_every_address_and_by_broadcast(self):
        me = {'feeder': 'card-dropper-sw', 'ip': '192.168.51.108', 'mac': FEEDER['mac'], 'paired': False, 'station': None,
              'boot': 'b007b007', 'port': 80}
        udp = FakeUdp([(json.dumps(me).encode(), ('192.168.51.108', 50505)), (b'not json', ('192.168.51.9', 50505)),
                       (json.dumps(me).encode(), ('192.168.51.108', 50505))])
        found = dropper_module.find_feeders(['192.168.51.61'], wait=0.05, make_socket=lambda: udp)
        self.assertEqual(found, [{'ip': '192.168.51.108', 'name': 'card-dropper-sw', 'mac': FEEDER['mac'], 'paired': False,
                                  'station': None}])
        targets = [t for _, t in udp.sent]
        self.assertIn(('192.168.51.255', 50505), targets)   # the broadcast
        self.assertIn(('192.168.51.108', 50505), targets)   # ... and each address directly (a firewall drops broadcast answers)
        self.assertEqual(len(targets), 255)
        self.assertTrue(all(d == b'card-dropper?' for d, _ in udp.sent))
        self.assertTrue(udp.closed)

    def test_paired_with_the_owners_key_once(self):
        fake = FakeFeeder()
        paired = dropper_module.pair_feeder('192.168.51.108', 'owner-key', 'Living room PC', http=fake)
        self.assertEqual(paired['feeder'], FEEDER)
        checked(dict(WIFI_ON, pair_key=paired['pair_key']))  # a key the feeder takes and the settings keep
        sent = fake.requests[-1][1]
        self.assertEqual(sent['config_key'], 'owner-key')
        self.assertEqual(sent['pair_key'], paired['pair_key'])
        self.assertEqual(sent['station'], 'Living room PC')
        self.assertNotEqual(dropper_module.pair_feeder('192.168.51.108', 'owner-key', 'x', http=fake)['pair_key'],
                            paired['pair_key'])              # a new key each pairing
        with self.assertRaisesRegex(ValueError, 'wrong config key'):
            dropper_module.pair_feeder('192.168.51.108', 'guess', 'x', http=fake)
        with self.assertRaisesRegex(ValueError, 'key'):
            dropper_module.pair_feeder('192.168.51.108', '', 'x', http=fake)
        with self.assertRaisesRegex(ValueError, 'address'):
            dropper_module.pair_feeder('nope', 'owner-key', 'x', http=fake)
        fake.down = True
        with self.assertRaisesRegex(ValueError, 'does not answer'):
            dropper_module.pair_feeder('192.168.51.108', 'owner-key', 'x', http=fake)

    def test_the_stations_commands(self):
        from card_scanner.station.station_client import Station
        station = Station.__new__(Station)
        station.scanner, station.name = mock.Mock(), 'Living room PC'
        station.state = lambda: {}
        with mock.patch.object(dropper_module, 'find_feeders', return_value=[{'ip': '1.2.3.4'}]):
            self.assertEqual(station.on_command({'method': 'find_feeders'})['result'], [{'ip': '1.2.3.4'}])
        with mock.patch.object(dropper_module, 'pair_feeder', side_effect=ValueError('wrong config key')) as pair:
            answer = station.on_command({'method': 'pair_feeder', 'args': ['1.2.3.4', 'k']})
            self.assertEqual(answer, {'ok': False, 'error': 'wrong config key'})
            pair.assert_called_once_with('1.2.3.4', 'k', station_name='Living room PC')


class FakeSettings:
    def __init__(self, saved=None):
        self.saved = dict(saved or {})

    def get(self, key, default=None):
        return self.saved.get(key, default)

    def set(self, key, value):
        self.saved[key] = value


class TheServer(unittest.TestCase):
    """The pair key stays on the server (and the station): the page never gets it, and a save from the page keeps it"""

    def test_the_pages_events(self):
        import app as launcher  # noqa: F401 - the server's routes and events
        from card_scanner.server.state import app, socketio
        settings_events = sys.modules['card_scanner.server.settings_events']
        station = mock.Mock(connected=True, dropper=None, dropper_state={'enabled': False, 'pulses': 0, 'error': None,
                                                                          'last_pulse': None}, settings=FakeSettings())
        with mock.patch.object(settings_events, 'scanner', station):
            client = socketio.test_client(app, flask_test_client=app.test_client())
            client.get_received()
            try:
                def emit(event, payload=None):
                    client.emit(event, payload or {})
                    return {e['name']: e['args'][0] for e in client.get_received()}

                # Chosen and switched on before any pairing: kept off, and why
                answer = emit('set_dropper', {'dropper': {'enabled': True, 'transport': 'wifi'}})
                self.assertIn('Pair a feeder', answer['error']['message'])
                self.assertEqual(station.settings.saved['dropper']['transport'], 'wifi')
                self.assertFalse(station.settings.saved['dropper']['enabled'])

                station.find_feeders.return_value = [{'ip': FEEDER['ip'], 'name': 'card-dropper-sw'}]
                self.assertEqual(emit('find_feeders')['feeders_found'], {'ok': True, 'feeders': station.find_feeders.return_value})
                station.find_feeders.side_effect = ValueError('The station cannot look for feeders')
                self.assertFalse(emit('find_feeders')['feeders_found']['ok'])

                station.pair_feeder.side_effect = ValueError('wrong config key - not paired')
                answer = emit('pair_feeder', {'ip': FEEDER['ip'], 'config_key': 'guess'})
                self.assertEqual(answer['feeder_paired'], {'ok': False, 'message': 'wrong config key - not paired'})
                self.assertIsNone(station.settings.saved['dropper']['pair_key'])

                station.pair_feeder.side_effect = None
                station.pair_feeder.return_value = {'feeder': FEEDER, 'pair_key': KEY}
                answer = emit('pair_feeder', {'ip': FEEDER['ip'], 'config_key': 'owner-key'})
                station.pair_feeder.assert_called_with(FEEDER['ip'], 'owner-key')
                self.assertEqual(answer['feeder_paired'], {'ok': True, 'feeder': FEEDER})
                self.assertEqual(station.settings.saved['dropper']['pair_key'], KEY)          # kept on the server
                self.assertEqual(station.dropper['pair_key'], KEY)                            # ... and sent to the station
                self.assertNotIn(KEY, json.dumps(answer))                                     # never to the page
                self.assertNotIn('owner-key', json.dumps(station.settings.saved))             # the owner's key kept nowhere
                self.assertTrue(answer['dropper_updated']['settings']['paired'])

                # The page's form saved: switched on - the feeder and its key kept, though the page never had them
                answer = emit('set_dropper', {'dropper': {'enabled': True, 'transport': 'wifi', 'pin': None, 'pulse_ms': 150,
                                                          'chip': '/dev/gpiochip0', 'active_low': False}})
                self.assertEqual(station.settings.saved['dropper'], dict(DEFAULTS, **WIFI_ON))
                self.assertNotIn(KEY, json.dumps(answer))
                # ... and a page sending a key of its own changes nothing of it
                emit('set_dropper', {'dropper': {'enabled': True, 'transport': 'wifi', 'pair_key': 'x' * 32,
                                                 'feeder': {'ip': '10.0.0.1'}}})
                self.assertEqual(station.settings.saved['dropper']['pair_key'], KEY)
                self.assertEqual(station.settings.saved['dropper']['feeder'], FEEDER)

                answer = emit('forget_feeder')
                saved = station.settings.saved['dropper']
                self.assertEqual((saved['enabled'], saved['feeder'], saved['pair_key']), (False, None, None))
                self.assertFalse(answer['dropper_updated']['settings']['paired'])

                # Forgetting a feeder while a GPIO pin drives it leaves the pin on
                emit('set_dropper', {'dropper': {'enabled': True, 'transport': 'gpio', 'pin': 17}})
                station.settings.saved['dropper'] = dict(station.settings.saved['dropper'], feeder=FEEDER, pair_key=KEY)
                station.dropper = station.settings.saved['dropper']
                emit('forget_feeder')
                self.assertTrue(station.settings.saved['dropper']['enabled'])
            finally:
                client.disconnect()


if __name__ == '__main__':
    unittest.main()
