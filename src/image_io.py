import imageio.v3
import os
import tifffile

from src.utils import uint8_image


# TODO: add ome.zarr support


def imread(path):
    paths = os.path.splitext(path)
    ext = paths[-1].lower()
    is_tiff = ext in ['.tif', '.tiff']

    if is_tiff:
        # if pyramid load lowest res, convert to uint8
        data = uint8_image(tifffile.imread(path, level=-1))
    else:
        data = imageio.v3.imread(path)
    return data


def imread_metadata(path):
    paths = os.path.splitext(path)
    ext = paths[-1].lower()
    is_tiff = ext in ['.tif', '.tiff']
    pixel_size = []

    if is_tiff:
        with tifffile.TiffFile(path) as tif:
            if tif.is_ome:
                metadata = tifffile.xml2dict(tif.ome_metadata)
                if 'OME' in metadata:
                    metadata = metadata['OME']
                pixels = metadata.get('Image', {}).get('Pixels', {})
                pixel_size = [(float(pixels.get('PhysicalSizeX', 0)), pixels.get('PhysicalSizeXUnit', 'µm')),
                              (float(pixels.get('PhysicalSizeY', 0)), pixels.get('PhysicalSizeYUnit', 'µm'))]
            else:
                tags = {tag.name: tag.value for tag in tif.pages[0].tags.values()}
                xres = tags['XResolution']
                if xres is not None:
                    if isinstance(xres, tuple):
                        xres = xres[0] / xres[1]
                yres = tags['YResolution']
                if yres is not None:
                    if isinstance(yres, tuple):
                        yres = yres[0] / yres[1]
                units = tags['ResolutionUnit'].name
                pixel_size = [(1 / xres, units), (1 / yres, units)]
    else:
        resolution = imageio.v3.improps(path).spacing
        if resolution:
            metadata = imageio.v3.immeta(path)
            units = metadata.get('unit')
            pixel_size = [(1 / res, units) for res in resolution]

    pixel_size_um = convert_units_micrometer(pixel_size)
    return pixel_size_um


def create_tiff_metadata(pixel_size_um, is_ome=False):
    resolution = None
    resolution_unit = None
    metadata = None

    if len(pixel_size_um) > 0:
        resolution_unit = 'CENTIMETER'
        resolution = [1e4 / size for size in pixel_size_um]
        if is_ome:
            metadata = {
                'PhysicalSizeX': pixel_size_um[0],
                'PhysicalSizeY': pixel_size_um[1],
                'PhysicalSizeXUnit': 'µm',
                'PhysicalSizeYUnit': 'µm',
            }
    return metadata, resolution, resolution_unit


def imwrite(path, data, pixel_size_um=[], tile_size=None, compression=None):
    resolution = None
    resolution_unit = None
    metadata = None

    paths = os.path.splitext(path)
    ext = paths[-1].lower()
    is_tiff = ext in ['.tif', '.tiff']
    is_ome = paths[-1].lower().endswith('.ome')

    if is_tiff:
        if len(pixel_size_um) > 0:
            metadata, resolution, resolution_unit = create_tiff_metadata(pixel_size_um, is_ome)
        tifffile.imwrite(path, data,
                         metadata=metadata, resolution=resolution, resolutionunit=resolution_unit,
                         tile=tile_size, compression=compression)
    else:
        imageio.v3.imwrite(path, data)


def imwrite_metadata(path, pixel_size_um):
    is_ome = os.path.splitext(path)[-1].lower().endswith('.ome')
    metadata, resolution, resolution_unit = create_tiff_metadata(pixel_size_um, is_ome)
    # TODO: write metadata using Exif Tags / file description for ome tiff (e.g. using Pillow)


def convert_units_micrometer(value_units0: list):
    conversions = {'nm': 1e-3, 'nanometer': 1e-3,
                   'µm': 1, 'um': 1, 'micrometer': 1,
                   'mm': 1e3, 'millimeter': 1e3,
                   'cm': 1e4, 'centimeter': 1e4,
                   'm': 1e6, 'meter': 1e6}
    if value_units0 is None:
        return None

    value_units = [value_unit[0] * conversions.get(value_unit[1] if len(value_unit) > 1 else 'um', 1)
                   for value_unit in value_units0]
    return value_units
