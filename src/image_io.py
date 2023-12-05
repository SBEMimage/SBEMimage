import imageio.v3
import numpy as np
import os
import tifffile

from utils import resize_image


# TODO: add ome.zarr support


def imread(path, target_pixel_size_um=None):
    paths = os.path.splitext(path)
    ext = paths[-1].lower()
    is_tiff = ext in ['.tif', '.tiff']
    metadata = imread_metadata(path)
    size = metadata['size']
    source_pixel_size = metadata.get('pixel_size')

    if is_tiff:
        if target_pixel_size_um is not None and source_pixel_size is not None:
            target_size = (np.divide(source_pixel_size, target_pixel_size_um) * size).astype(int)
            target_level = 0
            for level, size1 in enumerate(metadata['sizes']):
                if np.all(size1 > target_size):
                    target_level = level
            data = resize_image(tifffile.imread(path, level=target_level), target_size)
        else:
            data = tifffile.imread(path)
    else:
        data = imageio.v3.imread(path)
    return data


def imread_metadata(path):
    all_metadata = {}
    paths = os.path.splitext(path)
    ext = paths[-1].lower()
    is_tiff = ext in ['.tif', '.tiff']
    pixel_size = []

    if is_tiff:
        with tifffile.TiffFile(path) as tif:
            size = tif.pages.first.imagewidth, tif.pages.first.imagelength
            sizes = [size]
            if tif.is_ome:
                metadata = tifffile.xml2dict(tif.ome_metadata)
                if 'OME' in metadata:
                    metadata = metadata['OME']

                subsizes0 = metadata.get('StructuredAnnotations', {}).get('MapAnnotation', {}).get('Value', {}).get('M', [])
                subsizes = {item['K']: item['value'] for item in subsizes0}
                sizes += [[int(s) for s in subsizes[key].split()] for key in sorted(subsizes)]

                pixels = metadata.get('Image', {}).get('Pixels', {})
                pixel_size = [(float(pixels.get('PhysicalSizeX', 0)), pixels.get('PhysicalSizeXUnit', 'µm')),
                              (float(pixels.get('PhysicalSizeY', 0)), pixels.get('PhysicalSizeYUnit', 'µm'))]
            else:
                tags = {tag.name: tag.value for tag in tif.pages[0].tags.values()}
                xres = tags['XResolution']
                yres = tags['YResolution']
                units = tags['ResolutionUnit'].name
                if xres is not None:
                    if isinstance(xres, tuple):
                        xres = xres[0] / xres[1]
                    if xres != 0:
                        pixel_size.append((1 / xres, units))
                if yres is not None:
                    if isinstance(yres, tuple):
                        yres = yres[0] / yres[1]
                    if yres != 0:
                        pixel_size.append((1 / yres, units))
    else:
        properties = imageio.v3.improps(path)
        size = properties.shape[1], properties.shape[0]
        sizes = [size]
        resolution = properties.spacing
        if resolution:
            metadata = imageio.v3.immeta(path)
            units = metadata.get('unit')
            pixel_size = [(1 / res, units) for res in resolution]

    all_metadata['size'] = size
    all_metadata['sizes'] = sizes
    all_metadata['pixel_size'] = convert_units_micrometer(pixel_size)
    return all_metadata


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

    paths = path.split('.', 1)
    ext = paths[-1].lower()
    is_tiff = 'tif' in ext
    is_ome = paths[-1].lower().startswith('ome')

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

    value_units = [value_unit[0] * conversions.get(value_unit[1].lower() if len(value_unit) > 1 else 'um', 1)
                   for value_unit in value_units0]
    return value_units
