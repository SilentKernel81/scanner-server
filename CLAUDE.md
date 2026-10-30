# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Camera-based scanner for Magic: The Gathering cards, split into a **server** and **camera
stations**. Cards are dropped onto a pile in a box under a camera; a station finds each new
card by its outline (OpenCV), captures it once and uploads the picture; the server reads it
(light-ocr first, a vision AI - Gemini / OpenAI / Anthropic / local Ollama - for what OCR can't
confirm: name, collector number, set code, ★/• foil marker), matches the exact printing in a
local Scryfall SQLite database, and adds it to the scanned cards, from where it goes into the
collection.

| Program | Where it runs | Entry point |
|---|---|---|
| Server (Flask + Socket.IO web app; collection, decks, OCR, AI) | One machine, normally the Docker image (target `server`) | `app.py` (a launcher; the server is the package `src/card_scanner/server/`) |
| Camera station (camera, detection, auto-capture, focus) | Each machine with a USB webcam - PC, laptop, Raspberry Pi; Docker image (target `client`) or a venv | `station.py` (a launcher; the station is the package `src/card_scanner/station/`) |
| Android app, in client mode a station too | A phone | its own repository, [SilentKernel81/mtg-scanner-android](https://github.com/SilentKernel81/mtg-scanner-android) (checked out beside this one, `../mtg-scanner-android`) |

The Android app is a Kotlin port of detection and auto-capture (and, standalone, of AI,
matching and the inventory); its README maps each Kotlin file to the Python code here - keep
both in step when changing that logic, the upload's answer (`ServerOutcome.parse` there) or the
collection CSV (`ExportParityTest` there).

**This code base lives in two checkouts, and changes are made in one of them.** The source of
truth is [SilentKernel81/scanner-server](https://github.com/SilentKernel81/scanner-server)
(`../scanner-server` when the other is open): every change is made, tested and committed
there. The other is [SilentKernel81/scanner](https://github.com/SilentKernel81/scanner)
(`../scanner`, "the standalone": one computer with a webcam, run from the AppImage or a
checkout): it is a mirror of that tree and takes changes only by `git merge server/main`
from its own checkout (its remote `server`; the remote `desktop` in the server's checkout
stays fetch-only, nothing is pushed from one to the other). **Never edit a file in the
standalone's checkout** - the next merge would conflict, and the change would be missing from
the server. The two must differ only in what starts the camera: the standalone starts a
station beside the server on the same machine (`scripts/start.sh`, the AppImage's `AppRun`),
the server receives the captures of stations elsewhere. So code that exists for one of them
only goes behind that difference - a launcher, a setting - never into a file the other has too.

The project is developed entirely with AI (this assistant, directed by the user), and the
documentation says so (README.md, *How this project was built*): keep that statement true and
in place, and keep marking in the docs what was measured and what was never tested.

**The license is PolyForm Noncommercial 1.0.0** (since 2026-10-19; MIT before, and copies of those
versions stay MIT): free for personal and other noncommercial use, no resale or commercial use.
The source is public but this is *source-available*, not open source - never describe the
project as "open source" (README, docs, videos, store texts). The Android app's repo has the
same license; the standalone `scanner` mirror gets it by merging `server/main`.

**How everything works is documented in [docs/PROGRAM_DOCUMENTATION.md](docs/PROGRAM_DOCUMENTATION.md)**
(stations, detection, auto-capture rules, matching, foil logic, schema, events, measured
thresholds) - read the relevant section before changing behavior, and keep it up to date.
User docs: [README.md](README.md); what the program does: [docs/FEATURES.md](docs/FEATURES.md) (add a line there
when a feature is added, with what was never tried); installation: [docs/INSTALL.md](docs/INSTALL.md); manual test list:
[docs/TEST_CASES.md](docs/TEST_CASES.md).

## Common Commands

```bash
# server
docker compose up -d --build                                                   # data/ and scanned_cards/ are volumes
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.gpu.yml up -d --build   # ... with OCR on an NVIDIA GPU
venv/bin/python app.py                    # without Docker (the server never opens a camera)
venv/bin/python scripts/setup_database.py # (re)download the Scryfall card database
venv/bin/python scripts/cleanup.py --stats  # capture images; --days N / --dry-run / --all

# camera station, on the machine the webcam is plugged into
docker compose -f deploy/docker-compose.client.yml up -d --build         # SCANNER_SERVER in .env
venv/bin/python station.py --server http://<server>:5000   # without Docker (requirements-client.txt)

# tests
venv/bin/python -m unittest discover tests

# single machine without Docker: the server and a station for its camera, side by side
./scripts/deploy.sh [--service | --update | --camera N]      # --service installs both units
./scripts/start.sh [--no-station]                            # both programs; Ctrl+C stops both
```

Dependencies: `requirements.txt` (server, ~300 MB, Python 3.10+; the OCR reader also needs
Node.js 22+ and `npm install` in `src/ocr/`), `requirements-client.txt` (station). The dev venv on
this machine is Python 3.12 and has both.

**Testing.** `tests/`: unit tests on temporary databases and stand-ins - each file's header says what it
covers; `tests/app_surface.json` is the recorded list of the server's routes and events. Nothing else is
automated: verify changes
by running the programs, and for scanner logic by feeding recorded / synthetic frames through
`CardScanner` with a fake camera (patch `detect_camera_type` / `_initialize_usb_camera`).
**Never test against a server's real `data/`** (adds, clears, forgets, imports, load tests):
use copies of the databases in a temporary folder - as the tests do, also inside the server
container - or a second container with its own data folder and port.

## Where Things Live

**All the code is one package, `src/card_scanner/`** (since 2026-10-13), sorted by which
program a module belongs to. Module names are written bare below - this says where each is:

| Folder | Modules |
|---|---|
| `card_scanner/` itself (both programs) | `paths.py`, `config.py`, `config_loader.py`, `settings.py` |
| `station/` (a camera station: all of it) | `station_client.py`, `station_setup.py` + `station_setup.html`, `station_login.py`, `scanner.py`, `object_detector.py` |
| `core/` (no web app, no camera) | `identification.py`, `card_ocr.py`, `card_identifier.py`, `prompts.py`, `api_keys.py`; `database.py`, `card_search.py`, `setup_database.py`; `inventory.py`, `decks.py`, `trades.py`, `arena.py`, `backups.py`, `storage.py`, `pending.py`, `review.py`, `cleanup.py`; `stations.py`, `remote_scanner.py`, `recommendations.py`, `frames.py` (camera frames behind captures, training data), `card_back.py` (is a capture a card's back) |
| `server/` (the web app) | the `server/...` modules below; its pages in `server/templates/`, `server/static/` (written `templates/...`, `static/...` below) |
| `games/` | `base.py`, `mtg.py`, `mtg_decks.py` |

Imports are written out in full (`from card_scanner.core import inventory`,
`from card_scanner.config import Config`). The OCR reader (Node.js) is beside the package,
in `src/ocr/`. The top folder has two Python files, the launchers `app.py` (server) and
`station.py` (a station), plus `config.yaml`, `.env` and the data (`data/`, `scanned_cards/`,
`station_captures/`). `hardware/` holds what is printed and flashed, not run by either program
(the card dropper's CAD and its Pico firmware). `scripts/setup_database.py` and `scripts/cleanup.py` start the two tools.

**More of this map, and the rules that go with it, lie beside the code** - each loaded when working
under its folder: [`src/card_scanner/station/CLAUDE.md`](src/card_scanner/station/CLAUDE.md) (the camera station: capture,
detection, focus, its setup page, the dropper's station side), [`src/card_scanner/core/CLAUDE.md`](src/card_scanner/core/CLAUDE.md)
(reading a card: OCR, the AI, the picture index and printing check, the decision, the foil marker; prices),
[`src/card_scanner/server/CLAUDE.md`](src/card_scanner/server/CLAUDE.md) (the pages and the web UI's rules; the picture index
download), [`hardware/CLAUDE.md`](hardware/CLAUDE.md) (the card dropper's mechanism). Read the one for the code you touch
even when working from elsewhere.

| Area | Code |
|---|---|
| **Server** | |
| One desk per camera: whose card, review and events this is | `server/desks.py`: `Desk`, `desk`, `desk_for`, `in_desk`, `at_station`, `emit_desk`, the `scanner` proxy, `make_remote_scanner`; `server/scan_events.py`: `handle_connect` (`page_stations`) |
| A station's capture arriving; kept until settled | `server/stations_api.py`: `station_capture`; `server/captures.py`: `submit_capture`, `resume_pending`; `server/stations_api.py`: `capture_outcome_response`; `server/state.py`: `seen_captures`; `pending.py`: `PendingCaptures` (`settle`, `fail`, `settled`), `APPLIED_CAPTURES_TABLE` (`data/pending_captures.db`) |
| Where one capture's copy is, and removing it (the phone's list) | `server/stations_api.py`: `station_capture_sync`, `removed_from_scanned`, `removed_from_review`; `inventory.py`: `captured_copy`, `UNFOLLOWED_CAPTURES_TABLE`; `review.py`: `by_capture`; `server/scan_events.py`: `handle_add_inventory` (the key handed on); `server/captures.py`: `submit_capture` (`sync_key`) |
| What becomes of a read card: lookup, automatic add, review, events | `server/captures.py`: `announce_and_route`, `route_identified` (returns the outcome), `search_and_emit_card`, `add_automatically`, `queue_for_review`; `server/desks.py`: `queue_changed`; `server/settings_events.py`: `set_auto_add`; `Game.suggested_finish` |
| Stations: registry, per-station settings, list / rename / forget | `stations.py`: `Stations`, `StationSettings` (`data/stations.json`); `server/stations_api.py`: `station_list`, `station_item`, `station_undo`; `server/inventory_api.py`: `clear_camera`; `scanner.js`: `loadStations`, `renderStations` |
| The server's stand-in for a station's camera; the stations' connection | `remote_scanner.py`: `RemoteScanner` (`METHODS`, `DECIDED`, `SENT`, `REPORTED`, `CAMERA_SETTINGS`), `CameraHub` (namespace `/station`) |
| Review queue (per station and game) | `review.py` (`review_queue`, `data/review/`, `ANY`, `clear`); the picture's candidates in an open item: `printing_check.py`: `PrintingCheck.candidates`, `server/scan_events.py`: `handle_review_open` (`candidates`), `scanner.js`: `reviewCandidatesHtml` (a tile is a `[data-printing]`: `select_printing`), `scripts/check_review_page.py` (headless browser); an entry sent back to it: `server/inventory_api.py`: `send_inventory_card_to_review`, `inventory.py`: `review_candidate`, `release_for_review` (no capture_key: it is noted in `unfollowed_captures`); `common.js`: `sendToReview`; `server/scan_events.py`: `review_open` / `review_skip` / `review_close`; `scanner.js`: `renderReview`, `reviewSearch` |
| Card games (the active one drives search, finishes, exports / imports) | `games/`: `base.Game`, `mtg.Magic`, `games.active()`; plan in `docs/plans/MULTI_GAME_IMPLEMENTATION_PLAN.md` |
| Card data: schema, updates, search, printing match, confidence | `database.py`: `CARD_COLUMNS` (`games`: where a printing is played), `_CARD_RARITY` (a card's rarity: its Arena printings' lowest, else all printings' - what the deck search filters on and wildcards are counted by), `replace_table`, `card_data_info`, `search_card_exact`, `search_card`, `find_printings`, `CONFIRMED_MATCHES`, `search_key`, `names_match`; `Game.check_for_update`; `server/card_data.py`: `start_card_data_update`, `check_card_data_updates` |
| Inventory: add / merge / undo / split / export, locations, tags, bulk edits, capture thumbnails | `inventory.py` (`KEY_COLUMNS`, `update_card`, `bulk_update`, `inventory_captures`, `data/captures/`); capture → add: `desk().pending_capture`, `card['capture']`; `scan_location` |
| Scanned cards by camera (filter, per-camera move, clear) | `inventory.py`: `inventory_sources`, `_station_rows`, `_move_sources`, `stations_by_entry`, `get_all_cards(station)`, `get_stats(station)`, `take_from(station)`, `clear_inventory(station)`; `server/captures.py`: `scan_camera`, `scan_stats`; `scanner.js`: `scannedCamera`, `loadInventoryCameras`; `common.js`: `addScannedToCollection(camera)` |
| Trades: cards set aside until a trade is confirmed (and cards it receives from someone's imported collection) | `trades.py`: `Trades` (`add`, `receive`, `set_receive_quantity`, `set_quantity`, `confirm`, `cancel`, `by_entry`); `inventory.py`: `TRADE_RECEIVES_TABLE`; `inventory.py`: `TRADES_TABLE`, `TRADE_CARDS_TABLE`, `TRADE_TRIGGERS`, `TRADE_HELD`; `server/trades_api.py`: `trade_list`, `trade_item` (`DELETE ?action=cancel` / `?action=forget`: each refuses the other's trade, never one in place of the other), `trade_confirm` (the `fingerprint` of the trade the person SAW - `collection.js` `tradeAction` keeps the on-screen one and asks nothing when it changed meanwhile, never adopting a newer one unseen; REQUIRED - a confirm without one is refused, 409 - `Trades.fingerprint`, every card and copy on both sides, never the price - refused when the trade changed), `trade_export`, `write_refused`; review and plan: `docs/plans/TRADES_REVIEW_PLAN.md`; `collection.js`: `loadTrades`, `renderTrades`, `setAsideForTrade`; a trade's sale picture (3 × 3 scans with their names, drawn on a canvas in the browser, no server route): `collection.js`: `openSalePicture`, `drawSalePicture`, `saveSalePicture`, `#sale-modal` in `collection.html` |
| Other people's collections to trade with / buy from, the buy list (`data/others.db`, apart from the collection) | `others.py`: `Others` (`import_collection`, `cards`, `buy`, `buy_list`), `card_dict`; `server/others_api.py`: `read_collection_file`, `chosen_cards`; `inventory.py`: `read_collection_csv`; `games/mtg.py`: `import_rows` (Moxfield, ManaBox); `collection.js`: `loadOthers`, `loadBuyList`; `tests/test_others.py` |
| Backups of the collection, scanned cards and decks | `backups.py`: `create` (`keep`), `create_scheduled`, `restore` (`RESTORABLE`), `archive` / `add_archive`, `list_backups`, `INVENTORY_TABLES` (`data/backups/<date_time>/`); `server/backups_api.py`: `collection_backups`, `restore_backup`; `collection.js`: `openSettings`, `renderBackups` |
| Everything at one moment (all database files + pictures) | `backups.py`: `create_full`; `server/backups_api.py`: `full_backup`; `server/state.py`: `maintenance_barrier`; `scripts/backup.sh` |
| Automatic updates of the card data and the picture index (off by default; like the backup schedule: "due", not a clock time) | `server/card_data.py`: `run_update_schedule`, `schedule_tick`, `scheduled_card_data_updates`, `card_data_due`, `scheduled_index_update`, `index_due` (`INDEX_AUTO_MIN_COVERAGE`: never a first build), `start_card_data_update` / `start_index_update` (`on_done`), `update_schedule_state`, `parse_update_schedule`, `GET` / `POST /api/updates/schedule` (guarded); `data/settings.json` `card_data_every_hours`, `image_index_every_hours`, `card_data_auto_last`, `image_index_auto_last`; `config.yaml` `database.auto_update_every_hours`, `reading.index_retry_every_hours`; `settings.js`: `showUpdateSchedule`; `tests/test_update_schedule.py`; plan: `docs/plans/UPDATE_SCHEDULE_PLAN.md` |
| Database connections, migrations, measurements | `storage.py`: `connect`, `rebuild`, `schema_migrations`; `scripts/benchmark_db.py` (on copies only) |
| Decks, deck checks, decklist text | `decks.py`: `DeckManager` (`DECKS_TABLE`, `cover`); `games/mtg_decks.py`: `DECK_FORMATS`, `check_deck`, `parse_decklist`, `format_arena` (the list for MTG Arena: `on_arena`, `arena_name`; `Game.arena_decklist`); `server/decks_api.py`: `deck_payload`, `deck_covers` (which card stands for a deck), `resolve_entries`; `database.py`: `search_cards`, `cards_by_names` |
| The digital collection (MTG Arena) and decks of two kinds | `arena.py`: `read_collection`, `read_decks`, `find_card`, `resolve`, `save_account` / `account`, `wildcards_needed`; `inventory.py`: `replace_all`; `decks.py`: `kind`, `arena_id`, `replace_arena_decks`, `needed_by_name(kind)`; `server/arena_api.py`: `arena_import`, `arena_info`; `server/inventory_api.py`: `digital_collection_is_read_only`; `server/decks_api.py`: `collection_of`, `arena_check`; `collection.js`: `showCollection`, `inArena`, `importArena`; `decks.js`: `deckKindShown`, `arenaCheckHtml`; `scripts/check_arena_pages.py` (copied data only) |
| Deck ideas from other sites (EDHREC, MTGJSON, Archidekt, Moxfield) | `recommendations.py`: `Recommendations` (`_get` cache + throttle, `Unavailable`); `server/decks_api.py`: `deck_suggestions`; `server/deck_ideas_api.py`: `popular_decks`, `run_deck_ideas`, `precon_covers` (the card a preconstructed deck is shown by; `decks.js`: `loadPreconCovers`, asked for as tiles come into view) |
| **MCP server** (an AI assistant reads the decks and the collection; its own folder, runs on the client's machine) | `mcp_server/`: `card_scanner_mcp.py` (registers the tools; `mcp` 2.x `MCPServer`, 1.x `FastMCP` as fallback), `tools.py` (the tools: plain functions of a `ScannerApi`), `scanner_api.py` (urllib client of the server's web API); Arena: `collection='arena'` (`?area=arena`), an Arena deck's cost in wildcards (`missing_on_arena` reads `/api/decks/<id>/arena`), `search_cards` (`/api/cards/search`); deck writes only with `--allow-deck-writes` (`create_deck`, `change_deck`, `rename_deck`; `scanner_api.DECK_WRITE_ROUTES` / `ScannerApi.write` refuse any other route; checked whole by `_plan_changes` first; no delete; never a `from_arena` deck); otherwise read-only, `propose_deck_changes` changes nothing; `tests/test_mcp_tools.py` (a stand-in API, no MCP library); README.md there. Keep it out of `src/` and the images: it imports nothing of the project and needs the `mcp` library |
| **Both** | |
| Desktop program (AppImage): launcher options, quit / restart, who can reach it, the station beside the server | `server/program.py`: `parse_arguments`, `network_access`, `listen_host`, `start_station` / `stop_station`, `exec_again_if_requested`; `server/startup.py`: `main`; `packaging/` (`AppRun`), `scripts/build-appimage.sh`, `.github/workflows/appimage.yml`; `templates/_program.html`, `common.js`: `quitProgram`, `restartProgram`, `setNetworkAccess` |
| Settings | `config.yaml` (+ `config.py`: also `SCANNER_CAMERA`, `SCANNER_CAMERA_INDEX`, `SCANNER_STATION_TOKEN`), `.env`; on the server `data/settings.json` (everyone's choices), `data/stations.json` (each station's), `data/api_keys.env`, `data/prompts.json` |
| Images | `deploy/`: `Dockerfile` (targets `server`, `client`, `client-pi` for a Raspberry Pi camera), `docker-compose.yml`, `docker-compose.gpu.yml`, `docker-compose.client.yml`, `docker-compose.client-pi.yml`, `.env` (a link to the top folder's); `compose.yaml` in the top folder (includes the server's file); `scripts/docker-entrypoint.sh` |

## Conventions and Pitfalls

**Server and stations**

- **The server is the package `server/`** (`card_scanner.server`), not one file: `server/__init__.py` lists its
  modules in the order they build on each other, and **a module imports only from those
  before it** (state, logs, lock, desks, captures, card_data, pages, decks_api, deck_ideas_api,
  inventory_api, arena_api, trades_api, backups_api, stations_api, scan_events, settings_events,
  ai_events, startup) - an import the other way is a cycle and fails at start. What two
  modules both need lives in the earlier one. Routes are plain `@app.route` on the one app
  from `server/state.py` (no Blueprints: templates use the endpoint names). A route or event
  exists once its module is imported: **a new module must be added to the list in
  `server/startup.py`**, and `tests/app_surface.json` recorded again - the surface test
  fails otherwise, on purpose.
- **Shared objects are proxies.** `database`, `inventory`, `scan_inventory`, `arena_inventory`, `review`,
  `stations`, `pending`, `identification`, `deck_store`, `trade_store`, `recommend`,
  `printing_check`, `camera_hub`, `app_settings` are imported from `server.state` and used as plain names; the
  real objects are attributes of `services`, set by `initialize_components`. `if inventory:`
  works, `inventory is None` never does; assign only through `services.x = ...`; values
  that change (`debug_mode_running`, `daily_backup_status`, `default_desk`) are always
  written and read as `services.x`.
- **Paths come from `paths.py`, not from `__file__`** (the one exception: a file that names
  another lying beside it, as `station_setup.py` does its page). `paths.TOP` is the top folder:
  what ships (`config.yaml` as shipped, `src/ocr`, `bin/`; `Config.BASE_DIR`). `paths.USER_DIR` is
  the person's folder - data, `scanned_cards/`, `.env`, their `config.yaml` laid over the shipped
  one (`Config.USER_DIR`, `Config.DATA_DIR`, `server.ROOT`): the same folder as TOP in a checkout
  and the images, `~/.mtg-scanner` when packaged, `MTG_SCANNER_HOME` chooses. Never
  write under TOP; name a file of `data/` in a message with `Config.shown('logs', 'app.log')`;
  find `node` / `v4l2-ctl` with `paths.tool()` (a missing `v4l2-ctl` means no focus control, said
  once). `paths.CODE` is
  the package's folder: use it for what belongs to the code (the pages). A path built from a
  file's own location means another folder as soon as the file moves - and a server whose
  data folder is a new, empty one starts without complaint. `tests/test_paths.py` checks
  every such path; a new one belongs in it.
- **The desktop program is this server with a launcher** (`server/program.py`, `app.py --app`):
  anything that exists only for it goes behind `services.app_mode` or in `packaging/`, never into
  a file a server does not also have. Try a change to the launcher or the packaging by building
  (`scripts/build-appimage.sh`) and running it with `MTG_SCANNER_HOME=/tmp/try ... --no-browser`.
- **One server per data folder**: `startup.lock_instance()` holds `data/app.lock` (flock, gone
  with the process); a second server on the same `USER_DIR` says so and exits.
- **Only the two launchers in the top folder, and `src/` first on Python's path.** `app.py`
  and `station.py` put it there, the images and the scripts set `PYTHONPATH`, tests and
  `scripts/*.py` have their own first line; nothing inside the package touches the path. A
  file inside the package cannot be run by its path (Python would not find `card_scanner`):
  what is started is a launcher outside it - a new program needs one. `python -c` lines in
  the scripts import by the full name (`from card_scanner.config import Config`). The
  project is not pip-installed (see `pyproject.toml` for why); `requirements*.txt` are the
  lists of libraries.
- **Who may import whom is a test** (`tests/test_layout.py`): `station/` and the four shared
  modules import only each other; `core/` and `games/` import nothing of `server/` or
  `station/`; no relative imports; no import by a bare old name (`import inventory`). The
  `__init__.py` of the package, of `station/` and of `core/` must stay empty of code - a
  station's image holds `station/` and the shared four and nothing else, so one import of
  `core/` there and no station starts. A new module goes into the folder of the program it
  belongs to, and its name into that folder's set in the test (`SHARED` / `STATION` / `CORE`).
- **Changing the server without changing what it does** (moving code, renaming inside):
  `scripts/walk_server.py` records what a server answers - run it before and after on fresh
  copies of the data (never real data) and `--compare`.
- **Two programs, and the camera is always the station's.** `scanner.py` /
  `object_detector.py` run in `station_client.py` only: the server opens no camera (removed
  2026-10-12), imports neither module, and its `scanner` is always a `RemoteScanner`. One
  machine as server and camera runs both programs (`scripts/start.sh`; two systemd units).
  Don't add a "local camera" branch back to the server. The client must not import server
  modules (`database`, `inventory`, `identification`, Flask) - the layout test refuses it -
  and its images copy `station.py`, `config.yaml`, the folder `card_scanner/station/` and
  the four shared modules by name: a new module in `station/` needs nothing, a new *shared*
  one must be added to the `COPY` lines of the `client` and `client-pi` targets (both, kept
  equal). After building an image,
  `docker run --rm --entrypoint python <image> -c "import card_scanner.station.station_client"`
  shows a missing one at once.
- **`RemoteScanner` mirrors `CardScanner`.** Anything the server reads or calls on `scanner` must
  exist on both: a new attribute goes into the client's `state()` and one of `DECIDED` / `SENT`
  / `REPORTED`; a new method into `METHODS` on both sides.
- **Camera settings live on the server.** The client's `CardScanner` gets a `ServerSettings`
  filled by `hello`; a new per-camera setting key must be in `CAMERA_SETTINGS` or it is neither
  sent nor saved. On the server they are per station (`StationSettings`), falling back to
  `data/settings.json`.
- **One desk per camera.** The handlers look single-camera, but `scanner` is a proxy for
  `desk().scanner`, and the card on a page, its open review and its capture are
  `desk().current_card_info` / `.current_review_id` / `.pending_capture` - never module globals.
  Code that runs outside a page's request (threads, callbacks) must be inside
  `with in_desk(...)`, or it works for `default_desk`. `if scanner:` works; `scanner is None`
  does not.
- **`emit_desk` vs `socketio.emit`.** What concerns one camera's card goes to its pages only
  (`emit_desk`); `socketio.emit` reaches every page - right only for shared things. A scanner
  page gets `?station=` on every `/api/` request from the `fetch` wrapper at the top of
  `scanner.js`, so a new route that depends on the camera needs nothing more than `desk()`.
- **Every queued capture goes through `submit_capture`** (on record until settled, its desk
  remembered, counted). Cards come back on `Identification`'s one results thread (`on_done`) -
  never route a card from the OCR / AI workers themselves. Station captures arrive on request
  threads, several at once.
- **A capture's copy can be asked about and removed by its station** (`station_capture_sync`,
  for the Android app's list). Its identity is the capture's uid (the `sync_key` in settled
  outcomes), carried by the copy's photo row (`inventory_captures.capture_key`) or its review
  item (`review_queue.capture_key`): anything new that moves copies must keep moving the photo
  rows with them, and a new way from review to the scanned cards must hand the key on, keep
  the capture's station as the card's `source`, and hold `maintenance_barrier` from reading
  the item to writing the card (as `handle_add_inventory` does - the route holds it too). Never
  answer `resolved` for a capture that is unknown or cannot be followed (404 / 409), and never
  give the collection's photo rows a key - that is what keeps a phone out of the collection.
- **Uploads are "at least once", a capture counts once.** `capture_id` makes a repeat the same
  capture (`seen_captures`, and `settled_captures` across a restart); a capture's `uid` is noted
  by whatever its result writes (`add_card(capture_key=)`, `review.add(capture_key=)`), in the
  same commit. A new place a capture's result is written to must take `capture_key()` too. Keep
  both when touching `station_capture`, `submit_capture` or the clients' retry loops.
  On a computer station a queued capture is on disk before it is in the queue
  (`write_note`: `station_captures/<image>.upload.json` with its `capture_id` and destination)
  and is queued again by the next start (`load_pending`); one taken for another server or
  station id is held for the setup page to decide, never sent on its own. Anything new that a
  capture needs to be sent must go into the note. A station's waiting captures live in
  `Config.STATION_CAPTURES_DIR` (`station_captures/`), never in the server's `scanned_cards/`:
  the server's clean-up deletes old pictures there, and server and station can share one
  checkout. A station must end on SIGINT and SIGTERM however it was started (`main` takes
  both signals back: a program a shell starts in the background ignores SIGINT).
- **A change is whole or not at all.** Inventory methods that write are `@_writes` (one
  transaction, the outermost commits and a failure rolls everything back; thumbnails of
  deleted captures go only after the commit - `_committed`);
  deck changes are inside `with self._transaction()` (`storage.Transactional`). **Reads never write**: no DELETE / UPDATE in a
  method that only returns rows - it leaves a write transaction open and other connections get
  "database is locked". A quantity is lowered together with `_trim_sources()` (before
  `_trim_captures`).
- **The database enforces what belongs together** (connections from `storage.connect`: foreign
  keys on). An entry or a station's row never has quantity 0: delete it (`_delete_entries`,
  `_take_copies`, `_set_source`) instead of `UPDATE ... quantity - n` followed by a clean-up -
  the CHECK refuses the UPDATE. Delete entries with `_delete_entries`, which removes the
  captures first: the cascade takes their rows but not the thumbnail files. A change to an
  existing table is a named migration through `storage.rebuild` (backup, one transaction,
  counts compared) with the new definition also in the `CREATE TABLE` for new files; try it
  on a copy of the real databases before deploying.
- **Other people's collections are not the collection.** `others.py` / `others_api.py` keep them (and the buy list) in `data/others.db` with ids of their own; no route that changes the collection takes one, and nothing in `others_api.py` calls an inventory. A trade *receives* a snapshot of their card (`trade_receives`), never an entry: confirming adds nothing to the collection. Keep it that way - an `others` id given to an inventory route would change another card.
- **Copies a trade holds stay.** Triggers on `inventory` refuse to delete an entry an open
  trade holds copies of, or to lower it below them (`TRADE_HELD`): new code that removes or
  moves copies needs no check of its own, but must roll back when the statement fails
  (`@_writes`), and anything that commits entry by entry must refuse held entries before it
  starts (as `bulk_update` does). A trade's own code lets go of the entry first
  (`inventory_id = NULL`), then takes the copies.
- **Scanned cards and cameras.** Entries merge across cameras; who scanned what is beside them
  (`inventory_sources`, `inventory_captures.station`; `add_card(source=...)`). Anything that
  shows or moves "a camera's cards" goes through `_station_rows`; anything that moves copies
  between entries must call `_move_sources` (before the quantity and captures change); a new
  table beside the entries belongs in `backups.INVENTORY_TABLES`. A filtered list's `quantity`
  is the camera's copies, not the entry's (`entry_quantity`).
- **New Socket.IO events** need a handler in `server/` (`scan_events.py`, `settings_events.py`
  or `ai_events.py`) and in `static/js/scanner.js`, the new list recorded
  (`venv/bin/python tests/test_app_surface.py --record`), and a line
  in docs/PROGRAM_DOCUMENTATION.md. Messages between server and station are in `remote_scanner.py`
  and `station_client.py` - change both.
- **Stations are open without a token** (`stations.token`), like the web UI, which has no login
  except for one optional lock: the settings password (`server/lock.py`) on the AI keys, restart / quit,
  network access, debug mode and the backups' restore / upload / download / delete / full backup. A new
  route or event of that kind takes `@guarded` / `@guarded_event`; the list is in docs/PROGRAM_DOCUMENTATION.md.
  **Never send full API keys to the browser**: `api_keys.credential_status()` masks them; the UI
  can only replace or remove a key.
- **Where the compose files are.** In `deploy/`, with paths written from there (`../data`), the
  build context `..` and the project name pinned (`name: scanner-server`): the folders, volumes
  and network Docker resolves are the same as when the files lay in the top folder - check
  with `docker compose ... config` before and after touching them (a wrong path there would
  start the server on an empty `deploy/data`). Compose reads `.env` for `${...}` from beside
  the compose file, hence the link `deploy/.env` → `../.env`; deploying with rsync must copy
  links as links (`-l`). The image's build context is the top folder, and the images are laid
  out like the project (`/app/src/card_scanner`, `/app/config.yaml`, `/app/data`): `COPY`
  paths and `.dockerignore` are written from the top folder (`src/ocr/node_modules/` is
  ignored - the image builds its own; `**/__pycache__/` with the `**/`, or only the top
  folder's is kept out). **rsync does not delete**: a file that is moved or removed in the
  repository stays on a machine deployed that way until it is deleted there.
- **Docker images.** light-ocr's native library needs glibc 2.38+ (Debian 13 base images - on
  Debian 12 OCR silently fails to start), and NVIDIA's Vulkan driver needs the X11 / GLVND
  libraries plus `NVIDIA_DRIVER_CAPABILITIES=all`, or OCR falls back to the CPU. After changing
  the server image, check `data/logs/ai.log` for `light-ocr ready (webgpu)`.

**Card data, matching, inventory**

- **Schema**: cards columns are defined once in `database.py:CARD_COLUMNS`; missing columns are
  added on startup (`initialize_database`). Rows are `sqlite3.Row` - access by column name.
  New search-relevant columns may need filling in the migration (see `name_search`).
- **Match confidence**: `search_card_exact` tags results (`card['match']`); only the game's
  `confirmed_matches` (Magic: `CONFIRMED_MATCHES`) may be added without review - check with
  `game.is_confirmed(card)`. Keep new search paths tagged.
- **Games**: app code goes through `games.active()` (identify, find_printings, card_payload,
  inventory_fields, export_formats), never straight to `database` / `CardSearcher`. Inventory
  rows carry `game` and `finish` (a key of `game.finishes`) and are addressed by `id`; the
  inventory schema lives in `inventory.py`, not `database.py`.
- **Three inventories**: `scan_inventory` (`data/scan_inventory.db`: what stations add),
  `inventory` (the collection) and `arena_inventory` (`data/arena_inventory.db`: what the
  user has in MTG Arena). Statistics and a paper deck's "owned" read `inventory`; an Arena
  deck's read `arena_inventory` (`decks_api.collection_of(kind)` - never `inventory`
  directly in deck code); REST routes pick with `inventory_area()` (`?area=scan`,
  `?area=arena`).
- **The digital collection is a copy, replaced whole, never edited.** Only
  `arena_api.arena_import` writes it (`replace_all` and the account in one transaction).
  A route that changes an inventory must be named in `inventory_api.CHANGES_AN_INVENTORY`
  (refused for `?area=arena`), and a request of the collection page that changes one must
  carry `areaQuery()`: the ids of Arena entries are ids of other cards in the collection,
  so a write that forgets its area changes the paper collection. Arena decks an import
  brought (`arena_id`) are replaced by the next import; never give that id to a deck made
  here.
- **Inventory key**: `location` is part of `inventory.KEY_COLUMNS` (and the table's UNIQUE);
  anything that looks an entry up by its key must include it. Changing the key means rebuilding
  the table (`_migrate_add_location` is the pattern: backup, keep ids, check counts).
- **Moves to the collection are crash-safe** (`take_from`, `pending_moves` / `arrived_moves`,
  `finish_interrupted_moves`): two files, two commits - keep the note-first order.
- **Other sites** (`recommendations.py`): only MTGJSON is a published API. Go through `_get`
  (cache, 1 request/s per site), catch shape changes and raise `Unavailable`; never call these
  from scanning code paths. The cache is `data/web_cache.db`: disposable, bounded, in no backup -
  nothing that must be kept goes into it.

**Logs**: on the server `data/logs/app.log` (also every station's scanner lines), `ai.log`,
`database.log`, `scanned_cards.log`, `ocr.log`, `printing_check.jsonl` (the shadow check), `reading.jsonl` (the reading log: `core/reading/record.py`, `scripts/reading_report.py`); `requests.log` only with Debug mode on. A station logs to its console
(`docker compose -f deploy/docker-compose.client.yml logs`) - only there: why a card waits ("Waiting
N s: ..."), focus probes and saved debug frames.
