import yaml
import os
import time
import logging
import random
import json
import locale
from picframe import geo_reverse, image_cache

DEFAULT_CONFIGFILE = "~/picframe_data/config/configuration.yaml"
DEFAULT_CONFIG = {
    'viewer': {
        'blur_amount': 12,
        'blur_zoom': 1.0,
        'blur_edges': False,
        'edge_alpha': 0.5,
        'fps': 20.0,
        'background': [0.2, 0.2, 0.3, 1.0],
        'blend_type': "blend", # {"blend":0.0, "burn":1.0, "bump":2.0}

        'font_file': '~/picframe_data/data/fonts/NotoSans-Regular.ttf',
        'shader': '~/picframe_data/data/shaders/blend_new',
        'show_text_fm': '%b %d, %Y',
        'show_text_tm': 20.0,
        'show_text_sz': 40,
        'show_text': "name location",
        'text_justify': 'L',
        'fit': False,
        #'auto_resize': True,
        'kenburns': False,
        'display_x': 0,
        'display_y': 0,
        'display_w': None,
        'display_h': None,
        'use_glx': False,                          # default=False. Set to True on linux with xserver running
        'test_key': 'test_value',
        'mat_images': True,
        'mat_type': None,
        'outer_mat_color': None,
        'inner_mat_color': None,
        'outer_mat_border': 75,
        'inner_mat_border': 40,
        'inner_mat_use_texture': False,
        'outer_mat_use_texture': True,
        'mat_resource_folder': '~/picframe_data/data/mat',
        #'codepoints': "1234567890AÄÀÆÅÃBCÇDÈÉÊEËFGHIÏÍJKLMNÑOÓÖÔŌØPQRSTUÚÙÜVWXYZaáàãæåäbcçdeéèêëfghiíïjklmnñoóôōøöpqrsßtuúüvwxyz., _-+*()&/`´'•" # limit to 121 ie 11x11 grid_size
    },
    'model': {

        'pic_dir': '~/Pictures',
        'no_files_img': '~/picframe_data/data/no_pictures.jpg',
        'subdirectory': '',
        'recent_n': 3,
        'reshuffle_num': 1,
        'time_delay': 200.0,
        'fade_time': 10.0,
        'shuffle': True,
        'sort_cols': 'fname ASC',
        'image_attr': ['PICFRAME GPS'],                          # image attributes send by MQTT, Keys are taken from exifread library, 'PICFRAME GPS' is special to retrieve GPS lon/lat
        'load_geoloc': True,
        'locale': 'en_US.utf8',
        'key_list': [['tourism','amenity','isolated_dwelling'],['suburb','village'],['city','county'],['region','state','province'],['country']],
        'geo_key': 'this_needs_to@be_changed',  # use your email address
        'db_file': '~/picframe_data/data/pictureframe.db3',
        'portrait_pairs': False,
        'deleted_pictures': '~/DeletedPictures',
        'log_level': 'WARNING',
        'use_kbd': False,
    },
    'mqtt': {
        'use_mqtt': False,                          # Set tue true, to enable mqtt
        'server': '',
        'port': 8883,
        'login': '',
        'password': '',
        'tls': '',
        'device_id': 'picframe',                                 # unique id of device. change if there is more than one picture frame
    },
    'http': {
        'use_http': False,
        'path': '~/picframe_data/html',
        'port': 9000,
        'use_ssl': False,
        'keyfile': "/path/to/key.pem",
        'certfile': "/path/to/fullchain.pem"
    }
}


class Pic: #TODO could this be done more elegantly with namedtuple

    def __init__(self, fname, last_modified, file_id, orientation=1, exif_datetime=0,
                 f_number=0, exposure_time=None, iso=0, focal_length=None,
                 make=None, model=None, lens=None, rating=None, latitude=None,
                 longitude=None, width=0, height=0, is_portrait=0, location=None, title=None,
                 caption=None, tags=None):
        self.fname = fname
        self.last_modified = last_modified
        self.file_id = file_id
        self.orientation = orientation
        self.exif_datetime = exif_datetime
        self.f_number = f_number
        self.exposure_time = exposure_time
        self.iso = iso
        self.focal_length = focal_length
        self.make = make
        self.model = model
        self.lens = lens
        self.rating = rating
        self.latitude = latitude
        self.longitude = longitude
        self.width = width
        self.height = height
        self.is_portrait = is_portrait
        self.location = location
        self.tags=tags
        self.caption=caption
        self.title=title


class Model:

    def __init__(self, configfile = DEFAULT_CONFIGFILE):
        self.__logger = logging.getLogger("model.Model")
        self.__logger.debug('creating an instance of Model')
        self.__config = DEFAULT_CONFIG
        self.__last_file_change = 0.0
        self.__required_db_schema_version = 1
        configfile = os.path.expanduser(configfile)
        self.__logger.info("Open config file: %s:",configfile)
        with open(configfile, 'r') as stream:
            try:
                conf = yaml.safe_load(stream)
                for section in ['viewer', 'model', 'mqtt', 'http']:
                    self.__config[section] = {**DEFAULT_CONFIG[section], **conf[section]}

                self.__logger.debug('config data = %s', self.__config)
            except yaml.YAMLError as exc:
                self.__logger.error("Can't parse yaml config file: %s: %s", configfile, exc)
        logging.getLogger().setLevel(self.get_model_config()['log_level']) # set root logger
        self.__file_list = [] # this is now a list of tuples i.e (file_id1,) or (file_id1, file_id2)
        self.__number_of_files = 0 # this is shortcut for len(__file_list)
        self.__reload_files = True
        self.__file_index = 0 # pointer to next position in __file_list
        self.__current_pics = (None, None) # this hold a tuple of (pic, None) or two pic objects if portrait pairs
        self.__num_run_through = 0

        model_config = self.get_model_config() # alias for brevity as used several times below
        try:
            locale.setlocale(locale.LC_TIME, model_config['locale'])
        except:
            self.__logger.error("error trying to set locale to {}".format(model_config['locale']))
        self.__pic_dir = os.path.expanduser(model_config['pic_dir'])
        self.__subdirectory = os.path.expanduser(model_config['subdirectory'])
        self.__load_geoloc = model_config['load_geoloc']
        self.__geo_reverse = geo_reverse.GeoReverse(model_config['geo_key'], key_list=self.get_model_config()['key_list'])
        self.__image_cache = image_cache.ImageCache(self.__pic_dir,
                                                    os.path.expanduser(model_config['db_file']),
                                                    self.__geo_reverse,
                                                    self.__required_db_schema_version,
                                                    model_config['portrait_pairs'])
        self.__deleted_pictures = model_config['deleted_pictures']
        self.__no_files_img = os.path.expanduser(model_config['no_files_img'])
        self.__sort_cols = model_config['sort_cols']
        self.__col_names = None
        self.__where_clauses = {} # these will be modified by controller

    def get_viewer_config(self):
        return self.__config['viewer']

    def get_model_config(self):
        return self.__config['model']

    def get_mqtt_config(self):
        return self.__config['mqtt']

    def get_http_config(self):
        return self.__config['http']

    @property
    def fade_time(self):
        return self.__config['model']['fade_time']

    @fade_time.setter
    def fade_time(self, time):
        self.__config['model']['fade_time'] = time

    @property
    def time_delay(self):
        return self.__config['model']['time_delay']

    @time_delay.setter
    def time_delay(self, time):
        self.__config['model']['time_delay'] = time

    @property
    def subdirectory(self):
        return self.__subdirectory

    @subdirectory.setter
    def subdirectory(self, dir):
        _, root = os.path.split(self.__pic_dir)
        actual_dir = root
        if self.subdirectory != '':
            actual_dir = self.subdirectory
        if actual_dir != dir:
            if root == dir:
                self.__subdirectory = ''
            else:
                self.__subdirectory = dir
            self.__logger.info("Set subdirectory to: %s", self.__subdirectory)
            self.__reload_files = True

    @property
    def EXIF_TO_FIELD(self): # bit convoluted TODO hold in config? not really configurable
        return self.__image_cache.EXIF_TO_FIELD

    @property
    def shuffle(self):
        return self.__config['model']['shuffle']

    @shuffle.setter
    def shuffle(self, val:bool):
        self.__config['model']['shuffle'] = val #TODO should this be altered in config?
        #if val == True:
        #    self.__shuffle_files()
        #else:
        #    self.__sort_files()
        self.__reload_files = True

    def set_where_clause(self, key, value=None):
        # value must be a string for later join()
        if (value is None or len(value) == 0):
            if key in self.__where_clauses:
                self.__where_clauses.pop(key)
            return
        self.__where_clauses[key] = value

    def pause_looping(self, val):
        self.__image_cache.pause_looping(val)

    def stop_image_chache(self):
        self.__image_cache.stop()

    def get_directory_list(self):
        _, root = os.path.split(self.__pic_dir)
        actual_dir = root
        if self.subdirectory != '':
            actual_dir = self.subdirectory
        subdir_list = next(os.walk(self.__pic_dir))[1]
        subdir_list[:] = [d for d in subdir_list if not d[0] == '.']
        subdir_list.insert(0,root)
        return actual_dir, subdir_list

    def force_reload(self):
        self.__reload_files = True

    def set_next_file_to_previous_file(self):
        self.__file_index = (self.__file_index - 2) % self.__number_of_files # TODO deleting last image results in ZeroDivisionError

    def get_next_file(self):
        if self.__reload_files:
            for _i in range(5): # give image_cache chance on first load if a large directory
                self.__get_files()
                if self.__number_of_files > 0:
                    break
                time.sleep(0.5)
        if self.__file_index == self.__number_of_files:
            self.__num_run_through += 1
            if self.shuffle and self.__num_run_through >= self.get_model_config()['reshuffle_num']:
                #self.__num_run_through = 0
                #self.__shuffle_files()
                self.__reload_files = True
            self.__file_index = 0
        if self.__number_of_files == 0:
            pic = Pic(self.__no_files_img, 0, 0)
            paired_pic = None
        else:
            file_ids = self.__file_list[self.__file_index]
            pic_row = self.__image_cache.get_file_info(file_ids[0])
            pic = Pic(**pic_row) if pic_row is not None else None
            if len(file_ids) == 2:
                pic_row = self.__image_cache.get_file_info(file_ids[1])
                paired_pic = Pic(**pic_row) if pic_row is not None else None
            else:
                paired_pic = None
        self.__current_pics = (pic, paired_pic)
        self.__file_index += 1 # don't wrap back as __file_index == __number_of_files used as trigger above
        return self.__current_pics

    def get_number_of_files(self):
        #return self.__number_of_files
        #return sum(1 for pics in self.__file_list for pic in pics if pic is not None)
        # or
        return sum(
                    sum(1 for pic in pics if pic is not None)
                        for pics in self.__file_list
                )

    def get_current_pics(self):
        return self.__current_pics

    def delete_file(self):
        # delete the current pic. If it's a portrait pair then only the left one will be deleted
        pic = self.__current_pics[0]
        if pic is None:
            return None
        f_to_delete = pic.fname
        move_to_dir = os.path.expanduser(self.__deleted_pictures)
        # TODO should these os system calls be inside a try block in case the file has been deleted after it started to show?
        if not os.path.exists(move_to_dir):
          os.system("mkdir {}".format(move_to_dir)) # problems with ownership using python func
        os.system("mv '{}' '{}'".format(f_to_delete, move_to_dir)) # and with SMB drives
        # find and delete record from __file_list
        for i, file_rec in enumerate(self.__file_list):
            if file_rec[0] == pic.file_id: # database id TODO check that db tidies itself up
                self.__file_list.pop(i)
                self.__number_of_files -= 1
                break

    def __get_files(self):
        if self.subdirectory != "":
            picture_dir = os.path.join(self.__pic_dir, self.subdirectory) # TODO catch, if subdirecotry does not exist
        else:
            picture_dir = self.__pic_dir
        where_list = ["fname LIKE '{}/%'".format(picture_dir)] # TODO / on end to stop 'test' also selecting test1 test2 etc
        where_list.extend(self.__where_clauses.values())

        if len(where_list) > 0:
            where_clause = " AND ".join(where_list) # TODO now always true - remove unreachable code
        else:
            where_clause = "1"

        sort_list = []
        recent_n = self.get_model_config()["recent_n"]
        if recent_n > 0:
            sort_list.append("last_modified < {:.0f}".format(time.time() - 3600 * 24 * recent_n))

        if self.shuffle:
            sort_list.append("RANDOM()")
        else:
            if self.__col_names is None:
                self.__col_names = self.__image_cache.get_column_names() # do this once
            for col in self.__sort_cols.split(","):
                colsplit = col.split()
                if colsplit[0] in self.__col_names and (len(colsplit) == 1 or colsplit[1].upper() in ("ASC", "DESC")):
                    sort_list.append(col)
            sort_list.append("fname ASC") # always finally sort on this in case nothing else to sort on or sort_cols is ""
        sort_clause = ",".join(sort_list)

        self.__file_list = self.__image_cache.query_cache(where_clause, sort_clause)
        self.__number_of_files = len(self.__file_list)
        self.__file_index = 0
        self.__num_run_through = 0
        self.__reload_files = False

    """def __shuffle_files(self):
        #self.__file_list.sort(key=lambda x: x[1]) # will be later files last
        recent_n = self.get_model_config()['recent_n']
        temp_list_first = self.__file_list[-recent_n:]
        temp_list_last = self.__file_list[:-recent_n]
        random.seed()
        random.shuffle(temp_list_first)
        random.shuffle(temp_list_last)
        self.__file_list = temp_list_first + temp_list_last

    def __sort_files(self):
        self.__file_list.sort() # if not shuffled; sort by name"""
