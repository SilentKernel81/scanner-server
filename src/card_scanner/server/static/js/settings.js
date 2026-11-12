// The settings page (templates/settings.html): every setting of the program in sections (the plan:
// docs/plans/SETTINGS_REDESIGN_PLAN.md), each saved the moment it changes. Loaded after audio.js and common.js; it has its own `$`,
// `api` and connection (scanner.js, collection.js and library.js are for other pages and declare
// the same names).
//
// Per camera (Cameras): the connection to the server is opened for the chosen camera
// (?station=), so that the events of the camera's settings (auto-add, focus, rotation, debug
// trace) reach that camera's desk, as they do from its own page. The rest is the server's.

const $ = id => document.getElementById(id);
const plural = (count, word, many = word + 's') => `${count} ${count === 1 ? word : many}`;

async function api(path, options = {}) {
    // JSON request; shows the server's error and returns null when it fails
    if (options.body && typeof options.body !== 'string' && !(options.body instanceof FormData)) {
        options = {...options, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(options.body)};
    }
    try {
        const response = await fetch(path, options);
        const data = await response.json();
        if (data.success === false || (response.status >= 400 && data.error)) {
            notify(data.error || data.message || 'Request failed', 'error');
            return null;
        }
        return data;
    } catch (error) {
        notify(`Request failed: ${error.message}`, 'error');
        return null;
    }
}

// A setting that only acts while another one is in some state is greyed out and cannot be changed otherwise - the locked-focus checks while the camera's autofocus is on,
// the sounds while sound effects are off. Its value is kept: it applies again as soon as the other setting allows it.
function setDependents(ids, enabled) {
    for (const id of ids) {
        const control = $(id);
        if (!control) continue;
        control.disabled = !enabled;
        const row = control.closest('.switch-row, .input-group, .volume-row');
        if (row) row.classList.toggle('is-dependent-off', !enabled);
    }
}

function remember(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* storage blocked */ }
}

function recall(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
}

const CATEGORIES = ['overview', 'cameras', 'reading', 'carddata', 'backups', 'storage', 'server'];

// The sections the page had before the redesign of 2026-10-22, and where their contents went: other pages link to the old addresses
// (the collection page sends #data, an older bookmark #sounds) and a browser may remember one as its last section
const OLD_CATEGORIES = {sounds: 'cameras', data: 'backups'};

// ============================================================================
// Categories
// ============================================================================

function showCategory(name, remembered = true) {
    name = OLD_CATEGORIES[name] || name;
    if (!CATEGORIES.includes(name)) name = 'overview';
    CATEGORIES.forEach(category => {
        $('cat-' + category).hidden = category !== name;
    });
    document.querySelectorAll('#settings-nav button').forEach(button =>
        button.classList.toggle('is-active', button.dataset.category === name));
    if (remembered) {
        try { history.replaceState(null, '', location.pathname + location.search + '#' + name); } catch (e) { /* fine */ }
        remember('settingsCategory', name);
    }
}

// The old addresses: the scanner page's drawer (#settings) was cameras, sound and the AI; the
// collection page's was backups and storage
function categoryFromAddress() {
    const asked = location.hash.replace('#', '');
    const name = OLD_CATEGORIES[asked] || asked;
    if (CATEGORIES.includes(name)) return name;
    const remembered = recall('settingsCategory', 'overview');
    return OLD_CATEGORIES[remembered] || remembered;
}

// ============================================================================
// The overview: one line per section, how things stand. Nothing is asked for it: each loader below hands its part over
// (setOverview) when its own answer comes - the stations, the card data, the index, the backups... - and the list is drawn again.
// A line is a button to its section; a line marked `warn` is something to look at.
// ============================================================================

const OVERVIEW_ORDER = [
    ['cameras', 'Cameras', 'cameras'], ['reading', 'Card recognition', 'reading'], ['carddata', 'Card data', 'carddata'], ['prices', 'Prices', 'carddata'],
    ['index', 'Picture index', 'carddata'], ['backups', 'Backups', 'backups'], ['storage', 'Storage', 'storage'], ['server', 'Server', 'server'],
];
const overview = {};     // line -> {text, warn}

function setOverview(line, text, warn = false) {
    overview[line] = {text, warn};
    renderOverview();
}

function renderOverview() {
    $('overview-list').innerHTML = OVERVIEW_ORDER.filter(([line]) => overview[line]).map(([line, label, section]) =>
        `<button type="button" class="overview-row${overview[line].warn ? ' is-warn' : ''}" data-goto="${section}">`
        + `<span class="overview-label">${escapeHtml(label)}</span><span class="overview-text">${escapeHtml(overview[line].text)}</span>`
        + `<span class="overview-go" aria-hidden="true">&rsaquo;</span></button>`).join('')
        || '<div class="hint">Loading...</div>';
}

function shortTime(iso) {
    return new Date(iso).toLocaleString(undefined, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
}

// Card recognition's line is made of three answers that come separately (the OCR, the AI, the reading mode)
const readingParts = {};

function overviewReading(part, value) {
    readingParts[part] = value;
    const {ocr, ai, reading} = readingParts;
    if (!reading) return;
    const steps = [];
    if (reading.mode === 'evidence') steps.push('picture');
    if (ocr) steps.push('OCR');
    if (ai) steps.push('vision AI');
    const text = steps.length ? 'Reads by ' + steps.join(', then ') : 'Every step is off: each card goes to review';
    setOverview('reading', text, !steps.length);
}

// ============================================================================
// The connection (one for the chosen camera) and the server's answers
// ============================================================================

let socket = null;
let cameraId = null;   // the camera chosen under Cameras

function connect() {
    if (socket) socket.disconnect();
    socket = io(cameraId ? {query: {station: cameraId}} : {});

    socket.on('error', data => {
        if (data && data.locked) return unlockAndReconnect();
        notify((data && data.message) || 'The server refused that', 'error');
    });

    // Camera
    socket.on('fast_scan_toggled', () => {});
    socket.on('stop_at_card_back_toggled', data => { $('toggle-stop-at-back').checked = Boolean(data.enabled); });
    socket.on('camera_rotation_updated', data => {
        $('camera-rotation').value = String(data.rotation);
        notify(`Camera image rotated ${data.rotation}°` + (data.fixed_area_off ? ' - fixed area off, draw it again' : ''), 'info');
        loadCameraSettings();
    });
    socket.on('refocus_every_updated', data => { $('refocus-every').value = String(data.captures); });
    socket.on('refocus_on_drop_updated', data => showRefocusOnDrop(data.ratio));
    socket.on('fixed_area_updated', () => loadCameraSettings());
    socket.on('dropper_updated', applyDropper);
    socket.on('feeders_found', showFeedersFound);
    socket.on('feeder_paired', data => {
        $('dropper-config-key').value = '';          // used once, kept nowhere
        if (data.ok) { $('dropper-found').textContent = ''; $('dropper-pairing').hidden = true; }
        notify(data.ok ? `Paired with the feeder at ${data.feeder.ip}` : `Not paired: ${data.message}`, data.ok ? 'success' : 'error');
    });
    socket.on('dropper_tested', data => notify(data.ok ? `Card released (${plural(data.pulses, 'card')} since the station started)`
                                                       : `The card dropper did not release a card: ${data.message}`, data.ok ? 'success' : 'error'));

    // Card recognition
    socket.on('ocr_toggled', data => applyOcrState(data.enabled, data.installed));
    socket.on('ai_toggled', data => applyAiState(data.enabled, data.available));
    socket.on('reading_mode_changed', applyReadingState);
    socket.on('debug_mode_toggled', data => applyDebugMode(data.enabled, data.running, data.debugger));
    socket.on('ai_provider_set', data => {
        activeProvider = data.provider; activeModel = data.model;
        notify(data.message || 'AI provider changed', 'success');
        loadPromptSummary();
    });
    socket.on('ai_credential_saved', onCredentialSaved);

    // Card data
    socket.on('database_update_progress', data => { $('database-progress').textContent = data.message; });
    socket.on('database_update_complete', data => {
        $('update-database').disabled = false;
        $('update-database').textContent = 'Update card database';
        $('database-progress').textContent = `Updated: ${data.total_cards.toLocaleString()} cards loaded.`;
        notify('Card data updated', 'success');
        loadDatabaseState();
        loadIndex();
        loadUpdateSchedule();
    });
    socket.on('database_update_error', data => {
        $('update-database').disabled = false;
        $('update-database').textContent = 'Update card database';
        $('database-progress').textContent = `The update failed: ${data.message}`;
        notify(`Card data update failed: ${data.message}`, 'error');
        loadUpdateSchedule();
    });
}

// ============================================================================
// Cameras
// ============================================================================

let stations = [];

function stationSetupUrl(station) {
    // The station's own page (which camera, its name, its server). A station on this computer
    // connects from a loopback address: that is this page's host
    if (!station.setup || !station.setup.port) return '';
    const loopback = !station.setup.address || ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(station.setup.address);
    const host = loopback ? window.location.hostname : station.setup.address;
    return `http://${host.includes(':') ? '[' + host + ']' : host}:${station.setup.port}`;
}

async function loadStations(keep = true) {
    const data = await api('/api/stations');
    if (!data) return;
    stations = data.stations;
    $('server-origin').textContent = window.location.origin;
    const connected = stations.filter(station => station.connected).length;
    setOverview('cameras', stations.length ? `${connected} of ${plural(stations.length, 'camera')} connected` : 'No camera has connected yet', !connected);
    const select = $('camera-select');
    select.innerHTML = stations.map(station =>
        `<option value="${escapeHtml(station.id)}">${escapeHtml(station.name)}${station.connected ? '' : ' (not connected)'}</option>`).join('');
    $('camera-empty').hidden = stations.length > 0;
    $('camera-settings').hidden = stations.length === 0;
    select.hidden = stations.length === 0;
    document.querySelector('label[for="camera-select"]').hidden = stations.length === 0;
    if (!stations.length) { cameraId = null; return; }
    const wanted = (keep && cameraId) || new URLSearchParams(location.search).get('camera') || recall('settingsCamera', '');
    const chosen = stations.find(station => station.id === wanted)
        || stations.find(station => station.connected) || stations[0];
    select.value = chosen.id;
    if (cameraId !== chosen.id) {
        cameraId = chosen.id;
        connect();
    }
    showCamera();
}

function currentStation() {
    return stations.find(station => station.id === cameraId) || null;
}

function showCamera() {
    const station = currentStation();
    if (!station) return;
    $('camera-name').value = station.name;
    $('camera-location').value = station.location || '';
    $('camera-status').textContent =
        `${station.connected ? 'Connected' : 'Not connected'} · ${plural(station.scanned, 'scanned card')} · `
        + `${station.captures} captured in all · last seen ${station.last_seen || 'never'}`
        + (station.camera_error ? ` · camera: ${station.camera_error}` : '');
    $('camera-page').href = '/scan/' + encodeURIComponent(station.id);
    const url = stationSetupUrl(station);
    $('camera-setup').hidden = !url;
    if (url) $('camera-setup').href = url;
    const first = stations[0];
    $('edit-prompts').href = '/scan/' + encodeURIComponent((station || first).id) + '#prompts';
    loadCameraSettings();
}

let cameraRequest = 0;

async function loadCameraSettings() {
    const mine = ++cameraRequest;
    const query = cameraId ? '?station=' + encodeURIComponent(cameraId) : '';
    const data = await api('/api/scan_settings' + query);
    if (!data || mine !== cameraRequest) return;
    $('toggle-auto-add').checked = Boolean(data.auto_add);
    $('toggle-stop-at-back').checked = data.stop_at_card_back !== false;     // on unless switched off
    $('toggle-autofocus').checked = Boolean(data.autofocus);
    applyFocusMode(Boolean(data.autofocus));
    $('refocus-every').value = String(data.refocus_every);
    showRefocusOnDrop(data.refocus_on_drop);
    $('camera-rotation').value = String(data.camera_rotation || 0);
    $('toggle-debug-trace').checked = Boolean(data.debug_trace);
    applyDropper(data.dropper);
    $('fixed-area-state').textContent = data.fixed_area_enabled
        ? 'Fixed area: on. Cards are judged by the area drawn on the camera\'s page, not by their outline. Draw or turn it off there.'
        : 'Fixed area: off. Cards are found by their outline; the area for sleeved cards is drawn on the camera\'s page.';
    $('location-options').innerHTML = (data.locations || [])
        .map(location => `<option value="${escapeHtml(location)}"></option>`).join('');
    // The server's own settings come with the same answer
    applySound(data.sound);
    applyOcrState(data.ocr_first, data.ocr_installed);
    applyAiState(data.ai_enabled, data.ai_available);
    applyReadingState(data.reading);
    applyDebugMode(data.debug_mode, data.debug_mode_running, data.debugger_running);
}

// The card dropper (station/dropper.py; the server's settings_events: set_dropper / test_dropper): this camera's settings, and what
// the station says of it - the cards released since it started, or why the last one could not be
function applyDropper(payload) {
    if (!payload) return;
    const settings = payload.settings || {}, state = payload.state;
    $('toggle-dropper').checked = Boolean(settings.enabled);
    // Not while it is being typed in: the answer to the previous change would undo the next keystrokes
    if (document.activeElement !== $('dropper-pin')) $('dropper-pin').value = settings.pin === null || settings.pin === undefined ? '' : String(settings.pin);
    if (document.activeElement !== $('dropper-pulse')) $('dropper-pulse').value = String(settings.pulse_ms);
    if (document.activeElement !== $('dropper-chip')) $('dropper-chip').value = settings.chip || '';
    $('dropper-active-low').checked = Boolean(settings.active_low);
    const wifi = settings.transport === 'wifi';
    $('dropper-transport').value = wifi ? 'wifi' : 'gpio';
    $('dropper-gpio').hidden = wifi;
    $('dropper-wifi').hidden = !wifi;
    const feeder = settings.feeder;
    $('dropper-feeder').textContent = feeder && settings.paired
        ? `Paired with ${feeder.name || 'the feeder'} at ${feeder.ip}.` : 'No feeder paired yet: find it on the station\'s network.';
    $('dropper-forget').hidden = !(feeder && settings.paired);
    $('dropper-test').disabled = !settings.enabled || !payload.connected;
    $('dropper-state').textContent = !payload.connected ? 'The station is not connected: its settings are sent when it connects.'
        : !state ? 'This station\'s program has no card dropper yet - update the station.'
        : state.error ? `It could not release a card: ${state.error}`
        : settings.enabled ? `On: ${plural(state.pulses, 'card')} released since the station started.`
        : 'Off.';
}

function saveDropper() {
    // The whole set each time: the server checks it whole (an empty pin is "none"); the paired feeder is the server's to keep
    const pin = $('dropper-pin').value.trim();
    socket.emit('set_dropper', {dropper: {
        enabled: $('toggle-dropper').checked,
        transport: $('dropper-transport').value,
        pin: pin === '' ? null : parseInt(pin, 10),
        pulse_ms: parseInt($('dropper-pulse').value, 10),
        chip: $('dropper-chip').value.trim(),
        active_low: $('dropper-active-low').checked,
    }});
}

// A feeder over Wi-Fi: the station looks on its own network (find_feeders), and pairs the one chosen with the feeder's key (pair_feeder)
function showFeedersFound(data) {
    const list = $('dropper-found');
    list.textContent = '';
    if (!data.ok) { notify(`Could not look for feeders: ${data.message}`, 'error'); return; }
    if (!data.feeders.length) { list.textContent = 'No feeder answered on the station\'s network.'; return; }
    $('dropper-pairing').hidden = false;
    for (const feeder of data.feeders) {
        const row = document.createElement('div');
        row.className = 'settings-actions';
        const label = document.createElement('span');
        label.textContent = `${feeder.name} at ${feeder.ip}` + (feeder.paired ? ` (paired with ${feeder.station || 'a station'})` : '');
        const pair = document.createElement('button');
        pair.type = 'button';
        pair.className = 'btn btn-small';
        pair.textContent = 'Pair';
        pair.addEventListener('click', () => {
            const key = $('dropper-config-key').value;
            if (!key) { notify('Type the feeder\'s key first', 'error'); $('dropper-config-key').focus(); return; }
            socket.emit('pair_feeder', {ip: feeder.ip, config_key: key});
        });
        row.append(label, pair);
        list.append(row);
    }
}

// The two focus checks act on a LOCKED focus only (autofocus off): greyed out while the camera focuses by itself
function applyFocusMode(autofocus) {
    setDependents(['refocus-every', 'refocus-on-drop'], !autofocus);
}

function showRefocusOnDrop(ratio) {
    // A value that is not one of the choices (set in config.yaml) is shown as it is
    const select = $('refocus-on-drop');
    const value = String(ratio || 0);
    if (![...select.options].some(option => option.value === value)) {
        select.add(new Option(`When they are ${Math.round(ratio * 100)}% as sharp (config.yaml)`, value));
    }
    select.value = value;
}

async function saveStation(change) {
    const station = currentStation();
    if (!station) return;
    const data = await api('/api/stations/' + encodeURIComponent(station.id), {method: 'PUT', body: change});
    if (data) {
        await loadStations();
        notify('Saved', 'success');
    }
}

async function forgetCamera() {
    const station = currentStation();
    if (!station) return;
    const ok = await confirmDialog({
        title: `Forget ${station.name}?`,
        message: 'It is removed from the list, with the cards it scanned that are not in the collection yet and the cards it has waiting for review. Cards already in the collection stay. It comes back, empty, if it connects or sends a card again.',
        confirmText: 'Forget and delete its cards', danger: true
    });
    if (!ok) return;
    const data = await api('/api/stations/' + encodeURIComponent(station.id), {method: 'DELETE'});
    if (!data) return;
    notify(`Forgotten: ${plural(data.cards, 'scanned card')} and ${plural(data.reviews, 'review card')} removed`, 'success');
    cameraId = null;
    await loadStations(false);
}

function bindCameras() {
    $('camera-select').addEventListener('change', event => {
        cameraId = event.target.value;
        remember('settingsCamera', cameraId);
        connect();
        showCamera();
    });
    $('camera-name').addEventListener('change', event => {
        const name = event.target.value.trim();
        if (name) saveStation({name}); else showCamera();
    });
    $('camera-location').addEventListener('change', event => saveStation({location: event.target.value.trim()}));
    $('camera-undo').addEventListener('click', () => {
        // Answered with inventory_updated (undone) or an error
        socket.emit('undo_last_add', {station: cameraId});
        notify('Asked it to take back the last card added', 'info');
    });
    $('camera-forget').addEventListener('click', forgetCamera);

    $('toggle-stop-at-back').addEventListener('change', event => {
        socket.emit('toggle_stop_at_card_back', {enabled: event.target.checked});
        notify(event.target.checked ? 'A card back stops auto-capture' : 'A card back no longer stops auto-capture', 'success');
    });
    $('toggle-auto-add').addEventListener('change', event => {
        socket.emit('toggle_fast_scan', {enabled: event.target.checked});
        notify(`Cards are added ${event.target.checked ? 'automatically' : 'after you confirm them'}`, 'success');
    });
    $('toggle-autofocus').addEventListener('change', event => {
        applyFocusMode(event.target.checked);
        socket.emit('set_autofocus', {enabled: event.target.checked});
        notify(`Autofocus ${event.target.checked ? 'on' : 'off'}`, 'success');
    });
    $('refocus-every').addEventListener('change', event =>
        socket.emit('set_refocus_every', {captures: parseInt(event.target.value) || 0}));
    $('refocus-on-drop').addEventListener('change', event =>
        socket.emit('set_refocus_on_drop', {ratio: parseFloat(event.target.value)}));
    $('camera-rotation').addEventListener('change', event =>
        socket.emit('set_camera_rotation', {rotation: parseInt(event.target.value)}));
    for (const id of ['toggle-dropper', 'dropper-transport', 'dropper-pin', 'dropper-pulse', 'dropper-chip', 'dropper-active-low']) {
        $(id).addEventListener('change', saveDropper);
    }
    $('dropper-find').addEventListener('click', () => {
        $('dropper-found').textContent = 'Looking on the station\'s network...';
        socket.emit('find_feeders', {});
    });
    $('dropper-forget').addEventListener('click', () => socket.emit('forget_feeder', {}));
    $('dropper-test').addEventListener('click', () => socket.emit('test_dropper', {}));
    $('toggle-debug-trace').addEventListener('change', event => {
        socket.emit('toggle_debug_trace', {enabled: event.target.checked});
        notify(`Debug trace ${event.target.checked ? 'on' : 'off'} for this camera`, 'success');
    });
}

// ============================================================================
// Sounds
// ============================================================================

function applySound(sound) {
    if (!sound) return;
    $('toggle-audio').checked = sound.enabled;
    $('audio-volume').value = sound.volume;
    $('volume-value').textContent = sound.volume + '%';
    $('toggle-sound-capture').checked = sound.capture;
    $('toggle-sound-added').checked = sound.added;
    applySoundsEnabled(sound.enabled);
    audioManager.setEnabled(sound.enabled);
    audioManager.setVolume(sound.volume / 100);
    audioManager.setMuted('capture', !sound.capture);
    audioManager.setMuted('added', !sound.added);
}

// The single sounds and the volume only matter with sound effects on
function applySoundsEnabled(enabled) {
    setDependents(['toggle-sound-capture', 'toggle-sound-added', 'audio-volume', 'audio-test'], enabled);
}

function saveSound(change) {
    api('/api/sound', {method: 'POST', body: change});
}

function bindSounds() {
    $('toggle-audio').addEventListener('change', event => {
        applySoundsEnabled(event.target.checked);
        audioManager.setEnabled(event.target.checked);
        saveSound({enabled: event.target.checked});
        if (event.target.checked) audioManager.playSuccess();
    });
    $('toggle-sound-capture').addEventListener('change', event => {
        audioManager.setMuted('capture', !event.target.checked);
        saveSound({capture: event.target.checked});
        if (event.target.checked) audioManager.playCapture();
    });
    $('toggle-sound-added').addEventListener('change', event => {
        audioManager.setMuted('added', !event.target.checked);
        saveSound({added: event.target.checked});
        if (event.target.checked) audioManager.playAdded();
    });
    $('audio-volume').addEventListener('input', event => {
        audioManager.setVolume(event.target.value / 100);
        $('volume-value').textContent = event.target.value + '%';
    });
    // Saved when the slider is let go, not on every step of the drag
    $('audio-volume').addEventListener('change', event => saveSound({volume: parseInt(event.target.value)}));
    $('audio-test').addEventListener('click', () => {
        audioManager.ensureAudioContext().then(() => {
            audioManager.playCapture();
            setTimeout(() => audioManager.playSuccess(), 400);
            setTimeout(() => audioManager.playNextReady(), 1000);
        });
    });
}

// ============================================================================
// Card recognition: the picture, OCR, the vision AI
// ============================================================================

const OCR_DESC = $('ocr-desc').textContent;

const AI_DESC = $('ai-desc').textContent;

// The vision AI switch: off sends what OCR and the picture cannot decide to the review queue; without a provider set up there is nothing to switch
function applyAiState(enabled, available) {
    overviewReading('ai', Boolean(enabled) && Boolean(available));
    const toggle = $('toggle-ai');
    toggle.checked = Boolean(enabled) && Boolean(available);
    toggle.disabled = !available;
    $('ai-desc').textContent = !available ? 'No vision AI is set up (a provider and its key)'
        : enabled ? AI_DESC : 'Off: nothing is sent to an AI service; what is left goes to review';
}

function applyOcrState(enabled, installed) {
    overviewReading('ocr', Boolean(enabled) && Boolean(installed));
    const toggle = $('toggle-ocr');
    toggle.checked = Boolean(enabled) && Boolean(installed);
    toggle.disabled = !installed;
    $('ocr-desc').textContent = installed ? OCR_DESC
        : 'Not installed on this server (it needs Node.js 22+ and "npm install" in src/ocr; scripts/deploy.sh does it)';
}

// The reading mode (core/identification.py: reading_mode): off is OCR then the AI as always; on reads a card OCR could not confirm by its picture first
function applyReadingState(reading) {
    if (!reading) return;
    overviewReading('reading', reading);
    const evidence = reading.mode === 'evidence';
    $('toggle-reading-evidence').checked = evidence;
    $('toggle-picture-alone').checked = evidence && Boolean(reading.accept_image_alone);
    $('toggle-picture-alone').disabled = !evidence;
    $('toggle-extend-index').checked = Boolean(reading.extend_index);     // independent of the mode: it only keeps the index current
    $('reading-evidence-desc').textContent = evidence
        ? 'Compared with every printing\'s picture; a clear match settles the card'
        : 'Off: OCR first, then the vision AI';
    const missing = [];
    if (reading.index_printings === null || reading.index_printings === undefined) {
        missing.push('there is no picture index (Card data)');
    }
    // OCR off is no strip: only the picture alone can decide then, so it is a gap only while that is off too
    if (!reading.ocr_enabled && !reading.accept_image_alone) missing.push('OCR is switched off and the picture alone is not allowed');
    const pictureOnly = evidence && !reading.ocr_enabled && reading.accept_image_alone && reading.index_printings;
    // While the index lacks printings of the card data, the picture alone adds nothing (the server refuses it: a missing printing would be added as another one)
    const stale = evidence && reading.accept_image_alone && reading.index_missing
        ? `The picture index lacks ${plural(reading.index_missing, 'printing')}: until it is updated (Card data), cards the picture alone would settle go on to the next step. ` : '';
    // (the index's size is not repeated here: it is under Card data, with the button that updates it)
    $('reading-status').textContent = stale + (pictureOnly ? 'OCR is off: the picture alone decides what it can. ' : '')
        + (evidence && missing.length ? `Not working yet: ${missing.join(' and ')}.` : '');
}

let availableModels = {};
let activeProvider = null, activeModel = null;
let aiCredentials = {};

const PROVIDER_INFO = {
    gemini: {name: 'Google Gemini', keyUrl: 'https://aistudio.google.com/app/apikey'},
    openai: {name: 'OpenAI', keyUrl: 'https://platform.openai.com/api-keys'},
    anthropic: {name: 'Anthropic', keyUrl: 'https://console.anthropic.com/settings/keys'},
    local: {name: 'Local AI'}
};
const providerInfo = provider => PROVIDER_INFO[provider] || {name: provider};

function populateModels(provider, selected = null) {
    const select = $('ai-model');
    select.innerHTML = '';
    const models = availableModels[provider];
    if (!models || !models.length) {
        select.add(new Option('No models available', ''));
        return;
    }
    models.forEach(model => select.add(new Option(model, model, false, model === selected)));
}

async function loadLocalModels(selected = null) {
    $('ai-model').innerHTML = '<option value="">Loading models from Ollama...</option>';
    try {
        const data = await (await fetch('/api/local_ai_models')).json();
        if (data.success && data.models && data.models.length) availableModels.local = data.models;
        else notify('Using the static model list (the local AI server is not available)', 'warning');
    } catch (error) {
        notify('Could not reach the local AI server', 'warning');
    }
    populateModels('local', selected);
}

async function loadAI() {
    try {
        availableModels = (await (await fetch('/api/ai_models')).json()).models || {};
        aiCredentials = await (await fetch('/api/ai_credentials')).json();
        const active = await (await fetch('/api/ai_provider')).json();
        if (active.provider) {
            activeProvider = active.provider; activeModel = active.model;
            $('ai-provider').value = active.provider;
            if (active.provider === 'local') await loadLocalModels(active.model);
            else populateModels(active.provider, active.model);
        }
        renderCredentialField($('ai-provider').value);
    } catch (error) {
        notify(`Could not load the AI settings: ${error.message}`, 'error');
    }
}

function hasCredential(provider) {
    return provider === 'local' || Boolean(aiCredentials[provider] && aiCredentials[provider].configured);
}

function renderCredentialField(provider) {
    const input = $('ai-credential'), label = $('ai-credential-label'), hint = $('ai-credential-hint');
    const info = providerInfo(provider), status = aiCredentials[provider] || {};
    input.value = '';
    if (provider === 'local') {
        label.textContent = 'Server address';
        input.type = 'text';
        input.value = status.endpoint || '';
        input.placeholder = 'http://localhost:11434/v1/chat/completions';
        hint.textContent = 'Ollama or another OpenAI-compatible server';
        return;
    }
    label.textContent = `${info.name} API key`;
    input.type = 'password';
    if (status.configured) {
        input.placeholder = `Saved: ${status.masked} - type a new key to replace it`;
        hint.textContent = `Key configured (${status.masked})`;
    } else {
        input.placeholder = 'Paste your API key';
        hint.innerHTML = `No key yet - <a href="${info.keyUrl}" target="_blank" rel="noopener">get one from ${escapeHtml(info.name)}</a>`;
    }
}

function applyProvider(provider) {
    // The provider's models, and the program switches to it; returning to the active provider keeps its model
    const keep = provider === activeProvider ? activeModel : null;
    const loaded = provider === 'local' ? loadLocalModels(keep) : Promise.resolve(populateModels(provider, keep));
    loaded.then(() => socket.emit('set_ai_provider', {provider, model: $('ai-model').value}));
}

async function saveCredential() {
    const provider = $('ai-provider').value, value = $('ai-credential').value.trim();
    if (!value) {
        if (provider === 'local' || !hasCredential(provider)) {
            notify(provider === 'local' ? 'Enter the server address' : 'Paste an API key first', 'warning');
            return;
        }
        const ok = await confirmDialog({
            title: `Remove the ${providerInfo(provider).name} key?`,
            message: 'Removes the key saved in the web interface. A key in the .env file (if any) is used again after a restart.',
            confirmText: 'Remove key', danger: true
        });
        if (!ok) return;
    }
    socket.emit('save_ai_credential', {provider, value});
}

function onCredentialSaved(data) {
    aiCredentials[data.provider] = data.status;
    const selected = $('ai-provider').value, info = providerInfo(data.provider);
    renderCredentialField(selected);
    notify(data.provider === 'local' ? 'Local AI address saved'
        : data.status.configured ? `${info.name} API key saved` : `${info.name} API key removed`, 'success');
    if (data.provider === selected && hasCredential(selected)) applyProvider(selected);
}

const PROMPT_SOURCES = {'built-in': 'built-in prompt', 'all': 'saved for all models', 'model': 'saved for this model'};

async function loadPromptSummary() {
    try {
        const data = await (await fetch('/api/prompts')).json();
        const custom = data.order.map(kind => data.prompts[kind]).filter(prompt => prompt.source !== 'built-in');
        $('prompt-summary').textContent = custom.length
            ? custom.map(prompt => `${prompt.label}: ${PROMPT_SOURCES[prompt.source]}`).join(' · ') + '. The editor is on a scanner page.'
            : 'What the AI is asked about each card. The editor is on a scanner page.';
    } catch (error) { /* the summary is only a hint */ }
}

function bindReading() {
    $('toggle-ocr').addEventListener('change', event => socket.emit('toggle_ocr', {enabled: event.target.checked}));
    $('toggle-ai').addEventListener('change', event => socket.emit('toggle_ai', {enabled: event.target.checked}));
    // The mode is the program's design (the vision AI last): no question either way. The picture-alone switch decides what is added with no one asking: ON asks first,
    // and the page goes back if it is declined
    $('toggle-reading-evidence').addEventListener('change', event =>
        socket.emit('set_reading_mode', {mode: event.target.checked ? 'evidence' : 'cascade'}));
    $('toggle-picture-alone').addEventListener('change', async event => {
        const toggle = event.target;
        if (toggle.checked) {
            const ok = await confirmDialog({
                title: 'Add cards the picture alone decided?',
                message: 'A printing newer than the image index whose collector line cannot be read can then be added as another printing of the card, with no one asking. It is the picture-first design: keep the picture index current (Settings > Card data) and look at what is added.',
                confirmText: 'Turn on', danger: true
            });
            if (!ok) { toggle.checked = false; return; }
        }
        socket.emit('set_reading_mode', {accept_image_alone: toggle.checked});
    });
    // (not a risk to what is added - it only fetches pictures - so no confirmation; the event itself is guarded and the page goes back if declined)
    $('toggle-extend-index').addEventListener('change', event =>
        socket.emit('set_reading_mode', {extend_index: event.target.checked}));
    $('ai-provider').addEventListener('change', event => {
        const provider = event.target.value;
        renderCredentialField(provider);
        if (hasCredential(provider)) {
            applyProvider(provider);
        } else {
            populateModels(provider);
            $('ai-credential').focus();
            notify(`Enter your ${providerInfo(provider).name} API key to use it`, 'warning');
        }
    });
    $('ai-model').addEventListener('change', event =>
        socket.emit('set_ai_provider', {provider: $('ai-provider').value, model: event.target.value}));
    $('ai-credential').addEventListener('keydown', event => { if (event.key === 'Enter') saveCredential(); });
    $('save-credential').addEventListener('click', saveCredential);
    $('refresh-models').addEventListener('click', async () => {
        const provider = $('ai-provider').value;
        $('ai-model').innerHTML = '<option value="">Refreshing models...</option>';
        if (provider === 'local') {
            await loadLocalModels(activeModel);
        } else {
            try { availableModels = (await (await fetch('/api/ai_models')).json()).models || {}; } catch (e) { /* keep */ }
            populateModels(provider, provider === activeProvider ? activeModel : null);
        }
    });
}

// ============================================================================
// Backups, card data (with the picture index and the automatic updates), storage
// ============================================================================

async function loadBackups() {
    const data = await api('/api/backups');
    if (!data) return;
    renderBackups(data.backups);
    $('backup-every').value = String(data.schedule.every_hours);
    $('backup-keep').value = data.schedule.keep;
    $('backup-keep').disabled = !data.schedule.every_hours;
    backupSchedule = data.schedule;
    overviewBackups();
}

let backupSchedule = null, newestBackup = null;    // for the overview's line

function overviewBackups() {
    const every = backupSchedule && backupSchedule.every_hours;
    const auto = !backupSchedule ? '' : every ? ` · automatic every ${every === 24 ? 'day' : every === 168 ? 'week' : every + ' hours'}` : ' · automatic backups off';
    setOverview('backups', (newestBackup ? `Last ${shortTime(newestBackup.created)}` : 'No backup yet') + auto, !newestBackup || !every);
}

async function saveBackupSchedule(change) {
    const data = await api('/api/backups/schedule', {method: 'POST', body: change});
    if (!data) return loadBackups();
    $('backup-every').value = String(data.schedule.every_hours);
    $('backup-keep').value = data.schedule.keep;
    $('backup-keep').disabled = !data.schedule.every_hours;
    backupSchedule = data.schedule;
    overviewBackups();
    notify(data.schedule.every_hours ? 'Automatic backups saved' : 'Automatic backups switched off', 'success');
}

function renderBackups(backups) {
    newestBackup = backups[0] || null;     // the list is newest first
    overviewBackups();
    $('backup-list').innerHTML = backups.map(backup => `
        <div class="backup-row" data-backup="${escapeHtml(backup.id)}" data-created="${escapeHtml(backup.created.slice(0, 16))}">
            <div>
                <div class="idea-name">${escapeHtml(backup.created.slice(0, 16))}${backup.automatic || backup.daily ? ' <span class="backup-auto">automatic</span>' : backup.uploaded ? ' <span class="backup-auto">uploaded</span>' : ''}</div>
                ${backup.note ? `<div class="idea-meta">${escapeHtml(backup.note)}</div>` : ''}
                <div class="idea-meta">${plural(backup.cards, 'card')} in the collection · ${backup.scanned} scanned · ${plural(backup.decks, 'deck')}</div>
            </div>
            <button type="button" class="btn btn-small" data-backup-action="restore" data-guarded>Restore</button>
            <a class="mini-btn" href="/api/backups/${encodeURIComponent(backup.id)}/download" download title="Download this backup as a zip file, to keep a copy elsewhere"><svg class="icon"><use href="#i-download"/></svg></a>
            <button type="button" class="mini-btn" data-backup-action="delete" title="Delete this backup"><svg class="icon"><use href="#i-trash"/></svg></button>
        </div>`).join('') || '<div class="hint">No backups yet.</div>';
}

async function createBackup() {
    const button = $('backup-create');
    button.disabled = true;
    const data = await api('/api/backups', {method: 'POST', body: {note: $('backup-note').value}});
    button.disabled = false;
    if (!data) return;
    $('backup-note').value = '';
    renderBackups(data.backups);
    notify(`Backup made: ${plural(data.backup.cards, 'card')}, ${data.backup.scanned} scanned, ${plural(data.backup.decks, 'deck')}`, 'success');
}

async function uploadBackup(file) {
    const button = $('backup-upload');
    button.disabled = true;
    button.textContent = 'Uploading...';
    const form = new FormData();
    form.append('file', file);
    const data = await api('/api/backups/upload', {method: 'POST', body: form});
    button.disabled = false;
    button.textContent = 'Upload a backup file';
    if (!data) return;
    renderBackups(data.backups);
    notify(`Backup of ${data.backup.created.slice(0, 16)} added to the list: ${plural(data.backup.cards, 'card')}, ${plural(data.backup.decks, 'deck')}`, 'success');
}

async function backupAction(row, action) {
    const id = row.dataset.backup, created = row.dataset.created;
    if (action === 'restore') {
        const ok = await confirmDialog({title: `Restore the backup of ${created}?`, confirmText: 'Restore', danger: true,
            message: 'The collection, the scanned cards and the decks go back to how they were then - everything '
                + 'changed since is replaced. What you have now is backed up first, so you can go back to it.'});
        if (!ok) return;
        const data = await api(`/api/backups/${id}/restore`, {method: 'POST'});
        if (!data) return loadBackups();
        renderBackups(data.backups);
        notify(`Backup of ${created} restored`, 'success');
    } else {
        const ok = await confirmDialog({title: `Delete the backup of ${created}?`, confirmText: 'Delete', danger: true,
            message: "Your cards are not changed. This can't be undone."});
        if (!ok) return;
        const data = await api(`/api/backups/${id}`, {method: 'DELETE'});
        if (data) renderBackups(data.backups);
    }
}

async function loadDatabaseState() {
    const data = await api('/api/stats');
    if (!data || !data.database) return;
    const state = data.database;
    const parts = [`${(state.total_cards || 0).toLocaleString()} cards in the card database`];
    if (state.updating) parts.push('an update is running');
    else if (state.update) parts.push(state.update);
    if (state.error) parts.push(`last update failed: ${state.error}`);
    $('database-state').textContent = parts.join(' · ');
    cardDataState = state;
    overviewCardData();
    try {
        // What the update downloads depends on the game being scanned
        const games = await (await fetch('/api/games')).json();
        const game = games.games.find(item => item.id === games.active);
        if (game) {
            $('database-source-hint').textContent =
                `Downloads the latest ${game.label} card data${game.id === 'mtg' ? ' and prices' : ''} from ${game.source}. Scanning keeps working meanwhile.`;
        }
    } catch (error) { /* the general text stays */ }
}

let cardDataState = null, cardDataSchedule = null;     // the overview's card data line is made of both

function overviewCardData() {
    if (!cardDataState) return;
    const parts = [`${(cardDataState.total_cards || 0).toLocaleString()} cards`];
    if (cardDataState.updating) parts.push('updating now');
    else if (cardDataState.update) parts.push('newer data available');
    if (cardDataSchedule) parts.push(cardDataSchedule.every_hours ? `next update ${whenText(cardDataSchedule.next)}` : 'automatic update off');
    setOverview('carddata', parts.join(' · '), Boolean(cardDataState.error || (cardDataState.update && !cardDataState.updating)));
}

function formatBytes(bytes) {
    if (bytes >= 1073741824) return `${(bytes / 1073741824).toFixed(2)} GB`;
    return `${(bytes / 1048576).toFixed(bytes >= 10485760 ? 0 : 1)} MB`;
}

function showCaptureUsage(usage) {
    // The total, then each kind of file the cameras' captures leave on the server
    const kinds = [
        ['received', 'Pictures received from the cameras', 'scanned_cards, removed after a few days'],
        ['thumbnails', 'Thumbnails of the cards in the lists', 'data/captures'],
        ['large', 'Large copies kept with each capture', 'data/captures_full'],
        ['frames', 'Camera frames kept for training', 'data/frames'],
    ];
    setOverview('storage', `${formatBytes(usage.total_bytes)} of capture files`);
    $('capture-usage').innerHTML = `<div class="storage-total">${formatBytes(usage.total_bytes)}</div>`
        + kinds.map(([key, label, where]) => `<div class="storage-row" title="${escapeHtml(where)}"><span>${escapeHtml(label)}</span>`
            + `<span>${usage[key].count.toLocaleString()} files, ${formatBytes(usage[key].bytes)}</span></div>`).join('');
}

// The picture index (server/card_data.py: index_status): how much of the card database it covers, and a running build's progress. The button
// downloads the pictures of what is missing; while it runs the page asks the server every two seconds how far it is (so it also shows after a reload).
let indexWatch = null;

function showIndex(state) {
    const status = $('index-status');
    const covers = `${state.indexed.toLocaleString()} of ${state.printings.toLocaleString()} printings`;
    $('update-index').disabled = !!state.running;
    $('stop-index').hidden = !state.running;
    $('stop-index').disabled = !!state.stopping;
    setOverview('index', state.running ? `Building: ${state.done.toLocaleString()} of ${state.total ? state.total.toLocaleString() : '?'} new pictures`
        : !state.indexed ? 'Not built yet' : state.missing ? `Lacks ${plural(state.missing, 'printing')} of the card data` : `Complete: ${state.indexed.toLocaleString()} printings`,
        !state.running && (!state.indexed || Boolean(state.missing)));
    if (state.running) {
        status.textContent = `Building: ${state.done.toLocaleString()} of ${state.total ? state.total.toLocaleString() : '?'} new pictures done (${covers} covered before).`
            + (state.stopping ? ' Stopping...' : '');
        if (!indexWatch) indexWatch = setInterval(loadIndex, 2000);
        return;
    }
    const wasWatching = Boolean(indexWatch);
    if (indexWatch) { clearInterval(indexWatch); indexWatch = null; }
    $('update-index').textContent = state.indexed ? 'Update the picture index' : 'Build the picture index';
    status.textContent = state.indexed ? `Covers ${covers}` + (state.missing ? ` - ${state.missing.toLocaleString()} to add` : ' - up to date')
                                       : `Not built yet (0 of ${state.printings.toLocaleString()} printings)`;
    if (state.error) status.textContent += ` - the last build did not finish: ${state.error}`;     // stays after a reload: it is not only a notification
    if (state.built) status.title = `Built ${state.built}`;
    if (wasWatching) {
        loadUpdateSchedule();       // an automatic build that just ended changes the "last / next" line
        // It has just ended: say how it went, once
        if (state.error) notify(`Picture index: ${state.error}`, 'error');
        else if (state.result) {
            const r = state.result;
            notify(r.stopped ? `Stopped: ${plural(r.new, 'picture')} added so far - press the button again to go on`
                             : `Picture index updated: ${plural(r.new, 'new picture')}`, r.stopped ? 'info' : 'success');
        }
    }
}

async function loadIndex() {
    const state = await api('/api/image_index');
    if (state) showIndex(state);
}

// The automatic updates (server/card_data.py: update_schedule_state): the card data's download and the picture index's retry - each a
// select and a line saying how the last automatic run ended and when the next is due. The times come with the server's offset, and are
// shown in the browser's own time zone.

function whenText(iso) {
    const moment = new Date(iso);
    if (moment <= new Date()) return 'within 10 minutes';
    return moment.toLocaleString(undefined, {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
}

function lastRunText(last) {
    // ok: true / false, or null while it runs (or when a server stopped in the middle of it)
    if (!last || !last.at) return 'Not run yet.';
    const at = new Date(last.at).toLocaleString(undefined, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
    if (last.ok === true) return `Last ${at}: ${last.message}.`;
    if (last.ok === false) return `Last ${at} did not finish: ${last.message}.`;
    return `Last began ${at} (still running, or the program stopped during it).`;
}

// Prices: whose prices the pages show and the collection is counted in (core/prices.py). Changing it prices every entry again
function showPriceSource(state) {
    const select = $('price-source');
    // A source without prices yet cannot be chosen: Scryfall's until the card data is downloaded again (data from before they
    // were kept), a shop's until its prices are downloaded (the button below)
    const until = choice => choice.kind === 'shops' ? ' - after the first update of the shops\' prices' : ' - after the next card data update';
    if (document.activeElement !== select) {
        select.innerHTML = state.choices.map(choice =>
            `<option value="${escapeHtml(choice.id)}"${choice.priced ? '' : ' disabled'}>${escapeHtml(choice.label)}`
            + `${choice.priced ? '' : until(choice)}</option>`).join('');
        select.value = state.source;
    }
    window.PRICE_SYMBOL = state.symbol;
    $('price-source-hint').textContent = `${state.from}. The collection, the scanned cards and the decks are counted in ${state.currency}; `
        + 'a change prices every card again, and a card the new source has no price for is left without one '
        + '(cards imported without their printing keep theirs, unless the currency changes).';
    setOverview('prices', state.choices.find(choice => choice.id === state.source).label);
    showShopPrices(state.shops || {});
}

// The shops' prices (server/card_data.py: shop_prices_status): MTGJSON's date of those in use, and an update's progress. While
// one runs the page asks every two seconds how far it is (also after a reload), as for the picture index
let shopWatch = null;

function showShopPrices(shops) {
    const status = $('shop-prices-status');
    $('update-shop-prices').disabled = !!shops.running;
    if (shops.running) {
        status.textContent = `Updating: ${shops.message || 'starting'}...`;
        if (!shopWatch) shopWatch = setInterval(loadPriceSource, 2000);
        return;
    }
    const wasWatching = Boolean(shopWatch);
    if (shopWatch) { clearInterval(shopWatch); shopWatch = null; }
    status.textContent = shops.date
        ? `Prices of ${shops.date} for ${shops.printings.toLocaleString()} printings` + (shops.downloaded_at
            ? `, downloaded ${new Date(shops.downloaded_at).toLocaleString(undefined, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'})}` : '')
        : 'Not downloaded yet: Card Kingdom and Mana Pool can be chosen after the first update.';
    if (shops.error) status.textContent += ` - the last update did not finish: ${shops.error}`;
    if (wasWatching) {
        loadUpdateSchedule();       // an automatic update that just ended changes the "last / next" line
        if (shops.error) notify(`Shops' prices: ${shops.error}`, 'error');
        else if (shops.result) notify(`Shops' prices: ${shops.result}`, 'success');
    }
}

async function updateShopPrices() {
    // Guarded on the server: with a settings password set, common.js asks for it and sends the request again
    $('update-shop-prices').disabled = true;
    const state = await api('/api/prices/update', {method: 'POST'});
    if (!state) return loadPriceSource();
    showPriceSource(state);
}

async function loadPriceSource() {
    const state = await api('/api/prices/source');
    if (state) showPriceSource(state);
}

async function savePriceSource(source) {
    // Guarded on the server: with a settings password set, common.js asks for it and sends the request again
    $('price-source').disabled = true;
    const state = await api('/api/prices/source', {method: 'POST', body: {source}});
    $('price-source').disabled = false;
    if (!state) return loadPriceSource();       // refused (or the password dialog cancelled): back to what is saved
    showPriceSource(state);
    const label = state.choices.find(choice => choice.id === state.source).label;
    notify(`Prices from ${label} - ${plural(state.repriced, 'entry', 'entries')} priced again`
           + (state.unpriced ? `, ${plural(state.unpriced, 'entry', 'entries')} without a price there` : ''), 'success');
}

function showUpdateSchedule(state) {
    const card = state.card_data, index = state.image_index, shops = state.prices;
    cardDataSchedule = card;
    overviewCardData();
    $('database-every').value = String(card.every_hours);
    $('database-auto').textContent = card.every_hours
        ? `${lastRunText(card.last)} Next: ${whenText(card.next)}.`
        : 'Off: only with the button above (a notice says when newer data is there).';
    $('index-every').value = String(index.every_hours);
    $('index-auto').textContent = index.every_hours
        ? `${lastRunText(index.last)} Next look: ${whenText(index.next)}, if any are missing. Never the first build.`
        : 'Off: what a build left out (a rate limit, a stop) waits for the button or the next card data update.';
    $('prices-every').value = String(shops.every_hours);
    $('prices-auto').textContent = shops.every_hours
        ? `${lastRunText(shops.last)} Next look: ${whenText(shops.next)} (MTGJSON's new prices are out in the morning, UTC).`
        : 'Off: the shops\' prices change only with the button in Prices above.';
}

async function loadUpdateSchedule() {
    const state = await api('/api/updates/schedule');
    if (state) showUpdateSchedule(state);
}

async function saveUpdateSchedule(change) {
    // Guarded on the server: with a settings password set, common.js asks for it and sends the request again
    const state = await api('/api/updates/schedule', {method: 'POST', body: change});
    if (!state) return loadUpdateSchedule();       // refused (or the password dialog cancelled): the selects go back to what is saved
    showUpdateSchedule(state);
    const [what, hours] = Object.entries(change)[0];
    const label = {card_data: 'Automatic card data update', image_index: 'Picture index retry', prices: 'Automatic price update'}[what];
    notify(hours ? `${label} saved` : `${label} switched off`, 'success');
}

let compressWatch = null;   // the timer that asks how far the compression is, while it runs

function showCompress(info) {
    const state = info.compress || {};
    $('compress-copies').disabled = !!state.running;
    if (state.running) {
        $('compress-hint').textContent = `Compressing... ${state.done} of ${state.total || '?'} copies looked at.`;
        if (!compressWatch) compressWatch = setInterval(loadCaptureCopy, 2000);
        return;
    }
    if (compressWatch) {
        // It has just finished: say how it went, once
        clearInterval(compressWatch);
        compressWatch = null;
        if (state.error) notify(`Compressing failed: ${state.error}`, 'error');
        else notify(`${state.files} large cop${state.files === 1 ? 'y' : 'ies'} made smaller, ${state.megabytes} MB freed`, 'success');
        $('compress-hint').textContent = state.error ? 'Compressing failed (see the log).'
            : `Done: ${state.files} made smaller, ${state.megabytes} MB freed. Backups keep the old files until they are deleted.`;
    }
}

function showCaptureCopy(info) {
    if (document.activeElement !== $('cleanup-days')) $('cleanup-days').value = info.cleanup_days;
    showCompress(info);
    if (info.usage) showCaptureUsage(info.usage); else $('capture-usage').textContent = 'Could not be measured (see the log).';
    $('capture-copy-size').value = info.size;
    $('keep-frames').checked = !!info.keep_frames;
    $('keep-frames-hint').textContent = `${plural(info.frames, 'frame')} kept, ${info.frames_megabytes} MB - training data from cameras with Debug trace on. `
        + (info.keep_frames ? 'They stay when their cards are cleared or added (up to 3 GB).' : 'Off: a frame goes when its card is cleared or added.');
    $('capture-copy-hint').textContent = (info.size === 'off' ? 'Only a thumbnail is kept. '
        : 'Kept beside the thumbnail, to read a card again later or train the detector. ')
        + `${info.count} kept, ${info.megabytes} MB. Applies to new captures.`;
}

async function loadCaptureCopy() {
    const data = await api('/api/capture_copy');
    if (data) showCaptureCopy(data);
}

async function saveCaptureCopy(body, message) {
    const data = await api('/api/capture_copy', {method: 'POST', body});
    if (!data) return loadCaptureCopy();
    showCaptureCopy(data);
    notify(message, 'success');
}

function bindData() {
    $('backup-create').addEventListener('click', createBackup);
    $('backup-upload').addEventListener('click', () => $('backup-upload-input').click());
    $('backup-upload-input').addEventListener('change', event => {
        const file = event.target.files[0];
        event.target.value = '';
        if (file) uploadBackup(file);
    });
    $('backup-every').addEventListener('change', event => saveBackupSchedule({every_hours: parseInt(event.target.value)}));
    $('backup-keep').addEventListener('change', event => saveBackupSchedule({keep: parseInt(event.target.value)}));
    $('database-every').addEventListener('change', event => saveUpdateSchedule({card_data: parseInt(event.target.value)}));
    $('price-source').addEventListener('change', event => savePriceSource(event.target.value));
    // The list is not rebuilt while it has the focus (showPriceSource): a shop that became choosable meanwhile shows on leaving it
    $('price-source').addEventListener('blur', loadPriceSource);
    $('index-every').addEventListener('change', event => saveUpdateSchedule({image_index: parseInt(event.target.value)}));
    $('prices-every').addEventListener('change', event => saveUpdateSchedule({prices: parseInt(event.target.value)}));
    $('update-shop-prices').addEventListener('click', updateShopPrices);
    $('backup-list').addEventListener('click', event => {
        const button = event.target.closest('[data-backup-action]');
        if (button) backupAction(button.closest('[data-backup]'), button.dataset.backupAction);
    });

    $('update-database').addEventListener('click', () => {
        $('update-database').disabled = true;
        $('update-database').textContent = 'Updating...';
        $('database-progress').textContent = 'Starting the card data update...';
        socket.emit('update_database');
    });
    $('cleanup-days').addEventListener('change', event => {
        const days = parseInt(event.target.value);
        if (!(days >= 1 && days <= 3650)) { notify('Days: a whole number from 1 to 3650', 'error'); return loadCaptureCopy(); }
        saveCaptureCopy({cleanup_days: days}, `Received pictures are kept ${days} days`);
    });
    $('cleanup-now').addEventListener('click', async () => {
        $('cleanup-now').disabled = true;
        const data = await api('/api/storage/cleanup', {method: 'POST', body: {}});
        $('cleanup-now').disabled = false;
        if (!data) return;
        $('cleanup-result').textContent = data.deleted_files
            ? `Deleted ${data.deleted_files} picture${data.deleted_files === 1 ? '' : 's'}, freed ${data.freed_megabytes} MB.`
            : `Nothing older than ${data.cleanup_days} days.`;
        showCaptureCopy(data);
    });
    $('update-index').addEventListener('click', async () => {
        const state = await api('/api/image_index/update', {method: 'POST', body: {}});
        if (state) showIndex(state);
    });
    $('stop-index').addEventListener('click', async () => {
        const state = await api('/api/image_index/stop', {method: 'POST', body: {}});
        if (state) showIndex(state);
    });
    $('compress-copies').addEventListener('click', async () => {
        const data = await api('/api/storage/compress', {method: 'POST', body: {}});
        if (data) showCaptureCopy(data);
    });
    $('capture-copy-size').addEventListener('change', event =>
        saveCaptureCopy({size: event.target.value}, event.target.value === 'off' ? 'No large copies will be kept' : `Large copies will be ${event.target.value}`));
    $('keep-frames').addEventListener('change', event =>
        saveCaptureCopy({keep_frames: event.target.checked},
            event.target.checked ? 'Camera frames stay after their cards are cleared or added' : 'Camera frames go with their cards'));
}

// ============================================================================
// Server: restart, network, debug mode
// ============================================================================

const DEBUG_MODE_DESC = $('debug-mode-desc').textContent;

function applyDebugMode(enabled, running, debuggerRunning) {
    $('toggle-debug-mode').checked = Boolean(enabled);
    let text = Boolean(enabled) === Boolean(running) ? DEBUG_MODE_DESC
        : `Now ${running ? 'on' : 'off'}: restart to turn it ${enabled ? 'on' : 'off'}. ` + DEBUG_MODE_DESC;
    // The debugger is half of the mode, and only where nobody else can reach the server
    if (running) {
        text += debuggerRunning ? ' The debugger is on (only this computer can reach the server).'
            : ' The debugger stays off: other devices can reach this server.';
    }
    $('debug-mode-desc').textContent = text;
}

// -- The settings password (server/lock.py) ---------------------------------

async function unlockAndReconnect() {
    // A guarded event was refused. The unlocked cookie is only read when a connection is made:
    // after the password the page connects again, and the action is asked for once more
    if (!(await unlockSettings())) return;
    connect();
    loadLock();
    notify('Unlocked - do that again', 'info');
}

async function loadLock() {
    const status = await (await fetch('/api/settings_lock', {cache: 'no-store'})).json();
    $('lock-status').textContent = !status.has_password
        ? 'No password is set: everything is open.'
        : status.fixed
            ? 'The password is set by SCANNER_SETTINGS_PASSWORD in the server\'s environment (it cannot be changed here). '
              + (status.unlocked ? 'This browser is unlocked.' : 'This browser is locked.')
            : status.unlocked ? 'A password is set. This browser is unlocked (for 12 hours).' : 'A password is set. This browser is locked.';
    $('lock-set-row').hidden = status.fixed;
    $('lock-set').textContent = status.has_password ? 'Change password' : 'Set password';
    $('lock-unlock').hidden = !(status.has_password && !status.unlocked);
    $('lock-lock').hidden = !(status.has_password && status.unlocked);
    $('lock-remove').hidden = !(status.has_password && !status.fixed);
    // The padlocks (settings.css: [data-guarded] - everything the server asks the password for, the backups' Restore too) only
    // mean something while a password is set: without one nothing asks
    document.body.classList.toggle('has-settings-password', Boolean(status.has_password));
    hasSettingsPassword = Boolean(status.has_password);
    overviewServer();
}

let hasSettingsPassword = null;     // from loadLock: the Server line is drawn again when the network switch changes, without asking for it again

// The overview's Server line: the password, and who can reach the server NOW - common.js's setNetworkAccess keeps what is saved and what runs on the
// switch's description (data-saved / data-running): the switch takes effect after a restart, and the line says so until then
function overviewServer() {
    if (hasSettingsPassword === null) return;
    const desc = $('network-access-desc');
    const saved = desc.dataset.saved === 'true', running = desc.dataset.running === 'true';
    let network = running ? 'reachable from other devices' : 'this computer only';
    if (saved !== running) network += saved ? ' (other devices too after a restart)' : ' (this computer only after a restart)';
    setOverview('server', `${hasSettingsPassword ? 'Settings password set' : 'No settings password'} · ${network}`, saved !== running);
}

function bindLock() {
    $('lock-set').addEventListener('click', async () => {
        const data = await api('/api/settings_password', {method: 'POST', body: {password: $('lock-new').value}});
        if (!data) return;
        $('lock-new').value = '';
        notify('Settings password saved', 'success');
        connect();          // the cookie it came with is read when a connection is made
        loadLock();
    });
    $('lock-unlock').addEventListener('click', async () => { if (await unlockSettings()) { connect(); loadLock(); } });
    $('lock-lock').addEventListener('click', async () => {
        await fetch('/api/settings_lock', {method: 'DELETE'});
        connect();
        loadLock();
    });
    $('lock-remove').addEventListener('click', async () => {
        if (!(await confirmDialog({title: 'Remove the settings password?', message: 'Everything is open again to anyone who can reach this server.',
                                    confirmText: 'Remove', danger: true}))) return;
        if (await api('/api/settings_password', {method: 'POST', body: {password: ''}})) {
            notify('Settings password removed', 'success');
            connect();
            loadLock();
        }
    });
    // A backup's download is a link: a refused request would be saved as a file, so ask first
    $('backup-list').addEventListener('click', async event => {
        const link = event.target.closest('a[download]');
        if (!link || link.dataset.unlocked) return;
        event.preventDefault();
        if (await ensureSettingsUnlocked()) {
            link.dataset.unlocked = '1';
            link.click();
            delete link.dataset.unlocked;
        }
    });
}

function bindServer() {
    bindLock();
    loadLock();
    $('restart-program').addEventListener('click', restartProgram);
    if ($('quit-program')) $('quit-program').addEventListener('click', quitProgram);
    // Saved (or refused, and the switch goes back) - then the overview's line says what is now saved and what runs
    $('toggle-network-access').addEventListener('change', async event => { await setNetworkAccess(event.target.checked); overviewServer(); });
    $('toggle-debug-mode').addEventListener('change', event => socket.emit('toggle_debug_mode', {enabled: event.target.checked}));
}

// ============================================================================
// Start
// ============================================================================

document.addEventListener('DOMContentLoaded', async () => {
    document.querySelectorAll('#settings-nav button').forEach(button =>
        button.addEventListener('click', () => showCategory(button.dataset.category)));
    $('overview-list').addEventListener('click', event => {
        const row = event.target.closest('[data-goto]');
        if (row) showCategory(row.dataset.goto);
    });
    renderOverview();
    window.addEventListener('hashchange', () => showCategory(categoryFromAddress(), false));
    showCategory(categoryFromAddress(), false);

    bindCameras();
    bindSounds();
    bindReading();
    bindData();
    bindServer();

    connect();              // the server's own settings need a connection even before a camera is chosen
    await loadStations();   // chooses a camera and reconnects for it
    if (!stations.length) loadCameraSettings();
    loadAI();
    loadPromptSummary();
    loadBackups();
    loadDatabaseState();
    loadCaptureCopy();
    loadIndex();
    loadUpdateSchedule();
    loadPriceSource();
});
