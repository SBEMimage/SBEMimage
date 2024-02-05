from image_io import imread


def load_image(path):
    image = imread(path)


if __name__ == '__main__':
    path = 'D:/slides/Sigma_test_images/grab.tif'
    load_image(path)
