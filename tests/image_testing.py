from tifffile import OmeXml

from image_io import *


def load_image(path):
    image = imread(path)
    return image


def save_image(path, image):
    imwrite(path, image)


def generate_image():
    omexml = OmeXml()
    omexml.addimage(
        dtype='uint16',
        shape=(2, 256, 256),
        storedshape=(2, 1, 1, 256, 256, 1),
        axes='CYX',
        Name='First Image',
        PhysicalSizeX=2.0,
    )
    omexml.annotations.append('test')
    xml = omexml.tostring().replace('<', '\n<')
    print(xml)


if __name__ == '__main__':
    #path = 'D:/slides/Sigma_test_images/grab.tif'
    #load_image(path)

    path = 'D:/slides/test.ome.tif'
    image = np.zeros(shape=(16, 16), dtype=np.uint8)
    generate_image()
