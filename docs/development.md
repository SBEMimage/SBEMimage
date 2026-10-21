# For developers

The following notes are for developers who would like
to contribute to the development of *SBEMimage*.

## General

Use Python 3 and PyQt 5 or higher, and see requirements.txt for dependencies.

Folder structure:

-   `array`: Array imaging example data from Thomas Templier
-   `cfg`: All custom user and system configuration files. Also,
    `status.dat` is saved here when *SBEMimage* is closed; it contains
    the file name of the last configuration used. When using the
    Windows uninstaller, this directory will be preserved.
-   `dm`: Scripts for *DigitalMicrograph* (in a proprietary language)
    for both GMS 2 and GMS 3.
-   `docs`: Documentation (generated using
    mkdocs <https://www.mkdocs.org> and hosted as github pages <https://sbemimage.github.io/SBEMimage>)
-   `gui`: All PyQt user interface files (.ui), created with *Qt
    Designer* (bundled with *Anaconda*)
-   `img`: Various images and icons
-   `notes`: Known issues and TODO list for developers
-   `scripts`: Standalone helper scripts, for example `convert_images.py`
-   `src`: All Python source files
    -   `default_cfg`: The default configuration files `default.ini`
        (session configuration template) and `system.cfg` (system
        configuration template), and `device_presets.cfg`
    -   `dialog`: Dialog windows, one class per file, with subfolders
        `viewport` and `array` for the Viewport's and array imaging's
        dialogs
    -   `sem`: SEM control
    -   `microtome`: Microtome control
-   `tests`: tests (starting with `test_`); configuration files for
    the tests (using the mock SEM and microtome) are in `tests/resources`

In the root folder:

-   `.gitattributes` and `.gitignore` for GitHub
-   `LICENSE`: Text of MIT License
-   `README.md`: Readme file (Markdown) for GitHub
-   `requirements.txt`: Required libraries, currently listed without
    version specifications
-   `environment.yml`: Conda environment
-   `tox.ini`: Test configuration (used by the GitHub Actions CI)
-   `mkdocs.yml`: Documentation configuration
-   `installer.cfg` and `installer.nsi`: Configuration files for
    building the installer with pynsist/NSIS installer
-   `SBEMimage.bat`: Windows batch file to run SBEMimage (works for both
    the system Python and the Python interpreter (+ packages) installed
    by the NSIS installer)
-   `SKILLS.md`: Working conventions for coding agents (loaded through
    `CLAUDE.md` and `AGENTS.md`)

## Conventions

-   Use PEP8 (<https://pep8.org>) as a general guideline.
-   Use four spaces as one unit of indentation. Don't mix spaces and
    tabs.
-   Use 'snake_case' for all variable names, functions and filenames:
    `grid_index`, `very_long_variable_name`, `load_parameters()`,
    `my_module.py`.
-   Note that PyQt uses camelCase style: `pushButton`,
    `setWindowIcon()`... You can keep this style when naming PyQt GUI
    elements.
-   Follow established naming patterns and conventions and aim for
    consistency with existing code, for example: When referring to the
    index of a tile, use `tile_index` (and not `tile` or `tile_number`).

## Architecture overview

The application is launched from `sbemimage.py`, which loads the
configuration (the startup dialog lets the user select it) and creates
the Main Controls window (`MainControls.py`) as a `QMainWindow`. The
Viewport window (`Viewport.py`) is created from Main Controls as a
`QWidget`; it has three tabs: the Viewport, the Slice-by-slice Viewer
and the Reslice/Statistics tab. Dialog windows are implemented in
`src/dialog`, one class per file (for example `GridSettingsDlg.py`),
with their layouts in `gui`.

The acquisition loop `run()` in `Acquisition.py` is started from Main
Controls and runs in a thread. Overview and stub overview acquisitions
and other functions started manually by the user are in `acq_func.py`.

The elements to be acquired and/or to be displayed are managed by:

-   `GridManager`: for the tile grids (`Grid`, made up of `Tile`s)
-   `OverviewManager`: for the ROI overviews (`Overview`) and the stub
    overview (`StubOverview`)
-   `ImportedImages` (in `ImportedImage.py`): for imported (single) images
-   `TemplateManager`: for templates (`Template`)

The abbreviations `self.gm`, `self.ovm`, `self.imported` and `self.tm`
for these instances are used throughout *SBEMimage*.

For SEM and microtome control, base classes are provided in
`sem/SEM.py` and `microtome/Microtome.py`. Implementations for
different manufacturers or APIs have the same name followed by `_` and
the brand or API name, for example: `sem/SEM_SmartSEM.py` (ZEISS),
`sem/SEM_SharkSEM.py` (TESCAN), `sem/SEM_Phenom.py` (TFS),
`microtome/Microtome_3View.py` and `microtome/Microtome_katana.py`.
`SEM_Mock.py` and `Microtome_Mock.py` simulate the devices for testing
without hardware. `Stage.py` moves the SEM or the microtome stage,
depending on which is in use.

`Autofocus.py` (with `autofocus_mapfost.py`) provides the autofocus
methods, `ImageInspector.py` image integrity and quality checks
(including debris detection) for overview and tile images, and
`Notifications.py` email notifications (status reports and error
messages) and remote commands.

`CoordinateSystem.py` provides functionality to convert between stage,
SEM and viewport coordinates.

`ArrayData.py` holds array imaging data (sections and ROIs), and
`image_io.py` reads and writes images and their metadata.

`config_template.py` checks configuration files and updates older ones
to match the templates in `src/default_cfg`; its key and section counts
must be updated when entries are added to or removed from the templates.

`utils.py` contains various helper functions, and `constants.py`
constants, enums and the version.

## Git workflow

The 'master' branch contains tested code ready for production use, and is
protected.

The [dev](https://github.com/SBEMimage/SBEMimage/tree/dev) branch is
used for all ongoing development. Several developers who are familiar
with the code base can work directly on that branch. Pull requests to
that branch are welcome, ideally from short-lived feature branches. If
you wish to develop new functionality or suggest larger (structural)
changes, it is recommended to post on [Image.sc forum](https://forum.image.sc) with the tag #sbemimage to
discuss what you have in mind, or post a message on *SBEMimage*'s
[GitHub Issues](https://github.com/SBEMimage/SBEMimage/issues) page.
