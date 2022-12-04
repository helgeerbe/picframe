import pytest
import logging


from  picframe.get_image_meta import GetImageMeta

logger = logging.getLogger("test_get_image_data")
logger.setLevel(logging.DEBUG)

def test_file_not_found():
    try:
        exifs = GetImageMeta("nonsense")
        assert exifs.has_exif() == False
    except:
        pytest.fail("Unexpected exception")

def test_open_file():
    try:
        GetImageMeta("test/images/AlleExif.JPG")
    except:
        pytest.fail("Unexpected exception")

def test_has_exif():
    try:
        exifs = GetImageMeta("test/images/AlleExif.JPG")
        assert exifs.has_exif() == True
    except:
        pytest.fail("Unexpected exception")

def images_has_no_exif():
    try:
        exifs = GetImageMeta("test/images/noimage.jpg")
        assert exifs.has_exif() == False
    except:
        pytest.fail("Unexpected exception")

def test_get_location():
    try:
        exifs = GetImageMeta("test/images/AlleExif.JPG")
        gps = exifs.get_location()
        assert  gps == {"latitude": 25.197269, "longitude": 55.274359}
    except:
        pytest.fail("Unexpected exception")

def test_get_no_location():
    try:
        exifs = GetImageMeta("test/images/noimage.jpg")
        gps = exifs.get_location()
        assert  gps == {"latitude": None, "longitude": None}
    except:
        pytest.fail("Unexpected exception")

def test_exifs_jpg():
    try:
        exifs = GetImageMeta("test/images/AlleExif.JPG")
        val = exifs.get_exif('EXIF FNumber')
        assert  val == 2.8
        val = exifs.get_exif('EXIF ExposureTime')
        assert  val == "1/30"
        val = exifs.get_exif('EXIF ISOSpeedRatings')
        assert  val == 6400
        val = exifs.get_exif('EXIF FocalLength')
        assert  val == "17.0"
        val = exifs.get_exif('EXIF DateTimeOriginal')
        assert  val == "2020:01:30 20:01:28"
        val = exifs.get_exif('Image Model')
        assert  val == "ILCE-7RM3"
        width, height = exifs.get_size()
        assert width == 1920
        assert height == 1200
        val = exifs.get_exif('Image Make')
        assert  val == "SONY"
        val = exifs.get_exif('EXIF Make') # This should work as well
        assert  val == "SONY"
    except:
        pytest.fail("Unexpected exception")

def test_get_orientation():
    try:
        # no image
        exifs = GetImageMeta("test/images/noimage.jpg")
        orientation = exifs.get_orientation()
        assert  orientation == 1

        # jpg
        exifs = GetImageMeta("test/images/AlleExif.JPG")
        orientation = exifs.get_orientation()
        assert  orientation == 1

        exifs = GetImageMeta("test/images/test3.HEIC")
        orientation = exifs.get_orientation()
        assert  orientation == 1 
    except:
        pytest.fail("Unexpected exception")

def test_exifs_heic():
    try:
        exifs = GetImageMeta("test/images/test3.HEIC")
        orientation = exifs.get_orientation()
        assert  orientation == 1

        width, height = exifs.get_size()
        assert height == 4032
        assert width == 3024


        f_number = exifs.get_exif('EXIF FNumber')
        assert f_number == 1.8

        make =  exifs.get_exif('Image Make')
        assert make == "Apple"

        model = exifs.get_exif('Image Model')
        assert model == "iPhone 8"

        exposure_time = exifs.get_exif('EXIF ExposureTime')
        assert exposure_time == "1/5"

        iso =  exifs.get_exif('EXIF ISOSpeedRatings')
        assert iso == 100

        focal_length =  exifs.get_exif('EXIF FocalLength')
        assert focal_length == "3.99"

        rating = exifs.get_exif('EXIF Rating')
        assert rating == None

        lens = exifs.get_exif('EXIF LensModel')
        assert lens ==  "iPhone 8 back camera 3.99mm f/1.8"

        exif_datetime = exifs.get_exif('EXIF DateTimeOriginal')
        assert exif_datetime == "2021:05:14 20:27:14"

        gps = exifs.get_location()
        assert gps['latitude'] == 38.71365
        gps['longitude'] == -78.15960555555556
        

        #IPTC
        tags = exifs.get_exif('IPTC Keywords')
        assert tags == 'Stichwort1,Stichwort2,'

        title = exifs.get_exif('IPTC Object Name')
        assert title == 'Das ist die Überschrift'

        caption = exifs.get_exif('IPTC Caption/Abstract')
        assert caption == 'Hier ist die Beschreibung'

    except:
        pytest.fail("Unexpected exception")