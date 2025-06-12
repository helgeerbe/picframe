"""Controller of picframe."""

import logging
import time
import signal
import sys
import ssl


def make_date(txt):
    dt = (txt.replace('/', ':')
          .replace('-', ':')
          .replace(',', ':')
          .replace('.', ':')
          .split(':'))
    dt_tuple = tuple(int(i) for i in dt)  # TODO catch badly formed dates?
    return time.mktime(dt_tuple + (0, 0, 0, 0, 0, 0))


class Controller:
    """Controller of picframe.

    This controller interacts via mqtt with the user to steer the image
    display.

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
        self.__logger.setLevel(model.get_model_config()['log_level']) # set controller logger to model level
        self.__logger.info('creating an instance of Controller')
        self.__model = model
        self.__viewer = viewer
        self.__http_config = self.__model.get_http_config()
        self.__mqtt_config = self.__model.get_mqtt_config()
        self.__paused = False
        self.__force_navigate = False
        self.__next_tm = 0
        self.__date_from = make_date('1901/12/15')  # TODO This seems to be the minimum date to be handled by date functions  # noqa: E501
        self.__date_to = make_date('2038/1/1')
        self.__where_clauses = {}
        self.__sort_clause = "exif_datetime ASC"
        self.publish_state = lambda x, y: None
        self.keep_looping = True
        self.__interface_peripherals = None
        self.__interface_mqtt = None
        self.__interface_http = None

    @property
    def paused(self):
        """Get or set the current state for pausing image display.
        Setting paused to true will show the actual image as long
        paused is not set to false.
        """
        return self.__paused

    @paused.setter
    def paused(self, val: bool):
        self.__paused = val
        if self.__viewer.is_video_playing():
            self.__viewer.pause_video(val)
        pic = self.__model.get_current_pics()[0]  # only refresh left text
        self.__viewer.reset_name_tm(pic, val, side=0, pair=self.__model.get_current_pics()[1] is not None)
        if self.__mqtt_config['use_mqtt']:
            self.publish_state()

    def next(self):
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
            self.__next_tm = 0
        self.__viewer.reset_name_tm()
        self.__force_navigate = True

    def back(self):
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
            self.__next_tm = 0
        self.__model.set_next_file_to_previous_file()
        self.__viewer.reset_name_tm()
        self.__force_navigate = True

    def delete(self):
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
            self.__next_tm = 0
        self.__model.delete_file()
        self.next()  # TODO check needed to avoid skipping one as record has been deleted from model.__file_list

    def set_show_text(self, txt_key=None, val="ON"):
        if val is True:  # allow to be called with boolean from httpserver
            val = "ON"
        self.__viewer.set_show_text(txt_key, val)
        for (side, pic) in enumerate(self.__model.get_current_pics()):
            if pic is not None:
                self.__viewer.reset_name_tm(pic, self.paused, side, self.__model.get_current_pics()[1] is not None)

    def refresh_show_text(self):
        for (side, pic) in enumerate(self.__model.get_current_pics()):
            if pic is not None:
                self.__viewer.reset_name_tm(pic, self.paused, side, self.__model.get_current_pics()[1] is not None)

    def purge_files(self):
        self.__model.purge_files()

    @property
    def subdirectory(self):
        return self.__model.subdirectory

    @subdirectory.setter
    def subdirectory(self, dir):
        self.__model.subdirectory = dir
        self.__model.force_reload()
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
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
            # remove from where_clause
            self.__model.set_where_clause('date_from')
        self.__model.force_reload()
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
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
            self.__model.set_where_clause('date_to')  # remove from where_clause
        self.__model.force_reload()
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
            self.__next_tm = 0

    @property
    def display_is_on(self):
        return self.__viewer.display_is_on

    @display_is_on.setter
    def display_is_on(self, on_off):
        self.paused = not on_off
        self.__viewer.display_is_on = on_off
        if self.__mqtt_config['use_mqtt']:
            self.publish_state()

    @property
    def clock_is_on(self):
        return self.__viewer.clock_is_on

    @clock_is_on.setter
    def clock_is_on(self, on_off):
        self.__viewer.clock_is_on = on_off

    @property
    def shuffle(self):
        return self.__model.shuffle

    @shuffle.setter
    def shuffle(self, val: bool):
        self.__model.shuffle = val
        self.__model.force_reload()
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
            self.__next_tm = 0
        if self.__mqtt_config['use_mqtt']:
            self.publish_state()

    @property
    def fade_time(self):
        return self.__model.fade_time

    @fade_time.setter
    def fade_time(self, time):
        self.__model.fade_time = float(time)
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
            self.__next_tm = 0

    @property
    def time_delay(self):
        return self.__model.time_delay

    @time_delay.setter
    def time_delay(self, time):
        time = float(time)  # convert string before comparison
        # might break it if too quick
        if time < 5.0:
            time = 5.0
        self.__model.time_delay = time
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
            self.__next_tm = 0

    @property
    def brightness(self):
        return self.__viewer.get_brightness()

    @brightness.setter
    def brightness(self, val):
        self.__viewer.set_brightness(float(val))
        if self.__mqtt_config['use_mqtt']:
            self.publish_state()

    @property
    def matting_images(self):
        return self.__viewer.get_matting_images()

    @matting_images.setter
    def matting_images(self, val):
        self.__viewer.set_matting_images(float(val))
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
            self.__next_tm = 0

    @property
    def location_filter(self):
        return self.__model.location_filter

    @location_filter.setter
    def location_filter(self, val):
        self.__model.location_filter = val
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
            self.__next_tm = 0

    @property
    def tags_filter(self):
        return self.__model.tags_filter

    @tags_filter.setter
    def tags_filter(self, val):
        self.__model.tags_filter = val
        if self.__viewer.is_video_playing():
            self.__viewer.stop_video()
        else:
            self.__next_tm = 0

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

    def loop(self):  # TODO exit loop gracefully and call image_cache.stop()
        # catch ctrl-c
        signal.signal(signal.SIGINT, self.__signal_handler)

        video_extended = False
        while self.keep_looping:
            time_delay = self.__model.time_delay
            fade_time = self.__model.fade_time

            tm = time.time()
            pics = None  # get_next_file returns a tuple of two in case paired portraits have been specified
            if not self.paused and tm > self.__next_tm or self.__force_navigate:
                self.__next_tm = tm + self.__model.time_delay
                self.__force_navigate = False
                pics = self.__model.get_next_file()
                self.__logger.info('NEXT file: %s', pics[0].fname if pics and len(pics) > 0 else 'None')
                if pics[0] is None:
                    self.__next_tm = 0  # skip this image file moved or otherwise not on db
                    pics = None  # signal slideshow_is_running not to load new image
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
                            image_attr[key] = pics[0].__dict__[field_name]  # TODO nicer using namedtuple for Pic
                    if self.__mqtt_config['use_mqtt']:
                        self.publish_state(pics[0].fname, image_attr)
            self.__model.pause_looping = self.__viewer.is_in_transition()
            (loop_running, skip_image, video_playing) = self.__viewer.slideshow_is_running(pics, time_delay, fade_time, self.__paused)
            if not loop_running:
                break
            if skip_image or (video_extended and not video_playing):
                self.__next_tm = 0
                video_extended = False
            if video_playing:
                video_extended = True
            self.__interface_peripherals.check_input()

    def start(self):
        self.__viewer.slideshow_start()
        from picframe.interface_peripherals import InterfacePeripherals
        self.__interface_peripherals = InterfacePeripherals(self.__model, self.__viewer, self)

        # start mqtt
        if self.__mqtt_config['use_mqtt']:
            from picframe import interface_mqtt
            try:
                self.__interface_mqtt = interface_mqtt.InterfaceMQTT(self, self.__mqtt_config)
            except Exception as e:
                self.__logger.error("Can't initialize MQTT: %s. Continuing without MQTT.", e)
                self.__interface_mqtt = None

        # start http server
        if self.__http_config['use_http']:
            from picframe import interface_http
            model_config = self.__model.get_model_config()
            self.__interface_http = interface_http.InterfaceHttp(
                                                                    self,
                                                                    self.__http_config['path'],
                                                                    model_config['pic_dir'],
                                                                    model_config['no_files_img'],
                                                                    self.__http_config['port'],
                                                                    self.__http_config['auth'],
                                                                    self.__http_config['username'],
                                                                    self.__http_config['password'],
                                                                )  # TODO: Implement TLS
            if self.__http_config['use_ssl']:
                self.__interface_http.socket = ssl.wrap_socket(
                                                self.__interface_http.socket,
                                                keyfile=self.__http_config['keyfile'],
                                                certfile=self.__http_config['certfile'],
                                                server_side=True)

    def stop(self):
        self.keep_looping = False
        self.__interface_peripherals.stop()
        if self.__interface_mqtt:
            self.__interface_mqtt.stop()
        if self.__interface_http:
            self.__interface_http.stop()
        self.__model.stop_image_cache()  # close db tidily (blocks till closed)
        self.__viewer.slideshow_stop()  # do this last

    def __signal_handler(self, sig, frame):
        if sig == signal.SIGINT:
            self.__logger.info('Ctrl-c pressed, stopping picframe...')
        else:
            self.__logger.warning('Signal %s received, stopping picframe...', sig)
        print('You pressed Ctrl-c!')
        self.keep_looping = False
