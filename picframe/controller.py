"""Controller of picframe."""

import logging
import time
import json
import os
import signal
import sys

def make_date(txt):
    dt = txt.replace('/',':').replace('-',':').replace(',',':').replace('.',':').split(':')
    dt_tuple = tuple(int(i) for i in dt) #TODO catch badly formed dates?
    return time.mktime(dt_tuple + (0, 0, 0, 0, 0, 0))

class Controller:
    """Controller of picframe.
    
    This controller interacts via mqtt with the user to steer the image display.

    Attributes
    ----------
    model : Model 
        model of picframe containing config and business logic
    viewer : ViewerDisplay
        viewer of picframe representing the display
   

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
        self.__date_from = make_date('1901/12/15') # TODO This seems to be the minimum date to be handled by date functions
        self.__date_to = make_date('2038/1/1')
        self.__location_filter = ""
        self.__where_clauses = {}
        self.__sort_clause = "exif_datetime ASC"
        self.publish_state = lambda x, y: None
        self.__keep_looping = True
        self.__location_filter = ''
        self.__tags_filter = ''
        self.__shutdown_complete = False

    @property
    def paused(self):
        """Get or set the current state for pausing image display. Setting paused to true
        will show the actual image as long paused is not set to false.
        """
        return self.__paused

    @paused.setter
    def paused(self, val:bool):
        self.__paused = val
        pic = self.__model.get_current_pics()[0] # only refresh left text
        self.__viewer.reset_name_tm(pic, val, side=0, pair=self.__model.get_current_pics()[1] is not None)

    def next(self):
        self.__next_tm = 0
        self.__viewer.reset_name_tm()

    def back(self):
        self.__model.set_next_file_to_previous_file()
        self.__next_tm = 0
        self.__viewer.reset_name_tm()

    def delete(self):
        self.__model.delete_file()
        self.back() # TODO check needed to avoid skipping one as record has been deleted from model.__file_list
        self.__next_tm = 0

    def set_show_text(self, txt_key=None, val="ON"):
        if val is True: # allow to be called with boolean from httpserver
            val = "ON"
        self.__viewer.set_show_text(txt_key, val)
        for (side, pic) in enumerate(self.__model.get_current_pics()):
            if pic is not None:
                self.__viewer.reset_name_tm(pic, self.paused, side, self.__model.get_current_pics()[1] is not None)

    def refresh_show_text(self):
        for (side, pic) in enumerate(self.__model.get_current_pics()):
            if pic is not None:
                self.__viewer.reset_name_tm(pic, self.paused, side, self.__model.get_current_pics()[1] is not None)

    @property
    def subdirectory(self):
        return self.__model.subdirectory

    @subdirectory.setter
    def subdirectory(self, dir):
        self.__model.subdirectory = dir
        self.__model.force_reload()
        self.__next_tm = 0

    @property
    def date_from(self):
        return self.__date_from

    @date_from.setter
    def date_from(self, val):
        try:
            self.__date_from = float(val)
        except ValueError:
            self.__date_from = make_date(val if len(val) > 0 else '1901/12/15')
        if len(val) > 0:
            self.__model.set_where_clause('date_from', "exif_datetime > {:.0f}".format(self.__date_from))
        else:
            self.__model.set_where_clause('date_from') # remove from where_clause
        self.__model.force_reload()
        self.__next_tm = 0

    @property
    def date_to(self):
        return self.__date_to

    @date_to.setter
    def date_to(self, val):
        try:
            self.__date_to = float(val)
        except ValueError:
            self.__date_to = make_date(val if len(val) > 0 else '2038/1/1')
        if len(val) > 0:
            self.__model.set_where_clause('date_to', "exif_datetime < {:.0f}".format(self.__date_to))
        else:
            self.__model.set_where_clause('date_to') # remove from where_clause
        self.__model.force_reload()
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
        self.__model.shuffle = val
        self.__model.force_reload()
        self.__next_tm = 0

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
        time = float(time) # convert string before comparison
        # might break it if too quick
        if time < 5.0:
            time = 5.0
        self.__model.time_delay = time
        self.__next_tm = 0

    @property
    def brightness(self):
        return self.__viewer.get_brightness()

    @brightness.setter
    def brightness(self, val):
        self.__viewer.set_brightness(float(val))

    @property
    def location_filter(self):
        return self.__location_filter

    @location_filter.setter
    def location_filter(self, val):
        self.__location_filter = val
        if len(val) > 0:
            self.__model.set_where_clause("location_filter", self.__build_filter(val, "location"))
        else:
            self.__model.set_where_clause("location_filter") # remove from where_clause
        self.__model.force_reload()
        self.__next_tm = 0

    @property
    def tags_filter(self):
        return self.__tags_filter

    @tags_filter.setter
    def tags_filter(self, val):
        self.__tags_filter = val
        if len(val) > 0:
            self.__model.set_where_clause("tags_filter", self.__build_filter(val, "tags"))
        else:
            self.__model.set_where_clause("tags_filter") # remove from where_clause
        self.__model.force_reload()
        self.__next_tm = 0

    def __build_filter(self, val, field):
        if val.count("(") != val.count(")"):
            return None # this should clear the filter and not raise an error
        val = val.replace(";", "").replace("'", "").replace("%", "").replace('"', '') # SQL scrambling
        tokens = ("(", ")", "AND", "OR", "NOT") # now copes with NOT
        val_split = val.replace("(", " ( ").replace(")", " ) ").split() # so brackets not joined to words
        filter = []
        last_token = ""
        for s in val_split:
            s_upper = s.upper()
            if s_upper in tokens:
                if s_upper in ("AND", "OR"):
                    if last_token in ("AND", "OR"):
                        return None # must have a non-token between
                    last_token = s_upper
                filter.append(s)
            else:
                if last_token is not None:
                    filter.append("{} LIKE '%{}%'".format(field, s))
                else:
                    filter[-1] = filter[-1].replace("%'", " {}%'".format(s))
                last_token = None
        return "({})".format(" ".join(filter)) # if OR outside brackets will modify the logic of rest of where clauses

    def text_is_on(self, txt_key):
        return self.__viewer.text_is_on(txt_key)

    def get_number_of_files(self):
        return self.__model.get_number_of_files()

    def get_directory_list(self):
        actual_dir, dir_list = self.__model.get_directory_list()
        return actual_dir, dir_list

    def get_current_path(self):
        (pic, _) = self.__model.get_current_pics()
        return pic.fname

    def loop(self): #TODO exit loop gracefully and call image_cache.stop()
        # catch ctrl-c
        signal.signal(signal.SIGINT, self.__signal_handler)

        #next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']
        while self.__keep_looping:

            #if self.__next_tm == 0: #TODO double check why these were set when next_tm == 0
            #    time_delay = 1 # must not be 0
            #    fade_time = 1 # must not be 0
            #else:
            time_delay = self.__model.time_delay
            fade_time = self.__model.fade_time

            tm = time.time()
            pics = None #get_next_file returns a tuple of two in case paired portraits have been specified
            if not self.paused and tm > self.__next_tm:
                self.__next_tm = tm + self.__model.time_delay
                pics = self.__model.get_next_file()
                if pics[0] is None:
                    self.__next_tm = 0 # skip this image file moved or otherwise not on db
                    pics = None # signal slideshow_is_running not to load new image
                else:
                    image_attr = {}
                    for key in self.__model.get_model_config()['image_attr']:
                        if key == 'PICFRAME GPS':
                            image_attr['latitude'] = pics[0].latitude
                            image_attr['longitude'] = pics[0].longitude
                        elif key == 'PICFRAME LOCATION':
                            image_attr['location'] = pics[0].location
                        else:
                            field_name = self.__model.EXIF_TO_FIELD[key]
                            image_attr[key] = pics[0].__dict__[field_name] #TODO nicer using namedtuple for Pic
                    self.publish_state(pics[0].fname, image_attr)
            if self.__viewer.is_in_transition() == False: # safe to do long running tasks
                self.__model.pause_looping(True)
            else:
                self.__model.pause_looping(False) #TODO only need to set this once rather than every loop
            (loop_running, skip_image) = self.__viewer.slideshow_is_running(pics, time_delay, fade_time, self.__paused)
            if not loop_running:
                break
            if skip_image:
                self.__next_tm = 0
        self.__shutdown_complete = True

    def start(self):
        self.__viewer.slideshow_start()

    def stop(self):
        self.__keep_looping = False
        while not self.__shutdown_complete:
            time.sleep(0.05) # block until main loop has stopped
        self.__model.stop_image_chache() # close db tidily (blocks till closed)
        self.__viewer.slideshow_stop() # do this last
    
    def __signal_handler(self, sig, frame):
        print('You pressed Ctrl-c!')
        self.__shutdown_complete = True
        self.stop()
