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
`true` throughout an acquisition. Documented as unreliable in docs/external_tools.md.

### ADD ARRAY GRID divides by the calibration scale
`GridManager.add_new_grid_from_overview_roi` divides `roi_center` and `size` by `cs.scale_x/y` before
`convert_d_to_s`, which multiplies by the scale again. Image µm are already SEM (d) coordinates, so the region is
offset and resized by the scale unless it is 1 in magnitude (the mock calibration). `size` becomes the grid's `sw_sh`,
which `update_grid_tiles_with_mask` compares with d sizes. Check against real data before changing: napari-isbem
relies on the current behaviour.

### Image position metadata
Images store their top-left corner in SEM (d) coordinates (`SEM.get_grab_metadata`, centre -> position in
`image_io.create_tiff_metadata`), but the stub overview stores `centre_sx_sy` (stage coordinates, centre) as its
position (`acq_func.py`). TESCAN (`SEM_SharkSEM`) does not write the metadata yet.

### Unused TCP server
`src/RemoteControlTCP.py` (SBEMimage as TCP server) is not referenced anywhere; only `TCPRemote` (client) is used.

### TODOs in the code
~70 `TODO`/`FIXME` comments in `src/` (mostly `Acquisition.py`, `Autofocus.py`, `autofocus_mapfost.py` and the
dialogs). Move any worth tracking here; remove those no longer relevant.

## In progress

Nothing.

## TODO

ESSENTIAL

MINOR

- [ ] **TCP `paused` flag** - send `self.acq_paused` (or `pause_state in (1, 2)`) instead (see Known issues).
- [ ] **TCP reads** - SBEMimage waits on the server without a timeout; napari-isbem's server reads only the first
      1024 bytes of the state, which more overviews (longer `ov_dirs`) exceed.

REFACTORING

- [ ] **autofocus_mapfost uses the Zeiss API directly** - calls `sem.sem_api` instead of the SEM class's methods.
- [ ] **constants.py enums** - replace hard-coded values with `auto()`.

## Done

- **docs/development.md up to date** - module names (CamelCase files, `sem/`, `microtome/`, `src/dialog/`), folder
  structure and architecture overview match the current code.
