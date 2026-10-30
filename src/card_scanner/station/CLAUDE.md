# CLAUDE.md - the camera station

Loaded when working under this folder. Moved here from the root `CLAUDE.md` (2026-10-30) word for word; the
project-wide rules stay there. Module names are written bare, as in the root file.

## Where things live

| Area | Code |
|---|---|
| Connection, status, preview, commands, uploads | `station_client.py`: `Station` (`hello`, `report_loop`, `on_command`, `on_set`, `auto_captured`, `manual_capture`, `upload_loop`), `ServerSettings` |
| The station's own setup page (server, name, camera, a Pi camera's crop) | `station_setup.py`: `resolve` (command line > environment > `data/station.json` > default), `apply_camera`, `checked`, `list_cameras`, `take_picture`, `SetupPage`; `station_setup.html`; `station_client.py`: `main` (setup mode, `request_restart`); `scanner.py`: `with_camera_released` |
| The setup page's password (scrypt hash, signed session cookie, lock after wrong attempts) | `station_login.py`: `Login` (`set_password`, `check`, `new_session`, `valid_session`), `data/station_login.json`; `station_setup.py`: `logged_in`, `log_in` |
| How fast a station runs on a machine (container against plain Python, one Pi against another) | `scripts/benchmark_station.py` (the station stopped first) |
| Capture loop, stillness, auto-capture, new-card detection, fixed area | `scanner.py`: `_capture_frames` (camera missing / lost: `_open_camera`, `_read_failed`, `_wait_for_camera`), `_is_card_settled`, `_new_card_arrived`, `_mark_captured`, `_fixed_area_step`, `set_fixed_area` |
| The card dropper: the station pulses a GPIO pin to release the next card (the mechanism: its own repository, `SilentKernel81/card-dropper`, since 2026-10-30) | `station/dropper.py`: `checked` (the settings' rules, used by the server too), `Dropper` (`configure`, `pulse` - with the caller's `gate`, entered after the line is opened, the pin set inside it - `state`), `GpiodPin` (libgpiod 2, imported only when a pulse is due); `station_client.py`: `release_next_card` / `_release_loop` (one running, one kept, a third refused; each tied to its `scan_session` - bumped by scanning on / off and by the dropper switched off - a stale one refused before its pulse), `_release`, `_still_wanted` (the gate: under `release_lock`, atomic with the pin going active), `_auto_captured` (takes the scanning session first; makes the capture_id itself and records the debt - `owe_drop` - BEFORE `queue_upload(capture_id=)`), `after_upload` (auto-add on: the next card once the server ANSWERED the upload and not `card_back` - `send_until_settled`; `release_session` rides on the upload item, never in its note), `on_set` (the whole switch - old state read, new session, pending cleared, then the switch - under `release_lock`, and `apply` never writes `auto_capture_enabled`), `after_set(started)` (the first card when scanning starts, for the session that start began - only if the session has no capture and none is coming: `last_capture_session`), `_capture_session` (a capture's session, under the lock), `on_review_done` (`drop_owed` is (capture_id, session), paid only by the server's `review_done` for it - never by `card_under_review` going False, which errors do too), `drop_card`; `server/desks.py`: `review_done(image_path)`, `remember_capture_id` / `forget_capture_id`, `Desk.capture_ids` (each shown capture's id under its own picture, set in `stations_api.station_capture`), settled on Add of the shown card (`card['capture']` or `pending_capture`) / the person's Skip (not `dismiss_card` with `keep_capture`: "not found" dismissing itself) / queued for review - never by "the latest capture"; `remote_scanner.py`: `CAMERA_SETTINGS` / `DECIDED` `dropper`, `REPORTED` `dropper_state`, `drop_card`, `review_done` (remembered in `review_settled`, repeated in `hello`), `stop_unsent` (every stop, by its number, repeated in each `hello` until a station report says off AND that it applied that stop or newer - `auto_capture_revision`, `_take_state`; a start cancels it and is never replayed); `station_client.py` `dropper_synced` / `release_deferred` (no release while disconnected - kept and decided after the next `hello`, which applies a replayed stop through `on_set`), `connection` (a `hello` puts the station in step only for its own, still current connection), `settings_lock` (the server's settings applied one at a time - `on_set`, `hello`'s answer; a stale `hello` refused before it changes anything), `_newer_only` / `settings_revisions` (each value numbered by the server - `remote_scanner` `_revision`, `SERVER_START`, in every `set` and `hello`; only a newer one applied, setting by setting) and `HELLO_RETRY_DELAYS` (a failed `hello` asked again while the connection lasts); `server/settings_events.py`: `dropper_payload`, `set_dropper`, `test_dropper`; `settings.js`: `applyDropper`, `saveDropper`; `deploy/docker-compose.client-gpio.yml`; `tests/test_station_dropper.py`; the mechanism (3D-printed parts, its Pico firmware) and its contract - one pulse of 10-2000 ms = one card; the Pico needs >= 8 ms: `SilentKernel81/card-dropper` |
| Focus sweep / lock / drift tracking | `scanner.py`: `focus_sweep`, `refocus`, `_run_focus_sweep`, `_run_focus_probe`, `_move_focus` (approach from below: the lens has play), `_check_focus_drift`, `set_continuous_autofocus` |
| Outline detection, warp | `object_detector.py`: `find_card_outline` (+ `_track_outline`, `_outline_from_edge_groups`, `_card_inside_box`), `warp_card`, `ObjectDetector.detect` (asks `corner_net.py`'s network first - `detection.neural`, `corner_net.onnx` beside it - and falls back to the outline detector); training and scoring: `scripts/train_corner_net.py`, `scripts/label_frames.py`, `scripts/score_detector.py --neural` |

## Conventions and pitfalls

- **The station's setup page** (`station_setup.py`, port 8080) only holds what a station needs
  before it can reach the server: the server's address, its id / name / token, the camera, a
  Pi camera's crop. Everything about scanning stays on the server (`CAMERA_SETTINGS`). A value
  from the command line or the environment wins over the saved file and is shown as fixed -
  keep that order (`resolve`), or stations set up by `.env` change behaviour. The token is
  never sent to the page. It uses Python's built-in web server: no Flask on a station.
  Every route but the page's HTML and the login needs a session (`logged_in()`): a new route
  goes below that check. The password is only ever stored as its scrypt hash
  (`station_login.py`) - never write it, or the station token, to a log. The cookie key is
  random and the station's own: never derive it from the password.

**Camera and detection** (the station)

- **Auto-capture thresholds** in `scanner.py` come from measured camera noise and a live drop
  test (documented in docs/PROGRAM_DOCUMENTATION.md). Re-measure before changing them.
- **The camera is exclusive**: only one process can open it; stop the station before testing
  with the real camera. Camera *controls* (`v4l2-ctl -c ...`) can be changed while another
  process streams.
- **The camera may be missing**: a station must start and connect without it.
  `scanner.camera_error` says why (also in its status and `/api/detection_status`);
  `scanner.camera` is `None` then and the capture thread retries (`_open_camera`). Don't log
  per failed frame or retry. Nothing about the camera may fail when `config.py` is imported:
  a camera named by its `/dev/v4l/by-id/...` path has no number while unplugged
  (`Config.USB_CAMERA_INDEX` is `None`, `USB_CAMERA_SOURCE` keeps the name) and is looked up
  again at every attempt to open it.
- **Frame sizes**: with a raw-JPEG camera ≥ 1920 px wide, `current_frame`, detections, corners
  and the preview are **half size**; only captures decode full size (`get_detected_card`,
  `get_full_frame`). Don't crop captures from `current_frame` directly.
- **CPU**: `cv2.setNumThreads(2)` in scanner.py - OpenCV's default (all cores) doubled CPU use.
- **Focus timing**: a `focus_absolute` change takes ~0.4 s to show up in frames; measure after
  that, or sweeps score the previous lens position.
- **Thread safety**: frames / detection state under `scanner.frame_lock`. Auto-capture
  callbacks, uploads, focus sweeps and the server's commands each run in their own thread.
