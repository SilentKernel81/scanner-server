"""
Decks: named lists of cards (by card name, with a count and a board) built on the collection
page. A deck is only a list - the copies owned are counted from the inventory when it is shown,
and editing a deck never changes the inventory.

    decks = DeckManager()
    deck_id = decks.create('mtg', 'Elves', 'commander')
    decks.add_card(deck_id, 'Llanowar Elves', 'main', 1)
"""
import threading

from card_scanner.core import storage
from card_scanner.config import Config
from card_scanner.core.database import search_key
from card_scanner.core.inventory import now

BOARDS = ('commander', 'main', 'side')
# cover: the name of the card of the deck whose picture stands for it - in the deck list and
# behind the deck's name. Empty: not chosen, the page then shows the commander, or for a deck
# without one its most valuable card (server/decks_api.py: deck_covers). A name that is no
# longer in the deck counts as empty: nothing has to be cleaned up when a card is taken out.
DECKS_TABLE = '''
    CREATE TABLE {table} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game TEXT NOT NULL,
        name TEXT NOT NULL,
        format TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        cover TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'paper' CHECK (kind IN ('paper', 'arena')),
        arena_id TEXT NOT NULL DEFAULT ''
    )
'''
COVER_MIGRATION = 'deck_cover_1'
# kind: which collection a deck is of - 'paper' (cards on a shelf: the collection) or 'arena'
# (MTG Arena: the digital collection, data/arena_inventory.db). It decides what "owned" and
# "missing" are counted against, and the deck list can be filtered by it.
# arena_id: for a deck that came in with an Arena export, the id Arena has for it - what the
# next import finds the deck's chosen cover again by. That import replaces EVERY Arena deck
# (replace_arena_decks, since 2026-11-13), also those made here, which have no arena_id; paper
# decks are never touched.
KINDS = ('paper', 'arena')
KIND_MIGRATION = 'deck_kind_1'
# card_id: the printing shown (image); the card itself is identified by its name. A deck's
# cards go with the deck (ON DELETE CASCADE, on connections from storage.connect)
DECK_CARDS_TABLE = '''
    CREATE TABLE {table} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
        card_name TEXT NOT NULL,
        card_id TEXT,
        quantity INTEGER NOT NULL DEFAULT 1 CHECK (typeof(quantity) = 'integer' AND quantity > 0),
        board TEXT NOT NULL DEFAULT 'main' CHECK (board IN ('commander', 'main', 'side')),
        UNIQUE(deck_id, card_name, board)
    )
'''
# No index of its own on deck_id: UNIQUE(deck_id, card_name, board) starts with it and answers
# "the cards of a deck" as fast (measured 2026-10-09, scripts/benchmark_db.py: 0.05 ms / 0.08 ms)
DECK_CARDS_INDEXES = ()
CONSTRAINTS_MIGRATION = 'deck_constraints_1'
# What the standalone program (until 2026-10-14) kept these rules as: triggers on tables without
# CHECK or REFERENCES. One that names `decks` makes the rename of a rebuilt `decks` fail, so they
# go in the migration that gives the tables the rules themselves
LEGACY_TRIGGERS = ('DROP TRIGGER IF EXISTS deck_cards_valid_insert', 'DROP TRIGGER IF EXISTS deck_cards_valid_update',
                   'DROP TRIGGER IF EXISTS decks_take_cards')


class DeckManager(storage.Transactional):
    """Decks and their cards. Every edit is one transaction (storage.Transactional): all of it or, when it fails, none"""

    def __init__(self, db_file=None):
        self._lock = threading.RLock()
        self.db_file = db_file or Config.DATABASE_FILE
        self.conn = storage.connect(self.db_file)
        with self._lock:
            if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'decks'").fetchone():
                # A new file has the table as it is today: nothing to migrate later
                self.conn.execute(DECKS_TABLE.format(table='decks'))
                storage.record(self.conn, COVER_MIGRATION, 'new file')
                storage.record(self.conn, KIND_MIGRATION, 'new file')
            if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'deck_cards'").fetchone():
                self.conn.execute(DECK_CARDS_TABLE.format(table='deck_cards'))
                storage.record(self.conn, CONSTRAINTS_MIGRATION, 'new file')
            self.conn.execute('DROP INDEX IF EXISTS idx_deck_cards_deck')
            self.conn.commit()
            # Files from before the constraints: rebuilt with them, once. Left out are only cards
            # of decks that are gone and rows without copies or on a board there is not
            valid = ("deck_id IN (SELECT id FROM decks) AND CAST(quantity AS INTEGER) > 0 "
                     "AND board IN ('commander', 'main', 'side')")
            storage.rebuild(self.db_file, CONSTRAINTS_MIGRATION, [
                ('deck_cards', DECK_CARDS_TABLE,
                 f'SELECT id, deck_id, card_name, card_id, CAST(quantity AS INTEGER), board FROM deck_cards WHERE {valid}',
                 DECK_CARDS_INDEXES)],
                lambda conn: tuple(conn.execute(
                    f'SELECT COUNT(*), COALESCE(SUM(CAST(quantity AS INTEGER)), 0), COALESCE(MAX(id), 0) '
                    f'FROM deck_cards WHERE {valid}').fetchone()),
                prepare=LEGACY_TRIGGERS)
            # Files from before a deck could have a cover (2026-10-13): the decks table gets the
            # column, every deck as it was and without a cover chosen. A named migration like
            # the one above - a backup of the file first, one transaction, and the decks counted
            # and their names and dates compared before and after - although SQLite could add
            # this column in place: the same care for every change to a table that holds what
            # someone made.
            decks_as_they_are = lambda conn: (
                tuple(conn.execute('SELECT COUNT(*), COALESCE(MAX(id), 0) FROM decks').fetchone()),
                [tuple(row) for row in conn.execute(
                    'SELECT id, game, name, format, notes, created_at, updated_at FROM decks ORDER BY id')],
                tuple(conn.execute('SELECT COUNT(*) FROM deck_cards').fetchone()))
            # A file from before covers goes straight to today's table: the SELECT gives the
            # cover's place an empty text and the two newer columns their values for a deck
            # of before - and the kind migration below then finds its work done
            if storage.rebuild(self.db_file, COVER_MIGRATION, [
                    ('decks', DECKS_TABLE,
                     "SELECT id, game, name, format, notes, created_at, updated_at, '', 'paper', '' FROM decks", ())],
                    decks_as_they_are):
                with self._lock:
                    storage.record(self.conn, KIND_MIGRATION, f'with {COVER_MIGRATION}')
                    self.conn.commit()
            # Files from before decks had a kind (2026-10-13): every deck there is a deck of
            # cards on a shelf - 'paper' - and none came from Arena. The same care as above:
            # the file copied first, one transaction, the decks compared before and after
            # (their covers too, now that they have them).
            storage.rebuild(self.db_file, KIND_MIGRATION, [
                ('decks', DECKS_TABLE,
                 "SELECT id, game, name, format, notes, created_at, updated_at, cover, 'paper', '' FROM decks", ())],
                lambda conn: (decks_as_they_are(conn),
                              [tuple(row) for row in conn.execute('SELECT id, cover FROM decks ORDER BY id')]))

    def _require(self, deck_id):
        if not self.conn.execute('SELECT 1 FROM decks WHERE id = ?', (deck_id,)).fetchone():
            raise ValueError(f"Unknown deck: {deck_id}")

    # -- Decks ---------------------------------------------------------------

    def list_decks(self, game):
        """A game's decks of both kinds, most recently changed first, with their card counts"""
        with self._lock:
            rows = self.conn.execute('''
                SELECT d.*, COALESCE(SUM(CASE WHEN c.board != 'side' THEN c.quantity END), 0) AS cards,
                       COALESCE(SUM(CASE WHEN c.board = 'side' THEN c.quantity END), 0) AS side_cards
                FROM decks d LEFT JOIN deck_cards c ON c.deck_id = d.id
                WHERE d.game = ? GROUP BY d.id ORDER BY d.updated_at DESC, d.id DESC''', (game,)).fetchall()
            commanders = {}
            for row in self.conn.execute('''
                    SELECT c.deck_id, c.card_name FROM deck_cards c JOIN decks d ON d.id = c.deck_id
                    WHERE d.game = ? AND c.board = 'commander' ORDER BY c.id''', (game,)):
                commanders.setdefault(row['deck_id'], []).append(row['card_name'])
        return [{**dict(row), 'commanders': commanders.get(row['id'], [])} for row in rows]

    def get(self, deck_id):
        """The deck with its 'cards' ([{'name', 'card_id', 'quantity', 'board'}]), or None"""
        with self._lock:
            deck = self.conn.execute('SELECT * FROM decks WHERE id = ?', (deck_id,)).fetchone()
            if not deck:
                return None
            cards = self.conn.execute(
                'SELECT * FROM deck_cards WHERE deck_id = ? ORDER BY card_name COLLATE NOCASE', (deck_id,)).fetchall()
        return {**dict(deck), 'cards': [{'name': row['card_name'], 'card_id': row['card_id'],
                                         'quantity': row['quantity'], 'board': row['board']} for row in cards]}

    def create(self, game, name, deck_format, notes='', kind='paper', arena_id=''):
        if kind not in KINDS:
            raise ValueError(f"Unknown kind of deck: {kind}")
        with self._transaction():
            deck_id = self.conn.execute(
                'INSERT INTO decks (game, name, format, notes, created_at, updated_at, kind, arena_id) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (game, name.strip() or 'New deck', deck_format, notes or '', now(), now(), kind, arena_id or '')).lastrowid
        return deck_id

    def replace_arena_decks(self, game, decks):
        """
        Every Arena deck of the game is replaced by the decks of this export - all at once, or
        not at all: after an import with a deck file, the Arena decks are exactly the ones in
        that file. A deck that is gone from Arena goes here, one that changed there changes
        here, and a deck that is still there keeps its cover (found again by Arena's id for
        it). Arena decks made or copied here go too (since 2026-11-13: before, they had no
        arena_id and stayed); paper decks are never touched.

        decks: [{'arena_id', 'name', 'format', 'cards': [{'name', 'card_id', 'quantity',
        'board'}]}]. Returns the new decks' ids.
        """
        with self._transaction():
            covers = {row['arena_id']: row['cover'] for row in self.conn.execute(
                "SELECT arena_id, cover FROM decks WHERE game = ? AND arena_id != ''", (game,))}
            # kind, not arena_id: an Arena deck made here (arena_id '') goes as well - the file is the
            # whole list of Arena decks. self.delete takes each deck's cards with it (same transaction)
            for row in self.conn.execute("SELECT id FROM decks WHERE game = ? AND kind = 'arena'", (game,)).fetchall():
                self.delete(row['id'])
            made = []
            for deck in decks:
                deck_id = self.create(game, deck['name'], deck['format'], kind='arena', arena_id=deck['arena_id'])
                self.import_cards(deck_id, deck['cards'])
                names = {card['name'] for card in deck['cards']}
                if covers.get(deck['arena_id']) in names:
                    self.conn.execute('UPDATE decks SET cover = ? WHERE id = ?', (covers[deck['arena_id']], deck_id))
                made.append(deck_id)
        return made

    def update(self, deck_id, name=None, deck_format=None, notes=None, cover=None):
        """Change what is given (None: as it is). cover: a card's name, or '' for none chosen"""
        with self._transaction():
            deck = self.conn.execute('SELECT * FROM decks WHERE id = ?', (deck_id,)).fetchone()
            if not deck:
                return False
            self.conn.execute('UPDATE decks SET name = ?, format = ?, notes = ?, cover = ?, updated_at = ? WHERE id = ?', (
                (name.strip() if name is not None else '') or deck['name'], deck_format or deck['format'],
                notes if notes is not None else deck['notes'],
                cover if cover is not None else deck['cover'], now(), deck_id))
        return True

    def delete(self, deck_id):
        with self._transaction():
            self.conn.execute('DELETE FROM deck_cards WHERE deck_id = ?', (deck_id,))
            deleted = self.conn.execute('DELETE FROM decks WHERE id = ?', (deck_id,)).rowcount
        return bool(deleted)

    def duplicate(self, deck_id, kind=None):
        """
        A copy of a deck; returns its id (None: no such deck). kind: the copy's kind - the
        deck's own when not given. A copy of the other kind is the same list counted against
        the other collection: an Arena deck copied as a paper deck shows which of its cards
        are on the shelf and what the rest would cost to buy. It is named after its kind
        ("... (Physical)", "... (Arena)") rather than "(copy)", to tell the two apart.
        """
        if kind is not None and kind not in KINDS:
            raise ValueError(f"Unknown kind of deck: {kind}")
        with self._transaction():  # the copy with its cards, or no copy
            deck = self.get(deck_id)
            if not deck:
                return None
            kind = kind or deck['kind']
            label = 'copy' if kind == deck['kind'] else 'Arena' if kind == 'arena' else 'Physical'
            # Made here, so not one of Arena's (no arena_id) - an Arena copy is still removed by the next import with a deck file
            new_id = self.create(deck['game'], f"{deck['name']} ({label})"[:80], deck['format'], deck['notes'], kind=kind)
            self.import_cards(new_id, deck['cards'])
            if deck['cover']:  # the copy looks like the deck it was made from
                self.conn.execute('UPDATE decks SET cover = ? WHERE id = ?', (deck['cover'], new_id))
        return new_id

    # -- Cards ---------------------------------------------------------------

    def _touch(self, deck_id):
        self.conn.execute('UPDATE decks SET updated_at = ? WHERE id = ?', (now(), deck_id))

    def _quantity(self, deck_id, name, board):
        row = self.conn.execute('SELECT quantity FROM deck_cards WHERE deck_id = ? AND card_name = ? AND board = ?',
                                (deck_id, name, board)).fetchone()
        return row['quantity'] if row else 0

    def set_card(self, deck_id, name, board, quantity, card_id=None):
        """Set how many copies of a card a board has (0 removes it)"""
        if board not in BOARDS:
            raise ValueError(f"Unknown board: {board}")
        with self._transaction():
            self._require(deck_id)
            if quantity <= 0:
                self.conn.execute('DELETE FROM deck_cards WHERE deck_id = ? AND card_name = ? AND board = ?',
                                  (deck_id, name, board))
            else:
                self.conn.execute('''
                    INSERT INTO deck_cards (deck_id, card_name, card_id, quantity, board) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(deck_id, card_name, board) DO UPDATE SET
                        quantity = excluded.quantity, card_id = COALESCE(excluded.card_id, card_id)''',
                                  (deck_id, name, card_id, int(quantity), board))
            self._touch(deck_id)

    def set_printing(self, deck_id, name, board, card_id):
        """Choose the printing an entry is shown in"""
        with self._transaction():
            self.conn.execute('UPDATE deck_cards SET card_id = ? WHERE deck_id = ? AND card_name = ? AND board = ?',
                              (card_id, deck_id, name, board))
            self._touch(deck_id)

    def add_card(self, deck_id, name, board, change=1, card_id=None):
        """Add (or, with a negative change, take out) copies; returns the new count"""
        with self._transaction():
            quantity = max(0, self._quantity(deck_id, name, board) + int(change))
            self.set_card(deck_id, name, board, quantity, card_id)
        return quantity

    def move_card(self, deck_id, name, from_board, to_board):
        """Move every copy of a card to another board (added to the copies already there) -
        in one commit: there and gone from here, or neither"""
        with self._transaction():
            quantity = self._quantity(deck_id, name, from_board)
            if not quantity or from_board == to_board:
                return
            # The printing shown comes along - unless the card is on the other board already,
            # which keeps the printing it shows there
            there = self._quantity(deck_id, name, to_board)
            printing = None if there else self.conn.execute(
                'SELECT card_id FROM deck_cards WHERE deck_id = ? AND card_name = ? AND board = ?',
                (deck_id, name, from_board)).fetchone()['card_id']
            self.set_card(deck_id, name, to_board, there + quantity, printing)
            self.set_card(deck_id, name, from_board, 0)

    def import_cards(self, deck_id, entries, replace=False):
        """Add entries ([{'name', 'quantity', 'board', 'card_id'}]) to a deck; returns how many cards"""
        # Read in full before anything is changed: a bad entry must not leave a deck half replaced.
        # (An entry without a quantity is one copy, one without a known board goes to 'main'.)
        rows = []
        for entry in entries:
            name = str(entry.get('name') or '').strip()
            if not name:
                raise ValueError('A card without a name')
            rows.append((deck_id, name, entry.get('card_id'), max(1, int(entry.get('quantity') or 1)),
                         entry.get('board') if entry.get('board') in BOARDS else 'main'))
        if replace and not rows:
            raise ValueError('No cards to replace the deck with')  # emptying a deck is not an import
        added = 0
        with self._transaction():
            self._require(deck_id)
            if replace:
                self.conn.execute('DELETE FROM deck_cards WHERE deck_id = ?', (deck_id,))
            for row in rows:
                quantity = row[3]
                self.conn.execute('''
                    INSERT INTO deck_cards (deck_id, card_name, card_id, quantity, board) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(deck_id, card_name, board) DO UPDATE SET quantity = quantity + excluded.quantity''',
                                  row)
                added += quantity
            self._touch(deck_id)
        return added

    def needed_by_name(self, game, commander_formats=(), kind='paper'):
        """
        {search_key(card name): [{'deck_id', 'deck', 'quantity'}]} over every deck of a game
        and a kind - which decks want a card, to tell when two decks need the same copy. Only
        decks of one kind can compete for a copy: a paper deck and an Arena deck never use
        the same card. The 'side' board of a deck in commander_formats is a list of cards
        being considered, not counted.
        """
        needed = {}
        with self._lock:
            rows = self.conn.execute('''
                SELECT d.id, d.name, d.format, c.card_name, c.board, c.quantity
                FROM deck_cards c JOIN decks d ON d.id = c.deck_id WHERE d.game = ? AND d.kind = ?''', (game, kind)).fetchall()
        for row in rows:
            if row['board'] == 'side' and row['format'] in commander_formats:
                continue
            decks = needed.setdefault(search_key(row['card_name']), [])
            existing = next((deck for deck in decks if deck['deck_id'] == row['id']), None)
            if existing:
                existing['quantity'] += row['quantity']
            else:
                decks.append({'deck_id': row['id'], 'deck': row['name'], 'quantity': row['quantity']})
        return needed
