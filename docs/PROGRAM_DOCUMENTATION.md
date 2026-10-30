# Card Scanner - Technical Documentation

How the scanner works inside. For what it is and how to use it see [README.md](../README.md); for
installing the server, the camera stations and the phone app see [INSTALL.md](INSTALL.md).

The program and this document were written by an AI coding assistant (Claude, through Claude
Code), directed by the project's author, who ran it on real hardware with real cards. The
numbers below - thresholds, timings, counts - come from those runs and from recorded sessions;
each says when it was measured, and "not tested" marks what never was.

## Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Stations](#stations)
4. [Card detection](#card-detection)
5. [Auto-capture](#auto-capture)
6. [Identification (vision AI)](#identification-vision-ai)
7. [Matching the printing](#matching-the-printing)
8. [Foil and finish](#foil-and-finish)
9. [Database](#database)
10. [Focus](#focus)
11. [Collection page and decks](#collection-page-and-decks)
12. [Web interface](#web-interface)
13. [Configuration and files](#configuration-and-files)
14. [Performance](#performance)
15. [Tests](#tests)
16. [Known limitations](#known-limitations)

## Overview

The scanner turns a camera pointed into a box into a card-cataloguing station: cards are dropped
onto a pile, each new card is detected, captured once, identified down to the exact printing
and finish, and added to an inventory. It is split in two:

- **Camera stations** - a small computer with a USB webcam (a PC, a laptop, a Raspberry Pi), or
  a phone - find the card, decide when to capture it, and send one picture per card.
- **One server** reads the pictures (OCR, then a vision AI), matches the printing, and keeps
  everything that lasts: the card data, the scanned cards, the collection, the decks, the
  settings. Its web pages are the only user interface of the computer stations.

Design choices:

- **Classic computer vision for detection.** A card is found by its outline, not by an object
  detection model: fast (milliseconds, fine on a Raspberry Pi), exact corners for a flat
  perspective-corrected crop, and unaffected by foil glare.
- **Detection runs next to the camera.** Stillness and "is this a new card?" are judged frame
  by frame at camera speed, and the lens is moved between frames; over a network both would
  depend on its jitter. A station therefore sends one image per card (and a small preview),
  not a video stream - about 1 Mbit/s, fine on Wi-Fi - and the server does no image work per
  frame, whatever the number of cameras.
- **Reading is shared.** One OCR reader and one AI configuration serve every station, each
  behind its own queue. The AI only reads text: the name, collector number and set code from
  the crop, and the ★/• foil marker from a zoomed corner. Any provider works: Gemini, OpenAI,
  Anthropic, or a local Ollama model.
- **The local Scryfall database decides.** What was read is matched against 110,000+ printings;
  set code + collector number identify a printing exactly, and only confirmed matches are added
  without review.
- **A station keeps nothing.** Its camera settings are saved on the server, and a captured
  image is deleted once the server has it. A station can be replaced or reinstalled without
  losing anything.

## Architecture

### The programs

| Program | Runs on | What it does |
|---|---|---|
| `app.py` - the server (the package `server/`) | One machine; a Docker image (`deploy/Dockerfile` target `server`) | Web pages, reading (OCR + AI), matching, card data, scanned cards, collection, decks, backups; holds every station's settings |
| `station.py` - a camera station (the package `card_scanner/station/`) | The machine a USB webcam is plugged into; a Docker image (target `client`, x86-64 and ARM64) | Camera, outline detection, stillness, new-card rules, focus; uploads each capture; shows nothing itself |
| The Android app ([mtg-scanner-android](https://github.com/SilentKernel81/mtg-scanner-android)) in client mode | A phone over the box | The same job with the phone's camera (a Kotlin port of the detection); uploads each capture. It can also work on its own, without a server |

The server opens no camera itself. Until 2026-10-12 it could (`camera.type` other than
`remote`, as the single-machine scanner this grew from): that path was removed - every
machine in use already had its camera at a station, and it was the one part of start-up that
the tests of the server never ran. A machine that is server and camera in one runs both
programs (`scripts/start.sh`, or the two services of `scripts/deploy.sh --service`).
Everything below about detection, auto-capture and focus is `CardScanner`, which runs inside
`station_client.py`.

### Modules

All the code is one package, `src/card_scanner/`, sorted by which program a module belongs
to: `station/` (a camera station: `station_client.py`, `station_setup.py`, `station_login.py`,
`scanner.py`, `object_detector.py`), `core/` (reading cards, card data, the collection - no
web app, no camera), `server/` (the web app, with its pages in `server/templates/` and
`server/static/` - written `templates/...` and `static/...` in this document), `games/`, and
at the package's top what both programs use (`paths.py`, `config.py`, `config_loader.py`,
`settings.py`). Modules are named by their file below (`inventory.py` is
`src/card_scanner/core/inventory.py`). The OCR reader (Node.js) is beside the package, in
`src/ocr/`. The top folder holds the two launchers - `app.py` starts the server, `station.py`
a station - `config.yaml` and the data (`data/`, `scanned_cards/`, `station_captures/`);
`paths.py` says where the folders are (`TOP`: what ships; `USER_DIR`: the person's data,
`.env` and own `config.yaml` - the same folder in a checkout, `~/.mtg-scanner` when
packaged, `MTG_SCANNER_HOME`; `CODE`), and nothing else builds a path
from where its own file lies. One server runs per data folder (`data/app.lock`). Which part may import which is a test (`tests/test_layout.py`):
a station imports nothing of `core/` or `server/`, and `core/` nothing of `server/` or
`station/`.

| Module | Runs in | Responsibility |
|---|---|---|
| `app.py`, `server/` | server | `app.py` only starts it; `server/` is the Flask + Socket.IO app, a module per area (listed in `server/__init__.py`): pages, routes, events; one desk per station (`Desk`, `desk()`); station captures (`station_capture`, `submit_capture`); what happens to a read card (`route_identified`) |
| `identification.py` | server | Reading a card, for every camera: light-ocr, the vision AI, the queue in front of each (`Identification`) |
| `card_ocr.py`, `ocr/server.mjs` | server | light-ocr reader: the Node.js process that runs the OCR models (kept running, one request per line), and the parsers that pick name, number, set code and foil marker from the text lines |
| `reading/evidence.py`, `reading/decide.py` | server | The decision about a printing as a pure function of plain data (`decide_printing`, rule A2; `decide_finish`; the guards around it, `accept_printing` and `confirm_by_ocr`, since 2026-10-21): what `printing_check.py`'s lookup used to do inline, now with test files another program can pass too (see *Printing check*) |
| `image_index.py`, `printing_check.py` | server | The printing check, shadow mode (see *Printing check*): a 96-byte fingerprint of every printing's picture (`hash_card`, `ImageIndex`, the builder `build`) and the check that a capture looks like the printing the server resolved (`PrintingCheck`) |
| `foil_marker.py`, `foil_net.onnx` | server | The foil marker (★ / •) read from the set line by a small network where OCR left it unread (`FoilMarker`, `load`); the network is the file beside the module, run with OpenCV's dnn (310 KB) |
| `card_identifier.py` | server | Vision AI providers (`_ask_*`), response parsing, foil marker check, model warm-up |
| `prompts.py` | server | Built-in prompts and the ones edited in Settings (`data/prompts.json`), per model |
| `stations.py` | server | The stations (`data/stations.json`): name, location, counters, and each one's settings (`StationSettings`) |
| `remote_scanner.py` | server | `RemoteScanner`: what the server holds in place of a station's `CardScanner`; `CameraHub`: the `/station` Socket.IO namespace the clients connect to |
| `pending.py` | server | Captures in the queues, on disk until settled, and what became of them (`data/pending_captures.db`); the `applied_captures` table the inventory and review queue note applied captures in |
| `review.py` | server | The review queue (`review_queue` table, `data/review/`), per station |
| `database.py` | server | Scryfall download and import, schema / migrations, searches, printing lookup, match confidence |
| `games/` | server | Card games: `base.Game` (the interface the app uses), `mtg.Magic` (Scryfall data, matching, finishes, exports); `games.active()` is the game being scanned |
| `card_search.py` | server | Magic search helpers combining name, number, set and treatment |
| `others.py` | server | Other people's collections imported to trade with or buy from (`Others`), and the buy list - their own file `data/others.db`; see [Other people's collections](#other-peoples-collections) |
| `trades.py` | server | Cards of the collection set aside for a trade until it is confirmed (`Trades`); the tables and the triggers that keep the copies are in `inventory.py` |
| `inventory.py` | server | Inventory table for every game: schema + migration, add (merging duplicates), undo, edit / split, bulk edits, locations and tags, which station scanned what, move to the collection, CSV import / export |
| `decks.py`, `games/mtg_decks.py` | server | Decks (`decks`, `deck_cards`): lists of card names; formats, deck checks, text decklists |
| `recommendations.py` | server | Deck ideas from EDHREC, MTGJSON, Archidekt and Moxfield, cached in `data/web_cache.db` |
| `backups.py` | server | Backups of the collection, the scanned cards and the decks; full backups of every database file at one moment |
| `storage.py` | server | What every database file has in common: connection setup, named migrations, table rebuilds |
| `settings.py` | server | Choices made in the web interface, in `data/settings.json` |
| `cleanup.py`, `setup_database.py` | server | Old capture images (on startup and as a CLI); downloading the card database |
| `station_client.py` | station | `Station`: connects to the server, runs a `CardScanner`, reports status and preview, executes the server's commands, uploads captures |
| `scanner.py` | station | `CardScanner`: camera (USB via OpenCV / V4L2, or Pi camera), capture thread, detection state, stillness, auto-capture, fixed area, focus |
| `object_detector.py` | station (or server) | Outline detection (`find_card_outline`), perspective warp (`warp_card`) |
| `config.py`, `config_loader.py` | both | Settings from `config.yaml` and the environment |
| `templates/`, `static/` | server | The pages: `stations.html` (the cameras), `scanner.html` (one camera's page), `collection.html`; shared `_topbar.html`, `_dialogs.html`, `_icons.html`, `common.js` |
| `tests/` | - | `test_ownership.py`: which station scanned what, and backups (see [Tests](#tests)) |

A station must not import the server's modules: its image contains only `station_client.py`,
`scanner.py`, `object_detector.py`, `settings.py`, `config.py`, `config_loader.py` and
`config.yaml`.

### Threads

Server:

| Thread | What it does |
|---|---|
| Main | Flask + Socket.IO (threading mode): one thread per request - pages, REST, Socket.IO events of the pages and of the stations, the MJPEG streams, capture uploads (several at once) |
| OCR worker (`Identification._ocr_worker`) | Reads queued captures with light-ocr, one at a time; passes on what it can't settle |
| AI workers (`Identification._ai_worker`, `vision_ai.workers`, default 3) | Ask the vision AI about the cards OCR passed on, several at once |
| Identified worker (`Identification._done_worker`) | Hands each read card back - lookup, add or review queue (`route_identified`) - one at a time |
| Background tasks | Card database update / rebuild, startup image cleanup, model warm-up, the update schedule (`run_update_schedule`: the card data update check 10 s after startup, then daily; the automatic card data download and picture index retry every 10 minutes from 5 minutes after start - off unless chosen), "What can I build?" searches |

Station (`station_client.py`):

| Thread | What it does |
|---|---|
| Main (`Station.report_loop`) | Status every 0.2 s; the preview while a page is watched |
| Capture (`CardScanner._capture_frames`) | Reads frames, detects the card, tracks stillness, draws the overlay, triggers auto-captures |
| Auto-capture callback (`Station.auto_captured`) | One short-lived thread per capture: crops and saves the card, waits for a focus probe, sends the beep, queues the upload |
| Uploads (`Station.upload_loop`) | Sends captures in order; retries until the server has each |
| Socket.IO client | The server's commands (`on_command`, `on_set`); focus sweeps and probes run in their own threads |

Frames and detection state are shared under `scanner.frame_lock`; the card database, each
inventory, the review queue, the stations and the pending captures each have their own lock
around a SQLite connection or file. On the server, anything that concerns one station's card
runs "at its desk" (`in_desk`), which decides where its events and log lines go - see
[A page per camera](#a-page-per-camera).

**No camera.** A station starts without one: `CardScanner._open_camera` logs one warning and
sets `camera_error`, and the capture thread tries again every `CAMERA_RETRY_SECONDS` (3 s),
silently, until it opens - no restart. On Linux a missing `/dev/videoN` is seen before OpenCV is
asked (which would print its own errors at each try); a device that opens but sends no first
frame counts as no camera too. While running, `CAMERA_LOST_AFTER` (20, ~2 s) failed reads in a
row (`_read_failed`: unplugged) close the camera, clear the frame and go back to waiting - one
warning instead of an error per frame. `camera_error` is part of the station's status and of
`/api/detection_status`: the station's page covers the video with the reason and disables the
capture button. **No station** is the same to the page: `RemoteScanner.camera_error` then says
that no camera station is connected.

### Flow of a card

```
 CAMERA STATION                                   SERVER
 camera frame ─> outline ─> settled? ─> new card?
                                            │ capture: flat, perspective-corrected card image
                                            │ (the beep: drop the next card)
                                            └── upload ──────────> saved, on record until settled
                                                                          │
                                  OCR queue: light-ocr reads name, collector number, set code, ★/•
                                     confirmed printing? done (the AI only for a missed ★/•)
                                                                          │ otherwise
                                  AI queue: vision AI reads name, number, set code (+ ★/• corner)
                                                                          │
                                  card data: set + number (checked against the name)
                                             → name + number → name → fuzzy name
                                                                          │
                                  confirmed printing ──> scanned cards (with Undo), the station's page is told
                                  uncertain ───────────> the station's review queue; scanning goes on
                                                                          │
                                  "Add to collection" ──> the collection (all cameras, or one camera's)
```

With "Add cards automatically" off (a computer station only), a capture is read at once and
shown on the station's page, and the station holds its next capture until **Add** or **Skip**.

## Stations

A station is a camera somewhere: it finds and captures the card itself and sends the picture
to the server, which does everything after that. There are two kinds, and they use the same
upload:

| | Camera station (`station_client.py`) | Capture-only station (the Android app, or any program) |
|---|---|---|
| Sends captures | `POST /api/stations/<id>/captures` | The same |
| Stays connected | Yes: Socket.IO namespace `/station` - status, live view, commands | No |
| Its page on the server | Live view, capture button, auto scanning, focus, fixed area, rotation | The same page without the camera panel |
| User interface | The server's page | Its own (the phone's screen) |

A station is known by an **id** it chooses and keeps (1-40 letters, digits, `-`, `_`). It
appears the first time it connects or sends a card (`stations.py`, `data/stations.json`: name,
location, capture count, last seen, whether it has a camera the server can show, its settings).

### Sending a capture

`POST /api/stations/<id>/captures` (multipart; `server/stations_api.py: station_capture`):

| Field | |
|---|---|
| `image` | The card as the station cut it out (JPEG as it is, or PNG) |
| `foil_image` | Optional: the perspective-corrected card, for the ★/• foil check by the AI - when `image` is something else (a fixed area) |
| `foil_is_image` | Optional, `1`: `image` is the perspective-corrected card itself, so no `foil_image` is needed |
| `name` | Optional: what the station calls itself (used until it is renamed on the server) |
| `wait` | Optional: seconds to wait for the outcome (default 30, at most 120; 0 answers at once) |
| `capture_id` | Optional: the station's own id for this capture (up to 64 characters). Sent again - no answer came the first time - it is the same capture, answered with its outcome, not a second card |
| `mode` | `station_client.py` only: `review` = read it now and show it on the station's page instead of adding it (a manual capture, or auto scanning that waits for Add / Skip) |

The image is saved in `scanned_cards/` as `<id>_<n>_<time>.jpg` and goes through the two
queues (see [Identification](#identification-vision-ai)), always as when adding automatically:
a confirmed printing is added to the scanned cards, anything else goes to the station's review
queue. The answer:

```
{"capture": 12, "status": "added", "seconds": 0.31, "sync_key": "5f0c...",
 "card": {"name": ..., "set": ..., "number": ..., "finish": ..., "quantity": 1},
 "read": {"name": ..., "number": ..., "set": ..., "foil": ..., "reader": "light-ocr"}}
{"capture": 13, "status": "review", "reason": "printing not confirmed" | "not found" | "not read" | "game switched", ...}
```

or `202` with `"status": "pending"` when the card isn't settled within `wait` (it still is,
afterwards). Errors: `400` (bad id, no readable picture), `401` (token), `413` (over 30 MB).
Every settled answer - this one, the same capture sent again, and the outcome asked for later,
also after a restart - has `capture` (the station's capture number) and `sync_key` (the
capture's identity on the server; see [Capture synchronization](#capture-synchronization)).

| Also | |
|---|---|
| `GET /api/stations/<id>/captures/<n>` | The outcome of a capture that was still pending (`202` while it still is). Outcomes of the last 500 captures are kept in memory: `404` after a restart |
| `GET /api/stations/<id>/captures/<n>/sync` | Where that capture's copy is now: `{"success": true, "state": "pending" \| "scanned" \| "review" \| "resolved"}` (below) |
| `DELETE /api/stations/<id>/captures/<n>/sync` | Remove that capture's copy from the scanned cards or the review queue - never from the collection: `"state": "removed"`, or `"pending"` / `"resolved"` when there was nothing to remove |
| `POST /api/stations/<id>/undo` | Take back the station's last automatic add |
| `GET /api/stations` | The stations, with whether each is connected, sees a card, is scanning, and how many cards it has in review |
| `PUT /api/stations/<id>` | Rename it (`name`) or set where its cards are put (`location`) |
| `DELETE /api/stations/<id>` | Forget it - after clearing its scanned cards and review items (`clear_camera`, every game), so nothing of it is left where no page shows it. Cards already in the collection stay |

#### Capture synchronization

A phone keeps a row for every card it scanned, and the two sides are kept in step through
the capture: removing a row on the phone removes that card on the server, and a card that
left the scanned cards (moved into the collection, or removed on a page) disappears from the
phone. The Android app asks `GET .../sync` about every 10 s for each row that has a
`sync_key`, and sends `DELETE .../sync` when a row is removed (`station_capture_sync`).

| `state` | Meaning |
|---|---|
| `pending` | Still being read - or failed and kept to be read again at the next start. A `DELETE` removes nothing and says `pending` too: the phone asks again |
| `scanned` | Its copy is in the scanned cards |
| `review` | It waits in the review queue |
| `resolved` | Known, and in neither place: moved into the collection, or removed, skipped or cleared on the server. Also the answer to a `DELETE` repeated after `removed` |
| `removed` | This `DELETE` took it out |

- **The state is the one of this moment**, not what the capture first became: queued for review
  and added from there it is `scanned`; once in the collection, `resolved`.
- **Exactly this copy.** Each photographed copy in the scanned cards is a row of
  `inventory_captures`, which now carries the capture's uid (`capture_key`; the uid is the one
  from `pending.py` that already makes a capture count once, and it is the `sync_key`). The
  row stays with its copy when an entry is split, merged or given another printing
  (`_move_captures`), so `InventoryManager.captured_copy` finds the entry the copy is in now
  and removes that photo, one copy, and the station's claim on it - of three identical cards
  scanned in a row, the one named. A review item carries the same uid (`review_queue.capture_key`),
  and the card added from it takes it along (`handle_add_inventory`).
- **The page's Add and a station's removal take turns** (`maintenance_barrier`, held by
  `handle_add_inventory` and by the route). Without it an Add could read which review item is
  open, the station's `DELETE` then remove that item and answer `removed`, and the Add still
  put the card into the scanned cards. Everything the Add reads about the page is read under
  the barrier: after a removal there is no card on the page to add, and an item that left the
  queue some other way is refused ("no longer in the review queue") instead of added again.
- **A reviewed capture stays its station's card**, whichever page works through the review:
  the page without a station lists every station's items, and a card added there is counted
  as the capture's station's (`source`), not as nobody's - or its phone could never follow it.
- **Send to review** (the circular-arrow button on an entry of the scanned cards and of the collection;
  `POST /api/inventory/<id>/to_review`, `?area=`): one copy - the one behind the entry's newest
  capture - goes back to the review queue when the card or printing it was added as is wrong. The
  item holds a copy of the capture's large picture (the thumbnail when none) with the entry's
  printing as the suggestion (`match` "sent back": never confirmed), under the capture's station
  (nobody's when the registry no longer knows it). The review item is written first, then the
  copy leaves (`release_for_review`: photo row, station count, quantity - as a station's
  removal does); if that fails (an open trade holds the copies) the item is taken back, so a
  failure leaves nothing queued and nothing lost. The item carries **no `capture_key`**: the
  capture's uid is used up in `applied_captures` (review and scanned cards would refuse it as
  "applied before"), so the key is noted in `unfollowed_captures` and a phone asking about it is
  told "cannot be followed", never "gone". An entry with no capture (typed in, imported) has
  nothing to review by and is refused. What is added from the review always goes into the
  **scanned cards**: a collection card sent back comes through "Add to collection" again and
  loses its location, tags and condition. Not offered for the digital (Arena) collection.
  The page names the copy it showed (`capture`, its picture); only that one is sent, so a request
  repeated after its answer was lost gets 409 "not here any more" instead of taking another copy.
  Clearing a camera, skipping a review item and "Add to collection" take `maintenance_barrier` too,
  so none can run between the item being queued and the copy leaving. **A stop in between is
  settled at the next start** (two files, two commits): the item is written with `transfer`
  ("scan:" or "collection:" and the copy's picture file) and stays out of the queue (`review._of`)
  until the copy has left and the route confirms it (`confirm_transfer`). `finish_interrupted_sends`
  (inventory_api.py, called by `startup`) looks at each pending item: its picture still in that
  inventory (`has_picture`) means the copy never left - the item is dropped; gone means it left -
  the item is confirmed. So the card ends in exactly one place. The pending item is made durable
  before the copy may leave (a power cut, not only a program stop): its picture is fsynced with its
  folder and its commit alone is `synchronous=FULL` (the databases are NORMAL otherwise) - not
  tried with an actual power cut. The inventory's release commits `FULL` too, before its pictures
  are deleted; and if a power cut still took that commit back (the row is there, its picture is
  gone), the next start finishes the release (`release_by_picture`) and keeps the item - it holds
  the only picture left.
  Tested (storage and route): `tests/test_send_to_review.py`, `tests/test_capture_sync.py`;
  the browser buttons were not tried in a browser.
- **The collection is out of reach.** `take_from` copies the photos without the key and deletes
  the rows in the scanned cards: afterwards there is no row to find, in either file. A `DELETE`
  then answers `resolved` and changes nothing.
- **Unknown is never `resolved`.** A capture the server has no outcome for - a number the
  station never had, or one settled more than 30 days ago (`pending.KEEP_DAYS`) - is `404`. A
  capture it knows but cannot follow is `409` with a message: settled before this was added
  (no `sync_key`), failed for good, shown on the camera's page instead of added (`mode:
  review`), added without a photo (`unfollowed_captures`: the thumbnail could not be made), or
  a copy that is another station's. The phone keeps its row in both cases.
- **Removed stays removed.** The uid stays in `applied_captures`: the capture sent or read
  again after its copy went adds nothing.
- **Numbers can come round again.** The capture is named by station and number, and a station
  forgotten on the server (`DELETE /api/stations/<id>`) counts from 1 again: a row the phone
  kept from before then names a new capture. `?sync_key=<key>` on either request makes it
  exact - a number that belongs to another capture now is refused (`409`). The Android app
  sends it. A row whose capture is answered `404` / `409` can never be kept in step: the app
  then offers to take it off the phone only, on a second Remove.
- **Pages**: a removal from the scanned cards sends `inventory_updated` (`cleared: true`) to every
  page, which count and list again; one from the review queue sends `review_queue_update` to the
  station's page, and closes the item there if it was the one open (`review_item` with
  `id: null`) - or its Add would still add the card.
- **Migration**: two columns that may be empty (`inventory_captures.capture_key`,
  `review_queue.capture_key`), a unique index on each and one small table
  (`unfollowed_captures`) are added in place at the first start; no table is rebuilt. Tried on
  copies of the real databases (5,407 cards in 2,151 entries, 4,107 photos, 15 decks, 147
  settled outcomes): every row of every table was the same before and after. What was scanned
  before has no `sync_key` and stays as it is: the phone is answered `409` for it.
- Tested (`tests/test_capture_sync.py`, 39 cases on temporary databases, the routes through
  Flask's test client and the page's Add through Socket.IO's): a removal arriving in the
  middle of an Add (it waits, then removes the card), a review worked through on the page of
  every station, duplicates, repeated removal, two stations, pending and failed
  captures, restarts, review removal and hand-off, splits, merges, printing changes, the move
  into the collection with a location (collection rows compared before and after a `DELETE`),
  forgotten outcomes, a number used again. Also run once on a local server with test data
  (2026-10-12), with real uploads: two pictures of the same card and one nothing can be read
  from; the answers carried `capture` and `sync_key` (also for the capture sent again, before
  and after a restart); one of the two identical cards removed, a second `DELETE` `resolved`;
  the review item added through the page's events (`review_open`, `search_card`,
  `select_printing`, `add_to_inventory`) read `scanned` and was removed; the last card moved
  into the collection with a location read `resolved`, and a `DELETE` left the collection's
  count unchanged. **Not tried**: against the Android app, or on the real server.

- **Token**: with `stations.token` in `config.yaml` (or `SCANNER_STATION_TOKEN`) set, uploads,
  the outcome, the capture synchronization, undo and the `/station` connection need it (header `X-Station-Token`, or `token`
  in the connection's `auth`). Without it anyone on the network can send cards - like the web
  interface itself, which has no login.
- **Order**: a card the AI had to read is added after cards dropped later that OCR confirmed.
  The entry gets the time its capture arrived (`add_card(when=...)`), so the scanned list stays
  in dropping order.
- **Location**: a station's cards get its own location (the page's *Scan into location*).
- **Undo** is kept per station (`InventoryManager.last_added[source]`): one station's Undo never
  takes back another's card.
- **The Android app** in client mode (`server/ScannerServer.kt` there): uploads each capture
  with a `capture_id`, shows the answer, asks again while it is pending and uses the undo
  endpoint. Change the answer's fields and its `ServerOutcome.parse` (and `ServerOutcomeTest`)
  must follow.

**Captures survive a restart.** Every capture that goes into the queues is on record in
`data/pending_captures.db` (`pending.py`, written by `submit_capture`) from the moment it is
accepted until it is added or in the review queue; its image is in `scanned_cards/` (a
separate foil image as `<name>_foil.jpg`, deleted afterwards). At startup `resume_pending`
queues what is still on record. Measured 2026-10-08: container killed (`docker kill`) with 110
captures on record; after the restart all were added, 120 cards for 119 accepted uploads - the
extra card was one added just before the kill and not yet taken off the record (then added
again), which is what the next paragraph is about.

**A capture counts once** (since 2026-10-09, after plans/DATABASE_REVIEW.md):
- Each capture on record has a `uid`. The add (`InventoryManager.add_card(capture_key=)`) or
  the review item (`ReviewQueue.add(capture_key=)`) notes it in its own commit, in a table
  `applied_captures` of the database it writes to; a capture read again after a crash between
  that commit and its removal from the record finds its uid there and changes nothing.
  `submit_capture` hands the uid down through `settling` (thread-local) / `capture_key()`.
- What became of an uploaded capture is written to `settled_captures` (in
  `pending_captures.db`) in the commit that takes it off the record (`PendingCaptures.settle`).
  A station that sends the same `capture_id` again - also after a restart, when
  `seen_captures` (this run's memory) is empty - gets that answer; asking and claiming a
  `capture_id` is one step (`capture_accept_lock`), so two uploads of it at once are one capture.
- A capture whose result could not be applied stays on record and is tried at the next starts,
  three times in all (`PendingCaptures.fail`, `MAX_ATTEMPTS`); then it is settled as an error.
- A sender's `capture_id` can be on record once (a unique index), whatever asks first.
- The station deletes a picture only when the server's answer names the capture
  (`station_client.upload_verdict`: 200 / 202 with `capture`); 400 / 413 from the server mean
  it will never be taken (kept, not sent again); everything else - a wrong token, a proxy's
  page - is tried again. It used to delete on any answer below 500.
- Applied uids and outcomes are kept 30 days (`KEEP_DAYS`). `applied_captures` is not part of a
  backup and stays when cards move to the collection or a backup is restored.

Verified 2026-10-09 on an isolated copy of the server (copies of the databases, another port):
one upload sent twice, another sent twice at the same moment, the process killed (`kill -9`),
the first capture put back on the record as a crash would leave it, restart - 2 cards for 2
captures, and both repeats answered from the record. **Not tested**: a kill at exactly the
moment between the two commits (the state was built by hand); the station's new rule against
a real server (its decisions are unit-tested); and the Android app, which still deletes its
picture on any answer below 500 (its own repository - `ServerOutcome.parse` there).

Measured 2026-10-08 (server in Docker, OCR on an RTX 4070 Ti SUPER, a laptop on Wi-Fi sending
recorded captures): one station at a card every 2.5 s - 30 of 30 added, 29 by OCR in 0.34 s
(median, upload included) and 1 by the AI in 1.2 s; four stations at a card every 0.5 s each
(7.8 cards/s) - 100 of 100 added, OCR median 0.48 s, worst 1.0 s.

### A camera station

`station_client.py` runs the real `CardScanner` next to the camera - capture thread, outline
detection, stillness, new-card rules, focus sweeps and probes, all at camera speed. On the
server holds a `RemoteScanner` (`remote_scanner.py`) in its place, one per station
(`CameraHub.scanner(id)`): the same attributes and methods, so the page's handlers are the same
whether the camera is local or at a station.

The client opens the connection (Socket.IO namespace `/station`, `auth`: id, name, token) and
keeps it; nothing has to be configured on the server to add a camera.

| Client → server | |
|---|---|
| `hello` | Answered with the camera's saved settings (`CAMERA_SETTINGS`: focus position, rotation, focus check interval, fixed area, debug trace) and the attributes the server decides (`DECIDED`: add automatically, stability frames, capture delay). The client creates its `CardScanner` with them - which is when the camera opens; after a reconnect only the decided attributes are applied again |
| `status` (every 0.2 s) | The scanner's state and `get_detection_status()`; the answer says whether the preview is being watched |
| `preview` | The annotated live view as JPEG (`get_stream_jpeg`), at most ~12 a second and only while a page shows `/video_feed` (measured: 12 fps, 66-81 KB a frame over Wi-Fi). A card the station finds by its outline has no border: it is tinted, see-through, orange while it settles, green when ready, blue while held, and a capture washes it a stronger green that fades down to the tint in 0.6 s (`_mark_auto_card` / `_wash_card`, drawn into the picture by the station - the page has only the beep). The fixed area keeps its rectangle (the area that was drawn, green / orange / blue by state) and gets the same wash at a capture. The app does the same on its own overlay. On the page the camera's frame has the shape of the picture it shows (`updateVideoFrame` sets `--picture-aspect` from the stream's size every second; `.video-container` is as wide as the panel but at most `--frame-max-height`, 62% of the window's height or 620 px): a camera cropped to the box gives a smaller, upright frame - the same for every camera cropped alike, and with no bars - and an uncropped webcam fills the panel as a 16:9 one. (Until 2026-10-15 a portrait picture switched the frame to a 9:16 box, which left bars above and below a 4:5 picture.) |
| `setting` | A camera setting the scanner changed (a focus sweep's result, ...): saved on the server |
| `log`, `captured` | The scanner's log lines, shown on the station's page only (lines no station owns - backups, card data, the collection - go to pages that show no station: room `general`); `capture_received` (`url`, `number`: a camera-less station's page, a phone, shows the picture it sent last where a camera's live view would be; `/api/last_capture` gives the current one on load); the capture beep (`auto_capture_triggered` to its pages) |

| Server → client | |
|---|---|
| `command` | A `CardScanner` method (`METHODS`: rotation, fixed area, focus, detection, and `capture` for the page's Capture button), waited for (6 s); the answer carries the result or the error text (raised as `ValueError` on the server) and the state after it |
| `set` | Attributes: `card_under_review`, `auto_capture_enabled`, and the decided ones when they change |

What the server reads on its scanner comes from three places (`remote_scanner.py`): `DECIDED`
attributes are the server's and are sent to the client; `SENT` ones are set by the server now
and then but otherwise the client's own (`auto_capture_enabled`, `card_under_review`);
`REPORTED` ones only come from the client's status. With no client connected the camera
settings are read from the saved values, so the page still shows them.

- **Its settings live on the server.** The client's `CardScanner` gets a `ServerSettings`
  object (get / set) filled by `hello`; every change it makes is sent back (`setting`).
  `StationSettings` keeps them per station in `stations.json`; a value a station doesn't have
  yet is read from `settings.json` (what the single camera used before stations).
- **Captures** go out through a queue (`Station.upload_loop`): in order, each with a
  `capture_id`, retried until the server has it, then the local file is deleted. `mode: auto`
  is added or queued for review; `mode: review` is read at once and shown on the page, and the
  client holds its next auto-capture until the page says Add or Skip (`card_under_review`).
  **A capture the server answers oddly 20 times** (an error page, a 5xx for that picture, a wrong
  token - anything but "received" or "refused"; no answer at all does not count) is **parked**
  (`Station.park`, since 2026-10-16): it joins the held captures with its picture and note on disk, the
  setup page shows it ("the server kept answering with something other than ...") and offers
  "Send them to this server", the next start tries it again, and the captures behind it go on instead
  of waiting for ever. `tests/test_station_uploads.py`.
- **The server or the network goes away**: the station keeps scanning and the captures wait;
  the client reconnects by itself (~5 s after a server restart). Its own state decides
  `auto_capture_enabled`: a connection that drops and comes back goes on scanning; a client
  that restarts has it off, and its pages are told (`auto_capture_toggled`).
- **The same id connecting again** replaces its earlier connection.
- **Its setup page is linked from the server**: a station tells its setup page's port when it
  connects (`auth.setup_port`), the server keeps it with the address it connected from
  (`CameraHub.setup_page`, `setup` in `GET /api/stations`) and the scanner page's Stations list
  is not on the scanner page any more (it was under the camera's picture until 2026-10-16): the
  **Settings** page's Cameras category has a **Camera setup** button for the chosen camera
  (`settings.js`: `stationSetupUrl`) - a station on this computer connects from a loopback address, and
  the link then uses the host the page was opened on; no button while the station has not told a setup port.
  Tried only through the page's code, not in a browser.
- **Which camera**: `camera.usb_index` in the station's `config.yaml` (`auto`, the default: the
  first USB camera that is not a laptop's own - `integrated`, `built-in`, `facetime` or `IR` in
  its name - else the first one, read from /sys, `config.auto_camera_index`), or
  `SCANNER_CAMERA_INDEX` - a number, or a `/dev/v4l/by-id/...` path, which stays the same
  camera when the numbers change (`config.configured_camera`) - or chosen on the station's
  setup page. The path is turned into its `/dev/videoN` at every attempt to open the camera
  (`camera_index_or_none`, `scanner._open_camera`), not once at the start: while the camera
  is unplugged the path does not exist, which used to stop the station from starting at all
  (in Docker it restarted without end - found on the Pi 5 with its webcam removed,
  2026-10-11). Now the station starts, connects, says "No camera" and finds the camera when
  it is plugged in again, also under another number. Tried on that Pi 5 without its camera;
  plugging the camera back in has not been tried.

#### The station's setup page

`station_setup.py` serves one page on the station itself (port 8080, `SCANNER_SETUP_PORT`,
`--setup-port 0` for none), with Python's built-in web server - a station has no Flask. It
holds only what a station must know *before* it can reach the server; everything about
scanning stays on the camera's page on the server.

- **The camera list follows the cameras** (2026-10-19). The page re-reads the station's state every
  2 s, and rebuilds the dropdown whenever the cameras found change - a webcam plugged in
  after the page was opened shows up without a reload - keeping the camera the person has
  chosen (saved or not) and listing a saved camera that is gone as "not found right now". Until
  then the list was filled once, at the first load. A camera named by `SCANNER_CAMERA_INDEX` in
  the station's environment (`.env`) is *fixed* and wins over the dropdown: to choose from the
  page, take the line out of `.env`. Tried in headless Chromium with a camera list that changed
  while the page was open; not with a real unplugging.

| On the page | Saved as (`data/station.json`) |
|---|---|
| Server address, station token. *Test connection* asks the address for `/api/stations` (only a scanner server answers that) and, if the server wants a token, for this station's capture 0 - a request that needs the token and changes nothing: 401 means the token is wrong | `server`, `token` |
| Name, id | `name`, `id` |
| Camera: *automatic*, a USB camera (listed from `/sys/class/video4linux`, saved by its `/dev/v4l/by-id/` name where it has one) or a Raspberry Pi camera (listed by `picamera2`) | `camera`, `camera_index` |
| A crop, dragged on a picture of the whole camera image (any camera, since 2026-10-15). A Pi camera reads out just that part of its sensor; a USB camera sends its whole picture and the station cuts the crop from every frame (`CardScanner._crop_view`: a slice of the decoded picture, before the rotation, no scaling - the pixels are the camera's own; the live frames are cut at half size, the captures at full size). The picture the page draws on is the camera's whole one (`get_whole_picture`), and a fixed area has to be drawn again after the crop changes | `crop` |
| Status: connected, the camera and its pictures a second, captures waiting to be sent, temperature | - |

- **Who wins** (`resolve`): the command line, then the environment (`SCANNER_SERVER`, ...),
  then the saved file, then the default. A value from the first two is shown on the page as
  fixed and is not saved - a station set up with `.env` behaves as before the page existed.
- **Setup mode**: without a server address from any of them, `station_client.py` serves only
  the page and waits; the camera is not opened.
- **Saving** checks the form (`checked`), writes the file (to a temporary file, then renamed:
  whole or not at all; mode 600, it can hold the token) and restarts the station: the page's
  thread raises a flag, the main thread ends `Station.run()` - which releases the camera - and
  replaces the program by a new copy of itself (`os.execv`), so a container keeps running.
  Captures still waiting to be sent are not lost by it: see *Captures that are not on the
  server yet* below. One that is on its way gets up to 10 s to arrive first.
- **Captures that are not on the server yet** (`station_client.py`: `write_note`,
  `load_pending`, `send_until_settled`): the upload queue is in memory, so every queued
  capture also has a note beside its picture, `station_captures/<image>.upload.json` - its
  `capture_id`, mode, foil picture, and where it was going (server address, station id).
  A new start queues the notes it finds, oldest first, under the same `capture_id`: a
  capture that may or may not have arrived before the program ended is sent again and is
  still one card (the server counts an id once). The note goes when the server has the
  capture, or has refused it for good (the picture is then kept, as before). This holds for
  a restart from the setup page, a stopped container and a power cut alike; in Docker the
  folder is the volume `station-captures`, so it also outlives a new image.
  - *Taken for another server, or under another station id* (the setup page changed one
    while captures waited): they are **held** - kept, not sent. The old server may have moved
    to a new address, or the station may have been pointed at another collection; the
    program cannot know which. The setup page's status shows them with *Send them to this
    server* and *Delete them* (asked twice).
  - The token is not in the note: a capture is sent with the token the station has now, so
    correcting a wrong token on the setup page lets the waiting captures through.
  - Until this was added (2026-10-11, found by a Codex review of the setup page), a
    station's unsent captures were only sent by the run that took them, and the setup
    page's restart made that a common case.
  - *A folder of its own.* The waiting captures are in `station_captures/`
    (`Config.STATION_CAPTURES_DIR`), not in `scanned_cards/`, where the server keeps the
    pictures it received and deletes those older than `cleanup.days`. On a machine that
    runs both programs from one checkout the two folders were the same until 2026-10-12, and
    a capture that waited longer than the server keeps pictures would have been deleted
    before it was ever sent - the station then found no picture and dropped its note. What
    an earlier version left in `scanned_cards/` is moved over at the next start
    (`adopt_old_folder`: every note with its pictures; the server writes no notes, so
    nothing of its own is touched). In Docker the volume `station-captures` is mounted at
    the new folder and carries over what was waiting. Found by a Codex review of the
    one-machine setup; `tests/test_station_uploads.py` runs the server's clean-up over a
    waiting capture a year old.
  - *Stopping.* The station ends in an orderly way (the camera released) on SIGINT and
    SIGTERM, and takes both back explicitly at its start: a shell that starts a program in
    the background makes it ignore SIGINT, and Python then never raises `KeyboardInterrupt`.
    With a server address the Socket.IO library happened to re-arm the signal; in setup mode
    nothing did, and the station could only be killed (reproduced on the version before:
    still running 10 s after `kill -INT`). `scripts/start.sh` also gives the station 10 s
    and then kills it, so the script itself cannot hang. Tried: started in the background,
    both modes, both signals - stopped each time; the start script with Ctrl+C in a
    terminal, and with the server killed - the station followed within a second.
- **The camera in Config** (`apply_camera`): the saved camera and crop are put into `Config`
  before the scanner is created, and only where the environment did not decide.
- **Show picture** (`SetupPage.picture`): a free camera is opened for one picture and closed.
- **Crop shape** (setup page, `fitShape`): the crop is dragged in a chosen shape - 4:5 upright
  (the default), 16:9 or free - counted in the picture's own pixels, so a Pi 4 and a webcam both
  set to 4:5 give live views of the same shape on the scanner page (whose frame follows the
  picture's shape). Only the drawing is constrained: what is saved is still the four fractions,
  and detection, the capture and its storage are unchanged (the card is cut from the full
  picture by its outline). Tested in `tests/test_station_setup.py` (`CropShape`, run with node).
  A drag that starts inside the drawn crop moves it (`moveBox`, same size, stops at the picture's
  edge); one that starts outside draws a new one; a right click clears it.
  A USB camera the scanner is using: the scanner's current frame. A Pi camera the scanner is
  using: the scanner shows only its crop, so it lets go of the camera for the moment
  (`CardScanner.with_camera_released` - the capture thread closes it, the picture is taken,
  it opens again; 4.5 s on a Pi 4, scanning pauses meanwhile).
- **The token never reaches the page** (only whether one is saved).
- **Login** (`station_login.py`): the page asks for a password - one password, no user names.
  At the first visit it asks to choose one (at least 8 characters); `SCANNER_SETUP_PASSWORD`
  fixes it from outside instead (kept the same way: a hash and a random key in the file,
  rotated when the variable's password changes). Until a password exists, whoever opens the page first
  chooses it. Everything but the page's HTML and the login itself answers 401 without a
  login.
  - *Kept hashed, not encrypted*: `data/station_login.json` (mode 600) holds a random salt,
    the scrypt hash of the password (N 2^14, r 8, p 1) and a random key - never the password.
    An encrypted password could be decrypted by whoever has the key, and the key would lie
    beside it; a hash cannot be turned back.
  - *Sessions*: a cookie with an expiry time (30 days) and its HMAC-SHA256 signature made
    with that key (`HttpOnly`, `SameSite=Strict`). The station keeps no list of logins, so a
    login survives the restart after *Save and restart*. Changing the password makes a new
    key: every browser has to log in again. The key is always random and this station's
    own - never made from the password. (The first version made it from
    `SCANNER_SETUP_PASSWORD` with one SHA-256: a password guess could then be tested by
    signing a cookie with it, without a login, scrypt or the lock, and stations with the same
    password accepted each other's cookies. Found by the same review; fixed before release.)
  - *Wrong passwords*: the next attempt has to wait 1 s, then 2, 4 ... up to 30 s. The wait
    is for everyone, so someone guessing can make the owner wait up to 30 s.
  - *Forgotten*: delete `data/station_login.json` on the station and restart it.
  - *Not protected*: the page is plain HTTP - the password crosses the network unencrypted
    when it is typed. This keeps out the curious on a home network, not someone listening
    on it. The server's own pages still have no login.

Tried 2026-10-11 on the Pi 4 below, from its own Python and in the container: setup mode →
*Test connection* → save → restarted, connected and scanning; a picture in setup mode (2 s)
and while scanning; settings kept over a restart of the container; the page driven in a
headless Chromium (picture shown, a crop dragged, no script errors). On a PC only setup mode
and the page's routes were tried; choosing between two USB cameras has not been tried at all.
`tests/test_station_setup.py` covers who wins, the form's checks, the connection test (wrong
and right tokens, addresses that cannot be requested), the file, and the password
(hashing, the lock after wrong attempts, session cookies, that a cookie cannot be made from
the environment's password); `tests/test_station_uploads.py` the notes (a restart with
captures waiting, a capture sent twice under one id, held captures sent or deleted) against
a stand-in for the server. Tried on a PC: a capture left waiting, the station restarted from
its page - the new run queued it and went on trying; two captures for another server shown
as kept, and deleted with the page's buttons in a headless Chromium. Not tried: a real
server accepting a capture re-sent after a restart (the server's side of that, the same
`capture_id` twice, was measured 2026-10-08). The login was tried on a PC in
setup mode: every route refused without it, a second "choose a password" refused, a forged
cookie refused, the old cookie refused after a change; and its form driven in a headless
Chromium.

Measured 2026-10-08 (laptop, Ryzen 5 7235HS, Anker PowerConf C200, Wi-Fi; server in Docker):
manual capture to card on the page 2.7 s when the AI had to read it, auto-capture to added
0.4 s (OCR); a focus sweep asked from the page, its result saved on the server; fixed area,
rotation, focus check interval and detection switched from the page; server stopped for 12 s
with a capture waiting - sent when it was back, one card; the same `capture_id` twice - one
card. Client load: ~30% of one core, 155 MB (66 MB in the container). A live run of 17 cards:
17 captures, 17 added, all read by OCR (median 0.11 s), 1.7 s per card.

Measured 2026-10-09 on a Raspberry Pi 5 (8 GB, Raspberry Pi OS / Debian 13, the same camera,
Wi-Fi, the client in its container): ~50% of one core idle, ~70% while scanning, 75 °C, no
throttling; live view 11.6 fps; a live run of 18 cards in 28 s (1.6 s per card), all read by
OCR.

### A page per camera

Every station has its own scanner page, `/scan/<id>`: its live view and controls, the card it
is showing, its review queue, its Undo, its activity log and its scanned-cards count. `/` lists
the stations (`templates/stations.html`, refreshed from `GET /api/stations`). A station's count there is
`scanned`, its copies in the scanned cards now (what its page lists); `captures` in
`data/stations.json` counts every picture it ever sent and only numbers the captures.

Review items without a station (`review_queue.station` NULL) are listed on **every** camera's
page beside its own (`ReviewQueue._of`), and counted for each station in the list. They come
from the camera the server itself could have until 2026-10-12 - what it had queued, and its
captures that were still waiting to be read at the update - whose page went with it; shown
nowhere, they could never have been resolved. Resolving one on any page removes it from all;
clearing a camera's scanned cards leaves them. (Tested on a temporary database; no real
installation with such items was updated.)

On the server each station has a **desk** (`server/desks.py: Desk`, `desk_for`): its scanner, the card
on its page (`current_card_info`), its open review, the capture being reviewed, its captures
being read. The handlers were written for one camera and still read that way: `desk()` gives
the current desk and `scanner` is a proxy for `desk().scanner`. Which desk is current:

| Where | The desk |
|---|---|
| A scanner page's Socket.IO event | The station the page named when it connected (`io({query: {station}})`, `page_stations`); the page's socket is in the room `station:<id>` |
| An HTTP request | `?station=<id>` (the scanner page adds it to every `/api/` request - a wrapper around `fetch` at the top of `scanner.js`), or the id in `/api/stations/<id>/...` |
| A worker thread | The one set with `in_desk(...)`: `submit_capture` remembers its desk for the result, the OCR / AI workers run each job in its desk (`Job.scope`), a `RemoteScanner`'s callbacks in its station's (`at_station`) |
| Anything else | `default_desk`: a desk with no camera (a request that names no station) |

Events about a card go to the desk's room only (`emit_desk`: captured, found, added, queued
for review, log lines, the capture beep, camera settings); events about shared things stay
broadcasts (card data, game, AI provider, the scanned list changing).

| Per station | Shared by all |
|---|---|
| Camera settings (focus, rotation, fixed area, focus check interval), add automatically, debug trace | The game being scanned (switching it stops every camera) |
| Location for scanned cards | AI provider, model, keys, prompts, OCR first |
| Review queue, Undo, the card on the page | Card data, the collection, decks, backups |
| Count of cards scanned | Sound settings |

### The scanned cards, by camera

The scanned cards are **one list** (`scan_inventory`), with a camera filter - so there is one
place to check everything and one "Add to collection", and each camera's page still shows only
its own.

The same printing scanned by two cameras into the same location is one entry, so who scanned
what is recorded beside the entries: the station of every capture (`inventory_captures.station`)
and how many of an entry's copies each station added (`inventory_sources`; `add_card(source=)`).
Everything that concerns "a camera's cards" goes through `InventoryManager._station_rows`: the
entries a station has copies in, with as many copies as it added - at most what the entry still
has.

| | With a camera chosen | "All cameras" |
|---|---|---|
| List (`GET /api/inventory?area=scan&camera=<id>`) | That camera's entries; `quantity` is its copies, `entry_quantity` the entry's, `shared` when they differ - the page then offers no edit / delete, which act on the whole entry | Every entry, with `cameras: {name: copies}` |
| Add to collection (`POST /api/scan_inventory/to_collection`, `take_from(station=)`) | Only its copies and captures move; the rest stays | Everything |
| Clear (`POST /api/clear_inventory?area=scan`, `clear_camera`) | Its copies, its capture images and its review items (a review open on its page is closed) | Every scanned card; the review queues stay |
| Top bar count (`scan_stats`) | On a station's page: its own cards | |

- A station's page opens the list on its own camera.
- **Ownership follows the copies** when an entry is split or merged (`_move_sources`): the
  stations of the newest captures give up a copy each, as those captures move too. For copies
  without a capture (added by hand), the station that came to the entry last gives up first.
- **A move is finished after a crash for the camera it was for**: the note in `pending_moves`
  carries the station (simulated 2026-10-08: moved once, the other camera's copy still scanned).
- **Backups** include `inventory_sources`; a backup made before stations restores with no
  ownership rather than keeping today's.

Measured 2026-10-08 with two pages open at once (a camera station and a station uploading
captures): each page received only its own station's events, including the OCR / AI log
lines; review queues, focus-check interval and location were each station's own.

## Card detection

This chapter, [Auto-capture](#auto-capture) and [Focus](#focus) describe `CardScanner` (`scanner.py`, `object_detector.py`): it runs where the camera is, inside `station_client.py`
on a camera station. The Android app
has the same rules ported to Kotlin (its README maps the files).

**Frames.** USB cameras deliver MJPEG; the scanner asks OpenCV for the raw JPEG
(`CAP_PROP_CONVERT_RGB = 0`) and `grab()`s every frame off the camera (so frames are never stale)
but decodes only `camera.fps` of them. For cameras of 1920 px and wider, live frames are decoded
at **half size** (2560 × 1440 → 1280 × 720): detection, stability, focus measurement and the
preview stream all work at that size, and a capture decodes the stored JPEG at full size and
scales the card's corners up (`get_detected_card`, `get_full_frame`). OpenCV runs with 2 threads
(`cv2.setNumThreads(2)`) - its default of one thread per core spent more CPU spin-waiting than
working. The preview encodes each new frame once (`get_stream_jpeg`): a station sends that JPEG to the
server while a page is watching, and the server hands it to every browser tab showing the camera.

**Rotation** (`camera.rotate` or **Settings → Camera rotation**, saved per station as `camera_rotation`;
`set_camera_rotation` / `camera_rotation_updated`): every frame is rotated right after it is
decoded - live and the full-size capture (`CardScanner._rotate`) - so detection, crops, the
fixed area and focus all see an upright card. The card stands along the frame's short side
(1440 px) otherwise: measured over a 67-card lot, the card grew 16% (1038 → 1204 px) as the
pile rose ~20 mm, i.e. the camera sat ~14.5 cm above the box floor, and the card would reach
the frame's edge after ~115 cards. With the camera mounted sideways and the image rotated 90°,
the card's long side runs along 2560 px: at the same distance the pile can grow ~270 cards, or
the camera can come closer (~10 cm) for ~45% more detail per card and still ~125 cards.
Changing the rotation turns the fixed area off (it was drawn for the other orientation).

`object_detector.find_card_outline(frame, previous=...)` runs on every frame (~3 ms):

0. **Follow the previous card** (`_track_outline`, when the scanner passes the last outline -
   across detector gaps of up to 2 frames; after a new card is detected it starts afresh, since
   following the old outline once latched onto a new foil's inner frame, and the photo lost its
   set line): fit a line to the edges along each side of the
   previous outline (within 6 px at 640 px, corner zones left out) and intersect them. The
   result is kept if it is card-shaped, within 15% of the previous size, has edges along ≥ 80%
   of its perimeter, moved ≤ 2% (more means it was fitted to another edge, e.g. the inner
   frame of a blurry card - taking it made the outline flip) and is a rectangle (step 6) - one
   that moved ≤ 2% but is skewed keeps the previous outline as it was; otherwise it is only a last
   resort after steps 1-5. On a sleeved pile the top card's outline often merges with the
   edge of a card underneath or with the box's corner crease once the pile is high - then no
   closed contour exists (in recorded pile frames the detector found nothing in most frames
   of a still card), or the largest outline flips between the top card and the whole pile.
   Both made cards wait 8-19 s and caused duplicate captures (the flip looks like a drop).
   Replaying 5 recorded pile moments through `CardScanner`: a card the current detector never
   captured in its 4 s recording was captured 1.3 s after landing, and a duplicate case gave
   one capture.

1. Downscale to 640 px on the long side, grayscale, Gaussian blur.
2. Canny edges with thresholds derived from the median brightness, dilated to close gaps.
3. For each contour covering at least 2% of the frame, fit the minimum-area rectangle and keep
   it if:
   - its aspect ratio is within 8% of a card's (88 × 63 mm = 1.397; settled cards measure
     1.33-1.37 on the widened edges). It was 18% until a borderless Rivendell, whose name
     banner runs from side to side, was photographed without its name (2026-10-06): when the
     card's own outline did not close, the part below the banner (1.18-1.25) was the largest
     card-shaped outline. On 1,600 recorded frames of that session 104 outlines had that
     shape at 18% and none at 8%, with an outline in 1,408 frames instead of 1,421; the
     outline also jumped less between frames (38 → 7 jumps over 5%),
   - the contour fills at least 85% of the rectangle (it really is rectangular),
   - it is portrait - unless `detection.allow_landscape` (a card's landscape art box has
     nearly the card's proportions),
   - it isn't the frame *inside* a card's dark border: the band just outside the rectangle
     must not be darker than the band just inside (this happens when the card's outer edge
     is cut off by the image border).
4. The largest remaining rectangle is the card; its four corners are returned.
   - **Unless it is the box** (`_card_inside_box`): with the whole scanning box in view, its
     floor is a closed, card-shaped outline, while a card pushed into the box's corner shares
     two sides with it and has no closed contour of its own - the outline was then the box,
     and the photo had the floor around the card. If the largest rectangle's edge is about as
     bright inside as outside (inside ≥ 75% of outside: white floor, white wall), a
     card-shaped rectangle inside it with a dark border (inside ≤ 50% of outside), edges along
     ≥ 80% of its perimeter and at least half its area is taken instead. A side must lie ≥ 4%
     of the box's length away: a clear sleeve's edge is such a pale outline too, 1-2% outside
     its card, and is left alone (on 400 recorded frames, 15 of a sleeved card would otherwise
     have changed; with the 4% rule none do).
5. **Broken outline fallback** (only when step 3 finds nothing): where a card's edge is as
   bright as the background - a borderless foil's silver frame against the white box - the
   outline has a gap and no closed contour exists (a Gwen Stacy borderless: the right edge
   along the text box, ~100 px, had no edge at all). Edge pieces within ~15 px of each other
   are grouped; a group's hull counts as the card if its rectangle passes the same ratio,
   portrait and inner-frame checks, the hull fills ≥ 90% of it, and edges run along ≥ 80% of
   its perimeter. On 100 recorded frames it found only that card (no false detection on empty
   boxes, piles or screenshots); it costs ~5 ms more on frames where it runs.
6. **Rectangle check** for the outlines of steps 0 and 5, which are built from edge pieces or
   fitted lines: opposite sides within 4% of each other and corners within 3° of square (the
   camera looks straight down). A holo Pokémon card (N's Zoroark ex) once gave a skewed outline
   whose "top edge" was a streak of the holo art running from the name to the top-right corner,
   and the photo lost the card name. Rejected outlines leave the photo to the other steps or,
   in fixed area mode, to the area itself. The check was 8% / 8° at first and skipped the
   followed outline that had moved ≤ 2%: such an outline creeps a little every frame, and a
   showcase Théoden was photographed with corners of 84° and 94° (top edge 6° off, the name
   chopped; 2026-10-06). On 400 recorded pile frames, followed outlines that were right were
   within 2% / 1°, wrong ones 7-15% / 3-7° off; with 4% / 3° none of the skewed ones is left.
   A skewed followed outline is not dropped but replaced by the previous outline: dropping it
   left the photo to the other steps, which on a borderless The Shire took the frame inside
   the card - the outline went back and forth and the same card was captured 9 times (2026-10-06).
7. **Gap closing** (only when steps 3 and 5 find nothing; `GAP_CLOSING`): a card lying against
   the wall of a small box has a side where its black border meets the wall's shadow, and that
   side of the outline comes out in pieces. The edge image is closed with a 21 px square (gaps
   up to ~7% of a card's width) and step 3 runs again. Closing *before* step 3 was tried and
   dropped: it lost outlines that are found without it (10 of 271 frames of one session).
   Measured on recorded frames, old detector → new, with the outline followed as the scanner
   does: three Pi camera sessions 274 → 423 of 471, 256 → 365 of 513 and 389 → 585 of 764
   frames with an outline; 704 frames of the USB camera 593 → 606 (the 13 gained are cards in
   motion). No frame lost its outline. On stretches where a still card had waited, found in
   0-48% of the frames before and 82-100% after (one card, the worst, still only ~55%).
   Live: one session of 17 cards on the Pi camera (below); not run live on a USB camera.
8. **The picture's own border is not a card** (`_is_whole_picture`; in step 3 and on the final
   result): an outline whose corners all lie within 3 px of the picture's corners is dropped.
   A dark picture with a card's proportions - a Pi camera's crop around the box, the lamp off -
   gave exactly that: the edge thresholds follow the picture's median brightness, near zero
   the sensor's noise becomes one sheet of edges, and the sheet's outline is the picture.
   Seen once on a station in the dark (2026-10-12; never captured, the picture was too
   blurry). With synthetic dark frames (brightness 2-8 of 255, with noise): 474x640 and
   1382x1866 pictures gave the whole picture as a card in 96 of 120 frames before, 0 of 120
   after; a 16:9 picture gave none either way. The 3,200 recorded frames on the development
   machine (USB camera) give the same result before and after, and a drawn card 12 px from
   every border is still found. The 1,600 recorded frames of the Pi camera (three sessions)
   give the same result before and after as well. Not run live with the lamp off. The
   Android app's port has the rule too (`CardOutline.kt`: `isWholePicture`).

`warp_card(frame, corners)` maps the corners to an upright rectangle with the card's aspect
ratio - the image sent to the AI is flat and tightly cropped, and the collector line is always in
the same place.

For display, the last detection is held for 6 s when the card is briefly lost ("HOLD"), but a
held detection never counts as a still card.

## Auto-capture

### When a card is ready

A frame counts toward `stable_frames` only if `_is_card_settled()` holds:

- the corners moved less than **1.5%** (`auto_capture.max_movement`; 1% until 2026-10-15. 2% was tried for one run of the
  same 69 cards (no waits, but one double: Captain America again 1 s after its capture, jump 3.8% with the
  picture unchanged) and put back - the limit is not to be moved on one run's evidence; 1% was changed when
  a Pi 5 run of 211 cards showed the corner network's outline jittering 1-1.5% on a still card
  on a tall sleeved pile: 32 waits, 18 of 5 s or more, the longest 15 s; the outline detector
  measured <= 0.4%) of the card size since the previous frame **and** since
  the still streak began - a sleeved card sliding slowly (a few px per frame) passes the
  frame-to-frame test on every frame and used to be captured mid-slide: blurred, then captured
  again when it stopped (seen live with a Lake-town),
- sharpness (variance of the Laplacian on a 160 px wide crop) changed by less than **20%**
  (autofocus still adjusting changes it a lot),
- sharpness is at least `auto_capture.min_sharpness` (**250**) - a camera that hasn't focused
  yet is steady but blurry.

A capture needs `auto_capture.stability_frames` (5) such frames in a row, or
`fast_scan.stability_frames` (6, about 0.3 s) when cards are added automatically. Simulated
sleeve slides (0.8 s after landing): with 4 frames and only the frame-to-frame test, 12 of 12
cards were captured mid-slide; with the drift test and 6 frames none (slides of 2-3 px/frame),
captured ~0.5 s after the card stopped. 4 frames with the drift test still let a 2 px/frame
slide through. The status
pill shows *Focusing*, *Stabilizing n/N*, *Ready*, *Capturing - wait for the beep*, or
*Captured - drop the next card*.

**Why is it waiting?** When auto scanning waits more than 2 s for a card to become ready,
the scanner's log - the station's output, its page's Activity, and `data/logs/app.log` on the
server - says why, once a second (`_trace_waiting`): *no card outline found* (every 5 s), or
*card not ready (n/N)* with the frame's movement, drift, sharpness change and sharpness against
their limits (1%, 1%, 20%, `min_sharpness`). With **Settings → Cameras → Troubleshooting → Debug trace** on (remembered per station: `debug_trace`), the scanner also
keeps the last 3 s of frames (640 px wide - what the outline detector works on) and saves them,
plus the next second, to `data/debug_frames/<time>_<reason>/` (on the station's machine) when a card waits over 2 s or a
new card is detected, or the card is "gone", less than 2 s after a capture (a likely duplicate:
a foil Gwen Stacy lost its outline right after its capture and was captured again - by its
look the pair differed 0.79, so appearance can't tell such a case from a new card); the newest 30 dumps of each
reason are kept (counted per reason since 2026-10-15: a run of captures writes one "soon after capture" dump each and
used to push the "waiting" ones out); the older dumps go
are kept. Replaying such frames through `CardScanner` with a fake camera reproduces the case.

**Camera frames as training data (debug trace on; since 2026-10-14, never tested on a Pi).** A
capture is the card cut out and straightened: the frame it came from and the outline found in it
are gone, and those are what a better detector would be trained and scored on. With debug trace
on, each capture is also sent with its whole camera frame (`CardScanner._frame_snapshot`: the
camera's own JPEG, encoded again only when the camera is rotated) and a note
(`station_client.queue_upload`, form fields `frame` and `frame_meta`): `corners` of the outline in
that frame's pixels (full size, also when detection ran at half size; `null` when no outline was
found and the capture is the whole frame), `frame_width` / `frame_height`, `card_size`, `rotation`,
`fixed_area`, `stable_frames` / `required_stable_frames`, `new_card` (what made the card count as
new: `kind` = `jump_or_image_change` with `jump` and `image_change`, `area_change` (fixed area:
`area_change`, `big_changes`, `differs_from_captured`), `dropped_while_focusing` or
`card_gone`, and `seconds_before` the capture), `seconds_since_previous_capture`, `capture_id` and
`previous_capture_id` (a double capture shows as a pair that follow each other within seconds).
The pair waits on the station like the capture does (`<image>_frame.jpg`, in the upload note) and
goes with it; an older server ignores the two fields. The server keeps it as
`data/frames/<capture_id>.jpg` + `.json` (`core/frames.py`, `stations_api.keep_camera_frame`): once per
capture (a retried upload adds nothing), never failing the capture, capped at 3 GB (oldest first),
outside the collection backups. The note also has `station`, `number` and `image` (the capture's
file in `scanned_cards/`). Since 2026-10-15 a frame goes with its scanned card: once the capture is settled
the server notes its `uid` in the frame's `.json` (`frames.attach`, called from `submit_capture`), and
when the scanned cards are cleared (a camera's, or all: `clear_camera`, `clear_inventory`) or added to the
collection (`scan_to_collection`) the frames of the captures that left the scanned list are deleted
(`inventory_api.release_frames`, `Inventory.capture_keys`, `frames.forget`) - unless **Keep camera frames
after clearing or adding** is on (Settings → Storage; `keep_frames` in
`data/settings.json`, through `/api/capture_copy`), which is for the days frames are labelled. A frame
without a `uid` (taken before this, or never settled) stays until the 3 GB cap. Tests:
`tests/test_frames_release.py`. Only captures have a frame: a card that was *missed* leaves none (the
stations' own `debug_frames/` dumps are what show those).

**Labelling and scoring the frames** (stdlib / this checkout only, never against the live server's
`data/`: copy `data/frames/` first). `scripts/label_frames.py --frames <folder>` serves a local page
(127.0.0.1) that shows each frame with the detector's outline and lets a person drag the four corners
onto the card's own edge (not its sleeve, not the cards under it); it writes
`<capture_id>.label.json` (`corners` top left, top right, bottom right, bottom left, in the frame's
pixels, and `status`: `labelled` / `no_card` / `unsure`) beside the pair and changes nothing else.
`scripts/score_detector.py --frames <folder> [--station ID]` replays the labelled frames through
`ObjectDetector` and prints the intersection over union (IoU) with the label per station and mode -
for the outline the station stored (its note) and for the one this code finds now. The replay starts
cold on one frame (no `previous`), so it is for comparing one version of the code with another, not
for the live numbers. First measurement (2026-10-14, 78 labelled frames, one Pi box with sleeved
cards, a webcam): the laptop's stored outlines matched the labels (IoU 0.997, 21 frames); the Pi's
were too large on nearly every edge (IoU 0.90 in outline mode, 13 frames; mean 3-4% of the card's
width per side, up to ~10%), following the pile's silhouette - the cards under the top one and the
sleeves' rims. Among the candidates the detector has, the best one would have reached 0.93, and on
5 of 13 frames a cold detection found none: edge selection is not the whole problem.

**Our own corner network (2026-10-14; used by the stations since 2026-10-15, not by the Android app yet).** The camera of this
project is always fixed overhead of a box, which is what the network is built for: no
perspective or arbitrary rotation to cover, only a card of nearly one size in a window of
nearly one place. `scripts/train_corner_net.py` trains a small network (0.76 M parameters; one
card per 192 x 320 window, four corner maps read as soft-argmax positions plus a presence
score) only from labels made with `scripts/label_frames.py` - no other model's weights or
outputs. A frame is read in two stages: the whole frame letterboxed, then a window of 1.45 x
the card's box cut from the full-resolution frame (twice). Validation is by whole station
(`--train` / `--val`). The labelling page has a click mode (press D: corners 1, 3, 2, 4 - top left,
bottom right, then top right, bottom left; after the first two the box is there, the other two
put a tilt right; Escape keeps what is placed) and a station filter. Training on a GPU needs a
CUDA build of PyTorch (not in `requirements*.txt`): `--device auto` uses it when there is one
(RTX 3050 laptop: 3000 steps in 2.5 minutes, 17 on the CPU).
First result (trained on 57 Pi frames, scored on 21 webcam frames of another camera): mean IoU
0.966, worst 0.954. A box with the same place and size in every frame already scores 0.90 - 0.97
inside one station (and 0.47 across stations), so a within-station score proves little: the
held-out one, and the phone's frames are the tests that count. Trained on the Pi's and the
webcam's frames and scored on the phone's 49 labelled captures: mean IoU 0.969, worst 0.926
(the app's own outline on the same frames: 0.861; the phone's frames exist only for captures the
app did make, so the "No card" stretches of the screen recording are the test still to run).
The exported file (3 MB) loads in OpenCV's dnn and agrees with PyTorch to 4e-6; 2.6 ms a
window on a laptop CPU. Not tested: speed on a Pi, the Android build.

*In the station* (`station/corner_net.py`; the weights are `station/corner_net.onnx`, 3 MB, beside it
and so inside the images' `station/` folder; trained on 253 labelled frames, 3 "no card" ones
as negatives): `CornerNet.find` runs the whole frame in one window, then one window around the card (a
second gave the same IoU, 0.978 on 127 labelled frames) with OpenCV's dnn (no PyTorch on a
station); given the card's previous outline it skips the whole-frame stage. On a Pi 4
(OpenCV 4.10 in the `client-pi` image, 2026-10-15) the file loads and runs: 58 ms a frame cold
(the whole frame, then one window), 28 ms with a previous outline (one window); with two
refinement windows it was 86 / 57 ms. The Android app has the same network (`CornerNet.kt`,
`CardFinder.kt`, `assets/corner_net.onnx`): on an emulator (OpenCV 4.14) its corners match this
code's to 0.05 px on four frames, cold and tracked (`CornerNetParityTest`); Settings → "Find
cards with the corner network" turns it off.

*Retrained on 2026-10-15 (the file in the stations since then)*: 42 more frames were labelled, the
most doubtful outlines of the Pi 5's runs of the same 69-card pile (odd shapes, tilted edges, the
doubles' frames; `~/mtg-detector-data/label_next`), and the network was trained again on all 299
labels with the same recipe (3000 steps, ~2 min on an RTX 3050; file size and speed unchanged).
Held out by whole runs, twice (the same physical cards, so optimistic): 16 frames mean IoU 0.933 ->
0.966 (worst 0.870 -> 0.939), 26 frames 0.932 -> 0.954 (worst 0.898 -> 0.921). On all 295 labelled
frames (trained on): 0.970 -> 0.975, worst 0.870 -> 0.935. Live, the same 69 cards on the Pi 5: 69
captures, none for review, no double, no wait but the first card's (the run before: Monica's left side
was cut off and the card went to review). Not tested on the Pi 4, the phone (its app has the old
network until its asset is replaced) or a different pile.

*Live runs of the same 57 sleeved cards with the network on (2026-10-15, one pile, each run once;
the outline detector alone had needed fixed area on the Pi and lost the card for ~6 s at a time
on the phone):* Pi 4, outline mode - run 1: 57 captures, no waits; run 2: 58 captures (one double
inside the run of identical copies at the end: its triggers were image change 0.36 and 0.26),
11 "card not ready" waits, the longest 9 s. Phone: 57 captures, 57 added, none for review,
nothing waited longer than 3.9 s. Webcam: 55 captures, no "no outline" waits (how many cards
were dropped was not counted). Not measured: a different pile, unsleeved cards, other lighting. `ObjectDetector`
asks it first (`detection.neural` in config.yaml, or `SCANNER_NEURAL_DETECTOR=off`) and believes
the answer when the score is >= 0.5 and the shape is a card's (convex, 1.12 - 1.68 tall, inside the
frame, >= 2% of it); otherwise - or when the network fails or its file is missing - the outline
detector answers as before, so `None` still means "no card" to the capture logic. Scored through the
station's own code path (`scripts/score_detector.py --neural`, on the frames it was trained on, so
not a held-out number): IoU 0.977 over 253 frames, an outline on every one, 12 ms a frame on a
laptop CPU; the outline detector alone: 0.65 with 64 frames without an outline. Frames labelled
"no card" scored 0.003 - 0.061, card frames 1.00 (those 3 were in training). On the 20 recorded
drop sequences of 2026-10-06 (webcam, 20 fps) it found an outline on 94% of frames (the outline
detector 87%); on frames that lie still, the corners moved at most 0.65% of the card's height
between frames for 90% of pairs (0.85% for the outline detector), median 0.24% against 0.15%,
far below the 1% still threshold. **Not measured:** the capture logic with it (double captures,
misses) on a live run, a Pi 4's speed (the station runs at ~7 fps there; with a previous outline
it is one window), the containers' OpenCV reading the file.

**The capture beep is the signal to drop the next card.** `auto_capture_triggered` (beep +
flash) reaches the station's pages once the image is taken and a focus probe started by that
capture is done (`scanner.capture_pending` / status `capturing` until then): a station sends
`captured` at that moment (`Station.auto_captured`) and the server passes it on; with a camera
on the server it is `app.handle_auto_capture` (`announce_capture`). Auto-captures take the image at once (`capture_card_image_only(settle=0)` - the card has
already been still for `stability_frames`); the beep used to come *before* the image, which was
taken 0.3 s later, and a card dropped right away could land in it. Adding a card (after the AI,
1-2 s later) only plays the success ding. Measured with a fake camera and a probe on every
capture: image at t, probe done and beep at t + 1.0 s; without a probe, right after the image.

### One capture per card

Cards are dropped onto a pile, so the view never becomes empty. After every capture (automatic
or manual) `awaiting_new_card` is set and a tiny normalized thumbnail of the card is stored.
Auto-capture re-arms (`_new_card_arrived`) when:

- the card jumps more than **3%** of its size, or its image (32 × 45 thumbnail) changes by more
  than **0.3** between frames - the drop itself, or a hand;
- after a gap in detection (a falling card usually can't be detected for a few frames), the card
  reappears more than **0.8%** away from where it was - a dropped card never lands exactly on the
  previous one, while a detector hiccup leaves it within ~0.3%;
- no card is seen for **6** frames or more;
- the settled card looks different from the captured one.

Identical copies are caught by the drop, not by their looks. Measured noise of a card lying
still: movement ≤ 0.4%, image change ≤ 0.07, detection gaps ≤ 2 frames. In a live test with
11 drops (including two identical copies) every card was captured exactly once; real drops
measured 2–5 frames without a card, jumps of 4.5–8.5% and image changes of 0.7–1.2.

*Image change, since 2026-10-15:* the corner network's outline of a still card wobbles by 1–1.5%
of its size from frame to frame (card sizes 867, 874, 879, 890 px within 4 s), which shifts the
32 × 45 thumbnail by a fraction of a pixel. On a detailed card (Nick Fury, Agent of S.H.I.E.L.D.)
that alone made the frame-to-frame change 0.3–0.5, the card "disturbed" and so a new card, again
and again within a second (5 captures of 2 cards in one run, 3 and 2 of 2 in the next; none were
drops: jumps of 0.5–1.5%). The two comparisons that look at the picture - frame to frame
(`card_disturbed`) and the settled card against the captured one (`_new_card_arrived`) - now blur
both thumbnails (σ 1.5) and normalise them again before comparing (`_thumbnail_difference(smooth=True)`),
and the limit is `IMAGE_CHANGE_LIMIT` = 0.35 (was 0.3 on unblurred ones). Measured on 11 consecutive
capture pairs of that run: the same card differed 0.45 at most unblurred, 0.22 blurred; different
cards 0.67 and 0.51 at least. The flicker test above stays unblurred. `tests/test_image_change.py`.

Captures are also at least `auto_capture.delay` (1 s) apart.

When the only sign was the outline vanishing for a frame and coming back shifted (a hand
approaching), the card must not settle as the very image just captured (`_outline_flicker`:
thumbnail difference < 0.05) - in a 67-card lot a card was captured twice this way (0.02), while
real copies of a card differed 0.07-0.50 and came with bigger signs (jumps, image changes).
Over that lot the pile grew 16% in height; pace (2.0-2.5 s per card), text sharpness and focus
stayed the same.

### Fixed area (sleeved cards)

On a pile of sleeved cards the outline is unreliable: the top card's outline merges with the
card underneath or the box's corner crease, or flips between the top card and the whole pile -
cards waited seconds and some were captured twice. The **Fixed area** toggle in the camera panel
(`set_fixed_area`, saved per station as `fixed_area_enabled` / `fixed_area`) judges
cards by the image inside an area instead (`CardScanner._fixed_area_step`). The area is drawn
on the video (**Area**: drag around the card; saved as fractions of the frame) or taken from the
detected card plus 5% (**Use detected card**).

Per frame, a 48×64 grayscale thumbnail of the area with its mean brightness removed (so a
shadow or exposure change is not a change) is compared with the previous frame's:

| Measured on recorded sleeved piles | Thumbnail difference |
|---|---|
| Still card, frame to frame | ≤ 2.4 (≤ 5.4 over 1 s with the light changing) |
| A hand's shadow | ≤ 0.6 |
| A card falling in, frame to frame | 10-38, several frames in a row |
| A card settling after its capture (sleeve slide) | 13 in a single frame |
| A different card settled, compared with the last one | ~21 |

- **card present:** area sharpness ≥ `min_sharpness` (empty box ~30, a card ~1,600);
- **still:** change < 3 frame to frame and < 4 since the still streak began (a slow slide
  drifts), for `stability_frames` frames;
- **new card after a capture:** change > 8 in 2 frames in a row (a card falling in - also an
  identical copy), or the settled area differs > 10 from the captured one.

**The photo is the area as drawn.** The outline detector still runs, only for the ★/• foil
check: an outline inside the area gives the flat card whose corner is read (no outline, no foil
check). The photo used to be cut along that outline, but a holo Pokémon card's streak passed for
its top edge and the photo lost the card name - the area is what the user chose, so nothing
inside it is cut off. The outline is not drawn on the video in this mode. Replaying the five
recorded pile moments: every card captured once (the outline mode duplicated one); simulator
drops of identical copies, sleeve slides and focus probes: every card captured once, none
mid-slide.

### Adding automatically vs. reviewing

With **Add cards automatically** (default; internally `fast_scan_mode`, saved per station as
`auto_add`): the capture is uploaded, put on record and queued (`submit_capture`), read in the background (`Identification.submit`: OCR, then the AI
workers - see [The two queues](#the-two-queues)), and a confirmed printing
is added immediately by the server (`add_automatically`: one Near Mint copy in
`Game.suggested_finish` - the same rule as the page's `suggestedFinish`) - when its finish is known (`Game.finish_known`, since 2026-10-21: a printing
made in one finish only, or a ★ / • read; a printing made in both with the marker unread is queued for review, reason "finish not read (printed in foil and
non-foil)", instead of being added as regular - a confetti foil the Pixel's network could not read had gone in as regular), never through the
current card, so it can't replace a card being reviewed. It used to be the page that sent the
add; a tab still running an older script then sent every add without its card and all confirmed
cards ended in the review queue - and with no page open (phone asleep) nothing was added. The
station's pages are told (`inventory_updated` with `auto: true`) and show the card with an
**Undo** button (`undo_last_add`).

Anything uncertain - printing not confirmed, name not found, no name read - goes to the
station's **review queue** (`review.py`, table `review_queue` with the station's id, a copy of the
capture in `data/review/`) and scanning goes on (it used to pause until the card was reviewed). Items keep what the AI
read, the ★/• result and the best match. The *Review* counter opens them oldest first
(`review_open` → `review_item`): the capture beside the suggested card, the AI read, and a
search prefilled with it (without a match kept, the search runs at once). With an image index (see *Printing check*) it also shows **"The picture looks like"**: the five nearest
printings of the capture's picture, nearest first (`PrintingCheck.candidates`, worked out when the item is opened - nothing is stored with the item, so there is no migration), as
tiles that pick the printing when clicked (the same `select_printing` as the printing list) - beside what the AI read, never instead of it; the one that was read is outlined and
tagged, the nearest says "closest". An item whose foil marker was not read says so ("check the finish before adding"). Limits: the candidates come from the picture file the item keeps, so for a station
that sends a fixed area they are those of the area as drawn (the flat copy is not kept) and poorer; and the finish hint covers items in the review only - a card added automatically
with an unread marker is still filed as regular, with no flag (a printing that exists in one finish only is not affected). `scripts/check_review_page.py` tries the panel in a headless browser. Add resolves the item
- the capture becomes the entry's thumbnail - and the server sends the next; Skip drops it
(`review_skip`; the review's **Delete** button does the same when the card can't be found);
Close leaves the rest (`review_close`). Cards added automatically meanwhile
don't disturb the open item, and a card captured during a review in any other way (manual
capture, auto scanning without automatic adds) goes to the queue too (`route_identified`)
instead of taking the reviewed card's place and capture. The review belongs to the page that
opened it (`review_sid`): when that page disconnects the server closes it, and the page opens
it again when it reconnects. Per station and game; kept across restarts.

With the switch off, each capture is uploaded with `mode: review`, read at once
(`Identification.identify`) and shown on the station's page, where it waits for **Add** / **Skip**;
the station holds its next capture until then (`card_under_review`), and a card dropped
meanwhile is captured right after.

### A card back stops auto-capture

A face-down Magic card is a stop sign (since 2026-10-21; `docs/plans/CARD_BACK_STOP_PLAN.md`): put one at the end of a stack and the camera stops by itself
instead of capturing whatever is dropped next. **How it is recognised** (`core/card_back.py`): the picture index's own fingerprint (`image_index.hash_card`) of
the flat card - `foil_image` when the station sends it - as given and turned 180 degrees, against the fingerprint of Scryfall's picture of the standard back,
pinned in the code as hex (`CARD_BACK_FINGERPRINT`, made with `image_index.DESCRIPTOR` - a test pins that; recomputed by
`scripts/experiments/image_match/card_back_fingerprint.py`); a back from `CARD_BACK_MIN_SIMILARITY` on. **That threshold, 0.35, is provisional**: the 16,881
saved captures of card fronts on the development machine reach at most 0.219 (99.9% below 0.177), Scryfall's back degraded on purpose stays above 0.92 when
blurred, darkened, tinted or compressed and near 0.71 with a glare spot or a 3% perspective error, but falls to 0.35 cropped by 5% and 0.42 with everything
together - **no real camera capture of a back has been measured yet** (`scripts/experiments/image_match/card_back_measure.py --backs ... --fronts ...`).

**Where it acts**: `stations_api.station_capture`, after the upload is saved and its repeat check, BEFORE it branches into mode `review` (read at once) or
`submit_capture` - so both are covered (`captures.stop_at_card_back`). Only for a sender that understands the answer: a computer station (`camera=1`; it reads
only the capture's number from the answer, and its auto-capture follows the server's) or one that says so (`accepts=card_back`: the Android app since it knows
the status - an older one maps an unknown status to an error, so its captures are read as before). With the camera's setting on (**Settings > Cameras >
Scanning: Stop at a card back**, per station as `stop_at_card_back` in `data/stations.json`, on unless switched off; event `toggle_stop_at_card_back`), a back
is answered `{'status': 'card_back', 'similarity'}` and remembered under the upload's key (`remember_outcome`) and on record (`pending.settle_unrecorded`, in
`settled_captures` by its `capture_id`: a Codex review found that a station sending it again after a restart stopped the camera a second time) - a repeat gets the same answer and stops nothing
twice, across a restart too; it is not put on record in `pending`, not read, not added, not reviewed; the station's `auto_capture_enabled` and `card_under_review` go to False (the
latter releases a `review` capture's hold); the camera's pages get `auto_capture_toggled` and `card_back_seen` (a log line, a notice, the queue alert's beeps - and the
Start / Stop button now follows `auto_capture_toggled`, which it did not before: a game switch stopped the cameras with the button still saying Stop); `scanned_cards.log`
gets `(card back)` with the reader `card-back`, the reading log a record with `card_back` (the similarity) and `result.outcome: card_back`. The picture stays in
`scanned_cards/` (the clean-up removes it with the others) - it is what the threshold will be measured on. The phone's sync route refuses a back (409: nothing
was added). A failing check is "not a back": the capture is read as before.

Not covered: a capture waiting in `pending` when the server stopped is read as before when it resumes (`resume_pending` does not check: every capture on
record there passed the check at its upload, or came before the check existed); a sleeved card shows the SLEEVE's back; other products' own backs and a
double-faced card's back are read as cards (they land in review). The standalone phone app reads cards itself and does not check.

## Identification (vision AI)

### The two queues

Reading a card is shared by every camera (`identification.py`, one `Identification` in
the server) and has two stages, each behind its own queue:

1. **OCR** - one worker, because the reader takes one request at a time (0.10 s per card on a
   GPU). A confirmed read with its foil marker is done here.
2. **Vision AI** - `vision_ai.workers` (default 3) at once, for what OCR passes on: a read that
   isn't a confirmed match (or no read at all - full-art and borderless cards), and the foil
   marker of a confirmed card when OCR and the foil-marker network both missed it.

So a card OCR confirms never waits behind a slow AI answer. (One small exception since 2026-10-20: for a card the AI identifies,
the foil-marker network is tried first, and that second OCR request on the strip is made from the AI worker's thread; the reader
takes one request at a time, so the OCR stage can wait for it for the length of one read - about 0.1-0.2 s. For a card OCR confirms,
the read is made in the OCR stage.) Results are handed back by one more
thread, one card at a time, in the order they are settled - not the order captured.
`Identification.identify()` runs both stages in the caller's thread (a capture sent with
`mode: review`: manual capture, and auto scanning that waits for Add / Skip). A capture of a game that is no longer the active one is
passed through unread at either stage (see `route_identified`).

Workers measured 2026-10-08 with Ollama (qwen3.5:9b-q8_0, RTX 4070 Ti SUPER, default
`OLLAMA_NUM_PARALLEL`), 12 cards: 1 at a time 1.3 cards/s, 2 at a time 1.9, 3 at a time 2.0,
6 at a time 2.0 - more than 3 workers gains nothing there.

### OCR first

With *Read with OCR first* on (Settings; `ocr_first` in `data/settings.json`, on by default),
`identification.py` reads the card with
[light-ocr](https://github.com/arcships/light-ocr) (PP-OCRv6, offline) before any AI request:

1. `CardOcr.read_card()` sends the card image to the reader process and gets every text line
   with its confidence and corner coordinates. `parse_magic()` takes the name from the title
   bar (first line in the top 16%, left of the mana cost), and from the bottom-left (below 84%
   of the height) the collector line (`U 0172`, `M0128`, `M.0010`; or `123/281` on older cards)
   and the set line (`HOB·EN`), including the symbol between set and language code.
2. `Game.confirmed_read()` looks the read up. If it identifies the exact printing (a confirmed
   match - for set + number that includes the name agreeing), the card is done without the AI.
   When OCR read no `★`/`•`, the small foil-marker network reads it from the set line (see
   *Foil and finish*); only what it is not sure of is asked of the AI's foil check.
3. Otherwise the vision AI identifies the card as before. If the AI fails too, or none is
   configured, what OCR read is used (it usually still finds the card by name for review).

Measured on 747 saved scans (Magic, mostly *The Hobbit* and *Spider-Man*, with a few Pokémon
cards and unreadable test captures among them), against qwen3.5:9b-q8_0 on the same images:

| | Confirmed match | Time per card |
|---|---|---|
| light-ocr | 658 (88.1%) | 0.17 s (GPU through WebGPU/Vulkan; 0.77 s on the CPU) |
| Vision AI | 708 (94.8%) | 1.04 s + 0.62 s foil check |
| OCR first, then AI | 710 (95.0%) | |

Where both were confirmed (656 cards) they chose the same printing every time. The collector
number pattern is strict on purpose: with a looser one, a `202米` read from a mana/level symbol
above the collector line matched another printing of the same card. What OCR doesn't confirm
is mostly a collector line too soft to read, which the AI still manages.

The reader is `src/ocr/server.mjs`, started by `CardOcr` when the app starts (the models take
1-2 s to load) and restarted after a failure (at most once a minute); its errors go to
`data/logs/ocr.log`. It needs Node.js 22+ and `npm install` in `src/ocr/` (the server's Docker image
has both; `deploy.sh` does it for an installation without Docker); without them the switch is
disabled and cards go to the AI. Its native library needs glibc 2.38 or newer, and on an NVIDIA
GPU inside a container the Vulkan driver's X11 / GLVND libraries (see INSTALL.md). `ocr.provider` in `config.yaml`
chooses GPU or CPU. Only Magic has a parser (`card_ocr.PARSERS`); other games are read by the AI.

### The vision AI request

**Retries** (since 2026-10-16; `CardIdentifier._post_with_retry`, `tests/test_ai_retry.py`): the three cloud providers
(Gemini, OpenAI, Anthropic) are asked up to three times when the answer is a rate limit (429), the provider's own
error (500 / 502 / 503 / 504) or a timeout / connection error - after 1 s and 3 s, or the `Retry-After` the provider
sent (at most 8 s). A wrong key or a bad request (400 / 401 / 403 / 404) is not repeated. The last answer is handed
back and the caller raises for its status as before (the card then goes to review). A local server has its own
fallback (native API, then the OpenAI-compatible one) and is not retried. Before this, one 429 in a batch sent the
card to the review queue as "not identified".

`CardIdentifier.identify_card()` sends the flat card image (JPEG, longest side
`vision_ai.image_size`, 1024 px) with a prompt asking for three values from fixed places on the
card:

```
NAME: <card name>            top of the card
NUMBER: <collector number>   bottom-left, line 1 ("U 0014")
SET: <set code>              bottom-left, line 2 ("HOB • EN")
```

The answer format asks for all three lines with their labels ("…, or Unknown"): with a plain
"exactly three lines" qwen3.5:9b often dropped the labels and sometimes the number line
("Mirkwood / HOB"), which lost 4 of 25 cards in one session; with the labels it answered 25/25.
The parser still accepts answers without labels, or with only some of them, and places bare
lines by their shape (number or set code). It also copes with chatty answers - Markdown
(`- **NAME**: Riolu (The card is ...)`), a comment in parentheses, a trailing ★, a number buried
in a sentence (`The number at the bottom left is "84/145"`), a language code after the set
(`PAL EN`). Letters read for digits in a mostly-digit number are
corrected (`018B` → `0188`: O/D→0, B→8, I/l→1, S→5, Z→2). Ollama
answers are capped (`num_predict`), so a model that starts reasoning aloud can't take seconds.

### Prompts

Prompts live in `prompts.py` and are editable in Settings → Card recognition → **Edit prompts**. Each
prompt (card identification, foil marker) has two parts:

- **instructions** - what the card looks like and where each value is; this is what the editor
  changes;
- **answer format** - fixed (`NAME: / NUMBER: / SET:`, or "one word: star, dot, or unclear")
  and appended by the code, so an edit can never break the parser.

Edited instructions are saved in `data/prompts.json`, keyed by game (`mtg`; ready for other
games), prompt kind, and either `default` (all models) or `provider:model`. The prompt used is
this model's, else the all-models one, else the built-in one. **Restore default** removes the
saved prompt in effect (the model's first).

**Test on last capture** runs the AI on the last card read, from any camera
(`identification.last_capture`), with the
text in the editor, without saving, and shows the raw answer, how it was read, and the database
match it would get (confirmed → added automatically, or review). The foil test needs a capture
with a detected outline.

**The built-in identification prompt has no example values.** With examples ("E 0367",
"LTR · EN", "Lightning Bolt / 0367 / M21") models copied them on blurry cards instead of
answering Unknown - once producing a real but wrong LTR #367 printing. Measured on 90 recorded
scans (the 4 blurry ones checked by eye), with the native Ollama API:

| Prompt, image | qwen3.5:9b (server) | qwen3.5:4b (RTX 3050) |
|---|---|---|
| old prompt with examples, 2048 px | 86/90 correct, 84 confirmed, 1.42 s | - |
| same, answer format moved last, 2048 px | 87/90, 85 confirmed, 1.41 s | 89/90, 85 confirmed, 2.42 s |
| **no examples, 1024 px (built-in)** | **89/90, 83 confirmed, 0.92 s** | **89/90, 86 confirmed, 1.50 s** |
| no examples, 2048 px | 88/90, 84 confirmed, 1.27 s | 90/90, 85 confirmed, 2.23 s |
| no examples, 768 px | 87/90, 80 confirmed, 0.75 s | 88/90, 83 confirmed, 1.13 s |

No variant produced a confirmed (auto-added) wrong printing. Halving the image cuts the image
tokens (~1,400 → ~900), which is most of the prompt; shortening the text saved ~350 tokens.

Providers share one request function per API (`_ask_gemini`, `_ask_openai`, `_ask_anthropic`,
`_ask_local`). For Ollama, requests set `think: false` (thinking models otherwise spend the
whole token budget reasoning and return nothing), `temperature: 0`, and `keep_alive: 30m`; the
model is preloaded (`warm_up`) when auto scanning starts, because loading a 9B model takes about
10 s. Ollama error bodies (e.g. "model not found") are logged.

## Matching the printing

`CardDatabase.search_card_exact(name, number, set_code)` tries, in order:

| Step | Match | Tag |
|---|---|---|
| 1 | Set code + collector number (unique per printing), accepted if the name roughly matches (`names_match`: same, prefix, a double-faced card's face, ≥ 60% similar, or ≥ 75% similar to the short name before the comma - "Thands" / "Thanos, the Mad Titan") | `set_number` |
| 2 | Name + collector number, then shortened name ("Thanos" → "Thanos, the Mad Titan") + number. One printing → confirmed; several (the same card under the same number in more than one set - Solemn Offering #33 in M10 and M15, basic lands; ~9% of printings) → the one whose set code is closest to the one read, else the oldest, for review (`_by_name_number`) | `name_number` / `name_number_ambiguous` |
| 3 | Name only (exact, flavor name, shortened), else fuzzy (`difflib`, cutoff 0.6, candidates sharing the first letters) - then the number to pick the printing (`name_number` / `name_number_ambiguous`, as in step 2), else the printing from the same set (if any) whose collector number is closest to the one read. If the name was read exactly and exactly one printing of it in the set read is one digit off the number read - a digit misread, dropped or doubled, compared as printed with leading zeros ("0189" for #188, "6186" for 0186, "017" for 0117) - that printing is certain (with two printings a digit away it goes to review) | `name_set_digit` / `name_set` / `name` / `fuzzy` |
| 4 | Name unrecognizable but set + number exist: trust the printed set + number | `set_number_unverified` |

Collector numbers are compared in their variants ("0014" → 14, 0014, 14s, 0014s). Names are
compared through `name_search` / `flavor_search` columns - lowercase, accent-free copies
(`search_key`: "Fíli" → "fili", "Æther" → "aether").

Only `CONFIRMED_MATCHES` (`set_number`, `name_number`, `name_set_digit`) are added automatically; the card panel
warns "Printing not confirmed" for the others.

**Manual search** (`CardSearcher.find_printings`): set + number go straight to the printing -
also without a name, or with a name no card has (runes, another language, a misread name: the
AI read the Dwarvish-rune Arcane Signet as "Nthryx-Cipher"); otherwise all printings of the name (optionally filtered by a treatment: regular, borderless,
showcase, extended art, full art, retro frame, etched, surge foil) are listed newest first and
shown as a picker when there's more than one.

## Foil and finish

Modern cards print a star instead of a dot between set code and language on foil copies
(`HOB★EN` vs `HOB•EN`). **An unread finish is not regular** (since 2026-10-21): a confirmed printing made in foil and non-foil whose marker nothing read goes
to review with its printing (`Game.finish_known`, see "Adding automatically vs. reviewing"); and in the picture + collector line path the strip's symbol and
the network decide only for a printing that prints the marker at all (`prints_a_marker`; the reading by picture's rule (3) below). For captures found by outline detection - where the corner is known to
be in the image - `read_foil_symbol()` sends the bottom-left corner (lowest 14% × left 45% of
the flat card, enlarged 3×) and asks which symbol it is (`vision_ai.detect_foil`).

The wording matters. Asked only "is the separator a STAR or a DOT?", qwen3.5:9b called regular
cards foil when the capture was a little soft: 25 of 84 regular cards (from a scanning session
where auto-added lands came out foil). Describing both shapes ("a dot is a plain round point; a
star has five sharp points") fixed that on the same set - checked by eye: 84/84 regular and
40/40 readable foils right; 3 unreadable, blurry foils were called dot. qwen3.5:4b still called
12 of the 84 regular cards foil (23 with the old wording). The prompt also says to answer
*unclear* when the set line is cut off: a crop that missed it (see below) was answered "dot"
and a foil went in as regular; with the sentence that crop gives *unknown*, and 160/160
readable cards (the set above plus later captures) stay right. The taller crop keeps the set line in
view when the detected outline also takes in the edge of the card underneath in the pile.

With *OCR first*, a marker light-ocr read is used instead: a `*`/`★` is foil, a `·`/`•`
regular. On the 747 scans that agreed with the AI on 524 of the 526 OCR-confirmed cards where
OCR read a marker, and on the two others the corner crops show a star (the AI said dot). OCR
reads no symbol on about a third of the foils (and some regular cards), so a missing one
counts as unknown - and, since 2026-10-20, a small network reads it before the AI is asked:

**The foil-marker network** (`core/foil_marker.py`, `core/foil_net.onnx`; `ocr.foil_marker` in `config.yaml`, on by default;
`tests/test_foil_marker.py`). When OCR confirmed a card but read no marker (or the AI is about to identify a card and OCR
read none), `FoilMarker.read()` cuts the bottom-left strip of the flat card (lowest 14% x left 62%, enlarged to 1,000 px high if
smaller), has the OCR reader read the strip again, finds the set line with `parse_magic`'s rules, cuts that line (a quarter of its
height of margin) to a 32 x 128 grey crop and asks a four-block convolutional network (about 100k parameters, run with OpenCV's
dnn like the corner network). It answers *foil* at a probability of 0.9 or more, *non-foil* at 0.1 or less, and *unknown* in between
or when no set line was found - then the AI's foil check follows as before. The OCR's own marker is always asked first,
and a star or dot that the second OCR request (on the strip) reads itself stands: the network is not asked then (it was never
wrong on a symbol OCR read, 99.9%; on its own it was wrong on two of five confetti-foil cards). An earlier version let the network
overrule such a symbol - found by a review on 2026-10-20, fixed the same day (`symbol_read`, with tests for both contradictions).

**The foil marker with the OCR switched off** (2026-10-20): nothing finds the set line then, so the network is asked about it at its fixed place on the flat card (`foil_marker.FIXED_BOX`, `fixed_crop`, `FoilMarker.read_fixed`;
used by `Identification._read_foil_locally` and, for the finish of a card the picture alone decided, `printing_check.read_strip_evidence` with no reader), where before the AI's foil check - 25 s on a cold model - was the only
answer. The box is the median of the set line's box over 1,487 cards (`scripts/experiments/image_match/foil_fixed_crop.py`): its centre varies by +/-0.73% of the card's height and the line is 2.4% high. **Measured with the same
network and the same threshold on held-out cards where the marker is needed (the shipped code, `check_foil_marker.py`, 600 cards):** at the OCR's own box 97.8% answered and 99.8% right; at the fixed box of a card ASSUMED upright 95.5% answered and 99.3% right,
4 ms a read (43 ms with the OCR request); on the 15 Deadpool phone captures (confetti foils) **10 answered, 9 right** (15 of 15 with the OCR, which reads the symbol itself).
**Which way up the card is must be established first** (a Codex review, 2026-10-20: the fixed place is only the set line on an upright card, and a card put in upside down fed the network art and title pixels - 5 of 30 turned
evaluation pictures got a confident wrong finish, one a foil called regular at 0.00002): `PrintingCheck.upright` turns the card the way the picture search says (it already compares both orientations) and answers None - so
the finish is 'unknown' and the AI's check follows - when the better orientation matches no printing at 0.30 or is not ahead of the other by 0.20 (`ORIENTATION_MIN_SIMILARITY`, `ORIENTATION_MIN_MARGIN`; on 1,628 pictures the
better orientation matches at a median of 0.68 and leads by a median of 0.44; 6.2% are unsure) and with no printing check or no index. **The shipped path** (`check_foil_marker.py`, the same 600 cards): 91.7% answered, **99.5% right**
(3 wrong of 550), 22 ms a read - and the same 91.7% / 99.5% for the cards turned 180 degrees, which is the point: an upside-down card is turned back before it is cut. The price of the check is 3.8 points more cards left to the AI. **It must also be a card that prints a marker** (a Codex review, 2026-10-20: knowing which way up a card is does not say it has a star or dot; the network has only the outputs foil / non-foil and answers about
whatever sits in the box): `prints_a_marker` (released from 2023-06-23 - the earliest set in the evaluation data where the OCR reads a marker, The Lord of the Rings, on 83% of its cards; nothing older is in the data - and in the
`2015` frame, since a retro frame in a new set prints the old collector line) judged by `PrintingCheck.marker_expected` over EVERY printing of the index the picture cannot tell apart from its best match (less than `AGREE_BELOW` under it - taken from the distances to the whole index, not from the five rows of `top`: with five or more same-art reprints tied, an older one just outside them was never looked at, found by a second Codex review; more than `MARKER_MAX_TIED` = 200 tied is too ambiguous and answers 'no' without a database read each).
**Measured on real pictures** (Scryfall's own scans of 80 other old-frame printings and 80 modern ones, and the owner's captures): the network with no guard answered confidently on **53 of 80 old-frame cards** (none prints a
marker) and the shipped path on **0 of 80**; modern cards 79 of 80 and 79 of 80; the owner's 600 held-out cards unchanged at 91.7% answered, 99.5% right; and again with every tied row considered, on a fresh sample of 100 each: **old frames 63 of 100 unguarded, 0 of 100 shipped**; modern 98 of 100 both ways. A first form of the rule, ALL five nearest printings, was
measured and rejected: it let only 15% of modern cards through, because a modern card often shares art with an older reprint. The rule is conservative: a card that does print a marker but is older than that date goes to the AI's
check. **On the AI path the network's answer is provisional** (a third Codex finding): it is taken before the AI says which card this is, and the check ran on the nearest *indexed* printings - a card the index lacks can borrow a
modern lookalike's marker layout. So once the AI has named the card, the answer stands only if that printing resolves and prints a marker (`Identification._resolved_prints_a_marker`); otherwise it is discarded and the AI's own foil
check runs (one extra AI request, only in that case). The picture-alone path needs no such step: the printing it decides is the best match, which is always among the printings `marker_expected` checks. **The same test guards the picture-alone path** (`orientation_established`, used by `upright` and by `live_read` when it has no reader; a Codex review found the second use missing): a picture can pass the printing's 0.5 similarity and 0.05 lead and still be nearly as near to the other orientation, so without it the network would read the wrong crop and its answer become the finish - now it is not asked, and the finish falls back to the printing's own finishes or the AI's check. A taller / wider box was clearly worse (82% answered,
96% right; 4 of 10 on the Deadpool captures): do not widen it. With OCR on nothing changed: the OCR's symbol, then the network at the OCR's box. **Not measured:** other cameras, a card the warp cut loosely, cards of older frames;
and with no OCR symbol to stand first, a confetti foil can be called the wrong finish without the AI's check seeing it.

What was measured (`docs/plans/IMAGE_MATCH_EXPERIMENT.md`, section 5; 10,501 set lines of 13 recent sets from the owner's
collection; tested on cards the network was not trained on - the split is by card): where OCR had left the marker unread, right
97.6% (381 cards; 97.1% on collection photos the owner had confirmed); the whole answer - the OCR's marker when read, else the
network at 0.9 - answered 99.6% of the cards that need one and was right 99.5%; a guess from the set alone got 48.8% on those cards,
so it reads the symbol, not the set. Checked again with the shipped module (the strip OCR's own symbol first, the network for
what is left) and the real OCR reader on 400 held-out cards whose printing exists in both finishes: answered 394 (98.5%), right
on all 394; a read took 169 ms (median) and 264 ms (95th percentile) - measured while the GPU was busy with training, so probably
slow - and it runs only for cards whose marker the full-card OCR did not read. On the owner's Deadpool Secret Lair rescan (15 cards,
finish known from the physical copies) it answered all 15 and was right on all 15: the strip OCR read the symbol on 14 of them;
the network alone would have been wrong on two of the confetti-foil copies.

**Never tested:** other sets and older cards (which print no marker at all), other cameras, a Raspberry Pi or a phone's speed,
the Android app (it does not have this network), and the network trained on all the cards (the shipped file was trained on 80%,
so that its numbers above are the measured ones). The labels were not independent: for the cards whose marker OCR had read, the
stored finish came from that marker.

The web page combines this with the printing's `finishes` in `suggestedFinish()`:

1. only printed in foil → Foil (Surge foil if the printing is a surge foil) - certain;
2. only printed non-foil → Regular - certain;
3. otherwise ★ → Foil / Surge foil, • → Regular;
4. unknown → Regular.

The suggested finish is pre-filled with quantity 1 and the reason is shown ("Foil: ★ next to
the set code"). Automatic adds use the same suggestion. Cards printed before the marker existed
(roughly 2020) rely on step 1–2 only.

## Printing check (shadow mode)

*Since 2026-10-20. Research behind it: `docs/plans/IMAGE_MATCH_EXPERIMENT.md`. It changes nothing: it only writes down where
the picture does not look like the printing the server added.*

**Why.** The collector line does not always name the printing: a Secret Lair card prints the set and number of the card it is
made from, so the server resolves the base printing (the owner's Deadpool cards were all added as the base printing, 0 of 15
right); and the vision AI misread at least 12% of the cards it handled (a name and a number that agree with each other and with
nothing in the picture). The picture is the one piece of evidence that goes through neither the OCR nor the AI.

**The fingerprint** (`image_index.hash_card`, descriptor `phash_rgb_v1`): a perceptual hash of the whole card, per colour. The edge is
cut off a little, the picture is scaled to 224 x 312, each colour channel is stretched to its 2nd - 98th percentile, scaled to 64 x 64,
and the lowest 16 x 16 frequencies of its discrete cosine transform become one bit each (above or below their median):
3 x 256 bits = 96 bytes. Two pictures are compared by the number of bits that differ; `similarity` = 1 - 2 x differing / 768. The
same function makes the fingerprints of Scryfall's pictures and of a capture. It is bit for bit what the experiment's code made
(600 of 600 printings identical, with OpenCV 4.14 and 5.0; `tests/test_printing_check.py` pins it on a synthetic card), so the
experiment's numbers apply.

**The index** (`data/image_index/`: `manifest.json` and a pair of `hashes-<generation>.bin` / `ids-<generation>.txt`; about 15 MB for the
112,765 printings, twice that while the previous generation is kept; not in git, not in a backup):
built by `python scripts/build_image_index.py` - pictures are taken from a folder given with `--images` first (the experiment's cache has
them all), the rest downloaded from Scryfall at the card database's `image_uri` (8 requests at a time, never two started less than 0.1 s
apart, one 429 / 403 is waited out and a refusal that goes on stops the run), hashed and thrown away. A first build from nothing downloads
~12 GB and takes hours; a later run only does the printings added since (new sets), so it belongs after a card data update. It
checkpoints every 5,000 printings and can be stopped and run again.
**The index for a phone** (since 2026-10-20; the first step of a standalone phone that reads cards by their picture - the Android side is not written): a phone cannot build the index (118,000 pictures, hours, 12 GB),
so it takes this server's - `GET /api/image_index/download` (the generation and each file's address, size and SHA-256; 404 without an index) and `GET /api/image_index/download/<hashes|ids|printings>?generation=<g>`
(`server/stations_api.py`: `index_for_download`, `index_printings_table`; resumable with `Range`, the ETag is the SHA-256). `hashes` and `ids` are the files of the current generation as they are on disk; `printings` is a
gzipped tab-separated table (`id, set, number, oracle_id, finishes, name`, and since 2026-10-21 `released_at, frame` - added LAST, the Android app reads the columns by name: what `printing_check.prints_a_marker` needs for the phone's fixed-place foil reading; `image_index.printings_table`, from `database.printing_facts`) for the printings of the index the card data has, joined by id - the part of
the decision's evidence (`decide.py`: set, number, oracle id, finishes) a phone needs of each candidate without asking Scryfall. **Only the current generation** is served: another one is a 409 that names the current
one, so a phone never holds the hashes of one build and the ids of another. **The table is pinned by its own checksum too** (a Codex review, 2026-10-20): it follows the card data, which changes without a new generation, so its address in the listing carries `&version=<sha256>` and a request with another one - a card data update since the listing, also a resumed `Range` request - is a 409 naming the current version, never other bytes with a 200. Behind the station token (open without one, like the other station routes), read-only; the table is built once per generation and card data
download (0.7 s, in memory). **Measured on the development machine's index (112,765 printings): 22 MB in all - hashes 10.8, ids 4.2, table 6.6 MB gzipped (the oracle ids do not compress).** Tried with a Flask test client
and a synthetic index (`tests/test_index_download.py`); downloaded by the owner's phone (the app's `reading/IndexDownload.kt`) - never while the server's index was changing.

**What happens when the index changes during a download** (reviewed 2026-10-22, both sides' code). A phone can never hold a mix: each file is asked for
with its generation (and the table with its version), so a request made after a change is a 409 and the app starts again from the listing (once); every
file is checked against its SHA-256; the new index is put in place by one rename, only once it loads, else the index the phone had stays. The previous
generation's files are kept on the server (`image_index.write`: `keep = {generation, previous}`), so a file already being sent is not cut off. A card data
update that only refreshes prices changes nothing a phone downloads: the table's version is the checksum of its content (set, number, finishes...), which
holds no prices. **The window:** an update changes the two a few minutes apart (the card data, then the extended index: 09:41:28 and about 09:47 in the
first live run of the automatic update), so a download in between got a generation about to be replaced, or failed after a second 409 ("kept changing").
**Since 2026-10-22 the listing says when the index is changing** - `building` (`running`, `done`, `total`: `card_data.index_progress`) and
`card_data_updating` (the active game's download running) - and the app downloads nothing then: "The server is updating its picture index (1,200 of 3,592
new pictures) - try again in a few minutes", its index staying (`IndexDownload.ServerBusy`). An older app ignores the two fields; an older server lists
neither and is downloaded from as before. Tests: `tests/test_index_download.py` (the two fields), the app's `IndexDownloadPublishTest` (a change
mid-download: asked again, the new one published; two changes: given up, the index that worked stays; a busy server: nothing fetched but the listing).
Not tried on a phone against a server mid-update.

**The same run is a button** (since 2026-10-20): Settings > *Card data* (in Storage until 2026-10-20, then under Card reading > Picture until 2026-10-22) shows how many printings of the card database the index covers
("Covers 112,765 of 112,818 printings - 53 to add") and downloads the missing ones in the background (`server/card_data.py`: `index_status`,
`start_index_update`; `GET /api/image_index`, `POST /api/image_index/update` and `/stop`, the last two behind the settings password). The page asks for the
progress every two seconds while it runs (so it shows after a reload), a Stop button keeps what is done (`build`'s `cancel`; the next press goes on
from there; it is heard within a quarter of a second even while the workers wait out a 429 - the waits are interruptible and no request is sent after it (a review of
2026-10-20 found the first version ignored it for minutes) - except that a request already on its way is waited for, 60 s at most), a second start is refused (409) and a build started from the command line holds the same lock (said in the page). It is a button, not
automatic: after a card database update the page says the index can be updated, and the person presses it. The running server follows the new
generation by itself. Not done: re-fetching a picture Scryfall replaced (a placeholder that later got its real scan) - every printing's picture
address has a version stamp (the automatic retry of what is missing: see *Automatic updates* under Card data), but all 112,765 carry one (many were re-stamped in July with no change in the art), so the stamp cannot tell; Scryfall's
`image_status` would, and the card database does not keep it yet. **Publishing is one step** (found by a review on 2026-10-20: the
first version replaced three files one after the other): each build writes its own pair of files, nothing pointing at them yet, then
replaces `manifest.json` with one rename - it names the current pair and holds the SHA-256 of both. A build that is interrupted anywhere
leaves the previous generation current and whole (the next build clears what was left); a reader loading while one is published gets
one generation or the other, never a mix; two files that do not belong together fail the checksums even when their counts agree. The
generation before the current one is kept until the next publication, so a slow reader still finds its files. **Two writers are kept
apart** (a second review, the same day: two overlapping builds each cleaned up the other's files, the ones the manifest named included):
publishing takes an exclusive `flock` on the folder (`.publishing`) from the lookup of the previous generation to the end of the clean-up
- seconds, never while pictures are hashed - and a build holds another one (`.building`) for its whole run, so a second build is refused
(`BuildRunning`: "another build of the image index is running") instead of repeating hours of work and leaving out what the first added.
The server loads the
index when first needed and again when the manifest changes; **without an index the check does nothing** (said once in the log).

**The rule** (`PrintingCheck.check`). The capture is fingerprinted twice, upright and turned 180 degrees (a card put in upside down
matched a wrong card with a clear lead for 2% of the pictures in the experiment), and compared with every printing; the better
orientation counts. With R the printing the server resolved, `gap` = similarity of the best match - similarity of R:

| gap | verdict | meaning |
|---|---|---|
| below 0.02 (`AGREE_BELOW`) | `agree` | R looks like the picture as well as the best match: a reprint with the same art has almost the same fingerprint |
| from 0.06 (`DISAGREE_FROM`) | `disagree` | the picture looks like something else. `kind`: `other_card` (the best match is another card: probably a misread) or `same_card` (another printing of the same card: the printed line named the wrong printing) |
| between | `weak` | written down, not counted |
| - | `not_indexed` | R is a printing newer than the index |

The thresholds are from `scripts/experiments/image_match/calibrate_gap.py`, on the colour hash: among 10,677 pictures whose labels are not
known to be wrong, the gap was 0 for 95% of them and 0.036 at the 99th percentile; the 20 labels known to be wrong (the AI's misreads
among the hard cases, five Deadpool photos filed under the wrong entry) all had 0.089 or more. At 0.06, 0.68% of the right labels would
have been flagged (some of those are probably labels that were wrong too: the labels came from the OCR and the AI) and all 20 wrong ones
caught. **20 known-wrong cases is a small sample: the thresholds are a first guess for shadow mode to check, not a result.**

Checked with the shipped code and the real index (112,765 printings, built from the experiment's picture cache) on the owner's Deadpool
Secret Lair rescan - 15 captures of physical copies whose version is known: the right printing `agree`d 15 of 15 (gap 0.000), and the
printing the server had added at scan time for five of them (Lightning Strike [Game Night 2019, 42], Worn Powerstone [Starter Commander
Deck, 288]) `disagree`d 5 of 5, gaps 0.23 to 0.51, kind `other_card` (the printed line names another card than the one in the picture).
One check took 74 ms (median) and 192 ms (95th percentile) on the development laptop with a GPU training run beside it, and 24 ms and
47 ms with only the training's evaluation running (a quiet server was not measured); it runs on the background thread, so a capture
does not wait for it.

**Shadow mode** (`printing_check.mode: shadow` in `config.yaml`, the default; `off`). `search_and_emit_card` hands each capture and
the card it resolved to `PrintingCheck.observe`, which returns at once: the work is on one background thread behind a queue of 200
(more are dropped), and nothing it does can fail or delay a capture. Every card looked at is one line of
`data/logs/printing_check.jsonl` (time, station, picture, verdict, kind, gap, lead, orientation, the printing resolved and the one the picture
looks like; renamed to `.1` beyond 10 MB), and a `disagree` also a line in the log. `python scripts/printing_check_report.py` sums it up:
how many cards, how many agreed, the latest disagreements.

**The lookup: what the picture and the strip alone would have answered** (since 2026-10-20; also log-only; `printing_check.lookup` in
`config.yaml`: `ai_cases` by default, `all`, `off`). The aim is to drop the vision AI, and the evidence has to come from live scans before
anything is switched off: for the captures the AI is, or would be, needed for, `PrintingCheck.lookup` works out what the picture and the
strip alone would have done and the log keeps it beside what the AI answered. The strip is read with a light-ocr reader OF ITS OWN
(`StripReader`: a second Node process, started on the first strip, stopped after two idle minutes and at shutdown; a small request on the
bottom-left strip: `read_strip`, `card_ocr.parse_strip`; skipped while OCR is switched off, then the lookup goes by the picture alone) -
never the live reader: a review found that a slow shadow request would hold up the live OCR worker (the reader holds its request lock
while it waits) for up to its 10 s time-out, and that a time-out stops the shared process and starts its 60 s cool-down, after which live
captures go to the AI; here a stalled or failed read can only spoil the lookup's own reader (the cost: a second set of models in memory
while lookups are running). A card the search found upside down is turned back first, or the strip would be the title area (a review
found that; `tests/test_printing_check.py` pins it with two reprints of one art). The rule is the experiment's rule A2:
`strong` - the strip names a printing (number AND set) that is one of the picture's five nearest and looks as much like the picture as the
best match does (a gap below 0.02: a reprint with the same art has almost the same fingerprint, so the strip decides among those) - that
printing; `image` - else the best match, when it leads the second by 0.05 (`IMAGE_LEAD`); `review` - else the lookup would not decide.
Each record's `lookup` block has the path, the printing chosen (id, name, set, number, similarity), what the strip read, the lead, the
orientation and `against_resolved`: `same_printing`, `same_card` (another printing of the card), `other_card`, `picture_review` (it would
not have decided) or `unresolved` (the server found no card: the AI gave no answer, or one the database does not know).
`ai_cases` runs it for the captures the vision AI read and for those no card was resolved for (whoever read them): about 3% of the
captures, one more small OCR request each. `all` adds the OCR-confirmed ones (it shows how often the picture agrees on easy cards,
at one more request per capture). The hook is `search_and_emit_card` (also when nothing was found) and `route_identified` (when nothing
was read at all). `python scripts/printing_check_report.py` prints, for the AI-handled cards: how many were compared, how many the picture
and the strip would add by themselves and how many they would send to review, how they stand against what the AI resolved, how many of the
unresolved ones they would have added, the exit criteria below with the numbers so far, and the latest disagreements to look at.

**The decision is a pure function** (since 2026-10-20, phase 2a of `docs/plans/READING_REFACTOR_PLAN.md`): `PrintingCheck.lookup` gathers the evidence - the
picture's five nearest printings with their set, number, oracle id and finishes (one database read each), and what the strip says - as plain data
(`core/reading/evidence.py`) and `core/reading/decide.py: decide_printing` applies rule A2 to it; the function imports nothing but `typing`, so every test case is
a complete file. Two files of cases, made from different sources: `tests/data/reading_decision_cases.json`, hand-written with the answer worked out by hand for each edge
(22 cases, including the boundaries), and `tests/data/reading_finish_cases.json` (hand-written, for `decide_finish`; 20 cases, the boundaries included) and `tests/data/reading_regression_cases.json`, captured from the lookup as committed in a84dcb9 before it was rebuilt (135 real
pictures: 96 strong, 31 by the picture alone, 8 review; ids and similarities only). **Nothing changed in what the lookup answers**, shown picture by picture and not by
totals: the previous code (taken from git) and the rebuilt one ran on the same 444 pictures (the 15 Deadpool captures, the AI-read ones, a sample of the OCR-confirmed
ones) in separate processes and every record - path, printing, strip, lead, orientation, comparison with the resolved card, the check's verdict and gap - was identical
(`scripts/experiments/image_match/compare_lookup_versions.py`); the 72 tests that existed before passed unedited.

**The finish as evidence** (phase 2b, log only): for a capture that gets the lookup, `data/logs/printing_check.jsonl` carries a `finish` field *beside* `lookup` - never inside
it, because the exit criteria were measured on the lookup's answer as it was. The strip is read once for both (`StripReader.read`: number, set, the symbol the OCR read in the set
line and, only where it read none, the probability of the foil network - the shadow reader has a `FoilMarker` of its own, `foil_marker.read` of the live path is untouched).
`core/reading/decide.py: decide_finish` answers in this order: a printing that exists in one finish only is certain (source `printing`); else the symbol the OCR read (`symbol`);
else the network when it is at least 0.9 sure either way (`network`); else `unknown` (source `none`) - **not** regular: the live rule (`Game.suggested_finish`) files an
unread marker as regular, which is exactly where the two can differ. The field: `{decision, source, symbol, net, server, same}`; `server` is the finish the server chose
(`finish_for`, handed in by `startup.py` so `core/` needs no game code), `same` compares them with a surge foil counted as a foil, and is `null` when either side does not say.
Not measured live yet; the first use is counting `same: false` once real scans have gone through.

*Exit criteria for dropping the AI (written 2026-10-20, before any live data):* about 300 AI-handled cards compared; at least 85% of
them added by the picture and the strip; at most 0.5% wrong - judged BY EYE on the disagreements, because a disagreement with the AI is not
an error of the picture (the AI misreads about 12% of what it handles); an extra review load the owner accepts (about +0.5% of all captures
in the experiment); the index rebuilt after every card data update, with a printing newer than the index (`not_indexed`) going to review.
Then `vision_ai.enabled` is switched off by default; the AI's code stays for one release.

*Measured* with the shipped code, the real index and the real OCR reader (`scripts/experiments/image_match/check_lookup.py`): on the 128
AI-read pictures of the experiment, against the frozen corrected truth, it added 107 by itself (83.6%, 75 strong and 32 by the picture
alone) with **0 wrong**, and would have sent 21 (16.4%) to review - the experiment's colour hash with illustration ids got 85.2% and 14.8%
(two pictures more in review: the shipped rule judges "the same art" by the fingerprint, the experiment by Scryfall's illustration id).
It disagreed with what the AI resolved on 13 cards (all `other_card`: the AI's misreads, among them the five Deadpool cards) and agreed on
94. On 300 OCR-confirmed pictures it added 292 (97.3%, all `strong`) and every one of them was the printing the OCR had confirmed; 8
would have gone to review. With two real light-ocr processes side by side (`check_strip_reader.py`): the lookup's own reader started in
1.6 s and read the same strip as the live one, 30 strips each at the same time took 53 ms (median) on both, the live reader's state was
untouched, the lookup's process stopped itself when idle (two processes, then one), started again on demand, and none were left after
closing. In a second sample of 100 the one disagreement was an owner's Deadpool Lightning Bolt (`sld IFIYW-2`) that the
OCR had "confirmed" as `Lightning Strike [gn2 42]`, the base printing its printed line names: the strip read `gn2 42` too, the picture did
not look like it, and the lookup went by the picture (`image`) - the very case it is for, and the lookup's answer was the right one. **Never tried:** live scans (this is what shadow mode is for), a Raspberry Pi, a phone, a card data update
followed by a rebuild, printings newer than the index, and the 58 captures that went to review in the owner's history (they are not in
the evaluation set).

**What happens after shadow mode is not decided.** The experiment's rule would, for a printing the picture disagrees with, use the
picture's printing or send the card to review; that needs the shadow log looked at on real scans first (are the disagreements the AI's
misreads and the Secret Lair cards, or something else?), and its own tests. **Never tried:** the Android app (it has no index), a
Raspberry Pi, a Docker image with the index in its data volume, a card data update followed by a rebuild, cards of sets newer than
the index (`not_indexed`), foil and confetti-foil copies as ordinary captures (the check does not look at the finish; the rescan's were
only checked against the right printing), a quiet server's timing, and the false-alarm rate on live scans - that is what shadow mode is for.


## Reading mode: evidence - the picture before the vision AI (phase 3 of the reading refactor; the default since 2026-10-20)

**Why it is the default.** The vision AI was in this project from the start because the OCR then did not read well enough. light-ocr does now, and the picture of a card can be matched against every
printing, so the AI is the **last** step - kept as the fallback until it can be removed. What waits for the exit criteria (see *Printing check*) is *removing* it, not its place in the order.

`reading.mode` in `config.yaml` (`evidence`, the default), overridden by the person's choice in Settings > Card recognition (the event `set_reading_mode`, guarded; remembered in `data/settings.json` as `reading_mode`,
`reading_accept_image_alone` and `reading_extend_index` (the checkbox beside the index button, carried by the same event); the next card takes it - no restart and no image rebuild). The page says what the mode needs (the picture index with its number of printings - Settings > Card data - and OCR switched on;
**without them every card is read as in `cascade`**, so a new installation behaves as before until its index is built); asking for the picture alone to add cards asks for confirmation. **`cascade` is exactly the reading as it was before the picture matching existed**: OCR, then the vision AI; nothing in this section runs in it (the foil-marker tests, which predate the mode,
pass unedited, and `cascade` never calls the code of this section - a test pins that). A `reading_mode` that is not understood is `cascade`, not `evidence`.

**The order - the picture first (decided and built on 2026-10-20, the same day the mode became the default; it first changed only a card the full-card OCR did not confirm; that is history, the order below is the present one).** In `Identification._read_with_ocr`
(so also in `identify()`, which the synchronous station route uses), in this order, each step only for what the one before did not settle:
1. **the picture** (steps 1-4 below), with the collector line read from its strip when OCR is on - a card it settles is settled, and the full-card OCR is never read for it;
2. **in doubt, the full-card OCR** (when OCR is on): a confirmed read stands, with the one question below (does the picture look like another printing of the same card, or - for a name only partly read - like any other card?);
3. **the vision AI** (when it is on), whose answer is checked against the picture; else the card goes to review under the name OCR read.

OCR and AI both off: the picture alone, then review. OCR off, AI on: the picture, then the AI. OCR on, AI off: the picture, then OCR, then review. `reading.accept_image_alone` is **on by default** now (a clear picture settles a card: see below
for what that risks) - **but only while the picture index covers the whole card data** (a Codex review of 2026-10-20: with it on by default, a printing the index lacks - after a card data update, before the index is
extended - would be added as its best match, another printing, when no strip says otherwise). `PrintingCheck.missing_printings` counts every printing of the card data the index lacks - with a picture address or without, since one with none can never be indexed (a second Codex finding; there were none in the card data on 2026-10-20, 0 of 116,329) - once per index
generation and card data download (0.20 s on 112,765 printings, then remembered); `Identification._read_by_picture` passes the picture alone on only at 0, and the Card recognition section says how many are missing and that
the picture alone adds nothing until the index is updated. **The index is extended by itself after a successful card data download** (`reading.extend_index_after_update`, on by default; `Config.READING_EXTEND_INDEX`, the person's `reading_extend_index` wins; `server/card_data.py`: `extend_index_after_update` calls `start_index_update` at the end of `start_card_data_update`'s task): only when an index exists already (never a first build - hours and ~12 GB - which stays the button's), not while a build runs, and a failure to start it never turns the finished update into a failed one. The Scanner pages' banner then says "Extending the picture index: N of M" (`reading_status()['index_build']`, polled every 3 s while it runs). Never tried against a live server. **A card newer than the card data itself** (in neither the data nor the index - a third Codex finding: a complete index of a stale card data
still let its best match, another printing, be added) is caught by two more rules, each where the other cannot see: (1) the strip names a printing (number AND set) the card data does not have at all -> no add by the picture alone
(`PrintingCheck._names_unknown`; measured with `scripts/experiments/image_match/unknown_strip.py`: 13 of 47 picture-alone decisions had such a strip, all 13 right - OCR misreads of special printings like `spm 2099` - so they go on to the
full-card OCR, a cost in time, not in errors); (2) with OCR on, EVERY decision by the picture alone - whatever the strip read (a fourth Codex finding: a strip naming another existing printing was a contradiction the picture overruled unconfirmed) - needs the full-card
OCR to CONFIRM the chosen printing (`printing_check.ocr_agrees`, from `Identification._ocr_names`): the same name (`database.names_match`), and - when it read a whole collector line that is not the chosen printing's - that line must not name
ANOTHER PRINTING OF THE SAME CARD (same oracle id: a fifth Codex finding, the name alone let printing A stand where the OCR had read printing B) nor a printing the card data lacks. A line that names a DIFFERENT card is no evidence about this card's
printing and the name decides: a Secret Lair prints another card's line by design (Deadpool's Bolt reads `GN2 042`, Lightning Strike), and OCR misreads numbers (`SPM 0069` for Shocker #89 is Swarm). (A first form that rejected every differing
line refused 28 of 49 correct picture decisions, all 15 Deadpool captures among them; the same-card test must not use names_match, which takes Lightning Strike for Lightning Bolt.) Not confirmed: the card is in doubt and the OCR path reads it.
**Its cost, measured** (`scripts/experiments/image_match/confirm_cost.py`, the shipped function: 1,628 evaluation pictures and the 15 Deadpool captures, real OCR): of 49 picture-alone decisions **29 confirmed** (25 right and the 4 label errors
where the picture is right) **and 20 refused, the picture right in all 20** - OCR could not read the name (a sticker or a styled title: `Worn`, `Swiftfo`, `THRILLOF`, `WASHINGTONDC`) or read a line naming no printing (`LTR 2023`); the same-card
contradiction never occurred in the data. No error was prevented; those 20 go on to the OCR path, the AI or review. The person's design reads such doubt as a job for OCR. **Since 2026-10-21 a clear lead stands in for the name** (`decide.LEAD_WAIVES_NAME` = 0.10, `confirm_by_ocr(ocr, lead)`): the live case was the Deadpool Sol Ring, which prints "Worn Powerstone" - six live scans refused, leads 0.12-0.19. Measured with `scripts/experiments/image_match/lead_waiver.py` (every printing of a card removed from the index, the case the name check is for: the best match then led by a median of 0.005 and never more than 0.052 - 0 of 428 would be added as another card at 0.08; with the index complete, 257 of 386 right picture-alone decisions lead by 0.10 or more) and `confirm_cost.py --with-lead` (real OCR): **39 confirmed right, 6 refused (all right), the same 4 label errors - 0 more wrong.** A whole collector line naming exactly the chosen printing (`line_names: chosen`) stands in for the name as well. What the lead does not cover is the printing: `lead_waiver.py --missing printing` gave 107 wrong printings at 0.10, all of the same card - so the lines are still checked: the full-card OCR's (`same_card`, `unknown`, `lookup_failed` refuse) and, since a second Codex review the same day, the strip's (`strip_names: same_card` refuses whatever the name and the lead - `accept_printing` lets a strip naming another indexed printing through, and the name check was what caught it). And a name that is ANOTHER card's which a whole line - the OCR's or the strip's - names too refuses whatever the lead (`name_of_other_line`, a Codex review: two readings agreeing on a different card are a contradiction, not a misread); a Secret Lair's printed name comes with a part of a line at most (`Worn`, `SCD`, no number), so this cost nothing measured. None of the three has met a live case yet. **Three more rules of the same evening** (Codex reviews of the Android port, whose flaws were the server's too):
(1) **A collector number with a letter suffix names its own printing** (`printing_check.printing_named_by_line`, used by `PrintingCheck._strip_printing` and
`Identification._ocr_names`): looked up AS WRITTEN only - leading zeros off, then as read - never by its digits (`database.collector_number_variants` took
`233a` for `233`, and ZEN has both Plains: a line saying 233a "confirmed" the 233 the picture chose); no such printing in the card data is `unknown` (fail
closed: a misread suffix costs a review, never a wrong printing). Checked on the real card data: `zen 233a` -> `10a087d3`, was the 233's `e9646663`.
(2) **The confirmation reads the card the way up the picture search found it**: `live_read` returns `rotated`, `_ocr_names` reads the card turned 180 degrees
when it is set - the strip was always read so, the full card was read as given, and `parse_magic` finds the title at the top only (an upside-down card's
decision was refused for that alone). (3) **The strip's star / dot and the foil network give the finish only on a printing that prints the marker**
(`prints_a_marker`: The Lord of the Rings on, modern frame - the rule the fixed-place network already followed): an older line's separator is not known to
encode the finish; the 200 station captures with a known finish all print the marker (symbol right 76, wrong 1), so nothing was measured on older cards -
failing closed costs them the AI's foil check or a review. Left open: with OCR OFF there is nothing to agree with - the person's "picture only" configuration takes that risk knowingly; and a reprint of the SAME card in a set newer than the card data, with an unreadable
strip, passes the name check (the same name) and would be added as an older printing of that card. **The Scanner pages say when the index is stale or missing** (a banner under the header of the cameras' overview and of each camera's
page, `common.js: showIndexNotice / loadIndexNotice`, from `/api/scan_settings`'s `reading.index_missing`; asked on opening, every five minutes and after a card data update). **Measured on the rehearsal server** (`scripts/experiments/image_match/rehearse_matrix.py`: a copy of the real data in a second container, the same 39 pictures - 15 Deadpool phone captures, 12 ordinary, 12 hard
evaluation pictures - in the four configurations, each answer scored against the known one): **0 added wrong in any of them.** OCR on + AI on: 39 added, picture 18 + picture and strip 19 + AI 2 (the old order asked the AI for 20 of the same
39), median 0.12 s; OCR on + AI off: 37 added, 2 to review; OCR off + AI on: 39 added, picture 29 + AI 10, median 0.08 s; OCR off + AI off: 29 added, 10 to review, median 0.06 s. The reader labels: `picture` (nothing but the picture
decided), `picture+strip` (the collector line named the printing the picture agrees with), `light-ocr`, or the AI's model. **Not yet run on a live scan in the OCR-on configuration.**

What follows describes steps 1-4 of the picture's own reading, unchanged:
1. `PrintingCheck.live_read` fingerprints the capture (both orientations), takes the five nearest printings of the image index, reads the strip of the flat card with the
   **live** OCR reader (one more small request; here the read is the live path, unlike the shadow lookup's isolated reader) and applies `decide_printing` (rule A2).
2. `strong` (the strip names a printing the picture agrees with) or, only when `reading.accept_image_alone: true` (**on by default since 2026-10-20**, see below), `image` (the picture alone leads
   clearly; otherwise those cards go to the AI): the card is returned with its **printing id**, `reader: picture+strip`, and a `foil` field from `decide_finish` (printing's finishes, then the symbol, then the
   network; an unknown finish still gets the AI's foil check where that was possible, and otherwise stays `unknown`, which `Game.suggested_finish` files as regular, as before).
3. `review`, no index, a printing the card data lacks, or any failure: the card goes to the vision AI as in `cascade`. **With OCR switched off there is no strip** (`live_read` is handed no reader and reads none): only the picture alone can decide, and only with `reading.accept_image_alone` on - the way to try the picture on its own; with it off every card goes to the AI at once. No strip also means the guard against a printing newer than the index (`_names_unindexed`) has nothing to compare, so the similarity floor and the lead are all that stand - the 4% of the simulation. **Measured with no strip at all** (`scripts/experiments/image_match/calibrate_picture_only.py`, 1,628 evaluation pictures, picture alone allowed): it decided 1,085 (66.6%) and left 543 to the AI;
4 of the 1,085 differ from the stored label, and in all 4 the picture is right and the label is wrong (looked at by eye 2026-10-20: `Shocker, Unshakable` SPM 89 - the strip's "69" was a misread -, `Super Strength` MSH 189,
`Living Brain` SPM 167, and the Deadpool `Lightning Bolt` IFIYW-2, whose art has no rainbow), so 0 wrong - **on printings that are in the index**. A printing newer than the index is the hazard this mode cannot see:
extend the index (Settings > Card data) after every card-data update before trusting it. **The AI's answer is then checked
   against the picture** (`PrintingCheck.verdict_of`): if the picture clearly looks like another printing (`disagree`), its number and set are dropped and the card goes to
   the review queue under the name the AI gave; any other verdict, or a failed check, leaves the answer alone.

**Which picture.** Both the fingerprint and the strip are made of the *flat card* (the station's perspective-corrected picture; the capture itself when there is no separate one), and so is
the check of the AI's answer: a fixed area's capture is the area as drawn, not a card, and the index was built from whole-card pictures. The shadow log, by contrast, hashes the saved capture
file, so its numbers for a fixed-area station carry that difference. `verify_live_read.py` uses flat-card pictures only: **a fixed-area station was never tried with this mode.**

**A floor for `strong` too** (a Codex review of the whole branch, 2026-10-20): the floor below applied only to the picture-alone path, so a collector line naming ANY of the five nearest printings was enough for
`strong` even when every candidate looked unlike the capture (a probe gave `strong` at a similarity of 0.10), and the default reading would have added it. `STRONG_MIN_SIMILARITY` is 0.30: measured on 1,517 `strong`
decisions on real pictures (`scripts/experiments/image_match/calibrate_strong.py`, none wrong), the printing they pick is at least 0.245 similar (1st percentile 0.355, median 0.68), so 0.30 refuses 5 of them (0.33%; they go
to the AI) and everything near 0.10. It is a backstop calibrated against the correct decisions - no wrong `strong` one exists in the data. On the same 1,628 pictures the picture-alone path (switched on for the measurement)
made 47 decisions, 4 of which differ from the stored label - and in all 4 it is the label that is wrong (an older run's misread number; the OCR read the name the picture chose, and one is the Deadpool `Lightning Bolt`).

**A printing the index lacks (Codex review, 2026-10-20).** The lead of the best match over the second is *relative*: with an index that lacks the card's printing (a set newer than the
index, or a stale index) an unrelated best match can still lead, and the picture alone would add it. Two guards apply to a decision by the picture alone (not to `strong`, whose printing
the strip names and the picture confirms): the best match must be at least `IMAGE_MIN_SIMILARITY` (0.5) similar in absolute terms, and the strip must not name a printing the card
database has but the index lacks (if the card database cannot say, the picture alone is not enough). Measured with `scripts/experiments/image_match/calibrate_uncovered.py` on 428 real
pictures, each also with its own printing removed from the index (every add is then wrong): the lead alone still added **36%** of those; the strip rule brought it to 5.4% at no cost to
covered cards; adding the floor, **4.0%**, at 1.1 points of covered cards (which go to the AI). A higher floor costs more than it helps - a covered camera picture is only 0.66 similar to
Scryfall's scan (median), and the same-art reprints of an uncovered printing stay in the index and score high - so the floor is a backstop, not the protection. **Residual risk of the picture alone, and the history of its default** (second Codex review, same day). With the two guards above, a printing newer than the index whose strip is unreadable can still be added by
the picture alone (4% in that simulation), and a stale index makes that likelier. For part of 2026-10-20 `reading.accept_image_alone` was therefore **false** by default: such cards went to the AI, and only the decisions the strip
confirms were made without it. With that setting the same simulation added **0 of 428** pictures whose printing was not indexed, while 359 of 428 covered ones (83.9%) were still decided by picture and strip, none wrong;
allowing the picture alone was 24 more of the 128 AI-read cards. That was changed the same day, when the picture became the first step: the setting is **true** now (`config.yaml`, `Config.READING_ACCEPT_IMAGE_ALONE`; the Settings
page's choice wins), and what makes it acceptable are the guards, which are all in the code: the picture alone adds nothing while the index lacks any printing of the card data (`PrintingCheck.missing_printings() == 0`, checked in
`Identification._read_by_picture`), it needs `IMAGE_MIN_SIMILARITY`, it is refused when the strip names a printing the card database has and the index lacks (`_names_unindexed`) or one the card data lacks (`_names_unknown`),
and with OCR on the full-card OCR must confirm the printing (`printing_check.ocr_agrees`). `PrintingCheck.live_read`'s own parameter `accept_image_alone` still defaults to `False` (a caller that says nothing gets the strip-confirmed
decisions only); `Identification` always passes the setting. Rebuild the index after every card data update either way (`not_indexed` in the report says when).

**The decided printing travels by its id.** `route_identified` / `search_and_emit_card` take `printing_id` and use `Game.card_by_printing` (tag `picture`, in
`CONFIRMED_MATCHES`) instead of looking the card up again by name and number. Measured with `scripts/experiments/image_match/verify_roundtrip.py`: on a seeded sample of 3,000
printings, 14% do not come back as themselves, confirmed, from `identify(name, number, set)` - promos and special numbers (`CMR-77`, `245p`, `4g`, `185★`, `UU04a`) - so the cheaper
route (hand the server the database's name, number and set) would have added another printing or sent a right one to review. Nothing else produces the `picture` tag.

**Not recorded in the shadow log.** `PrintingCheck.observe` ignores a card whose reader is `picture+strip` (comparing the picture with the printing it chose would only
compare the choice with itself). **The exit criteria's evidence is therefore collected in `cascade` mode only**: with the mode on, the shadow log covers just the cards the AI
still handles and says nothing about the cards the mode adds itself. What the mode adds is in the scanned-cards log (`ai_model` = `picture+strip`) and the app log
(`Picture and strip: ...`) - and, since 2026-10-21, in the reading log below.

**The reading log** (`data/logs/reading.jsonl`, `core/reading/record.py`; since 2026-10-21, step 2 of `docs/plans/READING_REVIEW_2026-10-21_PLAN.md`): one JSON line per capture,
in **either** mode, of what each step of the reading saw and did - so that the thresholds and guards above, set on 20 known-wrong labels and simulations, can be judged on live scans.
It is not the shadow log and does not replace it. A record has `time`, `station`, `capture` (the file name), `capture_key` (the capture's uid, for a queued capture), `mode`, `ocr_on`,
`ai_on`, `accept_image_alone`, `game`, `index_covers` / `index_missing` (asked only when the picture alone is allowed), `seconds` per step (`picture`, `ocr`, `ai`, `total`);
`picture` (`rotated`, `lead`, the five `candidates`: id, set, number, similarity), `strip` (`number`, `set`, `symbol`, `net`), `decision` (rule A2's `path`, `printing_id`, `similarity`,
`lead`; `accepted: true` when the card was taken), `refused` - `null` or **the name of the guard** that stopped the picture's decision (`record.GUARDS`: `image_alone_off`,
`index_incomplete`, `card_not_in_data`, `below_image_floor`, `below_strong_floor`, `strip_names_unindexed`, `strip_names_unknown`, `ocr_did_not_confirm` with `refused_ocr_name` /
`refused_ocr_line` - both null when the OCR read nothing, which is also what a reader in its cool-down gives); `ocr` (the full-card read: `name`, `collector_number`, `set_code`, `foil`,
`confirmed`, `contradicted` + `why`; for the read that confirms - or not - a decision by the picture alone, also `confirms_picture` and the facts `decide.confirm_by_ocr` took, `name_matches`, `line_names`, `name_of_other_line`, `strip_names` - written whether it confirmed or not since 2026-10-21, before that only on a refusal - and `name_waived`: confirmed without the name, by the lead or the line); `ai` (`asked`: `identify` / `foil`, `answer`, `verdict` of the picture against it: `agree` / `weak` / `disagree` / `not_indexed` / `not_found`);
`result` (`reader`, `printing_id`, name / number / set, `foil`, and `outcome` + `reason` from the router: `added` / `review` / `shown`). A second kind of line, `review: true`, is
written when a review item is settled by picking a printing (`scan_events.add_selected_card`): `picked`, the `candidates` the review screen showed (kept on the desk by
`handle_review_open`), and the picked one's `rank` among them - 0: the picture's best match was right and a guard (or the AI) sent it to review; null: the picture had it wrong or showed
nothing. It joins the capture's record by `capture_key` (a review item keeps its picture under a name of its own).
How it travels: the thread reading a capture holds its record as the *current* one (`record.using`; the OCR worker, then the AI worker, with the record on the `Job`), every step adds
to whatever record is current (`record.note`, `record.refuse` - `PrintingCheck.live_read` names its guards so, `Identification` the others), and the record is then *handed over* to
the code that routes the card in the same thread (the results thread's `on_done`, or the station's route after `identify`): `captures.announce_and_route` completes it with the
outcome (`record.complete`), and one nobody completes is written without an outcome. Nothing of it is in the outcome a phone parses (`ServerOutcome.parse`). It never raises: a
failed write is a debug line in `ai.log`. Renamed to `.1` beyond 10 MB, in no backup. The summary: `scripts/reading_report.py` (`core/reading/report.py`): captures by configuration,
by reader and outcome, the refusals by guard, the review picks by rank and joined to the guard that sent the card there (the cost of each guard in live numbers), seconds per step
(median, 95th percentile), and the captures to look at by eye (picture-alone adds under 0.6 similarity, strong decisions whose strip and full-card OCR read different numbers, AI
answers the picture only weakly agrees with); the `ocr_did_not_confirm` refusals are split by why (nothing read, the name not the card's, what the line names - step 6 of the plan). *Tested with stand-ins and the synthetic index (`tests/test_reading_log.py`). First live run 2026-10-21 (OCR on, AI on, picture alone on; the owner's scans): 133 captures in 25 minutes, 121 by picture + strip, 4 by the picture alone, 8 to review; 6 picture-alone decisions refused by `ocr_did_not_confirm`; 2 review picks, both the picture's first candidate, both of a card the OCR guard had refused (the Deadpool Sol Ring, which prints another card's name - `Worn Powerstone` - and line, so no read of its text can confirm it).*

**The guards as a pure function** (since 2026-10-21; step 5 of the same plan). What `PrintingCheck.live_read` and `Identification._read_by_picture` checked inline is now two pure
functions in `core/reading/decide.py`, beside rule A2, with exactly the same rules in the same order: `accept_printing(decision, facts)` - review is no decision; the picture alone
needs the setting (`image_alone_off`) and an index that covers the card data (`index_incomplete`); the printing must be in the card data (`card_not_in_data`); each path its floor
(`below_image_floor` 0.5, `below_strong_floor` 0.30); the picture alone, a strip naming a printing the index lacks or that cannot be looked up (`strip_names_unindexed`) or one the
card data lacks (`strip_names_unknown`) - and, for the picture alone with OCR on, `needs_ocr`: then `confirm_by_ocr(ocr)` decides (`ocr_did_not_confirm`). The facts are gathered
outside (`PrintingCheck._strip_names`: one lookup of the strip's line; `printing_check.ocr_facts`: the name, the full-card OCR's line and the strip's - `ocr_agrees`, which
`confirm_cost.py` calls, is the two halves together). On the server the index's coverage is folded into the setting by `_read_by_picture` before `live_read` (as before), so
`live_read` passes it as covered and the log's `index_incomplete` is named by `_read_by_picture`. The case file is `tests/data/reading_guard_cases.json` (44 cases, hand-written: one
per guard, one per way through, and the order between them); the Android app's `Decide.kt` (`acceptPrinting`, `confirmByOcr`) passes a copy of it. The guards' names are defined
there once (`decide.GUARDS`; `record.py` imports them). `missing_printings` takes the game from the server (`PrintingCheck(..., game_id=games.active_id)`) instead of naming one.
*Checked:* `verify_live_read.py` and `compare_lookup_versions.py` unchanged (95/128, 286/300, 0 wrong; 444 of 444); the `Identification` path on 529 real captures, the tree of step 4
against this one, identical record by record, with 6 `ocr_did_not_confirm`, 10 `strip_names_unknown`, 3 + 3 below a floor and 17 picture-alone adds among them. `strip_names_unindexed`,
`card_not_in_data`, `index_incomplete` and `image_alone_off` did not occur in those captures (the development index covers its card data): the case file and the unit tests cover them.

**One body of evidence per capture** (`core/reading/capture.py`, since 2026-10-21; step 4 of the same plan). The steps of the reading ask about the same flat card more than once:
the picture search (`PrintingCheck._search`: two fingerprints, two passes over the whole index, 18 ms median) by `live_read`, then `contradicts` / `disagrees` for an OCR-confirmed
card, `upright` for the foil network with OCR off, and `verdict_of` for the AI's answer; the strip by `live_read` and again by `foil_marker.read` for an OCR-confirmed card whose
marker the full-card OCR missed; the full-card OCR by `_ocr_names` (the picture alone's confirmation) and again by `_read_with_ocr`. Each is now worked out once: the thread
reading a capture holds a `CaptureEvidence` as its current one (`capture.using`; on the `Job` between the OCR and the AI worker, let go of in `_finish`), and `_search`, the strip
(`capture.remember` in `live_read`, `recall` in `Identification._read_foil_locally`) and `Identification._read_card` ask it first. A value is kept for one picture only - the
very array it was made of - and a step with no current capture (the shadow worker, the review screen's candidates, scripts) computes as before. The strip's marker is taken as
`foil_marker.read` would answer from the same read (`_foil_of_strip`: the symbol, else the network at `SURE`), but of the card turned **upright**: an upside-down OCR-confirmed card
got `unknown` (and the AI's check) before. The two guards on the strip's printing share one lookup (`PrintingCheck._strip_printing`). *Not done:* the AI's answer is still looked up
twice (`_resolved_prints_a_marker`: `confirmed_card`; `_checked_against_picture`: `identify`) - the two lookups are not the same rule, and folding them would change what is checked.
*Checked:* the reading tests pass unedited; `verify_live_read.py` gives the same counts before and after; the full `Identification` path on real captures gives the same answer
capture by capture before and after (`tests/test_reading_capture.py` pins "once per capture").

*Measured* (`verify_live_read.py --no-image-alone` - the strip-confirmed decisions only, the shipped default for part of 2026-10-20 - with the real index, OCR reader and foil network, against the frozen truth): the 128 AI-read pictures - 75 decided
(58.6%, all strong), **0 wrong**, 53 left for the AI; a seeded sample of 300 OCR-confirmed pictures - 284 decided (94.7%), **0 wrong**, 16 left. With `accept_image_alone: true` and the two
guards (`verify_live_read.py`): 104 of 128 (81.2%) and 287 of 300 (95.7%), 0 wrong (without the guards: 107, 83.6%) when first measured; re-run on 2026-10-21 with the code of that day (all the guards since added): **95 of 128 (74.2%: 74 strong, 21 by the picture alone) and 286 of 300 (95.3%), 0 wrong** - the cause of the difference was not looked into. About 60 ms per card
(median; 75-81 ms at the 95th percentile) on the development machine, in the OCR worker. On the server, rehearsed on a copy of the real data with the real 9B model (0.18-0.41 s per card read this way, GPU peak 11.2 of 16.4 GB with two OCR readers up); *not yet run on live scans: the first live evidence is what the collection and `scanned_cards.log` (`ai_model` = `picture+strip`) show*.

**An OCR-confirmed card is asked one thing** (`Identification._contradicted_by_picture`, `PrintingCheck.contradicts`; 2026-10-20): whether the picture clearly looks like *another printing of
the same card* than the one the OCR read (the Secret Lair case: the card prints the set and number of the card it is made from). If so, the OCR read is no longer a confirmed read: its
number and set are dropped, and it goes on to the AI (whose answer is checked as above) or, without it, to review under its name (the picture was asked first and has already declined). It fails open
to the OCR: no index, no verdict or a failure leaves the read standing. The look-up is one (`Game.confirmed_card`, `confirmed_read` unchanged) and the search costs 18 ms (median) on the
development machine, on the single OCR worker, for every OCR-confirmed card in this mode. **Two rules, one question each.** (1) `contradicts`: the picture clearly looks like *another printing of the same card* - always believed. Measured on the stored labels of 10,568 OCR-confirmed
pictures, 82 disagree: 6 `same_card` (all the Deadpool Secret Lair cards, genuine) and 76 `other_card`, a mix of foil glare / showcase backgrounds / printings newer than the index on correct reads and a few
genuine misreads - so a disagreement about *another card* is NOT believed by itself (0.67% of correct reads, 43 of 6,374 on today's pipeline). (2) `disagrees` (added 2026-10-20, after the Deadpool `Lightning Bolt`
was confirmed as `Lightning Strike` in 3 of 15 captures of the first rehearsal): a disagreement about another card IS believed when **the name the OCR read is only a fragment of the matched card's name**
(`printing_check.name_only_partly_read`: `Lightning` of `Lightning Strike`; not a whole name, a face of a double-faced card, the flavor name, a legendary name cut at the comma, or noise). A sticker over the
title leaves the printed set + number to confirm the card, and a Secret Lair prints another card's set + number; `names_match` takes a prefix for a name (for `Thanos` of `Thanos, the Mad Titan`), so the lookup
cannot tell. The rule is the conjunction, because each half alone is a poor reason. **Measured on the 6,374 OCR-confirmed pictures:** 18 reads are a fragment; for 15 of them the picture agrees (no effect) and
for 3 it disagrees - exactly the three `Lightning Strike` confirmations; the other 40 disagreements (glare, showcase, new printings) are untouched. Run through the real OCR, lookup, index and gate on the 15
Deadpool captures: the gate fires on all three Lightning captures (1038, 1043, 1048) and on nothing else; the other 12 are not OCR-confirmed and go on to the picture / AI as before. What it does to such a card:
it is no longer confirmed (number and set dropped) and goes on to the AI or review (as the picture is the first step, it has already declined; measured on the picture alone, all 15 are the right printing, 1,085 of 1,628 evaluation pictures decided with 0 wrong - see the OCR-off paragraph),
to the AI (checked as above) or to review. **Not covered:** a card whose name was read *whole* but wrongly, or a Secret Lair of another card entirely read in full, with a picture that disagrees - those are
indistinguishable from glare by these signals; the picture alone (`accept_image_alone`) is the route for them.

*Not done* (decided or deferred): the single worker pool that would replace the OCR and AI workers is **decided against** (see the plan); the finish hint covers review items only.

## Database

One SQLite file, `data/cards_database.db`.

**`cards`** - Scryfall's "default cards" bulk data (gzipped JSON lines), art cards excluded; **tokens
and emblems are kept since 2026-10-20** (before, they were skipped, and the four tokens of a 62-card session
- a Cadet, a Treasure, a Dwarf - could not be matched at all). A token prints `T 0001` over `FRA • EN`: the
letter `T` where a card has its rarity (no card has that rarity), the code of the set it came with, and Scryfall
files it as the set `tfra`, number 1. `card_ocr.prints_token_letter` / `token_set_code` turn that read into the
set `TFRA` (`parse_magic`) / `tfra` (`parse_strip`), so the exact lookup and the picture's candidates find the
token and not the first card of the parent set. **Only the newer form is handled** (the letter and a four-digit
number); older tokens print neither and are found by name and number if at all. **Never tried on a real
download yet:** a card-data update (Settings > Card data) loads the tokens, and the picture index's button then
adds their pictures - until then a token is matched by its collector line alone (OCR) and the picture
cannot confirm it. The standalone Android app's parser (`ParserParityTest`) was not changed. Columns are defined
once in `database.CARD_COLUMNS`:

**The download is streamed** (since 2026-10-16; `CardDatabase._stream_cards`, `tests/test_card_data_stream.py`):
`download_scryfall_data` hands back a generator that decompresses and parses the gzipped JSON lines as they arrive,
and the import (`populate_database`) inserts them in batches of 5,000 - the file is never held whole. Measured with a
real download into a throwaway database: 112,899 cards in 10 s, peak memory 44 MB (the old path joined, decompressed
and parsed everything into one list; the review of 2026-10-16 estimated ~1.5 GB). A file cut off mid-way raises and the
swap (`replace_table`) does not happen: the old cards stay.

| Group | Columns |
|---|---|
| Identity | `id` (Scryfall id), `name`, `flavor_name`, `set_code`, `set_name`, `collector_number`, `rarity`, `released_at` |
| Prices | `price_usd`, `price_usd_foil`; since 2026-10-23 also `price_usd_etched` (what an etched-only printing has instead - 892 printings in this checkout's data), `price_eur`, `price_eur_foil` (Cardmarket's, as Scryfall gives it). The three are at the end of `CARD_COLUMNS` (an older file gets them by `ADD COLUMN`) and empty until the next download. **What is read**: `price`, `price_foil`, `price_etched` (since 2026-10-24) - the chosen price source's copy of its columns (*The price source* below); nothing reads the others for a price shown or counted |
| Card text | `type_line`, `mana_cost`, `oracle_text`, `colors` (JSON), `image_uri` (front face for double-faced cards) |
| Treatment | `border_color`, `frame`, `frame_effects` (JSON), `full_art`, `promo_types` (JSON), `finishes` (JSON) |
| Search | `name_search`, `flavor_search` |
| Deck building | `oracle_id` (the same for every printing of a card), `cmc`, `color_identity` (JSON), `legalities` (JSON: format → `legal` / `restricted` / `banned`; formats a card is not legal in are left out), `keywords` (JSON); `games` (JSON: `paper` / `arena` / `mtgo`, where the printing can be played - since 2026-10-29, at the end of `CARD_COLUMNS`, empty until the next download) |

Indexes: name, flavor name, search names, (set code, collector number), rarity, type, oracle id.
Missing columns are added on startup (search names are filled in automatically; treatment and
deck-building data arrive with the next card database update - until then
`CardDatabase.has_deck_data()` is false and the Decks tab offers the update). (A "Rebuild database schema" button that copied the
table into the canonical column order was removed on 2026-10-22: every update already builds a new table in that order with fresh indexes.)

**`inventory`** (created and migrated by `inventory.py`) - one row per game + card name + set +
number + condition + finish + location (`UNIQUE`); adding an existing combination increases `quantity`.
`location` ('' = none) says where the copies are (a binder, a box), so copies of one printing
can be in two places; `tags` ("trade, keep") belong to the entry and are not part of the key -
entries that merge keep both sets. Moving part of a stack to another location splits the row,
like a finish change (`split_quantity`). **Edit card → Printing** changes an entry to another
printing of the same card (`update_card(printing=...)`, `card_id` in `/api/inventory/update`;
the choices come from `GET /api/inventory/<id>/printings`, i.e. `Game.printings` - Magic only so
far): the set, number, rarity, card id and price change, the photos stay with the copies, and
several copies split the same way. `bulk_update` applies one change (delete, condition,
location - whole stacks -, add / remove a tag) to several entries. Cards added while scanning
get their station's location (Settings → Scan into location; `scan_location()`). Inventories from before
locations are rebuilt once on startup (the key changed): backup in
`data/backups/inventory_before_locations_<time>.db`, row ids kept (the captures point at them),
entry and card counts checked, one transaction.
Rows are addressed by `id` (edit, delete, undo). Also stores the printing id (`card_id`), set
code, rarity, type, mana cost, colors, color identity, price and timestamp. `finish` is one of
the game's finish keys (Magic: `regular`, `foil`, `surge`). Editing the finish of part of a stack
splits the row; an edit that makes a row identical to another merges them. A new finish takes
the printing's price in that finish (`Game.get_card` + `inventory_fields`); rows without a printing id (CSV imports) keep their price.

**`inventory_captures`** (also `inventory.py`) - one row per captured copy behind an entry:
`inventory_id`, `file` (a thumbnail in `data/captures/`, 400 px tall, ~25 KB - the captures in
`scanned_cards/` are deleted after `cleanup.days`; since 2026-10-14 a large copy of the same
name, at most 1200 px tall (~100-150 KB; the person's choice, below), is kept in `data/captures_full/` for training data later:
since 2026-10-18 the capture viewer loads it (`/captures/<name>?size=full`, which answers the thumbnail when the capture has no large copy): a click on the one capture of an entry, or on a picture in the window of several; it goes with the thumbnail when the capture is deleted, it is in
`scripts/backup.sh`'s archive and, since 2026-10-15, in the app's backups as well - the folder
`captures_full/` beside `captures/`, as hard links, in the zip of a backup, and brought back by a
restore and by an uploaded zip, so a standalone program that restores a server's backup has the
pictures too - and in a full backup (as optional pictures: not "missing" for captures that have
none); captures from before have none, and a zip made before has no such folder), `captured_at`, `station` (which station's
capture it is) and `capture_key` (the uid of the capture the copy came from, unique; empty in
the collection and for copies from before 2026-10-12 - see
[Capture synchronization](#capture-synchronization)). The capture follows the card from the queues to the add: `search_and_emit_card` puts it on the matched card
(`card['capture']`, so a queued automatic add can't take another card's photo), and
`pending_capture` keeps the one under review for a manual search (the automatic "not found"
dismissal keeps it, Skip drops it). Several finishes added at once arrive as one
`add_to_inventory` event (`items`) - separate events ran in parallel threads - and the photo
goes with the first. The photos follow the copies: undo removes that add's photo; moving
copies to another finish moves the newest photos with them; merging moves all; lowering a
quantity drops the newest photos (the usual reason is a card captured twice); deleting or
clearing entries deletes their files. Entries added before this, or imported, have none.
`/api/inventory` returns each entry's `captures` (newest first, URLs under `/captures/`).

**`inventory_sources`** (also `inventory.py`) - `inventory_id`, `station`, `quantity`: how many of
an entry's copies each station added. It only matters for the scanned cards - see
[The scanned cards, by camera](#the-scanned-cards-by-camera).

**`trades`** and **`trade_cards`** (also `inventory.py`: `TRADES_TABLE`, `TRADE_CARDS_TABLE`;
used in the collection - the scanned cards' file has them too, empty) - a trade is `game`,
`name`, `status` (`open` / `done`), `created_at`, `closed_at`; a row of `trade_cards` is
`trade_id`, `inventory_id`, `quantity` and `card`. In an open trade the row names the entry
and how many of its copies are set aside (one row per entry and trade; several trades may hold
copies of one entry, never more between them than it has - `Trades.add` / `set_quantity`).
A confirmed trade's rows have no entry (`inventory_id` NULL) and keep the card as it was, as
JSON, in `card`. Two triggers (`TRADE_TRIGGERS`, made again at every start, because a rebuilt
table loses its triggers) keep what an open trade holds: an entry with such a row cannot be
deleted (`trade_keeps_entry`) and its quantity cannot be lowered below the copies set aside
(`trade_keeps_copies`) - by any part of the program; the statement fails with `TRADE_HELD`,
the method's changes are rolled back, and the page shows the sentence. See [Trades](#trades).

Inventories from before multi-game support (`foil`/`surge` flags) are rebuilt once on startup:
the old table is first copied to `data/backups/inventory_before_multigame_<time>.db`, the
migration checks that the card count is unchanged, and it runs in one transaction.

Exports and imports are on the collection page only, per game and per site / app, so more can
be added: `Game.export_formats` fills the **Export…** menu (Magic: Moxfield CSV - `Edition` is
the set code, which Moxfield matches; with the set name it took the alphabetically first set of
the card; surge foils go out as `foil`; the file has the 13 columns of Moxfield's own export, in
its order, because Archidekt's **Moxfield** preset (+ **Set columns**) reads them by position - a
9-column file failed there with "Row columns do not match header columns"; the 13-column one
imported there on 2026-10-14 (Moxfield's own import: not tried); every game: "Card Scanner (everything)",
`games.base.write_collection_csv` - all the columns of an entry, with `Card ID`, `Set Code` and
`Timestamp`, so `import_csv` puts each entry back as it was), `Game.import_rows`
reads another app's file (`import_formats` names them). `POST /api/import_inventory` picks by
the file's columns: Moxfield (`Count`, `Name`, `Edition`) → `Magic.import_rows` matches each row
to its printing by set code + collector number as written (`get_card_by_set_number(exact=True)`:
"M19-128" of The List) - when the card's front name agrees with the row's, since 2026-10-15
(before, an exact match was taken whatever the name said) - then the number's variants if the
name agrees, then the name alone (counted as `by_name`: maybe another printing); `foil`/`etched` become foil, or surge for a
surge foil printing; Moxfield's conditions map to the ones here (Lightly Played → Excellent,
Moderately → Good, Heavily → Played, Damaged → Poor); tags are kept, the location is empty
(Moxfield has none - entries that differ only by location merge) → `inventory.import_entries`.
The app's own columns (`Card Name`, `Set`) → `import_csv`; CSVs written before the `Card ID` /
`Set Code` columns existed import without a link to their printing. Any other
file, or one where no card is found, is refused before "replace" deletes anything - and since
2026-10-15 so is a Moxfield replacement in which any row is unresolved (`not_found`) or has no
name (`unnamed`), as the app's own file already was: the answer names the cards, nothing is
changed, and adding instead still takes the known ones and lists the rest (`skipped` counts
not-found cards and unnamed rows both; `unnamed` says how many of them). Every upload of the
app's own CSV is written to a temporary file of its own in `data/uploads/` (`tempfile`), removed
afterwards. Tests: `tests/test_import_replace.py`.

**The database files, in common** (`storage.py`, since 2026-10-09). Every manager's connection
comes from `storage.connect`: usable from any thread (each manager has its lock), rows by
column name, WAL, `synchronous=NORMAL` (unchanged: with WAL a power cut can lose the last
commits, not corrupt the file) and `foreign_keys=ON` - SQLite enforces foreign keys only on
connections that ask. A change to an existing table is a **named migration**, recorded in the
table `schema_migrations` of the file it changed (a table, not `PRAGMA user_version`: the card
database file is shared by four managers). `storage.rebuild` does one: a backup of the file
first (`data/backups/migrations/<file>_before_<name>_<time>.db`, opened and checked - or the
migration does not start), then one transaction with every table copied into its new
definition, ids and AUTOINCREMENT counters kept, `PRAGMA foreign_key_check`, and counts and
totals compared before and after; anything else is rolled back. The older column additions
(`ALTER TABLE ... ADD COLUMN` at startup, each checked against the columns there) stay as they
are.

**Constraints** (migrations `inventory_constraints_1`, in both inventory files, and
`deck_constraints_1`): `inventory.quantity` is an integer above 0, `inventory_batches` follows an entry (`REFERENCES inventory ON DELETE CASCADE`) with a quantity above 0, `added_quantity` NULL or not
negative; `inventory_captures` and `inventory_sources` belong to an entry (`REFERENCES
inventory(id) ON DELETE CASCADE`), a station's `quantity` is above 0; `deck_cards` belong to a
deck (cascade), `quantity` above 0, `board` one of commander / main / side. The standalone program (until
2026-10-14) kept these rules as triggers on tables without CHECK or REFERENCES; a file it made is
given the rules themselves by the same migrations - they drop its triggers (`LEGACY_TRIGGERS`,
`storage.rebuild(prepare=...)`: one that names a rebuilt table made the rename fail and the server
unable to start on the file) and rebuild `inventory_batches` too. One case per rule:
`tests/test_constraints.py`, with a file in the standalone's form. So an entry or a
station's row is deleted, never kept at 0 (`_delete_entries`, `_take_copies`, `_set_source` in
`inventory.py`) - and `_delete_entries` removes the captures itself first, because the cascade
takes rows, not thumbnail files. There is no foreign key from an entry's `card_id` to `cards`:
entries outlive card data updates and other games have other card tables. Restoring a backup
made before the constraints leaves out rows that could not stand (`backups.RESTORABLE`). Run on
a copy of the collection in use (1,910 entries, 3,982 captures, 857 deck rows): every row
identical afterwards, counters kept, 0.3 s.

**Measured, not guessed** (`scripts/benchmark_db.py`, on a copy, 2026-10-09, 112,765 cards,
warm medians): a printing by set + number 0.02 ms and a card by exact name 0.02 ms (both by
index); a name by substring 34 ms and the deck builder's search 41 ms (both read every card);
the collection list 17 ms; one camera's totals among 5,000 scanned entries 4.9 ms; a camera's
oldest review item among 2,000, 0.12 ms. Done with that: `idx_deck_cards_deck` removed - the
UNIQUE index on (deck_id, card_name, board) answers the same question as fast (0.05 / 0.08 ms).
Not done, on purpose: indexes on `inventory_sources(station, inventory_id)` (4.7 -> 3.9 ms at a
size the table never has), `review_queue(game, station, id)` (0.12 -> 0.02 ms) and
`decks(game, updated_at)` (0.16 ms with 10 decks) - nothing a person would notice; and FTS5
with the trigram tokenizer for substring search, which answered in 0.05-0.14 ms (index built in
0.33 s) but would be a second structure to rebuild with every card data update and another
definition of "matches" beside the one identification relies on, for 34 ms nobody waits on.
Worth doing when the card data is several times larger.

**Imports never leave a half-filled table.** The download fills a staging table (`cards_import`) on a connection of its own (one refresh at a time), committing every 5,000 rows so the inventory can still write, and swap
it in at the end in one transaction (`CardDatabase.replace_table`: `BEGIN IMMEDIATE`, drop,
rename, indexes, the `card_data_info` row, commit - or all of it rolled back) - scanning keeps
using the old data while an update runs. Before anything is touched the import is refused when
its table is missing, empty, or holds less than half the cards in use (`MIN_SHARE`: a download
cut short); the cards in use then stay. Only `cards` / `cards_import` are accepted (`CARD_TABLES`).

**`card_data_info`** - per game: the source's own date (Scryfall's `updated_at`), when it was downloaded, and the card count.
One more row, `mtgjson_prices` (`shop_prices.INFO_KEY`): MTGJSON's date of the shops' prices in use, when they came, how many printings.

**`shop_prices`** (since 2026-10-24; `core/shop_prices.py`, `CardDatabase.replace_shop_prices`) - the shops' prices from
MTGJSON, one row per printing: `id` (as `cards.id`, the primary key) and a REAL column per shop, kind and finish -
`cardkingdom`, `cardkingdom_foil`, `cardkingdom_etched`, the same three for `cardkingdom_buy` (Card Kingdom's buylist: never a price source, shown
beside the value since 2026-10-24 - *What Card Kingdom would pay* below) and for `manapool`. A table of its own, beside `cards`, because a card data download replaces `cards` whole: the
shops' prices survive it, and new printings of the download are priced at once when the shops know them (the join).
Created empty at start; replaced whole by each price update (`replace_table`, like `cards`).

**What Card Kingdom would pay** (since 2026-10-24, phase 4 of `docs/plans/PRICE_SOURCES_PLAN.md`; `core/prices.py`: `BUYLIST`;
`CardDatabase.buylist_by_ids`; `Game.buylist_prices` - `games/mtg.py` beside `inventory_fields`; `server/inventory_api.py`;
`collection.js`: `buylistMoney`, `buylistTotal`). Card Kingdom's buylist - what the shop offers for a copy, not what it is
worth - shown beside the value, never counted in it. `/api/inventory` gives each entry of the collection (not the scanned
cards, not Arena's) `buylist`: the offer for one copy, `null` without one. It is **read when the page asks, from the shops'
table, and never written into an inventory**: no repricing, price change, `pricing_lock` or transition concerns it, and it is
not withheld while a change of currency is half done (keep it that way - stored in the entries it would need all of
them). The finish picks the column, with no fallback to the other finish (unlike the value's): a foil or surge foil copy
the foil offer, or the etched one of an etched-only printing; a regular copy the regular one - a shop pays very differently
for each, and a borrowed number would be an offer nobody made. Always in US dollars (`buylistMoney`, never `money()`),
whatever the price source. **Always with its day, never as "today"** (a Codex finding): the offers are those of the last
price update and stay until the next one replaces them - one that fails or is switched off leaves them as they were - so
`/api/inventory` also gives `buylist_date` (MTGJSON's date of the prices in use, `Game.buylist_date`, from
`shop_prices.INFO_KEY`), every place says "offered ... on 2026-10-24", and offers more than two days old
(`BUYLIST_OLD_AFTER_DAYS`: MTGJSON publishes daily) say how old they are and where to update them (`collection.js`:
`buylistAge`, `buylistWhen`; a list row's line in the warning colour, `.is-old`). **Near Mint's, and only Near Mint
copies counted** (a Codex finding): Card Kingdom states its listed buylist prices assume Near Mint and are graded lower for
a worn copy, by an amount it decides and MTGJSON does not publish. So every offer is said as Near Mint's ("for Near
Mint"), `/api/inventory` gives each entry `buylist_as_listed` (`Game.buylist_as_listed`: its condition is one of
`games/mtg.py` `BUYLIST_CONDITIONS`, Mint and Near Mint), the totals (the tile, a trade) count only those copies, and a
worn copy's row keeps the quote with "yours is Played, graded lower" in the warning colour - never a guessed discount. Shown: under a list row's value ("Card
Kingdom offered $8.50 each for Near Mint"), a Statistics tile with the copies it covers ("$2378.07 - Card Kingdom offered,
for 1,243 of 3,953 cards (Near Mint copies it buys), on 2026-10-24": a partial total must not read as the collection's), and in an open trade's summary (from the
entries; a confirmed trade's cards have none). Nothing shows before
the first *Update the shops' prices*. **Tried 2026-10-24** on a copy of this checkout's data with that day's MTGJSON prices
(102,652 printings; offers for 46,542 regular, 35,764 foil, 890 etched): 784 of 1,604 entries with an offer, 74 of them
foils; on the dearest cards the offer was 55-76% of TCGplayer's value (The One Ring HOC: $131.05 / $100.00). Never compared
with Card Kingdom's own page. The date's wording tried the same day on the copy with its prices' date set to 9 days
earlier ("9 days ago - update the shops' prices"), and with its dearest offered card set to Played: out of the total
($2378.07 -> $2278.07, 1,243 -> 1,242 cards), its row "offered $100.00 for Near Mint - yours is Played, graded lower". `tests/test_prices.py` (`TheBuylist`).

**The price source** (since 2026-10-24; `core/prices.py`, `CardDatabase.set_price_source` / `priced_printings` /
`price_currency`, `server/card_data.py`: `GET` / guarded `POST /api/prices/source`; Settings > Card data > Prices;
`tests/test_prices.py`, `PriceSources`). Four sources: two from Scryfall's file - TCGplayer in US dollars
(`scryfall_usd`, the default) and Cardmarket in euros (`scryfall_eur`, no etched price) - and two from MTGJSON's prices of the
day, *the shops' prices* below - Card Kingdom (`cardkingdom_usd`) and Mana Pool (`manapool_usd`), both in dollars. A source
says where its columns are (`kind`: `card_data`, the columns of `cards`; `shops`, those of `shop_prices`, read by a
correlated subquery on its primary key - not `UPDATE ... FROM`, so any SQLite runs it). The chosen one is remembered in
`data/settings.json` (`price_source`) and copied by one `UPDATE` (`prices.apply_sql`) into the columns everything reads -
`cards.price`, `price_foil`, `price_etched`: at every start (about a second; the file may have been filled elsewhere),
when the choice changes, and on the import table **before** each new card data is swapped in (a change during an import
is applied again after the swap). A price the source lacks is NULL there, never another source's: a euro never stands
in for a missing dollar, nor one shop's price for another's. A change then prices every entry again (`reprice_collections`) and sends `price_source_changed`
(`source`, `currency`, `symbol`); the pages take the symbol from `_topbar.html` (`window.PRICE_SYMBOL`, from
`pages.page_links`) and show every price through `common.js`: `formatPrice` / `priceSymbol` (not `priceText`, which
`collection.js` has for itself and which calls `money()`: one shared name made each call the other until the stack ran
out, found on the trial server). A source the card data holds no price from (card data downloaded before its columns
were kept), or a shop before the first price update, is refused with 409 and greyed out in the list ("after the next card
data update" / "after the first update of the shops' prices"): it would show the new currency on the old numbers. **What a
change does to an entry the new source cannot price** (`Game.price_changes`, `InventoryManager.clear_prices`, since
2026-10-24 - the owner chose market value): it loses its price (NULL; the pages show 0 / N/A, the totals skip it), never
keeps another shop's - a round trip TCGplayer -> Mana Pool -> TCGplayer first left Mana Pool's number on 23 entries. An
entry imported without its printing keeps the number it came with while the currency stays (no shop can price it), and
loses it on a change of currency. Without a change of source - a new day of the same one - an entry without a price today
keeps its own, as before. The answer counts both (`repriced`, `unpriced`) and Settings says them. **One at a time, and
finished even after a failure** (a Codex review of 2026-10-24; `tests/test_price_source_change.py`): every repricing works
out its prices and writes them under `card_data.pricing_lock`, which a change of source holds from the choice to the end
of its repricing - a shop's or the card data's update can no longer write back the prices of the source before a change.
Both inventories are repriced in ONE pass inside `maintenance_barrier` (lock order: `pricing_lock`, then the barrier):
"Add to collection" (`take_from`, under the barrier) cannot move scanned copies from the inventory not priced yet into
the one priced already, where they kept their old price - in the old currency, after a change of source (a fifth Codex
review). Each inventory is repriced in one transaction (`InventoryManager.apply_prices`: new prices and the ones taken
away together), holding its own lock from its entries read to their prices written (`InventoryManager.exclusive`: an
edit in between - copies split off to another location - made a row the repricing never saw, which kept the old
currency; an eleventh Codex review), and then noted as done in the change's note (`done`). **While a change through another currency is
unfinished, an inventory not done yet shows no prices** (a sixth Codex review: after a failure half-way it held dollars
under the € sign until the next repricing): `card_data.prices_withheld`, asked through
`InventoryManager.prices_withheld` (set in `startup.py`), makes its entries' prices 0 - the lists, the exports, the
trades - and its totals 0 with `prices_pending: true` in `get_stats`. "Withheld?" is asked under the inventory's lock
together with the rows it qualifies, and the repricing marks an inventory done under that same lock (a seventeenth Codex
review: asked after the rows, a retry finishing in between let an old total pass as current). A trade is not CONFIRMED meanwhile (`Trades.confirm`
answers "confirm it once they are repriced"; a fifteenth Codex review): its record would keep 0 for every card for good,
as it no longer refers to the entries a repricing corrects. The schedule's tick tries an unfinished repricing
again every 10 minutes (`finish_unfinished_repricing`), besides the next update and the next start. **An entry is written
at the price its printing has at that moment** (a seventh Codex review): a card shown on the scanner page before a change
of source, or an edit that read its new finish's price before one, was written in the old currency after the change's
repricing had passed. Every insert of an entry that knows its printing (`InventoryManager._priced`: the scanner's add,
the preconstructed decks, "Add to collection", the CSV import) and a change of finish or printing (`update_card`) take
the price from `current_price` (`card_data.current_card_price` -> `Game.current_price`, set in `startup.py`), asked under
the inventory's own lock, which the repricing needs too - so a change of source comes wholly before the write (it
reads the new prices) or after it (the repricing covers what was written). A printing the card data lacks keeps the
price given. **A day without a quote** (a ninth Codex review): an entry that only MOVES - "Add to collection", copies
split off to another location or condition in the same printing and finish (`_priced(moving=True)`) - keeps its own
price when the card data has none for it today, as a repricing does; a new entry takes the 0 (what reading its price now
gives - a number its caller read earlier may be of a source chosen before). A move out of an inventory whose prices are
withheld is not "as it is": its numbers may be of the old currency, so none is carried over (a tenth Codex review) - the
price is the card data's quote at that moment, or none, also for a card without its printing or one the card data lacks. That price is read **without the card data's lock** (`CardDatabase.card_for_pricing`: a read-only
connection per thread; an eighth Codex review): the collection is in the card data's file, so an inventory asks while
it holds SQLite's write lock, and a change of source holds the card data's lock while its UPDATE waits for that write
lock - through the lock, each waited for the other until SQLite's 10-second timeout (reproduced: 9.7 s). In WAL a
reader waits for no writer, and a price read just before a change's UPDATE is corrected by the repricing after it.
**A change of source is all or nothing**: `set_price_source` records the choice only once its UPDATE is in, and the
route puts the change's note back and leaves the setting alone when it fails (500, "nothing was changed"). **What must be
on disk first is written durably** (a twelfth Codex review: `Settings` printed a failed write and went on, so a restart
could forget a change whose prices stayed): `Settings.set_durably` raises and puts the value back. The change's note is
written so BEFORE anything changes (failing: nothing changes), the chosen source after its UPDATE (failing: the UPDATE
is undone - and that undoing is itself a change of source: an entry may have been written at the new source's price
meanwhile, so the note naming it is KEPT and the entries repriced back; a sixteenth Codex review), and a price change's `running` entry before the change (failing: the download does not begin). Writes after
a change stay ordinary: one that fails leaves a note behind, which only means a repricing more.
A change is noted in `data/settings.json` (`price_transition`: the source it came from and every source chosen while it
is unfinished - a change that failed half-way may have written any of their prices) BEFORE anything changes, and
forgotten only once both inventories are done; until then every repricing (the next card data or price update, choosing
a source again, the next start: `resume_price_transition`) finishes it: every entry the source now chosen cannot price
loses its price, and when any of those sources had another currency, so do the entries without their printing - so a
failure half-way never leaves dollars shown as euros, nor euros as dollars after a change back (a second Codex review of
2026-10-24: remembering only the first source, a change back to it kept the half-done change's euros). The route answers 500 then (and still tells the pages the new
currency). The database re-applies the chosen source after an import with the choice read under its own lock
(`reapply_price_source`): read before it, a change in between was undone. The CSV
export's price column says its currency (`Price (EUR)`, `€0.90`); in dollars it is the file it always was (the Android
app's `ExportParityTest`), and the import reads both. **Mixed currencies, on purpose:** other people's collections and
trades' records keep their numbers, and the entries' column is still named `price_usd`. The activity log's "Added to
inventory" line says the symbol (`InventoryManager.price_symbol`, set in `startup.py`), and the MCP server's answers say
the currency of their prices (`prices_in`; `collection_summary`: `value` and `currency`, `value_usd` until 2026-10-24) -
`USD` only for a scanner that answers 404 (older than the choice), `unknown` for any other failure of the question
(`ScannerError.status`; a fourteenth Codex review: a time-out labelled euros as dollars). Tried on a trial server with copies of this checkout's data
(2026-10-24): refused before a card data update (Cardmarket: 0 printings priced), after one 98,743 printings priced
in euros against 100,066 in dollars; to euros 1,547 entries repriced, $5,678.30 -> €5,266.15, back to dollars exactly
$5,678.30; the collection, deck, scanner and settings pages without a script error and in euros. **Not tried**: with the
settings password set (the padlock and its prompt), a page left open during the change.

**The shops' prices** (since 2026-10-24; `core/shop_prices.py`: `import_prices`, `rows_from`, `each_price`;
`server/card_data.py`: `start_shop_price_update`, `shop_prices_status`, guarded `POST /api/prices/update`, the schedule
below; `tests/test_prices.py`: `ShopPriceFile`, `ShopPricesInTheCardData`, `ShopPriceImport`, `CurrencyChange`). MTGJSON
(MIT; README, Acknowledgments) publishes every shop's price of the day in one file, keyed by its own card ids:
`AllPricesToday.json.xz` (4.3 MB) and two files mapping them to Scryfall ids, `csv/cardIdentifiers.csv.xz` (11 MB) and
`csv/tokenIdentifiers.csv.xz`. An update first asks `Meta.json` for MTGJSON's date: the date of the prices in use means
nothing is downloaded (`NothingNew`; the button sends `force` only from code, never from the page). The date recorded is
the price file's OWN (`file_date`: its `meta.date`), never `Meta.json`'s - the two are published and cached apart (a
thirteenth Codex review: yesterday's file saved under today's date made every later update "nothing new"). A file not
newer than the prices in use is not saved (the next update looks again), an older one is refused, and a file newer than
those in use but older than `Meta.json` says is saved as what it is - the next update, seeing `Meta.json`'s other date,
downloads again. Then the three files go
into a temporary folder, the price file is read one card at a time (`raw_decode`: `json.load` of the whole file peaked at
~580 MB), the identifiers row by row, and the faces of a double-faced card (one Scryfall id, a uuid per face) are merged
by union - they never disagreed (the plan, *Measured*). Kept: Card Kingdom's retail and buylist, Mana Pool's retail, paper
only; TCGplayer's and Cardmarket's come from Scryfall (one shop, one number), cardhoarder's are MTGO's. The rows replace
the table whole (`replace_table`: refused when empty or much smaller than the table in use - the prices in use stay), under
the card data's import lock (`_import_lock`: a card data download applies the chosen source to its new cards before its
swap, and must not see the shops' table change in between - an update during one fails and is asked again). When a shop's
source is shown, its prices are applied in the swap's own transaction (`replace_table`'s `also`, `_reapply_in`: a failure
rolls back the table and its date with it, so the next update downloads again instead of finding "today's prices are in
use"), and the entries are priced again - after every update that brought new prices, whatever the source is by then.
**Never left unpriced** (the third and fourth Codex reviews of 2026-10-24): `reprice_pending` in `data/settings.json` holds
one entry per change the entries must follow (`begin_price_change`: a card data download, a shops' update, a repricing
itself), `running` from BEFORE it begins, `done` once it is in (`price_change_done`; dropped when nothing was swapped
in). A repricing forgets only the entries that were done when it began, and only once both inventories are priced - so a
change of source during a download (its repricing runs from the old table) no longer swallows the download's own
repricing, as a single flag did. While an entry is done, an update that finds nothing new still reprices; at start every
entry counts as done (`resume_price_transition`). A shops' update whose repricing fails is reported as failed ("tried
again at the next update"). Settings > Card data > Prices shows MTGJSON's
date, when it came and how many printings, and the button *Update the shops' prices* (guarded: when a shop is the source
it rewrites every entry's price); while one runs the page asks every 2 s how far it is. **Measured 2026-10-24** on a copy
of this checkout's card data (112,765 printings): the import in 5.6 s (download 3 s), peak RSS 199 MB for the whole
process; 102,652 Scryfall ids with a price, 99,435 of our printings; Card Kingdom prices 94,253, Mana Pool 98,649
(TCGplayer, from Scryfall, 97,312); after a card data download (116,418 printings, tokens included) 96,979 and 101,770 -
the new printings joined without a new price download. Applying a shop's prices to the shown columns: 0.55 s. Against
TCGplayer's price of the same printing (printings of $1 or more): Card Kingdom median x1.21 (p10 0.68, p90 1.84), Mana
Pool median x0.74 (p10 0.33, p90 1.04) - MTGJSON's numbers as published, none compared with a shop's own page. **The
trial** (a server on copies, port 5077): Card Kingdom refused before the first update (409), the first update 102,652
printings; $5,986.52 (TCGplayer) -> $7,975.43 (Card Kingdom, 10 entries without a price) -> $4,773.89 (Mana Pool) ->
exactly $5,986.52 back at TCGplayer; a card data download with Card Kingdom chosen kept its prices shown and the total
($7,975.43); Cardmarket -> €5,228.69 (16 entries without a euro price) and back to exactly $7,975.43; a second update the
same day downloaded nothing. The Settings page without a script error. **Never tried**: the schedule's own run, a page
open during an update, the memory on a Raspberry Pi.

**Prices follow the card data** (since 2026-10-23; `server/card_data.py`: `reprice_collections`, `Game.current_prices`,
`InventoryManager.priced_entries` / `reprice`; `tests/test_prices.py`). An entry keeps its own price (`inventory.price_usd`),
taken when it is added; before this date it never changed after that. Now every successful card data download (the button
or the schedule) prices again the entries of the collection and of the scanned cards that know their printing (`card_id`):
`inventory_fields(card, finish)['price']` of the new data, in one transaction per inventory, then `inventory_prices_updated`
(the pages reload their totals). Left alone: an entry without a printing (a CSV import of an unknown one), a printing gone
from the data or without a price today (it keeps the one it has - Scryfall has no USD price for about 14% of the printings),
an entry edited between the computation and the write (the `UPDATE` asks that the printing and finish are still the same),
the digital collection (no prices, on purpose) and other people's collections (their prices are what they offered). A
failure is logged and leaves the old prices; the download counts as done either way. The prices are worked out
outside `maintenance_barrier` and written inside it (a full backup never copies half of it). `scripts/setup_database.py`
(no server) does not price again: the next download by the server does. Copies an open trade holds are
priced too (its triggers refuse only deletes and lower quantities). An etched foil is a `foil` copy (`suggested_finish`):
`inventory_fields` takes the foil price, then the etched one, then the regular one (regular copies: regular, foil, etched) -
before, an etched-only printing's copies went in at 0. Tried on copies of this checkout's databases (2026-10-23): 1,594 of
1,595 entries priced, 0 changed - the data had not changed since they were added. **First run after a real download
(2026-10-24)**, on a trial server with copies of this checkout's databases (own data folder, port 5077), card data from
2026-10-05 replaced by Scryfall's of 2026-10-24 (116,416 printings, 29 s from the request to `database_update_complete`):
1,452 of 1,595 entries priced again, none set to 0, one raised from 0 (an etched-only Lathril, Blade of the Elves: $1.52, its
etched price); new / old median 0.97, 1,154 of 1,451 within 20%, the extremes 0.38 and 2.47; the collection's value $5,986.52
-> $5,678.30; `inventory_prices_updated` sent. The new data: 1,218 printings with an etched price (all 892 etched-only
ones), 87,837 with a EUR price. **Not watched**: a page open during it, the scheduled update.

**Update check.** 10 s after startup and then once a day, `Game.check_for_update()` runs for
each game with data. Magic: Scryfall's bulk data description (one small request) - since
Scryfall republishes every day for prices, the data only counts as outdated once it is
`database.update_after_days` (7) older than Scryfall's, or when its date is not recorded (data
downloaded before this check existed). A result
is kept in `data_update_notices`, sent as `database_update_available`, and returned by
`/api/stats`; the page puts a dot on the Database counter (click → confirm → update) and shows
one notification per page load. Updates are not started without the user unless the automatic update below is on (it is off by default).

**Automatic updates** (since 2026-10-22; `server/card_data.py`, `tests/test_update_schedule.py`, plan:
`docs/plans/UPDATE_SCHEDULE_PLAN.md`). Built like the automatic backup, not like cron: no clock time, but a thread
(`run_update_schedule`) that asks every 10 minutes (`SCHEDULE_TICK`) whether something is DUE - so a laptop, an
AppImage or a Pi that was off when it was due catches up once it runs again. Nothing is downloaded in the first
5 minutes after start (`SCHEDULE_FIRST_DOWNLOAD`: a network that is not up yet); as the ticks are 10 minutes
apart, the first automatic download comes about 10 minutes after start. Each tick (`schedule_tick`) asks the update check
(when a day has passed), the card data, the picture index and the shops' prices in that order, each in its own `try`: one
failing never keeps the others from their turn.
- **The card data** (`scheduled_card_data_updates`, `card_data_due`): every game with data (the first download stays
  startup's, with its own retries) whose `card_data_info.downloaded_at` is the chosen number of hours old or older - a
  press of the button counts too - is downloaded again (`start_card_data_update`: the same safe swap, scanning goes on).
  The interval is the interval: the 7-day rule of the notice above is not asked (daily means fresh prices daily). An
  automatic attempt is noted in `data/settings.json` (`card_data_auto_last`: `at`, `ok`, `message`) BEFORE the download
  starts, so a server stopped in the middle still counts it; how it ended is written by `on_done`. A failed one is not
  tried again for an hour (`AUTO_RETRY_AFTER`), also across a restart. A download the button started between the
  question and the start is not the schedule's: the last real attempt is put back.
- **The picture index** (`scheduled_index_update`, `index_due`) already follows the card data (`extend_index_after_update`),
  so its schedule is a RETRY of what is still missing - a build Scryfall refused half-way, one stopped, one that failed -
  at most once per the chosen hours: only when an index exists (never a first build), it covers at least 90% of the
  printings (`INDEX_AUTO_MIN_COVERAGE`: a first build stopped early stays the button's - hours and ~12 GB), nothing is
  building and no card data download runs (its success extends the index itself), and `index_status()` counts something
  missing. A printing Scryfall serves no picture for stays "missing" and is asked for again at each run - the interval
  is what bounds that. A build that never began (another process holds the index: `BuildRunning`; or the button was
  first) puts back the last real attempt (`image_index_auto_last`), so the next tick asks again (a Codex review of
  2026-10-22: the first version used up the interval - up to a week - on a build that never ran).
- **The shops' prices** (`scheduled_shop_price_update`, `shop_prices_due`; since 2026-10-24): when the prices in use came the
  chosen number of hours ago or longer (or there are none), no update and no card data download runs, and no automatic
  attempt was made in the last hour (`shop_prices_auto_last`). MTGJSON's file of the day was out by 06:13 UTC on
  2026-10-23 and -24 (its FAQ says 9:00 AM EST): a try before it finds MTGJSON's date unchanged, downloads only
  `Meta.json` and leaves the prices as old as they were, so the next look comes an hour later - never at every tick.
- **The settings**: `card_data_every_hours` (0, 24, 72, 168, 720), `prices_every_hours` (0, 24, 72, 168; no `config.yaml` key - off until chosen) and `image_index_every_hours` (0, 6, 24, 168) in
  `data/settings.json`, else `config.yaml`'s `database.auto_update_every_hours` / `reading.index_retry_every_hours` (both
  0). Any other value - a hand-edited `true`, `"24"`, 48 - is off, never a guess. Settings > Card data
  and Settings > Card data: a select each, and a line with the last automatic run and the next
  (`GET /api/updates/schedule`, open; `POST`, guarded - `parse_update_schedule` checks every value before any is saved).
  The times are sent with the server's own offset (`astimezone`: a server in Docker runs in UTC) and shown in the
  browser's zone.

Tested: `tests/test_update_schedule.py` (stand-ins: nothing is downloaded); the routes and the two cards in a server on
copied data and headless Chromium. **First live run, 2026-10-22** (a server on a copy of the card data from 2026-10-05 and the index of 2026-10-20, schedule "every day", index retry off): started 09:31:10, update check at 09:31:20, the automatic download at 09:41:20 (the first tick after 5 minutes), 116,357 cards in by 09:41:28; the index extended itself after it (`extend_index_after_update`, 3,592 new pictures, all 116,357 covered by about 09:47); the page's line then said last run ok, "116,357 cards", next 2026-10-23 09:41. No error in the log. One run: the index RETRY itself was not exercised live (its schedule was off; nothing was missing after the extension). **The retry's own live run, the same day** (a server on a copy of card data from 2026-10-12 and its index, card data every day, "The picture index follows" OFF, the retry every 6 hours): started 12:12:18; the automatic card data download at 12:22:28 (116,357 cards at 12:22:37) and, the switch being off, no extension - 3,592 printings without a picture; at the next tick, 12:32:28, the retry started on its own ("automatic update of what is missing (every 6 h)"), published the extended index at 12:38:30 - all 116,357 covered - and noted the run (ok, "3592 new pictures", next 18:32). No error in the log. Never tried: a month-long run, a Pi whose network comes late.
A phone downloading the index meanwhile: see *What happens when the index changes during a download* (the listing says when it is changing).

## The card dropper

**Since 2026-10-22: the station's code, and a mechanism designed, its first parts printed, never run** (`station/dropper.py`,
`station/station_client.py`; plan: `docs/plans/PRODUCT_PLAN.md`, phase 5; the mechanism: `SilentKernel81/card-dropper`, a project of its own since 2026-10-30 - six
silicone-tyred wheels under the stack, two axles driven by servos through one-way bearings, roll the bottom card out
under an adjustable gate; a Raspberry Pi Pico turns each pulse into one card's feed, and keeps a pulse that comes during
a feed for right after it - its plan is in that repository). A station can release the next card itself by pulsing one GPIO pin of its
Raspberry Pi; what the pin drives (a servo's driver, a relay, a solenoid's transistor) is the mechanism's business - one
pulse means one card. Off unless switched on for a camera (Settings > Cameras > This camera > Card dropper).

**When a card is released** (`Station.release_next_card`, always in the background):
- **auto-add on**: once the server has ANSWERED the capture's upload, and not with `card_back` (`Station.after_upload`,
  from `send_until_settled` on an accepted upload; the upload item carries `release_session`, in memory only - never in
  its note, so a capture sent again after a restart owes no card). The card-back check is the server's and runs before
  anything else for a station's capture: released at queue time, the dropper buried the face-down card meant to stop
  the stack, and went on feeding for as long as the server was away (a Codex review of 2026-10-22). No answer (the
  server away), a refused or a set-aside upload: nothing is released - the feeding waits;
- **auto-add off**: the release is *owed* for that capture (`drop_owed` = its `capture_id` and session) until the server says
  THAT capture is settled - `desks.review_done`, sent (`review_done`, with the `capture_id`, to `Station.on_review_done`)
  on Add of the live card (not of a review-queue item), on the person's Skip, and when the card went to the review queue
  by itself; NOT when "not found" dismisses itself (`dismiss_card` with `keep_capture`: the picture kept for a manual
  search) - the dropper waits, and the card found by that search and added settles it (the next review);
  never when reading or adding it failed, a card back stopped the camera or the game changed. `card_under_review` going
  back to False pays nothing: the server clears it on those errors and stops too (a Codex review of 2026-10-22). The
  server remembers each shown capture's id under the capture's OWN picture (`Desk.capture_ids`,
  `desks.remember_capture_id` in `stations_api.station_capture`, mode `review`; an error forgets it), and Add / Skip
  settle the picture of the card actually SHOWN (`card['capture']`, else the camera's `pending_capture`), a capture
  queued for review its own - never "the latest capture", which a later one replaces while the earlier is still shown
  (a Codex review of 2026-10-22). A manual Capture that replaces an automatic capture on the page (as it always did)
  leaves that capture unsettled: the dropper waits - "Drop one card", or stopping and starting the scanning, goes on;
- **auto-scanning switched on**: the first card - only while this session has had no capture and none is coming (a capture
  under way, or a card in view not captured yet: `Station._still_wanted`, `first`); such a card brings the next one by its
  own capture, and the start's card as well would be two cards for one capture, one dropped onto a card being captured.
  The new session begins, and what was pending is cleared, BEFORE scanning is switched on, both under `release_lock`
  (`Station.on_set`), and a capture reads its session under the same lock (`_capture_session`, which also notes
  `last_capture_session`): a capture that starts the moment scanning is on belongs to the new session (a Codex review of
  2026-10-22). A stop and restart DURING a capture releases nothing - that capture is the old session's and the start's
  card waits for it - so the feeding waits there ("Drop one card" goes on): never two cards. Connecting (also again after a
  lost connection) never releases one;
- each release first waits for a focus probe or a refocus sweep to end (`DROP_WAIT_FOR_FOCUS`, 20 s; a sweep takes
  about 8 s) and is dropped when auto-scanning was stopped or the camera went meanwhile;
- one release runs at a time; one more asked for meanwhile is kept and runs right after it - a card captured while the
  previous pulse was still on its way (pulses may last 2 s, auto-capture can take a card after 1 s) owes its next card
  all the same (a Codex review of 2026-10-22: refusing it stalled the feeding for good); a third is refused, and
  stopping auto-scanning drops the one kept;
- every release belongs to the **scanning session** that asked for it (`Station.scan_session`, one more each time
  auto-scanning is switched on or off, and when the dropper is switched off - a release waiting then cannot come back
  when it is switched on again; other changes while it stays on cancel nothing). The last check is made ATOMICALLY with the
  pin going active: `Dropper.pulse` enters the station's gate (`Station._still_wanted`, under `release_lock`, which every
  cancellation also takes) after opening the line and sets the pin inside it - a stop or restart falls wholly before the
  check (refused) or after the pin is active (the card already moving); a check, then the line opened, then the pin, left
  a gap a stop and restart fell into (a Codex review of 2026-10-22, pinned by a test that holds the line's opening).
  `Dropper.pulse` also looks at `enabled` again once it holds its own lock - the one `configure` changes the settings
  under - so a switch-off between its first look and the lock activates nothing (the next review; the test button has
  no gate) and is refused right before its pulse once another session has begun - a release
  still waiting for the focus when scanning was stopped and started again would otherwise pulse beside the new session's
  first card: two cards, no capture between (a Codex review of 2026-10-22, reproduced and pinned by a test). A
  capture's session is the one it STARTED in (`_auto_captured` takes it first): a capture still being taken when
  scanning was stopped and started again releases nothing and owes nothing (the next review, reproduced too);
- the debt is recorded BEFORE the upload exists: `_auto_captured` makes the capture's id itself and hands it to
  `queue_upload`, so the server's `review_done` - possible as soon as the upload is sent - always finds it (recorded
  after, a quick answer was lost and the feeding stopped). The debt is set, paid and cleared under `release_lock`;
- **while the station's Socket.IO connection is down, no card is released** (`Station.dropper_synced`, false from the
  disconnect to the end of the next `hello`): uploads may still get through over HTTP while a stop cannot reach the
  station, so a release that comes up then is KEPT (`release_deferred`, set by the gate) and decided after `hello`. The
  server REPEATS every stop in each `hello` until the station's own report says it is off (`RemoteScanner.stop_unsent`,
  cleared in `_take_state`; a start cancels it - a newer command - and is never replayed itself, the station refusing one
  on connecting all the same). "Off" applied to a station that is off changes nothing, so repeating is safe, and a lost
  `hello` reply or a live stop sent into a dropping connection is not lost (the next review: crossed off when the hello was
  built, a lost reply lost the stop). `hello` applies it through `on_set` - a new session, the kept release stale (a Codex
  review of 2026-10-22: a stop during an outage was followed by more cards). A card back seen over HTTP during the outage stops the station the same way when it reconnects.
  A `hello` belongs to the connection it was started for (`Station.connection`, one more at every connect and disconnect)
  and puts the station in step only if that connection is still the current one - a disconnect while its answer is being
  applied is not undone by it; and a `hello` that fails is asked again while its connection lasts (`HELLO_RETRY_DELAYS`:
  1, 2, 5, 10, then every 30 s) - else the feeding waited on a healthy connection for ever (the next review);
- **the scanning switch is made in one place, under `release_lock`**: `on_set` reads the old state, moves the session and
  writes the new state there, and `apply` never writes `auto_capture_enabled`; the first card of a start is released for
  the session THAT start began (`after_set(started)`). Written again outside the lock, a start paused there undid a stop
  that came meanwhile, switched scanning back on and released a card (a Codex review of 2026-10-22);
- **the server's settings are applied one at a time** (`Station.settings_lock`, held by `on_set` and by `hello` while it
  applies its answer): a `hello` whose connection has ended is refused under it BEFORE it changes anything. Checked only
  after applying, an older `hello` answering late switched the dropper back on after a newer connection's `hello` had
  switched it off (the next review);
- **every value the server sends a station is numbered** (`'_revision': [server start, n]` in each `set` and in `hello`'s
  answer, the newest change it includes; `RemoteScanner._revision`, `SERVER_START`), and the station applies, setting by
  setting, only a value at least as new as the one it has (`Station._newer_only`, `settings_revisions`). The lock alone
  orders what is applied, not what was SENT: a `hello` answer built before a live "dropper off" and applied after it
  switched the dropper back on, on the same connection (the next review). Per setting, so a delayed change of one
  setting hides no newer change of another; a new server start begins its numbers again and the station starts afresh;
  a server that numbers nothing has everything applied, as before;
- **a waiting stop is confirmed by its number, not by "off"**: `stop_unsent` holds the stop's own number, and the
  station's report says which scanning change it last applied (`state()['auto_capture_revision']`, read before the
  switch itself); only a report of "off" with that stop's number or a newer one crosses it off (`_take_state`, under the
  numbering lock). A plain "off" crossed off a stop that never arrived: an idle report, delayed, came after the start
  and the lost stop (the next review). A station that reports no number never confirms: the stop is repeated in each
  `hello` until a start - harmless;
- a `review_done` sent while the station is away is not lost: `RemoteScanner.review_settled` keeps the last settled
  capture and `hello` repeats it at every connection (`Station.hello` -> `on_review_done`). Repeating is harmless - only
  a debt for exactly that capture is paid, once (a Codex review of 2026-10-22). Not covered: a *server* restart in that
  window (it is kept in memory) - stopping and starting the scanning, or "Drop one card", releases the next card then. A card that is not captured releases nothing, so the stack can never run
  on by itself. A card back
  releases nothing (auto-add on: its upload's answer; auto-add off: no `review_done` for it).

**The pin**: libgpiod 2 (`gpiod`, LGPL-2.1), imported only when a pulse is due - a PC station, or one without the package,
runs as before and the page says why the dropper cannot work (`Dropper.error`, reported in the station's state as
`dropper_state`). The line is requested inactive (requesting it never releases a card) and set inactive again after
every pulse, also when the pulse fails. On a Raspberry Pi 4 and 5 the 40-pin header is `/dev/gpiochip0` and the GPIO
(BCM) number is the line's offset - read on 2026-10-22 on both (Pi 5: pinctrl-rp1, 54 lines; Pi 4: pinctrl-bcm2711, 58
lines; `/dev/gpiochip4` is the same chip under its older name); the chip stays a setting.

**Settings** (`dropper.checked`, the one place their rules are written - the server before saving, the station before
using; `enabled`, `chip` `/dev/gpiochipN`, `pin` 0-63, `pulse_ms` 10-2000, `active_low`; on needs a pin): saved per
camera (`remote_scanner.CAMERA_SETTINGS` `dropper`), sent to the station when changed and when it connects (`DECIDED`).
Events `set_dropper` (answered `dropper_updated`; refused whole, the page goes back) and `test_dropper` ("Drop one card",
answered `dropper_tested`) - not guarded, like the camera's other settings.

**Images**: the station's requirements take `gpiod` on 64-bit ARM only; the Pi-camera image Debian's `python3-libgpiod`
(it runs privileged, so it reaches the chip). A USB-webcam station in Docker needs `deploy/docker-compose.client-gpio.yml`
laid over its compose file (the chip as a device; a PC has none, so it is not in the default file).

Tested: `tests/test_station_dropper.py` (76 tests, a stand-in pin and camera: the settings' rules, the pulse, a pin that
cannot be opened or fails half way, every moment above, a capture during a 2 s pulse, a stop and restart while a
release waits and while a capture is taken, a `review_done` arriving as the upload is queued, one sent while the station was away (repeated on reconnecting, paid once), settling a shown card while another capture is read, a manual capture during an automatic review, a card-back answer and an absent server through the real upload code, the dropper switched off and on while a release waits, a stop and restart while the line is being opened, a switch-off between the pulse's first look and its lock, "not found" dismissing itself, a capture starting the moment scanning switches on, a card captured before the start's card goes, a release and a stop during a connection outage, a lost `hello` reply, a disconnect while a `hello` is applied, a stop while a start is still being applied, an older `hello` answering after a newer one, a live change overtaken by an older `hello`'s answer, a delayed "off" report from before a start, a `hello` that times out, an error that clears the review flag, `review_done` on Add / Skip but not for a queue item or a failed Add, the server's events). The page tried in headless Chromium on
copied data (on without a pin refused, on with GPIO 17 saved, the test refused with no station connected). **Never
tried**: a real pin, a mechanism, a card released by it - and whether it damages cards (try commons and sleeved cards first).

## Focus

USB cameras start in **continuous autofocus**, unless a focus position has been locked. Measured
on an Anker PowerConf C200 looking into the box, continuous autofocus settled at a position
about 4× less sharp than the best manual position, and re-hunts whenever the image changes -
so a card dropped at the wrong moment can end up blurry.

Because the camera-to-card distance is fixed, the scanner can **lock** the focus instead:

- **Refocus** (button, `reset_focus` → `CardScanner.refocus`, on a station through the `command`
  message): switches autofocus off and runs
  `focus_sweep()` - a coarse pass over the camera's `focus_absolute` range (step 50), then a fine
  pass (step 10) around the best position, scoring each position by the sharpness of the card
  (or the image centre when there's no card); finally a parabola through the best position and
  its neighbours predicts the peak between the fine steps, which is measured and kept if sharper.
  On the C200 the sweep found 444 against a measured peak of 446 (without the parabola: 440, 4%
  less sharp). A lens move takes ~0.4 s to show up in the frames
  (lens + camera buffer), so each position waits 0.45 s; if re-measuring the chosen position
  doesn't confirm it, the sweep repeats with 0.8 s. About 10 s in total. The position is saved
  (`focus_value`, per station - on the server) and restored when the station starts.
  A station without a position of its own is given the one in the server's shared settings;
  a camera whose lens cannot be set from the station (a Pi camera, a webcam without the focus
  control) ignores it and reports continuous autofocus (`_open_camera`) - until 2026-10-12 it
  took the number over and its page showed autofocus as off. Checked with fake cameras only.
- **A saved lock that does not fit the camera, and a camera that crashes on it** (2026-10-19).
  The position is kept per *station*, not per camera, so after another webcam is plugged in the
  saved one (the Anker's 440) is another lens's. A lock outside the camera's own
  `focus_absolute` range is **not applied** (logged; continuous autofocus). And a webcam that lists
  the control but resets itself when the lens is set - the LX-260325-A "USB 2.0 Camera" (range
  0-15): a USB disconnect and a new device number a second later, v4l2-ctl "Protocol error",
  uvcvideo "Failed to query (SET_CUR) UVC control 6" - is remembered the first time it does so
  (`_focus_reset_the_camera`; its USB ids and name in `data/camera_quirks.json`, kept across
  restarts) and treated as a camera without a focus control: continuous autofocus, no lock, sweeps,
  refocus or drift check (`focus_range` is `None`, `_run_v4l2_command` skips lens writes). Other
  controls are still sent. Measured on that camera (2026-10-19): streaming at 1920×1080 and the
  other controls are fine, and only the lens write resets it. The lock is still one per station
  on the server; one per camera is not done. `tests/test_camera_quirks.py` (fake camera and v4l2-ctl).
- **The lens has play**: the same `focus_absolute` reached from above measured up to 5× blurrier
  than from below (395: 22 vs 118, peak 2,480). Sweeps measure while moving up, and every final
  or restored position is approached from 30 below (`_move_focus`).
- **Refocus when the sharpness drops** (`_check_sharpness_drop`, `auto_capture.refocus_on_drop`, default
  0.35, since 2026-10-15; with a locked focus only): the sharpness of each captured card is noted
  (the last 24); when the last 3 were all below that fraction of the median of the ones before them,
  and that median was at least 600 (a soft baseline, a pile of plain tokens, says nothing), the
  station refocuses with a sweep (~8 s, as "card out of focus") and starts the history again; not
  more than once a minute; 0 switches it off. A per-camera setting (`CardScanner.refocus_on_drop`,
  `set_refocus_on_drop`, the `set_refocus_on_drop` event, Settings → Cameras → Refocus when the
  cards get blurry; `config.yaml`'s `refocus_on_drop` is the default). Why: on the Pi 5's Anker C200 the camera's own
  continuous autofocus left stretches of captures at about a quarter of the usual text sharpness
  (21:16-21:19 about half, 21:35 351 against 1,200-2,200) that never came near `min_sharpness`,
  the only trigger there was. Tested on synthetic sequences (`tests/test_sharpness_drop.py`); not
  yet seen to fire on a real pile.
- **Focus probe while scanning** (`_run_focus_probe`, every `auto_capture.refocus_every`
  captures, default 10; **Settings → Cameras → Check the focus every** changes it while scanning; the count starts from zero each time auto scanning is started - `auto_capture_enabled` is a property that resets `captures_since_focus` on off → on - and is not reset by stopping, so a session of 12 cards with a check every 20 has none, and `tests/test_focus_count.py`): the best position drifts - in one session it moved from 395 to 430 in
  about 45 minutes (lens warming up, pile height), and the text in the captures became ~10×
  blurrier while the card as a whole still passed `min_sharpness`, so the automatic refocus
  never started. In the gap after a capture (~1 s, the image is already taken) the probe
  measures the card here and one step (10) away and keeps the sharper position (> 5% better);
  an improvement keeps the direction for the next probe, otherwise the next one tries the other
  way. Near the peak the sharpness changes ~3× per step, far more than the noise. Probes
  approach their positions from only 15 below (instead of 30) to keep the card readable.
  The interval was 3 captures until 2026-10-06: in a session of 489 captures the 163 probes
  moved the focus 5 times (420 ↔ 430 ↔ 440, 1.12-1.99× sharper), OCR had read all 9 cards
  before each move, and a capture followed by a probe held the next one back 0.9 s (2.5 s
  to the next capture instead of 1.6 s). Every 10 captures still looks about every 20 s,
  far more often than the position moves (one step in 10+ minutes).
- **While the lens moves** (sweep or probe, and 0.6 s after) the new-card rules are paused: the
  blur can hide the card for a few frames and shift its outline, and the "reappeared elsewhere"
  / "card gone" rules then took the same card for a new one (a probe caused two duplicate
  captures in a live session, reproduced in simulation: 22 captures for 15 drops). A real drop
  during a probe is still recognized by its jump (> 3%; the blur shifted the outline ≤ 1.9%) -
  in fixed-area mode by the area changing > 8 in 2 frames in a row: the card counts as new
  once the focus is done, and the probe's measurement is discarded. Otherwise the card in view
  becomes the reference for "looks different from the captured one": after a probe a foil's
  glare and outline changed enough (thumbnail 0.34, other cards 0.39-0.62) that a foil was
  captured twice. In fixed-area mode only when the area is still within 10 of the capture.
  The "dropped during the probe" flag is cleared at every capture: when the dropped card was
  taken as new another way ("card gone"), the flag used to survive and made the *next* card
  "new" right after its own capture - that card was captured twice (seen 2026-09-24 and 09-25).
  Still open: a probe itself sometimes reads as a drop right after a capture ("card dropped
  meanwhile" with the same card, 2 of ~630 captures), and a card that shifts ~2% right after
  its capture (image change 0.34) can't be told from a real drop - real drops of other cards
  often measure 0.30-0.42 with jumps under 3% - so that threshold stays.
  Simulated with 30 drops every 1.5 s and a peak 35 away: every card captured once, focus at
  the peak after 9 cards.
- **Automatic refocus** (`_check_focus_drift`): with a locked focus, a card that stays still but
  below `auto_capture.min_sharpness` for 3 s triggers a new sweep (at most every 15 s) - the pile
  grows toward the camera as cards are added.
- During a sweep the status shows *Focusing* and auto-capture pauses; new-card detection is off
  until 0.6 s after it (the heavy blur changes the card image like a drop would).
- **Settings → Camera autofocus** (`set_autofocus`) returns to continuous autofocus and forgets
  the locked position; switching it off runs a sweep.

Cameras without a `focus_absolute` control (and the Pi camera module) keep their own autofocus.

### Pi camera module

`camera.type: picamera` (`_initialize_picamera`). The sensor runs at its full resolution and
only `camera.crop` of it (fractions x1, y1, x2, y2 of the whole image, in the station's
`config.yaml`) is read out, pixel for pixel: a wide lens sees far more than the box, and the
cropped frames are small enough to be used as they are for detection, the live view and the
capture (no half-size decoding). Without a crop the whole image is scaled to
`camera.resolution`. Autofocus is continuous, over the whole lens range, measured inside the
crop. The frame rate is what the sensor's full-resolution mode gives, not `camera.fps`.
A rotation of 180° is done by the camera (the crop is mirrored to stay on the same spot) and
the frames arrive in RGB order; 90° / 270° are turned per frame as for other cameras. Changing
the rotation reopens the camera (`reopen_camera`, done by the capture thread).

The camera also delivers a small copy of each frame (640 px on its longer side, the
detector's working size; `current_small`): the outline is searched there (`_detect_outline`, corners scaled back to the frame) and the debug trace
saves it. Scaling the full frame down for the detector had taken half of its 33 ms.

**Frame counts and frame rate.** "Card gone" - no outline for 6 frames - was measured at 20
frames a second, where it is 0.3 s. For the Pi camera it is counted as that time at the rate
the station really runs at (`_frames`: 4 frames at 14 a second, never fewer than 3). The still
frames before a capture are *not* shortened: this camera's autofocus is still settling after
a drop, and a replay with fewer still frames captured one card twice. USB cameras are paced
to `camera.fps` and keep their numbers.

Tried on 2026-10-11, a Raspberry Pi 4 with a Camera Module 3 Wide NoIR (IMX708, 4608x2592,
102° wide) about 19 cm above the bottom of the box, crop `[0.33, 0.08, 0.67, 0.75]` =
1566x1736 px:

- Frame rate: the camera gives 14-15 a second in this mode. Turning the image by 180° and
  reordering its colours per frame took 24 ms of a 70 ms frame on the Pi 4, and with outline
  detection (40 ms) the loop missed every other frame: 7 a second in the first session of 15
  drops, 1-3 s from drop to capture. With both done by the camera: 14.2 a second (12.2 with
  the debug trace on, 10 with a 90° rotation) - measured on the empty box, not yet over a
  session of drops.
- That session (15 cards, ~140 lux, 60 ms exposure): every card captured once and confirmed by
  OCR, the ★/• markers right on the six looked at by eye. Three cards waited 9-18 s: for two
  no outline was found (the card's lower edge in the shadow of the box wall) until the
  autofocus rescanned by itself; the third is unexplained.
- Second session (17 cards, camera lowered and turned, ~1,700 lux, 7.7 frames a second with a
  card in view, the trace on and the live view watched; the Pi at 75 °C): 15 captured and
  read by OCR; one lay 17 s without an outline - its left edge against the shadowed wall of
  the box - and was captured by hand (read by the AI from the whole frame); and one, the
  third copy of a card, was **never captured**: it landed 0.4% from the copy before it, the
  fall hid the card for 3 frames (0.4 s), and "card gone" asked for 6. This led to the two
  changes above. Replaying the session's trace frames through `CardScanner` (a fake Pi camera
  at the recorded pace) reproduces the loss with the old count and captures the card with the
  new one, with the same captures otherwise; the first session's frames replay the same with
  both. The replay is on 640 px trace frames, not the camera's own.
- With the small frame from the camera: 14.4 frames a second on the empty box, also with the
  trace on and the live view watched (61 °C).
- Third session (17 cards, the changes above in place; 10.9 frames a second with cards, the
  Pi at 77 °C): all 17 captured once, the first 13 about 2.3 s apart. Three of the last four
  waited 11-27 s until the box was shaken: the card lay against a wall, its outline was found
  in about every other frame, and six still frames in a row never came. That led to the
  detector's gap closing (step 7 of [the outline detector](#card-detection)).
  Replaying the session with it captures those cards 1-2 s after they land, with no capture
  added. Replays of the first session (camera further away, frames smaller than the detector
  saw them live) show two repeat captures with it, where the outline of a still card dropped
  out for a moment and where the autofocus rescanned by itself - both can happen live.
- Fourth session (the same 17 cards, gap closing in place): 17 captures in 38 s, 2.4 s a card,
  none waiting, all read by OCR; the count of each card and of its foils is that of the pile
  (2, 2, 2 with 1 foil, 3, 8 with 2 foil), so none twice and none lost. The Pi at 70 °C.
  One session: the repeat captures the replay warned of have not been seen, nor ruled out.
- The detector with a card in view took 67 ms a frame on the Pi 4 (16 ms on the empty box),
  so with cards the station fell back to 7.7 frames a second. Three of its helpers were made
  cheaper without changing what they compute (`_card_inside_box` skips specks by their
  bounding box, `_outline_bands` works on the outline's surroundings instead of the whole
  image, `_perimeter_coverage` without a Python loop), and the camera's small frame is now
  exactly the detector's working size (no rescaling): about 40 ms, and 13.9 frames a second
  with a card in view. Checked on all 2,452 recorded frames (Pi and USB camera), alone and
  following the previous outline: every outline and score identical to before.
- **In Docker** (target `client-pi`, `deploy/docker-compose.client-pi.yml`): Debian 13 with Raspberry
  Pi's package archive for `picamera2` / libcamera - its keyring package is fetched over HTTPS
  from the archive's package list, because the key file offered for download is signed with
  SHA-1, which Debian 13's apt refuses. The container runs privileged with `/run/udev`
  mounted: a Pi camera is a chain of devices (sensor, image processor, picture memory) whose
  numbers differ between models. The image is 1.33 GB and built in a few minutes on the Pi 4.
  Tried: set up through its page, connected, 14 pictures a second, pictures taken from the
  page. No session of cards has run from the container yet.
- **Heat**: with a heatsink the Pi 4 ran at 77-79 °C while only watching the box, 1-3 °C under
  the point where it slows itself down. It was never seen throttling, but it has no margin.
- **Container against the Pi's own Python** (`scripts/benchmark_station.py`, the same camera,
  crop and card in view, two runs each, alternating, 20 s a phase):

  | | Python | Container |
  |---|---|---|
  | Scanning, frames a second | 14.3, 14.2 | 14.3, 14.4 |
  | ... processor (100% = one core) | 93%, 119% | 92%, 93% |
  | Scanning with the live view, frames a second | 14.3, 14.0 | 14.3, 14.3 |
  | ... processor | 140%, 165% | 138%, 139% |
  | Detector alone, ms a frame (afresh / following) | 22.6 / 32.3, 22.5 / 32.1 | 25.1 / 34.7, 23.0 / 32.6 |

  No difference beyond what two runs of the same thing differ by: both run the same Debian
  packages on the same kernel, and a container adds no layer between a program and the
  processor. 14.3 is the sensor's limit in its full-resolution mode.
- A card on the bottom of the box is 637x891 px, about 10 px per mm; a manual capture of it
  was confirmed by OCR (name, number, set, foil marker) in 0.5 s. One card, once.
- The lens: sharpest for that card at lens position 0, the far end of its range, where things
  a metre away stay blurred - on this module the range lies closer than its scale says. The
  bottom of the box is at its edge; a pile brings the cards into it. Not looked into further.
- Sharpness (Laplacian, the card's area) was about 200-250 there, around the
  `min_sharpness` of 250 that auto scanning asks for - a number measured with the USB webcam.

## Collection page and decks

**The decks are pages of their own since 2026-10-13** (`/decks`, `/decks/<id>`; before, a tab
of the collection page). What follows about decks describes what they do, which did not
change; how they look did. *The list*: a tile per deck with its commander's picture and
colours (`GET /api/decks`: `commander_cards`), filter and sort above; the other two tabs hold
"Build around a card" with "Commanders you own", and the preconstructed decks. *A deck*: a
banner (the commander's picture, name, format, legality, cards, value, share owned), the
charts in one strip, and the cards in one of two views (`decks.js`: `showDeckView`,
`deckGroups`) - **Columns** (`deckRowHtml`: a decklist in as many columns as fit; pointing at
a line shows the card beside it and the line's buttons) and **Stacks** (`deckCardHtml`: the
cards themselves, overlapping, one stack per group; pointing at one pulls it out) - grouped by
type, by cost or by colour (`groupOf`). The buttons are the same in both
(`entryActionsHtml`): one copy more or less, the printing, move to main / maybe, make
commander. Adding cards - search, suggestions, popular decks - is a panel that slides in
(`showAdding`); buy list, duplicate and delete are behind a menu. The view, the grouping and
the list's tab are remembered in the browser. Made for a screen with a pointer: on a phone
nothing can be pointed at, and the pages were not laid out or tried there.
**The scanner page's timers and handlers** (since 2026-10-16): `everyWhileVisible` (`scanner.js`) runs the detection
poll (500 ms), the stats (5 s), the camera link (15 s) and the picture-shape check (1 s) only while the tab is
visible and once at once when it comes back; the detection poll never has two requests open. The printings and
similar-card lists hold their value in `data-printing` / `data-similar` with one delegated click handler (a card
named `A\B` or `It's` broke the old `onclick="f('...')"`), and `escapeHtml` takes null / undefined / numbers.
`scripts/check_scanner_page.py` tries these in headless Chromium against a server on copied data that knows a
station called `check`. Not done: the inventory modal still rebuilds every row on an update (not measured as a problem).

`scripts/check_deck_pages.py` tries the pages in headless Chromium (on a server with copied
data only: it creates and deletes decks).

**Scanned cards and the collection are two inventories.** Scanning - every station - adds to
`scan_inventory` - a second `InventoryManager` on its own file, `data/scan_inventory.db`, with
the same tables - and its top bar counter, inventory window, edit / delete, Undo, export, import
and "Clear all" work on that one only (`?area=scan` on the `/api/inventory*` endpoints,
`inventory_area()` in `server/inventory_api.py`; `/api/stats` reports it as `inventory` and the collection as
`collection`). So a scanning session can be checked, corrected or thrown away without touching
the collection. **Add to collection** (`POST /api/scan_inventory/to_collection`,
`InventoryManager.take_from`) moves every scanned entry of the active game - or, with a camera
chosen in the list, that camera's copies - into the collection
(`inventory` in `cards_database.db`): entries that exist there get the copies added, tags are
joined, and the capture thumbnails follow (their rows move, the files stay). Both pages ask
first, with one dialog (`addScannedToCollection` in common.js; `GET` on the same address gives
the number of cards waiting, the locations in use - offered in a dropdown, the ones named after a deck under a "Decks" heading - and the decks' names): a **location** chosen or typed there (JSON
`location`) is given to every card moved, in place of the one it was scanned into; empty keeps
those. It commits the
collection first and then empties the scanned cards - two files, so two commits. A crash
between them must not leave the cards in both (a second "Add to collection" would double
them): the move is first noted in the scanned cards' file (`pending_moves`: game, a move id),
the id is written to the collection (`arrived_moves`) in the commit that brings the cards, and
the note goes in the commit that empties the scanned cards. On startup
`finish_interrupted_moves` finishes a move whose id arrived and drops the note of one that
did not (the scanned cards are then still waiting). An error while copying rolls the
collection back. Decks, statistics and "owned" only look at
the collection; the collection page shows a notice while scanned cards are waiting.

**Batches** (`inventory_batches`, since 2026-10-14). Which copies of an entry came in together
is one row per batch and entry: `batch` (an id, unique for each time cards came in - two in the
same second are still two), `inventory_id`, `added_at`, `quantity`. A batch is one "Add to
collection" (`take_from`: one for the whole move, also with a camera chosen), one import file
(`import_entries`, `import_csv`, `replace_all`), the cards of one precon deck added at once, or
one scanned card (`add_card`; `new_batch()` + `batch=` to make several cards one). An entry's
rows never add up to more than its quantity; copies no row accounts for were there before
(shown as "Added before <time>"). They follow the copies: a split (`_copy_with`) and a merge
(`update_card`) move the **newest batch's** copies first - as the newest captures go - and a
lowered quantity, an undo (its own batch first), a station's copies taken out or a removed
camera count (`_take_copies`) take from the batches the same way (`_take_from_batches`,
`_trim_batches`). The collection page filters by batch ("Added <time> (n cards)", from every
entry's `batches`) and, with one chosen, offers **Remove this batch**
(`POST /api/inventory/remove_batch`, JSON `batch`; `InventoryManager.remove_batch`): each
entry loses only the copies that batch brought, with their newest captures and the cameras'
counts; entries with no other copies are deleted. The cards are deleted, not moved back to the
scanner. `added_at` / `added_quantity` in an entry's JSON are its newest batch's (0 copies: all
of them were there before); the entry's own `added_at` column (the page's "Last added" sort) and
`added_quantity` column are still written, and `added_quantity` is no longer read. The table is
made on startup and, once (`inventory_batches_1`), filled with the one batch each entry knew of
(`old:<added_at>`) - nothing is filled where the table has rows already, as the standalone
program's had. A backup holds the table (`backups.INVENTORY_TABLES`); one made before it gets
the same one batch per entry when it is restored (`rebuild_batches`). `tests/test_batches.py`.

### Trades

Cards promised to someone stay in the collection until the trade has happened
(`trades.py`: `Trades`, made on the collection's `InventoryManager` - its connection, its lock;
tables in [Database](#database)). **Set aside for trade** on the bulk bar asks for a name
(`POST /api/trades`, JSON `name`, `ids`): the open trade with that name, whatever the case, or
a new one, takes every copy of the selected entries that no trade holds yet. A list row has
the same as its own button (⇄, `setAsideForTrade(card)`), for one card without ticking it. Nothing in the
inventory changes: the cards are still owned - totals, statistics and decks count them - and
their rows get a **Trade: name** badge (`/api/inventory` gives each entry `trades`:
`[{id, name, quantity}]`, `Trades.by_entry`); `trade:name` in the search field finds them.

The **Trades** tab (`GET /api/trades`; `collection.js`: `loadTrades`, `renderTrades`,
`tradeAction`) lists the open trades with their cards, value and date. Per card: **−** / **+**
change how many copies the trade holds, **×** takes the card out
(`PUT /api/trades/<id>/cards/<row>`, JSON `quantity`, 0 = out). Per trade: **Export…**
downloads its cards in one of the game's export formats (`GET /api/trades/<id>/export/<format>`
- Moxfield's collection CSV for Magic, or the app's own; `quantity` is the copies in the
trade), **Rename** (`PUT /api/trades/<id>`), **Cancel trade** (`DELETE /api/trades/<id>?action=cancel`: the
trade and its rows go, the cards are simply free again) and **Confirm trade**
(`POST /api/trades/<id>/confirm`, `Trades.confirm`; what is confirmed is the trade the person looked at: the page keeps
the `fingerprint` of the trade on the screen when Confirm was pressed, reads the trades again, and if that trade changed
meanwhile it shows the new list with a warning and asks nothing - the dialog shows only totals, under which a swapped card
would pass unseen (a second Codex finding) - so the person looks again and presses Confirm again; the server gets the
fingerprint that was seen - `Trades.fingerprint`, in `GET /api/trades` for each open trade: a digest of every
card given (row, entry, copies, the entry's printing / finish / condition / location) and received (row, seller, card,
copies), never the price, which a repricing changes daily - compared inside the confirm's transaction and refused when the
trade holds anything else by then; totals alone missed a card swapped for another, a Codex finding. The fingerprint is
required: a confirm without one - a page from before it, which sent nothing or only its totals - is refused with 409
"reload it" before anything is looked at, so no old tab can skip the check (a third Codex finding)): in one transaction each row keeps the
card as it was and lets go of its entry, the copies leave the collection - the entry is
deleted or lowered, with the newest photos and the cameras' counts as for any lowered quantity
(`_take_copies`, `_trim_sources`, `_trim_captures`) - and the trade becomes `done`. It stays
under **Confirmed trades** as a record (cards, value, date; it can still be exported) until
**Delete from history** (`DELETE ...?action=forget`). The two never stand in for each other (since 2026-10-24,
`docs/plans/TRADES_REVIEW_PLAN.md` part 1): a cancel of a trade confirmed meanwhile is refused ("confirmed meanwhile: it
stays in the history"), a forget of an open one too ("cancel it instead") - before, the route fell back from cancel to
delete, so a tab still showing a confirmed trade as open removed its record when Cancel was pressed. A `DELETE` without
`action` (a page from before) is a cancel. Receiving cards (`others_api`) and changing their copies tell the other pages
(`collection_updated`), and an answer says the copies that went in, not those asked (they are cut at what the other
person has).

**Sale picture…** (open trades only - a confirmed trade's cards have no entry, so no scans;
added 2026-10-24; `collection.js`: `openSalePicture`, `drawSalePicture`, `drawSalePreview`,
`saveSalePicture`, the dialog `#sale-modal` in `collection.html`) draws a picture for a sale post
in the browser, on a canvas: nothing on the server is involved but the pictures it already
serves. The trade's cards are looked up among the collection's entries (`/api/inventory`'s
`captures` and `details.image_uri` - fetched again while the Arena collection is shown, whose
entries are other cards). Each scan of an entry is a tile to tick, only the newest ticked: a
picture shows each card once, its caption saying how many copies the trade holds (`×16`) - an
entry scanned 16 times would otherwise fill two pictures with one card; an entry with
no scan gets Scryfall's picture of its printing in the `large` size, asked for with CORS
(`crossOrigin = 'anonymous'`: without it the canvas is "tainted" and cannot be saved). Scans are
loaded as their large copy (`/captures/<file>?size=full`); one answered with the 400 px
thumbnail (no large copy kept) is marked **low res** once it has been drawn. A large copy is loaded
only when its card is drawn (`saleImage`) - the page shown or a page being downloaded - never when
the dialog opens, and those of the cards not on the page shown are let go after each drawing: at
most nine held, plus a download's own (a Codex finding: a trade of a few hundred scans loaded them
all, ~4 MB each decoded). Measured on a trade of 155 scans: 9 large copies loaded on opening,
8 more per page turned, never more than 9 held. "Download all" lets go of each page's pictures
once its file is saved (the pages to come keep only their cards and turns): on the same trade
all ticked, 18 files, never more than 9 pictures held by the download, none at its end. Nine ticked tiles make one picture, 3 per
row: each card fitted into a 859 × 1200 px cell (63:88) with its name (bold, shrunk or cut to
fit) and set / number / a finish other than the usual / the copies under it, 48 px between cells. Saved as
JPEG (quality 0.92), shrunk to 2048 px on its longest side (what Facebook keeps) or at full size
(about 2770 × 4240 px for nine cards); "Download all" saves each picture as its own file. A download never saves the preview's canvas
(redrawn on every change of page, choice or turn - a drawing still waiting for its pictures can be
overtaken, and the file would hold another page's cards under this page's number, a Codex finding):
the cards, their turns, the page's number, the choices and the trade's name are taken when the
button is pressed and drawn on a canvas of the download's own (`exportSalePicture`,
`saleSnapshot`, `saleOptions`); a dialog closed meanwhile saves nothing. A
click on a card in the preview turns it 180° (scans are kept as the camera saw them, some
upside down) - only in the picture, the scan is not changed. Checked on copied data in headless
Chromium (two pictures from twelve scans, a Scryfall fallback saved without a tainted-canvas
error, a thumbnail-only scan marked; a trade of nine entries of 14-20 real scans each: one picture, every name under its own scan); never posted to Facebook Marketplace.

While a trade holds copies, the database refuses everything that would take them: deleting the
entry, lowering its quantity below what is held, moving a whole stack of several copies to
another location or merging the entry into another one by an edit (both delete the entry; a
single card is changed where it is and stays in its trade), "Remove this batch", clearing
the inventory, an import that replaces it. The page shows "These copies are set aside for a
trade: take them out of the trade first" (`TRADE_HELD`; `server/trades_api.py`: `write_refused`). Copies the
trade does not hold can be changed as always, and so can condition, tags and price. Bulk
delete and bulk move, (one edit since 2026-10-14: all entries or none) are refused before anything changes when
one of the entries is held. Trades are in every backup (`backups.INVENTORY_TABLES`): a restore
brings back the trades of that moment with their entries - a trade confirmed since is open
again, its cards back - and a backup from before trades restores with none.

Never tested: two browsers changing one trade at the same moment (each change is one
transaction under the collection's lock, so the second sees the first's result or is refused).

### Other people's collections

Added 2026-10-19 (not deployed when this was written). On the **Trades** tab, *Other people's
collections* imports someone else's collection file under a name - to browse it, to put its cards
in a trade as something the trade **receives**, or on a **buy list** - without touching the user's
collection.

- **Apart from everything the user owns.** `core/others.py` (`Others`) keeps them in
  `data/others.db`: `other_collections` (a name per game, unique in any case), `other_cards`
  (the printing, quantity, condition, finish and price of each row; rows of the same card in a
  file are added up) and `buy_list`. An id there is **not** an id of the collection: the only
  routes that take one are in `server/others_api.py`, which never calls an inventory, and the
  routes that change the collection take none of them. A card leaves as a snapshot in the shape
  the pages and exporters know (`others.card_dict`, JSON in `trade_receives` / `buy_list`), so
  **deleting an import changes no trade and no buy list**.
- **Formats** (`others_api.read_collection_file`): the app's own export (`inventory.read_collection_csv`
  - the loop `import_csv` reads with, now shared, nothing written), Moxfield and **ManaBox**
  (`Magic.import_rows`; the printing by ManaBox's Scryfall id when the row has one and it is that
  card, else by set code + number, else by name). The ManaBox reader was written from what its
  export is known to look like (Name, Set code, Collector number, Foil normal / foil / etched,
  Quantity, Scryfall ID, Condition near_mint ...) and **was never tried on a real ManaBox file**;
  it also means the user's own *Import* accepts ManaBox. Any other file is refused with the list
  of formats. A name already in use asks to replace (its cards are swapped in one edit) - and a
  replacement is refused, the old cards kept, when any row of the file cannot be used (cards not
  found, rows without a name or with an unknown finish), as the inventory's own replace does.
  Receiving refuses cards of another game than the active one (a page left open while the game
  was switched), in the route and in `Trades.receive`.
- **Receiving.** `Trades.receive` puts cards in the open trade with that name (made when there
  is none - a trade can receive without giving anything). The copies add up to what the other
  person has (`most`) and no more. A trade lists both sides and both values (`receives`,
  `receive_quantity`, `receive_value`); `trade_receives` (collection file, `ON DELETE CASCADE`)
  is in the backups with the trade (`backups.INVENTORY_TABLES`). **Confirming a trade adds
  nothing to the collection** - the received cards stay in its record, and the user adds them
  by hand (a choice made with the user, 2026-10-19). `GET /api/trades/<id>/export/<fmt>?side=receive`
  downloads the received cards.
- **Buy list.** One list, grouped by seller, with copies capped at what the seller has, totals,
  and an export (whole or one seller, `GET /api/buy_list/export/<fmt>?seller=`). Kept until the
  user empties it.
- **Backups.** `others.db` is in the *full* backup (`backups_api.full_backup`) but not in the
  collection's, scanned cards' or decks' backups: it is not the user's cards.
- **Routes:** `GET /api/others`, `POST /api/others/import` (multipart: file, name, replace),
  `DELETE /api/others/<id>`, `GET /api/others/<id>/cards?q=&sort=&page=&size=`,
  `POST /api/others/<id>/receive` (name, items [{row, quantity}]), `POST /api/others/<id>/buy`,
  `GET` / `DELETE /api/buy_list`, `PUT /api/buy_list/<row>`, `GET /api/buy_list/export/<fmt>`,
  `PUT /api/trades/<id>/receives/<row>`. The page: `collection.js` (`loadOthers`, `openOther`,
  `loadOtherCards`, `loadBuyList`, `receiveCardHtml`).
- **Tested:** `tests/test_others.py` (the store, receiving, the buy list, both import formats
  through the routes, ManaBox rows, the full backup) and `tests/test_trades.py` (backups with
  and without `trade_receives`); the page was tried in headless Chromium against a throwaway
  server (import, browse, search, buy, receive with the dialog, steps) - not against real data,
  not on a phone, and no ManaBox file.

### Backups

They are on the settings page, **Backups** (see [The settings page](#the-settings-page)).
**Back up now** (`POST /api/backups`, `backups.create`) writes `data/backups/<date_time>/`:
`backup.db` with plain copies of `inventory`, `inventory_captures`, `inventory_sources`, `trades` and `trade_cards` of the collection
(`collection_*`) and of the scanned cards (`scanned_*`), `decks`, `deck_cards` and an `info`
row (time, note, counts) - every game - and `captures/`, hard links to the thumbnails those
entries point at (no extra space; they survive the app deleting its own). It is written to a
`.tmp` folder and moved into place, under the managers' locks. Since 2026-10-13 a backup
also holds the digital collection (`arena_inventory`, `arena_arena_account`:
`ARENA_TABLES`; `arena` in its info counts the cards). Restoring a backup that has no such
part - every one made before - leaves the digital collection as it is; the full backup
takes `data/arena_inventory.db`. (On temporary files in the tests; not tried on a running
server.)

**Automatic backups** (`backups.create_scheduled`, marked `daily` in their info whatever the
interval) are asked for at startup (`initialize_components`, note "Application start") and
every ten minutes while the app runs (`run_backup_schedule`, note "Automatic") - a server stays
up for weeks, and a backup made only at startup would never come. One is made when the last
automatic backup is as old as the interval; none while nothing has changed since the newest
backup of any kind (`fingerprint` in a backup's info: a hash of every row it holds), and none
of an empty collection - both decided before anything is written or cleared away, under the
managers' locks. The interval and how many are kept are set in the drawer
(`POST /api/backups/schedule`; `backup_every_hours` - 0 off, 1, 6, 12, 24, 168 - and
`backup_keep`, 1-60, in `data/settings.json`; default every day, the last 7); older ones are
deleted when a new one is made, not when the number is lowered. A failure is logged and does
not stop the app. Backups made by hand are never deleted automatically.

**A full backup** (`POST /api/backups/full`, `backups.create_full`, used by
`scripts/backup.sh` while the server runs) is everything at one moment: the three database
files (SQLite's backup), hard links to the pictures their rows name (capture thumbnails, review
images, captures waiting to be read) and the settings files, in
`data/backups/full/<date_time>/` with a `manifest.json` (rows per table, pictures, the ones
missing, `verified`). It is taken holding every manager's lock (in the order `take_from` uses)
and `maintenance_barrier`, which a capture being settled and the clean-up of old pictures hold
too - so a card on its way to the collection or a capture being added is in none of the
snapshots or in all of them; the files are opened and checked after the locks are let go. The
last 2 are kept. `scripts/backup.sh` (which runs with `umask 077`: its archive holds the API keys, so the archive is 0600 and `~/scanner-backups` 0700, the older ones tightened on the next run - `tests/test_backup_script.py`) then archives those snapshots with the rest of `data/`
(without a running server it snapshots each file on its own, which is the same when nothing
runs). Bringing one back is done by hand with the server stopped (INSTALL.md). Tested on
temporary data (`FullBackup`: opened in another folder, an interrupted move in it is finished)
and against an isolated copy of the server; **not tested**: restoring a whole server from one.

The backups of the list above are in
`data/backups/`, on the same disk as the data: against a lost disk, download a backup - the
arrow beside it, `GET /api/backups/<id>/download`, `backups.archive`: a zip of its folder
(`<id>/backup.db`, `<id>/captures/`), packed into a temporary file. **Upload a backup
file** (`POST /api/backups/upload`, `backups.add_archive`) takes such a zip in again, from this
server or another: it only joins the list (marked `uploaded`, kept like one made by hand) and is
restored like any other. The file is not trusted: exactly one backup folder, `backup.db` and
captures with plain names, at most 2 GB unpacked (counted while unpacking, not as the file
claims), a `backup.db` whose `info` and tables read; a backup of the same time already there is
refused. It is unpacked into a `.tmp` folder and moved into place.
(`scripts/backup.sh` archives everything.) Covered by `tests/test_ownership.py`
(`ScheduledBackups`); the ten-minute timer itself and the drawer's controls were not tested.

**Restore** (`POST /api/backups/<id>/restore`, `backups.restore`) first makes an automatic
backup of the current state ("Before restoring ...", the last 5 are kept - never clearing away
the backup being restored, which may itself be the oldest of them), then replaces the
rows of each table (the columns the backup has; row ids are kept) and links missing
thumbnails back. Collection, scanned cards and decks are committed one after the other - the
collection and the decks are two connections to one file - so a failure part way leaves the
earlier parts restored; the automatic backup has the state from before. The automatic backup
and the replacement are one critical section - the route holds the maintenance barrier, then
`restore` holds every manager's lock from before the backup is made until the last table is
in place (`tests/test_restore_locking.py`): a card accepted in between would be in neither the
backup nor the restored tables. A capture arriving meanwhile waits and is added to the
restored state. Every page reloads its inventory (`inventory_updated`). Card data, the review queue, the stations and settings are not
part of these backups: copy the server's `data/` folder for everything (`scripts/backup.sh`
does that for an installation without Docker).

`/collection` (`templates/collection.html`, `static/js/collection.js`) works on the active
game's inventory over the REST endpoints; it listens to `inventory_updated`, `inventory_undone`
and `inventory_prices_updated` to follow what is scanned meanwhile, and reloads on `game_changed`.
A change to a trade is announced as `collection_updated` (`server/trades_api.py`: `collection_changed`, no
payload), which only this page listens to: a scanner page takes `inventory_updated` for a card
that was just added and would drop the card it is showing.

**Inventory tab.** `/api/inventory` adds to every row its `location`, `tags` and `details` from
`Game.card_details` (Magic: image, mana value, color identity). Filters (text,
color identity, type, rarity, set, finish, location, tag, price), sorts, the list / image grid
and the statistics are computed in the browser from that one response. The text field looks
for what is typed anywhere in name, set name, set code, type line, rarity, location and tags;
a term `field:value` (`collection.js`: `SEARCH_FIELDS`, `parseSearch`) looks in one place:
`set:` is the whole set code when the collection has a set with that code (`set:HOB` does not
find "Hobbiton"), otherwise part of the set's name; `name:` and `type:` are part of the text,
`rarity:` its beginning, `tag:`, `loc:` / `location:`, `finish:` and `number:` the whole value
(`loc:""`: no location), `qty:` the number of copies (`qty:>4`, `qty:<=2`, `qty:3` - the
entries with spare copies), `trade:` part of the name of a trade that holds copies. Quotes
keep spaces together, a minus in front turns one term around
(`-set:HOB`), and a word with a colon that names no field stays ordinary text. **Not** turns
the whole field around. The filters are kept in the browser (`localStorage`: `collectionFilters`,
`saveFilters` / `restoreFilters`) and are there again on the next visit - all but the "Added"
batch; a set, tag or location that is gone from the collection is
not filtered by, and **Clear filters** can only be pressed while something is filtered. What
narrows the list is also shown as chips above it (`activeFilters`: "Rarity: rare ×"), each
taken off with a click, and is written into the page's address (`FILTER_PARAMS`:
`/collection?q=qty%3A%3E1&rarity=rare&colors=G`; `history.replaceState`, so no history entry
per filter) - an address with filters, a bookmark, wins over the remembered ones. A click on a
row's rarity, finish, location, tag or trade badge filters by it, a second click takes that off
(`filterByBadge`). Type, Rarity, Set, Finish,
Location and Tags are dropdowns with ticks (`MULTI_FILTERS`, `multi`, `renderMulti`,
`fillMulti`, `passesMulti`): several values can be ticked - a card shows when it has *any* of
them - and a **Not** tick at the top of the list turns that around (every card with none of
them). A list of more than 12 values has a Find box. Each is one chip ("Not Set: Alpha, Beta"),
and is written into the address as `rarity=rare|mythic&rarity_not=1` (the values joined by a bar:
a set's name can have a comma; `type`, `rarity`, `set`, `finish`, `loc`, `tags`), so a bookmark
or a saved filter with one plain value still works. A row's badge ticks only that value (a
second click lets go). The one-tag list ("Any tag") stays beside the Tags dropdown. The Arena
view does not apply Location or Tags. `tests/test_multi_filter.py`. A list row shows the card twice: on the left what was captured (a click opens the captures),
and by its buttons the downloaded picture, small (`.card-peek`; Scryfall's `small` size of the
`image_uri`) - resting the pointer on that one shows the picture large beside it (`data-image`,
`showPreview`, `placePreview`, as for the deck builder's rows; devices with a mouse - the box
is not there on touch screens and narrow windows). The rest of the row shows nothing: a
picture that came up anywhere in the row was in the way. The large box appears at once,
card-shaped, and the picture when it has loaded; the previous card's picture is dropped first. The
list is shown in pages of 25 / 50 / 100 / 200 entries (100 until chosen, `collectionPageSize`;
`showPage`): a changed filter or sort starts at the first page, a reload after an edit stays
on the page. A tick with Shift held (`pick`) ticks or unticks every entry from the one ticked
before to this one, in the order shown and also across pages. **Export…** asks which cards
when some are ticked or the list is filtered - everything, the ones shown, or the ones selected
(`POST /api/export_inventory/<format>` with JSON `ids` answers with the file of those entries;
the `GET` is everything, as before).

**Undo.** A row's bin and every bulk action (delete, move, tag, condition) wait `UNDO_SECONDS`
(6 s) before the server hears of them (`changeLater`): the rows are greyed, a bar at the bottom
says what is about to happen and has **Undo** (also Ctrl+Z), which simply drops the change.
When the time is over the change goes to `POST /api/inventory/bulk` (`sendPending`). It is
never left behind: the page's `fetch` is wrapped so that any other write waits until the
pending change has been sent, a second change sends the first (the calls are taken one after
the other, `changesAsked`), and leaving the page sends it on the way out (`pagehide`; the
request is `keepalive`, so it is also finished when the page is left while it is on its way). The single delete no longer asks first; the bulk
delete still does. A change the server refuses (a card a trade holds) is reported when it is
sent, not when it is clicked. Never tested: closing the browser during the six seconds on a
phone.

**Keys** (`inventoryKey`; Inventory tab, no dialog open, not while typing): `/` goes to the
search field (Esc leaves it), Esc clears the selection, ← / → turn the page, Ctrl+A selects
everything shown, Del deletes the selection (asks), Ctrl+Z undoes the waiting change.
Selected entries get the bulk bar (`POST /api/inventory/bulk`). Rows also carry `decks`:
the names of the decks that use the card (by name, `DeckManager.needed_by_name`; a Commander
deck's considered cards don't count) - shown as a badge, and hidden by the **Not in a deck**
tick. A deck lists names, not copies, so the location decides which copies are its own
(`decks_using` in `server/decks_api.py`): when the location named after the deck holds as many copies as the
deck plays, only the entries there count for it and the same card elsewhere is free (the basic
lands in a box, next to the ones in ten precons); with fewer copies there - or no such
location - every entry of the card counts. The deck builder has the same idea as **Not in other decks** on the card search
(`free=1&deck_id=` → `search_cards(exclude_names=)`) and on the suggestions (`elsewhere`). The deck
builder goes by card name, not by copies: a card with three copies owned and one in a deck is "in a deck".
There used to be a second tick, **No use in my decks**, that also hid the cards EDHREC lists for
the commander of one of the decks; it was taken off the filters on 2026-10-14 because it needs the
internet (the page waited for EDHREC) and became **Find cards to trade or sell** on the Trades
tab (`collection.js`: `findSpareCards`, `spareCards`, `renderSpare`): asked by its button, never
on page load; the list is the entries with no deck and no EDHREC suggestion, with the copies no
trade holds, most valuable first, for one location or all (`spare-location`: before the search every location
of the collection, after it those with spare cards and how many); its ticks go to `setAsideForTrade(null, ids)` like the
Inventory's (`GET /api/inventory/suggested` →
`Recommendations.commander_cards` per deck with a commander, matched to the owned names by front
face; asked when the tick is set, one request per deck the first time, then from the 7-day
cache). Decks EDHREC has no answer for come back in `unknown` and are named in a notification.

**Decks** (Magic; a game without `Game.deck_formats` has no Decks tab). A deck (`decks.py`) is a
name, a format and `deck_cards` rows: card name, count, board (`commander`, `main`, `side`) and
a printing id for the image. The card is identified by its name, so any printing owned counts.
Nothing a deck does changes the inventory.

**A deck for MTG Arena** (the deck page's **Arena** button; `GET /api/decks/<id>/arena`, and as
a file `.../export/arena`). Arena, the digital game, makes a deck from a list on the
clipboard (its Decks screen: Import). `games/mtg_decks.py: format_arena` writes that list:
sections `Commander`, `Deck` and, for a 60-card deck, `Sideboard` (a Commander deck's
considered cards are not written); lines `4 Card Name` - names only, no set and number: the
deck's printings are paper ones, which Arena often does not have. Only cards that exist on
Arena are written, and the window names the rest: a card is taken to be on Arena when it is
legal, restricted or banned in a format only Arena has (`ARENA_FORMATS`, `on_arena` - mostly
`timeless`; the card table does not keep Scryfall's `games` list). A two-part name is written
as Arena does as far as known (`arena_name`: split cards and Rooms with both names, adventure
cards and double-faced cards by their front), decided from the type line. Of the laptop's
test decks, paper Commander precons, 66 to 75 of 100 cards are on Arena - Arena has no
Commander, and such a list imports as a Brawl deck at best. The window's Copy works on plain
http too (`copyArena`: `navigator.clipboard` exists only over https or on the machine
itself). **Compared with a deck Arena exported** (2026-10-13, a 60-card deck the user copied
out of Arena): Arena writes the heading `Deck` and lines `1 Llanowar Elves (M19) 314` - the
same heading, and its three adventure cards by their front name, as `arena_name` does. Pasted
into "New deck", that text was read whole by the deck import (60 cards, none unknown, the
adventure cards found by their front name); written back with the Arena button it gave the
same cards and counts, and every card was judged to be on Arena (27 of 27 the card data
knew by name; the three others it has under their two-part names). **Tried in Arena by the user the
same day**: a list of four lines without set and number (`4 Llanowar Elves`, `2 The
Arkenstone`, `1 Beorn, Reluctant Host`, `7 Forest` under `Deck`) was imported; exported
again, Arena had chosen the printings itself (the four Llanowar Elves as one of one
printing and three of another). So names alone are enough, and an adventure card is found
by its front name. **Still not tried**: a whole deck written by the Arena button, the
`Commander` and `Sideboard` sections, a split card, and what Arena says about a card it
does not have.

**The digital collection (MTG Arena)** - since 2026-10-13; plan and record in
`docs/plans/ARENA_COLLECTION_PLAN.md`. A third inventory, `arena_inventory`
(`data/arena_inventory.db`, the same tables once more), holds what the user has in Arena.
Arena gives no list of that; an exporter - the same author's
[mtga-export](https://github.com/SilentKernel81/mtga-export), a separate program for Linux
(Steam / Proton) - writes one while the game runs, and
the collection page's **Arena** view uploads its files (`POST /api/arena/import`,
`server/arena_api.py`): `mtga_collection.json`, `mtga_decks.json`, or both - each replaces
its own part (the cards; the decks Arena brought) and leaves the other. The cards are
stored **without a price** and the Arena view shows none (`priceText`; no value in the
summary or the statistics): what a paper printing costs says nothing about a digital card.
The filters the view hides - price, location, tag - are not applied there either
(`applyFilters`), or a minimum price remembered from the paper view would empty the list.
`core/arena.py` reads them (`read_collection`, `read_decks`; anything else is refused -
`NotAnExport`) and finds each entry's card (`find_card`, `resolve`): by Arena's set and
collector number **only when the card there has the entry's name** (fronts compared),
else by name. The reason, measured on the one export there was (1,972 entries): 1,891 are
the printed set's number, but Arena numbers the basic lands of one set its own way (its
Forest LCI #400 is the printed set's Mountain), 26 are *rebalanced* cards ("A-Ancestral
Katana": the number of the card they change - skipped, as the exporter's own totals do),
and 49 are in Arena-only sets the card data lacks. Everything is read and looked up before
anything changes; then `InventoryManager.replace_all` swaps the contents in one
transaction, with the account (`arena_account`: the export's date, wildcards by rarity,
gold, gems, how the import went) written in the same one. **An import replaces
everything** - Arena has the original - and the list is **read only**: the page hides
what changes a collection (`body.arena-view` in `collection.css`), its handlers refuse
(`collection.js`: `inArena`, `toggleSelected`, `changeLater`, `setAsideForTrade`), every
write of the page names its area (`areaQuery()`), and the server refuses a write to
`?area=arena` (`inventory_api.py`: `digital_collection_is_read_only`,
`CHANGES_AN_INVENTORY` - a new route that changes an inventory belongs in that set). The
second and third are not decoration: an Arena entry's id sent without its area is an id
of the *paper* collection. `GET /api/arena` gives the numbers of the page's bar; an
import or a restore sends `arena_updated` to every page (no data; the collection page's
Arena view and the deck pages read again).

**Decks are of two kinds**: `decks.kind` is `paper` (Physical on the pages; every deck
from before) or `arena`, and `decks.arena_id` is Arena's id of a deck an import brought
(migration `deck_kind_1`). The kind says which collection a deck counts against
(`decks_api.py`: `collection_of`): owned copies, the other decks that want them
(`needed_by_name(kind=)` - a paper and an Arena deck never compete), the buy list, the
card search (`?kind=arena`), EDHREC's suggestions. An Arena deck's basic lands count as
owned (`is_basic_land`: Arena gives them freely); what it lacks is counted in wildcards
(`wildcards`: `needed` by rarity from `arena.wildcards_needed`, `have` from the account) -
the rarity is the CARD's (`CardDatabase._CARD_RARITY`, since 2026-10-29): the lowest of
common / uncommon / rare / mythic among its Arena printings (`games`), or among all its
printings while the card data has no `games` yet or the card has no Arena printing - before,
it was the rarity of whichever printing stood for the card (a Commander reprint made
Banishing Light, a Foundations common, an "uncommon"); still not checked against Arena itself; and a card Arena does not have is a problem of the deck ("Not on
Arena"), not a wildcard. `DeckManager.replace_arena_decks` replaces, in one transaction,
the decks the last import brought by the ones this one brings (a deck still there keeps
its cover); decks made here, also Arena ones, have no `arena_id` and stay. So a change
made here to a deck that came from Arena lasts until the next import with a deck file.
The deck list filters All | Physical | Arena (`decks.js`: `deckKindShown`); New deck asks
for the kind, and so does **Duplicate** (`POST /api/decks/<id>/duplicate` with `kind`;
`DeckManager.duplicate(kind)`): a copy of the other kind is the same list counted against
the other collection - an Arena deck copied as Physical shows what of it is on the shelf
and what the rest costs to buy (cards cannot be bought singly in Arena, on paper they
can). Such a copy is named "... (Physical)" / "... (Arena)" and is a deck made here. Arena's formats were added for these decks (Historic, Timeless, Alchemy,
Brawl, Standard Brawl - keys of Scryfall's legalities like the others) and any deck can
have them. **"What can I build?"** has the same choice, Build from Physical | Arena
(`decks.js`: `buildKind`, `showBuildKind`): it decides whose cards "Build around a card"
lists (`/api/cards/search?kind=arena`), which collection the two rankings count as owned
(`collection` in the body of `POST /api/decks/ideas/<commanders|card>`, echoed in the
state so results of the other collection are not shown), and the kind of a deck started
there - from a commander of the Arena collection as a Brawl deck. The ranking of
preconstructed decks stays with the paper cards. **The Arena window of any deck** now also answers "can you build it in
Arena?" (`arena_check`, `check` in `GET /api/decks/<id>/arena`; `decks.js`:
`arenaCheckHtml`): copies already in the Arena collection, the cards to craft and their
wildcards beside the ones the account has, and how many copies are of cards Arena does
not have. **Measured** (test servers, copies of the laptop's data, the user's export):
3,061 cards in 1,946 entries, the exporter's own totals, the same count for every card
name; three decks in, fully owned; each file imported alone; `scripts/check_arena_pages.py` 32 of 32 (on copied
data only: it imports, and makes and deletes a deck). **Not tried**: a sideboard or a
commander in the exporter's deck file, another version of the exporter, the wildcard
counts against Arena; of "What can I build?" for Arena, the results of the two rankings
(they ask EDHREC and Archidekt - only that they start for the right collection). The
user looked at the pages and imported through the page's button in a real browser
(2026-10-13, a preview server on copied data).

**A deck's cover** is the card whose picture stands for it: the deck list shows every deck as
that card, and the deck's banner has its art behind the name. `decks.cover` holds the name of
the card chosen (the **Cover** button among a card's buttons; `PUT /api/decks/<id>` with
`cover`, `''` to give the choice up) - a column added on 2026-10-13 by the named migration
`deck_cover_1` (`storage.rebuild`: the file copied first, every deck compared before and
after; tried on a copy of the real database - 15 decks and 969 deck cards unchanged). What is
shown is `deck_covers` in `server/decks_api.py`, in the answers as `covers`: the card chosen
while it is in the deck; else the commanders in the order they were added - a deck with two
shows the first, and a button turns to the other (which one is showing is the browser's to
remember, `decks.js`: `coverIndex`, `turnCover`); else the deck's most valuable card that is
not a land. A card taken out of the deck stops being its cover without anything being
written. `deck_payload` in `server/decks_api.py` puts together what the
page shows:

- card data: one printing per name (`CardDatabase.cards_by_names` - the newest one that has an
  image and exists non-foil, so foil-only inserts and collector editions are not the default)
  and the cheapest price among all printings, which is what the deck and buy-list totals use.
  The image shown is the entry's own printing (`deck_cards.card_id`): the search result
  clicked, or the printing a precon / Moxfield / Archidekt list names (`scryfall_id` in
  `resolve_entries`). The set code + number button on a deck row opens the printing picker
  (`GET /api/cards/printings?name=`: every printing, the ones owned first; choosing one sends
  `printing` to `POST /api/decks/<id>/cards`). The printing only decides the picture - any
  printing owned counts as owned;
- `owned`: copies in the inventory over every printing, finish and location
  (`InventoryManager.owned_by_name`), and `elsewhere`: other decks with the card
  (`DeckManager.needed_by_name`) - the page shows *owned*, *shared* (owned, but other decks
  want more copies than there are), *n of m* or *missing*;
- `issues` from `games/mtg_decks.check_deck`, which reports and never blocks:

| Format | Checked |
|---|---|
| Commander | exactly 100 cards with the commander; one copy of each card; every card within the commanders' color identity; `legalities.commander`; a commander is a legendary creature (or says it can be one); two commanders need Partner, Friends forever, a Background or Doctor's companion |
| Standard, Pioneer, Modern, Legacy, Vintage, Pauper | at least 60 cards; at most 15 in the sideboard; at most 4 copies over main deck and sideboard (1 when restricted); legal in the format |

  Basic lands and cards that say "A deck can have any number of cards named" have no copy
  limit; "up to seven cards named" sets it to seven. A Commander deck's `side` board is a list
  of cards being considered: not counted, not checked, not in the buy list.

Card search for the builder is `CardDatabase.search_cards`: one row per card name, filtered by
name, type, rules text, mana value, rarity, color identity (within the commander's / including
chosen colors), legality in the deck's format and "owned"; the exact name sorts first. The
rarity filter and the rarity shown are the card's (`card_rarity`, above: the Arena printings'
lowest, else all printings' lowest - a `HAVING` after the grouping); until 2026-10-29 the
filter was on the printings, so a card with one promo of that rarity matched and showed that
printing (a Forest was a "rare", Llanowar Elves a "mythic"). Text
decklists (`1 Sol Ring`, `4x Lightning Bolt (2X2) 117`, `Commander` / `Deck` / `Sideboard`
sections, a blank line before the sideboard of a 60-card list) are read and written by
`parse_decklist` / `format_decklist`.

**Deck ideas from other sites** (`recommendations.py`). Every answer is cached in
`data/web_cache.db` - its own file since 2026-10-09 (it was a table of the card database, 138 MB
beside 91 MB of cards, and its writes shared the collection's file): compressed (the same 419
answers are 37 MB), entries older than 90 days dropped, the oldest making room above 200 MB
(`MAX_BYTES`), an answer above 8 MB not kept. The file can be deleted at any time and is in no
backup; a cache that cannot be written only makes the next request slower. At the first start
the old table's answers are copied over and the table dropped (the card database file does not
shrink - its pages are used again). Cached: (EDHREC and the MTGJSON list 7 days, precon lists 90 days, deck searches and
decks 1 day; a 403/404 is cached too), requests to one site are at least 1 s apart (MTGJSON
0.25 s) with a 10 s timeout, and a site that fails or answers in another shape raises
`Unavailable`: that panel says so and the rest works. Nothing here runs while scanning.

| Source | Used for |
|---|---|
| EDHREC `json.edhrec.com/pages/commanders/<slug>.json`, `/average-decks/<slug>.json` | Suggestions for a Commander deck (inclusion % = decks with the card / decks that could play it, synergy), "Start from the average deck", and the commander ranking. A pair is filed under one order of the names; the other order answers with a `redirect` that is followed |
| MTGJSON `DeckList.json`, `decks/<file>.json` | Preconstructed decks (the deck types in `PRECON_TYPES`: Commander, Challenger, theme and intro decks, starter kits, duel decks, Jumpstart packs ...) - the only source that is published for programs |
| Archidekt `api/decks/v3/?commanderName=` / `?deckFormat=`, `api/decks/<id>/` | Most viewed public decks of a commander or format; a deck by its address |
| Moxfield `api2.moxfield.com/v2/decks/search?fmt=`, `/v3/decks/all/<id>` | Most viewed public decks of a format (its search can't be narrowed to a commander by name); a deck by its address. Unofficial - Moxfield may refuse it |

"What can I build?" (`run_deck_ideas`) needs one request per item, so it runs in a background
thread and the page polls `GET /api/decks/ideas/<kind>`: `commanders` ranks the legendary
creatures in the inventory by the share (weighted by inclusion) of their EDHREC cards that is
owned; `precons` ranks the preconstructed decks by the share of their cards owned (only the kind chosen on
the page, JSON `type`, or all of them; one request per list the first time, then cached - about
230 Commander and Challenger lists took about a minute, all kinds together were never timed); `card` ("Build around a card": the page lists the owned
cards legal in a format - `/api/cards/search?owned=1&format=`, with `free=1` for the "Not in a deck" tick and `commander=1` for "Commanders only" (legendary creatures and "can be your commander" cards, offered for formats with a commander). The search has one printing per name; a card that is owned is returned in the printing owned (`InventoryManager.owned_printing_by_name`: the one with most copies), so its image is the card on the shelf. A click shows the card - `chooseAround` - and **Find
decks** starts the run, **Stop** in its place while it runs: `findAround`, `renderAround`) reads the
ten most viewed Archidekt decks of that format with the card (`?cardName=&deckFormat=`, which
can take Archidekt half a minute the first time for a much played card: 45 s timeout) and ranks
them by the share of each that is owned. `POST` starts a run and replaces one that is running;
`POST {"stop": true}` ends it at its next step, keeping what was found - the button that
started a search stops it while it runs.

**A preconstructed deck is shown as a card too** (since 2026-10-13), like a deck of your own.
MTGJSON's list of decks has no pictures and does not say what is in a deck - only each deck's
own file does, about a megabyte apiece and some 1,500 of them. So a tile starts as a plain
card with the deck's name, and asks for its cover when it comes into view (`decks.js`:
`watchPreconTiles`, `loadPreconCovers` - an `IntersectionObserver`, one request at a time,
8 decks each): `GET /api/precons/covers?files=...` (`precon_covers`) reads those decks' files
(`Recommendations.precon`: from MTGJSON the first time, 4 a second, then from the cache for
90 days), and answers with the same choice as for your own decks (`deck_covers`: the
commander - two: both, with the turn button - else the most valuable card that is not a
land), in the printing that is in the box. What was worked out is kept in the server's
memory while it runs. Measured on the laptop, nothing cached: the first 18 covers 6 seconds
after the tab was opened. 60 tiles are shown at once; the rest is reached by typing. A click
on a tile opens the window with the deck's cards, where pointing at a line shows its card
(`/api/precons/<file>` gives each card's `image_uri`).

**Preconstructed decks.** The Decks tab lists them from `GET /api/precons` (one cached request)
with a search and a choice of kind (MTGJSON's deck `type`). `PRECON_TYPES` says which types are
listed and the format each becomes as a deck: printed decks only - nothing that exists only
online, no Secret Lair drops, bundles or box sets. MTGJSON does not name a format, so decks
sold beside a set are `standard` (an old one's page then lists its cards as no longer legal
there) and reprint products `legacy`; a Jumpstart list is one 20-card pack - the Foundations
Beginner Box's ten are of that type - and its page reports it as short of 60 cards. Until
2026-10-11 only Commander and Challenger decks were listed (about 230); now 1,472. The
list and one Beginner Box pack were read from MTGJSON that day; the page's kind filter was
**not tested in a browser**. The ranking only adds the share owned. "View cards" shows a list
(`GET /api/precons/<file>`, `precon_cards`: its cards by board, with how many of each are
owned) and saves nothing - the button was "Open as deck" and created the deck at once, which
left decks nobody asked for. "Create deck" in that window creates a deck from the list
(`POST /api/decks`, `precon`), asking first when a deck of that name exists. "I own it" (`precon_own`) also adds the cards to the inventory: MTGJSON names the printing
in the box (`identifiers.scryfallId`, else set + number, else any printing of the name) and
whether it is foil, so the entries get the right set, finish (`Game.suggested_finish`) and
price; they are Near Mint at the location given (the deck's name by default), which is also how
to find them again - filter by that location to move or delete them. Undo does not cover it.

## The desktop program (AppImage)

`app.py --app` is the server as a program on one person's computer (`server/program.py`; the
launchers `packaging/AppRun`, `scripts/build-appimage.sh`, `.github/workflows/appimage.yml`).
It is the same server, and differs from one on a server only here:

- **The camera station is started beside it** (`program.start_station`: `station.py --server
  http://localhost:<port>`, the same file `scripts/start.sh` starts) and ended with it
  (`stop_station`: SIGINT, ten seconds, then killed - the server never hangs there; what the
  station has not sent is on disk). `--no-station`, or `camera.type: remote`, starts none.
- **Who can reach it**: `flask.host: auto` means the whole network on a server and
  `127.0.0.1` as a desktop program; the switch "Reachable from other devices" (Settings ->
  Program, `POST /api/network_access`, `data/settings.json: network_access`) overrides it and
  applies after a restart (`program.network_access`, `listen_host`). The station's setup page
  gets `SCANNER_SETUP_HOST=127.0.0.1` under the same rule.
- **Where it reaches itself**: the station, the browser and `--quit` use `program.local_url`
  - `localhost` for a server that listens on loopback or on every address, the address itself
  for one that listens on an address of its own (`flask.host: 192.168.1.5` answers there, not
  on loopback). Before the saved settings are read (`--quit`, a second start) both are tried
  (`candidate_urls`).
- **Quit** (`POST /api/quit`): only as a desktop program and only from the computer it runs
  on (a server is stopped with its service or container). `--quit` calls it.
- **Shutdown happens once**: however often it is asked (two tabs, a repeated SIGTERM) one stop
  is scheduled and a second SIGTERM during the cleanup is ignored; a quit asked before the stop
  began cancels a restart.
- **Restart** (`POST /api/restart`, in every mode): the program shuts down - the station
  first - and runs the same command in the same process (`os.execv`; the lock and the port
  are released by it); the page reloads when the server answers again.
- **One copy per data folder** (`data/app.lock`): a second start shows the running one;
  `--app` opens its page.
- **Where its files are**: `paths.USER_DIR` (`~/.mtg-scanner`), see *Configuration
  and files*. With no card data the program starts and downloads it in the background - the
  **first download is tried again** after a failure (1, 5, 15, then every 30 minutes, for as long
  as the program runs: `card_data.start_card_data_update(retry=True)`; an update of data that is
  there is asked for again by the person, not repeated), and every page shows a banner while a
  game has no cards (`common.js: watchCardData`, from `database.total_cards`, `updating` and
  `error` of `GET /api/stats`; the page reloads when the data arrives).
- **The AppImage** holds `app.py`, `station.py`, `config.yaml` and `src/` (OCR reader
  included) under `usr/app/`, the Python under `usr/python/`, Node.js as `usr/app/bin/node`
  (`paths.tool`). Never tried: another architecture than x86_64, a system without FUSE for
  anything but `--appimage-extract-and-run`, a real camera under it.

## Web interface

Three pages, all served by the server (`server/pages.py`), with one header (`templates/_topbar.html`)
and one icon in the browser's tab (`templates/_favicon.html`: `static/favicon.svg`, and
`static/favicon.ico` for browsers that want that - a card's outline, white on the brand
colour, like the header's mark; `/favicon.ico` answers with the same file, for a browser
that opens an address which is not a page). The station's own setup page carries the same
drawing inside its one file:

| Page | Template, script | What it is |
|---|---|---|
| `/` | `stations.html` (inline script) | The cameras: each station with its state and a link to its page |
| `/scan/<id>` | `scanner.html`, `static/js/scanner.js` | One station's scanner page. `window.STATION` tells the script which; a station without a camera gets the page without the camera panel |
| `/collection` | `collection.html`, `static/js/collection.js` | Inventory, trades, statistics, backups |
| `/decks`, `/decks/<id>` | `decks.html`, `static/js/decks.js`, `static/css/decks.css` | The deck list (tabs: My decks, What can I build?, Preconstructed decks) and one deck. One page for both addresses: the script shows what the address says (`showWhatTheAddressSays`) and keeps the address in step (`showAddress`: `history.pushState`), so a deck can be bookmarked, a reload stays in it and Back leads to the list |

`static/js/common.js` and `templates/_dialogs.html` hold what the pages share (text helpers,
in-page dialogs and notifications, the edit dialog, the capture viewer, "Add to collection");
`static/js/library.js` what the collection page and the deck pages share and the scanner page
does not (`$`, `api`, `valueDialog` with `templates/_value_dialog.html`, the card picture
beside the pointer - the scanner's script has its own `$`);
`static/css/style.css` has the dark / light theme (CSS variables).

**The scanner page**: top bar with counters; the camera on the left with the manual search
below it (first the scan, then the search; the search was above the camera until 2026-10-15), card panel on
the right, activity log below; its settings are on the settings page. It polls `/api/detection_status`
every 500 ms for the status pill (and `camera_error`, the message over the video), shows
`/video_feed?station=<id>` (MJPEG: each new frame once), and talks to the server over
Socket.IO. Its socket joins its station's room, and its `/api/` requests carry `?station=`, so
it only sees its own camera - see [A page per camera](#a-page-per-camera). The prompt editor
(a modal) stays on this page; the settings page's "Edit prompts" opens it (`/scan/<id>#prompts`).

#### The settings page

`/settings` (`server/pages.py: settings_page`, `templates/settings.html`, `static/js/settings.js`,
`static/css/settings.css`; since 2026-10-15 - before it each scanner page and the collection page
had a drawer of its own with a different part of the settings). Settings is the last link of the header's lower row, in its right corner (it was a gear button in the top row until 2026-10-16; on a narrow window it stays in the first row, the page's own tabs go below), a link to it
on every page. Seven sections since the redesign of 2026-10-22 (`docs/plans/SETTINGS_REDESIGN_PLAN.md`; five
before it), a list on the left and one at a time on the right (`#overview`, `#cameras`, `#reading`, `#carddata`,
`#backups`, `#storage`, `#server` in the address; the old `#sounds` and `#data` - and a browser that remembered one -
go to Cameras and Backups: `OLD_CATEGORIES`; `/scan/<id>#settings` and `/collection#settings` go to it):

| Section | Holds |
|---|---|
| **Overview** (the default) | One line per section - cameras connected, how cards are read, the card data and its next update, the picture index, the last backup, capture files, the password and network - each a button to its section, the ones to look at marked. No route of its own: each loader hands its part over (`setOverview`) |
| **Cameras** | *This camera*, chosen at the top (its own connection, `?station=`): name, location, status, camera setup / undo last add / forget; Add cards automatically, Stop at a card back, Camera rotation, the fixed area's state (it is drawn on the camera's page), Camera autofocus, Check the focus every, Refocus when the cards get blurry (Off / half / a third / a fifth as sharp: `refocus_on_drop`, per camera, saved in `data/stations.json` like the other camera settings); under Troubleshooting: Debug trace. *All cameras*: Capture size, Sounds (Sound effects, Capture beep, Card added, Volume) |
| **Card recognition** | The three steps, numbered in their order: 1 Picture (read by the picture; in its Details: Add a card only the picture decided), 2 OCR, 3 Vision AI (provider, key, model, Prompts - the summary, and a link to the editor) |
| **Card data** | The card database (state, update), Prices (the price source, guarded; the shops' prices: their date, *Update the shops' prices*), the picture index (coverage, update / stop), Automatic updates (the card database's schedule, "The picture index follows", the index's retry, the shops' prices) |
| **Backups** | Automatic backups (schedule, how many kept); Your backups (make, upload, list: restore / download / delete) |
| **Storage** | Capture files in use, how long received pictures are kept, Clean up now, Compress large copies, Keep camera frames |
| **Server** | Restart Card Scanner, Quit (desktop program only), Reachable from other devices, Settings password, under Troubleshooting: Debug mode |

**The padlock.** Every control the server asks the settings password for carries `data-guarded` in the page (a
backup's Restore gets it in `renderBackups`); `settings.css` draws a padlock after it (`::after`, a mask of the
sprite's `i-lock` - not an icon inside the element, since the script rewrites some of those buttons' text) only while
a password is set (`loadLock` puts `has-settings-password` on the body). A new guarded route or event needs the
attribute on its control.

**Removed on 2026-10-22: "Rebuild database schema"** (Collection and data > Advanced): see *Card data* - every update
already does what it did.

**Debug mode** (Server → Troubleshooting) is two things: the request log (`data/logs/requests.log`) and Werkzeug's
interactive debugger. Since 2026-10-16 the debugger only runs when the server listens on this computer
alone (`program.debugger_allowed`; `services.debugger_running`; the page says which is on) or when the
server is started with `SCANNER_LAN_DEBUGGER=1` - the switch can be reached from the network, and an
error page with a Python console (its PIN goes to the log) would be one step from running code for
anyone on it (an outside code review, 2026-10-16; the real server had it on until 2026-10-15).
Each setting is saved when it is changed, through the routes and Socket.IO events the drawers
used (nothing new on the server side except the page's route). Not carried over: the
"Auto-detection" switch (its state was never read back from the camera; the scanner page
shows "Manual Mode" no more). A scanner page that is open while a setting changes on the
settings page reads them again when its tab is looked at again. `tests/test_settings_page.py`.

Socket.IO events of the pages (namespace `/`; the stations' own connection is described under
[A camera station](#a-camera-station)):

| Page → server | Server → page |
|---|---|
| `capture_card`, `search_card`, `select_printing`, `add_to_inventory` (`finish` + `quantity`, or `items` for several finishes), `undo_last_add` (with `station` from Settings → Cameras: that camera's), `dismiss_card` (`keep_capture` from the automatic "not found" dismissal) | `card_captured`, `card_found`, `card_printings`, `similar_cards`, `card_not_found`, `inventory_updated` (`added`: what was added; `undone`: a station's card taken back; `cleared`: scanned cards were cleared - only the counters reload), `inventory_prices_updated` (prices fetched after an add, or the entries priced again), `price_source_changed` (another price source: its currency; sent by `POST /api/prices/source`), `inventory_undone`, `card_dismissed` |
| `toggle_auto_capture`, `toggle_fast_scan` (add automatically), `toggle_detection`, `toggle_ocr` (read with OCR first), `toggle_ai` (ask the vision AI at all; answers `ai_toggled`; open like `toggle_ocr`: it adds nothing, it only stops asking), `set_reading_mode` (`mode`: cascade / evidence, and / or `accept_image_alone`, `extend_index`; guarded; answered by `reading_mode_changed`, which carries the status the page shows), `toggle_debug_trace`, `toggle_debug_mode` (Debug mode, for the next start: the request log, and the interactive debugger only where `program.debugger_allowed` says so), `reset_focus` (refocus + lock), `set_autofocus`, `set_fixed_area` (`enabled` / `area` / `use_detected`), `set_camera_rotation`, `set_refocus_every` (`captures`: focus probe interval), `toggle_stop_at_card_back` (`enabled`: a card back stops this camera; answered `stop_at_card_back_toggled`), `set_dropper` (`dropper`: the card dropper's settings, checked whole; answered `dropper_updated`), `test_dropper` (one pulse now; answered `dropper_tested`) | `auto_capture_triggered` (image taken, focus probe done: drop the next card), `auto_capture_toggled` (also when the station's client restarted or went away, and when a card back stopped it), `card_back_seen` (`number`, `similarity`: a face-down card stopped this camera's auto-capture), `processing_queue_update` (the station's captures being read), `*_toggled`, `focus_reset`, `fixed_area_updated`, `camera_rotation_updated`, `refocus_every_updated` |
| `set_ai_provider`, `save_ai_credential`, `update_database` (the active game's data) | `ai_provider_set`, `ai_credential_saved`, `database_update_progress` / `_complete` / `_error`, `database_update_available` (update check found newer data), `log`, `error` |
| `save_prompt` (scope `model` / `all`), `reset_prompt`, `test_prompt` | `prompts_updated`, `prompt_test_result` (sent only to the page that asked) |
| `review_open`, `review_skip`, `review_close` | `review_item` (the station's oldest item, or `id: null` when empty; `station`: its name; `candidates`: the printings the picture looks like, `[]` without an index), `review_queue_update` (count; `queued: true` when a card was just queued - the page plays the queue alert) |
| `set_game` | `game_changed` (to every page; stops every camera's auto scanning; downloads the game's card data if it has none). Captures still waiting to be read keep their game (`game_id` in `route_identified`): they are not looked up as cards of the new game but go, unread, to their own game's review queue |

HTTP endpoints are listed in the README. The collection page adds no Socket.IO events; it only
listens to the inventory, game and card data events above (and sends `update_database`).

**Inventory captures.** Each entry shows its newest capture as a thumbnail. Hovering an entry
(only on devices with a mouse) shows a grid of its captures - up to 8, then "+N more"; clicking
the thumbnail (tapping, on a phone) opens all of them in a viewer.

**Card games.** The page loads `/api/games` (games, their finishes and export formats) and
builds the quantity grid, the edit dialog's finish choices and the export buttons from the
active game; the manual search's Treatment filter (Magic only), the set / number examples and
the card data hint follow it too. The game selector in the top bar only appears when more than
one game exists. Card payloads may carry `finish_options` (only those finishes are offered),
`prices` (`[[finish label, USD]]`) and `thumb_uri` (printing picker).

## The MCP server (decks and collection for an AI assistant)

`mcp_server/` (since 2026-10-15; its README.md has the install and the Claude settings): a
separate program on the machine of the AI client that speaks MCP over standard input / output and
asks this server's web API - `/api/decks`, `/api/decks/<id>`, `/api/decks/<id>/suggestions`,
`/api/decks/ideas/<kind>`, `/api/cards/search`, `/api/inventory`, `/api/stats` - so nothing changes
here. **Version 1 only reads.** Ten tools: `list_decks`, `get_deck`, `check_deck`, `missing_cards`,
`suggest_for_deck` (EDHREC through the server), `what_can_i_build` (starts the server's background
search and waits up to a time), `propose_deck_changes` (works out whether each card exists, is
legal, fits the commander's colours, how many copies are owned and which decks use it, the
singleton rule of commander formats, and the deck's size before and after - **nothing is
changed**), `search_collection`, `find_card`, `collection_summary`. Answers are short on purpose
(small local models). Tested: `tests/test_mcp_tools.py` on a stand-in API; the protocol (tool list,
calls, an error in the tool's own words) with the library's client against the real server, 2026-10-15.
Not tried: a local model as the client. The server has no login: writes (add / remove a card) are for
later, one at a time, each confirmed.

**MTG Arena** (since 2026-10-29). The collection tools take `collection='paper'|'arena'` (`?area=arena`:
the digital collection, `/api/arena` for its wildcards, gold, gems and export date). An Arena deck
(`kind: arena`) is counted by the server against that collection already; the MCP says its cost in
wildcards and never in money: `get_deck` / `check_deck` drop the paper prices and add the payload's
`wildcards`, `missing_cards` reads the decks page's Arena check (`/api/decks/<id>/arena`: the cards to
craft, wildcards needed and had, cards not on Arena), `propose_deck_changes` works out the wildcards the
deck would need after the change, and every Arena answer's `prices_in` says there are none. An eleventh
tool, `search_cards`, is the decks page's card search (`/api/cards/search`: rules text, type, colour
identity, mana value, rarity, legal in a format, owned only, `kind=arena`). `propose_deck_changes` also
checks the 4-copy limit of a 60-card deck (basic lands and "any number of cards named" excepted), and
`suggest_for_deck` says plainly that EDHREC has nothing for a deck without a commander. Tried with the
tools against the real server's Arena deck #22 (reads only); not tried through a client other than
Claude Code.

**Deck writes** (since 2026-10-29, only with `--allow-deck-writes` / `CARD_SCANNER_DECK_WRITES=1`; off,
the tools are not even registered). `create_deck` (`POST /api/decks` with the list as text: Commander /
Deck / Sideboard), `change_deck` (`POST /api/decks/<id>/cards`, removals first, the card data's spelling
and the printing the search picked), `rename_deck` (`PUT /api/decks/<id>`: name, notes). Every write goes
through `ScannerApi.write`, which refuses any method and path outside `DECK_WRITE_ROUTES` before the
network, and forgets the client's 20-second cache afterwards. A change is first worked out by
`_plan_changes` (what `propose_deck_changes` answers) and refused whole on any problem unless
`allow_problems` - because the cards route applies its items one by one, each in its own transaction, a
problem found half-way would leave the deck half-changed. A deck with `from_arena` is refused (the next
import replaces it). No delete. Tested: `tests/test_mcp_tools.py` (`DeckWrites`); end to end through the
MCP server against a throwaway server (`MTG_SCANNER_HOME` in the scratch folder, a copy of test data,
port 5011): create, a 4-copy refusal, a move between boards, rename, a DELETE refused, the commander's
colours.

## Configuration and files

**Where a setting comes from, and which wins** (written 2026-10-16 after an outside review found the
four sources hard to tell apart). Later in the list wins over earlier, per setting:

| Source | What it holds | Notes |
|---|---|---|
| `config.yaml` (shipped, top folder) | every default | never edited per machine (it has no machine's own values and no secret) |
| the person's `config.yaml` (`USER_DIR`; the same file in a checkout) | only what they change, laid over the shipped one section by section | `${NAME}` in a value is replaced by that environment variable (anywhere in the text) |
| the environment and `.env` | `SCANNER_*`, `LOCAL_AI_ENDPOINT`, API keys ... | the server reads `.env` when it starts (`server/__init__.py`) and it does not override a variable that is already set |
| `data/api_keys.env` | keys and the local AI address saved from the Settings page | **overrides** the environment and `.env` (`load_dotenv(override=True)`) |
| `data/settings.json` | choices made in the web interface, everyone's (provider, OCR first, sounds, backups, capture size, debug mode ...) | where a setting also exists in `config.yaml` (`refocus_every`, `refocus_on_drop`), this wins once it has been set |
| `data/stations.json` | each camera's own choices on the server (rotation, focus, refocus, debug trace, fixed area) | per station; falls back to `data/settings.json` |
| a station's own: command line > environment > `data/station.json` > default | the server's address, the station's id / name / token, the camera | `station_setup.resolve`; a value from the command line or the environment is shown as fixed on the setup page |

**The local AI endpoint** (since 2026-10-16; `api_keys.check_local_endpoint`, `tests/test_local_endpoint.py`) is where every
card's picture is sent, and the Settings page can change it from any device that reaches the server (unless a settings
password is set). It must be `http(s)` with no user name, and its host is **resolved**: every address it resolves to must
be loopback, private (10/8, 172.16/12, 192.168/16, fc00::/7), link-local or Tailscale's 100.64/10 - the text of a name proves
nothing (`http://134744072` is 8.8.8.8 to the resolver, found by the outside review; a public DNS name can end in `.lan`);
a name that does not resolve is refused. Another address is refused unless the server's environment has
`ALLOW_PUBLIC_AI_ENDPOINT=1`. The check is made again, and is bound to the connection, at **every request**
(`api_keys.pinned_endpoint`, used by `CardIdentifier._local` and the models route): the host is resolved then, every
address must be on the own network, and an `http` request is sent to that address itself with the name in the `Host`
header - so a name whose DNS answer was changed to a public server after it was saved (DNS rebinding, found by the second
Codex review) is refused and cannot change between the check and the connection. An `https` endpoint must be an **IP address**
(`refuse_https_by_name`; a name is resolved again when a request connects, and pinning https to the checked address while
keeping the name for the certificate is not done - the third Codex review found it; a local AI server is http in practice). Redirects are not followed. This
applies to the address in `config.yaml` or the environment too: a deliberately public one needs
`ALLOW_PUBLIC_AI_ENDPOINT=1`. Tests in `tests/test_local_endpoint.py`. `/api/local_ai_models` says only "could not get the models" (the cause is in the log).

**How much a request may carry** (since 2026-10-16): `MAX_CONTENT_LENGTH` is 64 MB (`server/state.py`) - a
capture is at most ~30 MB, a collection or Arena file a few MB - and `backups_api.limit_the_request_body`
refuses a bigger body with 413 before any route runs (Flask only checks when a route reads it, and several
answer "not ready" first). Uploading a backup (`upload_backup`) raises the limit for itself to 8 GB: it
holds the captures. `tests/test_upload_limit.py`.

**Who may use the server** (`server/access.py`, `tests/test_access.py`): there is no login, and
a browser sends any web page's requests to a local or network address, so a page open in
another tab could otherwise change the collection or restore a backup. Every request's Host
must be `localhost`, an IP address, this computer's own name (alone or under `.local`, `.lan`,
`.home`, `.home.arpa`, `.internal`, `.localdomain`) or in `flask.allowed_hosts` - another name
that resolves here is DNS rebinding. A changing request carrying an `Origin` must come from the
page it was sent to, and a cross-site `/api/` request (`Sec-Fetch-Site`) is refused; Socket.IO
connections follow the same rule (`socket_origin_allowed`). Stations send no `Origin`, so they
pass on the Host check alone: a station reaching the server by a host name that is not the
computer's own (a Docker service name, a reverse proxy) needs it in `flask.allowed_hosts`.
Never tested with the Android app in server mode reaching the server by a host name.

**The settings password** (since 2026-10-16; `server/lock.py`, `tests/test_settings_lock.py`,
`scripts/check_settings_lock.py`): the pages have no login, but the few actions that can hurt beyond one
card can be locked behind one optional password, chosen on Settings -> Server (or fixed by
`SCANNER_SETTINGS_PASSWORD`). Locked when it is set: the AI keys and endpoint (`save_ai_credential`), restart,
quit, network access, Debug mode (`toggle_debug_mode`), how cards are read (`set_reading_mode`: it decides what is added) and, of the backups, restore, upload, download, delete and
making a *full* backup (it holds the keys), and what the Storage card deletes or shrinks (`POST /api/storage/cleanup`, `POST /api/storage/compress`), starts or stops a picture index build (`POST /api/image_index/update`, `/stop`: it downloads for hours the first time), the automatic updates (`POST /api/updates/schedule`: downloads the server makes on its own), the price source (`POST /api/prices/source`: it rewrites every entry's price), the shops' price update (`POST /api/prices/update`), and the `cleanup_days` field of `POST /api/capture_copy` - the rest of that route stays open). Open: scanning, the cameras and their settings, the collection, the
decks, listing backups, making an ordinary backup. A route answers `401 {"locked": true}`; an event answers an
`error` event with `locked: true`. `common.js` wraps every page's `fetch`: on a locked answer it asks for the
password (`passwordDialog`), unlocks and repeats the request once; the Settings page reconnects its Socket.IO
connection after an unlock (the cookie is read when a connection is made) and asks for the event again; a backup's
download link asks first (`ensureSettingsUnlocked`), as a refused link would be saved as a file. It is the camera
station's setup-page mechanism (`station_login.Login`, parametrised): the password only as an scrypt hash in
`data/settings_login.json`, an HttpOnly SameSite=Strict cookie signed with a random key, 12-hour sessions, wrong
passwords wait 1, 2, 4 ... 30 s (so a stranger can make the owner wait). The first password can be set by anyone
who reaches the page; changing or removing it needs the current one. Not covered: the page is plain HTTP, so the
password crosses the network unencrypted - it keeps out mistakes and the curious, not someone listening. A
forgotten password: delete `data/settings_login.json` and restart. `scripts/backup.sh` asks for the full backup, which is guarded: it logs in with `SCANNER_SETTINGS_PASSWORD` (the environment, else the checkout's `.env`; `tests/test_backup_script.py`) and says so when the server is locked and it has no password. A new guarded route takes `@guarded`, a new
guarded event `@guarded_event` (below `@socketio.on`).

**`SCANNER_BIND`** (Docker, `deploy/docker-compose.yml`): the address the port is published on; unset it is every
address (as before), `127.0.0.1` only this computer. It is read by Compose for the `ports:` line only - the server
inside the container still listens on all of its addresses.

**Server**

| Where | What |
|---|---|
| `config.yaml` | Vision AI defaults, web server (`flask.allowed_hosts`: names the server may be reached under, besides localhost, IP addresses and the computer's own name - see *Who may use the server*), station token, cleanup, card data update interval. `camera.*` is read by a station, not by the server |
| `.env` (beside `deploy/docker-compose.yml`) | API keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`); `VISION_AI_PROVIDER`, `LOCAL_AI_ENDPOINT`, `SCANNER_STATION_TOKEN`; for Docker also `SCANNER_PORT`, `SCANNER_UID`, `SCANNER_GID` |
| `data/secret_key` | Signs Flask's cookies: a random key made on first start (mode 600) unless `flask.secret_key` is set |
| `data/api_keys.env` | Keys and local endpoint entered in Settings (`api_keys.py`, mode 600); overrides `.env`. The page only ever receives masked keys (`/api/ai_credentials`) - the web interface has no login |
| `data/settings.json` | Choices made in the web interface that are everyone's: AI provider / model, OCR first, the game, automatic backups (`backup_every_hours`, `backup_keep`), sound on / off, the capture beep and the card-added ding each on / off (`sound_capture`, `sound_added`) and volume (`POST /api/sound`), the size of the large copy kept with each capture how long the pictures received from the cameras are kept (`cleanup_days`, whole days, 1 to 3650, default `cleanup.days` of config.yaml; `POST /api/capture_copy` with `cleanup_days`; the server deletes older ones a few seconds after it starts and then every 24 hours, and `POST /api/storage/cleanup` does it at once - the Storage card's "Clean up now"), `POST /api/storage/compress` (the card's "Compress large copies": a thread makes the large copies already kept no taller than the chosen capture size - never bigger, a new file renamed over the old one so a backup's hard link keeps the old picture, one file at a time under `maintenance_barrier`; refused when the size is Off or one is running; `compress` in `/api/capture_copy` says how far it is), (`capture_copy_size`: `off` / `small` 600 px / `medium` 900 px / `large` 1200 px - the default - `GET` / `POST /api/capture_copy`: a choice of the server for every camera, on the collection page's Settings under Storage as "Capture size (all cameras)", with the number and size of the copies kept so far, and above it "Capture files in use": the total and the files of each kind the captures leave (`usage` in the answer: the pictures received in `scanned_cards/`, the thumbnails in `data/captures`, the large copies, the camera frames - a look at the folders each time the page asks, nothing stored); measured on 40 captures at JPEG 85: ~56, ~100 and ~145 KB each; it applies to new captures, existing copies stay), debug mode (`debug_mode`: Flask's debugger, and every request in `data/logs/requests.log`; taken when the server starts, always without the reloader). Also the camera settings of a camera on the server itself - which a new station inherits until it has its own |
| `data/stations.json` | The stations: name, location, capture count, last seen, `camera` (it connects as a camera station), and `settings` - each station's `focus_value`, `camera_rotation`, `refocus_every`, `fixed_area`, `fixed_area_enabled`, `debug_trace`, `auto_add` |
| `data/prompts.json` | Prompt instructions edited in Settings, per game / kind / model (`prompts.py`) |
| `data/cards_database.db` | Card data (`cards`, `card_data_info`), the collection (`inventory`, `inventory_captures`, `inventory_sources`, and the trades: `trades`, `trade_cards`), decks (`decks`, `deck_cards`), the review queue (`review_queue`), and the captures already applied to it (`applied_captures`) |
| `data/web_cache.db` | Answers cached from other sites (`recommendations.py`): disposable, not in backups |
| `data/scan_inventory.db` | Cards scanned and not yet added to the collection (the same three inventory tables, and `pending_moves`) |
| `data/arena_inventory.db` | The digital collection: what the user has in MTG Arena as the last import said (the inventory tables again, of which only `inventory` is used, and `arena_account`). Replaced as a whole by each import |
| `data/pending_captures.db` | Captures waiting in the OCR / AI queues, queued again after a restart (`pending_captures`), and what became of uploaded ones (`settled_captures`, 30 days) |
| `data/review/` | Captures waiting in the review queue (deleted when resolved) |
| `data/captures/` | Thumbnails of the captures behind inventory entries (deleted with their entry) |
| `data/backups/` | Backups (`<date_time>/`, see Backups); copies of the inventory table made before a migration rebuilds it (`inventory_before_*.db`) |
| `data/logs/` | `app.log` (also every station's scanner lines), `ai.log`, `database.log`, `scanned_cards.log` (one CSV line per identified card; the model column says `light-ocr` when OCR read it), `ocr.log` (errors of the OCR reader process), `printing_check.jsonl` (the shadow check), `reading.jsonl` (the reading log: one record per capture of what each step saw and did, and the review's picks - see "Reading mode: evidence"), `requests.log` (debug mode) |
| `scanned_cards/` | Captured images as uploaded (deleted after `cleanup.days`) |

**Camera station** - nothing it must keep:

| Where | What |
|---|---|
| `config.yaml` | The camera (`camera.usb_index`, `resolution`, `fps`), detection and auto-capture thresholds |
| Environment, or `.env` beside `deploy/docker-compose.client.yml` | `SCANNER_SERVER` (needed), `SCANNER_CAMERA_INDEX`, `SCANNER_STATION_ID` (default: the machine's name), `SCANNER_STATION_NAME`, `SCANNER_STATION_TOKEN` - or the same as `--server`, `--id`, `--name`, `--token` |
| `station_captures/` | Captures not sent yet, each with its note `<image>.upload.json` (deleted once the server has them); `data/debug_frames/` with debug trace on; on the server `data/frames/` (the camera frames behind captures, debug trace on) and `data/captures_full/` (large copies of the collection's capture thumbnails) |

## Performance

Measured with an Anker PowerConf C200 at 2560 × 1440 on the station, and on the server (4
cores of a Ryzen 7 7800X3D, RTX 4070 Ti SUPER) OCR on the GPU and `qwen3.5:9b-q8_0` on Ollama:

| Step | Where | Time |
|---|---|---|
| Camera | station | 27-29 fps at 2560 × 1440 (MJPEG); 20 fps processed (`camera.fps`) |
| Per processed frame | station | ~10 ms (half-size decode, detection, stability) - was ~24 ms at full size |
| Outline detection | station | ~3 ms per frame |
| CPU while scanning | station | ~30% of one core on a laptop (Ryzen 5 7235HS), ~70% on a Raspberry Pi 5 |
| Card landed → capture | station | ~0.15-0.5 s (settling) |
| Upload, OCR, lookup, add | server | 0.3-0.5 s from capture to "added" for a card OCR confirms (0.10 s of it OCR; 0.67 s on the CPU) |
| AI identification | server | ~0.9 s (qwen3.5:9b, 1024 px image); the foil check runs in parallel (+~0.3 s with Ollama); ~10 s once if the model has to load. About 2 cards a second with 3 workers |
| Set + number lookup | server | 0.1 ms; fuzzy name search ~90 ms |
| Live view | station → server | 12 fps, 66-81 KB a frame (~1 Mbit/s), only while a page shows it |
| Server load | server | ~0% CPU idle, 210-260 MB; the per-frame work is all on the stations |

A whole pile, card after card: 1.6-1.7 s per card on a laptop station and on a Pi 5 station,
every card read by OCR. Four simulated stations at a card every 0.5 s each: all added, OCR
median 0.48 s.

Vision models compared on 90 scans (identification + foil check, before the prompt and image
size change - identification alone is now 0.9 s / 1.5 s, see *Prompts*):

| Model | Hardware | Time per card | Notes |
|---|---|---|---|
| `qwen3.5:9b` (Q4_K_M, 6.6 GB) | Ollama server on the network | 1.6 s | reference; says "unknown" when the ★/• is unreadable |
| `qwen3.5:4b` (Q4_K_M, 3.4 GB) | laptop RTX 3050 6 GB (fits entirely) | 3.4 s | image processing ~920 vs ~2,560 tokens/s on the server; called 3 regular cards foil |

The 9B doesn't fit in a 6 GB GPU (it would be split with the CPU); the 4B is a usable fallback.

## Tests

`tests/test_ownership.py` (`venv/bin/python -m unittest discover tests`; also inside the server
container) covers which station scanned what - through splits, merges, a move to the
collection, a clear - and backups: ownership restored, restored over another state, a backup
from before stations, restoring the oldest automatic backup. Everything runs on temporary
databases and folders. These are the cases of a code review of 2026-10-09; 13 of the 14 fail
against the code from before its fixes.

`tests/test_trades.py` covers the cards set aside for a trade: they stay in the collection,
two trades never hold the same copy, nothing else can delete, lower, move or clear what a
trade holds (and a refused change leaves nothing half done), cancelling changes nothing,
confirming removes the copies with their photos and leaves a record, a confirm that fails
changes nothing, and backups (a restore brings a trade back with its entries, over an open
trade, from before trades). The routes and the page were tried in headless Chromium against
the server's code on a temporary copy of test data (2026-10-10), not against the server.

`tests/test_card_back.py` covers the card-back check on synthetic pictures (the pinned fingerprint swapped for one of a synthetic "back"), and that the pinned
one was made with today's fingerprint; `tests/test_card_back_stop.py` the upload route with a back - modes `auto` and `review`, a repeat, the setting off, a
front, an older phone app, a failing check, the sync route's 409 - through Flask's test client on temporary data, with a reading that fails the test if asked.

`tests/test_arena_collection.py` covers the digital collection and the decks' two kinds, on
temporary files and made-up exports: reading the exporter's two files and refusing others,
finding an entry's card (set and number only when the name agrees), an inventory replaced
whole or not at all, the deck table's new columns on an old file, Arena's decks replaced
while decks made here stay, and the digital collection in backups.

There are no automated tests for the rest. [TEST_CASES.md](TEST_CASES.md) lists what to check
by hand. For scanner logic, recorded or synthetic frames can be fed through `CardScanner` with
a fake camera (patch `detect_camera_type` / `_initialize_usb_camera`). **Never test against the
server's real `data/`**: use copies of the databases in a temporary folder, or a second
container with its own data folder and port.

## Known limitations

- **White-bordered cards on a white background** have no visible outline; use a darker
  background or capture them manually with detection off.
- **An identical copy landing within ~0.7 mm of the previous card** without the fall hiding the
  card for 6 frames isn't recognized as new - press Capture.
- **A card hidden for a moment** (a hand over the box for ~0.3 s) counts as a change of card:
  when it is still the same card it is captured again.
- **Cards without the ★/• marker** (older printings) get their finish from printing data only.
- **Undo** takes back only a station's most recent add; older adds are edited in the list.
- **At least once**: a capture is never lost by a restart, but in a crash at the wrong moment
  it can be added twice (see [Sending a capture](#sending-a-capture)).
- **No login**: the web interface and, without a token, the upload are open to the network.
  For a home or shop network, not the internet.
- **A station without a connection** shows no live view and no result until it is back; the
  captures wait, and are kept across restarts of the station and of the app (a computer
  station: pictures with a note each in its `station_captures/`; see the station's setup page).
- **One camera per station**, opened by one process.
- **Raspberry Pi camera modules** go through `picamera2`, which is not in the client's Docker
  image: the station runs from the Pi's own Python there (see [Pi camera module](#pi-camera-module)).
  Focus is the camera's own continuous autofocus - no sweep, lock or drift check. Tried once
  (2026-10-11) with one card; auto scanning, a growing pile and the capture thresholds, all
  measured with a USB webcam, have not been tested with it.
- **Entries shared between cameras** can't be edited from a list filtered to one camera.
