# MTG Card Scanner - server and camera stations

A camera-based scanner for Magic: The Gathering cards. Drop cards onto a pile under a camera:
each one is found in the picture, captured once, identified down to the exact printing and
finish, and added to a collection you can filter, build decks from and export to Moxfield.

> **Built with AI.** All of this project - the code, the tests and this documentation - was
> written by an AI coding assistant (Claude, through Claude Code), directed by the project's
> author. See [How this project was built](#how-this-project-was-built).

It is made of two kinds of programs on your network:

- **Camera stations** - any number of them. A small computer with a USB webcam (a PC, a laptop,
  a Raspberry Pi), or an Android phone. A station finds the card and decides when to capture
  it, and sends one picture per card.
- **One server** - reads the pictures, finds the printing, and keeps the collection, the decks
  and all settings. You use it from a browser; every camera has its own page there.

```
  Pi + webcam ──┐
  laptop + webcam ──┼── one picture per card ──>  server  <── browser: a page per camera,
  phone ────────┘                                (OCR, AI,        the collection, decks
                                                  collection)
```

The server needs no camera, and a station keeps nothing: it can be unplugged, replaced or
reinstalled without losing a card. This repository grew out of the single-machine
[scanner](https://github.com/SilentKernel81/scanner), which is a separate project; a single
machine can still be both here, running the server and a camera station side by side (see
[docs/INSTALL.md](docs/INSTALL.md)).

## How it works

1. **Find the card** (on the station) - each camera frame is searched for the card's outline:
   the largest four-sided shape with a card's 88×63 mm proportions. This takes a few
   milliseconds and isn't fooled by foil glare inside the card.
2. **Capture** (on the station) - once the card lies still and sharp, it is cut out and
   perspective-corrected into a flat, upright image. You hear a beep: drop the next card.
3. **Read** (on the server) - [light-ocr](https://github.com/arcships/light-ocr) reads the
   name, collector number and set code in about a tenth of a second. Only when that isn't a
   certain match - full-art and borderless cards, a soft collector line - is a vision AI asked.
4. **Foil check** - modern cards print a star (`HOB★EN`) instead of a dot (`HOB•EN`) next to
   the set code on foil copies. OCR reads it; when it can't, the AI is shown a zoomed crop of
   that corner.
5. **Match the printing** - set code + collector number (unique for every printing), checked
   against the name, are looked up in a local copy of [Scryfall](https://scryfall.com)'s card
   data, which also provides prices, images and which finishes each printing exists in.
6. **Add** - a confirmed printing goes straight into the *scanned cards* (with an Undo);
   anything uncertain waits in that camera's review queue, and scanning goes on. When you have
   checked a session, **Add to collection** moves the scanned cards into your collection.

## Features

The short list; [docs/FEATURES.md](docs/FEATURES.md) goes through everything the program does,
section by section, and says what was never tried.

- **Several cameras at once**, each with its own page: live view, review queue, Undo, scanned
  count and inventory location. One shared scanned list, which can be narrowed to one camera -
  to add just that camera's cards to the collection, or clear them and scan its pile again.
- **Automatic or manual capture** - start auto scanning and just drop cards into the box (about
  1.7 s per card), or capture on demand.
- **Picture first, OCR in doubt, AI last** - the picture of a card is matched against every printing
  (about 0.02 s), and a clear match settles the card; in doubt OCR reads it, and the vision AI handles only
  what is still open (both can be switched off in Settings; with both off the picture decides alone). Providers: Google Gemini, OpenAI,
  Anthropic Claude, or a self-hosted model via Ollama (or another OpenAI-compatible server).
- **Exact printing identification** from the set code and collector number, with name
  matching that tolerates misreads, accents ("Fili" → "Fíli"), flavor names ("Bucklebury
  Ferry") and shortened legendary names ("Thanos" → "Thanos, the Mad Titan").
- **Foil detection** from the ★/• marker, combined with printing data: printings that only
  exist in foil (or only non-foil) are known for certain.
- **Nothing is lost on the way**: a station keeps scanning while the server or the Wi-Fi is
  away and sends its captures when it is back; captures waiting on the server survive a
  restart; a capture sent twice is one card.
- **Focus that stays sharp** on a USB webcam: the sharpest position is found once, locked, and
  followed as the pile grows.
- **A review queue** for what the program is not sure of: you search, pick the printing and
  finish, and add it - and a button on any entry sends one copy **back to review** when the
  wrong printing was added.
- **Collection** with locations and tags, bulk edits, statistics, scheduled backups, and import /
  export (the app's own CSV, Moxfield, and ManaBox import - not yet tried on a real ManaBox file).
- **A deck builder** for 12 formats (Commander, Standard, Modern and more) with ownership,
  legality and colour-identity checks, suggestions from EDHREC, preconstructed decks, and a
  buy list of the copies you do not own.
- **Trades and a buy list:** set cards aside for a trade until you confirm it, import someone
  else's collection file to browse it, and put its cards in a trade as what you would receive,
  or on a buy list grouped by seller. Kept apart from your own collection.
- **MTG Arena:** your Arena collection and decks can be imported, and any deck exported for
  Arena's Import button.
- **Android app** ([mtg-scanner-android](https://github.com/SilentKernel81/mtg-scanner-android))
  as a station: the phone finds and captures, the server does the rest. It also works on its
  own, without a server.

## Screenshots

<p>
<img src="docs/images/collection-grid.jpg" width="49%" alt="The collection as card images">
<img src="docs/images/deck.jpg" width="49%" alt="A deck with its checks, mana curve and cards">
</p>
<p>
<img src="docs/images/trades.jpg" width="49%" alt="A trade: the cards given and the cards received from someone else's collection">
<img src="docs/images/other-collections.jpg" width="49%" alt="Browsing someone else's imported collection">
</p>

Left to right: the collection, a deck, a trade, and another person's imported collection. The
[full list of features](docs/FEATURES.md) has more screenshots (the review queue, statistics,
the buy list, a station's setup page, the Arena collection). They show the author's own
collection; the trade and the person it is with are made-up examples.

## Requirements

| Part | Needs |
|---|---|
| Server | A Linux machine with Docker (x86-64). ~1 GB for the image, ~300 MB for the card data. An NVIDIA GPU is optional (OCR in 0.1 s instead of 0.7 s per card) |
| Camera station | A Linux machine with a USB webcam - x86-64 or ARM64 (a Raspberry Pi 5 is tested) - with Docker, or Python 3.10+. A webcam with manual focus control (`focus_absolute`) is best |
| Phone | Android 8 or newer, with the app |
| Vision AI | An API key for Gemini, OpenAI or Anthropic, **or** an Ollama server with a vision model (the server can run beside it) |
| Network | The stations must reach the server (Wi-Fi is enough: about 1 Mbit/s per camera while its page is open). Internet for the card data, card images and cloud AI providers |

## Installation

[docs/DOCKER_GUIDE.md](docs/DOCKER_GUIDE.md) walks through a server and a camera station step by step, with
what each command should print (and a [75-second video](https://github.com/SilentKernel81/scanner-server/releases/tag/demo-video) shows it); [docs/INSTALL.md](docs/INSTALL.md) is the reference for every part. In short:

```bash
# the server
git clone https://github.com/SilentKernel81/scanner-server.git && cd scanner-server
mkdir -p data scanned_cards
docker compose up -d --build              # the first start downloads the card data
# open http://<server>:5000 and choose the AI in Settings

# a camera station, on the machine with the webcam (same repository)
cp .env.station.example .env              # edit it: the server's address, the camera, a name
docker compose -f deploy/docker-compose.client.yml up -d --build
# it appears on the server's page by itself
```

### As a desktop program

On one Linux computer with a USB webcam the whole thing is a single file: the AppImage built by
`scripts/build-appimage.sh` (attached to each release) holds the server and the camera station.
See [docs/INSTALL.md](docs/INSTALL.md#as-a-desktop-program-appimage).

## Choosing a vision AI provider

On a camera's page, **Settings → Card recognition**: pick a provider and a key field appears (keys you
saved before are shown masked, e.g. `AIza…3f9Q`, never in full). They are stored on the server
in `data/api_keys.env` (readable only by you) and used immediately. The choice is one for all
cameras.

| Provider | Setting | Key / endpoint |
|---|---|---|
| Google Gemini | `gemini` | `GEMINI_API_KEY` ([get a key](https://aistudio.google.com/app/apikey)) - default model Flash-Lite: same reads as Flash on a test of 10 cards at ~1/4 of the cost (~$0.79 per 1000 cards, Sept 2026) |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic Claude | `anthropic` | `ANTHROPIC_API_KEY` |
| Local (Ollama, vLLM, LM Studio) | `local` | `LOCAL_AI_ENDPOINT`, or `vision_ai.local.endpoint` in `config.yaml` |

Keys can also be put in `.env` beside the compose file; keys saved in the web interface take
precedence. The default provider is `vision_ai.provider` in `config.yaml` (or
`VISION_AI_PROVIDER`).

**Local models**: pick a vision-capable model in Settings - the list is loaded from your Ollama
server. Thinking is switched off for Ollama requests, so "thinking" models such as `qwen3.5`
answer in about a second instead of reasoning for tens of seconds. The model is preloaded when
you start auto scanning and kept loaded for 30 minutes.

`qwen3.5:9b` is the recommended model (about 1 s per card on a desktop GPU). It needs more
than 6 GB of GPU memory; on smaller GPUs `qwen3.5:4b` works, but it is slower on weak GPUs and
more often mistakes regular cards for foil - see docs/PROGRAM_DOCUMENTATION.md for the comparison.

**Prompts**: **Settings → Card recognition → Edit prompts** shows what the AI is asked (card
identification and the foil marker check) and lets you change it - for all models or just the
one in use. **Test on last capture** runs the edited text on the last card read before you
save it. **Restore default** goes back to the built-in prompt. Only the instructions are
editable; the answer format is added automatically.

The foil check sends one small request for the cards whose marker OCR could not read. It is
free with a local model; for cloud providers you can turn it off with
`vision_ai.detect_foil: false`.

## Using the scanner

Open `http://<server>:5000`. The start page lists your cameras - connected or not, whether a
card is in view, whether it is scanning, how many cards wait for review - each with a link to
its own page, `http://<server>:5000/scan/<id>`. **Collection** in the top bar is your
collection and decks.

### Scanning cards

On a camera's page:

1. Put a card in the box. It gets an outline in the video and the status pill shows
   **Focusing** / **Stabilizing**, then **Ready** once the card is still and sharp.
2. Click **Start auto scanning** and drop cards onto the pile, or **Capture card** for one.
3. **Drop the next card when you hear the capture beep.** It sounds once the image is taken
   (every few cards the scanner also checks the focus first, ~1 s, while the status shows
   *Capturing - wait for the beep*); then the status shows **Captured - drop the next card**,
   and the next capture happens when a new card has landed and settled. The drop is recognized
   by the motion and by where the new card lands, so two identical copies in a row are both
   captured.
4. The card panel shows what was added (name, set, finish) with an **Undo** button; the
   *Processing* counter shows how many captures are still being read.

Only cards whose exact printing is confirmed (set code + number, or name + number) are added
automatically. Anything less certain goes to that camera's **Review** queue and scanning goes
on. Click the *Review* counter when you're done: each item shows the capture next to the
suggested card and what was read, with a search to correct it; **Add** adds the card shown (and
opens the next), **Skip** / **Delete** drop the capture, **Close** keeps the rest for later. A
card whose name can't be read (runes, another language) is found by its set code + number
alone - leave the name empty.

**Confirm each card instead:** turn off **Settings → Cameras → Add cards automatically** on that
camera's page. Each capture is then shown with its printing, price and finish (pre-selected
with the reason, e.g. *"Foil: ★ next to the set code"*) and waits for **Add to inventory** or
**Skip**; the camera holds its next capture until you choose.

**Sleeved cards:** turn on **Fixed area** in the camera panel. The first time, drag a rectangle
on the video around where the cards land (or click **Use detected card**); **Area** redraws it.
Cards are then judged by the image inside that area instead of their outline, which a pile of
sleeves confuses, and the photo that is read is exactly that area - draw it around the whole
card.

**With the phone:** in the app's Settings, turn on *Send cards to a scanner server* and enter
the server's address. The phone shows the camera and each result itself; its page on the
server has its scanned cards and its review queue. Without a connection the phone keeps
capturing and sends the cards when it is back.

### Searching manually

Type a name in **Search**, optionally with the **Set** code and **Number** from the card's
bottom-left corner (e.g. `HOB` and `14`) - together they go straight to the exact printing -
and a **Treatment** (e.g. Borderless). If more than one printing matches, choose yours from
the thumbnail grid. After a capture, the fields are filled with what was read, so you can
correct a misread and search again.

### Scanned cards

What you scan is kept apart from your collection until you say so. The **Scanned** count in the
top bar opens the list; on a camera's page it counts and shows that camera's cards.

- The **camera** selector narrows the list to one camera or shows all of them.
- **Add to collection** moves what the list shows - one camera's cards, or everyone's - into
  the collection; you can choose one of your locations or type a new one (*Box #1*, a binder)
  first.
- **Clear** deletes what the list shows, never the collection: with a camera chosen, only that
  camera's scanned cards and its review queue, to scan its pile again.
- Each entry shows a thumbnail of what was captured: hover to see all its captured copies, or
  click the thumbnail to open them larger. You can filter, sort, and edit quantity / condition /
  finish (changing the finish of part of a stack splits it; the price follows the finish).
- **Settings → Cameras → Scan into location** puts everything that camera scans next into a location.
- **Settings → Cameras** renames a camera, sets its location, takes back its last card, or
  forgets it (with its scanned cards and review items).

An entry two cameras both scanned (the same printing into the same location) is one entry;
narrowed to one camera it shows that camera's copies and can't be edited from there - choose
*All cameras* for that.

### Collection page

**Collection** in the top bar (`http://<server>:5000/collection`) is the place to manage your
cards; **Decks** beside it (`/decks`) the place to build decks. The collection page works on
a phone too; the deck pages are made for a screen with a pointer.

- **Inventory** - filter by name, color identity, type, rarity, set, finish, location, tag and
  price (in the search field, `set:HOB` finds that set only - not every card with "hob" in its
  name; also `name:`, `type:`, `rarity:`, `tag:`, `loc:"Binder 2"`, `finish:`, `number:`, and a
  minus in front to leave them out: `-set:HOB`). The filters are still set when you come
  back to the page, and the list shows 25, 50, 100 or 200 cards a page. To select a few cards
  in a row, tick the first, hold Shift and tick the last. Also in the search field: `qty:>4`
  finds the cards you have more than four of. Click a badge on a row (rarity, location, tag...)
  to see only those cards; the active filters are listed above the cards, each with an × to
  take it off, and are part of the page's address, so a filtered view can be bookmarked. Hover
  the small card picture by a row's buttons to see it large. A delete or a change to several cards waits six
  seconds with an **Undo** button (Ctrl+Z) before it happens. **Export** asks whether you want
  everything, the cards shown or the cards ticked. Keys: `/` search, ← → pages, Ctrl+A select
  all shown, Del delete the selection, Esc clear it. Tick **Not in a deck** to see only
  the cards no deck uses yet; switch between the list and a grid of card images; tick entries to
  move them to a **location**, tag them (*trade*, *keep*), change their condition, add them to
  a deck or delete them in one step. Copies of the same printing can be in two locations -
  moving part of a stack splits it.
- **Cards to trade or sell** (Trades tab, **Find cards to trade or sell**) - the cards no deck
  uses and that EDHREC does not list for the commander of any of your decks, most valuable first;
  narrow it to one location (a binder, a box) or all, tick some and **Set aside for a trade**. It asks EDHREC about each deck with a commander, so
  it needs the internet (the first time takes a moment).
- **Export / import** - the **Export…** menu writes the collection for Moxfield (the same file
  imports into Archidekt: choose its **Moxfield** preset and **Set columns** - tried
  2026-10-14), or as
  **Card Scanner (everything)**: the app's own CSV with every entry's location, tags, finish
  and printing, which **Import** reads back exactly as it was (the Android app writes the same
  file). **Import** also takes a Moxfield collection CSV - each row is matched to its printing
  by set code and collector number (by name when that fails, which is reported).
- **Decks** (Magic; pages of their own, `/decks`) - Commander, Standard, Pioneer, Modern,
  Legacy, Vintage and Pauper. The list shows each deck by its commander's picture; a deck
  has an address (`/decks/<id>`) and two views - **Columns**, the decklist as text, and
  **Stacks**, the cards themselves - grouped by type, cost or colour. In the list a deck is
  shown as a card, its **cover**: the commander (with two, a button turns to the other), or
  for a deck without one its most valuable card - or any card of the deck you choose with
  its **Cover** button. **Arena** shows the deck as a list for MTG Arena's Import button -
  only the cards that exist on Arena, and which ones were left out. A deck copied out of
  Arena can be pasted into **New deck**. (Tried with a few lines pasted into Arena, which made the deck;
  a whole deck with a commander or a sideboard has not been tried.) The same window says
  whether you could **build the deck in Arena**: how many of its cards your Arena
  collection has, which you would craft and what that costs in wildcards.
- **Your MTG Arena collection** (Magic) - the collection page has a switch **Physical |
  Arena**. Arena shows what you have in the digital game: run
  [mtga-export](https://github.com/SilentKernel81/mtga-export) (a separate program by the
  same author, for Linux with Steam / Proton, that reads the game while it runs), then **Import from
  Arena** with its `mtga_collection.json` (your cards) and `mtga_decks.json` (your Arena
  decks) - both at once or one at a time. Each import replaces the one before - with the deck
  file, every Arena deck, also one made or copied here, is replaced by the file's decks (paper
  decks stay; copy an Arena deck as Physical to keep it) - Arena cards
  have no price, and the list cannot be changed here: Arena
  is where that collection lives. Decks are **Physical** or **Arena** (the Decks page
  filters by it): an Arena deck counts what you own in Arena and shows what is missing in
  wildcards. **Duplicate** asks which kind the copy is to be: an Arena deck copied as
  Physical shows what you would have to buy to own it on paper. **What can I build?** asks about either collection (Build from: Physical |
  Arena). (Tried with one export of one account, 1,946 cards and three decks; a deck
  with a sideboard or commander in the export, and the wildcard counts against Arena
  itself, were not.) **Add cards** opens a
  panel that searches the whole card database: click to add. Every card shows whether you own it, are missing
  it, or need it in another deck too; the deck shows what is not legal or unfinished, its mana
  curve, its price and what completing it costs, and **Buy list** downloads the missing cards.
  A deck is only a list: it never changes the inventory. Import a pasted decklist or a
  Moxfield / Archidekt deck address; export as text.
- **Deck ideas** - for a Commander deck, *Suggestions* lists the cards played with its
  commander (EDHREC) and *Popular decks* lists public decks you can copy. *What can I build?*
  searches from what you own: **Build around a card**, the legendary creatures you own by how
  much of their usual deck you already have, and the preconstructed decks by how much of each
  you own. These read other sites, so they need internet; if a site doesn't answer, only that
  list is missing.
- **Preconstructed decks** - Commander and Challenger decks, theme and intro decks, starter
  kits, duel decks and Jumpstart packs (as in the Beginner Box), by name, set, year or kind.
  **View cards** shows what is in one without saving anything;
  **Create deck** there makes a deck list to change as you like; **I own
  it** also adds its cards to your inventory (the printings and foils that come in the box).
- **Trades** - promised some cards to someone? Tick them and press **Set aside for trade**
  (or, for one card, the ⇄ button on its row), and give the trade a name. The cards stay in your collection, marked *Trade: name*, and
  cannot be deleted or moved away by accident. On the **Trades** tab you see each open trade
  with its value, change how many copies go, and **Export** the list (Moxfield's format, or
  the app's own). **Confirm trade** when it has happened - only then do the cards leave your
  collection, and the trade stays in a history - or **Cancel trade** and nothing has changed.
- **Added by mistake?** The *Added* filter lists each "Add to collection" with its time. Choose
  one and click **Remove this batch** to take exactly those copies back out.
- **Statistics** - cards and value by color, type, rarity, finish, set, location and tag, and
  your most valuable cards.
- **Backups** - one is made automatically the first time the server starts each day (the last
  7 are kept). The **Settings** link in the right corner of the header (Backups): **Back up now** keeps your collection, the
  scanned cards and your decks as they are - do it before a big load. **Restore** puts all
  three back as they were; what you had at that moment is backed up first, so a restore can be
  taken back.

### Tips for reliable scans

- **Contrast**: a light, plain background (e.g. a white box) makes the card's dark border
  easy to find. White-bordered cards on a white background have no visible outline - use a
  darker background, or capture them with auto-detection turned off.
- **Keep the whole card in view** with a small margin. If an edge is cut off, the card isn't
  detected - and the foil marker in the bottom-left corner can't be read.
- **Focus**: click **Refocus** once with a card in the box. The scanner sweeps through the
  camera's focus range (~10 s), locks the sharpest position and remembers it for that camera.
  While you scan, every few cards it checks whether a slightly different focus is sharper and
  follows it; if a card stays blurry for 3 s it refocuses completely. A soft focus is the usual
  reason for cards going to the AI or to review instead of being read by OCR.
- **Camera sideways** gives more detail and a taller pile: set **Settings → Cameras → Camera rotation**
  so the card shows upright.
- **Light** evenly from above, so reflective foils don't glare.
- **Keep your hand out of the picture** between drops: a card hidden for a moment counts as a
  new card when it is seen again.
- Cards printed before the ★/• convention (roughly before 2020) have no foil marker; for
  those, set the finish yourself when both versions exist.

## Configuration

Most settings are in the web interface and remembered on the server - per camera (focus,
rotation, fixed area, focus check interval, add automatically, location) or for everyone (AI
provider and model, OCR first, sound). `config.yaml` has the rest:

| Setting | Where | Default | Description |
|---|---|---|---|
| `camera.type` | station | `auto` | `auto` (a USB camera if there is one, else a Raspberry Pi camera), `usb` or `picamera`. Also `SCANNER_CAMERA` and the station's setup page. The server opens no camera; `remote` = this machine has none (`scripts/start.sh` and `scripts/deploy.sh` then run only the server) |
| `camera.usb_index` | station | | `auto` (default: the first USB camera that is not a laptop's own) or the `/dev/videoN` number of the USB camera (or `SCANNER_CAMERA_INDEX`: a number or a `/dev/v4l/by-id/...` path) |
| `camera.resolution` / `fps` | station | `[2560, 1440]` / `20` | Capture resolution and frames processed per second |
| `camera.rotate` | station | `0` | Default rotation (0/90/180/270) until it is set in Settings |
| `camera.crop` | station | | Raspberry Pi camera module only: the part of the sensor's image to use (`[x1, y1, x2, y2]`, fractions) - e.g. the box under a wide lens. Drawn on the station's setup page, which then wins |
| `detection.allow_landscape` | station | `false` | Accept cards lying sideways (a card's art box can look like a sideways card) |
| `auto_capture.delay` | station | `1.0` | Minimum seconds between automatic captures |
| `auto_capture.stability_frames` | station | `5` | Still, in-focus frames before a capture that waits for Add / Skip |
| `fast_scan.stability_frames` | station | `6` | Same, when adding automatically (~0.3 s, lets a dropped sleeved card stop sliding) |
| `auto_capture.min_sharpness` | station | `250` | Minimum sharpness for auto-capture; lower it if cards stay on *Focusing* |
| `auto_capture.refocus_every` | station | `10` | Default for *Check the focus every* (captures); `0` = off |
| `vision_ai.provider` | server | `gemini` | Default AI provider |
| `vision_ai.workers` | server | `3` | AI requests at the same time |
| `vision_ai.detect_foil` | server | `true` | Ask the AI for the ★/• marker when OCR couldn't read it |
| `vision_ai.image_size` | server | `1024` | Longest side of the card image sent to the AI (larger = slower, not more accurate) |
| `ocr.provider` | server | `auto` | Where light-ocr runs: `auto` (GPU when available), `cpu`, `webgpu` |
| `stations.token` | server | (none) | When set (or `SCANNER_STATION_TOKEN`), stations must send it |
| `flask.port` | server | `5000` | Web server port (with Docker: `SCANNER_PORT`) |
| `cleanup.enabled` / `days` | server | `true` / `7` | Delete uploaded capture images older than N days on startup |
| `database.update_after_days` | server | `7` | How old the card data may get before the update notice shows |

The station's settings are read from the `config.yaml` on the station's machine (or inside its
image).

## Maintenance

| Task | How |
|---|---|
| Update card data and prices | Click the Database counter when it shows a dot, or **Settings → Card data → Update card database**. Scanning keeps working during an update |
| Update the programs | `git pull`, then `docker compose up -d --build` again - on the server and on each station |
| Back up your cards | **Settings → Backups → Back up now**; automatic backups are set there too (every hour to every week, or off; default every day, the last 7 kept), and each backup can be downloaded as a zip file and uploaded again |
| Back up everything | Copy the server's `data/` folder while the container is stopped |
| See what a station is doing | Its page's Activity log; `docker compose -f deploy/docker-compose.client.yml logs -f` on the station |
| Server logs | `data/logs/`: `app.log` (web app, every station's scanner lines), `ai.log` (OCR and AI reads), `database.log`, `scanned_cards.log` (one CSV line per identified card), `ocr.log` |

Your collection lives in the same SQLite file as the card data (`data/cards_database.db`,
table `inventory`); updating the card data does not touch it.

## Troubleshooting

**A camera's page says "No camera station connected"** - the station's program isn't running
or can't reach the server. On the station: `docker compose -f deploy/docker-compose.client.yml logs`;
it retries by itself once the server is reachable.

**"No camera found" on a connected station** - the station doesn't see its webcam. Check
`v4l2-ctl --list-devices` there and `SCANNER_CAMERA_INDEX` / `camera.usb_index`. Only one
program can use a camera at a time. The station picks the camera up when it is plugged in.

**Auto scanning never captures** - the status tells you why: *Focusing* (image not sharp
enough - click **Refocus**, or lower `auto_capture.min_sharpness`), *Stabilizing* (card still
moving), or *Captured - drop the next card* (it's waiting for a new card to land).

**Cards go to review, or to the AI, more than they should** - usually focus: the small print
is too soft for OCR. Click **Refocus** with a card in the box.

**A card was added twice / one was skipped** - see *Tips*: a hand over the box between drops,
or an identical copy landing exactly on the previous one. Undo, or fix the quantity in the
scanned list.

**Card not detected** - make sure the whole card is visible with some margin and the
background contrasts with the border. A card without a clear outline can be captured with
auto-detection turned off, or with a fixed area.

**"Vision AI disabled"** - no API key was found for the selected provider. Enter one in
Settings, or switch to a local model.

**Local AI returns 404** - Ollama answers 404 when the requested model isn't installed. Pick
one of the models listed in Settings (they come from your server) or `ollama pull` it.

**Wrong printing** - check the set code and number that were read (shown in the Search bar
after a capture); correct them there and search again, or pick the printing from the grid.

## Project structure

All the code is one package, `src/card_scanner/`, sorted by which program it belongs to;
the top folder keeps what you start, set and own.

```
app.py               Starts the server (python app.py)
station.py           Starts a camera station (python station.py --server http://<server>:5000)
config.yaml          Settings (loaded by card_scanner/config.py / config_loader.py)
pyproject.toml       What the project is and which Python it needs (the libraries are in requirements*.txt)
compose.yaml         `docker compose up` in this folder starts the server (it points into deploy/)
data/                Card data, collection, settings, backups, logs (created at runtime)
scanned_cards/       Capture images the server received (created at runtime)
station_captures/    A camera station's captures that are not on the server yet (created at runtime)

src/card_scanner/    The code
  paths.py             Where the two folders are: the top folder (data, settings) and the code
  config.py, config_loader.py, settings.py
                       Reading config.yaml and the saved settings - used by both programs

  station/           A camera station: all of it, and nothing else
    station_client.py    The program: runs next to the camera, talks to the server
    station_setup.py     ... its setup page (server, name, camera), station_setup.html
    station_login.py     ... and that page's password
    scanner.py           Camera capture thread, detection, stability, auto-capture, focus
    object_detector.py   Card outline detection + perspective correction

  core/              Reading cards, card data, the collection - no web app, no camera
    identification.py    Reading a card: OCR queue, AI queue, shared by every camera
    card_ocr.py          light-ocr reader's process and the parser for what it reads
    card_identifier.py   Vision AI providers, card identification, foil marker check
    prompts.py           AI prompts: built-in ones and those edited in Settings
    api_keys.py          API keys entered in Settings
    database.py          Scryfall card data: download, schema, search, printings
    card_search.py       Magic search helpers; setup_database.py downloads the card data
    inventory.py         Inventory: add, merge, undo, edit, locations, tags, cameras, import / export
    decks.py             Decks (lists of cards; the inventory says what is owned)
    trades.py            Cards set aside until a trade is confirmed
    backups.py           Backups of the collection, scanned cards and decks; full backups
    storage.py           Database connections and migrations
    pending.py           Captures in the queues, kept across a restart
    review.py            The review queue; cleanup.py removes old capture pictures
    stations.py          The stations and each one's settings (data/stations.json)
    remote_scanner.py    The server's stand-in for a station's camera; the stations' connection
    recommendations.py   Deck ideas from EDHREC, MTGJSON, Archidekt and Moxfield (cached)

  server/            The web app: pages, routes, events, one desk per camera, station captures -
                     one module per area (server/__init__.py lists them)
    templates/, static/  The pages: the cameras, a camera's page, the collection. The font and
                         Socket.IO's client are in static/ too: the pages load nothing from the internet
  games/             Card games: base.py (interface), mtg.py (Magic), mtg_decks.py

src/ocr/             The light-ocr reader itself (Node.js)

tests/               Automated tests (camera ownership, backups, database, a station's setup page and uploads,
                     where the programs look for their folders, which module may import which)
deploy/              Everything about Docker: the Dockerfile (images server, client, client-pi) and
                     the compose files - server, server with GPU, camera station, station with a Pi camera
docs/                What it does (FEATURES.md), how it works, installation, the Docker guide, the manual test list; docs/plans/
scripts/             docker-entrypoint.sh; deploy.sh, start.sh, backup.sh for a setup without Docker;
                     setup_database.py (the card data), cleanup.py (old capture pictures);
                     benchmark_db.py, benchmark_station.py
```

[docs/FEATURES.md](docs/FEATURES.md) lists what the program does;
[docs/PROGRAM_DOCUMENTATION.md](docs/PROGRAM_DOCUMENTATION.md) explains how everything works inside
(stations, detection, auto-capture, identification, matching, database);
[docs/INSTALL.md](docs/INSTALL.md) covers installation and [docs/DOCKER_GUIDE.md](docs/DOCKER_GUIDE.md) is the
step-by-step version ([docs/VIDEO_SCRIPT.md](docs/VIDEO_SCRIPT.md): a script for filming it);
[docs/TEST_CASES.md](docs/TEST_CASES.md) lists what to check by hand.

## HTTP API

The web interface uses these endpoints, which you can also call directly. A scanner page adds
`?station=<id>` to say which camera it means. The inventory endpoints work on the collection;
add `?area=scan` for the cards scanned and not yet added to it, and `&camera=<id>` to narrow
those to one camera.

| Endpoint | Description |
|---|---|
| `GET /`, `GET /scan/<id>`, `GET /collection`, `GET /decks`, `GET /decks/<id>` | The cameras; a camera's scanner page; the collection; the deck list; one deck |
| `GET /video_feed?station=<id>` | MJPEG stream of a camera's annotated view |
| `GET /api/detection_status?station=<id>` | Whether a card is detected and how stable it is, or why there is no camera |
| `GET /api/stats` | Card data, scanned cards, collection and review counts |
| `GET /api/stations` | The stations and their state |
| `PUT` / `DELETE /api/stations/<id>` | Rename a station or set its location; forget it (with its scanned cards and review items) |
| `POST /api/stations/<id>/captures` | A card captured by a station (multipart `image`; optional `foil_image`, `foil_is_image`, `name`, `wait`, `capture_id`): read, then added or queued for review - see docs/PROGRAM_DOCUMENTATION.md, Stations |
| `GET /api/stations/<id>/captures/<n>`, `POST /api/stations/<id>/undo` | The outcome of a capture that was still pending; take back the station's last card |
| `GET` / `DELETE /api/stations/<id>/captures/<n>/sync` | Where one capture's card is now (being read, scanned cards, review, or gone into the collection); remove exactly that card from the scanned cards or the review queue - never from the collection. Used by the Android app to keep its list in step |
| `GET /api/scan_settings`, `POST /api/scan_location`, `POST /api/sound` | A camera's scanning settings; its location for scanned cards; the sound switches (all, capture beep, card added) and volume |
| `GET /api/games` | Supported card games (finishes, export formats) and the active one |
| `GET /api/inventory` | The active game's inventory (each entry has an `id` and its `captures`) |
| `GET /captures/<file>`, `GET /review_images/<file>` | A capture thumbnail of an inventory entry; the capture of a review item |
| `POST /api/inventory/update/<id>` | Update an entry (JSON: `quantity`, `condition`, `finish`, `location`, `tags`, `split_quantity`; `card_id`: another printing of the same card) |
| `GET /api/inventory/<id>/printings` | The printings an entry can be changed to |
| `POST /api/inventory/bulk` | One change to several entries (JSON: `ids`, `action`: `delete` / `condition` / `location` / `add_tag` / `remove_tag`, `value`) |
| `POST /api/inventory/delete/<id>` | Delete an inventory entry |
| `POST /api/clear_inventory` | Delete the active game's entries; with `?area=scan&camera=<id>` one camera's scanned cards and review items |
| `GET` / `POST /api/scan_inventory/to_collection` | Cards waiting and locations in use; move the scanned cards into the collection (JSON: `location`, `camera` - both optional) |
| `POST /api/inventory/remove_batch` | Take back the cards that came in together (JSON: `batch`, from an entry's `batches`) |
| `GET /api/export_inventory/<format>` | Download the inventory: `moxfield` (Magic), `csv` (the app's own, every column) |
| `POST /api/import_inventory` | Import a collection CSV (multipart `file`, `replace_existing`): Moxfield, or the app's own columns |
| `GET /api/backups`, `POST /api/backups`, `POST /api/backups/schedule` | List the backups (and the automatic backups' settings); make one (JSON: `note`); set how often automatic backups are made and how many are kept (JSON: `every_hours`, `keep`) |
| `GET /api/backups/full`, `POST /api/backups/full` | The full backups; make one: every database file and the pictures they point at, taken at one moment, in `data/backups/full/` (what `scripts/backup.sh` archives) |
| `GET /api/backups/<id>/download`, `POST /api/backups/upload` | A backup as a zip file, to keep elsewhere; add such a file to the list again (multipart `file`; nothing is restored by it) |
| `POST /api/backups/<id>/restore`, `DELETE /api/backups/<id>` | Put the collection, scanned cards and decks back as in a backup (the current state is backed up first); delete a backup |
| `GET /api/cards/search`, `GET /api/cards/printings?name=` | Deck builder card search; every printing of a card with the copies owned |
| `GET /api/decks`, `POST /api/decks` | List decks (each with `commander_cards`: name, picture and colours of its commanders); create one (JSON: `name`, `format`, and optionally `text`, `url`, `precon`, `commander`) |
| `GET` / `PUT` / `DELETE /api/decks/<id>` | A deck with card data, copies owned, issues and its `covers`; rename / change format / choose the `cover` card; delete |
| `POST /api/decks/<id>/cards`, `/import`, `/duplicate` | Change cards; add cards from a list or a deck address; copy a deck |
| `GET /api/decks/<id>/export/<text\|buylist\|arena>`, `GET /api/decks/<id>/arena` | Download the decklist, the cards not owned, or the list for MTG Arena's Import button; the same Arena list with the names it leaves out |
| `GET /api/arena`, `POST /api/arena/import` | The digital collection (MTG Arena): when it is from, its size, the wildcards; replace it with an exporter's files (form field `files`: `mtga_collection.json`, `mtga_decks.json`, or both - each replaces its own part). Its cards: `GET /api/inventory?area=arena` (read only) |
| `GET /api/decks/<id>/suggestions`, `GET /api/decks/popular` | EDHREC cards for the deck's commander; public decks on Archidekt / Moxfield |
| `GET` / `POST /api/decks/ideas/<commanders\|precons\|card>` | "What can I build?" searches: state / start a run / stop it |
| `GET /api/precons`, `GET /api/precons/covers?files=`, `GET /api/precons/<file>`, `POST /api/precons/<file>/own` | Preconstructed decks; the card that stands for each of up to 8 of them; one's cards with their pictures and how many of each are owned (nothing saved); add one's cards to the inventory and open it as a deck |
| `GET /api/inventory/suggested` | The owned cards EDHREC lists for the decks' commanders (no page asks for it at the moment) |
| `GET /api/ai_provider`, `/api/ai_models`, `/api/local_ai_models`, `/api/ai_credentials`, `/api/prompts` | The AI in use, model lists, masked keys, prompts |

Scanning, searching and settings on a camera's page go through Socket.IO events
(`capture_card`, `search_card`, `add_to_inventory`, `toggle_auto_capture`, ...), and a camera
station holds a Socket.IO connection of its own (`/station`); both are listed in
docs/PROGRAM_DOCUMENTATION.md.

The web interface has no login: run it on a network you trust.

## Ask an AI about your decks (MCP)

`mcp_server/` is a small read-only MCP server: an AI assistant (Claude, or a local model through an
MCP client) can list your decks, see what you own and what is missing, suggest cards for a
commander and check what adding a card would do, without changing anything. Setup:
[mcp_server/README.md](mcp_server/README.md).

## How this project was built

This project was developed entirely with AI. The code, the tests and the documentation - this
README, the installation guides, the technical documentation - were written by an AI coding
assistant: Claude, by Anthropic, working through Claude Code. The commit history records it
(nearly every commit carries a `Co-Authored-By: Claude` line). The same goes for the
[Android app](https://github.com/SilentKernel81/mtg-scanner-android).

The project's author did what the AI could not: decided what to build and how it should
behave, ran it on real hardware - webcams, a Raspberry Pi, a phone - with real cards, and
reported what happened. The thresholds and timings quoted in the documentation come from
those runs and from recorded sessions, and each says when and on what it was measured.

What that means if you use it:

- **It has been run, not audited.** The author uses it for their own collection, but no one
  has reviewed the code independently, and the automated tests cover one area (which camera
  scanned what, and backups). Where something was never tried, the documentation says so
  ("not tested").
- **It is made for a home network.** There is no login; see the note under
  [HTTP API](#http-api).
- **Keep backups** of a collection you care about - the server makes one a day, and
  *Back up now* is on the collection page.

## License

[PolyForm Noncommercial 1.0.0](LICENSE) - free for personal use, hobby projects, study, research
and non-profit use. You may change it for yourself and share it with others under the same terms.
You may **not** sell it or use it commercially without the author's permission. The source is
public (*source-available*); it is not under an OSI open-source license. Versions published
before 2026-10-19 were released under the MIT license, and copies of those stay under it.

## Acknowledgments

- Card data, prices and images: [Scryfall](https://scryfall.com)
- Card Kingdom's and Mana Pool's prices: [MTGJSON](https://mtgjson.com) (MIT License, © Zach Halpern)
- Deck ideas and deck lists: [EDHREC](https://edhrec.com) (cards played with a commander),
  [MTGJSON](https://mtgjson.com) (preconstructed decks), [Archidekt](https://archidekt.com)
  and [Moxfield](https://moxfield.com) (public decks, and decks imported by their address)
- Text recognition: [light-ocr](https://github.com/arcships/light-ocr)
- Computer vision: [OpenCV](https://opencv.org)
- Web: [Flask](https://flask.palletsprojects.com) and
  [Flask-SocketIO](https://flask-socketio.readthedocs.io)
- Shipped with the pages, each with its licence beside it: the
  [Socket.IO](https://socket.io) client (MIT, `static/js/vendor/`) and the
  [Roboto](https://fonts.google.com/specimen/Roboto) font (SIL Open Font License,
  `static/fonts/`)
- The MTG Arena collection is read from the files of
  [mtga-export](https://github.com/SilentKernel81/mtga-export), the same author's exporter;
  none of its code is in this repository

No code from another project was copied into this one; the libraries above are installed
as dependencies (`requirements*.txt`, `src/ocr/package.json`).

This is an unofficial fan project, not affiliated with or endorsed by Wizards of the Coast.
Magic: The Gathering is a trademark of Wizards of the Coast LLC.
