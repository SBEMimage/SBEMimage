# SBEMimage

Open-source acquisition software for scanning electron microscopy with a focus on serial block-face imaging, made with Python and PyQt.

*SBEMimage* is designed for complex, challenging acquisition tasks, such as large-scale volume imaging of neuronal tissue or other biological ultrastructure. Advanced monitoring, process control, and error handling capabilities improve reliability, speed, and quality of acquisitions. Debris detection, autofocus, real-time image inspection, and various other quality control features minimize the risk of data loss during long-term acquisitions. Adaptive tile selection allows for efficient imaging of large EM volumes of arbitrary shape. The software’s graphical user interface is optimized for remote operation. It includes a user-friendly Viewport window to visually set up acquisitions and monitor them.

*SBEMimage* is customizable and extensible, which allows for fast prototyping and permits adaptation to a wide range of SEM/SBEM systems and applications.

For more background and details read the [paper](https://www.frontiersin.org/articles/10.3389/fncir.2018.00054/abstract).

<img src="https://github.com/SBEMimage/SBEMimage/blob/master/img/viewport_screenshot.png" width="600">

## Getting started / Support

Please read the user guide: https://sbemimage.readthedocs.io. It currently contains installation instructions and a short introduction to the software (to be expanded). For support and discussion, please use the [Image.sc forum](https://forum.image.sc/).

## Releases

*The current version is 2020.07. We are planning to release future versions with an installer and an expanded user guide.*

## Authors / Contributing

Benjamin Titze ([btitze](https://github.com/btitze)), Friedrich Miescher Institute for Biomedical Research, Basel, Switzerland (lead developer); Thomas Templier, Janelia Research Campus (MagC wafer acquisition functionality); Joost de Folter, Francis Crick Institute; and others: https://github.com/SBEMimage/SBEMimage/graphs/contributors

The development of SBEMimage at the Friedrich Miescher Institute has been supported by the Novartis Research Foundation and by the European Research Council (ERC) under the European Union’s Horizon 2020 Research and Innovation Programme (Grant Agreement No. 742576).

Other institutes that have substantially contributed to SBEMimage development/testing: EPFL, Lausanne, Switzerland (CIME/BioEM); Francis Crick Institute, London, UK.

Please use GitHub Issues (https://github.com/SBEMimage/SBEMimage/issues) for bug reports. Contact benjamin.titze ÄT fmi.ch if you are interested in contributing to the development of SBEMimage. All ongoing development takes place in the 'dev' branch. Pull requests to that branch are welcome. For more information, see the section [For developers](https://sbemimage.readthedocs.io/en/latest/development.html) in the user guide.

## Publication ##

Please cite the following paper if you use SBEMimage:

Titze B, Genoud C and Friedrich RW (2018) [SBEMimage: Versatile Acquisition Control Software for Serial Block-Face Electron Microscopy](https://www.frontiersin.org/articles/10.3389/fncir.2018.00054/full). Front. Neural Circuits 12:54. doi: 10.3389/fncir.2018.00054

## Licence

This software is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
