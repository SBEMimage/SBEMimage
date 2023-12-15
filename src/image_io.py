import imageio.v3
import numpy as np
import os
import tifffile
from tifffile import TiffWriter

from utils import resize_image


# TODO: add ome.zarr support


def imread(path, level=None, target_pixel_size_um=None):
    data = None
    paths = os.path.splitext(path)
    ext = paths[-1].lower()
    is_tiff = ext in ['.tif', '.tiff']
    metadata = imread_metadata(path)
    size = metadata['size']
    nlevels = len(metadata['sizes'])
    source_pixel_size = metadata.get('pixel_size')
    scale_by_pixel_size = (target_pixel_size_um is not None and source_pixel_size is not None)
    target_size = 1

    if is_tiff:
        if scale_by_pixel_size:
            target_size = (np.divide(source_pixel_size, target_pixel_size_um) * size).astype(int)
            for level1, size1 in enumerate(metadata['sizes']):
                if np.all(size1 > target_size):
                    level = level1
        if level is None or level < nlevels:
            data = tifffile.imread(path, level=level)
            if scale_by_pixel_size:
                data = resize_image(data, target_size)
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
                if units.lower() not in ['', 'none', 'inch']:
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
    pixel_size_um = convert_units_micrometer(pixel_size)
    if len(pixel_size_um) > 0:
        all_metadata['pixel_size'] = pixel_size_um
    return all_metadata


def create_tiff_metadata(metadata, is_ome=False):
    ome_metadata = None
    resolution = None
    resolution_unit = None

    pixel_size = metadata.get('pixel_size')
    if pixel_size is not None:
        pixel_size_um = convert_units_micrometer(pixel_size)
        resolution_unit = 'CENTIMETER'
        resolution = [1e4 / size for size in pixel_size_um]
    else:
        pixel_size_um = None
    if is_ome:
        ome_metadata = {}
        if pixel_size_um is not None:
            ome_metadata['PhysicalSizeX'] = pixel_size_um[0]
            ome_metadata['PhysicalSizeXUnit'] = 'µm'
            ome_metadata['PhysicalSizeY'] = pixel_size_um[1]
            ome_metadata['PhysicalSizeYUnit'] = 'µm'
        position = metadata.get('position')
        if position is not None:
            plane_metadata = {}
            plane_metadata['PositionX'] = position[0]
            plane_metadata['PositionXUnit'] = 'µm'
            plane_metadata['PositionY'] = position[1]
            plane_metadata['PositionYUnit'] = 'µm'
            ome_metadata['Plane'] = plane_metadata
    return ome_metadata, resolution, resolution_unit


def imwrite(path, data, tile_size=None, compression=None, metadata=None,
            npyramid_add=0, pyramid_downsample=2):
    resolution = None
    resolution_unit = None

    paths = path.split('.', 1)
    ext = paths[-1].lower()
    is_tiff = 'tif' in ext
    is_ome = paths[-1].lower().startswith('ome')

    if is_tiff:
        if metadata is not None:
            tiff_metadata, resolution, resolution_unit = create_tiff_metadata(metadata, is_ome)
        else:
            tiff_metadata = None
        with TiffWriter(path) as writer:
            writer.write(data, subifds=npyramid_add,
                         tile=tile_size, compression=compression,
                         resolution=resolution, resolutionunit=resolution_unit,
                         metadata=tiff_metadata)
            new_size = np.flip(data.shape[:2])
            for i in range(npyramid_add):
                new_size = new_size / 2
                if resolution is not None:
                    resolution = tuple(np.divide(resolution, pyramid_downsample))
                int_size = new_size.astype(int)
                resized_data = resize_image(data, int_size)
                writer.write(resized_data, subfiletype=1,
                             tile=tile_size, compression=compression,
                             resolution=resolution, resolutionunit=resolution_unit)
    else:
        imageio.v3.imwrite(path, data)


def convert_units_micrometer(value_units0: list):
    value_units = []
    conversions = {'nm': 1e-3, 'nanometer': 1e-3,
                   'µm': 1, 'um': 1, 'micrometer': 1,
                   'mm': 1e3, 'millimeter': 1e3,
                   'cm': 1e4, 'centimeter': 1e4,
                   'm': 1e6, 'meter': 1e6}
    if value_units0 is None:
        return None

    for value_unit in value_units0:
        if (isinstance(value_unit, tuple) or isinstance(value_unit, list)) and len(value_unit) > 1:
            value_units.append(value_unit[0] * conversions.get(value_unit[1].lower()))
        else:
            value_units.append(value_unit)
    return value_units
