# Working conventions for this repo

Follow these when making changes here. They extend the developer notes in
[docs/development.md](docs/development.md) (published at https://sbemimage.github.io/SBEMimage/development/).

## Orientation
- Entry point `src/sbemimage.py`; `MainControls.py` (main window, startup), `Viewport.py` (Viewport, Slice-by-slice
  Viewer, Acquisition Monitor), `Acquisition.py` (acquisition loop `run()`, in a thread).
- Grids, overviews and imported images are managed by `GridManager`, `OverviewManager` and `ImportedImage`; their
  instances are `self.gm`, `self.ovm` and `self.imported` throughout.
- Device control: base classes `src/sem/SEM.py` and `src/microtome/Microtome.py`; each implementation is the base
  name plus `_` and the brand or API (`SEM_SmartSEM.py`, `Microtome_katana.py`). `SEM_Mock` / `Microtome_Mock` stand
  in for hardware.
- Dialogs live in `src/dialog/` (one class per file, `...Dlg.py`), their layouts in `gui/*.ui` (Qt Designer).
  Change a layout in the `.ui` file, not by building widgets in code.
- `CoordinateSystem.py` converts between stage, SEM and viewport coordinates; `ImageInspector.py` does image
  quality checks and debris detection; `utils.py` holds helpers, `constants.py` enums and `VERSION`.
- docs/development.md still names the old module files (`main_controls.py`, `sem_control_zeiss.py`); the CamelCase
  files above are current.

## Configuration
- Session settings are `.ini`, system (hardware) settings `.cfg`; the templates are `src/default_cfg/default.ini`
  and `system.cfg`, with device defaults in `device_presets.cfg`.
- Adding or removing a template key or section: update `CFG_NUMBER_KEYS` / `CFG_NUMBER_SECTIONS` (or the `SYSCFG_`
  pair) in `src/config_template.py`, and make sure older user configs still load (the template check updates them).
- `cfg/` holds users' own configs and is git-ignored except the templates; never commit a user/microscope config.

## Hardware safety
- This software drives real microscopes and microtomes: never run code that talks to a device API (SmartSEM,
  SharkSEM, Phenom, DigitalMicrograph, serial ports) outside the Mock devices, and never write to a real config.
  To run the app without hardware use a system config with `sem = Mock SEM` (as `tests/resources/mock.cfg`), or
  `simulation_mode = True` in the session config.
- Keep device-specific behaviour inside the device class: the rest of the code calls the base-class interface.
- An acquisition runs unattended for days: an error in the loop must set an error state, notify and pause safely,
  never leave the stage or knife mid-move or lose already-acquired data.

## Comments
- Code comments: 1-2 lines max, even for non-obvious WHY reasoning. No multi-line rationale blocks.
- Never narrate what changed, reference the current fix/task, or mention specific callers/sessions in a comment - that
  belongs in the commit message or chat response, not the code.
- Comments explain WHY (a hidden constraint, a subtle invariant), never WHAT (identifiers already say that).
- No performance statistics (timings, sizes, speedups) in comments - those go in the commit message or notes.

## Code style
- PEP 8, four-space indentation, `snake_case` for variables, functions and new module files; PyQt elements keep Qt's
  camelCase (`pushButton_save`). The existing module files are CamelCase after their class - keep those names.
- Follow established names for consistency: `tile_index` (not `tile` or `tile_number`), `grid_index`, `ov_index`.
- No single-letter variable names, comprehension variables included: `tile for tile in tiles`, not `t for t in tiles`.
- Avoid `continue` statements - restructure the loop body (e.g. invert the condition) instead.
- Reuse and extend existing functionality instead of writing a new module that parallels it.
- No atomic one-line wrapper functions; keep code intuitive over clever.
- Lines up to 127 characters (CI's flake8 limit); CI fails on syntax errors and undefined names
  (`flake8 . --select=E9,F63,F7,F82`) - run that before pushing.
- For a restructure, write a detailed plan first and agree it before editing.

## Testing
- Tests in `tests/` (`test_<module>.py`) run against the Mock SEM and microtome with configs in `tests/resources/`
  (`mock.ini`, `mock.cfg`, `array.ini`). Run from the repo root with `src` on the path:
  `PYTHONPATH=src python -m pytest tests/test_utils.py` (CI runs `tox` on Windows, Python 3.10-3.12).
- For a small/localized fix, run only the targeted test file(s); the full suite once before pushing a batch.
- Before adding a test, check for an existing one covering the same path - extend or parametrize it rather than
  adding a near-duplicate. Add tests to the existing file for the module under test.
- Never assert values that depend on real hardware, timing or image content noise (autofocus results, debris
  detection on real images): stub the device or the measurement and assert the code's handling exactly.
- Test on the least data that exercises the change; keep written output in a temporary folder (`tmp_path`).

## Carrying work across sessions
- Record the current task, its plan and how far it got under "In progress" in `notes/todo_known_issues.md` before
  editing code, and keep it updated. Clear it once the task is done.
- On "continue" with no other context, read that section first and resume from it.

## Git
- `master` is protected and production-ready; development happens on `dev`. Small changes go straight to `dev`,
  larger ones on a short-lived feature branch with a pull request to `dev`.
- Small, focused commits with a "why" in the message, not a changelog of "what".
- Never create git worktrees (no `EnterWorktree`, no `isolation: "worktree"` agents, no `git worktree add`).
