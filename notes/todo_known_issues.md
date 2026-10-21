# Known issues and TODO

Test setup: Mock SEM and microtome with `tests/resources/mock.ini` / `mock.cfg` (array imaging: `array.ini`).
Run the app without hardware with a system config whose devices are `Mock SEM` / the mock microtome, or with
`simulation_mode = True` in the session config.

## Known issues

### Config backward compatibility before merging dev to master
`src/config_template.py` notes that several `system.cfg` entries need backward compatibility before the dev branch
is merged to master.

### TODOs in the code
~70 `TODO`/`FIXME` comments in `src/` (mostly `Acquisition.py`, `Autofocus.py`, `autofocus_mapfost.py` and the
dialogs). Move any worth tracking here; remove those no longer relevant.

## In progress

Nothing.

## TODO

ESSENTIAL

MINOR


REFACTORING

- [ ] **autofocus_mapfost uses the Zeiss API directly** - calls `sem.sem_api` instead of the SEM class's methods.
- [ ] **constants.py enums** - replace hard-coded values with `auto()`.

## Done

- **docs/development.md up to date** - module names (CamelCase files, `sem/`, `microtome/`, `src/dialog/`), folder
  structure and architecture overview match the current code.
