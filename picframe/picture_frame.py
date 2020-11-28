import logging
import sys


from picframe import model, viewer_display, controller



def main(): 
    logging.basicConfig(stream=sys.stdout, level=logging.WARNING)
    logger = logging.getLogger("picture_frame.py")
    logger.info('starting')
    m = model.Model()
    v = viewer_display.ViewerDisplay(m.get_viewer_config())
    c = controller.Controller(m, v)
    c.loop()
    
    

if __name__=="__main__": 
    main() 