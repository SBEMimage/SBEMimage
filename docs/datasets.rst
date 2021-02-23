Datasets
========

For each acquisition a *base directory* must be specified in which the image data and metadata will be written. *SBEMimage* uses the name of the deepest subdirectory of the base directory path as the name of the dataset itself (“stack name”). Example: For the base directory ``D:\EM_data\October\Drosophila_20191023``, the name of the dataset will be ``Drosophila_20191023``.

----------------
Folder structure
----------------

.. image:: /images/dataset_folders.png
   :width: 620
   :align: center
   :alt: Folder structure of a base directory

--------------------
Acquisition metadata
--------------------

During an acquisition, metadata about the raw images and the acquisition settings is written to the base directory's subfolder ``meta``. Here, you'll find the subfolders ``logs`` and ``stats`` that contain various log files and histogram statistics about the acquired images.

Imagelist files
^^^^^^^^^^^^^^^

The most important files in ``logs`` are the *imagelist files* (``imagelist_<timestamp>.txt``). An imagelist file is created for each continuous acquisition run in *SBEMimage*. When you restart an acquisition after it's manually paused or interrupted, a new imagelist file with a new timestamp will be created. The imagelist files contain the relative paths and file names of all acquired raw image tiles, their global positions in X, Y, and Z (in nanometres), and their slice numbers. Each line in an imagelist file has the following format:

``path\file_name.tif;<X in nm>;<Y in nm>;<Z in nm>;<slice counter>``

For example (letters ‘g’, ‘t’ and ‘s’ stand for ‘grid’, ‘tile’ and ‘slice’):

``tiles\g0000\t0065\mystack_g0000_t0065_s00314.tif;-398553;-147855;7850;314``

The metadata contained in these imagelist files is the starting point for stitching, aligning and further processing the images. The imagelist files can be automatically concatenated with the Export dialog in *SBEMimage*, where you can set a slice range and save the full imagelist in *TrakEM2* format.

Metadata files
^^^^^^^^^^^^^^

More comprehensive metadata is provided in the *metadata files* (``metadata_<timestamp>.txt``). Metadata files and imagelist files for the same acquisition runs share exactly the same timestamp.

Each run starts with a session record (‘SESSION’) providing information about the current grid setup and acquisition parameters, for example:

``SESSION: {'timestamp': 1609707781, 'eht': 1.5, 'beam_current': 300, 'wd_stig_xy_default': [0.006247757934033871, -0.014188051223754883, 1.0942480564117432], 'slice_thickness': 25, 'grids': ['0000'], 'grid_origins': [[-238.719, -419.024]], 'rotation_angles': [0.0], 'pixel_sizes': [10.0], 'dwell_times': [0.8], 'contrast': 3.0, 'brightness': 7.9, 'email_addresses: ': ['benjamin.titze@fmi.ch', '']}``

For each tile that is acquired, a ‘TILE’ entry is added to the file, for example:

``TILE: {'tileid': '0000.0066.00000', 'timestamp': 1609707887, 'filename': 'tiles/g0000/t0066/test_stack_zf_g0000_t0066_s00000.tif', 'tile_width': 4096, 'tile_height': 3072, 'wd_stig_xy': [0.006247758, -0.014188000000000006, 1.094248], 'glob_x': -359593, 'glob_y': -147855, 'glob_z': 0, 'slice_counter': 0}``

When a slice is complete, the following entry (‘SLICE COMPLETE’) is added:

``SLICE COMPLETE: {'timestamp': 1609708435, 'completed_slice': 424}``

The data written to the metadata files can also be sent to a server listening to the acquisition. This option can be activated and set up in the acquisition settings dialog.

