.. image:: /images/logo_large.png
   :width: 400
   :align: center

User guide
==========
:Author(s):
    Benjamin Titze

:Version: *2018-04-28* for *SBEMimage* 2.0

This is a brief guide for getting started with *SBEMimage*. A more detailed manual is in preparation. Questions? Contact benjamin.titze@fmi.ch 

Device setup requirements
-------------------------

The following requirements must be met for running version 2.0 of *SBEMimage*. Future releases may support SEMs and microtomes from other manufacturers.

* **ZEISS SEM with SmartSEM software** (version 5.4 or above – older versions may work, but have not been tested.)
* **Gatan 3View system with DigitalMicrograph** (GMS 2 or 3; GMS 2 is fully tested, GMS 3 is experimental)
* **Remote control capability for SmartSEM**: The remote client must be installed and configured, and ``CZEMApi.ocx`` must be registered on the support PC. Ask ZEISS for further information.
* If you can see the images from the desired detector in SmartSEM, you can use *SBEMimage* directly. If you can only see the images in DigitalMicrograph, you may have to use an adapter to feed the detector signal to the SEM. The adapter can be built with the following parts: FCT Electronic FM-11W1P-K120, FCT Electronic FMX-008P102, and standard BNC cable, see image below. Find the amplified output signal of the Gatan BSE detector (or any other detector – does not matter as long as you can get the signal onto a BNC cable), then connect that output signal BNC cable to the BNC end of the adapter shown above. Then find the input boards at the back of the microscope where the signals from the different detectors are fed in. Choose one that you don’t regularly use. We always use the EsB detector input. Connect the other end of the adapter to that circuit board. The image you will now obtain in the SmartSEM software when the EsB detector is selected is the signal from your BSE detector.

.. image:: /images/ZEISS_adapter.jpg
   :width: 300
   :align: center

Installation
------------

* Install Python on the support PC (the PC on which DigitalMicrograph is running). We recommend the Anaconda Python distribution: https://www.anaconda.com/download/#windows. Important: Download Python version 3.6 (not 2.7)!

* Copy all files from the GitHub repository including the folder structure (subdirectories ``src``, ``img``, ``gui``…) into the folder ``C:\pytools\SBEMimage``. You can choose a folder other than ``C:\pytools``, but please ensure the program has full read/write access. Important: In the DM communication script ``dm\SBEMimage_DMcom_GMS2.s``, you have to update the variable ``install_path`` if you use a directory other than ``C:\pytools\SBEMimage``. The path to ``SBEMimage.py`` should be: ``\SBEMimage\src\SBEMimage.py``.

* Go to the ``SBEMimage`` directory, in which the file ``requirements.txt`` is located and type: ``pip install -r requirements.txt``. This will install all required Python packages.

Starting the software
---------------------

* Run the script ``SBEMimage_DMcom_GMS2.s`` (for GMS 2) or ``SBEMimage_DMcom_GMS3.s`` (for GMS 3) in DigitalMicrograph. It can be found in ``C:\pytools\SBEMimage\dm``. Open the correct script file for your GMS version in DigitalMicrograph and click on *Execute*. Further information is provided in the script file.

* Now run the main application by starting the batch file ``SBEMimage.bat`` or typing ``python SBEMimage.py`` in the console (current directory must be ``C:\pytools\SBEMimage\src``). Select ``default.ini`` in the startup dialog. This configuration will start *SBEMimage* in simulation mode. Simulation mode should always work because the APIs for the SEM and 3View are disabled. This mode can be used to set up acquisitions, calculate estimates, or look at existing data. If you can run *SBEMimage* in simulation mode, it means that your Python environment works and that the installation successful.

* If you wish to switch to the normal application mode, do the following: Open ``default.ini``, and under the section ``[sys]`` change ``simulation_mode = True`` to ``simulation_mode = False``. If the communication script is running in DigitalMicrograph and the SmartSEM remote API is active and set up correctly, the software should now be fully operational. If the APIs cannot be initialized, you will receive an error message when starting up the application.

User interface: Main Controls and Viewport
------------------------------------------

The graphical user interface consists of two windows that fit next to each other on a wide screen (1920 × 1080 is recommended). It was designed with remote desktop software such as TeamViewer and VNC in mind: All functions are accessible on a single screen. The window **Main Controls** (see below) displays at a glance all relevant settings, the acquisition status, the current electron dose, and real-time estimates for the duration of the acquisition and the total data size. Here you can set up all acquisition parameters. Click on the buttons with a cogwheel icon to open dialog windows for changing settings (available for the panels “SEM”, “Microtome/Stage”, “Overviews”, “Tile grids” and “Stack acquisition”. Click on the tool option buttons (“…”) to change the settings for the different features (for example, debris detection) that can be activated during stack acquisitions. Two additional tabs contain a focus tool and various functions for testing and debugging. 

.. image:: /images/main_controls.jpg
   :width: 550
   :align: center
   
The other, larger window (positioned on the left by default) is the **Viewport**. The workspace shown in the Viewport’s main tab covers the entire accessible range of the stage motors. When sufficiently zoomed out, the stage boundaries are shown as solid white lines, and the x and y stage axes as dashed white lines. To obtain an overview of the entire surface of the sample holder (‘stub’) mounted on the 3View stage, click on the button “Image stub”. A large low-resolution (372 nm pixel size) mosaic will be acquired and placed in the workspace as a background image (see screenshot below).

.. image:: /images/stub_ov.jpg
   :width: 550
   :align: center

You can then use the stub overview image to locate the region of interest. In the region of interest, you can acquire a smaller overview image at higher resolution (typically 100-200 nm pixel size). Press the CTRL key and click on the blue rectangle “OV 0” and drag it to the position where you wish to acquire the overview image. 
To acquire image tiles at the target resolution for analysis (typically 5-20 nm pixel size), you can set up a tile grid in the region of interest. Grid size, tile size, overlaps/gaps between tiles, and acquisition parameters (frame size, pixel size, and dwell time) are specified for each grid. The default tile grid is “Grid 0”. By pressing the ALT key and clicking on a grid, you can drag it to a new position.
Tiles can be individually selected or deselected for imaging (press SHIFT and click on a tile). For complex acquisition tasks, multiple overviews can be set up to cover the region(s) of interest, and multiple grids can be created with different imaging parameters. You can choose for each overview image and for each grid whether it should be acquired on every slice, or in intervals. This permits, for example, to image an area with alternating pixel sizes, or to acquire an overview stack at low resolution with a high-resolution mosaic on every tenth slice. The screenshot below shows an overview image (“OV 0”) and two tile grids (“GRID 0” and “GRID 1”). The highlighted tiles have been selected for imaging. A low-resolution stub overview mosaic is displayed in the background.

.. image:: /images/viewport.jpg
   :width: 550
   :align: center

The basic elements described above are displayed in different layers inside the viewport. The background layer consists of the stub overview image, which provides the main reference frame for an acquisition. The next layer contains the overview images that cover the regions of interest. They are primarily used for debris detection and to position the tile grids. The tile grids are usually located above the overview images, but they can also be placed on any other part of the workspace within the accessible motor range. Finally, additional imported images are shown in the foreground. You can choose whether to show or hide elements by using the controls at the bottom of the window.
The visual scene can be panned by left-click dragging, and zoomed in and out with the mouse wheel or the zoom slider in the bottom-right corner. The viewport is fully functional even while an acquisition is running.

Select the second and third tab to use the slice-by-slice viewer and to show reslices and statistics (see screenshots below; click to enlarge). In each tab, use the grid/tile selector on the bottom to choose the data source, then click on “(Re)load”. In the slice-by-slice viewer, click on the ruler icon to measure distances. When the button is activated (orange colour), mark the starting point for the measurement by clicking with the right mouse button. Mark the end point with a second right click. The distance is displayed in the bottom right corner. To deactivate the measurement function, click on the ruler icon again (colour changes back to black). The measurement tool works the same way in the viewport.
In the “reslice and stats” tab, you can select a slice by left-clicking on the area where the plots are shown. The selected slice is marked with a vertical line in the plot area and a red line in the reslice. The histogram and the mean/SD values are shown for the selected slice.

.. image:: /images/slice_view_and_stats.jpg
   :width: 550
   :align: center

Mouse and key commands
----------------------

======================================== =============================================
Command                                  Action
======================================== =============================================
:kbd:`left click and drag`               Drag to pan field of view 
:kbd:`double click`                      Zoom in at current position
:kbd:`right click`                       Open context menu (Tile selection, image import…) 
:kbd:`shift + left click`                Select or deselect single tiles
:kbd:`shift + left click drag`           Select or deselect tiles in painting mode
:kbd:`alt + left click drag`             Move grid to new position
:kbd:`ctrl + left click drag`            Move overview image to new position 
:kbd:`ctrl + alt + left click drag`      Move imported image to new position 
:kbd:`mouse wheel ↑/↓`                   Zoom in and out (in vieweport panel); Forward and backward through image series (in slice-by-slice panel)

:kbd:`Measuring tool`                    Activate by clicking on measure button (ruler icon), then right-click on two different points between which you wish to measure the distance. 
======================================== =============================================


