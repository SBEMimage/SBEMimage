import re
from tifffile import OmeXml

from image_io import *


def load_image(path):
    metadata = imread_metadata(path)
    image = imread(path)
    return image, metadata


def save_image(path, image, metadata=None):
    imwrite(path, image, metadata=metadata)


def save_image_custom_metadata(path, image, axes, metadata=None):
    xml = generate_omexml(image, axes, metadata.get('rotation', 0))
    tifffile.imwrite(path, image, ome=False, description=xml.encode())


def generate_omexml(image, axes, rotation, metadata={}):
    omexml = OmeXml()

    dim_dict = {axis.lower(): value for value, axis in zip(image.shape, axes)}
    depth, length, width = dim_dict.get('z', 1), dim_dict.get('y', 1), dim_dict.get('x', 1)
    channels = dim_dict.get('c', 1)

    axes = 'A' + axes.upper()
    # shape: dimensions according to definition of axes
    shape = [1] + list(image.shape)
    # storedshape: pages, separate_samples, depth, length, width, contig_samples
    storedshape = (channels, 1, depth, length, width, 1)

    omexml.addimage(
        dtype=image.dtype,
        shape=shape,
        storedshape=storedshape,
        axes=axes,
        **metadata
    )
    xml_match = r'<ModuloAlong.+/>'
    xml_replace = f'<ModuloAlongZ Type="angle" Unit="degree"><Label>{rotation}</Label></ModuloAlongZ>'
    xml = re.sub(xml_match, xml_replace, omexml.tostring())
    return xml


if __name__ == '__main__':
    path = 'D:/slides/test.ome.tif'
    image = np.zeros(shape=(16, 16), dtype=np.uint8)
    rotation = -12.3

    xml = generate_omexml(image, 'YX', rotation)
    print(xml)

    save_image_custom_metadata(path, image, 'YX', metadata={'rotation': rotation})
    image2, metadata2 = load_image(path)
    print(metadata2.get('rotation'))

    save_image(path, image, metadata={'rotation': rotation})
    image2, metadata2 = load_image(path)
    print(metadata2.get('rotation'))
