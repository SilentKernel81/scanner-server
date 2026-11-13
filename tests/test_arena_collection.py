#!/usr/bin/env python3
"""
The digital collection (what the user has in MTG Arena) and the decks' two kinds.

Run:  venv/bin/python tests/test_arena_collection.py     (or with the others: -m unittest discover tests)

On temporary files and made-up exports:
  - reading the exporter's two files, and refusing what is not one of them;
  - finding each entry's card: by Arena's set and number only when the name agrees;
  - an inventory replaced as a whole, or not at all;
  - decks: the new columns on a file from before, every Arena deck (also one made here)
    replaced by the next import while paper decks stay, and paper and Arena decks not
    competing for a card.
What the server makes of a real export is tried on a test server, not here.
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))  # the code is in src/

from card_scanner.core import arena, storage  # noqa: E402
from card_scanner.core.database import search_key  # noqa: E402
from card_scanner.core.decks import KIND_MIGRATION, DeckManager  # noqa: E402
from card_scanner.core.inventory import InventoryManager  # noqa: E402


def export(cards, **inventory):
    return json.dumps({'export_date': '2026-10-13T10:52:00', 'cards': cards, 'inventory': inventory})


def entry(name, set_code='fdn', number='1', count=1, **more):
    return {'count': count, 'name': name, 'set': set_code.upper(), 'collector_number': number, 'rarity': 'common', **more}


class ReadingTheExport(unittest.TestCase):

    def test_the_collection_file(self):
        read = arena.read_collection(export([entry('Opt', count=3), entry('A-Opt', rebalanced=True), entry('Gone', count=0)],
                                            WildCardCommons=18, WildCardRares=1, Gold=1125, Gems=130))
        self.assertEqual(read['exported'], '2026-10-13T10:52:00')
        self.assertEqual([(c['name'], c['set'], c['number'], c['quantity'], c['rebalanced']) for c in read['cards']],
                         [('Opt', 'fdn', '1', 3, False), ('A-Opt', 'fdn', '1', 1, True)])   # a count of 0 is no card
        # a rarity you have no wildcard of is not in the export at all: that is 0
        self.assertEqual(read['wildcards'], {'common': 18, 'uncommon': 0, 'rare': 1, 'mythic': 0})
        self.assertEqual((read['gold'], read['gems']), (1125, 130))

    def test_what_is_not_the_exporters_file_is_refused(self):
        for text in ('not json at all', '[]', '{"decks": []}', '{"cards": [{"name": "Opt"}]}', '{"cards": "many"}',
                     export([{'name': 'Opt', 'count': 'three'}])):
            with self.assertRaises(arena.NotAnExport, msg=text):
                arena.read_collection(text)

    def test_the_deck_file(self):
        decks = arena.read_decks(json.dumps({'decks': [
            {'id': 'abc', 'name': 'Elves', 'format': 'Historic', 'deck': [entry('Opt', count=4)]},
            {'id': 'def', 'name': 'Brawlers', 'format': 'Standard Brawl', 'deck': [entry('Island', count=30)],
             'commander': [entry('Jace')], 'sideboard': [entry('Negate', count=2)]},
            {'id': 'ghi', 'name': 'Odd', 'format': 'Some New Event', 'deck': []}]}))
        self.assertEqual([(d['arena_id'], d['name'], d['format']) for d in decks],
                         [('abc', 'Elves', 'historic'), ('def', 'Brawlers', 'standardbrawl'), ('ghi', 'Odd', 'historic')])
        self.assertEqual([(c['name'], c['board'], c['quantity']) for c in decks[1]['cards']],
                         [('Jace', 'commander', 1), ('Island', 'main', 30), ('Negate', 'side', 2)])
        with self.assertRaises(arena.NotAnExport):
            arena.read_decks('{"decks": [{"name": "no id"}]}')
        with self.assertRaises(arena.NotAnExport):
            arena.read_decks(export([]))


class FakeCards:
    """The card data, as far as find_card asks it: printings by set and number, cards by name"""
    PRINTINGS = {('fdn', '227'): 'Llanowar Elves', ('lci', '400'): 'Mountain', ('neo', '1'): 'Ancestral Katana',
                 ('hob', '170'): 'The Arkenstone // Seek the Heart'}
    NAMES = ('Llanowar Elves', 'Forest', 'Mountain', 'Ancestral Katana', 'The Arkenstone // Seek the Heart', 'Poq, Digital Only')

    def get_card_by_set_number(self, set_code, number, exact=False):
        name = self.PRINTINGS.get((set_code, number))
        return {'name': name, 'id': f'{set_code}-{number}'} if name else None

    def cards_by_names(self, names):
        known = {search_key(name): name for name in self.NAMES}
        known.update({search_key(name.split(' // ')[0]): name for name in self.NAMES})   # a front name finds its card
        return {search_key(name): {'name': known[search_key(name)], 'id': 'any printing'} for name in names if search_key(name) in known}


class FindingTheCards(unittest.TestCase):

    def found(self, *entries, **options):
        cards = FakeCards()
        read = [{'name': e['name'], 'set': e['set'].lower(), 'number': e['collector_number'], 'quantity': e['count'],
                 'rebalanced': bool(e.get('rebalanced'))} for e in entries]
        found, summary = arena.resolve(cards, cards, read, **options)
        return [(item['card']['name'], item['card']['id'], item['quantity']) for item in found], summary

    def test_set_and_number_when_the_name_agrees(self):
        found, summary = self.found(entry('Llanowar Elves', 'fdn', '227', 3))
        self.assertEqual(found, [('Llanowar Elves', 'fdn-227', 3)])
        self.assertEqual((summary['by_printing'], summary['by_name']), (1, 0))

    def test_a_front_name_is_the_card(self):
        found, _ = self.found(entry('The Arkenstone', 'hob', '170', 2))
        self.assertEqual(found, [('The Arkenstone // Seek the Heart', 'hob-170', 2)])

    def test_a_number_that_belongs_to_another_card_is_not_believed(self):
        # Arena's Forest LCI #400 is the printed set's Mountain
        found, summary = self.found(entry('Forest', 'lci', '400'))
        self.assertEqual(found, [('Forest', 'any printing', 1)])
        self.assertEqual((summary['by_printing'], summary['by_name']), (0, 1))

    def test_a_printing_the_card_data_lacks_goes_by_name(self):
        found, _ = self.found(entry('Poq, Digital Only', 'y26', '7'))
        self.assertEqual(found, [('Poq, Digital Only', 'any printing', 1)])

    def test_rebalanced_twins_are_skipped_and_unknown_cards_named(self):
        found, summary = self.found(entry('A-Ancestral Katana', 'neo', '1', rebalanced=True), entry('Nobody Knows Me', 'xxx', '9'),
                                    entry('Llanowar Elves', 'fdn', '227'))
        self.assertEqual(found, [('Llanowar Elves', 'fdn-227', 1)])
        self.assertEqual((summary['rebalanced'], summary['unknown']), (1, ['Nobody Knows Me']))
        # in a deck a rebalanced card is a card of the deck: found as the card it changes
        found, _ = self.found(entry('A-Ancestral Katana', 'neo', '1', rebalanced=True), skip_rebalanced=False)
        self.assertEqual(found, [('Ancestral Katana', 'neo-1', 1)])

    def test_what_missing_cards_cost(self):
        self.assertEqual(arena.wildcards_needed([('rare', 3), ('common', 4), ('rare', 1), ('land', 9), (None, 2), ('special', 1)]),
                         {'common': 4, 'uncommon': 0, 'rare': 4, 'mythic': 0})


def fields(name, set_code='fdn', number='1', rarity='common'):
    """What Game.inventory_fields gives for a card, as far as an inventory needs it"""
    return {'card_id': f'{set_code}-{number}', 'name': name, 'set_name': set_code.upper(), 'set_code': set_code,
            'number': number, 'rarity': rarity, 'type_line': 'Creature', 'mana_cost': '{G}', 'colors': 'Green',
            'color_identity': 'Green', 'price': 0.5}


class Temporary(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)


class ReplacingAnInventory(Temporary):

    def setUp(self):
        super().setUp()
        self.store = InventoryManager(db_file=self.path / 'arena.db')
        arena.prepare(self.store)   # as the server does at start
        self.addCleanup(self.store.conn.close)

    def contents(self):
        return sorted((row['card_name'], row['quantity']) for row in self.store.conn.execute('SELECT card_name, quantity FROM inventory'))

    def test_the_new_contents_replace_the_old(self):
        self.store.replace_all('mtg', [{'fields': fields('Opt'), 'finish': 'regular', 'quantity': 2}])
        count = self.store.replace_all('mtg', [
            {'fields': fields('Llanowar Elves', number='227'), 'finish': 'regular', 'quantity': 3},
            {'fields': fields('Llanowar Elves', number='227'), 'finish': 'regular', 'quantity': 1},   # the same printing again
            {'fields': fields('Forest', number='280'), 'finish': 'regular', 'quantity': 7}])
        self.assertEqual(count, 2)
        self.assertEqual(self.contents(), [('Forest', 7), ('Llanowar Elves', 4)])
        self.assertEqual(self.store.owned_by_name('mtg')[search_key('Llanowar Elves')], 4)

    def test_a_replacement_that_fails_changes_nothing(self):
        self.store.replace_all('mtg', [{'fields': fields('Opt'), 'finish': 'regular', 'quantity': 2}])
        arena.save_account(self.store, {'exported': 'first'})
        self.store.conn.commit()
        with self.assertRaises(Exception):
            with self.store._lock:
                arena.save_account(self.store, {'exported': 'second'})
                self.store.replace_all('mtg', [{'fields': fields('Forest'), 'finish': 'regular', 'quantity': 1},
                                               {'fields': {'card_id': 'no name'}, 'finish': 'regular', 'quantity': 1}])
        self.assertEqual(self.contents(), [('Opt', 2)])                       # the old cards are still there ...
        self.assertEqual(arena.account(self.store), {'exported': 'first'})   # ... and so is the date they are from

    def test_the_copies_and_the_date_beside_them_are_one_imports(self):
        # An import that comes right after the copies were read, and gets half a second to finish before the account is
        # read: read one after the other, the old copies were said beside the new import's date. arena.snapshot holds the
        # lock the import needs, so the import waits until both are read
        import threading
        from unittest import mock

        def an_import(n):
            with self.store._transaction():
                arena.save_account(self.store, {'exported': f'import-{n}'})
                self.store.replace_all('mtg', [{'fields': fields('Opt'), 'finish': 'regular', 'quantity': n}])
        an_import(1)
        read_copies = self.store.owned_by_name
        writer = []

        def copies_then_an_import(game):
            owned = read_copies(game)
            writer.append(threading.Thread(target=an_import, args=(2,)))
            writer[0].start()
            writer[0].join(timeout=0.5)               # done by now, unless it waits for the lock
            return owned
        with mock.patch.object(self.store, 'owned_by_name', copies_then_an_import):
            owned, account = arena.snapshot(self.store, 'mtg')
        writer[0].join()
        self.assertEqual((owned[search_key('Opt')], account['exported']), (1, 'import-1'))   # one import's, the first
        self.assertEqual(arena.snapshot(self.store, 'mtg'), ({search_key('Opt'): 2}, {'exported': 'import-2'}))

    def test_the_account_is_empty_until_something_was_imported(self):
        self.assertEqual(arena.account(self.store), {})


class ImportRoute(Temporary):
    """POST /api/arena/import with temporary data behind the server: each import has a revision of its own"""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # app.py: the server's routes
        import io
        from unittest import mock
        import app as launcher
        from card_scanner.server import arena_api, state
        self.io = io
        self.store = InventoryManager(db_file=self.path / 'arena.db')
        arena.prepare(self.store)
        self.addCleanup(self.store.conn.close)
        saved = {name: getattr(state.services, name) for name in ('arena_inventory', 'database')}
        self.addCleanup(lambda: [setattr(state.services, name, value) for name, value in saved.items()])
        cards = FakeCards()
        state.services.arena_inventory, state.services.database = self.store, cards
        game = mock.Mock(id='mtg', label='Magic', arena_decklist=True, cards_by_names=cards.cards_by_names)
        game.inventory_fields = lambda card, finish: {**fields(card['name']), 'card_id': card['id']}
        game.suggested_finish = lambda card, wanted: 'regular'
        for patch in (mock.patch.object(arena_api.games, 'active', return_value=game),
                      mock.patch.object(arena_api, 'socketio', mock.Mock())):
            patch.start()
            self.addCleanup(patch.stop)
        self.client = launcher.app.test_client()

    def an_import(self, count):
        text = export([entry('Llanowar Elves', number='227', count=count)], WildCardRares=1)
        answer = self.client.post('/api/arena/import', data={'files': (self.io.BytesIO(text.encode()), 'mtga_collection.json')},
                                  content_type='multipart/form-data')
        self.assertEqual(answer.status_code, 200, answer.get_json())
        return self.client.get('/api/arena').get_json()['arena']

    def test_two_imports_in_one_second_have_their_own_revisions(self):
        # 'imported' is to the second: the revision is what tells two imports apart (the MCP's plan check)
        first, second = self.an_import(2), self.an_import(3)
        self.assertEqual(first['imported'][:16], second['imported'][:16])
        self.assertTrue(first['revision'] and second['revision'])
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertEqual(arena.snapshot(self.store, 'mtg')[1]['revision'], second['revision'])   # stored with its cards


class DecksOfTwoKinds(Temporary):

    def decks(self):
        manager = DeckManager(self.path / 'cards.db')
        self.addCleanup(manager.conn.close)
        return manager

    def test_a_file_from_before_kinds_keeps_its_decks_and_their_covers(self):
        conn = sqlite3.connect(self.path / 'cards.db')
        conn.execute('''CREATE TABLE decks (id INTEGER PRIMARY KEY AUTOINCREMENT, game TEXT NOT NULL, name TEXT NOT NULL,
                        format TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL, cover TEXT NOT NULL DEFAULT '')''')
        conn.execute("INSERT INTO decks VALUES (4, 'mtg', 'Elves', 'commander', 'n', '2026-10-01 10:00:00', '2026-10-02 11:00:00', 'Llanowar Elves')")
        conn.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT, note TEXT)")
        conn.execute("INSERT INTO schema_migrations VALUES ('deck_cover_1', '2026-10-13', '')")
        conn.commit()
        conn.close()
        decks = self.decks()
        self.assertEqual([tuple(row) for row in decks.conn.execute('SELECT * FROM decks')],
                         [(4, 'mtg', 'Elves', 'commander', 'n', '2026-10-01 10:00:00', '2026-10-02 11:00:00', 'Llanowar Elves', 'paper', '')])
        self.assertTrue(storage.applied(decks.conn, KIND_MIGRATION))
        self.assertEqual(decks.create('mtg', 'New', 'standard'), 5)

    def test_a_deck_has_a_kind_and_only_two_exist(self):
        decks = self.decks()
        self.assertEqual(decks.get(decks.create('mtg', 'Paper', 'standard'))['kind'], 'paper')
        arena_deck = decks.create('mtg', 'Digital', 'historic', kind='arena')
        self.assertEqual(decks.get(arena_deck)['kind'], 'arena')
        self.assertEqual(decks.get(decks.duplicate(arena_deck))['kind'], 'arena')
        # ... or of the other kind, named after it: the same list against the other collection
        decks.add_card(arena_deck, 'Opt', 'main', 4)
        physical = decks.get(decks.duplicate(arena_deck, kind='paper'))
        self.assertEqual((physical['kind'], physical['name'], physical['arena_id']), ('paper', 'Digital (Physical)', ''))
        self.assertEqual([(card['name'], card['quantity']) for card in physical['cards']], [('Opt', 4)])
        self.assertEqual(decks.get(decks.duplicate(physical['id'], kind='arena'))['name'], 'Digital (Physical) (Arena)')
        with self.assertRaises(ValueError):
            decks.duplicate(arena_deck, kind='cardboard')
        with self.assertRaises(ValueError):
            decks.create('mtg', 'Nope', 'standard', kind='cardboard')

    def test_every_arena_deck_is_replaced_and_paper_decks_stay(self):
        decks = self.decks()
        paper = decks.create('mtg', 'Paper', 'standard')
        mine = decks.create('mtg', 'Planned here', 'historic', kind='arena')
        card = lambda name, quantity=1: {'name': name, 'card_id': 'x', 'quantity': quantity, 'board': 'main'}
        first = decks.replace_arena_decks('mtg', [{'arena_id': 'a', 'name': 'Elves', 'format': 'historic', 'cards': [card('Llanowar Elves', 4), card('Forest', 7)]},
                                                 {'arena_id': 'b', 'name': 'Gone soon', 'format': 'standard', 'cards': [card('Opt')]}])
        decks.update(first[0], cover='Forest')
        decks.replace_arena_decks('mtg', [{'arena_id': 'a', 'name': 'Elves v2', 'format': 'historic', 'cards': [card('Forest', 9)]}])
        listed = {deck['name']: deck for deck in decks.list_decks('mtg')}
        # 'Gone soon' left Arena, and here; 'Planned here' (an Arena deck made here) is not in the file, so it goes too
        self.assertEqual(sorted(listed), ['Elves v2', 'Paper'])
        self.assertEqual((listed['Elves v2']['kind'], listed['Elves v2']['arena_id'], listed['Elves v2']['cover']), ('arena', 'a', 'Forest'))
        self.assertEqual(listed['Elves v2']['cards'], 9)
        self.assertEqual(listed['Paper']['id'], paper)
        self.assertIsNone(decks.get(mine))
        # A copy made here of an imported deck is an Arena deck too: gone with the next import
        decks.duplicate(listed['Elves v2']['id'])
        decks.replace_arena_decks('mtg', [])
        self.assertEqual([deck['name'] for deck in decks.list_decks('mtg')], ['Paper'])

    def test_a_failed_replacement_keeps_arenas_decks_as_they_were(self):
        decks = self.decks()
        card = {'name': 'Opt', 'card_id': 'x', 'quantity': 1, 'board': 'main'}
        decks.replace_arena_decks('mtg', [{'arena_id': 'a', 'name': 'Elves', 'format': 'historic', 'cards': [card]}])
        with self.assertRaises(ValueError):
            decks.replace_arena_decks('mtg', [{'arena_id': 'b', 'name': 'New', 'format': 'historic', 'cards': [card]},
                                              {'arena_id': 'c', 'name': 'Broken', 'format': 'historic', 'cards': [{'name': ''}]}])
        self.assertEqual([deck['name'] for deck in decks.list_decks('mtg')], ['Elves'])

    def test_paper_and_arena_decks_do_not_want_the_same_copies(self):
        decks = self.decks()
        paper = decks.create('mtg', 'Paper', 'standard')
        digital = decks.create('mtg', 'Digital', 'standard', kind='arena')
        decks.add_card(paper, 'Opt', 'main', 2)
        decks.add_card(digital, 'Opt', 'main', 4)
        key = search_key('Opt')
        self.assertEqual([(d['deck'], d['quantity']) for d in decks.needed_by_name('mtg')[key]], [('Paper', 2)])
        self.assertEqual([(d['deck'], d['quantity']) for d in decks.needed_by_name('mtg', kind='arena')[key]], [('Digital', 4)])


class BackingUpTheDigitalCollection(Temporary):
    """The digital collection as a fourth part of a backup (core/backups.py)"""

    def setUp(self):
        super().setUp()
        from card_scanner.core import backups, inventory as inventory_module
        self.backups = backups
        # The backups and the capture thumbnails go to the temporary folder, as in test_ownership.py
        for module, name, value in ((backups, 'BACKUPS_DIR', self.path / 'backups'), (backups, 'CAPTURES_DIR', self.path / 'captures'),
                                    (inventory_module, 'CAPTURES_DIR', self.path / 'captures'),
                                    (inventory_module, 'FULL_CAPTURES_DIR', self.path / 'captures_full')):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, value)
        self.collection = InventoryManager(db_file=self.path / 'cards.db')
        self.scan = InventoryManager(db_file=self.path / 'scan.db')
        self.digital = InventoryManager(db_file=self.path / 'arena.db')
        self.decks = DeckManager(self.path / 'cards.db')
        arena.prepare(self.digital)
        for manager in (self.collection, self.scan, self.digital, self.decks):
            self.addCleanup(manager.conn.close)

    def fill(self, name, quantity, exported):
        with self.digital._lock:
            arena.save_account(self.digital, {'exported': exported, 'wildcards': {'rare': quantity}})
            self.digital.replace_all('mtg', [{'fields': fields(name), 'finish': 'regular', 'quantity': quantity}])

    def digital_now(self):
        return ([(row['card_name'], row['quantity']) for row in self.digital.conn.execute('SELECT card_name, quantity FROM inventory')],
                arena.account(self.digital).get('exported'))

    def test_a_backup_brings_the_digital_collection_back(self):
        self.fill('Opt', 3, 'monday')
        made = self.backups.create(self.collection, self.scan, self.decks, arena_inventory=self.digital)
        self.assertEqual(made['arena'], 3)
        self.fill('Forest', 9, 'tuesday')
        self.backups.restore(made['id'], self.collection, self.scan, self.decks, arena_inventory=self.digital)
        self.assertEqual(self.digital_now(), ([('Opt', 3)], 'monday'))

    def test_a_backup_without_it_leaves_the_digital_collection_alone(self):
        # as every backup made before 2026-10-13 is
        self.collection.replace_all('mtg', [{'fields': fields('Paper card'), 'finish': 'regular', 'quantity': 1}])
        old = self.backups.create(self.collection, self.scan, self.decks)
        self.fill('Forest', 9, 'tuesday')
        self.backups.restore(old['id'], self.collection, self.scan, self.decks, arena_inventory=self.digital)
        self.assertEqual(self.digital_now(), ([('Forest', 9)], 'tuesday'))

    def test_a_new_import_is_a_change_the_schedule_sees(self):
        self.fill('Opt', 3, 'monday')
        first = self.backups.create_scheduled(self.collection, self.scan, self.decks, 24, 7, arena_inventory=self.digital)
        self.assertIsNotNone(first)   # only the digital collection has anything: still worth a backup
        fingerprint = lambda: self.backups._fingerprint(self.collection, self.scan, self.decks, self.digital)
        before = fingerprint()
        self.fill('Opt', 4, 'tuesday')
        self.assertNotEqual(before, fingerprint())


if __name__ == '__main__':
    unittest.main()
