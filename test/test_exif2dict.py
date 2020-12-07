import pytest
import logging


from  picframe import exif2dict

logger = logging.getLogger("test_exif2dict")
logger.setLevel(logging.DEBUG)

def test_file_not_found():
    with pytest.raises(OSError):
        exif2dict.Exif2Dict("nonsense")

def test_open_file():
    try:
        exif2dict.Exif2Dict("test/AlleExif.JPG")
    except:
        pytest.fail("Unexpected exception")

def test_has_exif():
    try:
        exifs = exif2dict.Exif2Dict("test/AlleExif.JPG")
        assert exifs.has_exif() == True
    except:
        pytest.fail("Unexpected exception")

def test_has_no_exif():
    try:
        exifs = exif2dict.Exif2Dict("test/noimage.jpg")
        assert exifs.has_exif() == False
    except:
        pytest.fail("Unexpected exception")

def test_get_location():
    try:
        exifs = exif2dict.Exif2Dict("test/AlleExif.JPG")
        gps = exifs.get_locaction()
        assert  gps == {"latitude": 25.197269, "longitude": 55.274359}
    except:
        pytest.fail("Unexpected exception")

def test_get_no_location():
    try:
        exifs = exif2dict.Exif2Dict("test/noimage.jpg")
        gps = exifs.get_locaction()
        assert  gps == {"latitude": None, "longitude": None}
    except:
        pytest.fail("Unexpected exception")

def test_get_exif():
    try:
        exifs = exif2dict.Exif2Dict("test/AlleExif.JPG")
        val = exifs.get_exif('EXIF FNumber')
        assert  val == {"EXIF FNumber": 2.8}
        val = exifs.get_exif('EXIF ExposureTime')
        assert  val == {"EXIF ExposureTime": "1/30"}
        val = exifs.get_exif('EXIF ISOSpeedRatings')
        assert  val == {"EXIF ISOSpeedRatings": "6400"}
        val = exifs.get_exif('EXIF FocalLength')
        assert  val == {"EXIF FocalLength": "17"}
        val = exifs.get_exif('EXIF DateTimeOriginal')
        assert  val == {"EXIF DateTimeOriginal": "2020:01:30 20:01:28"}
        val = exifs.get_exif('Image Model')
        assert  val == {"Image Model": "ILCE-7RM3"}
    except:
        pytest.fail("Unexpected exception")