# Card Scanner test cases

What to check by hand (and what would be worth automating), for the server, the camera stations and the pages. Prepared from the README, the Flask routes and Socket.IO handlers, the Python managers, the game adapters and the browser code. It is a test plan, not a record: most cases have not been executed as written. The cases marked **(automated)** are covered by `tests/test_ownership.py` (`venv/bin/python -m unittest discover tests`); section 16 lists what was measured while the server / station split was built.

Each row is a test case with setup/action and an observable expected result. Parameter lists mean separate executions for each value. Expected results describe intended behavior; failures should be recorded as defects, not assumed to be supported already. Resilience, accessibility, and malicious-input cases are quality requirements to verify, rather than claims about implemented protections.

Priority: **P0** = release-blocking data integrity or core workflow; **P1** = normal feature coverage; **P2** = robustness or usability. Suggested layers: **U** = isolated Python/JavaScript test; **I** = Flask/Socket.IO/database integration; **E** = browser end-to-end; **H** = physical camera test (a camera station with its webcam, or the phone).

"The scanner page" below is a camera's page (`/scan/<id>`), with a camera station (`station_client.py`) connected to a server that has no camera of its own - the normal setup. Magic is the only game today: the cases that need a second game (GAME-*, and the ones naming "a second game") are kept for when one is added.

## Setup and reusable fixtures

Use a disposable server - a second container (or `app.py` on another port) with its own data folder - with separate databases, settings, capture directories, credentials, and backups, and point a test station at it. The automated tests and one-off scripts work on copies of the databases in a temporary folder instead. Never run delete, replace-import, restore, rebuild, or interruption cases against the user's collection. Reset fixtures between cases unless the case explicitly tests persistence.

- **MTG cards:** one exact set/number match; a name with multiple printings; regular/foil/surge printings with distinct prices; a foil-only printing; borderless and alternate art; leading-zero and letter-suffix collector numbers; a double-faced card; accented/punctuated names; a basic land; an unlimited-copy card; a limited-copy exception; banned, restricted, and illegal cards; a valid commander, compatible commander pair, and incompatible pair.
- **Inventory:** three copies of printing A, Near Mint, regular, Box 1, price $2; two copies of A, foil, Binder, price $5; one copy of printing B, price $3; a row of a second game, if there is one. Include rows with no location, multiple tags, captures, and imported rows without a card ID. The six MTG copies have value $19 before other fixtures are added.
- **Scanned:** two copies matching the collection's A/regular/Box 1 row, one distinct printing, and a row of a second game (if there is one); keep their capture thumbnails distinguishable.
- **Decks:** an empty deck; Commander decks at 99/100/101 total cards; a 60-card deck with 15/16 sideboard cards; two decks sharing a card; unresolved card names; an explicit printing selection.
- **Review:** one suggested match, one ambiguous match, one unreadable capture, one missing image, and one item per game.
- **Services:** stub AI, OCR, Scryfall/MTG data, EDHREC, Archidekt, Moxfield, and local model discovery. Provide success, empty, timeout, rate-limit, malformed, and unavailable responses. Freeze prices/time for deterministic assertions.
- **Camera:** recorded frame sequences plus real USB and Raspberry Pi cameras where available; plain/sleeved cards, identical consecutive copies, motion, glare, low light, and portrait/landscape frames.

For data-changing tests compare database rows, summed quantities, per-finish prices, captures, batch attribution, and game/area before and after. UI counters alone are insufficient evidence.

## 1. Startup, navigation, and game selection

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| BOOT-01 | P0 I/E | Start with empty disposable data; open `/` and `/collection`. | Required stores initialize; both pages load and show sensible empty states. |
| BOOT-02 | P1 I/E | Restart an instance containing inventory, scanned cards, decks, and review items. | Stored data and remembered preferences survive without duplication. |
| BOOT-03 | P1 I/E | Start without an available camera; use collection and manual search. | Camera failure is visible; non-camera features remain usable. |
| BOOT-04 | P1 E | Navigate scanner → collection → scanner and open Scanned/Review from the top bar. | Correct page/dialog and counts appear; navigation does not mutate data. |
| GAME-01 | P0 I/E | Switch MTG → a second game → MTG with both games populated. | Search, finishes, exports, counts, inventory, and review show only the active game's data. |
| GAME-02 | P1 I/E | Select a second game with none of its data installed. | One background download starts; progress/completion are shown and search becomes usable. |
| GAME-03 | P0 I/H | Switch game during auto scanning with a current card displayed. | Auto scanning stops; current selection is cleared; the old card cannot be added to the new game. |
| GAME-04 | P0 I | Switch game while AI work is queued/running; complete the old work. | Capture is kept in the original game's review queue, without trusting a reading made under the changed game. |
| GAME-05 | P1 I | Submit an unknown game ID. | Error is returned; active game and all data remain unchanged. |
| GAME-06 | P1 E/I | Select a game without deck formats and attempt deck-builder APIs directly. | Unsupported deck features are hidden or rejected with a useful error; no MTG deck is changed. |

## 2. Camera, detection, focus, and fixed area

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| CAM-01 | P0 H/E | Open video feed with each supported camera type. | Live MJPEG frames render with correct orientation and no stalled UI. |
| CAM-02 | P1 H/U | Present a correctly sized card, then remove it. | Outline/status transitions between detected and no-card states accurately. |
| CAM-03 | P1 H/U | Present a hand, sleeve edge, background rectangle, and partial card. | False detections do not trigger an automatic capture of a non-card. |
| CAM-04 | P0 H/U | Move a card, hold it still, then introduce blur. | Focusing/stabilizing/ready statuses track readiness; capture waits for configured stability. |
| CAM-05 | P1 H/U | Exercise outline detection on a closed outline, a broken one (borderless foil on white), a card in the box's corner and a followed outline. | The card is outlined in each case; a skewed or inner-frame outline is rejected (see PROGRAM_DOCUMENTATION.md, Card detection). |
| CAM-06 | P1 H/E | Toggle detection off/on; manually capture while it is off. | Detection state updates; manual full-frame capture still works; re-enable resumes detection. |
| CAM-07 | P1 H/E | Set rotation to 0/90/180/270; capture at each setting; reload. | Stream and saved image match selected rotation; preference persists. |
| CAM-08 | P1 I | Submit unsupported rotation, nonnumeric rotation, and missing scanner. | Useful errors; previous rotation/data stay valid. |
| CAM-09 | P1 H/E | Reset focus on a supported camera; repeat while a sweep is running. | Background sweep reports progress/result; repeated request reports already focusing rather than overlapping sweeps. |
| CAM-10 | P1 H/E | Toggle continuous autofocus, then lock focus and restart. | Camera uses selected focus behavior; saved locked position is restored where supported. |
| CAM-11 | P1 H/I | Request focus controls on a camera without manual focus. | Unsupported-control error; camera feed/scanning continues. |
| CAM-12 | P1 H/U | Set refocus interval to 0, 1, and N; capture N+1 cards. | 0 disables periodic probes; positive intervals refocus at the configured capture boundary. |
| CAM-13 | P1 I | Set negative/nonnumeric refocus interval; restart after a valid change. | Invalid input is rejected and previous value returned; valid interval persists. |
| CAM-14 | P0 H/E | Draw fixed area around a sleeved card; enable it and capture. | Readiness uses the selected region and saved AI image is exactly that region. |
| CAM-15 | P1 H/E | Choose Use detected card, then repeat without a detection. | First action derives a region with margin; second reports no detected card. |
| CAM-16 | P1 I/E | Enable fixed area before drawing; draw reversed/tiny/malformed/out-of-bounds coordinates. | Missing/tiny/invalid areas are rejected; bounds are clamped when a valid region remains. |
| CAM-17 | P1 H/E | Redraw fixed area; toggle off/on; reload/restart. | New area takes effect and persists; disabling returns to outline detection. |
| CAM-18 | P0 H/E | Rotate camera while fixed area is enabled. | Fixed area is disabled as required; client is notified and stale coordinates cannot crop the wrong region. |
| CAM-19 | P2 H/E | Disconnect camera during streaming/capture, then restart with it restored. | Failure is visible, no bogus card is added, and restarting restores usable capture. |

## 3. Capture, automatic scanning, and sounds

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| SCAN-01 | P0 I/H/E | Manually capture a detected card. | Image is saved; capture event, recognized fields, printing, finish, and price appear. |
| SCAN-02 | P1 I/H | Manually capture with no outline. | Full frame is captured; unreadable input is handled without inventing a confirmed match. |
| SCAN-03 | P1 I | Simulate image-save/capture failure. | Error is emitted; no inventory/review entry falsely claims a successful capture. |
| SCAN-04 | P0 H/U | Enable auto capture; leave one card stationary through multiple capture delays. | Exactly one capture occurs until a new-card arrival is detected. |
| SCAN-05 | P0 H/U | Drop two visually identical copies successively after the capture signal. | Two captures occur, resulting in two copies rather than one or a duplicate burst. |
| SCAN-06 | P0 H/U | Introduce a hand, outline flicker, focus movement, and lighting change without replacing the card. | No extra capture of the same physical card. |
| SCAN-07 | P0 H/E | Disable automatic adds; auto capture a card, drop the next before Add, then Add/Skip. | Scanning waits for disposition; next settled card is captured after disposition. |
| SCAN-08 | P0 I/E | Enable automatic adds; process exact matches alongside ambiguous/unreadable cards. | Confirmed cards add one Near Mint copy to Scanned; uncertain cards queue for review; capture continues. |
| SCAN-09 | P0 I/E | Delay AI while capturing several cards. | Processing counter reflects pending work; results map to their own captures; each image is processed once. |
| SCAN-10 | P1 I/E | Stop/restart auto capture while waiting, focusing, and processing. | Stop prevents new automatic captures and resets waiting state; already captured work is accounted for. |
| SCAN-11 | P1 I/E | Toggle automatic adds and OCR-first, then reload/restart. | Saved choices are restored; stability policy changes with automatic-add mode. |
| SCAN-12 | P0 I/E | Set Scan into location; scan more cards; change location and scan again. | Each addition uses its capture workflow's applicable location; existing entries retain their locations. |
| SCAN-13 | P1 I/E | Set location to blank, whitespace, and more than 60 characters. | Blank clears location; whitespace is trimmed and accepted length is limited consistently. |
| SCAN-14 | P0 H/E | Capture with focus check enabled; observe beep timing. | Capture signal occurs after the image is taken; dropping next card after the signal cannot alter that image. |
| SOUND-01 | P1 E | Enable/disable sound; set volume 0/30/100; reload/restart. | Preference persists; muted/zero volume is silent; enabled effects use chosen volume. |
| SOUND-04 | P1 E | Switch *Capture beep* off and *Card added* on, scan a card; then the other way round; reload. | Only the sound left on is heard; errors and alerts still sound; both switches persist. **Not tested in a browser** (settings route and script syntax checked only) |
| SOUND-02 | P2 E | Use a browser with suspended/unsupported Web Audio. | User interaction enables supported audio; audio failure does not block scanning. |
| SOUND-03 | P1 I/E | Submit volume below 0, above 100, and malformed values. | Values are bounded or rejected; stored sound state remains usable. |

## 4. OCR, AI identification, search, and finishes

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| READ-01 | P0 U/I | OCR returns an exact confirmed printing with OCR-first enabled. | Printing resolves without a vision AI identification call; reading source is reported correctly. |
| READ-02 | P0 U/I | OCR returns ambiguous/unknown text, or service is unavailable. | Vision AI fallback is attempted where configured; uncertainty is never silently auto-added. |
| READ-03 | P1 I | Disable OCR; capture a card. | Identification goes through vision AI; unavailable OCR is not required. |
| READ-04 | P1 U | Parse labeled, markdown-wrapped, unlabeled, partial, empty, and malformed AI responses. | Supported forms normalize fields; unreadable/missing values remain unknown rather than guessed. |
| READ-05 | P0 U/I | Provide name + number, set + number, conflicting fields, and name-only matches. | Only match types that confirm a printing auto-add; ambiguous/conflicting evidence is reviewed. |
| READ-06 | P1 U/I | Search with leading zeros, suffix numbers, case variation, punctuation, accents, and a double-faced front name. | Intended card/printing resolves without stripping meaningful identifying characters. |
| READ-07 | P0 I/E | Leave name empty; manually search a valid set code + number. | Exact printing can be found from printed identifiers alone. |
| READ-08 | P0 I/H | Capture an unreadable name with readable set/number. | Identifier-only reading is either resolved safely or queued with capture intact; no capture is lost. |
| READ-11 | P0 I/H | `reading.mode: evidence` with an image index; capture a card whose full-card OCR is not confirmed (a full-art card, or one with the number hidden by a sleeve). | It is added with the printing the picture and strip chose and `picture+strip` in the scanned-cards log, or goes to review; never lost. NOT TRIED on live scans. |
| READ-12 | P0 I/H | `evidence` mode: a Secret Lair card (e.g. the Deadpool ones) whose printed line names another printing. | The printing the picture matches is added, not the one the line names. NOT TRIED live. |
| READ-13 | P1 I | `evidence` mode with no image index, or with OCR switched off. | Every card is read as in `cascade`; nothing is lost and nothing fails. |
| READ-14 | P1 I/H | `evidence` mode: the AI answers a card with a printing the picture clearly is not. | The card goes to review under the AI's name with no number or set; log line "does not look like the picture". |
| READ-15 | P1 I/H | With an image index, open a review item (a card that could not be confirmed). | "The picture looks like" shows up to five printings, nearest first; clicking one shows that printing and it can be added; without an index the section is absent and the item works as before. |
| READ-16 | P1 I/H | After a card database update, open Settings > Card data > Picture index and press the button; press Stop on a longer run; press it again. | The status says how many printings are missing before; progress counts up; after it "up to date" (or, after Stop, what was done is kept and the second press goes on); with a settings password set the buttons ask for it; a second press during a run is refused. Network to Scryfall needed. |
| READ-09 | P1 E/I | Search by name alone, name + number, name + set + number, and treatment. | Appropriate matching printings appear; treatment filters variants correctly. |
| READ-10 | P1 E | Press Enter separately in each search field; correct prefilled capture fields. | Search runs consistently and the corrected selection replaces the previous candidate. |
| READ-11 | P1 E/I | Search an unknown/partial/misspelled name; select a similar suggestion. | No-match/suggestions are clear; selected result becomes the current card. |
| READ-12 | P0 I/E | Select one of multiple printing thumbnails; add it. | Stored ID/set/number/image/price match selected printing exactly. |
| READ-13 | P0 U/I | Read star, dot, unclear, and cropped-away foil markers; use foil-only printing. | Suggested finish and reason follow marker/printing availability; unknown does not imply foil. |
| READ-14 | P1 U/H | With an image index built (`scripts/build_image_index.py`) and `printing_check.mode: shadow`, scan a card whose printed line names another printing (a Secret Lair card) and an ordinary card; run `python scripts/printing_check_report.py`. Also: no index; `mode: off`; a card put in upside down. | Both cards are added exactly as before (nothing about the check changes what happens); the Secret Lair card is listed as a `disagree` of kind `same_card` with the printing the picture looks like, the ordinary one as `agree`; the upside-down card is still `agree` (orientation noted); without an index or with `off` nothing is written and nothing is slower. `tests/test_printing_check.py` covers the logic on synthetic cards; real accuracy is in the report. |
| READ-15 | P1 U/H | With an image index and `printing_check.lookup: ai_cases`, scan a card the OCR cannot confirm (a full-art or borderless card, or one with a glared collector line, so the AI reads it), and one it can; then `python scripts/printing_check_report.py`. Also: `lookup: all`, `lookup: off`, OCR switched off in Settings. | Both cards are added or queued exactly as before; the AI-read card has a `lookup` block (the path - strong, image or review - the printing the picture and the strip would have chosen, `against_resolved`), the OCR-confirmed one none (with `all`, one that is `same_printing`); a card the AI answered nothing for is listed as `unresolved` with what the lookup would have done; the report counts the AI-handled cards and the exit criteria; with OCR off the lookup goes by the picture alone. |
| READ-13b | P1 U/H | Scan a foil copy whose ★ the OCR does not read (a sleeved or glared card) and a regular copy of a printing that exists in both finishes, with `ocr.foil_marker` on and off. | On: the small network answers (log: "Foil marker read by the network") and the finish is Foil / Regular without an AI request; off, or when it is unsure, the AI's foil check follows as before. A card with no set line is never lost. `tests/test_foil_marker.py` covers the order of the steps; its accuracy is in PROGRAM_DOCUMENTATION.md. |
| READ-14 | P0 E/I | Select every supported finish on representative printings of each game. | Only available finishes are offered; price and stored finish follow the selected variant. |
| READ-19 | P1 I | Simulate missing, null, zero, and failed price fetches for both games. | Missing price is shown honestly; card identification/add remains usable without fabricated value. |
| READ-20 | P0 I | Delay price fetch; split/edit/delete the added row before fetch completes. | Late update affects only applicable surviving rows; it cannot change another printing/finish or resurrect a deletion. |

## 5. Review queue and undo

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| REVIEW-01 | P0 I/E | Queue ambiguous, not-found, and unreadable captures. | Queue count increases once per capture; AI fields, suggested match, and image are retained. |
| REVIEW-02 | P1 I/E | Open review with multiple items. | Oldest active-game item appears with total/count and capture beside candidate. |
| REVIEW-03 | P0 E/I | Correct a review item's search/printing/finish/quantity and Add. | Corrected card enters Scanned once; resolved item/image copy is removed; next item opens. |
| REVIEW-04 | P1 E/I | Skip/Delete an item; close queue midway; reopen/restart. | Skipped item is removed; unresolved items persist in order across close and restart. |
| REVIEW-05 | P0 I/E | Capture another card while review is open. | New result queues rather than overwriting the reviewed item or its image. |
| REVIEW-06 | P1 I/E | Review an item with missing capture or stale card ID. | Item remains correctable/skippable with clear missing content; no crash or silent discard. |
| REVIEW-07 | P0 I/E | Open review in client A; attempt to resolve from client B; disconnect A. | Review ownership behavior is explicit; no double resolution; disconnect clears stale client ownership. |
| REVIEW-08 | P1 E/I | Open an empty review queue or resolve its final item. | Empty state/count and scanner review state reset cleanly. |
| REVIEW-09 | P0 I/E | On a scanned card and on a collection card with captures, click the circular-arrow (Send to review) and confirm; repeat on a card with three copies, on a card held by an open trade, and on a card with no capture. | One copy leaves and an item with its capture and the old printing as suggestion waits in the review queue (count rises); adding the right printing puts it in the scanned cards. A trade-held card is refused with the trade message, nothing queued; no capture: no button / refused; Arena view: no button. |
| UNDO-01 | P0 I/E | Add a new row, then Undo. | Exactly the last addition and its associated capture are removed. |
| UNDO-02 | P0 I/E | Add two copies into an existing three-copy row, then Undo. | Original three copies and captures remain; only the two added copies are reversed. |
| UNDO-03 | P1 I/E | Undo with no prior addition; repeat Undo; delete/transfer/restore after an add and then Undo. | No unrelated row is modified; unavailable/stale undo is handled explicitly. |

## 6. Scanned inventory and collection transfers

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| TRANSFER-01 | P0 I/E | Scan/add a card; inspect Scanned and Collection separately. | Card exists only in Scanned until transferred; collection totals are unchanged. |
| TRANSFER-02 | P0 I/E | Add Scanned to Collection with no location override. | Active-game rows merge by printing/condition/finish/location; scanned locations/captures are preserved. |
| TRANSFER-03 | P0 I/E | Transfer with an existing or new location override. | All moved copies use chosen location; matching target rows merge; other games stay untouched. |
| TRANSFER-04 | P1 I/E | Cancel transfer dialog; transfer empty scanned area; repeat successful transfer. | Cancel changes nothing; empty/repeated transfer cannot add duplicates. |
| TRANSFER-05 | P0 I | Interrupt transfer between target write and source removal; restart and run recovery. | Each copy exists exactly once after recovery; no lost or double-counted batch/capture. |
| TRANSFER-06 | P0 I | Scan/add concurrently with transfer. | Defined transfer boundary preserves every addition exactly once in Scanned or Collection. |
| TRANSFER-07 | P0 I/E | Transfer into an existing row, select its Added batch, Remove this batch. | Only batch-attributed copies are removed; pre-existing copies remain. |
| TRANSFER-08 | P0 I | Split/merge/delete some batch copies, then remove that batch. | Only remaining attributable copies are removed; counts never become negative or affect unrelated batches. |
| TRANSFER-09 | P0 I/E | Clear Scanned, then clear Collection with another game populated. | Each clear affects only selected area/active game; other area and game remain intact. |

## 7. Inventory editing, filtering, bulk actions, and captures

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| INV-01 | P0 U/I | Add same printing/condition/finish/location twice; vary each key separately. | Exact keys merge quantities; differing printing, condition, finish, or location create separate rows. |
| INV-02 | P1 E/I | Edit quantity, condition, location, and tags; reload. | Values persist and totals update; tags normalize/deduplicate consistently. |
| INV-03 | P0 I/E | Set quantity to 0/negative; submit fractional/nonnumeric/very large values. | UI/API behavior is consistent and explicit; invalid input cannot corrupt counts or silently add copies. |
| INV-04 | P0 U/I/E | From three regular copies, change finish on one copy. | Two regular remain and one new-finish copy exists; appropriate finish price and capture follow it. |
| INV-05 | P0 U/I/E | Move one of three copies to Binder; move all remaining copies afterward. | First edit splits 2+1; full move leaves no empty source and merges compatible destination rows. |
| INV-06 | P0 I | Change finish/location without split quantity; submit split 0/negative/above stack size. | Default one-copy split is consistent; invalid splits are rejected or bounded without quantity loss. |
| INV-07 | P0 I/E | Change an entry to another printing of the same card, including an imported row without ID. | Set/number/ID/rarity/image/price update; transferred copies keep their captured evidence. |
| INV-08 | P0 I | Attempt printing change to another card, unknown ID, or unsupported finish. | Request is rejected; original row and quantities are unchanged. |
| INV-09 | P0 U/I | Edit a row until it matches another row. | Rows merge quantities and tags, preserve captures, and do not double-count value. |
| INV-10 | P1 E | Navigate previous/next in edit dialog with unsaved changes; cancel and save. | Unsaved-change choice is honored; correct filtered row is edited and navigation remains valid after a merge. |
| INV-11 | P1 E/I | Delete a row in the scanner page's list; cancel deletion; delete missing ID. (The collection page does not ask: INV-12i.) | Confirmation cancellation preserves data; confirmed deletion removes only target; missing ID gives useful failure. |
| INV-12 | P1 E | Apply text search to name/set/type/rarity/location/tag; vary case and enable Not. | Correct rows match; Not reverses text matching; blank text does not hide everything. |
| INV-12a | P1 E | Type `set:HOB` with a card of another set that has "hob" in its name; `-set:HOB`, `loc:"Binder 2"`, `loc:""`, `rarity:r`, two terms plus a word, `foo:bar`, a card name with a colon; enable Not. | A term looks in its field only (set code whole); the minus and Not reverse; unknown fields are searched as text. |
| INV-12b | P1 E | Set several filters and colors, reload; remove the last card of a filtered set and reload; clear filters and reload. | Filters come back (not Added); a value no longer offered is dropped; Clear filters is disabled with nothing filtered. |
| INV-12c | P1 E | Choose each page size; go to first / previous / next / last page; edit a card on page 3; filter down to one page; reload. | Ranges and totals are right; an edit stays on the page; a filter or sort starts at page 1; the size is remembered; no pager with one page. |
| INV-12d | P1 E | Tick a row, Shift-tick another below and above it, in list and grid, across two pages, and Shift-untick. | Every entry between the two gets the same tick, no text is selected, the bulk bar counts them all. |
| INV-12f | P1 E | Search `qty:>4`, `qty:2`, `qty:<=1`, `-qty:1`, `qty:x`. | Entries by their number of copies; a value that is no number finds nothing. |
| INV-12g | P1 E | Click a rarity, finish, location, tag and trade badge (list and grid); click it again; take filters off by their chips; clear all. | The filter, its chip and the address follow each click; a grid card is not selected by a badge click; no chip row with nothing filtered. |
| INV-12h | P1 E | Copy the address of a filtered view, open it in another browser; open plain `/collection` after; open `/collection#settings` with filters. | The address's filters win; without them the remembered ones come back; the settings drawer still opens. |
| INV-12i | P0 E/I | Delete a row and press Undo; let it run out; bulk-move and undo with Ctrl+Z; start a second change, edit a card, or leave the page while one waits; delete a card a trade holds. | Undo changes nothing; otherwise the change is sent exactly once - when the time is over, before any other write, or on leaving; the refusal is shown when it is sent. |
| INV-12j | P2 E | `/`, Esc, ← →, Ctrl+A, Del, Ctrl+Z on the Inventory tab; the same with a dialog open, while typing, and on another tab. | The keys act only on the Inventory tab with no dialog open and outside text fields. |
| INV-12k | P1 E | Export with nothing ticked or filtered; with a filter; with cards ticked; dismiss the question. | The whole collection without a question; else a choice of everything / shown / selected, and the file holds exactly those entries; dismissed: no file. |
| INV-12l | P2 E | Rest the mouse on the small card picture by a row's buttons; on the rest of the row; from row to row; on the last rows of the window; click the capture on the left; on a touch device or narrow window. | The downloaded picture large beside the small one, inside the window, never the previous row's card; nothing elsewhere in the row; the capture still opens with a click; no small picture on touch / narrow. |
| INV-13 | P1 E | Filter color identity, type, rarity, set, finish, location including none, tag, and Added individually and together. | Filter intersection matches fixtures; option lists and totals update correctly. |
| INV-14 | P1 E | Apply price min/max equal to a card's price, one-sided bounds, and min greater than max. | Boundary inclusion is consistent; contradictory range has a clear empty result. |
| INV-15 | P1 E/I | Enable Not in a deck. | Deck-used cards are excluded. |
| INV-16 | P1 E | Exercise every offered sort in each direction with ties/empty prices; reload. | Numeric values/numbers sort correctly; remembered sort is restored without losing rows. |
| INV-17 | P1 E | Toggle list/grid; clear filters; use empty inventory/no matches. | Both views show same rows; clear restores all; empty states are actionable. |
| INV-18 | P0 E/I | Select filtered rows; bulk condition/location/add tag/remove tag/delete, including canceled dialogs. | Only selected IDs change; merging keeps totals; cancellation changes nothing. |
| INV-19 | P1 I/E | Bulk action with no IDs, duplicate IDs, missing IDs, or unknown action. | Useful result/error; no duplicate application or unrelated mutation. |
| INV-20 | P0 E/I | Select inventory rows and Add to deck. | Correct names/quantities enter chosen deck; inventory quantities stay unchanged. |
| INV-21 | P1 E/I | Hover/tap capture thumbnail; open a merged stack and navigate captures. | All retained captured copies render in popover/large view in expected order. |
| INV-22 | P0 U/I | Reduce quantity, split, merge, move, and delete rows with multiple captures. | Capture associations follow copies; trimmed/deleted rows leave no broken references or unrelated deletions. |
| INV-23 | P2 E | Disable browser storage, then sort/switch views/reload. | Interface stays usable even when preferences cannot be saved. |

### Trades

| ID | Priority | Test | Expected |
|---|---|---|---|
| TRD-01 | P0 U/E | Tick entries, **Set aside for trade** with a new name; again with the same name in another case; with an entry that has no free copy. | One open trade; the cards stay in the inventory with a "Trade: name" badge and count in totals, statistics and decks; entries without a free copy are reported, not added. |
| TRD-01a | P1 E | Press ⇄ on a list row with other rows ticked; on a row whose copies are all in a trade. | That card's free copies go into the named trade, the ticks stay; with none free a warning, nothing changes. |
| TRD-02 | P0 U/I | Delete, lower below the held copies, bulk-delete, bulk-move, "Remove this batch", clear, and replace-import an entry a trade holds. | Each is refused with the sentence about the trade; nothing is half done (also not the other entries of a bulk action). The free copies and condition / tags can still be changed. |
| TRD-03 | P1 U/E | On the Trades tab: − / + / × per card, two trades holding copies of one entry, rename to an open trade's name. | Quantities stay within what the entry has free; × leaves the card in the collection; the rename is refused. |
| TRD-04 | P0 U/E | **Confirm trade**; press it twice (two tabs); make it fail part way. | The copies leave the collection once, with the newest photos; the trade moves to Confirmed trades with the cards as they were; a failure changes nothing. |
| TRD-05 | P1 U/E | **Cancel trade**; **Delete from history** on a confirmed one. Two tabs: confirm in one, then **Cancel trade** in the other (still showing it open); take a card out in one, then **Confirm** in the other; with the Confirm dialog open in one tab, swap a card for another (same total) or change a held card's finish in the other, then confirm; swap a card for another (same total) in one tab BEFORE pressing Confirm in the other. | Cancel: the cards are free, nothing else changed. Delete: only the record goes. The stale Cancel is refused ("confirmed meanwhile") and the record stays; the Confirm dialog shows the new numbers and exactly those leave; a change during the dialog, even one keeping the totals, is refused ("changed since it was shown"); a swap before pressing Confirm opens no dialog: a warning and the new list, and only a second Confirm, after looking, goes through; a tab left open from before the update: its Confirm is refused ("reload it") and nothing leaves. `tests/test_trades.py` (`StaleRequests`, `TradeRoutes`). |
| TRD-06 | P1 E | **Export…** an open and a confirmed trade in each format; import the Moxfield file at Moxfield. | The file holds the trade's cards with the copies in the trade. Importing at Moxfield was never tried. |
| TRD-07 | P0 U | Back up with an open trade, confirm it, restore; restore a backup from before trades over an open trade. | The trade is open again with its cards; the old backup restores with no trades. |
| TRD-08 | P2 E | Search `trade:name` and `trade:""`; watch a second browser while a trade changes. | Only the cards set aside are listed; the other browser's list and badges follow. |
| TRD-09 | P2 E/I | Trades tab → Find cards to trade or sell → Find cards; choose a location; tick some; Set aside for a trade. Try with the internet off. | The list holds only cards in no deck and not suggested by EDHREC (copies a trade holds not counted), most valuable first; the ticked ones go into the trade and leave the list; with no internet a message, no list. |
| TRD-09a | P1 E | Open trade → **Sale picture…** with: an entry of 3 copies and 3 scans, an upside-down scan, an entry with no scan (imported), a scan kept only as a thumbnail; tick more than nine; click a card in the preview; switch background and size; **Download** and **Download all**; press Download and turn to the next picture at once; close the dialog during Download all; open a trade of 100+ scans and watch the network tab; Download all of it with every scan ticked; open it with the Arena collection shown. | One tile per scan, only the newest of each entry ticked, "×3" under a card with 3 copies; the no-scan entry shows Scryfall's picture, the thumbnail-only one is marked "low res"; each card has its name and set / number / finish under it; the click turns that card; more than nine make 2+ pictures; the files are JPEGs of 2048 px (or ~2770 × 4240 px full size) on the long side; a download holds the cards, number and size of the moment it was pressed; a closed dialog saves nothing more; only the shown page's large copies are loaded (9 on opening, not every scan). Posting to Facebook Marketplace was never tried. |
| TRD-10 | P0 E/I | Trades tab → Other people's collections: import a file of each kind (this app's export, Moxfield, ManaBox, a ManaBox file with an unknown card) under a name; again under the same name (replace); a CSV of another program; a non-CSV. | Each good file is kept with its entries / cards / value; the same name asks before replacing; the wrong files are refused with the list of formats; cards not found in the card data are counted, the rest kept. Your collection, scanned cards and their backups are unchanged. ManaBox was never tried on a real file. |
| TRD-11 | P1 E | Browse an imported collection (thousands of rows): search by name / set / type / rarity, change the order, page through; Receive and Buy a card with 1 copy and with several. | A page at a time; the search narrows without showing an older answer; the copies asked cannot exceed what they have; Receive asks which trade (a new name makes one), Buy puts it on the list. |
| TRD-12 | P0 E/I | A trade that only receives: confirm it; give some cards and receive some, then export "what I receive"; delete the imported collection afterwards; cancel the trade. | Confirming removes only the cards you give (none: nothing leaves), and adds nothing to the collection; both sides and values show; the received cards survive deleting the import; cancelling removes them with the trade. |
| TRD-13 | P1 E | Buy list: − / + / × on a card, Export (whole and one seller), Empty the list, delete the imported collection. | Copies stay within what the seller has; the files hold the cards; deleting an import leaves the list as it was. |
| TRD-14 | P1 I | Restore a backup made before trades received anything, over a trade that receives; take a full backup. | The trade is back without received cards; the full backup holds `others.db`, the other backups do not. |

## 8. CSV import and exports

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| IO-01 | P0 I/E | Export CSV from each game/area; import into an empty matching game/area. | Names, set/number, quantity, condition, finish, prices, locations, and tags round-trip; captures are not expected in CSV. |
| IO-02 | P0 U/I | Import CSV matching an existing row, plus a distinct row. | Matching quantity increases; distinct row is added; added/updated counters are accurate. |
| IO-03 | P0 I/E | Import with replace enabled, keeping another area/game populated. | Only chosen game/area is replaced; canceling UI confirmation changes nothing. |
| IO-04 | P1 U/I | Import legacy Foil/Surge columns and CSV without optional fields. | Legacy flags map correctly; defaults apply to missing quantity/condition/finish/location/tags. |
| IO-05 | P1 U/I | Include missing name/set, unsupported finish, and malformed rows among valid rows. | Bad rows are skipped/count as errors as appropriate; valid rows and summary remain accurate. |
| IO-06 | P1 U/I | Import blank/nonnumeric/zero/negative quantity and malformed currency. | Documented current fallback applies: quantity at least 1/default 1 and unparseable price 0; no crash. |
| IO-07 | P1 I | Upload no file, empty filename, non-CSV file, empty CSV, UTF-8/BOM CSV, quoted commas/newlines. | Upload validation is clear; valid CSV escaping is preserved; encoding/header failures are visible. |
| IO-08 | P0 I | Fail during a replace import or run two uploads with same filename/time. | No silent loss from partial replacement or upload collisions; report failures and verify recovery. |
| IO-09 | P1 E/I | Export MTG Moxfield format across finishes/conditions; try it for a game without that exporter and for an unknown format. | Supported output follows game exporter; unsupported formats fail clearly without mutation. |
| IO-10 | P1 E | Download empty/nonempty exports. | Valid filename/content type and readable headers/output; downloading does not change data. |

## 9. Deck management, search, ownership, and rules

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| DECK-01 | P0 I/E | Create an empty deck in each of Commander/Standard/Pioneer/Modern/Legacy/Vintage/Pauper. | Selected format/name persists; deck appears in active game's list. |
| DECK-02 | P1 I/E | Create with commander; rename/change format/notes; duplicate; delete/cancel delete. | Changes persist; duplicate has independent rows; deletion/cancellation affects only intended deck. |
| DECK-03 | P1 I | Submit invalid format/board, nonexistent deck ID, and malformed quantity. | Useful errors and no unintended deck/inventory mutation. |
| DECK-04 | P0 I/E | Add, increment, decrement, set quantity, and remove a card in each board. | Board quantities are correct; zero removes a row; repeated names merge appropriately. |
| DECK-05 | P0 I/E | Move cards main ↔ side ↔ commander with same card already at destination. | Destination combines counts correctly; no loss/duplication; size/issues recalculate. |
| DECK-06 | P0 I/E | Choose another printing from row set code; reload/export/duplicate deck. | Choice persists and drives displayed printing/price without changing collection ownership. |
| DECK-07 | P1 I/E | Search name/type/rules text/mana value/rarity/colors/identity/format independently and combined. | Results satisfy requested filters and contain usable card details. |
| DECK-08 | P1 I/E | Search owned-only, commander colors, and Not in other decks. | Owned printing preference is correct; color constraints and other-deck exclusions match fixtures. |
| DECK-09 | P1 I/E | Load further search pages; change filters before delayed previous search returns. | No duplicate/skipped result pages; stale response cannot replace current search. |
| DECK-10 | P1 I/E | Use old card data lacking deck fields. | Update card database prompt appears; unsupported search/rule data is not falsely presented as complete. |
| DECK-11 | P0 I/E | Request four copies while owning two in multiple finishes/locations. | Owned 2, missing 2; ownership is summed correctly and never exceeds requested copies. |
| DECK-12 | P0 I/E | Put same card in two decks with limited inventory; add/remove it in one. | Shared-demand indicators update in both; inventory is never reserved, decremented, or increased by deck edits. |
| DECK-13 | P1 E/I | Sort decks by every offered order; filter format and deck/commander name. | Order/filter matches metadata, size, owned percentage, and missing counts, including empty decks. |
| RULE-01 | P0 U/I | Check Commander decks at 99/100/101 cards, including commander. | 99 warns incomplete; 100 has no size issue; 101 reports excess; edits remain allowed. |
| RULE-02 | P1 U/I | Check constructed main decks at 59/60/61 and sideboards 15/16. | Below 60 warns; 60+ accepted for size; 16 sideboard reports excess. |
| RULE-03 | P0 U | Check singleton/4-copy boundaries over main and side; repeat with basic lands, unlimited and limited-copy text. | Limits and card-specific exceptions are applied; Commander considering board is excluded. |
| RULE-04 | P1 U/I | Add banned/not-legal/restricted cards in corresponding formats. | Correct issues; restricted limit is one; legality issues inform rather than block editing. |
| RULE-05 | P1 U/I | Use no commander, unsuitable commander, supported pair, unsupported pair, and more than two. | Appropriate warnings/errors; supported pairing avoids generic pairing warning. |
| RULE-06 | P0 U/I | Add an outside-color card, colorless card, and cards under paired commanders' combined colors. | Identity check uses combined commander identity; valid cards pass and outside colors are listed. |
| RULE-07 | P1 U/I | Include unknown names and cards without legality/oracle data. | Unknowns are flagged as unchecked; missing data does not falsely prove deck legality. |
| RULE-08 | P1 E/I | Inspect mana curve, deck price, ownership, and completion cost; change printing/quantity. | Charts/totals update from the correct playable boards and per-copy prices; no NaN for missing values. |

## 10. Deck import/export, recommendations, and preconstructed decks

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| DECKIO-01 | P0 U/I/E | Paste plain, `4x`, Arena/Moxfield-style lists with section headings, set/number, foil/tags/comments. | Names/quantities/boards/printing references parse correctly; notes are not part of card names. |
| DECKIO-02 | P1 U/I | Parse blank-line sideboard separation in constructed and Commander lists. | Constructed sideboard is recognized; Commander blank lines do not misclassify main cards. |
| DECKIO-03 | P0 I/E | Import into a new/existing deck using append and replace modes. | Correct merging/replacement; unresolved names are reported; inventory unchanged. |
| DECKIO-04 | P1 I/E | Import supported Moxfield and Archidekt deck URLs. | Deck name/format/boards/cards map correctly; printing references resolve when available. |
| DECKIO-05 | P1 I/E | Import unsupported/private/deleted URLs or simulate timeout/malformed response. | Clear failure, no misleading success or half-created deck. |
| DECKIO-06 | P0 U/I/E | Export text and reimport; download Buy list with fully/partly/unowned cards. | Text preserves deck counts/boards supported by format; Buy list includes only missing quantities. |
| REC-01 | P1 I/E | Open Commander suggestions with one or paired commanders. | Categories/inclusion frequencies appear; owned-only filter and add-to-deck work. |
| REC-02 | P1 I/E | Import EDHREC average deck. | Correct entries populate deck; unknowns reported; inventory remains unchanged. |
| REC-03 | P1 I/E | Load Popular decks with both providers healthy, one failed, and both failed. | Available results remain visible; source-specific errors are understandable. |
| REC-04 | P1 I/E | Run commander ideas with owned legal commanders, no commanders, and duplicated inventory rows. | Candidates deduplicate; weighted fit/ranking reflects owned recommendations; empty result is clear. |
| REC-05 | P1 I/E | Run precon ideas where a deck needs four copies but only two are owned. | Owned fraction uses min(required, owned), not name presence alone. |
| REC-06 | P1 I/E | Build around an owned card with format and Not in a deck filter. | Legal owned candidates appear; returned public decks rank by owned proportion. |
| REC-07 | P1 I/E | Start/stop/restart each idea search; poll during and after; replace a running search. | Progress/state is consistent; stopped results remain; old workers cannot mix into the new run. |
| REC-08 | P1 I | Submit unknown idea kind, missing card, invalid format, or switch game during a run. | Useful validation; no result silently attributed to a different game/card/format. |
| REC-09 | P2 I | Repeat recommendations with fresh/expired cache; simulate rate-limit/empty/malformed responses. | Cache avoids redundant work where intended; failure does not disable local collection/deck features. |
| PRECON-01 | P1 E/I | Search precons by name/set code/year; View cards; close; then Create deck (also for a deck name that exists). | Viewing shows the list with owned counts and creates no deck; Create deck copies the list independently, asking first when the name exists; collection does not change. The view route **done** with a stand-in for MTGJSON; the window and buttons **not tested in a browser** |
| PRECON-02 | P0 I/E | Choose I own it with default and custom location. | Exact supplied printings/foils and quantities add Near Mint inventory; deck opens; counts/prices reflect contents. |
| PRECON-03 | P0 I/E | Own same precon twice; cancel own dialog; encounter unresolved printing or failed source. | Repeated ownership represents another box with intentional quantity increase; cancel changes nothing; unresolved/partial load is reported accurately. |
| PRECON-04 | P1 I | Request unknown precon file and traversal-like filename. | Invalid source is rejected without reading arbitrary files or creating inventory/deck data. |

## 10b. The digital collection (MTG Arena) and decks of two kinds

Needs the files of an Arena collection exporter. Automated in part:
`tests/test_arena_collection.py`, and `scripts/check_arena_pages.py` on a server with copied data.

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| ARENA-01 | P0 I/E | Collection page, **Arena**, **Import from Arena** with `mtga_collection.json` and `mtga_decks.json`. | The bar names the export's date and the wildcards; cards and entries equal the exporter's own totals; the Arena decks appear on the Decks page. The Physical collection is unchanged. |
| ARENA-02 | P0 I/E | Import again; import only the collection file; import a CSV or another JSON. | The same numbers, not doubled; without a deck file the Arena decks stay; a wrong file is refused and nothing changes. |
| ARENA-03 | P0 E | In Arena view try to tick, edit, delete, trade, bulk-change (also Ctrl+A, Del, double click in the picture view). | Nothing can be changed; switching back to Physical shows the same collection as before, editable. |
| ARENA-04 | P1 E | Decks page: All / Physical / Arena; New deck with kind Arena; open an Arena deck. | The filter shows the right decks; Arena decks carry a badge; totals say "in Arena" and what is missing in wildcards; a card Arena does not have is listed as a problem. |
| ARENA-05 | P1 E | Change a deck that came from Arena, then import again with the deck file. Make an Arena deck here, then import. | The imported deck is as Arena has it again (its cover kept); the deck made here is untouched. |
| ARENA-06 | P1 E | A Physical deck: **Arena**. | The window says how many copies the Arena collection has, the cards to craft with wildcards needed and had, and how many are not on Arena. Without an import it says to import first. |
| ARENA-07 | P1 I | Back up, import another export, restore; restore a backup made before the digital collection existed. | The digital collection of the backup is back; the old backup leaves it as it is. |
| ARENA-08 | P2 M | Never tried: an export whose decks have a sideboard or a commander; the wildcard counts compared with what Arena asks for the same cards. | Boards land where they belong; counts agree, or the difference is noted in the documentation. |

## 11. Statistics

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| STATS-01 | P0 I/E | Load the six-copy/$19 MTG fixture; inspect stats and inventory summary. | Copies total 6 and value $19; distinct entry count is not confused with quantity. |
| STATS-02 | P1 E/U | Switch statistics between card count and value. | Color/type/rarity/finish/set/location groups sum correct quantities or quantity × price. |
| STATS-03 | P1 E/U | Use multi-tag, untagged, multicolor/colorless, unknown type/rarity rows. | Buckets are labeled meaningfully; multi-tag membership may count a row in multiple tag groups and is not mistaken for global total. |
| STATS-04 | P1 E | View Most valuable with ties, missing prices, and more than ten rows. | Up to ten highest unit-price rows appear in correct order with finish/set labels. |
| STATS-05 | P1 I/E | Add/edit/split/delete/import/transfer/clear and switch games. | Stats refresh to active collection/game; empty stats contain zeros rather than NaN. |

## 12. Backups and restore

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| BACKUP-01 | P0 I/E | Back up populated collection, Scanned, decks, and captures with note. | Backup includes all three stores across games, metadata/counts/note, and capture files. |
| BACKUP-02 | P1 I/E | Create two backups in same second; list with long note. | IDs are unique; list newest first; note is trimmed/limited to 80 characters. |
| BACKUP-03 | P0 I/E | Edit/delete all backed-up data/captures; restore backup. | Saved rows and captures return; pre-restore state is automatically backed up; undo pointer is reset. |
| BACKUP-04 | P0 I/E | Restore the automatic pre-restore backup. | The state replaced by previous restore is recovered accurately. |
| BACKUP-05 | P1 I | Restore older schema backup after adding columns. | Shared columns restore; new columns retain defaults; valid foreign associations survive. |
| BACKUP-06 | P0 I | Inject write/space/lock failure during create and during each restore stage. | No incomplete backup is listed; partial restore is explicitly reported with prior-state backup available. |
| BACKUP-07 | P1 I/E | Delete/cancel deletion; use missing/corrupt/traversal backup IDs. | Cancel preserves backup; valid deletion affects only that backup; invalid IDs fail safely; corrupt entries do not break list. |
| BACKUP-11 **(automated)** | P0 I | Automatic backups: ask when none exists, again at once, after the interval with and without a change, with the interval off, with an empty collection, and past the number to keep. | One is made when due and something changed; none otherwise; only the newest *keep* automatic ones remain and manual ones stay. |
| BACKUP-13 **(automated)** | P1 I | Pack a backup as a zip; delete the backup; unpack the zip into the backups folder; restore it. | The zip holds `backup.db` and every capture under the backup's id; unpacked it is listed and restores the cards. Unknown ids are refused. The download button in a browser: **not tested** |
| BACKUP-14 **(automated)** | P0 I | Upload: a downloaded zip after deleting the backup; the same zip twice; files that are not a zip, hold paths outside the folder, extra files, two backups, a broken `backup.db`. | The backup is listed again (as uploaded, never cleared automatically) and restores; everything else is refused and leaves no folder behind. The upload button in a browser and a 100 MB file: **not tested** |
| BACKUP-12 | P1 E | Collection page → Settings: change *Automatic backup* and *keep the last*; reload; leave the server running past the interval. | The choices persist; a backup marked automatic appears when due. **Not tested**: the controls in a browser and the ten-minute timer on a running server |
| BACKUP-08 **(automated)** | P1 I | Make more than five automatic backups and several manual backups. | Only newest five automatic backups remain; manual backups persist until explicitly deleted. |
| BACKUP-09 | P0 I | Change settings/card data/review after snapshot, then restore. | Collection backup restores its documented scope; settings, downloaded card data, and review queue are not rolled back. |
| BACKUP-10 | P1 I | Simulate unsupported hard links and absent capture file during create/restore. | Copy fallback works; missing images do not invalidate unaffected inventory; restoration limitations are visible. |

## 13. AI settings, credentials, prompts, and debugging

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| AI-01 | P1 I/E | Select Gemini/OpenAI/Anthropic/local with valid stub credential/endpoint and model; restart. | Selected provider/model is used and persisted; model lists/status match settings. |
| AI-02 | P1 I/E | Select unknown provider/model or cloud provider without credential. | Useful failure; previously working scanner configuration remains usable. |
| AI-03 | P1 I/E | Discover local models via supported Ollama/OpenAI-compatible endpoints; return empty/timeout/malformed list. | Available models display; failures/empty list do not hang settings. |
| AI-04 | P1 I | Warm up local model when auto capture starts; simulate slow/failed warm-up. | Successful warm-up reduces first-use delay; failure is visible and does not falsely add a card. |
| KEY-01 | P0 I/E | Save/change/remove each key; inspect credential-status response and saved file permissions. | Runtime changes apply; cloud keys are masked; file permissions are owner-only; full keys are not returned. |
| KEY-02 | P1 I | Save unknown provider, multiline key, invalid local endpoint, and blank value. | Invalid values rejected; valid HTTP(S) endpoint accepted; blank clears saved override. |
| KEY-03 | P1 I | Configure base `.env` plus saved override; clear override and restart. | Saved value takes precedence; base key may reappear after restart, matching documented behavior. |
| PROMPT-01 | P1 I/E | Open prompts for each game/provider/model. | Correct tabs, effective instructions, source, built-in text, and fixed answer format appear. |
| PROMPT-02 | P1 U/I/E | Save all-model instructions, then model override; switch model/game. | Lookup is model → all-model → built-in; edits remain scoped to correct game/kind. |
| PROMPT-03 | P1 U/I/E | Reset model override, then all-model edit, then reset again. | Each reset exposes next fallback; final reset is a harmless built-in state. |
| PROMPT-04 | P1 I | Save empty text, unknown kind, text over 8,000 characters, and model scope without active model. | Validation errors; saved prompt remains intact and fixed answer format cannot be overwritten. |
| PROMPT-05 | P0 I/E | Test unsaved identification prompt on last capture. | Raw answer, parsed fields, timing, and match confidence return only to requesting client; no prompt/inventory mutation. |
| PROMPT-06 | P1 I/E | Test with no AI, no capture, empty prompt, or foil prompt without outline crop. | Specific errors; no background task claims success. |
| PROMPT-07 | P1 I | Test foil prompt with star/dot/unclear and simulate API failure. | Foil parse or useful error returns; existing card/review data stays intact. |
| DEBUG-01 | P1 I/E | Toggle trace and saved Flask debug mode; reload/restart. | Trace persists; debug UI distinguishes saved preference from running mode and restart requirement. |
| DEBUG-02 | P2 I/H | Cause slow/doubtful capture with tracing enabled; inspect logs/debug frames. | Useful traces/frame dumps are produced with bounded retention and do not interfere with scanning. |

## 14. Card database, migrations, configuration, and maintenance

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| DBR-01 **(automated)** | P0 I | A camera-filtered list, then a write from a second connection; delete an entry. | No transaction is left open and the write goes through; the entry's captures and camera rows go with it. |
| DBR-02 **(automated)** | P0 I | Card data swap with a missing, empty or much smaller import table, and with a failure after the drop. | The cards in use and `card_data_info` stay; a good import replaces both together. |
| DBR-03 **(automated)** | P0 I | Deck import with a bad entry / an injected failure / nothing to replace with, then another edit; a board move failing half way; a card for a deck that does not exist. | The deck is as before, nothing half done is committed later; a move is there and gone or neither, and keeps the printing. |
| DBR-04 **(automated)** | P0 I | Lower an entry's quantity below what its cameras claim; split, merge, undo, move one camera's cards; open a database with older over-claims. | The cameras never claim more than the entry has; copies added by hand go first; old rows are corrected at startup. |
| DBR-05 **(automated)** | P0 I | Replace the inventory from a CSV with no usable row / one unusable row; headers in another case; a write failing half way. | A refused replacement keeps cards, captures and cameras; headers are found in any case; a failed change is rolled back and thumbnails go only with a committed delete. |
| DBR-06 **(automated + run 2026-10-09)** | P0 I/E | The same capture applied twice (inventory, review queue); outcome after a restart; a failing capture; on an isolated copy of the server: an upload repeated, sent twice at once, `kill -9`, the capture back on the record, restart. | One card / review item per capture; repeats get the recorded answer; a failing capture is kept three starts. The isolated run: 2 cards for 2 captures. **Not tested**: a kill exactly between the two commits; the clients' retry rules. |
| DBR-07 **(automated)** | P1 I | Web cache: store and read, expiry, size budget, moving the old table over. | Answers come back, old ones go, the oldest make room, the old table is gone only after its answers are in the new file. Also run on a copy of the real database: 419 answers, 138 MB -> 37 MB. |
| DBR-08 **(automated + run 2026-10-09)** | P0 I | Open inventory and deck files from before the constraints (also from before stations); orphan rows, entries without copies, ids given out and gone. Then: rows the database must refuse; parents deleted. | Rebuilt once with a backup beside the file; only meaningless rows left out; ids and counters kept; a second start does nothing. Orphans, zero and non-integer quantities and unknown boards are refused; children go with their parent. Also run on a copy of the collection in use: every row identical. |
| DBR-09 **(automated)** | P1 I | Split an entry part of whose copies came with the last "Add to collection", then take that batch back; restore a backup holding rows that cannot stand; import card data while the shared connection has something open, with too few cards, twice at once. | The batch removes what it brought and no more; the restore leaves the rows out; the import is whole or refused, one at a time. |
| DBR-10 **(automated + run 2026-10-09)** | P0 I/E | Full backup with scanned cards, a review item, a waiting capture and a move cut short; open it in another folder; a capture being settled meanwhile; a picture gone. `scripts/backup.sh` against an isolated copy of the server. | All files at one moment, verified; usable elsewhere (the move is finished there); it waits for what is under way; a missing picture is reported; the last 2 kept. The script archives the server's snapshots. **Not tested**: restoring a whole server from an archive. |
| DBR-11 **(automated)** | P1 I | The station's reading of the server's answer to an upload (accepted / refused / anything else). | A picture is deleted only when the answer names the capture. **Not tested** against a real server; the Android app is unchanged. |
| DBR-12 | P2 | `scripts/benchmark_db.py` on a copy (numbers in PROGRAM_DOCUMENTATION.md). | Measured 2026-10-09; one redundant index removed, no index added, FTS5 not adopted (34 ms substring search). |
| DBR-13 **(automated)** | P1 I | Automatic card data update: off; data older and younger than the interval; data without a date; a failed attempt, then a restart within the hour and after it; two games, one without data; a download already running; a value in `data/settings.json` that is not a choice. | Downloaded only when due, every game with data and none without; a failure waits an hour across the restart; a running download is left alone; a wrong value is off. |
| DBR-14 **(automated)** | P1 I | Picture index retry: no index; nothing missing; 89.9% and 90% covered; a build or a card data download running; twice within the interval; a build from the command line holding the index, released. | Never a first build nor one under 90%; nothing while something runs; once per interval; the held build uses no interval and the next tick builds. |
| DBR-15 | P1 E | On a disposable server with card data older than a day: Settings > Card data > Automatic updates > *Card database* Every day; *Picture index: fetch what is missing* *Go back to what is missing* Every 6 hours; with a settings password set; reload; leave it running 10+ minutes. | The choices ask for the password and persist; the card data downloads by itself about 10 minutes after start, the index follows it; both cards show the last run and the next. **Run 2026-10-22** on copied data, without the password and with the schedule set in `data/settings.json`: the download at 10 minutes after start, the index extension after it, the last / next line - see PROGRAM_DOCUMENTATION, *Automatic updates*. The index retry live too, the same day (the extension switched off: the retry fetched the 3,592 missing pictures on the next tick). **Not tested**: the password prompt in a browser. |
| DATA-01 | P0 I | Download each game's initial data with progress stubs. | Searchable counts/details/indexes initialize; deck fields are available for supported MTG data. |
| DATA-02 | P0 I | Update existing data successfully; fail download/parse/write mid-update. | Success replaces data coherently; failure retains usable previous data and collection/decks. |
| DATA-09 **(automated)** | P1 I | Card data import with Scryfall's etched / EUR prices; an etched-only printing added as foil; a second download with new prices; no price today; a printing gone; an entry without a printing; an entry edited between the computation and the write; copies held by a trade; an older file without the new columns. | The three prices are kept; the etched one prices the etched foil and counts for `cheapest`; entries take the new price, keep theirs when there is none, a CSV entry and an edited one are left alone, held copies are priced; the columns are added at start. `tests/test_prices.py`. **Run 2026-10-24** after a real Scryfall download on copied data (PROGRAM_DOCUMENTATION, *Prices follow the card data*). **Not tested**: with a page open. |
| DATA-10 **(automated + run 2026-10-24)** | P1 I/E | Settings > Card data > Prices: Cardmarket on card data from before the euro prices were kept; after a card data update; back to TCGplayer; an unknown id; a change during a card data import; an older file without the shown columns; the CSV export in euros. With the settings password set: the padlock and its prompt. | Refused (409, greyed out) without euro prices; then every page in €, the entries repriced, back to the same dollar total; 400 for an unknown id; the import ends in the chosen source; the columns filled at start; `Price (EUR)` / `€`. `tests/test_prices.py` (`PriceSources`) and a trial server. **Not tested**: with the password. |
| DATA-11 **(automated + run 2026-10-24)** | P1 I/E | Settings > Card data > Prices with the shops: Card Kingdom before any shop prices; *Update the shops' prices* (the first, then again the same day); Card Kingdom -> Mana Pool -> TCGplayer; a card data download with Card Kingdom chosen; Cardmarket and back; the automatic update (every day) before and after MTGJSON's file of the day; an update during a card data download. With the settings password set: the button's padlock. | Refused (409, "update the prices first"); the first update fills about 100,000 printings, a second one downloads nothing; back at TCGplayer the total is the one before, to the cent; entries a source cannot price are counted and left without a price; the download keeps the shops' prices shown; the schedule looks again an hour after a try that found nothing newer; an update during a download fails and nothing changes. `tests/test_prices.py` (`ShopPrice*`, `CurrencyChange`), `tests/test_update_schedule.py` (`PricesSchedule`) and a trial server. **Not tested**: the schedule's own run, with the password. |
| DATA-12 | P1 E | After *Update the shops' prices*: the collection's list, Statistics, an open trade; a foil copy of a card Card Kingdom buys only as regular; the price source in euros; the scanned cards and the Arena collection; before any shop prices. | "Card Kingdom offered $x" under a row's value; a tile "$X - Card Kingdom offered, for N of M cards, on <date>"; the trade's summary adds the offer for its cards; with prices more than two days old (schedule off), "N days ago" on the tile and the trade, the rows in the warning colour; a Played or Poor copy: its row says "for Near Mint - yours is Played, graded lower" and the totals leave it out; no offer for that foil; still in dollars with euros chosen; nothing on the scanned cards, Arena or before an update. `tests/test_prices.py` (`TheBuylist`). Never compared with Card Kingdom's own page. |
| DATA-03 | P1 I/E | Run scheduled/startup update check with newer/no-change/unavailable source. | New-data notice is accurate; unavailable check does not prevent app startup. |
| DATA-04 | P1 I/E | Start update repeatedly and rebuild while update is active. | Conflicting jobs are prevented or serialized; progress/completion reflects actual operation. |
| DATA-05 | P0 I | Rebuild card database with both games, inventories, decks, review, and settings populated. | Intended card-data reset/redownload succeeds; user-created data is preserved. |
| DATA-06 | P0 I | Open legacy inventory schemas lacking game/location/captures fields; repeat startup. | Migration preserves quantities/finishes, makes migration backups where implemented, and is repeatable without duplicates. |
| DATA-07 | P1 U/I | Load valid/missing/malformed YAML, environment substitutions, corrupt/missing settings JSON. | Configuration errors are actionable; settings fall back to defaults as implemented; valid preferences override configured defaults. |
| DATA-08 | P0 I | Interrupt settings/prompt save and restart; simulate disk full/read-only data. | Atomic-file writes preserve last complete file; write failure is visible instead of falsely reporting persistence. |
| CLEAN-01 | P1 U/I | Clean images older than cutoff; include newer files, other extensions, and subdirectories. | Only eligible old image files are removed; count/freed space are correct. |
| CLEAN-02 | P1 U/I | Run dry-run, clean-all, missing directory, and deletion-error cases. | Dry-run changes nothing; clean-all affects designated images; per-file errors do not abort other cleanup. |
| CLEAN-03 | P0 I | Clean original scans while inventory captures, review copies, and backups reference them. | Preserved thumbnails/review/backup evidence remains usable after original scans expire. |
| OPS-01 | P1 I | In disposable deployment, run start/service scripts and archive backup script. | App starts with intended working directory/config and logs; archive covers documented full backup scope. |
| OPS-02 | P1 I | Shut down/restart during queued processing and compare capture/accounting totals. | No duplicate additions; any nonpersistent in-flight work is identified as a recovery limitation rather than counted as completed. |

## 15. API, browser robustness, accessibility, and workload

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| API-01 | P1 I | Exercise every documented route with valid method/query/body, plus wrong methods. | Correct content types and success payloads; unsupported methods fail without side effects. |
| API-02 | P0 I | Repeat row mutation by ID across wrong active game and `area=scan`/collection. | Mutations cannot unintentionally target another game/area; record any missing scope validation as a defect. |
| API-03 | P1 I | Send missing/null/wrong-type JSON fields, malformed JSON, invalid query offsets, and unavailable components. | Actionable errors; no uncaught exception or corrupted state. |
| API-04 | P0 I/E | Submit HTML/script-like card names, tags, locations, deck names, notes, and AI text. | Values render as text, never execute script or break dialogs. |
| API-05 | P0 I | Request traversal paths in capture/review routes and malicious upload filenames. | Files outside designated directories are inaccessible and unwritable. |
| API-06 | P1 I/E | Disconnect/reconnect Socket.IO during capture, add, review, and settings changes. | Client refreshes actual state; retries do not silently double-add; failed actions are visible. |
| API-07 | P0 I | Concurrent add/update/delete/transfer/backup operations using distinct clients. | Database locks protect quantities/associations; no deadlock, lost update, or mixed snapshot. |
| UI-01 | P1 E | Use scanner/collection on desktop and narrow phone viewport. | Controls, tables/grid, dialogs, capture viewer, and deck panels remain usable without blocked actions. |
| UI-02 | P2 E | Operate search, tabs, dialogs, switches, quantity buttons, and confirmation with keyboard only. | Focus is visible and logical; dialogs can be exited; controls have meaningful accessible names. |
| UI-03 | P2 E | Test slow/failed fetch, missing card images, empty results, and long labels. | Loading/error/empty states are understandable; layout remains usable; failed requests do not appear successful. |
| UI-04 | P1 E | Perform collection edits in one tab while scanner is open in another. | Counts/data refresh coherently on notification or reload; stale UI cannot conceal data loss. |
| UI-05 | P1 E | The Settings page (redesigned 2026-10-22): open it with nothing remembered; open each line of the Overview; open `/settings#data` and `/settings#sounds` (the collection page's old link); set a settings password and look at every section; then remove it; at phone width. | The Overview opens first, its lines say how things stand and lead to their sections; the old addresses open Backups and Cameras; with a password the padlocks mark exactly what asks for it (and are gone without one). **Tried 2026-10-22** in headless Chromium on copied data, every section, with and without a password, and at phone width (`tests/test_settings_page.py`: every id the script uses is in the page, every section has its button, the old addresses lead somewhere). **Not tried**: with a camera connected (the copy had none), clicking through in a real browser. |
| CAM-DROP-01 | P1 H | On a Raspberry Pi station with an LED (and resistor) on GPIO17: Settings > Cameras > Card dropper on, pin 17, *Drop one card*; then auto-scan with auto-add on, then off (Add / Skip on the page); stop scanning while a refocus runs; unplug the camera. | The LED blinks once per test, once after each capture beep, with auto-add off only after Add or Skip, once when scanning starts, never while the focus moves, never when scanning was stopped or the camera is gone. **Not tested** (no pin, no mechanism yet; `tests/test_station_dropper.py` covers it with a stand-in). Then with the mechanism (`SilentKernel81/card-dropper`, not yet assembled): card damage on commons and sleeved cards first - the tests in that repository's plan (`docs/MECHANISM_PLAN.md`). |
| LOAD-01 | P1 I/E | Load 10,000+ inventory rows and large decks; filter/sort/render/import/export. | Operations complete within agreed device-specific budgets with correct totals and responsive controls. |
| LOAD-02 | P0 I/H | Scan a counted stack of 100 cards with repeated/ambiguous copies and delayed AI. | Captured = added + unresolved review + explicitly skipped/failed work; no unexplained losses or duplicate copies. |
| LOAD-03 | P2 I/H | Run a prolonged scan session with trace, price fetches, and repeated review. | Memory, worker count, disk use, and queue latency stay within measured deployment budgets. |

## 16. Server, camera stations, and the phone

Checked while this was built (2026-10-08 / 09) are marked **done**, with what was measured in
PROGRAM_DOCUMENTATION.md (Stations) and INSTALL.md; **(automated)** is in `tests/test_ownership.py`.

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| STN-01 | P0 I/H | Start a camera station against a server without a camera. | It appears on `/` and its page shows the live view; the camera settings come from the server. **done** (laptop, Raspberry Pi 5) |
| STN-02 | P0 H | Auto scanning on a station: drop a counted pile, including identical copies in a row. | Captures = cards dropped; each added once or in that station's review queue. **done** for 17-18 cards (one count was off by one, cause not established) |
| STN-03 | P0 I/H | Manual capture, and auto scanning with "Add cards automatically" off. | The card is shown on that station's page and waits; the station holds its next capture until Add / Skip. **done** |
| STN-04 | P1 H | From the page: Refocus, fixed area (draw / use detected / off), rotation, focus check interval, detection off / on; an invalid rotation. | Each runs on the station and is saved for that station only; the invalid value gives the error text. **done** |
| STN-05 | P0 I | Stop the server with a capture waiting on the station; start it again. | The capture is sent once the server is back - one card. **done** (12 s outage) |
| STN-06 | P0 I | Send the same `capture_id` twice; kill the server with captures queued and restart. | One card per id; every accepted capture is added or in review after the restart (at least once: see the documentation). **done** |
| STN-07 | P1 I | Restart the server while a station is connected; stop the station. | The station reconnects by itself; its page says "No camera station connected" while it is away. **done** |
| STN-08 | P1 H | Unplug the webcam while the station runs; plug it back in (also under another `/dev/videoN`). | The page says "No camera"; the live view returns without a restart (by-id name), or after one. Not tested |
| STN-09 | P1 I | Set a station token; connect and upload without it, with a wrong one, with the right one. | 401 / refused connection without the right token. **done** for uploads; not tested with the camera client |
| STN-10 | P0 I/E | Two stations scanning at once, each with its page open. | Each page receives only its own station's cards, log lines, review items and counts. **done** (one camera station and one uploader) |
| STN-11 | P1 I | Per-station settings: change location, add automatically, focus check on one station. | The other stations and `settings.json` are unchanged; a new station starts from the shared values. **done** |
| STN-12 | P0 I | Scanned list with a camera chosen: list, count, Add to collection, Clear (cards and review items). | Only that camera's copies and captures are shown / moved / deleted; the others' stay; the other cameras' Undo still works. **done**, **(automated)** for the inventory side |
| STN-13 | P0 I | Two stations scan the same printing into the same location; filter, edit, split, merge. | One entry; each camera's list shows its copies; a shared entry can't be edited from a filtered list; ownership follows splits and merges. **(automated)** |
| STN-14 | P0 I | Crash between the two commits of a one-camera "Add to collection"; restart. | The move is finished for that camera only: nothing twice, nothing lost. **done** (simulated on copies) |
| STN-15 | P0 I | Back up, change which station owns what, restore; restore a backup from before stations; restore the oldest automatic backup. | Ownership is as in the backup (none for an old one); the backup being restored is not deleted. **(automated)** |
| STN-16 | P1 I/E | Forget a station that has scanned cards and review items; let it connect again. | Its scanned cards and review items are removed, the collection is untouched; it comes back empty. **done** through the API |
| STN-17 | P1 E | The cameras page, a station's page, a capture-only station's page; Settings → Cameras (rename, location, Undo last add, Forget). | Pages render with the right panels; the buttons act on the station named. Rendering **done**; the buttons not clicked in a browser |
| STN-18 | P1 I | Client image: build for x86-64 and ARM64; start with no camera, with a camera by number and by `by-id` path. | The image builds and the station connects; without a camera it says so and waits. **done** |
| PHONE-01 | P0 H | Phone in client mode: manual capture of a real card; Undo; auto mode over a pile. | Added on the server and shown on the phone; Undo removes it; the pile is counted. **done** (Pixel 10; auto mode: 16 cards) |
| PHONE-02 | P0 H | Phone with the network off: capture several cards, close the app, restore the network, open it. | Every capture reaches the server once. **done** on the emulator; not on a phone |
| PHONE-03 | P1 I | Export the phone's CSV (standalone) and import it on the collection page. | Every entry arrives with its printing id and set code. **done** with 102 entries |
| PHONE-04 | P0 H | Phone in client mode, three copies of the same card scanned. Remove the middle row on the phone. Then "Add to collection" on the server with a location; remove a row of a card that is in the collection now. | The server's scanned cards lose that one copy (and its photo); after the move the phone's rows of those cards disappear within ~10 s; the collection keeps every card. **done in part** on the Pixel 10 against the real server (2026-10-12): three captures of one card, the middle row removed (the server kept the other two, `resolved` for the removed one), then the camera's cards cleared on the server and the phone's rows gone by themselves. The move into the collection was not done from the phone (it would have put test copies into the real collection): `tests/test_capture_sync.py` and a run against a local server cover it |
| PHONE-05 | P1 H | A card the server queues for review, scanned by the phone: remove its row while the camera's page has it open; another one: add it from the review, then remove its row. | The item leaves the review queue and the page closes it; the added card leaves the scanned cards. Not tried with the app |
| OCR-01 | P1 I | Server image with and without an NVIDIA GPU. | `ai.log` says `light-ocr ready (webgpu)` / `(cpu)`; the same reads either way. **done** |
| LOAD-04 | P1 I | Four stations at a card every 0.5 s each; AI requests 1, 2, 3 and 6 at a time. | All cards settled; throughput as documented. **done** |

### The station's setup page and the Raspberry Pi camera

| ID | Priority / layer | Setup and steps | Expected result |
|---|---|---|---|
| SET-01 | P0 H/E | Start a station with no server set anywhere (no `.env`, no saved file). Open `http://<station>:8080`. | The page says the station is not set up; the camera is not opened; the log names the page. |
| SET-02 | P0 H/E | Type the server's address without `http://`, press *Test connection*; then a wrong address; then an address of another web server. | "Scanner server found" with the address tidied; "No answer"; "answers, but not as a scanner server". |
| SET-03 | P0 H/E | Fill in name and camera, *Save and restart*. | The page waits and reports the station running; the status shows connected and the camera working; the station appears on the server under that name. |
| SET-04 | P1 H/E | Restart the container / the machine. | The station comes back with the saved settings, without the page being opened. |
| SET-05 | P1 H/A | Set `SCANNER_SERVER` in `.env` and start. | The server field is shown as fixed and cannot be edited; saving other fields does not change the server. (`tests/test_station_setup.py` covers the order.) |
| SET-06 | P1 H | Two USB cameras plugged in: choose each in turn, *Show picture*. Save one, swap the USB ports, restart. | Each picture is of the camera chosen; after the swap the same camera is used (saved by its by-id name). Not tried yet. |
| SET-07 | P1 H | Raspberry Pi camera: *Show picture* while scanning, drag a rectangle around the box, save. | Scanning pauses a few seconds for the picture and goes on; after the restart the camera's page on the server shows only the dragged part. |
| SET-08 | P1 H | Save a token on the page, reload the page, inspect what the browser received. | The token field is empty with "a token is saved"; `/api/state` holds no token. *Remove the saved token* removes it. |
| SET-09 | P2 H | Type an id with a space; drag a tiny crop; save. | A sentence under the Save button says what is wrong; nothing is saved, the station is not restarted. |
| SET-11 | P0 H/A | Open the setup page of a station with no password yet; choose one; open the page in another browser. | The first asks to choose a password and then shows the settings; the second asks to log in. Without a login `/api/state`, `/api/save` and `/api/picture` answer 401. (`tests/test_station_setup.py` covers the password and cookies.) |
| SET-12 | P1 H | Type a wrong password three times, then the right one; *Save and restart*; change the password; *Log out*. | A wait after each wrong one; the login survives the restart; after the change other browsers must log in again; after *Log out* the login form. |
| SET-13 | P2 H | Read `data/station_login.json`; delete it and restart the station. | It holds a salt, a hash and a key, not the password, and is readable by its owner only; after deleting, the page asks to choose a password again. |
| SET-14 | P0 H/A | Stop the server; capture three cards at a station; restart the station (its page's *Restart only*, then `docker compose restart`, then a reboot); start the server. | The page shows 3 waiting after each restart; when the server is back each card is added exactly once and the station's `station_captures/` is empty. (`tests/test_station_uploads.py` covers it against a stand-in server.) Not yet tried with a real server. |
| SET-15 | P1 H | With captures waiting, change the server address on the setup page and save. Then *Send them to this server*; repeat with *Delete them*. | Nothing is sent on its own: the status shows them as kept, with the old address. *Send* adds them on the new server; *Delete* asks twice and removes the pictures. |
| SET-16 | P1 H | Stop the server, capture a card, set a wrong station token on the setup page, start the server; then correct the token. | The capture waits ("trying again"); after the token is corrected and the station restarted, it is added once. |
| SET-17 | P1 H | Open the setup page with a camera unplugged; plug it in without reloading; choose it and plug in another; unplug all. Also: a camera named in the station's `.env`. | The camera appears in the dropdown within a few seconds; the chosen one stays chosen when another appears; a saved camera that is gone shows as "not found right now". With `SCANNER_CAMERA_INDEX` in `.env` the field is fixed ("Set by ... change it there") and the dropdown cannot override it. |
| SET-18 | P1 H | A webcam that crashes when its lens is set (an LX-260325-A "USB 2.0 Camera"), with a focus lock saved for the station: start the station; then lock focus from the camera page. | At start the saved lock outside the camera's range is not applied (a warning in the station's log) and the camera stays connected; locking focus makes it reset once, after which its focus control is off for good (`data/camera_quirks.json`) and the page shows continuous autofocus. Tried by hand with one such camera. |
| ONE-01 | P1 H | One machine without Docker: `./scripts/start.sh`; open `http://localhost:5000` and `http://localhost:8080`; press Ctrl+C. | The server and this machine's camera station start together; the camera appears in the list under the machine's name; Ctrl+C stops both and the camera is released. **done** on a PC without a camera attached (2026-10-12); not with a camera scanning |
| ONE-02 | P1 I | `./scripts/deploy.sh --service` on a fresh machine; reboot. On a machine installed before 2026-10-12 (only `mtg-scanner`): `--update`. The same with `camera.type: remote` in `config.yaml`. | Two services, `mtg-scanner` and `mtg-scanner-station`, running and back after the reboot; `--update` on the older installation adds and starts the camera's service by itself; with `camera.type: remote` only the server's. Not tried on a real machine: the unit files were checked (`systemd-analyze verify`) and the script's service steps run with `sudo` / `systemctl` replaced by recorders |
| ONE-04 | P1 I | A server updated from before 2026-10-12 with review items of its own camera (`review_queue.station` NULL): open any camera's page. | The items are in that page's review queue and can be added or skipped; resolved once, they are gone from every page. **done** on a temporary database (`test_items_without_a_station_show_on_every_cameras_page`); not on an updated installation |
| ONE-03 | P2 H | `./scripts/start.sh --no-station`; `venv/bin/python app.py` with `camera.type: usb` in `config.yaml` and a webcam plugged in. | Only the server starts; it opens no camera whatever `camera.type` says (the webcam's light stays off). **done** for `camera.type: auto` without a webcam |
| SET-10 | P1 H | Pi camera in the container (`deploy/docker-compose.client-pi.yml`): a session of cards dropped onto a pile, with identical copies in a row and cards landing against the box walls. | Every card captured once, none waiting more than a few seconds; the Pi's temperature on the setup page stays under 80 °C. Not yet run from the container. |

## Suggested execution order and automation

1. **Smoke:** BOOT-01, STN-01, CAM-01, SCAN-01, READ-12, SCAN-08, STN-02, REVIEW-03, TRANSFER-02, STN-12, INV-04, IO-01, DECK-01, BACKUP-03.
2. **Data integrity gate:** remaining P0 cases, with before/after database snapshots and distinguishable capture files.
3. **Feature regression:** P1 cases, parameterized across supported games, finishes, areas, and formats where applicable.
4. **Hardware/usability:** camera cases on USB and Pi hardware, browser/mobile coverage, then P2 and workload measurements.

Automate parsers, finish selection, matching, quantity/split/merge/undo/batch logic, and deck rules as unit tests. Use Flask and Socket.IO test clients with temporary SQLite stores and stubbed services for integration tests. Use browser tests for filters, dialogs, persistence, selection, and downloads. Keep camera readiness/beep/drop/focus validation as recorded-frame tests plus physical acceptance tests. Agree performance targets on the intended device before marking workload cases pass or fail.

For each execution record: case ID and parameter values, application revision, device/browser, fixture version, actual result, pass/fail/blocked, and defect/evidence link. External live-site checks are separate smoke checks; deterministic regression tests must not rely on changing prices, deck listings, model output, or API availability.
