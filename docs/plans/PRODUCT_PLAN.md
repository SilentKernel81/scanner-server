# Turning the scanner into a product: plan

Date: 2026-10-22 (§2's Scryfall and Wizards rows and §3a researched the same day, from the sources listed at the end). Written against the three checkouts as they are today: this server (`main`,
36632a0), the standalone mirror (identical apart from an untracked `docs/plans/WINDOWS_STANDALONE_PLAN.md`)
and the Android app (189ea15). **Nothing here is implemented, nothing here was measured**: every
number below is quoted from a file of the project and says which; where a figure, a price or a legal
term is not in the files it is marked *to research*, and no guess is written in its place. The
legal section asks questions; it draws no conclusions - that is for a lawyer and the rights holders.

Like everything in these repositories, this document was written by an AI coding assistant directed by
the project's author (README.md, *How this project was built*). A product made of this code keeps that
statement, and keeps marking what was measured and what was never tried: it is the project's one
honest answer to "has this been tested?".

## 1. What there is, and what a product would be

Three programs, one code base and a port (CLAUDE.md, *Project Overview*):

| Program | Runs on | How a person gets it today | Released as |
|---|---|---|---|
| Server (`src/card_scanner/server/`, `core/`, `games/`; Flask + Socket.IO, Node.js 22+ for the OCR reader) | one Linux machine, Docker (`deploy/`), optional NVIDIA GPU | `git clone`, `docker compose up -d --build` (docs/INSTALL.md §1) | no release: the repository's two "releases" are videos |
| Camera station (`src/card_scanner/station/`) | a PC, a laptop or a Raspberry Pi with a USB webcam; a Pi camera module | the same clone, a second compose file, a setup page on port 8080 | none |
| Standalone desktop program (the mirror `../scanner`: server + station in one AppImage, `scripts/build-appimage.sh`) | one Linux PC with a webcam | a 235 MB AppImage from that repository's releases (v1.0 to v1.3, 2026-10-09 / 10) | 4 releases; "a real camera under it" is listed as never tried (PROGRAM_DOCUMENTATION, *The desktop program*) |
| Android app (`../mtg-scanner-android`) | Android 8+, 64-bit ARM | an APK downloaded from its releases page and installed by hand (INSTALL_GUIDE.md there, Part 1); `adb` is the developer's route | one release, v1.0 of 2026-10-09; `versionCode = 1` / `versionName = "1.0"` ever since (`app/build.gradle.kts`). Its README: of the release build "No card has been scanned with it yet" |

Three things set it apart, and they are not equal:

1. **The pile.** Drop cards one after another under a fixed camera; each is found by its outline,
   captured once when it lies still, read, matched to the exact printing and finish (about 1.7 s a
   card, README; 1.6 s on a Pi 5, docs/INSTALL.md). No other step of the project exists without it.
2. **Reading without a cloud AI.** The picture index (a 96-byte fingerprint per printing; 22 MB for
   112,765 printings, PROGRAM_DOCUMENTATION *Printing check*) and OCR read most cards; the vision AI is
   the last step and can be switched off. On the experiment's 128 AI-read pictures the picture and
   the collector line added 83.6% by themselves with 0 wrong (same section) - under the 85% line of the
   exit criteria for *removing* the AI (about 300 live cards, at least 85%, at most 0.5% wrong), which
   were written before any live data and have not been measured on it yet. So the AI stays a fallback,
   and a product must treat "needs an API key" as optional, which it already is.
3. **The collection behind it** - decks, trades, backups, Arena, 93 web routes (docs/FEATURES.md).

### Three candidate products

| | (a) The phone app alone | (b) Desktop program + webcam | (c) A scanning box with a server |
|---|---|---|---|
| Who it is for | anyone with a phone and a box; collectors who sort at the table | a collector at a PC; the owner's own setup | shops, serious collectors, several cameras |
| What exists | standalone mode: picture first, OCR on the phone, the AI optional, review, inventory, CSV / Moxfield (Android README) | the Linux AppImage; a Windows *plan* only (`WINDOWS_STANDALONE_PLAN.md`, untracked in the mirror; nothing run on Windows); no macOS | the server + stations as they are; an ESP32 station with a scale is a plan with no part bought (`docs/plans/ESP32_STATION_PLAN.md`) |
| What is missing for a stranger | an index without their own server (today "the index comes from the server - the only place it exists", `docs/plans/ANDROID_PICTURE_STANDALONE_PLAN.md`); a store listing or a trusted download; versions | Windows / macOS builds, a camera stand to recommend, a first run without a terminal, a camera tried under the packaged program | hardware to design, build, ship and support; installation on someone else's network; a login |
| Hardware the owner would support | none | none, unless a stand is sold | all of it |
| Measured so far | the phone's reading: 41 Pixel captures, 28 added by the picture alone, 24 ms a card (Android README); 13 cards in 33 s standalone on 2026-09-26 | the owner's PC and Pi; the AppImage was built and started, never scanned with | one home network, one owner's cards |

**Recommendation: (a) first, (c) as the second step or the premium option, (b) only as the owner's
own Windows wish or a cheap by-product of (c).** The phone is the one program a stranger can run in
ten minutes (the install guide's own estimate) with nothing to build, and its missing pieces are
software and an index to host, not hardware. The pile auto-capture - the differentiator - is in the
phone too (`detection/CardTracker.kt` is a port of `scanner.py`'s rules). What the phone cannot do is
be left running over a box for a thousand cards; that is the station's job, and the product for it
is (c). The server stays Linux-only by the owner's decision of 2026-10-21 (Windows plan §1), so (b)
and (c) are the standalone zip and the Docker server respectively, never a portable server.

## 2. Legal - questions to settle before any other work

None of this is settled by the files, and the plan takes no position. Each line is a question
with what to find out and whom to ask.

| Question | What the files say today | To find out |
|---|---|---|
| **May the owner sell what is under PolyForm Noncommercial?** | `LICENSE` (since 2026-10-19; MIT before, and copies of those versions stay MIT - README *License*). Its *No Other Rights* section says the terms do not "prevent the licensor from granting licenses to anyone else" | whether the owner, as the sole licensor, can offer their own copy under other terms (a lawyer); what the MIT history means for code published before 2026-10-19; whether a contributor other than the owner and the AI ever committed (the history says no, to confirm) |
| **Is code written entirely by an AI protected by copyright at all?** | README: "written by an AI coding assistant ... directed by the project's author"; the Android app also by Codex | what a license can enforce if the answer is "not, or only in part", in the owner's jurisdiction and in the markets the product would be sold in; whether the author's direction, selection and the documentation change that. A lawyer's question; it decides how much the license is worth, not whether to proceed |
| **Scryfall's data and pictures** | the server downloads the bulk card data (README *Acknowledgments*; `database.py` sends a `User-Agent`/`Accept` as Scryfall asks); the index is built from every printing's picture (~12 GB downloaded once, hashed, thrown away - PROGRAM_DOCUMENTATION); the phone calls `api.scryfall.com` directly and downloads ~80 MB of card data (Android README; `scryfall/Scryfall.kt`); the User-Agent calls itself "a personal collection scanner" (`core/image_index.py`) | **Read 2026-10-22** (their API page, rate limits, bulk data, images, Terms of Service): the data and images are free "for the primary purpose of creating additional Magic software ... as part of the Wizards of the Coast Fan Content Policy"; "You may not 'paywall' access to Scryfall data" (no payments, subscriptions or surveys for it); "You may not simply repackage, republish, or proxy Scryfall data. Your software must create additional value"; the User-Agent "must be accurate ... the name of your application, such as MTGExampleApp/1.0"; 10 requests/s, 2/s for search and named lookups, a 429 locks out for 30 s and ignoring it "may result in a temporary or permanent ban of your application"; "If you need to ... resolve a large number of card images, you must use the bulk data files" and `*.scryfall.io` has no rate limit (what the index build does already); images may not be cropped of the artist / copyright line, distorted, colour-shifted or watermarked; bulk prices are "dangerously stale after 24 hours ... not ... to power a storefront"; the Terms of Service: "Scryfall is not for advertising, trades, or sales" and no "undue burden ... through the use of automated means" - written for the site, but "Scryfall" is defined to include the API. **Still to ask Scryfall**: a paid tier (how does the no-paywall rule apply when the data stays free but the app does not?); whether a hosted card-data snapshot is "republishing" and a hosted index (fingerprints, no images) is "additional value"; one shared app name on thousands of phones under a per-application ban. **To check in the code**: the phone's User-Agent; every place a card picture is shown (the review screen's candidate tiles, deck covers) for a cropped artist line |
| **Wizards of the Coast** | README ends with "an unofficial fan project, not affiliated with or endorsed by Wizards of the Coast. Magic: The Gathering is a trademark" | **Read 2026-10-22** (Fan Content Policy, last updated 2017-11-15): "Free means FREE" - no payments, subscriptions, downloads or registration to access fan content; sponsorships, ad revenue and donations are allowed "so long as it doesn't interfere with the Community's access"; no Wizards logos or trademarks without prior written permission (the page's list of them is a set of logo images, so whether "MTG" may be in a name is not answered there); the notice "[Title] is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC." is asked for (README has a shorter one); Wizards may stop any use "at any time—for any reason or no reason". So **a paid app or a subscription is outside the policy** and needs Wizards' written approval (through support.wizards.com); a free app with donations or ads is inside it. **Still to ask Wizards**: "MTG" in a name or store listing; whether hardware sold with free software is fan content. The display name is already `Card Scanner` (`strings.xml`), but the repository, the APK file name (`mtg-scanner-<version>.apk`), the README titles, `~/.mtg-scanner` and the systemd unit names still say MTG |
| **The vision AI providers** | the user's own key, sent from the server or the phone | nothing the owner redistributes; if a hosted AI were ever offered (§3, costs), each provider's terms for resale |
| **Shipped third-party code** | Socket.IO client (MIT), Roboto (OFL), the PP-OCRv6 networks the phone ships (Apache-2.0, Android README), light-ocr itself (its license is not named in the files - *to confirm*), OpenCV, Flask, numpy ... (README *Acknowledgments*) | a license inventory with each file's notice for the store listing and the About page; nothing GPL (to confirm with a tool over `requirements*.txt`, `src/ocr/package-lock.json` and the Gradle dependencies) |
| **Privacy law** | the server keeps pictures of cards and nothing about people; the phone keeps everything on the phone; no telemetry (the manifest asks CAMERA and INTERNET only) | what a store requires anyway (§3, releases); what a tester programme that collects reading logs must tell people and ask of them (§4, phase 3) |

Order: the two license questions and Scryfall's answer first - a "no" to either changes the product,
not a phase. Wizards' policy decides the name and the listing. Everything in §4 is written as if
the answers allow it.

## 3a. What others make (researched 2026-10-22)

From the apps' store pages, their own guides and third-party comparisons; Google Play's and Printables' pages could
not be read by the tools used, and where sources disagree it says so. Prices in US dollars as listed.

| | Price | What it does | Notes |
|---|---|---|---|
| ManaBox (iOS, Android) | free with ads; PRO $2.49/month or $22.99/year | one card at a time, Quick Scan picks the first matching printing; decks, trades | card search works offline (offline *scanning* not confirmed); its guide: glare on sleeves stops border detection |
| Delver Lens (Android) | free with limits; ~$3/month per one listing (sources differ on what is free) | fast, cards and tokens | no source confirms offline scanning or a batch mode |
| TCGplayer app | free | Magic, Pokémon, Yu-Gi-Oh; sleeved cards; Trade-In | its FAQ: "one at a time"; does not tell black from white borders |
| Dragon Shield app | free | aimed at sleeved cards; TCGplayer prices | only a third-party source |
| Lotus Scan, Scrytics, Sparkheim | various | | Sparkheim *claims* its whole catalogue is on the phone; the Scrytics comparison is by Scrytics' own developer |
| X1PRO (TCG Verifier) | from $199 | a feeder only - your camera and app | |
| Card Slinger 3.0 (3D-printed) | print it, or finished units from its maker | a **passive funnel** guiding tossed cards to a phone running ManaBox | patent pending (Nov 2024); a remixer reports the original may not be modified or sold - check its license before printing |
| Arduino feeder by Fraens (3D-printed) | parts | a motor feeds cards one by one; a microphone **listens for ManaBox's success sound** to feed the next | license not stated in the article |
| CardMill (Kickstarter) | $575 / $750 | scans and sorts one method at a time; exports to TCGplayer, Moxfield, Deckbox, Archidekt | in production |
| Magic Sorter (Italy) | ~€2,500, over $3,000 delivered | scan and sort, **on a Raspberry Pi**, ~250 cards an hour | trouble with foils and full arts reported |
| TCGplayer Roca Sifter | $799 + $300/year (one source), lease-to-own (another) | sorts for stores | needs a TCGplayer seller account and internet |
| SortSwift | $8,999 (9 bins) / $24,999 (29 bins) | store sorters | |
| PhyzBatch-9000 (TCG Machines) | leased to stores | cameras on both sides of a glass plate | |

What it means for §1's choice:
- **Free phone scanners are common**, so (a) does not compete on price; it competes on reading without a cloud AI,
  and on the collection beside it.
- **The station sits in an empty middle**: phone apps go one card at a time, feeders (from $199) still need a
  recognition app, sorters start around $2,500. A self-hosted station reading by picture at about 1.7 s a card
  (README) is cheaper than a sorter.
- **The feeders lean on a phone app** - the Arduino rig listens for ManaBox's sound to know a card was read. The
  station already *knows* when the next card may come (`station_client.py`: `Station._auto_captured`, where it sends
  `captured` - the capture beep): it can tell a dropper to release the next card itself (§4, phase 5). The owner has a 3D printer to try one - of the project's
  own design, not a copy of either printed design above.
- **Every paid competitor's terms with Scryfall and Wizards are not public**; how ManaBox and Delver Lens charge
  subscriptions within §2's rules is a question to ask, not to infer.

## 3. Gaps, by area

Each row says what the files record as measured, tried or never tried.

### Installation

| | Today | A product needs | Measured / tried |
|---|---|---|---|
| Server | Docker on x86-64 Linux, Node 22+ inside the image, glibc 2.38 (Debian 13 base), optional NVIDIA toolkit (docs/INSTALL.md, CLAUDE.md *Docker images*) | for (c): a one-command install or a prepared image on the box's own computer; nothing for (a) | the owner's server and a Pi 5 station; the DOCKER_GUIDE walkthrough filmed (75 s video) |
| The first picture index | built by a button or `scripts/build_image_index.py`: ~12 GB from Scryfall, hours, 8 requests at a time (PROGRAM_DOCUMENTATION *The index*); never started automatically (`UPDATE_SCHEDULE_PLAN.md`) | a **ready-made index to download**: 22 MB measured for 112,765 printings (hashes 10.8 MB, ids 4.2 MB, the table 6.6 MB) - the format the phone already takes from a server (`GET /api/image_index/download`, resumable, pinned by SHA-256) | the download: a Flask test client and the owner's phone (116,331 printings, 21 MB in 3.5 s). Hosting it anywhere: never |
| **The index and the card data must match** | a picture alone adds nothing while the index lacks any printing of the card data (`PrintingCheck.missing_printings` must be 0; on the phone "the two downloaded on different days", Android README) | a hosted index is published *together with* the card-data snapshot it was built from, or the phone keeps asking Scryfall for data the index does not cover and the headline feature silently does nothing. A design decision of phase 2, not a footnote | the rule itself: tests only |
| Card data | 75 MB (docs/INSTALL.md, the Docker log), ~150 MB (the AppImage's first start, same file), ~80 MB on the phone (Android README) - three figures from three places, not reconciled here | one snapshot per index generation, from the same host | - |
| Desktop | Linux AppImage only; Windows planned in detail (shims for `fcntl`, `os.kill`, `execv`, the V4L2 backend; 6-9 days estimated there, "step 4 is the one that can grow"); macOS not even planned | (b): Windows first, then macOS; a signed program (SmartScreen / Gatekeeper warn on unsigned files, Windows plan §7) | the AppImage: started, `--quit`, the lock; never with a camera |
| Vision AI | the user's own key (Gemini, OpenAI, Anthropic, OpenRouter on the phone) or a local Ollama | stays optional; the first-run wizard must make "none" the plain default and say what review then means | Flash-Lite ~$0.79 per 1,000 cards (README, Sept 2026) - the only price in the files |

### Security

| | Today | A product needs |
|---|---|---|
| Login | none on the server's pages (PROGRAM_DOCUMENTATION *Known limitations*: "for a home or shop network, not the internet"); an optional **settings password** on the risky actions (*The settings password*: scrypt hash, signed cookie, 12-hour sessions, back-off); DNS-rebinding and cross-site requests refused (`server/access.py`) | (a): nothing - the phone talks to no server of the owner's except an index download. (c): a login, or a clear statement that the box lives on a trusted network; a shop will ask |
| Transport | plain HTTP everywhere; the passwords "cross the network unencrypted" (same section); the station token optional (`stations.token`) | HTTPS for anything hosted (the index download at least); for (c) a documented reverse-proxy setup or built-in TLS |
| Keys | masked in the browser, `data/api_keys.env` mode 600; on the phone AES-256-GCM under an Android Keystore key (Android README) | fine as is for (a); an audit for (c) - "run, not audited" (README) |

### Releases and updates

| | Today | A product needs |
|---|---|---|
| Android | `versionCode = 1` through every update; one release of 2026-10-09 that predates the whole picture-reading work (10-20/21); installed from a downloaded APK; the build signed with the owner's release key (its CLAUDE.md: raise `versionCode` for a new release) | a version per release and a changelog; a store listing (Google Play: a developer account, a **privacy policy**, the **data-safety form**, target-SDK upkeep each year - `targetSdk = 36` today, `compileSdk 37.2`; the exact current requirements *to research*), or a signed APK channel outside the store with its own "new version" check; a "new version available" notice in the app (none today) |
| Server / standalone | `git pull && docker compose up -d --build` (README *Maintenance*); the AppImage attached to a release by `.github/workflows/appimage.yml`; no update check for the program itself (the card data has one, `Game.check_for_update`) | a program-version check and a one-step update for (b) and (c); schema migrations already run on start (`storage.rebuild`) - keep that |
| Card data and the index | automatic updates since 2026-10-22, off by default; "never tried: a month-long run, a Pi whose network comes up late" (docs/FEATURES.md) | for a hosted index: a publishing job that builds a generation and the matching card-data snapshot, verifies it, publishes both at once |

### Reliability

| | Today |
|---|---|
| What was measured | one owner's cards, cameras (an Anker C200 on a Pi 5; a Pixel 10), network and lighting. The auto-capture thresholds "come from measured camera noise and a live drop test" on that setup (CLAUDE.md); the phone's stillness limit "was measured on the Pi 5's webcam, not yet on a phone's camera" (Android README) |
| What the docs mark never tried (a selection) | the Settings page's Cameras section with a camera connected; a card back stopping a real camera; the picture-first reading on a live scan with OCR on; ManaBox import on a real file; a Pi camera module over a whole pile; the AppImage with a camera; a month-long run; the Android release build scanning a card; the phone's token and Host check |
| Automated tests | the server: 59 files, about 960 `def test_` on 2026-10-22; the phone: parity tests against the server's reference files, a reliability suite on the emulator (Android README). Nothing drives a camera |
| What a product adds | other people's phones (sensors, autofocus, thermal limits), other webcams, sleeves, dim rooms, 500-card sessions. None of that can be done at the desk: it is what the tester phase (§4, phase 3) is for |

### Usability

| | Today | A product needs |
|---|---|---|
| First run | the server downloads the card data and shows a banner; the phone asks for the camera and starts on the camera screen; the AI, the server address and the index are in Settings | a first-run wizard on the phone: mount the phone (the install guide's Part 2 as screens), standalone or server, download the index + card data, AI or none, one test card |
| Help without a terminal | docs/INSTALL.md *Troubleshooting*, the station's console log, `data/logs/*` (CLAUDE.md *Logs*) | a problem report from inside the program: the last capture, the reading record (`data/logs/reading.jsonl` exists on the server - `core/reading/record.py`; **the phone has no reading log at all**: new work), the versions, sent where the owner can read it - only with the person's consent |
| Documentation | written for someone who runs Docker; "British-leaning, matter-of-fact" (docs/*) | a getting-started page per product with pictures of the mount and the box; the honesty markers kept but moved out of the first page |
| Name and identity | `Card Scanner` on the phone and the AppImage; MTG in the repositories and file names (§2) | one name across store, program, repository and data folder, chosen after the trademark question |

### Running costs, if anything is hosted

Nothing is hosted today, so nothing is known. To work out before phase 2: the index + card-data
snapshot (about 22 MB + the card data per download, once per phone per generation - bandwidth per
1,000 installs; a static file host is enough since the server's download route is plain files with
ETags), the publishing job's machine (the first build downloads ~12 GB from Scryfall: a job that
runs *once* and then extends - never a rebuild per release), a domain and TLS, a privacy policy's
hosting, the store's developer fee (*to research*), and the owner's time answering problem reports -
the one cost no file can estimate. A hosted AI service (the owner's key behind an API) is **left
out**: it turns a one-off download into a running bill per card and the provider's terms into the
owner's problem; the phone's own picture reading is the way round it.

## 4. Phases

Effort is not estimated here: the only comparable figure in the files is the Windows plan's 6-9 days
for a zip that does what the AppImage does, with the warning that its first run on Windows "is where
every *to verify* is found out". Expect the same shape for every phase below.

**Phase 0 - decide the product and settle the legal questions** (no code).
- §1's choice written down; §2's questions asked, answers filed in this document.
- Touches: this file; README.md and the Android README only where a name or a statement changes.

**Phase 1 - the index and the card data as a published pair** (server repository; the standalone
gets it by merge).
- A publishing script beside `scripts/build_image_index.py`: build or extend the index, snapshot the
  card data it was built against, write one listing (generation, versions, SHA-256s) in the shape of
  `GET /api/image_index/download`, upload to a static host over HTTPS. The route's contract is the
  contract: the phone's `reading/IndexDownload.kt` must not need a second code path.
- The User-Agent strings (`core/image_index.py`, `core/database.py`) say what the product is.
- Touches: `scripts/`, `core/image_index.py`, `server/stations_api.py` (nothing in the routes themselves
  if the listing's shape is kept), `tests/test_index_download.py`, PROGRAM_DOCUMENTATION *The index for a phone*.
- Never tried: any of it. Check: a phone with no server of its own downloads the pair, `missing_printings`
  is 0, a card is added by the picture.

**Phase 2 - the phone stands alone** (Android repository).
- The index + card-data source as a setting with the hosted pair as the default; the matching rule kept
  (the phone refuses a pair whose versions do not match).
- `versionCode` / `versionName` raised per release, a changelog, a "new version" check against the
  releases page or the store; a privacy policy and the data-safety answers written from what the app
  actually sends (Scryfall, the AI provider the person chose, the index host; nothing else).
- The first-run wizard (§3, usability); the problem report with a reading record on the phone
  (the server's `ReadingRecord` fields as the model, so one `scripts/reading_report.py` reads both).
- The name decided in phase 0 everywhere (repository, APK name, titles, `applicationId` stays).
- Touches: the whole app's settings and first screens; its README's *What has been tried* table grows.
- Check: a fresh phone, no server, no AI key: install, wizard, ten cards from the pile - how many added
  by the picture, how many to review, nothing wrong.

**Phase 3 - closed testing** (10-20 people, their own phones, their own cards).
- With consent: their reading records and problem reports, read with the report script; the
  thresholds re-measured on their cameras (CLAUDE.md: "re-measure before changing them").
- The docs' *never tried* list for the phone worked through, each line turned into "tried on <phone>,
  <date>, <result>" in the Android README - the same table it has today.
- Nothing is hosted beyond the index pair; the AI stays the tester's own key or off.

**Phase 4 - publish the phone app** (store or signed channel, per phase 0's answer).

**Phase 5 - the scanning box** (both server repositories, hardware).
- The station's hardware as a recommended list first (a Pi 5, a named webcam with `focus_absolute`, a
  box, a mount - the one setup the docs call tested, docs/INSTALL.md *On a Raspberry Pi*), a designed
  stand only after that list has been built by someone else from the description.
- One-click server: a prepared image for the box's computer, HTTPS, a login (§3, security) - the server
  changes are generic and land in `scanner-server`; the standalone merges them.
- Windows for (b) by the standalone's plan, in the mirror only, as new files (its §2 rule).
- **A card dropper the station drives from the Pi's GPIO pins** (the owner's idea, 2026-10-22; 3D-printed, of the
  project's own design - §3a). The station tells it to release the next card at the moment it already says so to a
  person: `station_client.py`, `Station._auto_captured`, where it sends `captured` - "the capture beep - the signal to
  drop the next card: once the image is taken and a focus probe started by this capture ... is done" (it waits up to
  2.5 s for the probe). Only then: never while a refocus sweep runs (about 8 s), never while a card waits for
  confirmation (auto-add off), never after a card back stopped auto-capture, never while the camera is lost. One
  pulse per card, so a missed capture cannot let the stack run on. Needs: the GPIO device in the station's container
  (the Pi-camera image runs privileged already; the USB-webcam one would need `/dev/gpiochip*` passed in), a
  setting to switch it on per station (`CAMERA_SETTINGS`), and the auto-capture thresholds measured again - they
  come from hand drops (CLAUDE.md), and a mechanism drops differently.
  **Card damage comes first** - the owner's concern, and the reason to measure before building further:
  - a *roller* that pulls a card from a stack rubs the face of the next one (scuffs, marks on foils) and can bend it;
    a *gravity* magazine with a thin gate or pusher that only touches the bottom card's edge is gentler, but the gap
    must stay under one card's thickness (about 0.3 mm unsleeved, more sleeved - to measure with calipers) or two
    come out at once;
  - the drop onto the pile: a short fall, a soft landing, corners not striking first;
  - try it on commons and on sleeved cards first (a sleeve takes the wear), look at faces, edges and corners after
    many passes, and keep valuable and foil cards out until that is measured.
  **The station's side is written** (2026-10-22: `station/dropper.py`, Settings > Cameras > Card dropper; PROGRAM_DOCUMENTATION,
  *The card dropper*) and tested with a stand-in pin. **The mechanism is designed** (2026-10-22/23; since 2026-10-30 its own repository,
  `SilentKernel81/card-dropper` - wheels with silicone tyres under the stack, two of three axles driven by
  servos through one-way bearings, an adjustable gate, both card sizes; a first design with a pusher was dropped) and
  checked in CAD; its first parts printed 2026-10-29/30. Never tried: an assembled feeder, a real pin, a card released.
- The ESP32-with-a-scale station stays a plan until phase 5 has a box to put it under.

## 5. Left out on purpose

- A hosted AI service, a hosted collection ("sync"), accounts on the owner's servers: each turns the
  product into a running service. The project is built so that a station keeps nothing and the server
  keeps everything *locally*; a product keeps that.
- Other card games before Magic is a product: `games/` is ready for one (docs/FEATURES.md), the index and
  the reading rules are measured on Magic only.
- A portable server (Windows / macOS server): the owner's decision stands (Windows plan §1).
- Reconciling the three card-data sizes, the test counts or the dates in older documents: cite, do not
  correct, until a phase touches them.

## 6. Open questions and decisions for the owner

1. **Which product** - (a), then (c), as recommended; or (b) because it is the owner's own setup?
2. **Relicense or dual-license?** The owner's copy under commercial terms while the public repositories
   stay PolyForm Noncommercial; or close the source. (A lawyer's question first - §2.)
3. **The name**, once Wizards' policy is read: keep `Card Scanner`, or a name that is also a brand.
4. **Scryfall**: ask for permission for a hosted index and card-data snapshot, or design the phone to
   build nothing and download nothing of theirs except through the person's own requests?
5. **Store or not**: Google Play with its yearly target-SDK and policy upkeep, or a signed APK channel
   with a built-in update check? (iOS is nowhere in the files: a Kotlin port's second port.)
6. **Who tests**: 10-20 people the owner knows, or a public call? What they are told about the reading
   records, and what they get for it.
7. **Price and support**: free app plus a paid box, a paid app, or a one-time price per program? §3a
   has what others charge (free to $2.49/month for phone apps, $199 to $24,999 for feeders and sorters);
   §2 has what Scryfall's and Wizards' terms say about charging at all - read both before choosing.
8. **Time**: the owner's own, with this assistant - the only development resource the project has ever
   had, and the one every phase above assumes.

## Sources (read 2026-10-22)

Scryfall: [API documentation](https://scryfall.com/docs/api), [rate limits](https://scryfall.com/docs/api/rate-limits),
[bulk data](https://scryfall.com/docs/api/bulk-data), [images](https://scryfall.com/docs/api/images),
[Terms of Service](https://scryfall.com/docs/terms). Wizards: [Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy).
Apps: [ManaBox on the App Store](https://apps.apple.com/us/app/-/id1460407674), [ManaBox scanner guide](https://manabox.app/guides/scanner/getting-started/),
[ManaBox paywall (Adapty)](https://adapty.io/paywall-library/manabox/), [Delver Lens (AppFollow)](https://appfollow.io/android/mtg-card-scanner-delver-lens/delverlab.delverlens?country=us),
[TCGplayer App FAQ](https://help.tcgplayer.com/hc/en-us/articles/115009506407-TCGplayer-App-FAQ), [Ricoh/PFU on scanning cards](https://www.pfu-us.ricoh.com/blog/scan-pokemon-cards),
[Scrytics' comparison](https://scrytics.com/blog/best-mtg-card-scanner-app-2026), [Sparkheim](https://mwm.ai/apps/sparkheim-mtg/6792481720).
Machines: [Eldwyn: sorting machines 2026](https://eldwyn.app/blog/mtg-card-sorting-machine-2026/), [TCG Verifier: sorters compared](https://www.tcgverifier.com/blog/automatic-tcg-card-sorters-compared),
[CardSellerTools](https://cardsellertools.com/machines), [SortSwift](https://sortswift.com/features/super-sorter),
[Arduino blog: a 3D-printable scanning rig](https://blog.arduino.cc/2025/03/27/quickly-digitize-your-magic-deck-with-this-3d-printable-scanning-rig/),
[Card Slinger 3.0](https://www.printables.com/model/1034404-card-slinger-30-for-mtg-manabox-app-for-sleeved-an), [Card Slinger on Thangs](https://thangs.com/m/1239254).
