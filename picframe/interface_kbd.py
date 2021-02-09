"""Keyboard interface of picture_frame."""

import logging
from pynput import keyboard
from picframe import __version__


class InterfaceKbd:
    """Keyboard interface of picture_frame.
    
    This interface interacts via keyboard with the user to steer the image display.

    Attributes
    ----------
    controller : Controler 
        Controller for picture_frame
   

    Methods
    -------

    """

    def __init__(self, controller):
        self.__logger = logging.getLogger("interface_kbd.InterfaceKbd")
        self.__logger.info('creating an instance of InterfaceKbd')
        self.__controller = controller
        listener = keyboard.Listener(
        on_press=self.on_press,
        on_release=self.on_release)
        listener.start()

    def on_press(self, key):
        try:
            print('alphanumeric key {0} pressed'.format(
                key.char))
        except AttributeError:
            print('special key {0} pressed'.format(
                key))

    def on_release(self, key):
        print('{0} released'.format(
            key))
        if key == keyboard.Key.esc:
            self.__controller.stop()
            # Stop listener
            return False
    