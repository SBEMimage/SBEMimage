Installation
============

-------------------
Install Python 3.6+
-------------------

Install Python on the computer on which you wish to run SBEMimage. If you are using DigitalMicrograph (DM) to control a 3View microtome, it must be the same computer on which DM is running. We recommend the Anaconda Python distribution: https://www.anaconda.com/products/individual. Important: Download Python version 3.6 or higher (not 2.7)!


------------------
Download SBEMimage
------------------

Copy all files from the GitHub repository (https://github.com/SBEMimage/SBEMimage) including the folder structure (subdirectories ``src``, ``img``, ``gui``…) into the folder ``C:\pytools\SBEMimage``. You can choose a folder other than ``C:\pytools``, but please ensure the program has full read/write access. Important: In the DM communication script ``dm\SBEMimage_DMcom_GMS2.s``, you have to update the variable ``install_path`` if you use a directory other than ``C:\pytools\SBEMimage``. The path to ``SBEMimage.py`` should be: ``\SBEMimage\src\SBEMimage.py``.

Use the command line to switch to the ``SBEMimage`` directory, in which the file ``requirements.txt`` is located and type: ``pip install -r requirements.txt``. This will install all required Python packages to run SBEMimage.

---------------------------
First start of the software
---------------------------

If you use DigitalMicrograph to control a 3View microtome, you first have to load and run a script in DM that allows SBEMimage to communication with DM.
Load the script ``SBEMimage_DMcom_GMS2.s`` (for GMS 2) or ``SBEMimage_DMcom_GMS3.s`` (for GMS 3) in DigitalMicrograph. It can be found in ``\SBEMimage\dm``. After opening the correct script in DM, click on *Execute*. The message : 'Ready. Waiting for command from SBEMimage...' should be displayed in DM's output window. Further information is provided in the script file.

Now run the main application by starting the batch file ``SBEMimage.bat`` or by typing ``python SBEMimage.py`` in the console (current directory must be ``C:\pytools\SBEMimage\src``). Select ``default.ini`` in the startup dialog. This configuration will start *SBEMimage* in simulation mode. The simulation mode should always work because the APIs for the SEM and the microtome are disabled. This mode can be used to set up acquisitions, calculate estimates, or look at existing data. If you can run *SBEMimage* in simulation mode, it means that your Python environment works and that the installation was successful.

To switch to the normal application mode, do the following: Open ``default.ini``, and save the current configuration under a new name. This will be your first custom user configuration. *SBEMimage* does not allow you to save to ``default.ini`` because that file is used as a template, but you can create as many configuration files as you want. A new configuration file can be created from an existing one by saving it under a new name.
Now, when you have saved your first custom user configuration file (the new file name show be displayed in the status bar of the Main Controls window), click on ``Configuration`` in the top menu and then on ``Leave simulation mode``. Confirm and restart *SBEMimage* with the same configuration file.

If the communication script is running in DigitalMicrograph and the SmartSEM remote API is active and set up correctly, the software should now be fully operational. If the APIs cannot be initialized, you will receive an error message when starting up the application.

-----------------------------
System and user configuration
-----------------------------

*SBEMimage* comes with a default system configuration (``system.cfg``) and a default user configuration (``default.ini``). Both can be found in the subdirectory ``cfg``. These files cannot be changed (from within *SBEMimage*) because they are used as templates. They should only be updated by developers when new functionality is added. When you save a new user configuration for the first time, you will also be asked to specify a new system configuration file. This new system configuration will be linked to all user configurations. ...

-----------
Calibration
-----------

When you have created a system configuration file for your setup and your first editable user configuration file, you need to perform several calibration routines to make *SBEMimage* ready for routine use on your setup.

Magnification calibration
^^^^^^^^^^^^^^^^^^^^^^^^^

Motor speed calibration
^^^^^^^^^^^^^^^^^^^^^^^

Cut cycle duration calibration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Stage calibration
^^^^^^^^^^^^^^^^^

