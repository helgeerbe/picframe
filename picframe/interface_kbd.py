"""Keyboard interface of picframe."""

import logging
import threading
import time
import pi3d


class InterfaceKbd:
    """Keyboard interface of picframe.
    
    This interface interacts via keyboard with the user to steer the image display.

    Attributes
    ----------
    controller : Controler 
        Controller for picframe
   

    Methods
    -------

    """

    def __init__(self, controller):
        self.__logger = logging.getLogger("interface_kbd.InterfaceKbd")
        self.__logger.info('creating an instance of InterfaceKbd')
        self.__controller = controller
        self.__keyboard = pi3d.Keyboard()
        self.__keep_looping = True
        t = threading.Thread(target=self.__loop)
        t.start()

    def __loop(self):
        while self.__keep_looping:
            key = self.__keyboard.read()
            if key == 27:
                self.__keep_looping = False
            elif key == ord('a'):
                self.__controller.back()
            elif key == ord('d'):
                self.__controller.next()
            elif key == ord('l'):
                if self.__controller.text_is_on("location"):
                    self.__controller.set_show_text("location", "OFF")
                else:
                    self.__controller.set_show_text("location", "ON")
            time.sleep(0.025)
        self.__keyboard.close() # contains references to Display instance
        self.__controller.stop()
    