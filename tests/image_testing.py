from tifffile import OmeXml

from image_io import *


def load_image(path):
    metadata = imread_metadata(path)
    image = imread(path)
    return image, metadata


def save_image(path, image, metadata=None):
    imwrite(path, image, metadata=metadata)


def generate_omexml(metadata):
    omexml = OmeXml()
    omexml.addimage(
        dtype='uint16',
        shape=(2, 256, 256),  # (1, 2, 256, 256),
        storedshape=(2, 1, 1, 256, 256, 1),
        axes='CYX',  # 'ACYX',
        Name='First Image',
        PhysicalSizeX=2.0,
        **metadata
    )
    #omexml.annotations.append('test')  # string merge custom data
    xml = omexml.tostring().replace('<', '\n<')
    print(xml)


if __name__ == '__main__':
    path = 'D:/slides/test.ome.tif'
    image = np.zeros(shape=(16, 16), dtype=np.uint8)

    #generate_omexml({'Image': {'DimensionOrder': 'ACYX', 'StructuredAnnotations': {'MapAnnotation': {'key': 'value'}}}})

    save_image(path, image, metadata={'rotation': -12.3})

    image2, metadata2 = load_image(path)
    print(metadata2['rotation'])
