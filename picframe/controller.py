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
        file_list, number_of_files = self.__model.get_files()
        actual_index = 0
        new_file = file_list[actual_index][0]
        num_run_through = 0
        reshuffle_num = self.__model.get_model_config()['reshuffle_num']
        next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']
        
        while self.__viewer.slideshow_is_running(new_file, self.__model.time_delay, self.__model.fade_time):
            tm = time.time()
            new_file = None
            if tm > next_tm:
                next_tm = tm + self.__model.time_delay
                actual_index += 1
                if actual_index < number_of_files:
                    new_file = file_list[actual_index][0]
                else:
                    num_run_through += 1
                    if self.__model.shuffle and (num_run_through >= reshuffle_num):
                        num_run_through = 0
                        self.__model.shuffle_files(file_list)
                    actual_index = 0
            
            if self.__viewer.is_in_transition() == False: # safe to do longrunning tasks
                if tm > next_check_tm:
                    if self.__model.check_for_file_changes():
                        file_list, number_of_files = self.__model.get_files()
                        num_run_through = 0
                        actual_index = 0
                    next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']


        self.__viewer.slideshow_stop()
        