# Known issues and TODO

Test setup: Mock SEM and microtome with `tests/resources/mock.ini` / `mock.cfg` (array imaging: `array.ini`).
Run the app without hardware with a system config whose devices are `Mock SEM` / the mock microtome, or with
`simulation_mode = True` in the session config.

## Known issues

### Config backward compatibility before merging dev to master
`src/config_template.py` notes that several `system.cfg` entries need backward compatibility before the dev branch
is merged to master.

### TCP state: `paused` always true
`Acquisition.send_data_tcp` sends `self.pause_state != 0`, but `pause_state` is `None`, 1 or 2 (never 0), so it is
`true` in every request. Documented as unreliable in docs/external_tools.md. See TODO.

### ADD ARRAY GRID divides by the calibration scale
`GridManager.add_new_grid_from_overview_roi` divides `roi_center` and `size` by `cs.scale_x/y` before
`convert_d_to_s`, which multiplies by the scale again. Image µm are already SEM (d) coordinates, so a region lands
as drawn only for a scale of exactly 1. Other scales offset and resize it. A negative scale (the default SEM-stage
calibration `[-1.0, 1.0, 0, 0]`) mirrors the x offset and gives a negative width. See TODO.

### Image position metadata
Images store their top-left corner in SEM (d) coordinates (`SEM.get_grab_metadata`, centre -> position in
`image_io.create_tiff_metadata`), but the stub overview stores `centre_sx_sy` (stage coordinates, centre) as its
position (`acq_func.acquire_stub_ov`). TESCAN (`SEM_SharkSEM`) does not write the metadata. See TODO.

### TCP errors other than a refused connection end the acquisition
`run_acquisition` catches only `ConnectionRefusedError` around the TCP exchange. A reset connection, invalid JSON or
a command without `args`/`kwargs` raises out of `run_acquisition`; `run()` logs it and resets the GUI, so the
acquisition stops rather than pausing safely. SBEMimage also waits for a reply without a timeout.

### Unused TCP server
`src/RemoteControlTCP.py` (SBEMimage as TCP server) is not referenced anywhere; only `TCPRemote` (client) is used.

### TODOs in the code
~70 `TODO`/`FIXME` comments in `src/` (mostly `Acquisition.py`, `Autofocus.py`, `autofocus_mapfost.py` and the
dialogs). Move any worth tracking here; remove those no longer relevant.

## In progress

Nothing.

## TODO

ESSENTIAL

- [ ] **ADD ARRAY GRID: drop the scale division** - in `GridManager.add_new_grid_from_overview_roi`, convert
      `roi_center + ref_center` with `cs.convert_d_to_s` as given, and pass `size` unchanged (both are SEM µm, as
      `grid.sw_sh` and `tile_width_d()` expect). No change for a scale of exactly 1. Other scales move and resize
      regions, so grids from napari-isbem change position on calibrated systems. Check on a calibrated system (an
      overview with a recognisable feature, a region of interest drawn on it, the tiles acquired) and with the default
      SEM-stage calibration (`scale_x = -1`). Then update the 'Grids from a region of interest' section in
      docs/external_tools.md.
- [ ] **TCP errors pause instead of stopping** - in `Acquisition.run_acquisition`, catch `OSError` (covers refused,
      reset and timed-out connections) and `ValueError` (invalid JSON) around `send_data_tcp`/`process_tcp_commands`,
      log them and `pause_acquisition(1)`, as for a refused connection. In `process_tcp_commands`, read
      `cmd.get('args', [])` / `cmd.get('kwargs', {})` and log an unknown or failing command instead of raising.
      Optionally a `tcp_timeout` setting in `[acq]` passed to `socket.settimeout` in `TCPRemote.send`.

MINOR

- [ ] **TCP `paused` flag** - the state is only sent at the start of a slice, inside the acquisition loop, where
      `acq_paused` is always false. Options: send `self.acq_paused` (correct, always false), or drop the field and
      document that a paused acquisition sends no requests. napari-isbem shows the value
      (`acquisition_model.py`, `request['paused']`), so dropping it needs a change there too.
- [ ] **Stub overview position** - in `acq_func.acquire_stub_ov`, write `'center': stub_ovm.centre_dx_dy` instead
      of `'position': stub_ovm.centre_sx_sy`, as the other images do (top-left in SEM coordinates after the
      centre -> position conversion). Older stub overview images keep the stage centre: check
      `ImportImageDlg` / `ImportedImage`, which read `position` back.
- [ ] **TESCAN image metadata** - in `SEM_SharkSEM.acquire_frame`, save through `image_io.imwrite(...,
      metadata=self.get_grab_metadata(stage))` instead of `PIL.Image.save` (the TODO already in the code), so
      TESCAN images carry pixel size and position.
- [ ] **napari-isbem reads 1024 bytes** - its `TCPServer.run` calls `conn.recv(1024)` once; the state grows with the
      number of overviews (`ov_dirs` paths): over 1024 bytes at 11 overviews with a 22-character `base_dir`, 9 with
      37 characters, 6 with 78 characters. Read until the JSON parses or the client stops sending (napari-isbem
      repo).
- [ ] **RemoteControlTCP** - remove `src/RemoteControlTCP.py`, or wire it up if SBEMimage should also accept
      commands outside the per-slice exchange.

REFACTORING

- [ ] **autofocus_mapfost uses the Zeiss API directly** - calls `sem.sem_api` instead of the SEM class's methods.
- [ ] **constants.py enums** - replace hard-coded values with `auto()`.

## Done

- **docs/development.md up to date** - module names (CamelCase files, `sem/`, `microtome/`, `src/dialog/`), folder
  structure and architecture overview match the current code.
