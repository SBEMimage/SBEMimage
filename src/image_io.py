import imageio.v3 as iio
import numpy as np
import os
import tifffile
from tifffile import TiffWriter, PHOTOMETRIC

from utils import resize_image, int2float_image, float2int_image, norm_image_quantiles, validate_output_path

# TODO: add ome.zarr support


CONVERSIONS = {'nm': 1e-3, 'nanometer': 1e-3,
               'µm': 1, 'um': 1, 'micrometer': 1,
               'mm': 1e3, 'millimeter': 1e3,
               'cm': 1e4, 'centimeter': 1e4,
               'm': 1e6, 'meter': 1e6}


def imread(path, level=None, target_pixel_size_um=None, channeli=None, render=True):
    image = None
    if os.path.exists(path):
        paths = os.path.splitext(path)
        ext = paths[-1].lower()
        is_tiff = ext in ['.tif', '.tiff']
        metadata = imread_metadata(path)
        dimension_order = metadata.get('dimension_order', -1)
        if 'c' in dimension_order:
            c_index = dimension_order.index('c')
        else:
            c_index = None
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
                image = tifffile.imread(path, level=level)
                # ensure colour channel is at the end
                if c_index is not None and c_index < len(dimension_order) - 1:
                    image = np.moveaxis(image, c_index, -1)
                    if channeli is not None:
                        image = image[..., channeli]
                if scale_by_pixel_size:
                    image = resize_image(image, target_size)
        else:
            try:
                image = iio.imread(path)
            except Exception as e:
                raise TypeError(f'Error reading image {path}\n{e}')
        if render and image is not None:
            image = render_image(image, metadata.get('channels', []))
    return image


def render_image(image, channels):
    new_image = np.zeros(list(image.shape[:2]) + [3], dtype=np.float32)
    nchannels = image.shape[-1] if image.ndim >= 3 else 1
    needs_normalisation = (image.dtype.itemsize == 2)
    n = len(channels)
    is_rgb = (nchannels in (3, 4) and (n <= 1 or n == 3))
    tot_alpha = 0
    if not is_rgb and channels:
        for channeli, channel in enumerate(channels):
            if n == 1:
                channel_values = image
            else:
                channel_values = image[..., channeli]
            channel_values = int2float_image(channel_values)
            if needs_normalisation:
                channel_values = norm_image_quantiles(channel_values)
            color = channel.get('color')
            if color:
                rgba = color
            else:
                rgba = [1, 1, 1, 1]
            color = rgba[:3]
            alpha = rgba[3]
            if alpha == 0:
                alpha = 1
            alpha_color = np.multiply(color, alpha).astype(np.float32)
            new_image = new_image + np.atleast_3d(channel_values) * alpha_color
            tot_alpha += alpha
        new_image /= tot_alpha
        needs_normalisation = False
    else:
        new_image = int2float_image(image)
    if needs_normalisation:
        new_image = norm_image_quantiles(new_image)
    final_image = float2int_image(new_image)
    return final_image


def imread_metadata(path):
    all_metadata = {}
    paths = os.path.splitext(path)
    ext = paths[-1].lower()
    is_tiff = ext in ['.tif', '.tiff']
    pixel_size = []
    position = []
    rotation = None
    dimension_order = 'yxc'
    channels = []

    if is_tiff:
        with tifffile.TiffFile(path) as tiff:
            size = tiff.pages.first.imagewidth, tiff.pages.first.imagelength
            sizes = [size]
            if hasattr(tiff, 'series'):
                series0 = tiff.series[0]
                dimension_order = series0.axes.lower().replace('s', 'c')
                x_index = dimension_order.index('x')
                y_index = dimension_order.index('y')
                if hasattr(series0, 'levels'):
                    sizes = [(level.shape[x_index], level.shape[y_index]) for level in series0.levels]
            if tiff.is_ome:
                metadata = tifffile.xml2dict(tiff.ome_metadata)
                if 'OME' in metadata:
                    metadata = metadata['OME']
                pixels = metadata.get('Image', {}).get('Pixels', {})
                pixel_size = [(float(pixels.get('PhysicalSizeX', 0)), pixels.get('PhysicalSizeXUnit', 'µm')),
                              (float(pixels.get('PhysicalSizeY', 0)), pixels.get('PhysicalSizeYUnit', 'µm'))]
                plane = pixels.get('Plane', {})
                if 'PositionX' in plane and 'PositionY' in plane:
                    position = [(float(plane['PositionX']), plane.get('PositionXUnit', 'µm')),
                                (float(plane['PositionY']), plane.get('PositionYUnit', 'µm'))]
                channels0 = pixels.get('Channel', [])
                if not isinstance(channels0, list):
                    channels0 = [channels0]
                for channeli, channel0 in enumerate(channels0):
                    channel = {}
                    label = channel0.get('Name', '')
                    if not label:
                        label = f'#{channeli}'
                    channel['label'] = label
                    color = channel0.get('Color')
                    if color is not None:
                        channel['color'] = color_int_to_rgba(color)
                    channels.append(channel)
            else:
                tags = {tag.name: tag.value for tag in tiff.pages[0].tags.values()}
                if tiff.is_imagej:
                    metadata = tiff.imagej_metadata
                    unit = metadata.get('unit', '').encode().decode('unicode_escape')
                    if unit == 'micron':
                        unit = 'µm'
                    for scale in metadata.get('scales', '').split(','):
                        pixel_size.append((float(scale), unit))
                    if len(pixel_size) == 0 and metadata is not None and 'spacing' in metadata:
                        pixel_size_z = (metadata['spacing'], unit)
                elif 'FEI_TITAN' in tags:
                    metadata = tifffile.xml2dict(tags.pop('FEI_TITAN'))
                    if 'FeiImage' in metadata:
                        metadata = metadata['FeiImage']
                        pixel_info = metadata.get('pixelWidth')
                        if pixel_info:
                            pixel_size.append((pixel_info['value'], pixel_info['unit']))
                        pixel_info = metadata.get('pixelHeight')
                        if pixel_info:
                            pixel_size.append((pixel_info['value'], pixel_info['unit']))
                        position = metadata.get('samplePosition')
                        if position:
                            position = [(position['x'], 'm'), (position['y'], 'm')]
                        rotation = metadata.get('acquisition', {}).get('frame', {}).get('rotation')
                if not pixel_size:
                    units = tags.get('ResolutionUnit')
                    if units is not None:
                        units = units.name
                        xres = convert_rational_value(tags.get('XResolution'))
                        yres = convert_rational_value(tags.get('YResolution'))
                        if units.lower() not in ['', 'none', 'inch']:
                            if xres is not None and xres != 0:
                                pixel_size.append((1 / xres, units))
                            if yres is not None and yres != 0:
                                pixel_size.append((1 / yres, units))
    else:
        try:
            properties = iio.improps(path)
            size = properties.shape[1], properties.shape[0]
            sizes = [size]
            resolution = properties.spacing
            if resolution:
                metadata = iio.immeta(path)
                units = metadata.get('unit')
                pixel_size = [(1 / res, units) for res in resolution]
        except Exception as e:
            raise TypeError(f'Error reading image {path}\n{e}')

    all_metadata['dimension_order'] = dimension_order
    all_metadata['size'] = size
    all_metadata['sizes'] = sizes
    if len(pixel_size) > 0:
        pixel_size_um = convert_units_micrometer(pixel_size)
        all_metadata['pixel_size'] = pixel_size_um
    if len(position) > 0:
        position_um = convert_units_micrometer(position)
        all_metadata['position'] = position_um
    if rotation is not None:
        all_metadata['rotation'] = rotation
    if len(channels) > 0:
        all_metadata['channels'] = channels
    return all_metadata


def create_tiff_metadata(metadata, is_ome=False):
    ome_metadata = None
    resolution = None
    resolution_unit = None
    pixel_size_um = None

    pixel_size = metadata.get('pixel_size')
    position = metadata.get('position')
    if pixel_size is not None:
        pixel_size_um = convert_units_micrometer(pixel_size)
        resolution_unit = 'CENTIMETER'
        resolution = [1e4 / size for size in pixel_size_um]
    channels = metadata.get('channels', [])

    if is_ome:
        ome_metadata = {}
        ome_channels = []
        if pixel_size_um is not None:
            ome_metadata['PhysicalSizeX'] = pixel_size_um[0]
            ome_metadata['PhysicalSizeXUnit'] = 'µm'
            ome_metadata['PhysicalSizeY'] = pixel_size_um[1]
            ome_metadata['PhysicalSizeYUnit'] = 'µm'
            if len(pixel_size_um) > 2:
                ome_metadata['PhysicalSizeZ'] = pixel_size_um[2]
                ome_metadata['PhysicalSizeZUnit'] = 'µm'
        if position is not None:
            plane_metadata = {}
            plane_metadata['PositionX'] = position[0]
            plane_metadata['PositionXUnit'] = 'µm'
            plane_metadata['PositionY'] = position[1]
            plane_metadata['PositionYUnit'] = 'µm'
            if len(position) > 2:
                ome_metadata['PositionZ'] = position[2]
                ome_metadata['PositionZUnit'] = 'µm'
            ome_metadata['Plane'] = plane_metadata
        for channel in channels:
            ome_channel = {'Name': channel.get('label', '')}
            if 'color' in channel:
                ome_channel['Color'] = color_rgba_to_int(channel['color'])
            ome_channels.append(ome_channel)
        if ome_channels:
            ome_metadata['Channel'] = ome_channels
    return ome_metadata, resolution, resolution_unit


def imwrite(path, data, metadata=None, tile_size=None, compression='LZW',
            npyramid_add=0, pyramid_downsample=2):
    resolution = None
    resolution_unit = None

    paths = path.split('.', 1)
    ext = paths[-1].lower()
    is_tiff = 'tif' in ext
    is_ome = paths[-1].lower().startswith('ome')
    size = np.flip(data.shape[:2])

    if is_tiff:
        if data.ndim <= 3 and data.shape[-1] in (3, 4):
            photometric = PHOTOMETRIC.RGB
            move_channel = False
        else:
            photometric = PHOTOMETRIC.MINISBLACK
            # move channel axis to front
            move_channel = (data.ndim >= 3 and data.shape[-1] < data.shape[0])

        if metadata is not None:
            tiff_metadata, resolution, resolution_unit = create_tiff_metadata(metadata, is_ome)
        else:
            tiff_metadata = None
        validate_output_path(path, is_file=True)
        with TiffWriter(path) as writer:
            new_size = size
            ordered_data = np.moveaxis(data, -1, 0) if move_channel else data
            writer.write(ordered_data, photometric=photometric, subifds=npyramid_add,
                         tile=tile_size, compression=compression,
                         resolution=resolution, resolutionunit=resolution_unit,
                         metadata=tiff_metadata)
            for i in range(npyramid_add):
                new_size = new_size / pyramid_downsample    # implicit int -> float conversion
                if resolution is not None:
                    resolution = tuple(np.divide(resolution, pyramid_downsample))
                int_size = np.round(new_size).astype(int)
                resized_data = resize_image(data, int_size)
                ordered_data = np.moveaxis(resized_data, -1, 0) if move_channel else resized_data
                writer.write(ordered_data, subfiletype=1,
                             tile=tile_size, compression=compression,
                             resolution=resolution, resolutionunit=resolution_unit)
    else:
        iio.imwrite(path, data)


def convert_units_micrometer(value_units0: list):
    value_units = []
    if value_units0 is None:
        return None

    for value_unit in value_units0:
        if (isinstance(value_unit, tuple) or isinstance(value_unit, list)) and len(value_unit) > 1:
            value_units.append(value_unit[0] * CONVERSIONS.get(value_unit[1].lower()))
        else:
            value_units.append(value_unit)
    return value_units


def convert_rational_value(value):
    if value is not None and isinstance(value, tuple):
        value = value[0] / value[1]
    return value


def color_int_to_rgba(intrgba: int) -> list:
    signed = (intrgba < 0)
    rgba = [x / 255 for x in intrgba.to_bytes(4, signed=signed, byteorder="big")]
    if rgba[-1] == 0:
        rgba[-1] = 1
    return rgba


def color_rgba_to_int(rgba: list) -> int:
    intrgba = int.from_bytes([int(x * 255) for x in rgba], signed=True, byteorder="big")
    return intrgba
