# Card Scanner MCP server

Lets an AI assistant look at your **decks and collection** (kept by the scanner server) and help
you build and improve decks from the cards you own. By default it **only reads**: it asks the
scanner server's web API, and `propose_deck_changes` works out what a change would do without
making it - you make the change on the decks page. Started with **`--allow-deck-writes`** it can
also change **decks** (and nothing else): see *Changing decks* below.

It runs on the machine of the AI client (your laptop), not on the scanner server.

## Tools

| Tool | What it answers |
|---|---|
| `list_decks` | every deck: id, name, format, commander, cards, how much of it you own |
| `get_deck(deck, with_card_text=false)` | a deck's cards by board, with copies owned, type, cost, power/toughness, loyalty, the mana it makes, Game Changer, rarity, price, other decks using each card; problems and totals (an Arena deck: no prices, its wildcards) |
| `check_deck(deck)` | the format's problems (legality, copies, colours) and totals |
| `missing_cards(deck)` | what you don't own enough copies of, with the cost (an Arena deck: the cards to craft, the wildcards needed beside the ones you have, the cards Arena does not have) |
| `suggest_for_deck(deck, per_category=8, only_owned=false)` | popular cards for the deck's commander (EDHREC) with inclusion %, synergy, copies you own, whether another deck uses it |
| `what_can_i_build(kind='commanders'\|'precons')` | decks your collection could make (asks other sites: can take minutes, returns what it has) |
| `propose_deck_changes(deck, add, remove)` | what adding / removing cards would do: legal? in colours? at most 4 copies? owned? used by other decks? the wildcards it would take (Arena) - **changes nothing** |
| `search_collection(text, set_code, rarity, card_type, tag, location, in_a_deck, limit, collection)` | the cards you own |
| `search_cards(collection, deck_format, owned_only, name, text, card_type, identity, colors, cmc, rarity, offset, limit, with_card_text, produces, sort)` | the card data, like the decks page's search: by rules text, colours, mana value, rarity, legal in a format, the mana a card makes (`produces='G'`), most played first (`sort='popularity'`); only what you own by default, and only cards played where the collection is |
| `find_card(name, collection)` | copies owned (printing, finish, location), decks using them, the card's text |
| `collection_summary(collection)` | cards, value (and its currency), biggest sets, rarities, types, locations; Arena: wildcards, gold, gems, the export's date |

Every answer says the currency of its prices (`prices_in`: `USD` or `EUR`, the price source chosen in the scanner's
Settings; `USD` for a scanner from before that choice existed - one that answers 404 for it; `unknown` when the question
failed otherwise, a time-out or an error: never a guess).

`deck` is a name (or part of it), a commander, or an id. If it matches several decks the tool says which.

**MTG Arena.** `collection` is `paper` (the default) or `arena`: the digital collection, the last
import of an Arena export (Collection page > Arena). An Arena deck (`kind: arena`) is counted
against it, and a card it lacks costs a **wildcard** of its rarity (basic lands are free) - so its
answers say wildcards, not money. `suggest_for_deck` only knows commander decks (EDHREC); for a
60-card deck, `search_cards(collection='arena', deck_format='standard', identity='GW', text='lifelink')`
finds the candidates you own. A deck that came from an Arena export is replaced by the next import:
change it in Arena itself. An import with a deck file replaces every Arena deck, also one made here.

## Install (once)

```bash
uv venv ~/venvs/mcp-scanner --python 3.12
uv pip install --python ~/venvs/mcp-scanner/bin/python -r mcp_server/requirements.txt
~/venvs/mcp-scanner/bin/python mcp_server/card_scanner_mcp.py --server http://192.168.1.23:5000 --check
```

`--check` lists the decks and stops: it shows whether the server can be reached.

## Connect Claude

**Claude Code:**

```bash
claude mcp add card-scanner -- ~/venvs/mcp-scanner/bin/python \
    ~/Projects/scanner-server/mcp_server/card_scanner_mcp.py --server http://192.168.1.23:5000
```

**Claude Desktop** (`claude_desktop_config.json`, `mcpServers`):

```json
{
  "mcpServers": {
    "card-scanner": {
      "command": "/home/you/venvs/mcp-scanner/bin/python",
      "args": ["/home/you/Projects/scanner-server/mcp_server/card_scanner_mcp.py",
               "--server", "http://192.168.1.23:5000"]
    }
  }
}
```

The server's address can also be the environment's `CARD_SCANNER_URL`.

## Try it

Ask: *"List my decks."*, *"Which of my commander decks is the least complete?"*,
*"Suggest cards for Calling All Angels that I already own"*, *"What would it do to add Lightning
Bolt and Swords to Plowshares to Calling All Angels?"*, *"What are my most valuable rares?"*,
*"Improve my Green/White Arena deck with cards I own on Arena - how many wildcards would it take?"*

## A local model

Any MCP client works, also one in front of a local model (Ollama): the model needs **tool
calling** (try Qwen 3 / Llama 3.1 class models), and fewer tools help small models. The facts
(what you own, what is legal) come from the server, so they are right whichever model reads them.

## Changing decks (`--allow-deck-writes`)

Off by default. Add the flag (or `CARD_SCANNER_DECK_WRITES=1`) to the command the client starts, and three
more tools appear:

| Tool | What it changes |
|---|---|
| `create_deck(name, deck_format, kind, cards, commander, allow_problems)` | a new deck (paper or `arena`) from a list of `{name, quantity, board}` |
| `change_deck(deck, add, remove, allow_problems)` | a deck's cards: add, remove, move between `main` and `side` (remove from one board, add to the other) |
| `rename_deck(deck, name, notes)` | its name and notes |

- **Decks only.** `ScannerApi.write` sends nothing but `POST /api/decks`, `POST /api/decks/<id>/cards` and
  `PUT /api/decks/<id>` (`DECK_WRITE_ROUTES`); anything else is refused before it reaches the network. No
  delete: that stays on the decks page.
- **Checked whole, first.** A change goes through the checks of `propose_deck_changes` (exists, legal,
  colours, the 4-copy limit, a commander deck's one copy) and is refused - nothing sent - when one fails,
  unless `allow_problems=true`; the server applies a deck's card changes one card at a time, so the list is
  checked before any of it goes.
- **Not a deck from an Arena export:** the next import replaces it, so a change there would be lost; the
  tools refuse it (make a new deck from its list instead).
- The tools are marked as writes (`readOnlyHint: false`): a client asks before each call, and the
  instructions tell the assistant to show the change and get a yes first.

What it cannot do, with or without the flag: change the collection, the scanned cards, the Arena collection,
trades or settings. The scanner server itself has no login: this restriction is the MCP server's, not the
network's.

## Tests

`tests/test_mcp_tools.py` tests `tools.py` against a stand-in for the server (no network, no MCP
library) - also that the write tools reach only the deck routes and send nothing when a check fails.
The protocol itself was tried with the library's own client against the real server; the deck tools
(2026-10-29) against a throwaway server on a copy of test data, never the real one.
