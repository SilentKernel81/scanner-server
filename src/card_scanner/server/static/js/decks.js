// The deck pages (/decks, /decks/<id>): the deck list, "What can I build?", the preconstructed
// decks, and the builder of one deck. Moved here from collection.js on 2026-10-13, when the
// decks left the collection page for pages of their own.
// Helpers come from common.js (escapeHtml, dialogs, notify) and library.js ($, api, ...).

const socket = io();

// ============================================================================
// Decks: list
// ============================================================================

let deck = null;          // the deck open in the builder (server payload)
let deckList = [];

function deckFormat(format) {
    // [key, label, has a commander]
    return gameInfo.deck_formats.find(([key]) => key === format);
}

function formatLabel(format) {
    const found = deckFormat(format);
    return found ? found[1] : format;
}

function hasCommander(format) {
    const found = deckFormat(format);
    return !!(found && found[2]);
}

function isCommanderCard(card) {
    return /Legendary.*Creature|can be your commander/.test(card.type_line.split(' // ')[0] + card.oracle_text);
}

async function loadDecks() {
    if (!gameInfo.deck_formats.length) return;
    const data = await api('/api/decks');
    if (!data) return;
    deckList = data.decks;
    $('deck-data-notice').hidden = data.has_deck_data;
    // The formats there are decks of; a choice that is gone falls back to all
    const formats = [...new Set(deckList.map(item => item.format))];
    const chosen = $('deck-filter-format').value;
    $('deck-filter-format').innerHTML = optionsHtml([['', 'Any format'], ...gameInfo.deck_formats.filter(([key]) => formats.includes(key))]);
    $('deck-filter-format').value = formats.includes(chosen) ? chosen : '';
    $('deck-filters').hidden = deckList.length < 2;
    // The kind switch only when there is something to tell apart: a game with a digital
    // collection, and at least one Arena deck (or the switch standing on a kind)
    $('deck-kind').hidden = !gameInfo.arena || !(deckList.some(item => item.kind === 'arena') || deckKindShown !== 'all');
    markSwitch('deck-kind', 'kind', deckKindShown);
    renderDeckList();
}

const DECK_SORTS = {
    changed: (a, b) => b.updated_at.localeCompare(a.updated_at) || b.id - a.id,
    name: (a, b) => a.name.localeCompare(b.name),
    format: (a, b) => formatLabel(a.format).localeCompare(formatLabel(b.format)) || a.name.localeCompare(b.name),
    owned: (a, b) => b.owned_percent - a.owned_percent || a.name.localeCompare(b.name),
    missing: (a, b) => (a.cards - a.owned) - (b.cards - b.owned) || a.name.localeCompare(b.name),
    cards: (a, b) => b.cards - a.cards || a.name.localeCompare(b.name),
};

// Decks are of two kinds: of paper cards ('paper', called Physical on the page) or of MTG
// Arena ('arena'). The kind says which collection "owned" is counted in. The list shows
// both, or one of them:
let deckKindShown = recall('deckKindShown', 'all');   // 'all' | 'paper' | 'arena'

function wildcardsHtml(wildcards) {
    // What crafting the missing cards costs, by rarity, beside what the account has:
    // "3 rare (you have 1)" - marked when the account has too few
    if (!wildcards) return '';
    const parts = ['common', 'uncommon', 'rare', 'mythic'].filter(rarity => wildcards.needed[rarity]).map(rarity => {
        const have = wildcards.have[rarity] || 0;
        return `<span class="${have < wildcards.needed[rarity] ? 'wild-short' : ''}">${wildcards.needed[rarity]} ${rarity} <small>(you have ${have})</small></span>`;
    });
    return parts.length ? parts.join(', ') : '';
}

function renderDeckList() {
    const words = searchWords('deck-filter-text');
    const format = $('deck-filter-format').value;
    const shown = deckList.filter(item => {
        const text = `${item.name} ${item.commanders.join(' ')}`.toLowerCase();
        return (deckKindShown === 'all' || item.kind === deckKindShown)
            && (!format || item.format === format) && words.every(word => text.includes(word));
    }).sort(DECK_SORTS[$('deck-sort').value] || DECK_SORTS.changed);
    $('deck-list').innerHTML = !shown.length && deckList.length
        ? '<div class="empty-state">No deck matches.</div>'
        : deckList.length ? shown.map(deckTileHtml).join('')
        : '<div class="empty-state">No decks yet. Create one, or see under "What can I build?" what your collection has the cards for.</div>';
}

function artOf(image) {
    // The picture inside a card's frame, from the address of the whole card's picture
    // (Scryfall keeps both under the same name: .../normal/... and .../art_crop/...).
    // Any other address is used as it is: the whole card, cut to fit
    return (image || '').replace('/normal/', '/art_crop/');
}

function identityHtml(letters) {
    // A deck's colours as the round symbols a mana cost is shown with, in the usual order
    return manaHtml([...'WUBRG'].filter(letter => letters.includes(letter)).map(letter => `{${letter}}`).join(''));
}

// -- A deck's cover: the card whose picture stands for it --------------------------
// The server says which cards those are (covers: the card chosen in the deck, else its
// commanders, else its most valuable card). A deck with two commanders has two: the first
// is shown, and a button turns to the other. Which one is showing is remembered in the
// browser, per deck - it is a way of looking at the deck, not something about the deck.

function coverIndex(item) {
    const count = (item.covers || []).length;
    return count > 1 ? (parseInt(recall(`deckFace:${item.id}`, '0')) || 0) % count : 0;
}

function coverOf(item) {
    // {name, image_uri} of the cover showing, or null for a deck that has none (no cards yet)
    return (item.covers || [])[coverIndex(item)] || null;
}

function turnCover(item) {
    // To the deck's other commander (and back)
    remember(`deckFace:${item.id}`, String((coverIndex(item) + 1) % item.covers.length));
}

function deckTileHtml(item) {
    // A deck in the list: a card - its cover - with the deck's name under it, so that the
    // list looks like decks lying on a table. A link, so that it can be opened in a new tab;
    // a plain click stays on this page (bindDeckHomeEvents).
    const cover = coverOf(item);
    const colours = [...new Set((item.commander_cards || []).flatMap(card => card.identity || []))];
    return `
        <a class="deck-tile" data-deck="${item.id}" href="/decks/${item.id}">
            <span class="deck-tile-card">
                ${cover && cover.image_uri
                    ? `<img src="${escapeHtml(cover.image_uri)}" alt="${escapeHtml(cover.name)}" title="${escapeHtml(cover.name)}" loading="lazy">`
                    : '<span class="deck-tile-empty">No cards yet</span>'}
                ${item.kind === 'arena' ? `<span class="deck-kind-badge" title="${item.from_arena
                    ? 'A deck from MTG Arena: the next import brings it again as it is there' : 'A deck for MTG Arena, made here: the next import with a deck file removes it'}">Arena</span>` : ''}
                ${(item.covers || []).length > 1
                    ? `<button class="deck-flip" data-flip title="Show the other commander: ${escapeHtml(item.covers[(coverIndex(item) + 1) % item.covers.length].name)}"><svg class="icon"><use href="#i-swap"/></svg></button>` : ''}
            </span>
            <span class="deck-tile-body">
                <span class="deck-tile-head"><span class="deck-tile-name">${escapeHtml(item.name)}</span><span>${identityHtml(colours)}</span></span>
                <span class="deck-tile-meta" title="${escapeHtml(formatLabel(item.format))}">${escapeHtml(item.commanders.length ? item.commanders.join(' + ') : formatLabel(item.format))}</span>
                <span class="meter" title="${item.owned} of ${item.cards} ${item.kind === 'arena' ? 'in your Arena collection' : 'owned'}"><span style="width: ${item.owned_percent}%"></span></span>
                <span class="deck-tile-foot"><span>${plural(item.cards, 'card')} · ${item.owned_percent}% owned</span><span title="Last changed">${escapeHtml(item.updated_at.slice(0, 10))}</span></span>
            </span>
        </a>`;
}

// -- The deck list's three tabs (in the header: #deck-tabs) --------------------------

function showDeckTab(tab) {
    // 'mine' (the decks), 'build' (what the collection can build), 'precons'
    if (!['mine', 'build', 'precons'].includes(tab)) tab = 'mine';
    remember('deckTab', tab);
    document.querySelectorAll('#deck-tabs .tab').forEach(button => button.classList.toggle('is-active', button.dataset.tab === tab));
    document.querySelectorAll('.deck-tab').forEach(panel => { panel.hidden = panel.id !== `deck-tab-${tab}`; });
}

function openDeckModal({text = '', importInto = null} = {}) {
    // New deck, or (importInto: a deck) add cards to an existing one
    $('deck-modal').dataset.importInto = importInto ? importInto.id : '';
    $('deck-modal-title').textContent = importInto ? `Import cards into ${importInto.name}` : 'New deck';
    $('deck-modal-name-group').hidden = $('deck-modal-format-group').hidden = !!importInto;
    $('deck-modal-replace').hidden = !importInto;
    $('deck-modal-save').textContent = importInto ? 'Import' : 'Create';
    $('new-deck-name').value = '';
    $('new-deck-url').value = '';
    $('new-deck-text').value = text;
    $('new-deck-replace').checked = false;
    $('new-deck-format').innerHTML = optionsHtml(gameInfo.deck_formats);
    // The kind is chosen for a new deck only; it starts as the kind the list is showing
    $('deck-modal-kind-group').hidden = !!importInto || !gameInfo.arena;
    markSwitch('new-deck-kind', 'kind', deckKindShown === 'arena' ? 'arena' : 'paper');
    $('deck-modal').classList.add('show');
    (importInto ? $('new-deck-url') : $('new-deck-name')).focus();
}

function reportUnknown(unknown) {
    if (unknown && unknown.length) {
        notify(`Not in the card data: ${unknown.slice(0, 6).join(', ')}${unknown.length > 6 ? ` and ${unknown.length - 6} more` : ''}`, 'warning');
    }
}

async function saveDeckModal() {
    const importInto = $('deck-modal').dataset.importInto;
    const body = {text: $('new-deck-text').value.trim() || undefined, url: $('new-deck-url').value.trim() || undefined};
    const button = $('deck-modal-save');
    button.disabled = true;
    let data;
    if (importInto) {
        if (!body.text && !body.url) {
            notify('Paste a decklist or a deck address', 'warning');
            button.disabled = false;
            return;
        }
        data = await api(`/api/decks/${importInto}/import`, {method: 'POST', body: {...body, replace: $('new-deck-replace').checked}});
    } else {
        // A deck from another site keeps that site's format unless the list is pasted
        const chosen = $('new-deck-kind').querySelector('.is-active');
        data = await api('/api/decks', {method: 'POST', body: {...body, name: $('new-deck-name').value.trim() || undefined,
                                                              kind: gameInfo.arena && chosen ? chosen.dataset.kind : 'paper',
                                                              format: body.url ? undefined : $('new-deck-format').value}});
    }
    button.disabled = false;
    if (!data) return;
    closeModal('deck-modal');
    reportUnknown(data.unknown);
    openDeck(data.deck);
}

async function createDeck(body, message) {
    const data = await api('/api/decks', {method: 'POST', body});
    if (!data) return;
    reportUnknown(data.unknown);
    if (message) notify(message, 'success');
    openDeck(data.deck);
}

function copyDeckClicked(event, kind = 'paper') {
    // "Copy as deck" on a public deck's row (kind: of the new deck)
    const button = event.target.closest('[data-import-url]');
    if (button) createDeck({url: button.dataset.importUrl, kind}, 'Deck copied');
}

// -- Preconstructed decks: browse, open as a deck, or add as owned ----------------

let precons = null;          // [{file, name, type, format, released, set}] newest first
let preconRank = {};         // file -> {owned, total, percent}, after "Rank by what I own"

async function loadPrecons() {
    if (precons) return renderPrecons();
    $('ideas-precons').innerHTML = '<div class="hint">Loading the list...</div>';
    const data = await api('/api/precons');
    if (!data) {
        $('ideas-precons').innerHTML = '<div class="hint">The list of preconstructed decks is not available right now.</div>';
        return;
    }
    precons = data.precons;
    // The kinds in the list, the ones with most decks first
    const kinds = {};
    precons.forEach(item => { kinds[item.type] = (kinds[item.type] || 0) + 1; });
    $('precon-type').innerHTML = optionsHtml([['', 'Any kind'],
        ...Object.entries(kinds).sort((a, b) => b[1] - a[1]).map(([kind, count]) => [kind, `${kind} (${count})`])]);
    renderPrecons();
}

function renderPrecons() {
    if (!precons) return;
    const words = searchWords('precon-search');
    const kind = $('precon-type').value;
    const ranked = Object.keys(preconRank).length > 0;
    let rows = precons.filter(item => {
        if (kind && item.type !== kind) return false;
        const text = `${item.name} ${item.set} ${item.type} ${item.released.slice(0, 4)}`.toLowerCase();
        return words.every(word => text.includes(word));
    });
    // Ranked: the decks you own most of first; otherwise the newest first (as loaded)
    if (ranked) rows = [...rows].sort((a, b) => ((preconRank[b.file] || {}).percent || 0) - ((preconRank[a.file] || {}).percent || 0));
    const more = rows.length - PRECONS_SHOWN;
    $('ideas-precons').innerHTML = rows.slice(0, PRECONS_SHOWN).map(preconTileHtml).join('')
        || '<div class="hint">No preconstructed deck matches.</div>';
    $('precon-more').textContent = more > 0 ? `${more} more - type to narrow the list` : '';
    watchPreconTiles();
}

// -- A preconstructed deck's cover -------------------------------------------------
// The list of preconstructed decks (MTGJSON) has names, sets and dates - no pictures, and
// not what is in a deck. That is in each deck's own file, a megabyte apiece and some 1,500
// of them. So a tile starts as a plain card with the deck's name, and its cover is asked
// for when the tile comes into view: a few decks per request (the server reads their files,
// once), one request at a time. What was learnt is kept while the page is open.

const PRECONS_SHOWN = 60;        // tiles at once; the rest is reached by typing
const PRECON_COVERS_AT_ONCE = 8; // decks per request (the server's limit)
const preconCovers = {};         // file -> [{name, image_uri}] ([]: read, and it has none)
const preconFace = {};           // file -> which of two commanders is showing
let preconWanted = new Set();    // files whose tiles are in view and have no cover yet
let preconAsking = false;
let preconWatcher = null;

function preconCoverHtml(item) {
    // What is inside a tile's card: the cover's picture once it is known, until then (and
    // for a deck without one) the deck's name on a plain card
    const covers = preconCovers[item.file];
    const cover = covers && covers[(preconFace[item.file] || 0) % (covers.length || 1)];
    return (cover && cover.image_uri
            ? `<img src="${escapeHtml(cover.image_uri)}" alt="${escapeHtml(cover.name)}" title="${escapeHtml(cover.name)}" loading="lazy">`
            : `<span class="deck-tile-empty">${escapeHtml(item.name)}</span>`)
        + (covers && covers.length > 1
            ? `<button class="deck-flip" data-flip title="Show the other commander"><svg class="icon"><use href="#i-swap"/></svg></button>` : '');
}

function preconTileHtml(item) {
    // A preconstructed deck: a card, as your own decks are. A click shows what is in it
    // (data-precon="view": the window with its cards, where a deck can be made of it)
    const rank = preconRank[item.file];
    return `
        <div class="deck-tile precon-tile" data-file="${escapeHtml(item.file)}" data-precon="view" tabindex="0" title="See what is in it - nothing is saved">
            <span class="deck-tile-card">${preconCoverHtml(item)}</span>
            <span class="deck-tile-body">
                <span class="deck-tile-head"><span class="deck-tile-name">${escapeHtml(item.name)}</span></span>
                <span class="deck-tile-meta">${escapeHtml(item.type)}</span>
                ${rank ? `<span class="meter" title="${rank.owned} of ${rank.total} cards owned"><span style="width: ${rank.percent}%"></span></span>` : ''}
                <span class="deck-tile-foot"><span>${escapeHtml(item.set)} · ${escapeHtml(item.released.slice(0, 7))}</span><span>${rank ? `${rank.percent}% owned` : ''}</span></span>
            </span>
        </div>`;
}

function watchPreconTiles() {
    // Tiles without a cover are watched; one that comes into view (or near it) is put on
    // the list of covers to ask for
    if (preconWatcher) preconWatcher.disconnect();
    preconWanted = new Set();
    preconWatcher = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            preconWanted.add(entry.target.dataset.file);
            preconWatcher.unobserve(entry.target);
        });
        loadPreconCovers();
    }, {rootMargin: '300px'});
    document.querySelectorAll('#ideas-precons .precon-tile').forEach(tile => {
        if (!(tile.dataset.file in preconCovers)) preconWatcher.observe(tile);
    });
}

async function loadPreconCovers() {
    // One request at a time, a few decks each, for as long as tiles in view are waiting.
    // A deck the server could not read just now (MTGJSON not answering) is not in its
    // answer: it is left alone until the list is shown again, not asked for in a loop.
    if (preconAsking) return;
    preconAsking = true;
    try {
        while (preconWanted.size) {
            const files = [...preconWanted].slice(0, PRECON_COVERS_AT_ONCE);
            files.forEach(file => preconWanted.delete(file));
            let data = null;
            try {
                const response = await fetch(`/api/precons/covers?files=${files.map(encodeURIComponent).join(',')}`);
                data = response.ok ? await response.json() : null;
            } catch (error) { /* the server is away: the tiles keep their names */ }
            if (!data || !data.covers) break;
            Object.entries(data.covers).forEach(([file, covers]) => {
                preconCovers[file] = covers;
                const tile = document.querySelector(`#ideas-precons .precon-tile[data-file="${CSS.escape(file)}"]`);
                const item = precons.find(precon => precon.file === file);
                if (tile && item) tile.querySelector('.deck-tile-card').innerHTML = preconCoverHtml(item);
            });
        }
    } finally {
        preconAsking = false;
    }
}

let viewedPrecon = null;     // the precon whose cards are shown

async function viewPrecon(item) {
    // Only a look: a deck is made by "Create deck" in the window (it once was made by opening)
    viewedPrecon = item;
    $('precon-title').textContent = item.name;
    $('precon-subtitle').textContent = `${item.type} · ${item.set} · ${item.released.slice(0, 7)}`;
    $('precon-cards').innerHTML = '<div class="hint">Loading the list...</div>';
    $('precon-create').disabled = $('precon-own').disabled = true;
    $('precon-modal').classList.add('show');
    const data = await api(`/api/precons/${encodeURIComponent(item.file)}`);
    if (viewedPrecon !== item) return;  // another one was opened meanwhile
    if (!data) return closeModal('precon-modal');
    const total = totalQuantity(data.cards);
    const have = data.cards.reduce((sum, card) => sum + Math.min(card.quantity, card.owned), 0);
    $('precon-subtitle').textContent += ` · ${plural(total, 'card')}, ${have} owned`;
    const boards = [['commander', 'Commander'], ['main', 'Main deck'], ['side', 'Sideboard']];
    $('precon-cards').innerHTML = boards.map(([board, label]) => {
        const cards = data.cards.filter(card => card.board === board).sort((a, b) => byText(a.name, b.name));
        return cards.length ? `<h4>${label} (${totalQuantity(cards)})</h4>` + cards.map(card => `
            <div class="precon-card" data-image="${escapeHtml(card.image_uri || '')}"><span>${card.quantity}×</span><span>${escapeHtml(card.name)}</span>
                <span class="${card.owned ? '' : 'missing'}">${card.owned ? `${card.owned} owned` : 'not owned'}</span></div>`).join('') : '';
    }).join('');
    $('precon-create').disabled = $('precon-own').disabled = false;
}

async function ownPrecon(item) {
    const location = await valueDialog({
        title: `Add ${item.name} to your inventory`,
        label: 'Its cards are added as Near Mint, in the printings that come in the box. Location (empty: none)',
        options: await knownLocations(), value: item.name.slice(0, 60)});
    if (location === null) return;
    const data = await api(`/api/precons/${encodeURIComponent(item.file)}/own`, {method: 'POST', body: {name: item.name, location}});
    if (!data) return;
    reportUnknown(data.unknown);
    notify(`${plural(data.added, 'card')} of ${item.name} added to your inventory`, 'success');
    preconRank = {};  // what is owned changed
    knownPlaces = null;
    openDeck(data.deck);
}

// -- "What can I build?": searches that run on the server, polled while they go ----

const ideaTimers = {};

function renderIdeas(kind, state) {
    if (kind === 'card') return renderAround(state);
    if (kind === 'precons') {
        // The ranking fills in the browsable list
        state.items.forEach(item => { preconRank[item.file] = item; });
        $('precon-progress').innerHTML = (state.running ? `<div class="hint">Reading the lists... ${state.done} of ${state.total || '?'}</div>`
                : state.stopped ? `<div class="hint">Stopped after ${state.done} of ${state.total} lists - the rest is not ranked</div>` : '')
            + (state.error ? `<div class="callout warning">${escapeHtml(state.error)}</div>` : '');
        return renderPrecons();
    }
    const list = $(`ideas-${kind}`);
    // A run made for the other collection (Physical | Arena) counted other cards: not shown
    if (state.started && (state.collection || 'paper') !== buildKind) return void (list.innerHTML = '');
    const progress = state.running ? `<div class="hint">Looking... ${state.done} of ${state.total || '?'}</div>`
        : state.stopped ? `<div class="hint">Stopped after ${state.done} of ${state.total}</div>` : '';
    const error = state.error ? `<div class="callout warning">${escapeHtml(state.error)}</div>` : '';
    const rows = state.items.slice(0, 60).map(item => `
        <div class="idea-row" data-image="${escapeHtml(item.image_uri || '')}">
            <div><div class="idea-name">${escapeHtml(item.name)}</div>
                 <div class="idea-meta">${item.decks.toLocaleString()} decks on EDHREC · you own ${item.owned} of the ${item.total} cards played with it</div></div>
            <div class="idea-share"><strong>${item.fit}%</strong><div class="meter"><span style="width: ${item.fit}%"></span></div></div>
            <button class="btn btn-small" data-start-commander="${escapeHtml(item.name)}">Start deck</button>
        </div>`).join('');
    const empty = !state.running && !state.error && state.started && !state.items.length
        ? `<div class="hint">No legendary creatures in ${buildKind === 'arena' ? 'your Arena collection' : 'the inventory'} yet.</div>` : '';
    list.innerHTML = progress + error + rows + empty;
}

async function pollIdeas(kind, start = false, body = {}) {
    // start: begin a run (body: what to look for); otherwise ask how the current one is doing
    clearTimeout(ideaTimers[kind]);
    const state = await api(`/api/decks/ideas/${kind}`, start ? {method: 'POST', body} : {});
    if (!state) return;
    // The button that started it stops it while it runs
    const button = document.querySelector(`[data-ideas="${kind}"]`);
    if (button) {
        button.dataset.label = button.dataset.label || button.textContent;
        button.dataset.running = state.running ? '1' : '';
        button.textContent = state.running ? 'Stop' : button.dataset.label;
    }
    renderIdeas(kind, state);
    if (state.running) ideaTimers[kind] = setTimeout(() => pollIdeas(kind), 1500);
}

function stopIdeas(kind) {
    // What was found so far stays
    return pollIdeas(kind, true, {stop: true});
}

// -- Build around a card: your cards legal in a format -> public decks that play one ----

// Which collection "What can I build?" asks about: the paper cards ('paper') or the Arena
// collection ('arena'). It decides whose cards are listed, what counts as owned in the
// rankings, and the kind of a deck started from this tab.
let buildKind = recall('buildKind', 'paper');

function showBuildKind(kind) {
    buildKind = kind === 'arena' && gameInfo.arena ? 'arena' : 'paper';
    remember('buildKind', buildKind);
    markSwitch('build-kind', 'kind', buildKind);
    // What is on display was found in the other collection
    aroundCard = null;
    $('ideas-commanders').innerHTML = '';
    renderAround();
    loadAroundCards();
}

let aroundCard = null;   // the card on display (clicked in the list)
let aroundState = null;  // the last answer about the search for decks
let aroundRequest = 0;

async function loadAroundCards() {
    const request = ++aroundRequest;
    const format = $('around-format').value;
    const params = new URLSearchParams({owned: '1', format});
    if (buildKind === 'arena') params.set('kind', 'arena');   // the cards of the Arena collection
    if ($('around-search').value.trim()) params.set('q', $('around-search').value.trim());
    if ($('around-type').value.trim()) params.set('type', $('around-type').value.trim());
    if ($('around-free').checked) params.set('free', '1');
    // Only offered for a format that has a commander
    $('around-commanders-label').hidden = !hasCommander(format);
    if ($('around-commanders').checked && hasCommander(format)) params.set('commander', '1');
    const data = await api(`/api/cards/search?${params}`);
    if (!data || request !== aroundRequest) return;  // a later search already answered
    $('around-cards-title').textContent = `Your ${buildKind === 'arena' ? 'Arena ' : ''}cards legal in ${formatLabel(format)}`;
    $('around-cards').innerHTML = data.cards.map(card => `
        <div class="result-row ${aroundCard && aroundCard.name === card.name ? 'is-chosen' : ''}" data-name="${escapeHtml(card.name)}" data-type="${escapeHtml(card.type_line)}"
             data-image="${escapeHtml(card.image_uri || '')}" data-commander="${isCommanderCard(card) ? '1' : ''}">
            <span class="result-main">
                <div><span class="result-name">${escapeHtml(card.name)}</span> ${manaHtml(card.mana_cost)}</div>
                <div class="result-sub">${escapeHtml(card.type_line)}</div>
            </span>
            <span class="result-numbers">${card.owned} owned</span>
        </div>`).join('') + (data.more ? '<div class="hint">More cards - type a name or type to narrow the list</div>' : '')
        || '<div class="hint">None of your cards match. Deck data missing? Update the card database.</div>';
}

function chooseAround(row) {
    // Shows the card; looking for decks waits for "Find decks" (it asks other sites)
    aroundCard = {name: row.dataset.name, commander: !!row.dataset.commander, format: $('around-format').value,
                  image: row.dataset.image, type: row.dataset.type};
    document.querySelectorAll('#around-cards .result-row').forEach(other => other.classList.toggle('is-chosen', other === row));
    renderAround();
}

function findAround() {
    if (!aroundCard) return;
    $('around-decks').innerHTML = '';
    pollIdeas('card', true, {card: aroundCard.name, format: aroundCard.format, collection: buildKind});
}

function renderAround(state = aroundState) {
    aroundState = state;
    const card = aroundCard;
    // A run made for the other collection counted other cards as owned: not shown
    const found = state && state.started && state.card && (state.collection || 'paper') === buildKind ? state : null;
    const running = !!(found && found.running);
    const mine = found && card && found.card === card.name && found.format === card.format;
    // A search that is running stays on display (and can be stopped) while another card is looked at
    const shown = running || mine || !card ? found : null;
    $('around-decks-title').textContent = shown ? `${formatLabel(shown.format)} decks with ${shown.card}` : 'Decks';
    const status = shown ? (running ? (shown.total ? `Reading the decks... ${shown.done} of ${shown.total}`
                : 'Asking Archidekt - for a much played card this can take half a minute...')
            : shown.stopped ? `Stopped after ${shown.done} of ${shown.total || '?'} decks`
            : `${plural(shown.items.length, 'deck')}, the ones you own most of first`)
        : card ? 'Find decks looks for public decks that play it.' : '';
    const buttons = (running ? '<button class="btn btn-small" id="around-stop">Stop</button>'
            : card ? `<button class="btn btn-small btn-primary" id="around-find">${mine ? 'Find again' : 'Find decks'}</button>` : '')
        + (card && card.commander && hasCommander(card.format)
            ? '<button class="btn btn-small" id="around-commander">Start a deck with it as commander</button>' : '');
    $('around-progress').innerHTML = (card ? `<div class="around-card">
            ${card.image ? `<img src="${escapeHtml(card.image)}" alt="${escapeHtml(card.name)}">` : ''}
            <div>
                <div class="idea-name">${escapeHtml(card.name)}</div>
                <div class="idea-meta">${escapeHtml(card.type || '')}</div>
                <div class="filter-row">${buttons}</div>
                <div class="hint">${status}</div>
            </div>
        </div>` : buttons || status ? `<div class="filter-row"><span class="hint">${status}</span><span class="spacer"></span>${buttons}</div>` : '')
        + (shown && shown.error ? `<div class="callout warning">${escapeHtml(shown.error)}</div>` : '');
    $('around-decks').innerHTML = !shown
        ? (card ? '' : '<div class="hint">Click one of your cards to see it, then Find decks to look for decks that play it.</div>')
        : shown.items.map(item => `
        <div class="idea-row precon">
            <div><div class="idea-name">${escapeHtml(item.name)}</div>
                 <div class="idea-meta">${escapeHtml(item.source)}${item.author ? ' · ' + escapeHtml(item.author) : ''} · ${item.views.toLocaleString()} views · ${item.owned} of ${item.total} cards owned</div></div>
            <div class="idea-share"><strong>${item.percent}%</strong><div class="meter" style="width: 70px"><span style="width: ${item.percent}%"></span></div></div>
            <div class="idea-actions">
                <a class="mini-btn" href="${escapeHtml(item.url)}" target="_blank" rel="noopener" title="Open on ${escapeHtml(item.source)}"><svg class="icon"><use href="#i-link"/></svg></a>
                <button class="btn btn-small" data-import-url="${escapeHtml(item.url)}" title="Open a copy as a new deck here">Copy as deck</button>
            </div>
        </div>`).join('') || (running || shown.error ? '' : '<div class="hint">No public decks found with this card in this format.</div>');
}

// ============================================================================
// Decks: builder
// ============================================================================

const BOARD_TITLES = {commander: 'Commander', main: 'Main deck', side: 'Sideboard'};
const TYPE_GROUPS = [['Creature', 'Creatures'], ['Planeswalker', 'Planeswalkers'], ['Instant', 'Instants'],
                     ['Sorcery', 'Sorceries'], ['Artifact', 'Artifacts'], ['Enchantment', 'Enchantments'],
                     ['Battle', 'Battles'], ['Land', 'Lands']];
let sidePanel = 'search';
let searchColors = new Set();
let searchOffset = 0;
let searchTimer = null;
let suggestions = null;    // {deckKey, data}: loaded per commander

function openDeck(payload) {
    deck = payload;
    suggestions = null;
    $('deck-home').hidden = true;
    $('deck-builder').hidden = false;
    $('deck-tabs').hidden = true;   // the list's tabs: not while one deck is shown
    $('deck-format').innerHTML = optionsHtml(gameInfo.deck_formats);
    renderDeck();
    showSide(hasCommander(deck.format) && commanders().length && deck.totals.cards < 30 ? 'suggestions' : 'search');
    // An empty deck wants cards: the panel for adding them is open from the start
    showAdding(deck.cards.length === 0);
    window.scrollTo(0, 0);
    showAddress(`/decks/${deck.id}`, `${deck.name} - Decks`);
}

function closeDeck() {
    deck = null;
    showAdding(false);
    $('deck-builder').hidden = true;
    $('deck-home').hidden = false;
    $('deck-tabs').hidden = false;
    loadDecks();
    showAddress('/decks', 'Decks');
}

function commanders() {
    return deck.cards.filter(entry => entry.board === 'commander');
}

function commanderNames() {
    return commanders().map(entry => entry.name);
}

function updateDeck(payload) {
    // The deck after a change, and what is shown beside it
    deck = payload;
    renderDeck();
    refreshSide();
}

function sideTitle() {
    return hasCommander(deck.format) ? 'Considering (not in the deck)' : BOARD_TITLES.side;
}

function typeGroup(entry) {
    const front = ((entry.card && entry.card.type_line) || '').split(' // ')[0];
    // A creature that is also an artifact or enchantment is filed as a creature; a land always as a land
    if (front.includes('Land')) return 'Lands';
    const found = TYPE_GROUPS.find(([type]) => front.includes(type));
    return found ? found[1] : 'Other';
}

function ownState(entry, wanted) {
    // What you have of a card this deck wants `wanted` copies of (over all its boards):
    // [kind, short mark, the explanation shown on pointing at it]
    const elsewhere = totalQuantity(entry.elsewhere);
    const others = entry.elsewhere.map(other => `${other.quantity} in ${other.deck}`).join(', ');
    if (entry.owned >= wanted + elsewhere) return ['have', '✓', `You own ${entry.owned}${others ? ' - also ' + others : ''}`];
    if (entry.owned >= wanted) return ['shared', '⇄', `You own ${entry.owned}, but other decks want it too: ${others}`];
    if (entry.owned > 0) return ['partly', `${entry.owned}/${wanted}`, `You own ${entry.owned} of ${wanted}`];
    return ['none', '✕', deck && deck.kind === 'arena' ? 'Not in your Arena collection' : 'Not in your inventory'];
}

function ownHtml(entry, wanted) {
    const [kind, mark, title] = ownState(entry, wanted);
    return `<span class="own-mark ${kind}" title="${escapeHtml(title)}">${mark}</span>`;
}

function entryActionsHtml(entry) {
    // What can be done with a card of the deck, the same buttons in both views: one copy
    // less / more, the printing shown, and where it can move (bindBuilderEvents answers them
    // by their data- attributes)
    const card = entry.card;
    const moves = [];
    if (entry.board !== 'main') moves.push(['main', 'Main', 'Move to the main deck']);
    if (entry.board !== 'side') moves.push(['side', hasCommander(deck.format) ? 'Maybe' : 'Side', `Move to: ${sideTitle()}`]);
    if (canCommand(card) && entry.board !== 'commander') moves.push(['commander', 'Cmdr', 'Make it the commander']);
    // The deck's cover: any of its cards with a picture. The one chosen says so, and a click
    // on it gives the choice up (the deck then shows its commander, or its most valuable card)
    const isCover = deck.cover === entry.name;
    const cover = card && card.image_uri ? `<button class="mini-btn ${isCover ? 'is-on' : ''}" data-cover="${isCover ? 'off' : 'on'}" title="${
        isCover ? "This card is the deck's cover - click to go back to the usual one" : "Show this card as the deck's cover, in the list and behind its name"}">${isCover ? '★ Cover' : 'Cover'}</button>` : '';
    return `<button class="mini-btn" data-change="-1" title="One less"><svg class="icon"><use href="#i-minus"/></svg></button>
            <button class="mini-btn" data-change="1" title="One more"><svg class="icon"><use href="#i-plus"/></svg></button>
            ${card ? `<button class="mini-btn printing-btn" data-printing title="Choose the printing shown">${
                escapeHtml(entry.printing.set_code ? `${entry.printing.set_code} ${entry.printing.number}` : 'Printing')}</button>` : ''}${moves.map(([board, label, title]) =>
                `<button class="mini-btn" data-move="${board}" title="${escapeHtml(title)}">${label}</button>`).join('')}${cover}`;
}

function deckRowHtml(entry, wanted) {
    // Columns view: one card as a line of a decklist - how many, its name, its cost, whether
    // you own it, its price. Pointing at the line shows the card's picture beside it
    // (data-image, library.js) and puts the buttons where the price was.
    const card = entry.card;
    return `
        <div class="deck-row" data-name="${escapeHtml(entry.name)}" data-board="${entry.board}" data-image="${escapeHtml((card && card.image_uri) || '')}">
            <span class="deck-row-qty">${entry.quantity}</span>
            <span class="deck-row-name ${card ? '' : 'unknown'}" title="${card ? '' : 'Not in the card data'}">${escapeHtml(entry.name)}</span>
            <span class="deck-row-cost">${card ? manaHtml(card.mana_cost) : ''}</span>
            ${ownHtml(entry, wanted)}
            <span class="deck-row-price">${card ? money(card.price * entry.quantity) : ''}</span>
            <span class="deck-row-actions">${entryActionsHtml(entry)}</span>
        </div>`;
}

function deckCardHtml(entry, wanted) {
    // Stacks view: the card itself. Its picture is asked for only when it comes into view
    // (loading="lazy": a deck is a hundred pictures); a card without one - not in the card
    // data, or the picture did not arrive - is a card-shaped box with its name and cost.
    // No data-image here: the card is the picture, nothing has to be shown beside it.
    const card = entry.card;
    const [kind, mark, title] = ownState(entry, wanted);
    return `
        <div class="deck-row stack-card" data-name="${escapeHtml(entry.name)}" data-board="${entry.board}" tabindex="0">
            <span class="stack-card-name">${escapeHtml(entry.name)} ${card ? manaHtml(card.mana_cost) : ''}</span>
            ${card && card.image_uri ? `<img src="${escapeHtml(card.image_uri)}" alt="${escapeHtml(entry.name)}" loading="lazy" onerror="this.remove()">` : ''}
            ${entry.quantity > 1 ? `<span class="stack-card-qty">×${entry.quantity}</span>` : ''}
            ${kind === 'have' ? '' : `<span class="stack-card-own own-mark ${kind}" title="${escapeHtml(title)}">${mark}</span>`}
            <span class="stack-card-foot"><span>${card ? money(card.price * entry.quantity) : 'not in the card data'}</span><span class="deck-row-actions">${entryActionsHtml(entry)}</span></span>
        </div>`;
}

// -- How the deck is shown: as columns of text or as stacks of cards, grouped three ways --

let deckView = recall('deckView', 'columns');        // 'columns' | 'stacks'
let deckGrouping = recall('deckGrouping', 'type');   // 'type' | 'cost' | 'colour'

const COLOUR_GROUPS = [['W', 'White'], ['U', 'Blue'], ['B', 'Black'], ['R', 'Red'], ['G', 'Green']];

function groupOf(entry) {
    // The heading a main-deck card is filed under, for the grouping chosen. Lands are a
    // group of their own in every grouping (they have no cost, and no colour to speak of);
    // a card the data does not know is "Other".
    const group = typeGroup(entry);
    if (deckGrouping === 'type' || group === 'Lands' || !entry.card) return group;
    if (deckGrouping === 'cost') {
        const cost = Math.min(7, Math.floor(entry.card.cmc || 0));
        return cost === 7 ? 'Cost 7 or more' : `Cost ${cost}`;
    }
    const colours = entry.card.colors || entry.card.identity || [];
    if (colours.length > 1) return 'Multicolour';
    const found = COLOUR_GROUPS.find(([letter]) => colours.includes(letter));
    return found ? found[1] : 'Colourless';
}

function groupTitles() {
    // The headings in the order they are shown
    if (deckGrouping === 'cost') return [...Array(7).keys()].map(cost => `Cost ${cost}`).concat(['Cost 7 or more', 'Lands', 'Other']);
    if (deckGrouping === 'colour') return [...COLOUR_GROUPS.map(([, title]) => title), 'Multicolour', 'Colourless', 'Lands', 'Other'];
    return [...TYPE_GROUPS.map(([, title]) => title), 'Other'];
}

function deckGroups() {
    // [[title, entries]]: the commander first, the main deck by the grouping chosen, then
    // what is only considered (the sideboard, where the format has one)
    const byName = (a, b) => byText(a.name, b.name);
    const groups = [[BOARD_TITLES.commander, commanders()]];
    const main = deck.cards.filter(entry => entry.board === 'main');
    groupTitles().forEach(title => groups.push([title, main.filter(entry => groupOf(entry) === title).sort(byName)]));
    groups.push([sideTitle(), deck.cards.filter(entry => entry.board === 'side').sort(byName)]);
    return groups.filter(([, entries]) => entries.length);
}

function showDeckView(view = deckView, grouping = deckGrouping) {
    deckView = view === 'stacks' ? 'stacks' : 'columns';
    deckGrouping = ['type', 'cost', 'colour'].includes(grouping) ? grouping : 'type';
    remember('deckView', deckView);
    remember('deckGrouping', deckGrouping);
    markSwitch('deck-view', 'view', deckView);
    markSwitch('deck-grouping', 'grouping', deckGrouping);
    if (deck) renderDeck();
}

function renderDeck() {
    $('deck-name').value = deck.name;
    $('deck-format').value = deck.format;
    const totals = deck.totals;
    const considering = hasCommander(deck.format);

    // The banner: the commander's picture behind the deck's name, colours and numbers
    const leaders = commanders();
    const face = coverOf(deck);
    const art = face && face.image_uri;
    $('deck-hero').style.backgroundImage = art ? `url('${artOf(art)}')` : '';
    $('deck-hero').classList.toggle('no-art', !art);
    $('deck-hero').title = face ? `Cover: ${face.name}` : '';
    // Two commanders: the banner shows one, this turns to the other
    $('deck-flip').hidden = (deck.covers || []).length < 2;
    $('deck-commanders').textContent = leaders.map(entry => entry.name).join(' + ');
    $('deck-identity').innerHTML = identityHtml([...new Set(leaders.flatMap(entry => (entry.card && entry.card.identity) || []))]);
    const problems = deck.issues.filter(issue => issue.level === 'error').length;
    $('deck-legal').innerHTML = !totals.cards ? ''
        : deck.issues.length ? `<span class="deck-chip ${problems ? 'bad' : 'warn'}">${problems ? '✕' : '!'} ${plural(deck.issues.length, 'problem')}</span>`
        : `<span class="deck-chip ok">✓ Legal in ${escapeHtml(formatLabel(deck.format))}</span>`;
    const owned = totals.cards ? Math.round(100 * (totals.cards - totals.missing) / totals.cards) : 0;
    // An Arena deck: owned means "in the Arena collection", and what is missing costs
    // wildcards, not money (its paper value says nothing about it and is left out)
    const digital = deck.kind === 'arena';
    const wild = digital ? wildcardsHtml(deck.wildcards) : '';
    $('deck-totals').innerHTML = `
        ${digital ? `<span class="deck-kind-badge" title="${deck.from_arena ? 'This deck came from MTG Arena: the next import replaces it with what it is there then - changes made here are lost' : 'A deck for MTG Arena, made here: counted against your Arena collection. The next Arena import with a deck file removes it - every Arena deck is then the file\'s'}">Arena</span>` : ''}
        <span><strong>${totals.cards}</strong> cards${totals.side ? ` <small>+ ${totals.side} ${considering ? 'considered' : 'sideboard'}</small>` : ''}</span>
        ${digital ? '' : `<span><strong>${money(totals.price)}</strong> value</span>`}
        <span title="${totals.missing ? `${plural(totals.missing, 'card')} missing` : digital ? 'Every card is in your Arena collection' : 'You own every card'}"><strong>${owned}%</strong> ${digital ? 'in Arena' : 'owned'}${
            totals.missing ? ` <small>${totals.missing} missing${digital ? '' : ', ' + money(totals.missing_price)}</small>` : ''}</span>
        ${wild ? `<span title="One wildcard of a card's rarity crafts one copy. The rarity is that of the card's Arena printing (the lowest, when there are several)">to craft: ${wild}</span>` : ''}`;
    // The problems themselves, under the banner (a legal deck has its chip above and nothing here)
    $('deck-issues').innerHTML = deck.issues.map(issue => `
        <div class="issue ${issue.level}">${issue.level === 'error' ? '✕' : '!'} ${escapeHtml(issue.message)}${issue.cards.length
            ? `<span class="issue-cards">: ${escapeHtml(issue.cards.slice(0, 12).join(', '))}${issue.cards.length > 12 ? ` and ${issue.cards.length - 12} more` : ''}</span>` : ''}</div>`).join('')
        || (totals.cards ? `<div class="issue ok">✓ Legal ${escapeHtml(formatLabel(deck.format))} deck</div>` : '');

    // Copies of each card over the boards that are played
    const played = deck.cards.filter(entry => !(considering && entry.board === 'side'));
    const wanted = {};
    played.forEach(entry => { wanted[entry.name] = (wanted[entry.name] || 0) + entry.quantity; });
    renderDeckCharts(played.filter(entry => entry.board !== 'side' && entry.card));

    const one = deckView === 'stacks' ? deckCardHtml : deckRowHtml;
    const list = $('deck-cards');
    list.className = `deck-cards deck-${deckView}`;
    list.innerHTML = deckGroups().map(([title, entries]) => `
        <section class="deck-group">
            <div class="deck-group-title"><span>${escapeHtml(title)}</span><span>${totalQuantity(entries)}</span></div>
            ${entries.map(entry => one(entry, wanted[entry.name] || entry.quantity)).join('')}
        </section>`).join('')
        || '<div class="empty-state">No cards yet. Add some with the panel on the right, or import a list.</div>';

    $('side-suggestions').hidden = !considering;
    $('search-identity-label').hidden = !considering;
}

function renderDeckCharts(entries) {
    if (!entries.length) {
        $('deck-charts').innerHTML = '';
        return;
    }
    // Mana curve: spells by mana value (lands have none)
    const curve = Array(8).fill(0);
    const pips = {W: 0, U: 0, B: 0, R: 0, G: 0};
    const types = new Map();
    entries.forEach(entry => {
        const group = typeGroup(entry);
        types.set(group, (types.get(group) || 0) + entry.quantity);
        if (group !== 'Lands') curve[Math.min(7, Math.floor(entry.card.cmc || 0))] += entry.quantity;
        ((entry.card.mana_cost || '').match(/\{[^}]+\}/g) || []).forEach(symbol =>
            Object.keys(pips).forEach(color => { if (symbol.includes(color)) pips[color] += entry.quantity; }));
    });
    const top = Math.max(...curve, 1);
    const colorNames = Object.fromEntries(COLORS);
    $('deck-charts').innerHTML = `
        <div><div class="chart-title">Mana curve</div>
            <div class="curve">${curve.map((count, cost) => `
                <div class="curve-col" title="Mana value ${cost}${cost === 7 ? ' or more' : ''}: ${plural(count, 'card')}">
                    <span>${count || ''}</span><div class="curve-bar" style="height: ${(72 * count / top).toFixed(0)}px"></div><span>${cost}${cost === 7 ? '+' : ''}</span>
                </div>`).join('')}</div></div>
        <div><div class="chart-title">Types</div>${barsHtml([...types.entries()], number => String(number), 9)}</div>
        <div><div class="chart-title">Mana symbols</div>${barsHtml(Object.entries(pips).map(([color, count]) => [colorNames[color], count]), number => String(number), 5)}</div>`;
}

// -- The deck for MTG Arena ---------------------------------------------------------

async function openArena() {
    // Arena's Import button makes a deck from the text on the clipboard. The window shows
    // that text - only the cards that exist on Arena - and says which of the deck's cards
    // had to be left out.
    const data = await api(`/api/decks/${deck.id}/arena`);
    if (!data) return;
    $('arena-text').value = data.text;
    $('arena-subtitle').textContent = `${deck.name}: ${plural(data.cards, 'card')} of ${deck.totals.cards + (hasCommander(deck.format) ? 0 : deck.totals.side)}`;
    const out = data.left_out;
    $('arena-left-out').hidden = !out.length;
    $('arena-left-out').textContent = out.length
        ? `Not on Arena, and left out of the list: ${out.slice(0, 40).join(', ')}${out.length > 40 ? ` and ${out.length - 40} more` : ''}` : '';
    $('arena-check').hidden = false;
    $('arena-check').innerHTML = arenaCheckHtml(data.check, data.cards);
    $('arena-copy').disabled = $('arena-download').disabled = !data.text;
    $('arena-modal').classList.add('show');
    $('arena-text').select();
}

function arenaCheckHtml(check, onArena) {
    // "Can I build this in Arena?" - the deck against the Arena collection as last imported:
    // how many of its copies are there already, which cards would be crafted and what that
    // costs in wildcards, how many Arena does not have at all (named above the check)
    if (!check.imported) {
        return '<div class="hint">To see which of these cards you already have in Arena, import your Arena collection (the collection page, <strong>Arena</strong>).</div>';
    }
    const copies = totalQuantity(check.craft.map(card => ({quantity: card.copies})));
    const wild = wildcardsHtml(check.wildcards);
    const short = ['common', 'uncommon', 'rare', 'mythic'].some(rarity => (check.wildcards.needed[rarity] || 0) > (check.wildcards.have[rarity] || 0));
    const verdict = !copies && !check.not_on_arena ? '<span class="deck-chip ok">✓ You have every card in Arena</span>'
        : !copies ? '<span class="deck-chip warn">! You have every card that is on Arena</span>'
        : short ? '<span class="deck-chip bad">✕ Not with the wildcards you have</span>'
        : '<span class="deck-chip warn">! Buildable by crafting</span>';
    return `
        <h3 class="section-title">Can you build it in Arena? ${verdict}</h3>
        <div class="arena-check-row"><strong>${check.have}</strong> of ${onArena} ${onArena === 1 ? 'copy is' : 'copies are'} in your Arena collection
            <small>(as exported ${escapeHtml(check.imported.slice(0, 10))}; basic lands are free)</small></div>
        ${copies ? `<div class="arena-check-row"><strong>${copies}</strong> to craft: ${wild || 'no wildcards needed'}</div>
            <div class="arena-check-cards">${check.craft.map(card =>
                `<span class="rarity-${escapeHtml(card.rarity)}" title="${escapeHtml(card.rarity)}">${card.copies} ${escapeHtml(card.name)}</span>`).join('')}</div>` : ''}
        ${check.not_on_arena ? `<div class="arena-check-row"><strong>${check.not_on_arena}</strong> not on Arena (named above)</div>` : ''}`;
}

async function copyArena() {
    // navigator.clipboard only exists on pages loaded over https or from this very machine,
    // and the scanner's pages usually come over plain http from another machine: there the
    // old way is used - select the text in its field and ask the browser to copy the selection
    const field = $('arena-text');
    let copied = false;
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(field.value);
            copied = true;
        }
    } catch (error) { /* refused: the old way below */ }
    if (!copied) {
        field.focus();
        field.select();
        try { copied = document.execCommand('copy'); } catch (error) { copied = false; }
    }
    notify(copied ? 'Copied - in Arena: Decks, then Import' : 'The browser did not copy it: select the text and press Ctrl+C',
           copied ? 'success' : 'warning');
}

// -- Printing of a deck card ------------------------------------------------------

let printingEntry = null;   // {name, board} of the entry whose printing is being chosen

async function openPrintings(name, board) {
    const entry = deck.cards.find(card => card.name === name && card.board === board);
    if (!entry) return;
    printingEntry = {name, board};
    $('printing-title').textContent = name;
    $('printing-grid').innerHTML = '<div class="hint">Loading the printings...</div>';
    $('printing-modal').classList.add('show');
    const data = await api(`/api/cards/printings?name=${encodeURIComponent(name)}`);
    if (!data) return closeModal('printing-modal');
    // The printings you own first, then the newest
    const printings = [...data.printings].sort((a, b) => (b.owned > 0) - (a.owned > 0));
    $('printing-grid').innerHTML = printings.map(printing => `
        <button class="printing ${printing.id === entry.printing.id ? 'is-current' : ''}" data-id="${escapeHtml(printing.id)}">
            ${printing.image_uri ? `<img src="${escapeHtml(printing.image_uri)}" alt="" loading="lazy">` : '<div class="no-image"></div>'}
            <span class="printing-set">${escapeHtml(printing.set)}</span>
            <span class="printing-meta">
                <span>${escapeHtml((printing.set_code || '').toUpperCase())} #${escapeHtml(printing.number)}</span>
                <span>${printing.price ? money(printing.price) : printing.price_foil ? money(printing.price_foil) + ' foil'
                    : printing.price_etched ? money(printing.price_etched) + ' etched' : ''}</span>
                ${printing.owned ? `<span class="own have">✓ ${printing.owned} owned</span>` : ''}
            </span>
            ${printing.treatments.length ? `<span class="printing-meta">${escapeHtml(printing.treatments.join(', '))}</span>` : ''}
        </button>`).join('') || '<div class="hint">No printings found.</div>';
}

async function changeDeckCards(cards) {
    const data = await api(`/api/decks/${deck.id}/cards`, {method: 'POST', body: {cards}});
    if (!data) return;
    updateDeck(data.deck);
}

async function saveDeckInfo(body) {
    const data = await api(`/api/decks/${deck.id}`, {method: 'PUT', body});
    if (!data) return;
    updateDeck(data.deck);
}

// -- Adding cards: a panel that slides in from the right, with search, suggestions and
// -- popular decks as its three parts ---------------------------------------------

function showAdding(open) {
    // The class on <body> also makes room for the panel beside the deck (decks.css)
    $('add-drawer').classList.toggle('show', open);
    document.body.classList.toggle('adding', open);
    if (open && sidePanel === 'search') $('search-text').focus();
}

function showDeckMenu(open) {
    $('deck-more-list').hidden = !open;
}

function showSide(panel) {
    sidePanel = panel;
    markSwitch('side-switch', 'side', panel);
    $('side-search').hidden = panel !== 'search';
    $('side-suggestions-panel').hidden = panel !== 'suggestions';
    $('side-popular-panel').hidden = panel !== 'popular';
    refreshSide(true);
}

function refreshSide(opened = false) {
    // After the deck changed: what is shown beside it depends on its cards
    if (sidePanel === 'search') { if (opened) runSearch(); else markResults(); }
    if (sidePanel === 'suggestions') loadSuggestions();
    if (sidePanel === 'popular' && opened) loadPopular();
}

function inDeck(name) {
    return totalQuantity(deck.cards.filter(entry => entry.name === name));
}

function addLabelHtml(count) {
    // On a result's add button: the copies already in the deck
    return count ? `${count} +` : '<svg class="icon"><use href="#i-plus"/></svg>';
}

function canCommand(card) {
    return !!card && hasCommander(deck.format) && isCommanderCard(card);
}

function resultRowHtml(card, numbers = '') {
    return `
        <div class="result-row" data-name="${escapeHtml(card.name)}" data-id="${escapeHtml(card.id)}" data-image="${escapeHtml(card.image_uri || '')}" title="${escapeHtml(card.oracle_text)}">
            <span class="result-main">
                <div><span class="result-name">${escapeHtml(card.name)}</span> ${manaHtml(card.mana_cost)}</div>
                <div class="result-sub">${escapeHtml(card.type_line)}</div>
            </span>
            <span class="result-numbers">${numbers}${card.owned ? `<span class="own have">✓ ${card.owned} owned</span>` : ''}<div>${money(card.price)}</div></span>
            <span class="result-actions">
                ${canCommand(card) ? '<button class="mini-btn" data-add="commander" title="Make it the commander">Cmdr</button>' : ''}
                <button class="mini-btn" data-add="main" title="Add to the deck">${addLabelHtml(inDeck(card.name))}</button>
            </span>
        </div>`;
}

async function runSearch(more = false) {
    if (!deck) return;
    searchOffset = more ? searchOffset : 0;
    const params = new URLSearchParams({offset: searchOffset});
    const add = (key, value) => { if (value) params.set(key, value); };
    add('q', $('search-text').value.trim());
    add('type', $('search-type').value.trim());
    add('text', $('search-oracle').value.trim());
    add('cmc', $('search-cmc').value);
    add('rarity', $('search-rarity').value);
    add('colors', [...searchColors].join(''));
    add('owned', $('search-owned').checked ? '1' : '');
    add('kind', deck.kind === 'arena' ? 'arena' : '');   // an Arena deck: "owned" is the Arena collection
    if ($('search-free').checked) {
        params.set('free', '1');
        params.set('deck_id', deck.id);
    }
    add('format', $('search-legal').checked ? deck.format : '');
    if (hasCommander(deck.format) && $('search-identity').checked && commanders().some(entry => entry.card)) {
        params.set('identity', [...new Set(commanders().flatMap(entry => (entry.card && entry.card.identity) || []))].join(''));
    }
    const data = await api(`/api/cards/search?${params}`);
    if (!data || !deck) return;
    const html = data.cards.map(card => resultRowHtml(card)).join('');
    const list = $('search-results');
    if (more) list.insertAdjacentHTML('beforeend', html);
    else list.innerHTML = html || '<div class="empty-state">No cards match.</div>';
    searchOffset += data.cards.length;
    $('search-more').hidden = !data.more;
}

function markResults() {
    // The counts on the add buttons follow the deck
    document.querySelectorAll('#search-results .result-row').forEach(row => {
        row.querySelector('[data-add="main"]').innerHTML = addLabelHtml(inDeck(row.dataset.name));
    });
}

async function loadSuggestions() {
    const key = `${deck.id}:${commanderNames().join('|')}`;
    if (!suggestions || suggestions.key !== key) {
        $('suggestions-list').innerHTML = '<div class="hint">Asking EDHREC...</div>';
        $('suggestions-source').textContent = '';
        const data = await api(`/api/decks/${deck.id}/suggestions`);
        if (!deck) return;
        suggestions = {key, data: data || {categories: [], message: 'Suggestions are not available right now'}};
    }
    const data = suggestions.data;
    const ownedOnly = $('suggestions-owned').checked;
    const freeOnly = $('suggestions-free').checked;
    $('suggestions-source').innerHTML = data.decks
        ? `Played with this commander in ${data.decks.toLocaleString()} decks - <a href="${escapeHtml(data.url)}" target="_blank" rel="noopener">EDHREC</a>` : '';
    const html = data.categories.map(category => {
        const cards = category.cards.filter(card => !inDeck(card.name) && (!ownedOnly || card.owned) && (!freeOnly || !card.elsewhere));
        return cards.length ? `<div class="category-title">${escapeHtml(category.title)}</div>` + cards.map(card => resultRowHtml(card,
            `<span title="In ${card.inclusion}% of this commander's decks; synergy ${card.synergy > 0 ? '+' : ''}${card.synergy}%">${card.inclusion}% </span>`)).join('') : '';
    }).join('');
    const average = !deck.totals.cards || deck.totals.cards <= 2
        ? '<button class="btn btn-small btn-block" id="suggestions-average">Start from EDHREC\'s average deck</button>' : '';
    $('suggestions-list').innerHTML = (data.categories.length ? average : '') + (html
        || `<div class="empty-state">${escapeHtml(data.message || (ownedOnly ? 'You own none of the suggested cards that are not in the deck already.' : 'No suggestions left.'))}</div>`);
}

async function startFromAverage() {
    const data = await api(`/api/decks/${deck.id}/import`, {method: 'POST',
        body: {average: commanderNames(), replace: true}});
    if (!data) return;
    reportUnknown(data.unknown);
    notify("Filled with EDHREC's average deck", 'success');
    updateDeck(data.deck);
}

async function loadPopular() {
    $('popular-list').innerHTML = '<div class="hint">Looking...</div>';
    const data = await api(`/api/decks/popular?deck_id=${deck.id}`);
    if (!data || !deck) return;
    $('popular-source').textContent = data.commander
        ? `Most viewed public decks with ${data.commander} (Archidekt)`
        : `Most viewed public ${formatLabel(deck.format)} decks (Archidekt, Moxfield)`;
    $('popular-list').innerHTML = data.problems.map(problem => `<div class="callout warning">${escapeHtml(problem)}</div>`).join('')
        + (data.decks.map(item => `
            <div class="result-row">
                <span class="result-main">
                    <div class="result-name">${escapeHtml(item.name)}</div>
                    <div class="result-sub">${escapeHtml(item.source)}${item.author ? ' · ' + escapeHtml(item.author) : ''} · ${item.views.toLocaleString()} views</div>
                </span>
                <span class="result-actions">
                    <a class="mini-btn" href="${escapeHtml(item.url)}" target="_blank" rel="noopener" title="Open on ${escapeHtml(item.source)}"><svg class="icon"><use href="#i-link"/></svg></a>
                    <button class="mini-btn" data-import-url="${escapeHtml(item.url)}" title="Open a copy as a new deck here">Copy</button>
                </span>
            </div>`).join('') || (data.problems.length ? '' : '<div class="empty-state">No decks found.</div>'));
}

function bindDeckHomeEvents() {
    // Deck list
    $('deck-new').addEventListener('click', () => openDeckModal());
    $('deck-sort').value = recall('deckSort', 'changed');
    $('deck-sort').addEventListener('change', event => {
        remember('deckSort', event.target.value);
        renderDeckList();
    });
    $('deck-filter-format').addEventListener('change', renderDeckList);
    bindSwitch('deck-kind', button => {
        deckKindShown = button.dataset.kind;
        remember('deckKindShown', deckKindShown);
        markSwitch('deck-kind', 'kind', deckKindShown);
        renderDeckList();
    });
    // Only marks the choice; saveDeckModal reads it
    bindSwitch('new-deck-kind', button => markSwitch('new-deck-kind', 'kind', button.dataset.kind));
    $('deck-filter-text').addEventListener('input', debounce(renderDeckList, 150));
    $('deck-modal-save').addEventListener('click', saveDeckModal);
    $('deck-list').addEventListener('click', async event => {
        const tile = event.target.closest('[data-deck]');
        if (!tile) return;
        // The button on a deck with two commanders turns its cover; it does not open the deck
        if (event.target.closest('[data-flip]')) {
            event.preventDefault();
            turnCover(deckList.find(item => String(item.id) === tile.dataset.deck));
            return renderDeckList();
        }
        // A tile is a link (/decks/<id>). With Ctrl, Shift or the middle button it is left to
        // the browser - a new tab; a plain click opens the deck here, without loading the page
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.button) return;
        event.preventDefault();
        const data = await api(`/api/decks/${tile.dataset.deck}`);
        if (data) openDeck(data.deck);
    });
    // The list's tabs, in the header
    $('deck-tabs').addEventListener('click', event => {
        const tab = event.target.closest('.tab');
        if (tab) showDeckTab(tab.dataset.tab);
    });
    showDeckTab(recall('deckTab', 'mine'));
    document.querySelectorAll('[data-ideas]').forEach(button => button.addEventListener('click', () =>
        button.dataset.running ? stopIdeas(button.dataset.ideas)
            // The precon ranking reads only the kind of deck that is chosen
            : pollIdeas(button.dataset.ideas, true, button.dataset.ideas === 'precons' ? {type: $('precon-type').value}
                                                                                     : {collection: buildKind})));
    $('build-kind-row').hidden = !gameInfo.arena;
    bindSwitch('build-kind', button => showBuildKind(button.dataset.kind));
    if (!gameInfo.arena) buildKind = 'paper';
    markSwitch('build-kind', 'kind', buildKind);

    // Build around a card
    $('around-format').innerHTML = optionsHtml(gameInfo.deck_formats);
    $('around-format').addEventListener('change', () => {
        aroundCard = null;  // chosen for the other format
        renderAround();
        loadAroundCards();
    });
    ['around-search', 'around-type'].forEach(id => $(id).addEventListener('input', debounce(loadAroundCards)));
    $('around-free').addEventListener('change', loadAroundCards);
    $('around-commanders').addEventListener('change', loadAroundCards);
    $('around-cards').addEventListener('click', event => {
        const row = event.target.closest('.result-row');
        if (row) chooseAround(row);
    });
    $('around-progress').addEventListener('click', event => {
        if (event.target.id === 'around-find') findAround();
        if (event.target.id === 'around-stop') stopIdeas('card');
        if (event.target.id === 'around-commander') {
            createDeck({name: aroundCard.name, format: aroundCard.format, commander: aroundCard.name, kind: buildKind});
        }
    });
    // A public deck copied from this tab is a deck of the collection it was ranked against
    $('around-decks').addEventListener('click', event => copyDeckClicked(event, buildKind));
    $('ideas-commanders').addEventListener('click', event => {
        const button = event.target.closest('[data-start-commander]');
        // In Arena the format with a commander is Brawl
        if (button) createDeck({name: button.dataset.startCommander, format: buildKind === 'arena' ? 'brawl' : 'commander',
                                commander: button.dataset.startCommander, kind: buildKind});
    });
    $('precon-search').addEventListener('input', debounce(renderPrecons, 150));
    $('precon-type').addEventListener('change', renderPrecons);
    const preconClicked = event => {
        const row = event.target.closest('[data-file]');
        const item = row && precons.find(precon => precon.file === row.dataset.file);
        if (!item) return;
        // The button on a deck with two commanders turns its cover; anything else on the
        // tile opens the window with the deck's cards ("Create deck" and "I own it" are there)
        if (event.target.closest('[data-flip]')) {
            preconFace[item.file] = (preconFace[item.file] || 0) + 1;
            row.querySelector('.deck-tile-card').innerHTML = preconCoverHtml(item);
            return;
        }
        viewPrecon(item);
    };
    $('ideas-precons').addEventListener('click', preconClicked);
    $('ideas-precons').addEventListener('keydown', event => { if (event.key === 'Enter') preconClicked(event); });
    $('precon-create').addEventListener('click', async () => {
        const item = viewedPrecon;
        // A second deck of the same name makes every card of the first count for two decks
        if (deckList.some(existing => existing.name.toLowerCase() === item.name.toLowerCase())
            && !await confirmDialog({title: `You already have a deck called ${item.name}`,
                                     message: 'Create another one with the same name?', confirmText: 'Create another'})) return;
        closeModal('precon-modal');
        createDeck({name: item.name, format: item.format, precon: item.file}, 'Deck created');
    });
    $('precon-own').addEventListener('click', () => {
        closeModal('precon-modal');
        ownPrecon(viewedPrecon);
    });
    $('deck-data-update').addEventListener('click', event => {
        event.target.disabled = true;
        $('deck-data-progress').textContent = 'Starting...';
        socket.emit('update_database');
    });
}

function bindBuilderEvents() {
    // Header
    $('deck-back').addEventListener('click', event => {
        // A link to /decks for a new tab; a plain click goes back without loading the page
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.button) return;
        event.preventDefault();
        closeDeck();
    });
    // The panel for adding cards, and the menu of the things done seldom
    $('deck-add').addEventListener('click', () => showAdding(!$('add-drawer').classList.contains('show')));
    $('add-close').addEventListener('click', () => showAdding(false));
    $('deck-more').addEventListener('click', event => {
        event.stopPropagation();
        showDeckMenu($('deck-more-list').hidden);
    });
    document.addEventListener('click', () => showDeckMenu(false));   // a click anywhere else, or on one of its entries
    $('deck-flip').addEventListener('click', () => {
        turnCover(deck);
        renderDeck();
    });
    // How the deck is shown
    bindSwitch('deck-view', button => showDeckView(button.dataset.view, deckGrouping));
    bindSwitch('deck-grouping', button => showDeckView(deckView, button.dataset.grouping));
    showDeckView();
    $('deck-name').addEventListener('change', event => saveDeckInfo({name: event.target.value}));
    $('deck-format').addEventListener('change', event => saveDeckInfo({format: event.target.value}));
    $('deck-import').addEventListener('click', () => openDeckModal({importInto: deck}));
    $('deck-export').addEventListener('click', () => { window.location = `/api/decks/${deck.id}/export/text`; });
    // Only a game that has a digital client to write for (games/: arena_decklist) shows the button
    $('deck-arena').hidden = !gameInfo.arena;
    $('deck-arena').addEventListener('click', openArena);
    $('arena-copy').addEventListener('click', copyArena);
    $('arena-download').addEventListener('click', () => { window.location = `/api/decks/${deck.id}/export/arena`; });
    $('deck-buylist').addEventListener('click', () => {
        if (!deck.totals.missing) return notify('You own every card of this deck', 'success');
        window.location = `/api/decks/${deck.id}/export/buylist`;
    });
    $('deck-duplicate').addEventListener('click', async () => {
        // With a digital collection the copy can be of either kind: an Arena deck copied as
        // Physical shows what you own of it on paper and what the rest costs to buy; a
        // Physical deck copied as Arena, what you have in Arena and the wildcards for the rest
        let kind = deck.kind;
        if (gameInfo.arena) {
            showDeckMenu(false);
            kind = await choiceDialog({
                title: `Duplicate ${deck.name}`,
                message: 'As a deck of which collection? The copy counts what you own there, and what is missing: '
                    + 'to buy for a Physical deck, to craft with wildcards for an Arena deck.',
                choices: [{label: 'Physical', value: 'paper', style: deck.kind === 'paper' ? 'primary' : undefined},
                          {label: 'Arena', value: 'arena', style: deck.kind === 'arena' ? 'primary' : undefined},
                          {label: 'Cancel', value: null}]});
            if (!kind) return;
        }
        const data = await api(`/api/decks/${deck.id}/duplicate`, {method: 'POST', body: {kind}});
        if (data) openDeck(data.deck);
    });
    $('deck-delete').addEventListener('click', async () => {
        const ok = await confirmDialog({title: `Delete "${deck.name}"?`, confirmText: 'Delete', danger: true,
            message: "The deck list is deleted. Your inventory is not touched."});
        if (ok && await api(`/api/decks/${deck.id}`, {method: 'DELETE'})) closeDeck();
    });

    // Deck cards
    $('deck-cards').addEventListener('click', event => {
        const row = event.target.closest('.deck-row');
        const button = event.target.closest('.mini-btn');
        if (!row || !button) return;
        const card = {name: row.dataset.name, board: row.dataset.board};
        if (button.dataset.cover) saveDeckInfo({cover: button.dataset.cover === 'on' ? card.name : ''});
        else if ('printing' in button.dataset) openPrintings(card.name, card.board);
        else if (button.dataset.change) changeDeckCards([{...card, change: parseInt(button.dataset.change)}]);
        else if (button.dataset.move) changeDeckCards([{...card, move_to: button.dataset.move}]);
    });

    $('printing-grid').addEventListener('click', event => {
        const button = event.target.closest('.printing');
        if (!button || !printingEntry) return;
        closeModal('printing-modal');
        changeDeckCards([{...printingEntry, printing: button.dataset.id}]);
    });

    // Search, suggestions, popular decks
    bindSwitch('side-switch', button => showSide(button.dataset.side));
    ['search-text', 'search-type', 'search-oracle'].forEach(id => $(id).addEventListener('input', debounce(() => runSearch())));
    ['search-cmc', 'search-rarity', 'search-owned', 'search-free', 'search-legal', 'search-identity']
        .forEach(id => $(id).addEventListener('change', () => runSearch()));
    $('search-colors').innerHTML = colorChipsHtml(searchColors);
    bindColorChips('search-colors', searchColors, () => runSearch());
    $('search-more').addEventListener('click', () => runSearch(true));
    const addFromRow = event => {
        const row = event.target.closest('.result-row[data-name]');
        if (!row || event.target.closest('a')) return;
        const button = event.target.closest('[data-add]');
        changeDeckCards([{name: row.dataset.name, card_id: row.dataset.id, board: button ? button.dataset.add : 'main', change: 1}]);
    };
    $('search-results').addEventListener('click', addFromRow);
    $('suggestions-list').addEventListener('click', event => {
        if (event.target.id === 'suggestions-average') return startFromAverage();
        addFromRow(event);
    });
    $('suggestions-owned').addEventListener('change', loadSuggestions);
    $('suggestions-free').addEventListener('change', loadSuggestions);
    $('popular-list').addEventListener('click', copyDeckClicked);
    $('popular-import').addEventListener('click', () => {
        const url = $('popular-url').value.trim();
        if (url) createDeck({url}, 'Deck copied');
    });
}

// ============================================================================
// The page: its address, what it borrows from the collection page, start-up
// ============================================================================

function showAddress(path, title) {
    // A deck has an address (/decks/7): it can be bookmarked and sent, a reload stays in the
    // deck, and the browser's Back leads from a deck to the list. The page itself is not
    // loaded again for that - only the address shown is changed (and a step added to the
    // browser's history, which popstate below answers when Back or Forward is pressed).
    document.title = `${title} - Card Scanner`;
    if (window.location.pathname !== path) history.pushState(null, '', path);
}

async function showWhatTheAddressSays() {
    // /decks/<id>: that deck; /decks: the list. A deck that is gone (deleted in another tab,
    // or an old bookmark) shows the list and says so.
    const match = window.location.pathname.match(/^\/decks\/(\d+)$/);
    if (!match) {
        if (deck) closeDeck();
        return;
    }
    if (deck && String(deck.id) === match[1]) return;
    const response = await fetch(`/api/decks/${match[1]}`);
    const data = response.ok ? await response.json() : null;
    if (data && data.deck) return openDeck(data.deck);
    notify('That deck does not exist (any more)', 'warning');
    history.replaceState(null, '', '/decks');
    if (deck) closeDeck();
}

let knownPlaces = null;   // the inventory's locations, asked for once when a dialog offers them

async function knownLocations() {
    // "I own it" suggests the places cards are kept in. The inventory is not on this page,
    // so it is asked for when the dialog first needs it (the collection page has it loaded)
    if (!knownPlaces) {
        const data = await api('/api/inventory');
        knownPlaces = data ? distinct((data.cards || data.inventory || []).map(card => card.location)) : [];
    }
    return knownPlaces;
}

// Called by the shared dialogs when the inventory changed: what is owned may have
function inventoryChanged() {
    refreshOwned();
}

const refreshOwned = debounce(() => {
    // Owned counts follow the inventory: the open deck, or the list
    if (deck) api(`/api/decks/${deck.id}`).then(data => { if (data && deck) { deck = data.deck; renderDeck(); } });
    else loadDecks();
}, 500);

// The inventory changes while scanning on another tab or device
// - and so does the Arena collection, when an export is imported (the list then has other Arena decks)
// Another price source: its currency, then what the deck shows is asked again (its prices and totals come from the server)
socket.on('price_source_changed', data => { window.PRICE_SYMBOL = data.symbol; });
['inventory_updated', 'inventory_undone', 'inventory_prices_updated', 'collection_updated', 'arena_updated', 'price_source_changed'].forEach(name => socket.on(name, refreshOwned));
socket.on('game_changed', () => window.location.reload());
socket.on('database_update_progress', data => { $('deck-data-progress').textContent = data.message; });
socket.on('database_update_complete', () => {
    $('deck-data-progress').textContent = '';
    notify('Card database updated', 'success');
    if (deck) refreshOwned(); else loadDecks();
});
socket.on('database_update_error', data => {
    $('deck-data-progress').textContent = '';
    $('deck-data-update').disabled = false;
    notify(`Card database update failed: ${data.message}`, 'error');
});

document.addEventListener('DOMContentLoaded', async () => {
    const data = await api('/api/games');
    if (!data) return;
    gameInfo = data.games.find(game => game.id === data.active);
    // A game without deck formats has no decks: its collection page is the place to be
    if (!gameInfo.deck_formats.length) return window.location.replace('/collection');
    $('game-label').textContent = data.games.length > 1 ? gameInfo.label : '';
    bindDeckHomeEvents();
    bindBuilderEvents();
    bindValueDialog();
    bindCardPreview();
    // Topmost first
    bindOverlays([
        ['dialog-modal', () => closeDialog(null)],
        ['value-modal', () => closeValueDialog(null)],
        ['printing-modal', () => closeModal('printing-modal')],
        ['precon-modal', () => closeModal('precon-modal')],
        ['deck-modal', () => closeModal('deck-modal')],
        ['arena-modal', () => closeModal('arena-modal')],
        ['add-drawer', () => showAdding(false)],   // Escape closes the panel for adding cards
    ]);
    window.addEventListener('popstate', showWhatTheAddressSays);
    await loadDecks();
    loadPrecons();
    loadAroundCards();
    await showWhatTheAddressSays();
    // "Add to a deck > New deck..." on the collection page sends its card names along
    if (new URLSearchParams(window.location.search).get('new')) {
        let text = '';
        try { text = sessionStorage.getItem('newDeckText') || ''; sessionStorage.removeItem('newDeckText'); } catch (e) { /* storage blocked */ }
        history.replaceState(null, '', '/decks');
        openDeckModal({text});
    }
});
