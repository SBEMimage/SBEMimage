For developers
==============

The following notes (to be expanded) are for developers who would like to contribute to the development of *SBEMimage*. Questions? Please contact benjamin.titze ÄT fmi.ch.

-------
General
-------

Use Python 3.6 and PyQt 5, and see requirements.txt for dependencies.

Folder structure:

* ``cfg``: Contains default configuration files ``default.ini`` and ``system.cfg``, and all custom user and system configuration files. Also, ``status.dat`` is saved here when *SBEMimage* is closed; it contains the file name of the last configuration used.
* ``dm``: Scripts for *DigitalMicrograph* (in a proprietary language with C syntax)
* ``docs``: Documentation (reStructuredText; HTML output generated with Sphinx and hosted on https://sbemimage.readthedocs.io)
* ``gui``: All PyQT user interface files (.ui), created with *Qt Designer* (bundled with *Anaconda*)
* ``img``: Various images and icons
* ``magc``: MagC (wafer imaging) example data from Thomas Templier
* ``src``: All Python source files including tests (starting with ``test_``)

In the root folder:

* ``.gitattributes`` and ``.gitignore`` for GitHub
* ``LICENSE``: Text of MIT License
* ``README.md``: Readme file (Markdown) for GitHub
* ``requirements.txt``: Required libraries, currently listed without version specifications
* ``SBEMimage.bat``: Windows batch file to run 'python SBEMimage.py'

-----------
Conventions
-----------

* Use PEP8 (https://pep8.org) as a general guideline.
* Use four spaces as one unit of indentation. Don't mix spaces and tabs.
* Use 'snake_case' for all variable names, functions and filenames: ``grid_index``, ``very_long_variable_name``, ``load_parameters()``, ``my_module.py``.
* Note that PyQt uses camelCase style: ``pushButton``, ``setWindowIcon()``... You can keep this style when naming PyQt GUI elements.
* Follow established naming patterns and conventions and aim for consistency with existing code, for example: When referring to the index of a tile, use  ``tile_index`` (and not ``tile`` or ``tile_number``).

---------------------
Architecture overview
---------------------

The application is launched from ``sbemimage.py``. The Main Controls window is created first as a ``QMainWindow``, and the Viewport window is created from Main Controls as a ``QWidget``. Dialog windows associated with Main Controls are implemented in ``main_controls_dlg_windows.py``, those associated with the Viewport in ``viewport_dlg_windows.py``.

``main_controls.py`` contains the startup routine and the Main Controls GUI. ``viewport.py`` contains all code for the Viewport, the Slice-by-slice Viewer and the Acquisition Monitor.

The acquisition loop ``run()`` in ``acquisition.py`` is started from Main Controls and runs in a thread.

The elements to be acquired and/or to be displayed are managed by:

* ``grid_manager``: for the tile grids
* ``overview_manager``: for the ROI overviews and the stub overview
* ``imported_images``: for imported (single) images

The abbreviations ``self.gm`` and ``self.ovm`` for the instances of ``grid_manager`` and ``overview_mamager`` are used throughout *SBEMimage*.

For SEM and microtome control, base classes are provided in ``sem_control.py`` and ``microtome_control.py``. Implementations for different manufacturers have the same name followed by ``_`` and the brand name of the device(s), for example: ``sem_control_zeiss.py``

``image_inspector.py`` provides image integrity and quality checks (including debris
detection) for overview and tile images.

``coordinate_system.py`` provides functionality to convert between stage, SEM and viewport coordinates.

``utils.py`` contains various constants and helper functions.

------------
Git workflow
------------

The 'master' branch contains tested code ready for production use. It is protected, currently only `btitze <https://github.com/btitze>`_ can push to this branch.

The `dev <https://github.com/SBEMimage/SBEMimage/tree/dev>`_ branch is used for all ongoing development. Several developers who are familiar with the code base can work directly on that branch. Pull requests to that branch are welcome. If you wish to develop new functionality or suggest larger (structural) changes, it is recommended to contact benjamin.titze ÄT fmi.ch first to discuss what you have in mind, or post a message on *SBEMimage*'s `GitHub Issues <https://github.com/SBEMimage/SBEMimage/issues>`_ page.

