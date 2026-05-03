# SBEMimage

*SBEMimage* is a free and open-source acquisition software for scanning electron microscopy with a focus on serial block-face imaging. It has been designed for complex, challenging acquisition tasks, such as large-scale volume imaging of biological ultrastructure. Advanced monitoring, process control, and error handling capabilities improve reliability, speed, and quality of acquisitions. Debris detection, autofocus, real-time image inspection, and various other quality control features minimize the risk of data loss. Adaptive tile selection allows for efficient imaging of large volumes of arbitrary shape. The software’s graphical user interface is optimized for remote operation with visual setup and monitoring capabilities. 

*SBEMimage* is customizable and extensible, which allows for fast prototyping and permits adaptation to a wide range of SEM/SBEM systems and applications.

For more background and details read the [paper](https://www.frontiersin.org/articles/10.3389/fncir.2018.00054/abstract). 

<br>

![SBEMimage screenshot](docs/images/SBEMimage_screenshot_with_logo.png)

<br>

## Highlights

*SBEMimage* is currently deployed as open-source software at research institutions worldwide, including:

<table>
  <tr>
    <td style="border: none; vertical-align: middle;"><img src="docs/images/FMI.jfif" height="50" /></td>
    <td style="border: none; vertical-align: middle;"><strong>Friedrich Miescher Institute</strong> in Basel, Switzerland</td>
  </tr>
  <tr>
    <td style="border: none; vertical-align: middle;"><img src="docs/images/EMBL_logo.png" height="50" /></td>
    <td style="border: none; vertical-align: middle;"><strong>European Molecular Biology Laboratory (EMBL)</strong> in Heidelberg, Germany</td>
  </tr>
  <tr>
    <td style="border: none; vertical-align: middle;"><img src="docs/images/crick_logo.png" height="50" /></td>
    <td style="border: none; vertical-align: middle;"><strong>Francis Crick Institute</strong> in London, UK</td>
  </tr>
  <tr>
    <td style="border: none; vertical-align: middle;"><img src="docs/images/Stellenbosch_University_New_Logo.jpg" height="50" /></td>
    <td style="border: none; vertical-align: middle;"><strong>Stellenbosch University</strong> in Stellenbosch, South Africa</td>
  </tr>
</table>

It is being used for a variety of applications, including:
* CZI-funded *Democratising Volumetric Visual Proteomics* project, together with a napari annotation plugin for Targeted Array EM Imaging at the Francis Crick Institute (UK) and Stellenbosch University (South Africa)
* MRC-funded multi-modal project, together with a napari registration plugin for Targeted Array EM Imaging at EMBL Heidelberg (Germany)

## Documentation & Support

A user guide containing installation instructions and a short introduction to the software is available here: [sbemimage.github.io/SBEMimage](https://sbemimage.github.io/SBEMimage).

For users who are not familiar with Python, it is recommended to download the Windows 10+ installer.

Detailed generated information can be found here [deepwiki.com/SBEMimage/SBEMimage](https://deepwiki.com/SBEMimage/SBEMimage)

For support and discussion, please use the [Image.sc forum](https://forum.image.sc/) and post to the forum with the tag 'sbemimage'.

## Development

*SBEMimage* was originally developed at the Friedrich Miescher Institute in Basel, supported by the Novartis Research Foundation and by the European Research Council (ERC) under the European Union’s Horizon 2020 Research and Innovation Programme (Grant Agreement No. 742576). Other institutes that have substantially contributed to *SBEMimage* development, testing and bug fixing include the Francis Crick Institute, London, UK, and EPFL, Lausanne, Switzerland (CIME/BioEM). See https://github.com/SBEMimage/SBEMimage/graphs/contributors for the list of individual contributors.

Contact benjamin.titze ÄT protonmail.ch if you are interested in contributing to the development of *SBEMimage*. All ongoing development takes place in the ['dev' branch](https://github.com/SBEMimage/SBEMimage/tree/dev). Pull requests to that branch are welcome. For more information, see the section ['For developers'](https://sbemimage.github.io/SBEMimage//development) in the user guide.

## Feedback and bug reports

Please use GitHub Issues (https://github.com/SBEMimage/SBEMimage/issues) for bug reports. For general feedback or feature suggestions, post to the [Image.sc forum](https://forum.image.sc/) with the tag 'sbemimage', or send an email to benjamin.titze ÄT protonmail.ch.

## Publication

Please cite the following paper if you use SBEMimage:

Titze B, Genoud C and Friedrich RW (2018) [SBEMimage: Versatile Acquisition Control Software for Serial Block-Face Electron Microscopy](https://www.frontiersin.org/articles/10.3389/fncir.2018.00054/full). Front. Neural Circuits 12:54. doi: 10.3389/fncir.2018.00054

## Licence

This software is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
