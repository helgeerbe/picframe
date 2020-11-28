import pytest
import logging

import sys
sys.path.append('/home/pi/picframe')


from picframe import model

logger = logging.getLogger("test_model")
logger.setLevel(logging.DEBUG)

def test_model_init():
    m = model.Model('/home/pi/dev/picframe/picframe/configuration.yaml')
    mqtt = m.get_mqtt_config()
    assert mqtt['server'] == 'home'
    viewer = m.get_viewer_config()
    assert viewer['test_key'] == 'test_value'
  

def test_for_file_changes():
    m = model.Model('/home/pi/dev/picframe/picframe/configuration.yaml')
    assert m.check_for_file_changes() == True
    assert m.check_for_file_changes() == False

def test_get_files():
    m = model.Model('/home/pi/dev/picframe/picframe/configuration.yaml')
    (files, num) = m.get_files()
    assert num == 443 # actual image folder 

def test_get_files_for_empty_dir():
    m = model.Model('/home/pi/dev/picframe/picframe/configuration.yaml')
    m.subdirectory = 'testdir'
    (files, num) = m.get_files()
    assert num == 1
    assert files[0][0] == '/home/pi/dev/picframe/picframe/PictureFrame2020img.jpg'

def test_getter_setter_fade_time():
    m = model.Model('/home/pi/dev/picframe/picframe/configuration.yaml')
    assert m.fade_time == 10.0
    m.fade_time = 20.0
    assert m.fade_time == 20.0

def test_getter_setter_time_delay():
    m = model.Model('/home/pi/dev/picframe/picframe/configuration.yaml')
    assert m.time_delay == 200.0
    m.time_delay = 21.0
    assert m.time_delay == 21.0

def test_getter_setter_subdirectory():
    m = model.Model('/home/pi/dev/picframe/picframe/configuration.yaml')
    assert m.subdirectory == ''
    m.subdirectory = 'testdir'
    assert m.subdirectory == 'testdir'

def test_getter_setter_shuffle():
    m = model.Model('/home/pi/dev/picframe/picframe/configuration.yaml')
    assert m.shuffle == True
    m.shuffle = False
    assert m.shuffle == False

def test_shuffle_files():
    m = model.Model('/home/pi/dev/picframe/picframe/configuration.yaml')
    (files1, num1) = m.get_files()
    (files2, num2) = m.get_files()
    m.shuffle_files(files1)
    assert num1 == num2 
    assert files1 != files2