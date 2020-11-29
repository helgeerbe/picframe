import logging
import time

class Controller:

    def __init__(self, model, viewer):
        self.__logger = logging.getLogger("controller.Controller")
        self.__logger.info('creating an instance of Controller')
        self.__model = model
        self.__viewer = viewer
    
    def loop(self):
        self.__viewer.slideshow_start()

        next_tm = time.time() + self.__model.time_delay
        next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']
        next_file = self.__model.get_next_file()
        
        while self.__viewer.slideshow_is_running(next_file, self.__model.time_delay, self.__model.fade_time):
            tm = time.time()
            next_file = None
            if tm > next_tm:
                next_tm = tm + self.__model.time_delay
                next_file = self.__model.get_next_file()
                
            if self.__viewer.is_in_transition() == False: # safe to do long running tasks
                if tm > next_check_tm:
                    self.__model.check_for_file_changes()
                    next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']

        self.__viewer.slideshow_stop()
        