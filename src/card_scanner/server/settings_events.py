# ============================================================================
# FILE: server/settings_events.py
# Settings of a camera and of scanning: toggles, the game, focus, rotation, fixed area, sound.
# ============================================================================
import threading

from flask import jsonify, request
from flask_socketio import emit

from card_scanner.core import frames
from card_scanner.core import inventory as inventory_module
from card_scanner.core.card_ocr import CardOcr
from card_scanner.core.cleanup import cleanup_old_images, get_images_stats
from card_scanner.config import Config
from card_scanner import games
# The card dropper's rules are written once, beside the code that drives the pin: the server checks with them before saving,
# the station before using (a plain module: it opens nothing and imports no GPIO library when imported)
from card_scanner.station.dropper import checked as dropper_checked

from card_scanner.server.state import app, app_settings, identification, inventory, maintenance_barrier, printing_check, services, socketio, stations
from card_scanner.server.logs import logger
from card_scanner.server.lock import LOCKED_MESSAGE, guarded, guarded_event, unlocked
from card_scanner.server.desks import desk, desks, emit_desk, in_desk, log_to_client, scanner
from card_scanner.server.captures import CARD_BACK_SETTING, scan_location, set_pending_capture, stops_at_card_back
from card_scanner.server.card_data import extend_index_wanted, index_progress, start_card_data_update


@app.route('/api/ai_provider')
def get_ai_provider():
    """Get current AI provider and model for card identification"""

    if identification and identification.card_identifier:
        return jsonify({
            'provider': identification.card_identifier.provider,
            'model': identification.card_identifier.model,
            'enabled': True
        })

    return jsonify({
        'provider': Config.VISION_AI_PROVIDER,
        'model': None,
        'enabled': Config.VISION_AI_ENABLED
    })


def game_info(game):
    """What the page needs to know about a game (lists keep their order; jsonify sorts dicts)"""
    return {
        'id': game.id,
        'label': game.label,
        'source': game.source,
        'has_treatments': game.has_treatments,
        'set_example': game.set_example,
        'number_example': game.number_example,
        'finishes': [[key, label] for key, label in game.finishes.items()],
        'exports': [[key, label] for key, (label, _prefix, _writer) in game.export_formats().items()],
        'imports': list(game.import_formats),
        # Deck builder formats: [[id, label, has a commander]] (none: the game has no deck builder)
        'deck_formats': [[key, rules['label'], bool(rules.get('commander'))]
                         for key, rules in game.deck_formats.items()],
        # Whether a deck can be written for the game's digital client (the deck page's Arena button)
        'arena': bool(game.arena_decklist),
    }


@app.route('/api/games')
def get_games():
    """Supported card games and the one being scanned"""
    return jsonify({'active': games.active_id(), 'games': [game_info(game) for game in games.all_games()]})


@socketio.on('set_game')
def handle_set_game(data):
    """Switch the game being scanned (stops auto scanning; the current card is dropped)"""
    game_id = data.get('game')
    try:
        games.set_active(game_id)
    except ValueError as e:
        emit('error', {'message': str(e)})
        return
    # The game is everyone's: every camera stops scanning and every page drops its card
    for target in [services.default_desk, *list(desks.values())]:
        with in_desk(target):
            target.current_card_info = target.current_review_id = target.review_sid = None
            set_pending_capture(None)
            if scanner and scanner.auto_capture_enabled:
                scanner.auto_capture_enabled = False
                scanner.card_under_review = False
                emit_desk('auto_capture_toggled', {'enabled': False})
    game = games.active()
    logger.info(f"Game switched to {game.label}")
    card_count = game.card_count()
    socketio.emit('game_changed', {**game_info(game), 'card_count': card_count})
    if not card_count:
        # First time: fetch its card data right away
        log_to_client(f"Downloading the {game.label} card data from {game.source}...")
        start_card_data_update(game, retry=True)  # no data yet: a failure is tried again


@socketio.on('toggle_auto_capture')
def handle_toggle_auto_capture(data):
    """Toggle auto-capture on/off"""

    if not scanner:
        logger.error("Toggle auto-capture requested but scanner not initialized")
        emit('error', {'message': 'Scanner not initialized'})
        return

    enabled = data.get('enabled', True)
    scanner.auto_capture_enabled = enabled

    # Load a local AI model now, so the first auto-captured card doesn't wait for it
    if enabled and identification.card_identifier:
        identification.card_identifier.warm_up()

    # When disabling, also clear the card_under_review flag to reset state
    if not enabled:
        scanner.card_under_review = False
        scanner.stable_frames = 0  # Reset stability counter
        logger.info("Auto-capture disabled - resetting scanner state")

    emit('auto_capture_toggled', {'enabled': enabled})
    logger.info(f"Auto-capture toggled: {enabled}")
    log_to_client(f"Auto-capture {('enabled' if enabled else 'disabled')}", level="info")


def set_auto_add(enabled):
    """
    Auto-add ("fast scan") mode: auto-captured cards are identified in the background and
    confirmed ones are added to the inventory without review; otherwise each card waits
    for Add / Skip.
    """
    scanner.fast_scan_mode = enabled
    scanner.required_stable_frames = Config.FAST_SCAN_STABILITY_FRAMES if enabled else Config.AUTO_CAPTURE_STABILITY_FRAMES
    scanner.auto_capture_delay = Config.AUTO_CAPTURE_DELAY


def saved_debug_mode():
    """Flask's debug mode for the next start: the switch in Settings, else flask.debug in config.yaml"""
    return bool(app_settings.get('debug_mode', Config.DEBUG)) if app_settings else bool(Config.DEBUG)


def reading_status():
    """
    How cards are read, for the Settings page: the mode (reading.mode: 'cascade' or 'evidence'), whether a card only the picture decided may be added, and
    what the evidence mode needs - the image index (its number of printings; None without one) and OCR switched on. The page warns when it is missing.
    """
    try:
        index = printing_check.index() if printing_check else None
    except Exception:
        index = None
    try:
        missing = printing_check.missing_printings() if printing_check and index is not None else None
    except Exception:
        missing = None
    missing = missing if isinstance(missing, int) else None        # a plain number for the page, or nothing
    return {'mode': identification.reading_mode if identification else 'cascade',
            'accept_image_alone': bool(identification.accept_image_alone) if identification else False,
            # extend the index by itself after a card data download (only when it exists), and a build's progress for the banner
            'extend_index': extend_index_wanted(),
            'index_build': index_progress(),
            'index_printings': len(index) if index is not None else None,
            # printings of the card data the index lacks: while not 0, the picture alone adds nothing (None: not known)
            'index_missing': missing,
            'ocr_enabled': bool(identification.ocr_enabled) if identification else False}


@app.route('/api/scan_settings')
def get_scan_settings():
    """Scanning preferences the page needs on load"""
    return jsonify({
        'auto_add': bool(scanner.fast_scan_mode) if scanner else True,
        'stop_at_card_back': stops_at_card_back(),     # this camera's: a face-down card stops its auto-capture (captures.stop_at_card_back)
        'ocr_first': bool(identification.ocr_enabled) if identification else True,
        'ocr_installed': CardOcr.installed(),
        'ai_enabled': bool(identification.ai_enabled) if identification else True,
        'ai_available': bool(identification and identification.card_identifier),
        'reading': reading_status(),
        'debug_trace': bool(scanner.debug_trace_enabled) if scanner else False,
        'dropper': dropper_payload(),
        'debug_mode': saved_debug_mode(),
        'debug_mode_running': bool(services.debug_mode_running),
        'debugger_running': bool(services.debugger_running),
        'autofocus': scanner.focus_locked_value is None if scanner else True,
        'fixed_area_enabled': bool(scanner.fixed_area_enabled) if scanner else False,
        'fixed_area': scanner.fixed_area if scanner else None,
        'camera_rotation': scanner.rotation if scanner else 0,
        'refocus_every': scanner.refocus_every if scanner else Config.AUTO_CAPTURE_REFOCUS_EVERY,
        'refocus_on_drop': scanner.refocus_on_drop if scanner else Config.AUTO_CAPTURE_REFOCUS_ON_DROP,
        'scan_location': scan_location(),
        'sound': sound_settings(),
        'locations': inventory.locations(games.active_id()) if inventory else [],
    })


def cleanup_days():
    """How many days the pictures received from the cameras (scanned_cards/) are kept: the
    person's choice (Settings > Storage), else cleanup.days of config.yaml"""
    days = app_settings.get('cleanup_days', None) if app_settings else None
    return days if isinstance(days, int) and not isinstance(days, bool) and 1 <= days <= 3650 else Config.CLEANUP_DAYS


def run_image_cleanup():
    """Delete the received pictures older than cleanup_days() (at start-up, once a day, and the
    button's). Not while a full backup is collecting the pictures. Returns (files, megabytes freed)"""
    with maintenance_barrier:
        return cleanup_old_images(days_to_keep=cleanup_days())


# The compression of the large copies, started by the Storage card's button and run in its own
# thread (thousands of pictures take minutes); the page asks /api/capture_copy while it runs
compress_state = {'running': False, 'done': 0, 'total': 0, 'files': 0, 'megabytes': 0.0, 'error': None}
compress_lock = threading.Lock()


def run_compress(height):
    def progress(done, total):
        compress_state.update(done=done, total=total)
    try:
        files, freed = inventory_module.compress_full_captures(height, lock=maintenance_barrier, progress=progress)
        compress_state.update(files=files, megabytes=round(freed / 1048576, 1))
        logger.info(f"Large copies compressed to {height} px: {files} made smaller, {freed / 1048576:.1f} MB freed")
    except Exception as error:
        compress_state['error'] = str(error)
        logger.error(f"Compressing the large copies failed: {error}")
    finally:
        compress_state['running'] = False


@app.route('/api/storage/cleanup', methods=['POST'])
@guarded
def storage_cleanup():
    """Delete the received pictures older than the chosen days right now (the Storage card's button)"""
    try:
        files, megabytes = run_image_cleanup()
    except Exception as error:
        logger.error(f"Cleanup failed: {error}")
        return jsonify({'success': False, 'error': str(error), 'message': str(error)}), 500
    logger.info(f"Cleanup on request: {files} old image(s) deleted, {megabytes:.2f} MB freed (keeping {cleanup_days()} days)")
    return jsonify({'success': True, **capture_copy_info(), 'deleted_files': files, 'freed_megabytes': round(megabytes, 1)})


@app.route('/api/storage/compress', methods=['POST'])
@guarded
def storage_compress():
    """
    Make the large copies already kept as small as the "Capture size" choice says (a thread;
    the page watches /api/capture_copy). Refused while one runs, and when the size is Off.
    """
    height = inventory_module.FULL_CAPTURE_HEIGHT
    if height <= 0:
        message = "Capture size is Off: choose a size first"
        return jsonify({'success': False, 'error': message, 'message': message}), 400
    with compress_lock:
        if compress_state['running']:
            return jsonify({'success': False, 'error': 'Already running', 'message': 'Already running'}), 409
        compress_state.update(running=True, done=0, total=0, files=0, megabytes=0.0, error=None)
    threading.Thread(target=run_compress, args=(height,), daemon=True).start()
    return jsonify({'success': True, **capture_copy_info()})


def capture_copy_info():
    """The large copy kept with each capture: what is chosen, the choices (px), and what is kept so far"""
    chosen = app_settings.get('capture_copy_size', inventory_module.FULL_CAPTURE_DEFAULT) if app_settings else \
        inventory_module.FULL_CAPTURE_DEFAULT
    count, size = inventory_module.full_capture_usage()
    kept, frames_size = frames.usage()
    # Every kind of capture file the server keeps, for the Storage card's total: the pictures
    # received from the cameras (scanned_cards/, cleaned after cleanup.days), the small and the
    # large copy kept behind inventory entries, and the camera frames
    try:
        received = get_images_stats()
        thumbs, thumbs_size = inventory_module.thumbnail_usage()
        usage = {'received': {'count': received['count'], 'bytes': round(received['total_size_mb'] * 1048576)},
                 'thumbnails': {'count': thumbs, 'bytes': thumbs_size},
                 'large': {'count': count, 'bytes': size},
                 'frames': {'count': kept, 'bytes': frames_size}}
        usage['total_bytes'] = sum(part['bytes'] for part in usage.values())
    except Exception as error:
        # A look at the folders must never fail what is asked of this route (a POST has
        # already saved its choice by now): the page then shows no total
        logger.warning(f"Could not measure the capture files: {error}")
        usage = None
    return {'usage': usage, 'cleanup_days': cleanup_days(), 'cleanup_every_day': Config.CLEANUP_ENABLED,
            'compress': dict(compress_state), 'size': chosen if chosen in inventory_module.FULL_CAPTURE_SIZES else inventory_module.FULL_CAPTURE_DEFAULT,
            'sizes': inventory_module.FULL_CAPTURE_SIZES, 'count': count, 'megabytes': round(size / 1048576, 1),
            # The camera frames kept for training (Debug trace): whether they stay when their
            # scanned cards are cleared or added to the collection, and what is kept
            'keep_frames': bool(app_settings.get('keep_frames', False)) if app_settings else False,
            'frames': kept, 'frames_megabytes': round(frames_size / 1048576, 1)}


@app.route('/api/capture_copy', methods=['GET', 'POST'])
def set_capture_copy():
    """
    The large copy kept with each capture, for every camera (a choice of the server, in
    data/settings.json; the collection page's Settings): GET answers what is chosen, the choices and
    what is kept so far; POST (JSON: 'size' = off / small / medium / large) chooses for new captures.
    """
    if request.method == 'GET':
        return jsonify({'success': True, **capture_copy_info()})
    data = request.get_json(silent=True) or {}
    if 'keep_frames' in data:
        # Keep the camera frames of scanned cards that are cleared or added to the collection
        app_settings.set('keep_frames', bool(data['keep_frames']))
        logger.info(f"Camera frames of cleared or added scanned cards: {'kept' if data['keep_frames'] else 'removed with them'}")
    if 'cleanup_days' in data:
        # How long pictures are kept decides what the (locked) cleanup deletes: locked as well,
        # whereas the rest of this route (capture size, keeping frames) stays open
        if not unlocked():
            return jsonify({'success': False, 'error': LOCKED_MESSAGE, 'locked': True}), 401
        days = data['cleanup_days']
        if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 3650:
            message = 'cleanup_days is a whole number of days, 1 to 3650'
            return jsonify({'success': False, 'error': message, 'message': message}), 400
        app_settings.set('cleanup_days', days)
        logger.info(f"Received pictures are kept {days} days")
    if 'size' in data or not ({'keep_frames', 'cleanup_days'} & set(data)):
        size = data.get('size')
        if size not in inventory_module.FULL_CAPTURE_SIZES:
            message = f"size is one of {', '.join(inventory_module.FULL_CAPTURE_SIZES)}"
            return jsonify({'success': False, 'error': message, 'message': message}), 400
        inventory_module.set_full_capture_size(size)
        app_settings.set('capture_copy_size', size)
        logger.info(f"Large copy of each capture: {size} ({inventory_module.FULL_CAPTURE_SIZES[size]} px)")
    return jsonify({'success': True, **capture_copy_info()})


def sound_settings():
    """
    Sound effects of the scanner page: {'enabled', 'volume' (0-100), 'capture', 'added'} - the
    last two switch off the capture beep and the ding of an added card, each on its own
    """
    settings = app_settings
    return {'enabled': bool(settings.get('sound_enabled', True)) if settings else True,
            'volume': int(settings.get('sound_volume', 30)) if settings else 30,
            'capture': bool(settings.get('sound_capture', True)) if settings else True,
            'added': bool(settings.get('sound_added', True)) if settings else True}


@app.route('/api/sound', methods=['POST'])
def set_sound():
    """Remember the sound switches and / or the volume (JSON: 'enabled', 'capture', 'added', 'volume' 0-100)"""
    data = request.get_json(silent=True) or {}
    try:
        for key in ('enabled', 'capture', 'added'):
            if key in data:
                app_settings.set(f'sound_{key}', bool(data[key]))
        if 'volume' in data:
            app_settings.set('sound_volume', max(0, min(100, int(data['volume']))))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'The volume must be a number from 0 to 100'}), 400
    return jsonify({'success': True, 'sound': sound_settings()})


@app.route('/api/scan_location', methods=['POST'])
def set_scan_location():
    """Set the inventory location scanned cards are added to ('' = none)"""
    location = str((request.get_json(silent=True) or {}).get('location') or '').strip()[:60]
    if desk().id:
        stations.update(desk().id, location=location)  # a station's cards go to its own location
    else:
        app_settings.set('scan_location', location)
    log_to_client(f"Scanned cards go to: {location}" if location else "Scanned cards get no location")
    return jsonify({'success': True, 'scan_location': location})


@socketio.on('toggle_fast_scan')
def handle_toggle_fast_scan(data):
    """Toggle adding auto-scanned cards to the inventory automatically (remembered)"""

    if not scanner:
        logger.error("Toggle auto-add requested but scanner not initialized")
        emit('error', {'message': 'Scanner not initialized'})
        return

    enabled = bool(data.get('enabled', False))
    set_auto_add(enabled)
    scanner.settings.set('auto_add', enabled)
    emit('fast_scan_toggled', {'enabled': enabled})
    logger.info(f"Auto-add toggled: {enabled} (required frames: {scanner.required_stable_frames})")
    log_to_client(f"Add cards automatically: {'on' if enabled else 'off - review each card'}", level="info")


@socketio.on('toggle_stop_at_card_back')
def handle_toggle_stop_at_card_back(data):
    """Whether a card back captured by this camera stops its auto-capture (docs/plans/CARD_BACK_STOP_PLAN.md; remembered per camera, like auto_add)"""
    if not scanner:
        emit('error', {'message': 'Scanner not initialized'})
        return
    enabled = bool(data.get('enabled', True))
    scanner.settings.set(CARD_BACK_SETTING, enabled)
    emit_desk('stop_at_card_back_toggled', {'enabled': enabled})      # every page of this camera (the Settings page shows its switch)
    log_to_client(f"A card back {'stops' if enabled else 'no longer stops'} auto-capture", level="info")


@socketio.on('toggle_ocr')
def handle_toggle_ocr(data):
    """Read cards with light-ocr first, the vision AI only when needed (remembered)"""
    if not scanner:
        emit('error', {'message': 'Scanner not initialized'})
        return
    identification.set_ocr_enabled(bool(data.get('enabled', False)))
    emit('ocr_toggled', {'enabled': identification.ocr_enabled, 'installed': CardOcr.installed()})


@socketio.on('toggle_ai')
def handle_toggle_ai(data):
    """Ask the vision AI at all, or send what OCR and the picture cannot decide to the review queue (remembered; open like the OCR switch: it adds nothing, it only stops asking)"""
    identification.set_ai_enabled(bool((data or {}).get('enabled', False)))
    emit('ai_toggled', {'enabled': identification.ai_enabled, 'available': bool(identification.card_identifier)})
    log_to_client(f"Vision AI: {'on' if identification.ai_enabled else 'off - what OCR and the picture cannot decide goes to the review queue'}", level="info")


@socketio.on('set_reading_mode')
@guarded_event
def handle_set_reading_mode(data=None):
    """
    How cards are read (remembered; the next card takes it, no restart): data['mode'] 'cascade' (OCR, then the vision AI) or 'evidence' (the picture and the
    strip before the AI - docs/PROGRAM_DOCUMENTATION.md, "Reading mode: evidence"), data['accept_image_alone'] (a card only the picture decided may be added)
    and data['extend_index'] (extend the picture index after a card data download). Guarded like the other settings that decide what is added. Any may be sent alone.
    """
    data = data or {}
    mode = data.get('mode')
    alone = data.get('accept_image_alone')
    extend = data.get('extend_index')
    if (mode is not None and mode not in ('cascade', 'evidence')) or any(value is not None and not isinstance(value, bool) for value in (alone, extend)):
        emit('error', {'message': 'Not a reading mode'})
        return
    if mode is not None:
        app_settings.set('reading_mode', mode)
    if alone is not None:
        app_settings.set('reading_accept_image_alone', alone)
    if extend is not None:
        app_settings.set('reading_extend_index', extend)
    status = reading_status()
    emit('reading_mode_changed', status)
    log_to_client(f"Card reading: {status['mode']}" + (' (the picture alone may add a card)' if status['mode'] == 'evidence' and status['accept_image_alone'] else ''),
                  level="info")
    # (with OCR off there is no strip: only the picture alone can decide, so that is the gap only while it is not allowed)
    if status['mode'] == 'evidence' and (status['index_printings'] is None or (not status['ocr_enabled'] and not status['accept_image_alone'])):
        log_to_client("Evidence reading needs the image index, and OCR or the picture alone - until they are there every card is read as before", level="warning")


def dropper_payload():
    """
    The card dropper as the Settings page shows it: this camera's settings (the defaults - off - when never set, or when
    data/stations.json holds values that do not pass), what the station reports of it (pulses sent, the last error; None from
    a station whose program has no dropper yet) and whether the station is connected at all.
    """
    if not scanner:
        return {'settings': dropper_checked(None), 'state': None, 'connected': False}
    try:
        settings = dropper_checked(scanner.dropper)
    except ValueError:
        settings = dropper_checked(None)
    # The pair key stays on the server and the station: the page only learns that there is one
    settings = dict(settings, paired=settings.pop('pair_key') is not None)
    return {'settings': settings, 'state': scanner.dropper_state if scanner.connected else None, 'connected': bool(scanner.connected)}


def saved_dropper():
    """This camera's dropper settings as saved (the defaults when none or wrong ones)"""
    try:
        return dropper_checked(scanner.dropper)
    except ValueError:
        return dropper_checked(None)


def keep_dropper(values):
    """Checked, saved, sent to the station (RemoteScanner: DECIDED 'dropper'), now and whenever it connects"""
    values = dropper_checked(values)
    scanner.dropper = values
    scanner.settings.set('dropper', values)
    return values


@socketio.on('set_dropper')
def handle_set_dropper(data):
    """
    This camera's card dropper (station/dropper.py): switched on or off, its pin, its pulse. Checked whole before anything is
    saved; saved with the camera's settings and sent to the station (RemoteScanner: DECIDED 'dropper'), now and whenever it
    connects. Not guarded, like the camera's other settings - it moves cards, it changes nothing that is kept.
    """
    if not scanner:
        emit('error', {'message': 'Scanner not initialized'})
        return
    asked = dict((data or {}).get('dropper') or {})
    # The paired feeder and its key come from pairing only (pair_feeder), never from the form: kept as they are
    asked.pop('paired', None)
    saved = saved_dropper()
    asked['feeder'], asked['pair_key'] = saved['feeder'], saved['pair_key']
    if asked.get('enabled') and asked.get('transport') == 'wifi' and saved['pair_key'] is None:
        # A feeder chosen before one is paired: kept, but off - the page then shows where to find and pair it
        asked['enabled'] = False
        emit('error', {'message': 'Pair a feeder first: the card dropper stays off until then'})
    try:
        values = keep_dropper(asked)
    except ValueError as e:
        emit('error', {'message': str(e)})
        emit('dropper_updated', dropper_payload())    # the page goes back to what is saved
        return
    if values['enabled']:              # (on: a pin, or a paired feeder - checked)
        how = f"the feeder at {values['feeder']['ip']}" if values['transport'] == 'wifi' else f"GPIO{values['pin']}, {values['pulse_ms']} ms"
        logger.info(f"Card dropper: on, {how}")
    else:
        logger.info("Card dropper: off")
    emit('dropper_updated', dropper_payload())


@socketio.on('find_feeders')
def handle_find_feeders(_data=None):
    """The Settings page's "Find feeders": the station looks on its network (station/dropper.py: find_feeders)"""
    if not scanner:
        emit('feeders_found', {'ok': False, 'message': 'Scanner not initialized'})
        return
    try:
        feeders = scanner.find_feeders()
    except ValueError as e:
        emit('feeders_found', {'ok': False, 'message': str(e)})
        return
    emit('feeders_found', {'ok': True, 'feeders': feeders})


@socketio.on('pair_feeder')
def handle_pair_feeder(data):
    """
    Pair the feeder at `ip` with this camera's station: the feeder's own key (the owner's, typed on the page) is passed to it
    through the station once and kept nowhere; the pair key it then takes is kept with the camera's settings, never shown.
    The dropper's transport becomes the feeder; switched on or off as it was.
    """
    if not scanner:
        emit('feeder_paired', {'ok': False, 'message': 'Scanner not initialized'})
        return
    data = data or {}
    try:
        paired = scanner.pair_feeder(str(data.get('ip') or ''), str(data.get('config_key') or ''))
        values = keep_dropper(dict(saved_dropper(), transport='wifi', feeder=paired['feeder'], pair_key=paired['pair_key']))
    except (ValueError, TypeError, KeyError) as e:
        emit('feeder_paired', {'ok': False, 'message': str(e)})
        return
    logger.info(f"Card dropper: paired with the feeder at {values['feeder']['ip']}")
    emit('feeder_paired', {'ok': True, 'feeder': values['feeder']})
    emit('dropper_updated', dropper_payload())


@socketio.on('forget_feeder')
def handle_forget_feeder(_data=None):
    """Forget the paired feeder (this side only: the feeder forgets the station on its own page). Off, if it drove it"""
    if not scanner:
        emit('error', {'message': 'Scanner not initialized'})
        return
    saved = saved_dropper()
    keep_dropper(dict(saved, enabled=saved['enabled'] and saved['transport'] != 'wifi', feeder=None, pair_key=None))
    logger.info("Card dropper: the paired feeder forgotten")
    emit('dropper_updated', dropper_payload())


@socketio.on('test_dropper')
def handle_test_dropper(_data=None):
    """The Settings page's "Drop one card": one pulse now, to try the mechanism (the station answers how it went)"""
    if not scanner:
        emit('dropper_tested', {'ok': False, 'message': 'Scanner not initialized'})
        return
    try:
        pulses = scanner.drop_card()
    except ValueError as e:
        emit('dropper_tested', {'ok': False, 'message': str(e)})
        return
    emit('dropper_tested', {'ok': True, 'pulses': pulses})
    emit('dropper_updated', dropper_payload())


@socketio.on('toggle_debug_trace')
def handle_toggle_debug_trace(data):
    """Toggle debug trace logging on/off (remembered)"""

    if not scanner:
        logger.error("Toggle debug trace requested but scanner not initialized")
        emit('error', {'message': 'Scanner not initialized'})
        return

    enabled = bool(data.get('enabled', False))
    scanner.debug_trace_enabled = enabled
    scanner.settings.set('debug_trace', enabled)
    emit('debug_trace_toggled', {'enabled': enabled})
    logger.info(f"Debug trace toggled: {enabled}")


@socketio.on('toggle_debug_mode')
@guarded_event
def handle_toggle_debug_mode(data):
    """Flask's debug mode on/off (remembered; the server takes it when it starts)"""
    if not scanner:
        emit('error', {'message': 'Scanner not initialized'})
        return
    enabled = bool(data.get('enabled', False))
    app_settings.set('debug_mode', enabled)
    emit('debug_mode_toggled', {'enabled': enabled, 'running': bool(services.debug_mode_running),
                                'debugger': bool(services.debugger_running)})
    logger.info(f"Debug mode toggled: {enabled} (running: {services.debug_mode_running})")
    if enabled != bool(services.debug_mode_running):
        log_to_client(f"Debug mode: {'on' if enabled else 'off'} after the next restart", level="info")


@socketio.on('reset_focus')
def handle_reset_focus():
    """Reset camera focus"""

    if not scanner:
        logger.error("Reset focus requested but scanner not initialized")
        emit('error', {'message': 'Scanner not initialized'})
        return

    logger.info("Focus reset requested by user")
    if scanner.reset_focus():
        # The sweep runs in the background; the result arrives as a log message
        emit('focus_reset', {'message': 'Focusing...'})
    elif scanner.focus_sweep_running:
        emit('focus_reset', {'message': 'Already focusing...'})
    else:
        emit('error', {'message': no_focus_message()})


def no_focus_message():
    return 'No camera connected' if scanner.camera_error else 'This camera has no manual focus control'


@socketio.on('set_autofocus')
def handle_set_autofocus(data):
    """Continuous autofocus on, or off = find the sharpest focus and lock it"""
    if not scanner:
        emit('error', {'message': 'Scanner not initialized'})
        return
    if not scanner.set_continuous_autofocus(bool(data.get('enabled'))):
        emit('error', {'message': no_focus_message()})


@socketio.on('set_camera_rotation')
def handle_set_camera_rotation(data):
    """Rotate the camera image (0/90/180/270 degrees clockwise) - e.g. a camera mounted sideways"""
    if not scanner:
        emit('error', {'message': 'Scanner not initialized'})
        return
    try:
        fixed_area_off = scanner.set_rotation(data.get('rotation', 0))
    except (TypeError, ValueError) as e:
        emit('error', {'message': str(e)})
        return
    emit_desk('camera_rotation_updated', {'rotation': scanner.rotation, 'fixed_area_off': fixed_area_off})
    if fixed_area_off:
        emit_desk('fixed_area_updated', {'enabled': False, 'area': scanner.fixed_area})


@socketio.on('set_refocus_every')
def handle_set_refocus_every(data):
    """Check the focus every this many captures while scanning (0 = never); remembered"""
    if not scanner:
        emit('error', {'message': 'Scanner not initialized'})
        return
    try:
        scanner.set_refocus_every(data.get('captures', 0))
    except (TypeError, ValueError) as e:
        emit('error', {'message': str(e)})
        emit('refocus_every_updated', {'captures': scanner.refocus_every})  # put the field back
        return
    emit_desk('refocus_every_updated', {'captures': scanner.refocus_every})


@socketio.on('set_refocus_on_drop')
def handle_set_refocus_on_drop(data):
    """Refocus by itself when the last 3 captured cards are this fraction as sharp as before (0 = never); remembered"""
    if not scanner:
        emit('error', {'message': 'Scanner not initialized'})
        return
    try:
        scanner.set_refocus_on_drop(data.get('ratio', 0))
    except (TypeError, ValueError) as e:
        emit('error', {'message': str(e)})
        emit('refocus_on_drop_updated', {'ratio': scanner.refocus_on_drop})  # put the field back
        return
    emit_desk('refocus_on_drop_updated', {'ratio': scanner.refocus_on_drop})


@socketio.on('set_fixed_area')
def handle_set_fixed_area(data):
    """
    Fixed capture area (sleeved cards): {'enabled': bool} turns it on/off, {'area': [x1, y1, x2, y2]}
    (fractions of the frame, drawn on the video) sets it, {'use_detected': true} takes the
    detected card plus a margin. Sent back to every page as fixed_area_updated.
    """
    if not scanner:
        emit('error', {'message': 'Scanner not initialized'})
        return
    area = data.get('area')
    if data.get('use_detected'):
        try:
            area = scanner.detected_area()
        except ValueError:
            area = None
        if area is None:
            emit('error', {'message': 'No card detected - put a card in the box, or draw the area'})
            return
    if area is not None:
        try:
            x1, y1, x2, y2 = (float(v) for v in area)
        except (TypeError, ValueError):
            emit('error', {'message': 'Invalid area'})
            return
        x1, y1, x2, y2 = max(0.0, x1), max(0.0, y1), min(1.0, x2), min(1.0, y2)
        if x2 - x1 < 0.05 or y2 - y1 < 0.05:
            emit('error', {'message': 'The area is too small - draw it around the card'})
            return
        area = [x1, y1, x2, y2]
    enabled = data.get('enabled')
    if enabled and area is None and scanner.fixed_area is None:
        emit('error', {'message': 'Draw the capture area first'})
        return
    try:
        state = scanner.set_fixed_area(enabled=enabled, area=area)
    except ValueError as e:  # the camera station did not answer
        emit('error', {'message': str(e)})
        return
    logger.info(f"Fixed area: {'on' if state['enabled'] else 'off'} {state['area']}")
    emit_desk('fixed_area_updated', state)


@socketio.on('set_ai_provider')
def handle_set_ai_provider(data):
    """Set AI provider and/or model for card identification"""

    if not scanner:
        logger.error("Set AI provider requested but scanner not initialized")
        emit('error', {'message': 'Scanner not initialized'})
        return

    provider = data.get('provider', 'gemini')
    model = data.get('model', None)  # Optional model parameter

    if model:
        logger.info(f"AI provider/model change requested: {provider} / {model}")
    else:
        logger.info(f"AI provider change requested: {provider}")

    result = identification.set_ai_provider(provider, model)

    if result['success']:
        emit('ai_provider_set', {
            'provider': provider,
            'model': result.get('model'),
            'message': result['message']
        })
        logger.info(f"AI provider set to: {provider} ({result.get('model')})")
    else:
        emit('error', {'message': result['message']})
        logger.error(f"Failed to set AI provider: {result['message']}")
