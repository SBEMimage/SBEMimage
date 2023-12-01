import imageio.v3
import os
import tifffile

# TODO: add ome.zarr support


def imread(path):
    paths = os.path.splitext(path)
    ext = paths[-1].lower()
    is_tiff = ext in ['.tif', '.tiff']

    if is_tiff:
        data = tifffile.imread(path)
    else:
        data = imageio.v3.imread(path)
    return data


def imread_metadata(path):
    paths = os.path.splitext(path)
    ext = paths[-1].lower()
    is_tiff = ext in ['.tif', '.tiff']

    if is_tiff:
        with tifffile.TiffFile(path) as tif:
            if tif.is_ome:
                metadata = tifffile.xml2dict(tif.ome_metadata)
                if 'OME' in metadata:
                    metadata = metadata['OME']
                pixels = metadata.get('Image', {}).get('Pixels', {})
                pixel_size = [(float(pixels.get('PhysicalSizeX', 0)), pixels.get('PhysicalSizeXUnit', 'µm')),
                              (float(pixels.get('PhysicalSizeY', 0)), pixels.get('PhysicalSizeYUnit', 'µm')),
                              (float(pixels.get('PhysicalSizeZ', 0)), pixels.get('PhysicalSizeZUnit', 'µm'))]
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
                pixel_size = 1 / xres, 1 / yres
    else:
        resolution = imageio.v3.improps(path).spacing
        pixel_size = [1 / res for res in resolution]
        metadata = imageio.v3.immeta(path)
        units = metadata.get('unit')

    # TODO convert from [units] to um
    return pixel_size


def imwrite(path, data, pixel_size_um=[], tile_size=None, compression=None):
    resolution = None
    resolution_unit = None
    metadata = None

    paths = os.path.splitext(path)
    ext = paths[-1].lower()
    is_tiff = ext in ['.tif', '.tiff']
    is_ome = paths[0].lower().endswith('.ome')

    if is_tiff:
        bigtiff = (data.size * data.itemsize > 2 ** 32)
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
        tifffile.imwrite(path, data, bigtiff=bigtiff,
                         metadata=metadata, resolution=resolution, resolutionunit=resolution_unit,
                         tile=tile_size, compression=compression)
    else:
        imageio.v3.imwrite(path, data)
