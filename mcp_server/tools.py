"""
What the assistant can ask the card scanner about: the decks and the collection.

Every tool is a plain function taking the server's `ScannerApi` first, so that the tests can use
a stand-in and the MCP library is only needed in card_scanner_mcp.py. Nothing here changes
anything: the tools read, and `propose_deck_changes` works out what a change WOULD do and says
so - the person makes it on the decks page.

Answers are kept short on purpose (names, numbers, short lists): a local model does badly with
long tool results, and a cloud one is slower and costlier with them.
"""
import re
import time

from scanner_api import ScannerError

# ----------------------------------------------------------------------------
# The currency of every price
# ----------------------------------------------------------------------------


def currency(api):
    """
    The currency the server's prices are in ('USD', 'EUR': Settings > Card data > Prices). Only a server that has no such
    route (404: from before the choice existed, 2026-10-24) is known to price in TCGplayer's dollars; any other failure -
    a time-out, the server away, an error - says 'unknown', never a guess (a Codex review of 2026-10-24: euros were
    labelled dollars when the question failed)
    """
    try:
        return api.get('/api/prices/source').get('currency') or 'unknown'
    except ScannerError as e:
        return 'USD' if e.status == 404 else 'unknown'


def with_currency(api, answer):
    """A tool's answer with the currency of its prices beside them ('prices_in'): a bare number in euros would be read as
    dollars. card_scanner_mcp.py adds it to every answer"""
    if isinstance(answer, dict):
        # An Arena answer: said at its top, or - the deck tools' answers - in the deck it reports ('now')
        now = answer.get('now') if isinstance(answer.get('now'), dict) else {}
        if answer.get('kind') == 'arena' or answer.get('collection') == 'arena' or now.get('kind') == 'arena':
            # An Arena answer has no prices (find_card's card price aside, which is paper's): a currency there would
            # read as "this costs dollars", and a card in Arena costs a wildcard
            return {**answer, 'prices_in': 'none: MTG Arena cards cost wildcards'}
        return {**answer, 'prices_in': currency(api)}
    return answer


# ----------------------------------------------------------------------------
# Finding a deck, a card
# ----------------------------------------------------------------------------


def normal(text):
    """A name as typed -> what is compared: lower case, letters and digits only ("Giada, Font of Hope" = "giada font of hope")"""
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()


def front(name):
    """The front face of a double-faced card's name ("Delver of Secrets // Insectile Aberration")"""
    return normal((name or '').split(' // ')[0])


# The two collections a question can be about: the paper one (what the scanner scanned) and the
# digital one (what the user has in MTG Arena, the last import of an Arena export). The server
# picks with ?area=arena; an Arena deck's 'owned' is already counted against the digital one.
COLLECTIONS = ('paper', 'arena')

# Formats played with a commander: one copy of each card, and the side board is not played
COMMANDER_FORMATS = ('commander', 'brawl', 'standardbrawl', 'oathbreaker', 'duel', 'paupercommander')


def area_of(which):
    """'paper' / 'arena' -> the server's ?area= value (None: the paper collection, the default)"""
    which = (which or 'paper').strip().lower()
    if which not in COLLECTIONS:
        raise ScannerError("collection must be 'paper' or 'arena'")
    return 'arena' if which == 'arena' else None


def copy_limit(card):
    """
    How many copies of a card a 60-card deck may play: 4, but any number of a basic land, and of
    a card whose own text says so (Relentless Rats: "A deck can have any number of cards named ...")
    """
    if 'Basic' in (card.get('type_line') or ''):
        return None
    if 'any number of cards named' in (card.get('oracle_text') or ''):
        return None
    return 4


def deck_list(api):
    return api.get('/api/decks')['decks']


def find_deck(api, deck):
    """
    A deck's id from what the person said: its id, its name (or part of it), or its commander.
    Says which decks match when it is not one.
    """
    decks = deck_list(api)
    wanted = str(deck).strip()
    if wanted.isdigit():
        for item in decks:
            if item['id'] == int(wanted):
                return item
    key = normal(wanted)
    exact = [item for item in decks if normal(item['name']) == key]
    if len(exact) == 1:
        return exact[0]
    part = [item for item in decks if key and (key in normal(item['name'])
                                               or any(key in normal(name) for name in item.get('commanders') or []))]
    if len(part) == 1:
        return part[0]
    if not part:
        raise ScannerError(f"No deck matches '{deck}'. The decks are: " + ', '.join(f"{item['name']} (#{item['id']})" for item in decks))
    raise ScannerError(f"Several decks match '{deck}': " + ', '.join(f"{item['name']} (#{item['id']})" for item in part)
                       + ". Say which one (its name or id).")


def load_deck(api, deck):
    """The deck as the server's page counts it: cards with copies owned, issues, totals"""
    item = find_deck(api, deck)
    return api.get(f"/api/decks/{item['id']}")['deck']


def power_toughness(card):
    """{'power_toughness': '4/3'} for a card with them (a creature, a Vehicle; '*/1+*' as printed), else {} - so a
    sorcery's line says nothing about them. A card with faces: its front face's. A server from before 2026-11-11, or a
    card data not downloaded again since, has none: then nothing is said either"""
    power, toughness = card.get('power'), card.get('toughness')
    return {'power_toughness': f'{power}/{toughness}'} if power is not None and toughness is not None else {}


def card_facts(card):
    """
    What a card's line says of it beside type and cost, each only when it has it - so a sorcery's line stays short:
    power_toughness ("4/3"), loyalty (a planeswalker's), defense (a battle's), produces (the mana letters it can make:
    "G" for Llanowar Elves, "WUBRG"), game_changer: true (Commander's Game Changers, the brackets). A server or card
    data from before 2026-11-11 has none of them: then nothing is said
    """
    facts = power_toughness(card)
    for key in ('loyalty', 'defense'):
        if card.get(key) is not None:
            facts[key] = card[key]
    if card.get('produced_mana'):
        facts['produces'] = ''.join(card['produced_mana'])
    if card.get('game_changer'):
        facts['game_changer'] = True
    return facts


def card_line(entry, text=False, arena=False):
    """One card of a deck, as short as it can be said. arena: the deck is an Arena deck - its cards
    are crafted with wildcards of their rarity, so the rarity is said and a paper price is not"""
    card = entry.get('card') or {}
    line = {'name': entry['name'], 'quantity': entry['quantity'], 'owned': entry['owned'],
            'type': card.get('type_line'), 'cost': card.get('mana_cost') or '', 'cmc': card.get('cmc'),
            **card_facts(card), 'rarity': card.get('rarity')}
    if not arena:
        line['price'] = card.get('price')
    # Another deck wanting a basic land is no news (every deck does): left out; a long list is cut
    if entry.get('elsewhere') and 'Basic' not in (card.get('type_line') or ''):
        names = [other['deck'] for other in entry['elsewhere']]
        line['also_in_decks'] = names[:4] + ([f'and {len(names) - 4} more'] if len(names) > 4 else [])
    if text:
        line['text'] = card.get('oracle_text') or ''
    return line


# ----------------------------------------------------------------------------
# Decks
# ----------------------------------------------------------------------------


def list_decks(api):
    """Every deck: id, name, format, commander, number of cards and how much of it you own"""
    return [{'id': item['id'], 'name': item['name'], 'format': item['format'], 'kind': item['kind'],
             'commanders': item.get('commanders') or [], 'cards': item['cards'],
             'owned': item['owned'], 'owned_percent': item['owned_percent']} for item in deck_list(api)]


def get_deck(api, deck, with_card_text=False):
    """A deck's cards, by board (main / commander / side), with the copies you own, what it costs and its problems"""
    data = load_deck(api, deck)
    arena = data.get('kind') == 'arena'
    boards = {}
    for entry in data['cards']:
        boards.setdefault(entry['board'], []).append(card_line(entry, with_card_text, arena))
    for cards in boards.values():
        cards.sort(key=lambda card: (card.get('cmc') or 0, card['name']))
    answer = {'id': data['id'], 'name': data['name'], 'format': data['format'], 'kind': data['kind'],
              'notes': data.get('notes') or '', 'totals': arena_totals(data) if arena else data['totals'],
              'issues': data['issues'], 'boards': boards}
    if arena:
        answer.update(arena_facts(data), collection_imported=arena_imported(api, data))
    return answer


def arena_imported(api, data=None):
    """
    When the Arena collection the answer counts against was exported from Arena (the last import) - said in every Arena
    deck answer, so two answers from either side of an import are not read as disagreeing. data: the deck as the server
    sent it, whose 'collection_imported' was read with its copies and wildcards (one snapshot, since 2026-11-11). Only a
    server from before that, which does not send it, is asked separately - and an import can land between the two asks
    """
    if data is not None and data.get('collection_imported') is not None:
        return data['collection_imported'] or 'never: import an Arena export first'
    return (api.get('/api/arena').get('arena') or {}).get('exported') or 'never: import an Arena export first'


def arena_totals(data):
    """An Arena deck's totals without the paper prices (a card there costs a wildcard, not money)"""
    return {key: value for key, value in (data.get('totals') or {}).items() if 'price' not in key}


def arena_facts(data):
    """
    What an Arena deck's answer adds: the wildcards its missing cards would take beside the ones the
    account had at the last import (the deck payload's 'wildcards'), and whether the deck came with
    an Arena export - such a deck is replaced by the next import, so a change is made in Arena itself
    """
    return {'owned_means': 'copies in the MTG Arena collection (the last import)',
            'wildcards': data.get('wildcards') or {},
            'from_arena_export': bool(data.get('from_arena')),
            'how_to_change': ('make the change in MTG Arena (this deck came from an Arena export: the next import replaces it)'
                              if data.get('from_arena') else 'make the change on the decks page, then export the deck to Arena - '
                                   'the next Arena import with a deck file removes this deck')}


def check_deck(api, deck):
    """The format's problems with a deck (legality, copies, colours), and what is missing from your collection for it"""
    data = load_deck(api, deck)
    arena = data.get('kind') == 'arena'
    answer = {'name': data['name'], 'format': data['format'], 'kind': data['kind'],
              'issues': data['issues'] or 'No problems found',
              'totals': arena_totals(data) if arena else data['totals']}
    if arena:
        answer['wildcards'] = data.get('wildcards') or {}
        answer['collection_imported'] = arena_imported(api, data)
    return answer


def missing_cards(api, deck):
    """The cards of a deck you do not own (enough copies of), with what they cost"""
    data = load_deck(api, deck)
    if data.get('kind') == 'arena':
        return missing_on_arena(api, data)
    wanted = {}
    for entry in data['cards']:
        if entry['board'] == 'side' and data['format'] in COMMANDER_FORMATS:
            continue   # the side board of a commander deck is not played
        slot = wanted.setdefault(entry['name'], {'quantity': 0, 'owned': entry['owned'], 'price': (entry.get('card') or {}).get('price') or 0})
        slot['quantity'] += entry['quantity']
    missing = [{'name': name, 'missing': slot['quantity'] - slot['owned'], 'price_each': slot['price']}
               for name, slot in sorted(wanted.items()) if slot['quantity'] > slot['owned']]
    return {'deck': data['name'], 'missing_cards': missing, 'copies_missing': sum(card['missing'] for card in missing),
            'cost_of_the_missing': round(sum(card['missing'] * (card['price_each'] or 0) for card in missing), 2)}


def missing_on_arena(api, data):
    """
    An Arena deck's missing cards, as the decks page's Arena window counts them
    (GET /api/decks/<id>/arena -> 'check'): what would be crafted, the wildcards that takes
    beside the ones the account had, and the cards Arena does not have at all
    """
    window = api.get(f"/api/decks/{data['id']}/arena")
    check = window.get('check') or {}
    wildcards = check.get('wildcards') or {}
    needed, have = wildcards.get('needed') or {}, wildcards.get('have') or {}
    short = {rarity: count - (have.get(rarity) or 0) for rarity, count in needed.items() if count > (have.get(rarity) or 0)}
    return {'deck': data['name'], 'kind': 'arena',
            'collection_imported': check.get('imported') or 'never: import an Arena export first',
            'to_craft': check.get('craft') or [],
            'wildcards_needed': needed, 'wildcards_have': have,
            'can_craft_all_now': not short, 'wildcards_short': short,
            'copies_not_on_arena': check.get('not_on_arena') or 0,
            'cards_not_on_arena': window.get('left_out') or []}


def suggest_for_deck(api, deck, per_category=8, only_owned=False):
    """
    Cards players put in a deck with the same commander (EDHREC), with how often (inclusion %) and
    how specific to this commander (synergy), marked with the copies you own and whether another
    of your decks uses them. Needs the internet on the server; slow the first time (a few seconds).
    """
    item = find_deck(api, deck)
    if not item.get('commanders'):
        # EDHREC's lists are by commander: a 60-card deck has none to ask about. search_cards is the way there
        return {'deck': item['name'], 'message': ('No suggestions: they come from EDHREC, which knows commander decks only. '
                                                  'Use search_cards (owned_only, the deck\'s format and colours) to find candidates.')}
    answer = api.get(f"/api/decks/{item['id']}/suggestions")
    if not answer.get('categories'):
        return {'deck': item['name'], 'message': answer.get('message') or 'No suggestions for this deck'}
    categories = []
    for category in answer['categories']:
        cards = [{'name': card['name'], 'type': card.get('type_line'), 'cost': card.get('mana_cost') or '',
                  'inclusion_percent': card.get('inclusion'), 'synergy': card.get('synergy'),
                  'owned': card.get('owned', 0), 'used_by_another_deck': bool(card.get('elsewhere')),
                  'price': card.get('price')}
                 for card in category['cards'] if card.get('owned', 0) > 0 or not only_owned]
        if cards:
            categories.append({'category': category['title'], 'cards': cards[:max(1, int(per_category))]})
    return {'deck': item['name'], 'source': answer.get('url'), 'decks_it_is_based_on': answer.get('decks'),
            'categories': categories}


def what_can_i_build(api, kind='commanders', wait_seconds=40, limit=10):
    """
    Decks your collection could make. kind: 'commanders' (legendary creatures you own, ranked by how
    much of their popular deck you own) or 'precons' (preconstructed decks, by the share you own).
    It asks other sites one card at a time, so it can take minutes: this waits up to wait_seconds
    and then returns what it has with running=true - ask again to see more.
    """
    if kind not in ('commanders', 'precons'):
        raise ScannerError("kind must be 'commanders' or 'precons'")
    # The search is a background job on the server: start it, then look at it for a while. Its
    # answers are cached there, so asking again is quick.
    api.post(f'/api/decks/ideas/{kind}', {})
    deadline = time.time() + max(1, int(wait_seconds))
    while True:
        state = api.get_fresh(f'/api/decks/ideas/{kind}')   # never kept: it changes while it runs
        if not state.get('running') or time.time() > deadline:
            break
        time.sleep(2)
    items = state.get('items') or []
    return {'kind': kind, 'running': bool(state.get('running')), 'checked': state.get('done'), 'of': state.get('total'),
            'error': state.get('error'),
            'best': [{key: item.get(key) for key in ('name', 'commander', 'type', 'owned', 'total', 'percent', 'fit', 'url') if key in item}
                     for item in items[:max(1, int(limit))]]}


ARENA_PLAN_TRIES = 3


def import_of(account):
    """Which import the Arena account is from: (its revision, its time)"""
    return account.get('revision') or '', account.get('imported') or ''


def _on_one_arena_import(api, kind, compute):
    """
    compute() for a deck of this kind - for an Arena deck, against one import of the Arena collection. A plan reads
    several answers of the server's (the deck, a search for each card added, the collection): an import landing between
    them mixed two collections' copies, with one import's wildcards and date beside them. So the reads are bracketed by
    the account's import time, read fresh before and after (never a kept answer: an answer kept from before the import
    would pass the check). The same time on both sides: no import landed. Each try starts with nothing kept, so every
    read in it is of the server as it then is. compute gets the account read before; tried ARENA_PLAN_TRIES times.
    An import is told by its revision (one of its own, since 2026-11-11) and its time; a server from before revisions
    has only the time, to the second - there two imports in one second would look like one.
    """
    if kind != 'arena':
        return compute(None)
    for _try in range(ARENA_PLAN_TRIES):
        api.forget()
        before = api.get_fresh('/api/arena').get('arena') or {}
        result = compute(before)
        after = api.get_fresh('/api/arena').get('arena') or {}
        if import_of(after) == import_of(before):
            return result
    raise ScannerError(f'The Arena collection was imported again while the change was worked out, {ARENA_PLAN_TRIES} '
                       'times in a row: ask again once the import is done')


def propose_deck_changes(api, deck, add=None, remove=None):
    """
    Work out what a change to a deck WOULD do - nothing is changed. add / remove: lists of
    {'name': ..., 'quantity': 1, 'board': 'main' | 'side'}. Says, for each card added: whether it exists,
    whether it is legal in the deck's format, within the commander's colours, how many copies you own,
    and which other decks of yours use it; and the deck's size before and after. The person makes the
    change on the decks page (or, with deck writes on, change_deck makes it).
    """
    answer, _plan = _on_one_arena_import(api, find_deck(api, deck).get('kind'),
                                         lambda _account: _plan_changes(api, load_deck(api, deck), add, remove))
    return answer


def _plan_changes(api, data, add=None, remove=None):
    """
    The work of propose_deck_changes on a deck already loaded: (its answer, the plan) - the plan is
    what change_deck would send, {'add': [...], 'remove': [...]}, each item a /api/decks/<id>/cards
    change ({name as the card data spells it, board, change: +n / -n, card_id}). Only read here.
    """
    arena = data.get('kind') == 'arena'
    plan = {'add': [], 'remove': []}
    commander_cards = [entry for entry in data['cards'] if entry['board'] == 'commander']
    commander_format = bool(commander_cards) or data['format'] in COMMANDER_FORMATS
    commander_identity = set()
    for entry in commander_cards:
        commander_identity |= set((entry.get('card') or {}).get('identity') or [])
    # What the deck plays (the side board of a commander deck is not played)
    # (two boards can hold the same card - main and side of a 60-card deck: their copies add up)
    playing = {}
    for entry in data['cards']:
        if commander_format and entry['board'] == 'side':
            continue
        slot = playing.setdefault(front(entry['name']), {'name': entry['name'], 'quantity': 0, 'owned': entry['owned'],
                                                         'card': entry.get('card') or {}})
        slot['quantity'] += entry['quantity']
    cards_before = sum(card['quantity'] for card in playing.values())
    # Which decks use each card you own, by name (the collection entries say) - the Arena
    # collection's entries for an Arena deck: only other Arena decks share its copies
    users = {}
    for entry in collection(api, 'arena' if arena else 'paper'):
        for deck_name in entry.get('decks') or []:
            users.setdefault(front(entry['name']), set()).add(deck_name)

    added, removed, problems = [], [], 0
    for item in (add or []):
        name, quantity = str(item.get('name', '')).strip(), max(1, int(item.get('quantity') or 1))
        report = {'name': name, 'quantity': quantity}
        board = str(item.get('board') or 'main').lower()
        if board not in ('main', 'side'):
            report['problem'] = "board must be 'main' or 'side'"
            problems += 1
            added.append(report)
            continue
        if board == 'side':
            report['board'] = 'side'
        found = api.get('/api/cards/search', q=name, format=data['format'], kind=data['kind'])['cards']
        match = next((card for card in found if front(card['name']) == front(name)), None)
        if match is None:
            # Not among the cards legal in the format: is it a card at all - one played where the deck is (the server's
            # search offers an Arena deck only Arena's cards and a paper deck only paper's), or one of the other place?
            def named(kind):
                anywhere = api.get('/api/cards/search', q=name, kind=kind)['cards']
                return next((card for card in anywhere if front(card['name']) == front(name)), None)
            real = named(data['kind'])
            other = None if real else named('paper' if arena else 'arena')
            report['name'] = (real or other or {}).get('name') or name
            report['problem'] = (f"not legal in {data['format']}" if real
                                 else ('not on MTG Arena' if arena else 'only on MTG Arena, not on paper') if other
                                 else 'no card with this name in the card database')
            problems += 1
            added.append(report)
            continue
        report.update(name=match['name'], copies_owned=match.get('owned', 0), rarity=match.get('rarity'))
        if not arena:
            report['price'] = match.get('price')
        # What change_deck sends: the card data's spelling of the name, and the printing the search
        # picked (the one owned, when one is - the deck page then shows the user's own art)
        plan['add'].append({'name': match['name'], 'board': board, 'change': quantity, 'card_id': match.get('id')})
        if commander_format and board == 'side':
            # A commander deck's side board is cards being considered: not played, so no rule applies
            report['note'] = 'side board of a commander deck: considered, not played'
            added.append(report)
            continue
        identity = set(match.get('identity') or [])
        if commander_format and not identity <= commander_identity:
            report['problem'] = ("outside the commander's colours: the card is "
                                 f"{''.join(sorted(identity)) or 'colourless'}, the deck {''.join(sorted(commander_identity)) or 'colourless'}")
            problems += 1
        existing = playing.get(front(match['name']))
        if existing:
            report['already_in_deck'] = existing['quantity']
            # Commander formats play one copy of a card (basic lands excepted)
            if commander_format and 'Basic' not in (match.get('type_line') or ''):
                report['problem'] = report.get('problem', '') + ('; ' if report.get('problem') else '') \
                    + 'already in the deck (a commander deck plays one copy of a card)'
                problems += 1
        if not commander_format:
            # A 60-card deck: at most 4 copies of a card (basic lands, and cards that say so, excepted)
            limit = copy_limit(match)
            total = (existing['quantity'] if existing else 0) + quantity
            if limit and total > limit:
                report['problem'] = report.get('problem', '') + ('; ' if report.get('problem') else '') \
                    + f'{total} copies: a {data["format"]} deck plays at most {limit}'
                problems += 1
        others = sorted(users.get(front(match['name']), set()) - {data['name']})
        if others:
            report['also_used_by'] = others[:4] + ([f'and {len(others) - 4} more'] if len(others) > 4 else [])
        playing[front(match['name'])] = {'name': match['name'], 'owned': match.get('owned', 0), 'card': match,
                                         'quantity': (existing['quantity'] if existing else 0) + quantity}
        added.append(report)
    for item in (remove or []):
        name, quantity = str(item.get('name', '')).strip(), max(1, int(item.get('quantity') or 1))
        wanted_board = str(item['board']).lower() if item.get('board') else None
        # The deck's entry it is taken from: on the board asked for, else the main deck before the side board
        entries = [entry for entry in data['cards'] if front(entry['name']) == front(name)
                   and (wanted_board is None or entry['board'] == wanted_board)]
        entries.sort(key=lambda entry: {'main': 0, 'commander': 1, 'side': 2}.get(entry['board'], 3))
        if not entries:
            removed.append({'name': name, 'problem': 'not in the deck' + (f' ({wanted_board} board)' if wanted_board else '')})
            problems += 1
            continue
        entry = entries[0]
        taken = min(quantity, entry['quantity'])
        removed.append({'name': entry['name'], 'copies_removed': taken,
                        **({'board': entry['board']} if entry['board'] != 'main' else {})})
        plan['remove'].append({'name': entry['name'], 'board': entry['board'], 'change': -taken})
        # The copies played after it (a commander deck's side board is not played: nothing to count)
        existing = playing.get(front(name))
        if existing and not (commander_format and entry['board'] == 'side'):
            new_quantity = existing['quantity'] - taken
            if new_quantity > 0:
                playing[front(name)] = {**existing, 'quantity': new_quantity}
            else:
                del playing[front(name)]
    cards_after = sum(card['quantity'] for card in playing.values())
    # Copies the deck would need beyond what you own, after the change
    missing_after = sum(max(0, card['quantity'] - card['owned']) for card in playing.values())
    answer = {'deck': data['name'], 'format': data['format'], 'kind': data['kind'], 'nothing_was_changed': True,
              'add': added, 'remove': removed, 'problems': problems,
              'cards_before': cards_before, 'cards_after': cards_after,
              # a 60-card deck's side board counts too (its copies share the 4-copy limit); a commander deck's is not played
              'cards_counted': 'main deck and commander' if commander_format else 'main and side boards together',
              'copies_missing_after': missing_after,
              'note': 'Nothing was changed: make the change on the decks page.'}
    if arena:
        # What the deck would cost to finish in Arena after the change: one wildcard of a card's
        # rarity per copy not owned (basic lands are free), beside what the account had
        needed = {'common': 0, 'uncommon': 0, 'rare': 0, 'mythic': 0}
        for card in playing.values():
            short = max(0, card['quantity'] - card['owned'])
            rarity = (card.get('card') or {}).get('rarity')
            if short and rarity in needed and 'Basic' not in ((card.get('card') or {}).get('type_line') or ''):
                needed[rarity] += short
        have = (data.get('wildcards') or {}).get('have') or {}
        answer['wildcards_after'] = {'needed': needed, 'have': have,
                                     'enough': all(count <= (have.get(rarity) or 0) for rarity, count in needed.items())}
        answer['collection_imported'] = arena_imported(api, data)
        answer['note'] = 'Nothing was changed: ' + arena_facts(data)['how_to_change'] + '.'
    return answer, plan


# ----------------------------------------------------------------------------
# Changing decks - only when the MCP server is started with --allow-deck-writes
# ----------------------------------------------------------------------------
# Three tools, and they reach nothing but the deck routes (ScannerApi.write refuses any other path):
# create a deck, change its cards, rename it / change its notes. No delete - that stays on the
# decks page. Each change is worked out by the same checks as propose_deck_changes first, and is
# refused when they find a problem (unless allow_problems): the server applies a deck's card changes
# one card at a time, so a list is checked whole BEFORE any of it is sent.


def refuse_imported(data):
    """A deck that came with an MTG Arena export is replaced by the next import: a change made to it here would be lost"""
    if data.get('from_arena'):
        raise ScannerError(f"'{data['name']}' came from an MTG Arena export: the next import replaces it, so a change "
                           "made here would be lost. Change it in Arena itself, or make a new deck here (create_deck) "
                           "from its list and change that one.")


def deck_summary(data):
    """A deck as it is after a change: what to tell the user (an Arena deck in wildcards, a paper one in money)"""
    arena = data.get('kind') == 'arena'
    summary = {'id': data['id'], 'name': data['name'], 'format': data['format'], 'kind': data['kind'],
               'totals': arena_totals(data) if arena else data['totals'], 'issues': data.get('issues') or []}
    if arena:
        summary['wildcards'] = data.get('wildcards') or {}
    return summary


def change_deck(api, deck, add=None, remove=None, allow_problems=False):
    """
    Change a deck's cards - this WRITES. add / remove: lists of {'name', 'quantity', 'board': 'main' |
    'side'}; a card is moved between boards by removing it from one and adding it to the other. Checked
    first exactly as propose_deck_changes; any problem (not legal, colours, copies, not a card, not in
    the deck) refuses the whole change unless allow_problems=true - then only the cards that could be
    found are changed.
    """
    def planned(_account):
        data = load_deck(api, deck)
        refuse_imported(data)
        return data, *_plan_changes(api, data, add, remove)
    data, answer, plan = _on_one_arena_import(api, find_deck(api, deck).get('kind'), planned)
    if answer['problems'] and not allow_problems:
        return {**answer, 'changed': False,
                'note': f"Refused, nothing was changed: {answer['problems']} problem(s) above. Fix the list, or ask the "
                        "user whether to make the change anyway (allow_problems=true)."}
    # Removals first: a card moved from the main deck to the side board ends with its copies where they belong
    items = plan['remove'] + plan['add']
    if not items:
        raise ScannerError('Nothing to change: no card of the list could be found in the deck or the card data')
    api.write('POST', f"/api/decks/{data['id']}/cards", {'cards': items})
    return {'changed': True, 'deck': data['name'], 'add': answer['add'], 'remove': answer['remove'],
            'problems': answer['problems'], 'now': deck_summary(load_deck(api, data['id']))}


def create_deck(api, name, deck_format, kind='paper', cards=None, commander='', allow_problems=False):
    """
    Make a new deck - this WRITES. deck_format: 'standard', 'commander', 'historic' ...; kind: 'paper' or
    'arena' (planned against the MTG Arena collection); cards: [{'name', 'quantity', 'board': 'main' |
    'side'}]; commander: the commander's name for a commander format. Checked first like
    propose_deck_changes (legal, colours, copies); a problem refuses it unless allow_problems=true.
    An Arena deck made here (kind 'arena') is removed by the next Arena import with a deck file: every
    Arena deck is then the file's. A paper deck is never touched by an import.
    """
    name, deck_format, kind = str(name or '').strip(), str(deck_format or '').strip().lower(), str(kind or 'paper').lower()
    if not name:
        raise ScannerError('A deck needs a name')
    if not deck_format:
        raise ScannerError("A deck needs a format ('standard', 'commander', 'historic' ...)")
    if kind not in COLLECTIONS:
        raise ScannerError("kind must be 'paper' or 'arena'")
    # An empty deck of that format for the checks to work on (and the commander, for its colours)
    def planned(account):
        # The draft is made inside the try too: the commander's copies owned are read from the search, like the cards'
        draft = {'id': None, 'name': name, 'format': deck_format, 'kind': kind, 'cards': [], 'from_arena': False}
        # A commander only where the format has one: Standard, Historic, Pioneer ... have none (and the checks
        # would otherwise treat the deck as a commander deck - one copy of each card, the commander's colours)
        if commander and deck_format not in COMMANDER_FORMATS:
            raise ScannerError(f"{deck_format} has no commander: leave commander empty "
                               f"(commander formats: {', '.join(COMMANDER_FORMATS)})")
        if commander:
            found = api.get('/api/cards/search', q=commander, format=deck_format, kind=kind, commander=1)['cards']
            # The name as written, else the one commander whose name begins with it ("Giada" -> Giada, Font of Hope)
            leader = next((card for card in found if front(card['name']) == front(commander)), None)
            if leader is None:
                starting = [card for card in found if front(card['name']).startswith(front(commander))]
                if len(starting) > 1:
                    raise ScannerError(f"Several commanders match '{commander}': "
                                       + ', '.join(card['name'] for card in starting[:8]) + '. Say which one.')
                leader = starting[0] if starting else None
            if leader is None:
                raise ScannerError(f"'{commander}' is no commander legal in {deck_format}")
            draft['cards'].append({'name': leader['name'], 'quantity': 1, 'board': 'commander',
                                   'owned': leader.get('owned', 0), 'card': leader})
        if account is not None:
            # The wildcards and the date of the import the whole plan is read against (_on_one_arena_import)
            draft['wildcards'] = {'have': account.get('wildcards') or {}}
            draft['collection_imported'] = account.get('exported') or ''
        return (draft, *_plan_changes(api, draft, cards, None))
    draft, answer, plan = _on_one_arena_import(api, kind, planned)
    if answer['problems'] and not allow_problems:
        return {**answer, 'deck': name, 'created': False,
                'note': f"Refused, no deck was made: {answer['problems']} problem(s) above. Fix the list, or ask the "
                        "user whether to make it anyway (allow_problems=true)."}
    # The list as the decks page's "paste a list" reads it (parse_decklist): Commander / Deck / Sideboard,
    # the same card twice on one board added up
    boards = {'commander': {}, 'main': {}, 'side': {}}
    for entry in draft['cards']:
        boards['commander'][entry['name']] = 1
    for item in plan['add']:
        boards[item['board']][item['name']] = boards[item['board']].get(item['name'], 0) + item['change']
    sections = [(title, boards[board]) for title, board in (('Commander', 'commander'), ('Deck', 'main'), ('Sideboard', 'side'))
                if boards[board]]
    text = '\n\n'.join(title + '\n' + '\n'.join(f'{count} {card}' for card, count in cards_on.items())
                       for title, cards_on in sections)
    created = api.write('POST', '/api/decks', {'name': name, 'format': deck_format, 'kind': kind, 'text': text})
    return {'created': True, 'unknown_cards': created.get('unknown') or [], 'add': answer['add'],
            'problems': answer['problems'], 'now': deck_summary(created['deck'])}


def rename_deck(api, deck, name='', notes=None):
    """Change a deck's name and / or its notes - this WRITES. notes: the whole new text ('' empties them)"""
    data = load_deck(api, deck)
    refuse_imported(data)
    body = {}
    if str(name or '').strip():
        body['name'] = str(name).strip()
    if notes is not None:
        body['notes'] = str(notes)
    if not body:
        raise ScannerError('Nothing to change: give a new name or notes')
    changed = api.write('PUT', f"/api/decks/{data['id']}", body)
    return {'changed': True, 'was': data['name'], 'now': deck_summary(changed['deck'])}


# ----------------------------------------------------------------------------
# The card database (the decks page's card search)
# ----------------------------------------------------------------------------


def search_cards(api, which='paper', deck_format='', owned_only=True, name='', text='', card_type='', identity='',
                 colors='', cmc=None, rarity='', offset=0, limit=50, with_card_text=False, produces='', sort=''):
    """
    The decks page's card search (GET /api/cards/search): every card of the card database, one per
    name, with the copies owned - in the paper collection or, which='arena', in the MTG Arena one.
      deck_format  only cards legal in it ('standard', 'historic', 'commander' ...)
      owned_only   only cards the user owns (in that collection)
      name / text / card_type  part of the name / of the rules text ('lifelink') / of the type line ('Creature')
      identity     the colour identity must fit within these letters ('GW': green, white, both or colourless)
      colors       the identity must include these letters ('C' = colourless only)
      cmc          mana value exactly; rarity: common / uncommon / rare / mythic
      produces     mana letters the card must be able to make ('G': mana creatures, rocks, lands; 'C' colourless)
      sort         'popularity': by EDHREC's rank, the most played first (else by name)
    The server answers a page at a time: offset pages through, 'more' says another page is there.
    """
    arena = area_of(which) == 'arena'
    params = {'q': name, 'text': text, 'type': card_type, 'identity': identity.upper() if identity else '',
              'colors': colors.upper() if colors else '', 'cmc': cmc, 'rarity': rarity.lower() if rarity else '',
              'format': deck_format.lower() if deck_format else '', 'owned': 1 if owned_only else '',
              'kind': 'arena' if arena else '', 'offset': max(0, int(offset or 0)),
              'produces': produces.upper() if produces else '', 'sort': sort.lower() if sort else ''}
    answer = api.get('/api/cards/search', **params)
    cards = []
    for card in (answer.get('cards') or [])[:max(1, int(limit))]:
        line = {'name': card['name'], 'owned': card.get('owned', 0), 'type': card.get('type_line'),
                'cost': card.get('mana_cost') or '', 'cmc': card.get('cmc'), **card_facts(card),
                'identity': ''.join(card.get('identity') or []), 'rarity': card.get('rarity')}
        if not arena:
            line['price'] = card.get('price')
        if with_card_text:
            line['text'] = card.get('oracle_text') or ''
        cards.append(line)
    return {'collection': 'arena' if arena else 'paper', 'format': deck_format or 'any', 'owned_only': bool(owned_only),
            'offset': params['offset'], 'shown': len(cards), 'more': bool(answer.get('more')), 'cards': cards}


# ----------------------------------------------------------------------------
# The collection
# ----------------------------------------------------------------------------


def collection(api, which='paper'):
    """The entries of the paper collection, or of the Arena one (which='arena')"""
    area = area_of(which)
    return api.get('/api/inventory', area=area)['cards'] if area else api.get('/api/inventory')['cards']


RARITY_ORDER = {'common': 0, 'uncommon': 1, 'rare': 2, 'mythic': 3}


def short_entry(card, arena=False):
    """A collection entry as the assistant needs it (an Arena one has no condition, place, tags or price)"""
    line = {'name': card['name'], 'set': (card.get('set_code') or '').upper(), 'number': card.get('number'),
            'copies': card.get('quantity'), 'rarity': card.get('rarity'), 'type': card.get('type_line'),
            'used_by_decks': card.get('decks') or []}
    if not arena:
        line.update(finish=card.get('finish'), condition=card.get('condition'), location=card.get('location') or '',
                    tags=card.get('tags') or [], price=card.get('price'))
    return line


def search_collection(api, text='', set_code='', rarity='', card_type='', tag='', location='', in_a_deck=None, limit=25,
                      which='paper'):
    """
    Search the cards you own. text: part of a name (or oracle text is not searched here - use the
    decks page for that); set_code: e.g. 'HOB'; rarity: common/uncommon/rare/mythic; card_type: e.g.
    'Creature'; tag, location: as saved on the entry; in_a_deck: true = only cards a deck uses, false =
    only cards no deck uses. Returns up to `limit` entries and how many matched. which: 'paper' (the
    scanned collection) or 'arena' (the MTG Arena one - sorted by rarity there, as nothing costs money).
    To search by rules text, colours or format, use search_cards.
    """
    wanted = normal(text)
    found = []
    for card in collection(api, which):
        if wanted and wanted not in normal(card['name']):
            continue
        if set_code and (card.get('set_code') or '').lower() != set_code.lower():
            continue
        if rarity and (card.get('rarity') or '').lower() != rarity.lower():
            continue
        if card_type and card_type.lower() not in (card.get('type_line') or '').lower():
            continue
        if tag and tag.lower() not in [t.lower() for t in card.get('tags') or []]:
            continue
        if location and location.lower() not in (card.get('location') or '').lower():
            continue
        if in_a_deck is not None and bool(card.get('decks')) != bool(in_a_deck):
            continue
        found.append(card)
    arena = area_of(which) == 'arena'
    if arena:
        found.sort(key=lambda card: (-RARITY_ORDER.get((card.get('rarity') or '').lower(), -1), card['name']))
    else:
        found.sort(key=lambda card: (-(card.get('price') or 0) * (card.get('quantity') or 1)))
    return {'collection': 'arena' if arena else 'paper', 'matches': len(found),
            'copies': sum(card.get('quantity') or 0 for card in found),
            'shown': min(len(found), int(limit)), 'sorted_by': 'rarity, highest first' if arena else 'total value, highest first',
            'cards': [short_entry(card, arena) for card in found[:max(1, int(limit))]]}


def find_card(api, name, which='paper'):
    """Everything about one card: the copies you own (printing, finish, where they are), the decks using them, and the card's
    text. which: 'paper' or 'arena' (the copies in MTG Arena, and the Arena decks using them)"""
    key = front(name)
    arena = area_of(which) == 'arena'
    owned = [card for card in collection(api, which) if front(card['name']) == key]
    details = None
    try:
        # The server's search offers an Arena search Arena's cards and a paper one paper's (since 2026-11-11): an
        # Alchemy-only card is found only by an Arena search, Black Lotus only by a paper one
        found = api.get('/api/cards/search', q=name, **({'kind': 'arena'} if arena else {}))['cards']
        details = next((card for card in found if front(card['name']) == key), None)
    except ScannerError:
        pass   # the collection part is still an answer
    return {'name': (details or (owned[0] if owned else {})).get('name', name),
            'collection': 'arena' if arena else 'paper',
            'copies_owned': sum(card.get('quantity') or 0 for card in owned),
            'entries': [short_entry(card, arena) for card in owned],
            'card': None if not details else {'type': details.get('type_line'), 'cost': details.get('mana_cost'),
                                              **card_facts(details),
                                              'colours': details.get('colors'), 'identity': details.get('identity'),
                                              'rarity': details.get('rarity'),
                                              **({} if arena else {'price': details.get('price')}),
                                              'text': details.get('oracle_text')}}


def collection_summary(api, top=8, which='paper'):
    """How big the collection is and what it is made of: cards, value, the biggest sets, rarities, types, locations.
    which='arena': the MTG Arena collection - its size, the wildcards, gold and gems at the last import, and when that was"""
    arena = area_of(which) == 'arena'
    cards = collection(api, which)

    def tally(key, weight=lambda card: card.get('quantity') or 0):
        counts = {}
        for card in cards:
            counts[key(card)] = counts.get(key(card), 0) + weight(card)
        return sorted(counts.items(), key=lambda pair: -pair[1])

    def main_type(card):
        line = (card.get('type_line') or '').split(' // ')[0]
        for kind in ('Creature', 'Land', 'Instant', 'Sorcery', 'Artifact', 'Enchantment', 'Planeswalker', 'Battle'):
            if kind in line:
                return kind
        return 'Other'
    if arena:
        account = api.get('/api/arena').get('arena') or {}
        return {'collection': 'arena', 'cards': account.get('cards'), 'different_entries': account.get('entries'),
                'exported_from_arena': account.get('exported') or 'never imported',
                'wildcards': account.get('wildcards') or {}, 'gold': account.get('gold'), 'gems': account.get('gems'),
                'by_set': tally(lambda card: card.get('set_name') or '?')[:top],
                'by_rarity': tally(lambda card: card.get('rarity') or '?'),
                'by_type': tally(main_type),
                'in_a_deck': sum(card.get('quantity') or 0 for card in cards if card.get('decks'))}
    stats = api.get('/api/stats')['collection']
    return {'collection': 'paper', 'cards': stats.get('total_cards'), 'different_entries': stats.get('unique_cards'),
            'value': stats.get('total_value'), 'currency': currency(api),
            'by_set': tally(lambda card: card.get('set_name') or '?')[:top],
            'by_rarity': tally(lambda card: card.get('rarity') or '?'),
            'by_type': tally(main_type),
            'by_location': tally(lambda card: card.get('location') or '(none)')[:top],
            'in_a_deck': sum(card.get('quantity') or 0 for card in cards if card.get('decks'))}
