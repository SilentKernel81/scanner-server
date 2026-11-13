#!/usr/bin/env python3
"""
An MCP server for the card scanner: lets an AI assistant (Claude Desktop, Claude Code, any MCP
client - also one that runs a local model) look at your decks and your collection and suggest
changes. By default it only READS: it asks the scanner server's web API, and `propose_deck_changes`
says what a change would do without making it. With --allow-deck-writes it can also change DECKS
(create one, change its cards, rename it - never delete, never anything outside the decks).

    mcp_server/card_scanner_mcp.py [--server http://192.168.1.23:5000] [--allow-deck-writes]
    mcp_server/card_scanner_mcp.py --check        (lists the decks and stops: is the server reachable?)

The server's address is --server, else the environment's CARD_SCANNER_URL, else
http://localhost:5000. It talks MCP over standard input / output (the client starts it).
The tools are in tools.py (plain functions, tested without the MCP library); this file only
registers them. Needs `pip install mcp` (README.md here).
"""
import argparse
import functools
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tools.py and scanner_api.py are beside this file

import tools  # noqa: E402
from scanner_api import ScannerApi, ScannerError  # noqa: E402

INSTRUCTIONS = """\
You can look at the user's Magic: The Gathering decks and card collection (kept by their card
scanner) and help them build and improve decks from the cards they own.
- Start with list_decks, then get_deck for one deck. 'owned' on a card is how many copies the user has.
- suggest_for_deck gives popular cards for a deck's commander and marks which the user owns.
- Prefer cards the user owns; say when a suggestion would need buying and what it costs.
- A card marked also_in_decks / used_by_another_deck is in another of the user's decks: say so.
- propose_deck_changes checks a change (legal? colours? owned?) but changes NOTHING.
- Every price is in the currency an answer names in 'prices_in' (US dollars or euros: the user's choice); 'unknown' means
  the scanner could not say - then do not name a currency for those prices.
- You cannot change the collection.{decks}
MTG Arena: a deck with kind 'arena' is played in MTG Arena, and the user has TWO collections - the paper
one and the Arena one (imported from an Arena export; collection_summary(collection='arena') says when).
- For an Arena deck, 'owned' is the Arena collection, and a missing card costs a WILDCARD of its rarity
  (basic lands are free), never money: talk in wildcards, compare with the wildcards the user has.
- Pass collection='arena' to search_collection / find_card / collection_summary / search_cards when the
  question is about Arena.
- To find cards for a 60-card deck, use search_cards(collection='arena', deck_format=<the deck's format>,
  owned_only=true, identity=<its colours>, text=<what the card should do>). suggest_for_deck only knows
  commander decks (EDHREC).
- A 60-card deck plays at most 4 copies of a card (basic lands excepted); propose_deck_changes checks it.
- An Arena deck that came from an Arena export (from_arena_export) is replaced by the next import: the user
  changes it in Arena itself.
"""

# What the instructions say about decks, read-only (the default) or with --allow-deck-writes
READ_ONLY_DECKS = """
- You cannot change the decks either: tell the user to make a change on the decks page."""
DECK_WRITES = """
- You CAN change decks: create_deck, change_deck, rename_deck (never delete one; nothing else can be
  changed). Before each write, show the user the change and get their yes - propose_deck_changes first
  for a change of some size. A write refused for problems changed nothing: fix the list, or ask the user
  whether to go ahead anyway (allow_problems). Decks that came from an Arena export cannot be changed
  (the next import replaces them): offer a new deck made from their list instead. Every Arena deck - also
  one made here - is removed by the user's next Arena import with a deck file: say so when making one, and
  offer a paper deck (kind 'paper') for a list to keep."""


def instructions(deck_writes):
    return INSTRUCTIONS.replace('{decks}', DECK_WRITES if deck_writes else READ_ONLY_DECKS)


def build_server(api, deck_writes=False):
    """The MCP server with the tools registered (the library is imported here, so tests of tools.py do not need it).
    deck_writes: also the three tools that change decks (--allow-deck-writes)"""
    try:
        from mcp.server.mcpserver import MCPServer            # mcp 2.x
        server = MCPServer('card-scanner', instructions=instructions(deck_writes))
    except ImportError:
        from mcp.server.fastmcp import FastMCP                # mcp 1.x
        server = FastMCP('card-scanner', instructions=instructions(deck_writes))
    from mcp.types import ToolAnnotations
    try:
        from mcp.server.mcpserver.exceptions import ToolError  # mcp 2.x
    except ImportError:
        from mcp.server.fastmcp.exceptions import ToolError    # mcp 1.x
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    def explained(function):
        """A ScannerError (no such deck, the server is away ...) reaches the assistant in its own words: the library hides every
        other error. Every answer says the currency of its prices (tools.with_currency)"""
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            try:
                return tools.with_currency(api, function(*args, **kwargs))
            except ScannerError as e:
                raise ToolError(str(e)) from None
        return wrapper

    @server.tool(annotations=read_only)
    @explained
    def list_decks() -> dict:
        """Every deck: id, name, format, commander, number of cards, and how many of them the user owns (owned_percent)."""
        return {'decks': tools.list_decks(api)}

    @server.tool(annotations=read_only)
    @explained
    def get_deck(deck: str, with_card_text: bool = False) -> dict:
        """A deck's cards by board (main, commander, side): quantity, copies owned, type, mana cost, power/toughness (a creature's), loyalty, the mana it makes, Game Changer, rarity, price (not for an Arena deck), other decks using the card; plus the format's problems and the totals. An Arena deck also has its wildcards (needed / have). `deck` is its name (or part of it), its commander, or its id. with_card_text adds each card's rules text (longer)."""
        return tools.get_deck(api, deck, with_card_text)

    @server.tool(annotations=read_only)
    @explained
    def check_deck(deck: str) -> dict:
        """The format's problems with a deck (illegal cards, too many copies, colours outside the commander) and its totals (price, copies missing)."""
        return tools.check_deck(api, deck)

    @server.tool(annotations=read_only)
    @explained
    def missing_cards(deck: str) -> dict:
        """The cards of a deck the user does not own enough copies of, with what the missing ones cost: money for a paper deck; for an Arena deck the cards to craft, the wildcards needed beside the ones the user has, and the cards Arena does not have."""
        return tools.missing_cards(api, deck)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
    @explained
    def suggest_for_deck(deck: str, per_category: int = 8, only_owned: bool = False) -> dict:
        """Cards other players put in a deck with the same commander (EDHREC): how often (inclusion_percent), how specific (synergy), the copies the user owns, and whether another of their decks uses it. only_owned=true leaves out what the user does not own. Needs the internet on the server; the first call can take several seconds."""
        return tools.suggest_for_deck(api, deck, per_category, only_owned)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
    @explained
    def what_can_i_build(kind: str = 'commanders', wait_seconds: int = 40, limit: int = 10) -> dict:
        """Decks the user's collection could make. kind='commanders': legendary creatures they own, by how much of their popular deck they own. kind='precons': preconstructed decks by the share they own. It asks other sites and can take minutes: it waits up to wait_seconds, then returns what it has (running=true means ask again for more)."""
        return tools.what_can_i_build(api, kind, wait_seconds, limit)

    @server.tool(annotations=read_only)
    @explained
    def propose_deck_changes(deck: str, add: list[dict] | None = None, remove: list[dict] | None = None) -> dict:
        """Work out what adding / removing cards would do to a deck - NOTHING IS CHANGED. add and remove are lists of {"name": "Card Name", "quantity": 1}. For each card added it says if it exists, is legal in the format, fits the commander's colours, the 4-copy limit of a 60-card deck, how many copies the user owns and which other decks use it; and the deck's size before and after. For an Arena deck: the wildcards finishing it would take after the change, and whether the user has them. The user makes the change on the decks page (or in Arena)."""
        return tools.propose_deck_changes(api, deck, add, remove)

    @server.tool(annotations=read_only)
    @explained
    def search_collection(text: str = '', set_code: str = '', rarity: str = '', card_type: str = '',
                          tag: str = '', location: str = '', in_a_deck: bool | None = None, limit: int = 25,
                          collection: str = 'paper') -> dict:
        """Search the cards the user owns by part of a name, set code (HOB), rarity, type (Creature), tag, location, and whether a deck uses them (in_a_deck true/false). collection: 'paper' or 'arena' (MTG Arena). Returns up to `limit` entries, most valuable first (by rarity for Arena), and how many matched. To search by rules text, colours or format, use search_cards."""
        return tools.search_collection(api, text, set_code, rarity, card_type, tag, location, in_a_deck, limit, collection)

    @server.tool(annotations=read_only)
    @explained
    def search_cards(collection: str = 'paper', deck_format: str = '', owned_only: bool = True, name: str = '',
                     text: str = '', card_type: str = '', identity: str = '', colors: str = '', cmc: float | None = None,
                     rarity: str = '', offset: int = 0, limit: int = 50, with_card_text: bool = False,
                     produces: str = '', sort: str = '') -> dict:
        """Search every card of the card database, like the decks page: by part of the name, rules text (text='lifelink'), type line (card_type='Creature'), colour identity within letters (identity='GW'), colours it must include (colors='R'; 'C' = colourless), mana value (cmc), rarity, legal in a format (deck_format='standard'), mana it can make (produces='G': mana creatures, rocks, lands), sort='popularity' (EDHREC's rank, the most played first); owned_only=true (the default) keeps the cards the user owns - in the paper collection or, collection='arena', in MTG Arena. 'owned' is the copies; when the card has them: 'power_toughness' ("4/3"), 'loyalty', 'produces' (mana letters), 'game_changer'. Only cards that can be played are offered, and only where the collection is: collection='arena' finds no paper-only card (Black Lotus), the paper one no Alchemy-only card. Pages of results: offset, and 'more' when there is another page. The tool to find candidates for a deck."""
        return tools.search_cards(api, collection, deck_format, owned_only, name, text, card_type, identity, colors, cmc,
                                  rarity, offset, limit, with_card_text, produces, sort)

    @server.tool(annotations=read_only)
    @explained
    def find_card(name: str, collection: str = 'paper') -> dict:
        """Everything about one card: how many copies the user owns (each printing, finish, location), which decks use them, and the card's type, cost, power/toughness, colours and rules text. collection: 'paper' or 'arena' (MTG Arena)."""
        return tools.find_card(api, name, collection)

    @server.tool(annotations=read_only)
    @explained
    def collection_summary(collection: str = 'paper') -> dict:
        """How big the collection is and what it is made of: card count, value, the biggest sets, rarities, card types, locations, and how many cards are in a deck. collection='arena': the MTG Arena collection - also its wildcards, gold and gems, and when it was exported from Arena."""
        return tools.collection_summary(api, which=collection)

    if deck_writes:
        register_deck_writes(server, api, explained, ToolAnnotations)
    return server


def register_deck_writes(server, api, explained, ToolAnnotations):
    """
    The tools that change decks - only registered with --allow-deck-writes, so a client of the
    read-only server never sees them. Marked as writes (readOnlyHint false): a client asks the user
    before each call. They reach nothing but the deck routes (ScannerApi.write).
    """
    adds = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
    changes = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

    @server.tool(annotations=adds)
    @explained
    def create_deck(name: str, deck_format: str, kind: str = 'paper', cards: list[dict] | None = None,
                    commander: str = '', allow_problems: bool = False) -> dict:
        """WRITES: make a new deck. deck_format: 'standard', 'commander', 'historic' ...; kind: 'paper' or 'arena' (planned against the MTG Arena collection); cards: [{"name": "Card Name", "quantity": 4, "board": "main" or "side"}]; commander: the commander's name in a commander format. Checked first like propose_deck_changes; refused with the problems when there are any, unless allow_problems=true. Show the user the list and get their yes first."""
        return tools.create_deck(api, name, deck_format, kind, cards, commander, allow_problems)

    @server.tool(annotations=changes)
    @explained
    def change_deck(deck: str, add: list[dict] | None = None, remove: list[dict] | None = None,
                    allow_problems: bool = False) -> dict:
        """WRITES: change a deck's cards. add / remove: [{"name": "Card Name", "quantity": 1, "board": "main" or "side"}] - a card is moved between boards by removing it from one and adding it to the other. Checked first exactly like propose_deck_changes; refused (nothing changed) when there is a problem, unless allow_problems=true. A deck that came from an Arena export is refused. Show the user the change and get their yes first."""
        return tools.change_deck(api, deck, add, remove, allow_problems)

    @server.tool(annotations=changes)
    @explained
    def rename_deck(deck: str, name: str = '', notes: str | None = None) -> dict:
        """WRITES: change a deck's name and / or its notes (notes: the whole new text; '' empties them). A deck that came from an Arena export is refused."""
        return tools.rename_deck(api, deck, name, notes)


def main():
    parser = argparse.ArgumentParser(description="MCP server for the card scanner's decks and collection")
    parser.add_argument('--server', default=os.environ.get('CARD_SCANNER_URL', 'http://localhost:5000'),
                        help="the card scanner server's address (default: CARD_SCANNER_URL, else http://localhost:5000)")
    parser.add_argument('--check', action='store_true', help="list the decks and stop (is the server reachable?)")
    parser.add_argument('--allow-deck-writes', action='store_true',
                        default=os.environ.get('CARD_SCANNER_DECK_WRITES') == '1',
                        help="also the tools that change decks: create, change cards, rename (never delete; "
                             "nothing outside the decks). Default: read-only (or CARD_SCANNER_DECK_WRITES=1)")
    args = parser.parse_args()
    api = ScannerApi(args.server)
    if args.check:
        try:
            decks = tools.list_decks(api)
        except ScannerError as e:
            sys.exit(str(e))
        print(f"{args.server}: {len(decks)} decks")
        for deck in decks:
            print(f"  #{deck['id']} {deck['name']} ({deck['format']}) {deck['owned_percent']}% owned")
        return
    build_server(api, deck_writes=args.allow_deck_writes).run()   # standard input / output: the client starts this program


if __name__ == '__main__':
    main()
