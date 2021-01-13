Requirements
============

*SBEMimage* can be run in simulation mode on any computer with Windows 7 or 10 and a Python 3.6+ environment. The Python environment is provided automatically if you use the installer, or it can be downloaded for free, see installation instructions. A screen resolution of at least 1920 × 1080 is required to fully see both application windows. On Windows 10, it is recommended not to use high-resolution scaling. Currently, when using a scaling other than 100% on Windows 10, there may be problems with the font size in the GUI (but no impact on functionality).

For data acquisitions, the following requirements must be met (version 2020.07 of *SBEMimage*). We will support SEMs and microtomes from other manufacturers in future releases.

* ZEISS SEM with SmartSEM software (version 5.4 or above – older versions may work, but have not been tested.)
* Remote control capability for SmartSEM (SmartSEM Remote API): The remote client must be installed and configured. Ask ZEISS for further information.
* For serial block-face imaging the Gatan 3View system with DigitalMicrograph (GMS 2 or 3) or the ConnectomX katana microtome are currently supported.
* If you can see the images from the desired detector in SmartSEM, you can use *SBEMimage* directly. If you can only see the acquired images in DigitalMicrograph, you may have to use an adapter to feed the detector signal to the SEM. The adapter (for ZEISS SEMs) can be built with the following parts: FCT Electronic FM-11W1P-K120, FCT Electronic FMX-008P102, and standard BNC cable, see image below. Find the amplified output signal of the Gatan BSE detector (or any other detector – does not matter as long as you can get the signal onto a BNC cable), then connect that output signal BNC cable to the BNC end of the adapter shown above. Then find the input boards at the back of the microscope where the signals from the different detectors are fed in. Choose one that is not in use or that is used for a detector you do not need. Connect the other end of the adapter to that circuit board. You can now record images from the detector of your choice in SmartSEM.

.. image:: /images/ZEISS_adapter.jpg
   :width: 300
   :align: center
