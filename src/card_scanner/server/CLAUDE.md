# CLAUDE.md - the web app

Loaded when working under this folder. Moved here from the root `CLAUDE.md` (2026-10-30) word for word; the
project-wide rules stay there. Module names are written bare, as in the root file.
Prices, which `server/card_data.py` also handles: `../core/CLAUDE.md`.

## Where things live

| Area | Code |
|---|---|
| The picture index for a phone that reads cards on its own (the Android app's standalone mode: `reading/PictureReader.kt` there, the same decisions as `live_read` with OCR off; its table's columns are read by name - a new one goes at the END) | `server/stations_api.py`: `image_index_download`, `image_index_file`, `index_for_download`, `index_printings_table` (`GET /api/image_index/download[/<hashes\|ids\|printings>]`, station token, current generation only, resumable; the listing's `building` / `card_data_updating` say the index is changing and the app's `IndexDownload.ServerBusy` waits then - keep both sides in step); `image_index.py`: `printings_table`; `database.py`: `printing_facts`; `tests/test_index_download.py` |
| Pages | `templates/stations.html` (the cameras), `scanner.html` + `static/js/scanner.js` (one camera: `STATION`, `suggestedFinish`, `displayCard`, `updateDetectionStatus`; the prompt editor), `collection.html` + `collection.js` (inventory, trades, statistics), `settings.html` + `settings.js` + `settings.css` (every setting, in seven sections since 2026-10-22 - `docs/plans/SETTINGS_REDESIGN_PLAN.md`: overview - one line per section, fed by the loaders (`setOverview`) - cameras - this camera, chosen at the top with its own `?station=` connection, then all cameras: capture size, sounds - card recognition - picture, OCR, vision AI - card data - the card database, the picture index, their automatic updates - backups, storage, and server - restart, network, password, debug mode; the old `#sounds` / `#data` are mapped (`OLD_CATEGORIES`); a control the server asks the password for carries `data-guarded` (its padlock, drawn by settings.css while a password is set) - a new guarded route or event needs it on its control; it has its own `$` / `api`: not `scanner.js`, `collection.js` or `library.js`), `decks.html` + `decks.js` + `decks.css` (the deck list and one deck: `/decks`, `/decks/<id>`; `showWhatTheAddressSays`, `renderDeckList`, `renderDeck`, `showDeckView`, `deckGroups`, `showAdding`); shared by all: `common.js`, `_topbar.html`, `_dialogs.html`, `_icons.html`; shared by the collection and deck pages: `library.js`, `_value_dialog.html` |

## Conventions and pitfalls

**Web UI**

- **JSON from NumPy**: values sent through `jsonify` / Socket.IO must be plain Python types
  (`bool(...)`, `float(...)`) - a `numpy.bool_` broke `/api/detection_status` once.
- **Restart after template changes**: Flask caches templates; a running server keeps serving
  the old page. Static files are served fresh - bump the `?v=N` query in the template when
  changing CSS / JS so browsers don't use cached copies.
- **No native `confirm()` / `alert()`**: browsers can silently block them, after which
  `confirm()` always returns false - this broke "Clear all". Use `confirmDialog()` /
  `choiceDialog()` / `notify()` in common.js.
- **Pages share code**: helpers used by more than one page live in `static/js/common.js` /
  `templates/_dialogs.html`; the header is `templates/_topbar.html` (brand, page links and the
  settings button stay in the same place on every page - only the `.topbar-page` part is a
  page's own; each page defines `openSettings()` and `inventoryChanged()`). `scanner.js` runs
  scanner-only code on load - never include it in another page.
- **Three scripts, two kinds of sharing.** `common.js` is loaded by every page;
  `library.js` only by the collection page and the deck pages (`$`, `api`, `money`,
  `valueDialog`, the card preview...) - never by the scanner page, whose `scanner.js`
  declares its own `$` and `socket`: the same name declared in two files stops a page from
  loading at all. A helper both `collection.js` and `decks.js` need goes into `library.js`.
- **The deck pages** are one template for two addresses (`/decks`, `/decks/<id>`): `decks.js`
  shows what the address says and changes it with `history.pushState` when a deck is opened
  or closed. Anything that opens or leaves a deck goes through `openDeck` / `closeDeck`, or
  the address and the page disagree. The two views of a deck (Columns, Stacks) render the
  same entries with the same buttons (`entryActionsHtml`: `data-change`, `data-move`,
  `data-printing` on a `.deck-row`) - a new action is added there once. They are made for a
  pointer (buttons and pictures appear on pointing); `scripts/check_deck_pages.py` tries
  them in a headless browser - on a server with copied data, it creates and deletes decks.
  The rules of the deck parts that were not redesigned are still in `collection.css`
  (its "Decks" section), which the deck pages load before `decks.css`.
- **The tab's icon** is said once, in `templates/_favicon.html` (included in each page's
  `<head>`): `static/favicon.svg` and `static/favicon.ico`, the same drawing - change both,
  and the copy written into `station_setup.html` as a `data:` address, and raise the `?v=`
  in the snippet. `/favicon.ico` is a route of its own (`server/pages.py`).
- **Nothing from the internet.** The pages load only from the server: the font is in
  `static/fonts/`, Socket.IO's client in `static/js/vendor/` (its version is in the file's
  name - a new version is a new file and a change in `scanner.html` and `collection.html`;
  keep it matching the server's python-socketio). No `<script>` or stylesheet from a CDN:
  a station network without internet must still work. Card pictures from Scryfall are the
  one thing that does come from outside.
- **Requests from other web pages are refused** (`server/access.py`: Host names, `Origin`,
  `Sec-Fetch-Site`, Socket.IO origins): never set `cors_allowed_origins="*"` or add CORS
  headers, and keep changes behind POST/PUT/DELETE (a GET from another site is only stopped
  under `/api/`). A new way to reach the server by a host name needs `flask.allowed_hosts`.
- **No machine's own values in `config.yaml`**: it is the shipped default. The camera is
  `usb_index: auto`, the Ollama endpoint is localhost (Docker sets `LOCAL_AI_ENDPOINT`); one
  setup's values go in Settings (`data/settings.json`, `data/api_keys.env`), the station's setup
  page or the environment.
- **No secret in `config.yaml`**: the cookie key is `data/secret_key` (made on first start).
- **`hidden` vs. display**: `.btn`, `.chip-toggle` etc. set `display`, which beats the `hidden`
  attribute; `collection.css` has `[hidden] { display: none !important }` for that page.
