"""Controller of picture_frame."""

import logging
import time
import json
import os

def make_date(txt):
    dt = txt.replace('/',':').replace('-',':').replace(',',':').replace('.',':').split(':')
    dt_tuple = tuple(int(i) for i in dt) #TODO catch badly formed dates?
    return time.mktime(dt_tuple + (0, 0, 0, 0, 0, 0))

class Controller:
    """Controller of picture_frame.
    
    This controller interacts via mqtt with the user to steer the image display.

    Attributes
    ----------
    model : Model 
        model of picture_frame containing config and business logic
    viewer : ViewerDisplay
        viewer of picture_frame representing the display
   

    Methods
    -------
    paused
        Getter and setter for pausing image display.
    next
        Show next image.
    back
        Show previous image.

    """

    def __init__(self, model, viewer):
        self.__logger = logging.getLogger("controller.Controller")
        self.__logger.info('creating an instance of Controller')
        self.__model = model
        self.__viewer = viewer
        self.__paused = False
        self.__next_tm = 0
        self.__date_from = make_date('1970/1/1')
        self.__date_to = make_date('2038/1/1')
        self.publish_state = None

    @property
    def paused(self):
        """Get or set the current state for pausing image display. Setting paused to true
        will show the actual image as long paused is not set to false.
        """
        return self.__paused

    @paused.setter
    def paused(self, val:bool):
        self.__paused = val
        if val == True:
            pic = self.__model.get_current_pics()[0]
            self.__viewer.reset_name_tm(pic, val)

    def next(self):
        self.__next_tm = 0
        self.__viewer.reset_name_tm()

    def back(self):
        self.__model.set_next_file_to_previous_file()
        self.__next_tm = 0
        self.__viewer.reset_name_tm()
    
    def back(self):
        self.__model.delete_file()
        self.back() # TODO check needed to avoid skipping one as record has been deleted from model.__file_list
        self.__next_tm = 0
        #TODO rebuild portait pairs as numbers don't match
    
    def set_show_text(self, txt_key=None, val="ON"):
        self.__viewer.set_show_text(txt_key, val)
        pic = self.__model.get_current_pics()[0]
        self.__viewer.reset_name_tm(pic, self.paused)
    
    def refresh_show_text(self):
        pic = self.__model.get_current_pics()[0]
        self.__viewer.reset_name_tm(pic, self.paused)
    
    @property
    def subdirectory(self):
        return self.__model.subdirectory

    @subdirectory.setter
    def subdirectory(self, dir):
        self.__model.subdirectory = dir
        self.__next_tm = 0

    @property
    def date_from(self):
        return self.__date_from

    @date_from.setter
    def date_from(self, val):
        try:
            self.__date_from = float(val)
        except ValueError:
            if len(val) == 0:
                val = '1970/1/1'
            self.__date_from = make_date(val)
        self.__next_tm = 0

    @property
    def date_to(self):
        return self.__date_to

    @date_to.setter
    def date_to(self, val):
        try:
            self.__date_to = float(val)
        except ValueError:
            if len(val) == 0:
                val = '2038/1/1'
            self.__date_to = make_date(val)
        self.__next_tm = 0

    @property
    def display_is_on(self):
        return self.__viewer.display_is_on

    @display_is_on.setter
    def display_is_on(self, on_off):
        self.__viewer.display_is_on = on_off

    @property
    def shuffle(self):
        return self.__model.shuffle

    @shuffle.setter
    def shuffle(self, val:bool):
        self.__model.shuffle = bool
        if val == True:
            self.__viewer.reset_name_tm()
    
    @property
    def fade_time(self):
        return self.__model.fade_time

    @fade_time.setter
    def fade_time(self, time):
        self.__model.fade_time = float(time)
        self.__next_tm = 0

    @property
    def time_delay(self):
        return self.__model.time_delay
    
    @time_delay.setter
    def time_delay(self, time):
        self.__model.time_delay = float(time)
        self.__next_tm = 0
    
    def text_is_on(self, txt_key):
        return self.__viewer.text_is_on(txt_key)
    
    def set_brightness(self, val):
        self.__viewer.set_brightness(float(val))
    
    def get_number_of_files(self):
        self.__model.get_number_of_files()
    
    def get_directory_list(self):
        actual_dir, dir_list = self.__model.get_directory_list()
        return actual_dir, dir_list

    def loop(self):
        next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']
        while True:

            if self.__next_tm == 0:
                time_delay = 1 # must not be 0
                fade_time = 1 # must not be 0
            else:
                time_delay = self.__model.time_delay
                fade_time = self.__model.fade_time

            tm = time.time()
            pics = None #get_next_file returns a tuple of two in case paired portraits have been specified
            if not self.paused and tm > self.__next_tm:
                self.__next_tm = tm + self.__model.time_delay
                pics = self.__model.get_next_file(self.date_from, self.date_to)
                if self.publish_state != None:
                    self.publish_state(pics[0].fname, pics[0].image_attr)
            if self.__viewer.is_in_transition() == False: # safe to do long running tasks
                if tm > next_check_tm:
                    self.__model.check_for_file_changes()
                    next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']
            if self.__viewer.slideshow_is_running(pics, time_delay, fade_time, self.__paused) == False:
                break


    def start(self):
        self.__viewer.slideshow_start()

    def stop(self):
        self.__viewer.slideshow_stop()
