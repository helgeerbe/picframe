
import logging

from  picframe import viewer_display, model

logger = logging.getLogger("test_viewer_display")
logger.setLevel(logging.DEBUG)

def test_model_init():
    m = model.Model('/home/pi/dev/picframe/picframe/configuration.yaml')
    viewer_config = m.get_viewer_config()
    model_config = m.get_model_config()
    viewer = viewer_display.ViewerDisplay(viewer_config)
    viewer.slideshow_start()
    viewer.slideshow_is_running(model_config['no_files_img'])
    assert True == True