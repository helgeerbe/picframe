import pytest
import logging

import os


from picframe import model

logger = logging.getLogger("test_model")
logger.setLevel(logging.DEBUG)

def test_model_init():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    mqtt = m.get_mqtt_config()
    assert mqtt['server'] == 'home'
    viewer = m.get_viewer_config()
    assert viewer['test_key'] == 'test_value'
  

def test_for_file_changes():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    m.subdirectory = 'testdir'
    testfile = os.path.expanduser(m.get_model_config()['pic_dir']) + "/"+ 'testdir' + "/testfile.jpg"
    assert m.check_for_file_changes() == False
    os.mknod(testfile)
    assert m.check_for_file_changes() == True
    os.remove(testfile)

def test_get_files():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    num = m.get_number_of_files()
    assert num == 443 

def test_get_next_file():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    file1 = m.get_next_file()
    file2 = m.get_next_file()
    assert file1 != file2

def test_get_next_file_whole_loop():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    num = m.get_number_of_files()
    m.shuffle = False
    file1 = m.get_next_file()
    file2 = None
    for _ in range(0, num):
        file2 = m.get_next_file()
    assert file1 == file2

def test_get_next_file_no_file_in_range():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    file, orientation, image_attr = m.get_next_file((1990,1,1), (1990,1,2))
    assert file == '/home/pi/.local/picframe/data/PictureFrame2020img.jpg'
    assert orientation == 1
    assert image_attr == {
        'latitude':None,
        'longitude':None,
        'EXIF FNumber':None,
        'EXIF ExposureTime':None,
        'EXIF ISOSpeedRatings':None,
        'EXIF FocalLength':None,
        'EXIF DateTimeOriginal':None,
        'Image Model':None}

def test_get_file_for_empty_dir():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    m.subdirectory = 'testdir'
    file, orientation, image_attr  = m.get_next_file()
    assert file == '/home/pi/.local/picframe/data/PictureFrame2020img.jpg'
    assert orientation == 1
    assert image_attr == {
        'latitude':None,
        'longitude':None,
        'EXIF FNumber':None,
        'EXIF ExposureTime':None,
        'EXIF ISOSpeedRatings':None,
        'EXIF FocalLength':None,
        'EXIF DateTimeOriginal':None,
        'Image Model':None}

def test_getter_setter_fade_time():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    assert m.fade_time == 10.0
    m.fade_time = 20.0
    assert m.fade_time == 20.0

def test_getter_setter_time_delay():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    assert m.time_delay == 200.0
    m.time_delay = 21.0
    assert m.time_delay == 21.0

def test_getter_setter_subdirectory():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    assert m.subdirectory == ''
    m.subdirectory = 'testdir'
    assert m.subdirectory == 'testdir'

def test_getter_setter_shuffle():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    assert m.shuffle == True
    m.shuffle = False
    assert m.shuffle == False


def test_get_subdirectory_list():
    m = model.Model('/home/pi/dev/picture_frame/config/configuration.yaml')
    act_dir, dir_list = m.get_directory_list()
    assert act_dir == 'Pictures'
    assert dir_list[0] == 'Pictures'
    assert dir_list[1] == 'testdir'
