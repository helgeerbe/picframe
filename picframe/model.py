import yaml
import os
import time
import logging
import random
import json
from picframe.get_image_meta import GetImageMeta
from picframe.geo_reverse import GeoReverse

DEFAULT_CONFIGFILE = "~/.local/picframe/config/configuration.yaml"
DEFAULT_CONFIG = {
    'viewer': {
        'blur_amount': 12,
        'blur_zoom': 1.0,  
        'blur_edges': False, 
        'edge_alpha': 0.5, 
        'fps': 20.0, 
        'background': [0.2, 0.2, 0.3, 1.0],  
        'blend_type': 0.0, # {"blend":0.0, "burn":1.0, "bump":2.0}
        'font_file': '~/.local/picframe/data/fonts/NotoSans-Regular.ttf', 
        'shader': '~/.local/picframe/data/shaders/blend_new', 
        'show_text_fm': '%b %d, %Y',
        'show_text_tm': 20.0,
        'show_text_sz': 40,
        'show_text': 14,
        'text_width': 90,
        'load_geoloc': True,
        'fit': False, 
        'auto_resize': True,
        'kenburns': False,
        'test_key': 'test_value'
    }, 
    'model': {
        'pic_dir': '~/Pictures', 
        'no_files_img': '~/.local/picframe/data/no_pictures.jpg',
        'subdirectory': '', 
        'check_dir_tm': 60.0, 
        'recent_n': 3, 
        'reshuffle_num': 1, 
        'time_delay': 200.0, 
        'fade_time': 10.0, 
        'shuffle': True,
        'image_attr': ['PICFRAME GPS'],                          # image attributes send by MQTT, Keys are taken from exifread library, 'PICFRAME GPS' is special to retrieve GPS lon/lat
        'load_geoloc': True,
        'locale': 'en_US.utf8',
        'key_list': [['tourism','amenity','isolated_dwelling'],['suburb','village'],['city','county'],['region','state','province'],['country']],
        'geo_key': 'this_needs_to@be_changed',  # use your email address
        'geo_file': './geo_locations.txt', #TODO sqlite alternative
        'file_list_cache': './file_list_cache.txt' #TODO sqlite altenative
    },
    'mqtt': {
        'server': '', 
        'port': 8883, 
        'login': '', 
        'password': '', 
        'tls': '',
        'device_id': 'picframe'                                 # unique id of device. change if there is more than one picture frame
    }
}
EXTENSIONS = ['.png','.jpg','.jpeg'] # can add to these


class Pic:

    def __init__(self, fname, orientation=1, mtime=None, dt=None, fdt=None, lat=None,
                 lon=None, aspect=1.5, shown_with=None, image_attr=None, location=None):
        self.fname = fname
        self.orientation = orientation
        self.mtime = mtime
        self.dt = dt
        self.fdt = fdt
        self.lat = lat # this is key to location desc record held as int(lat * 10000.0)
        self.lon = lon # this is key to location desc record held as int(lon * 10000.0)
        self.aspect = aspect
        self.shown_with = shown_with # set to pic_num of image this was paired with
        self.image_attr = image_attr
        self.location = None # use to pass to viewer but don't save in cache TODO check if this is best method
        # TODO this could be made JSON saveable by subclassing from dict and using
        # json.dumps(pic, default=lambda o : o.__dict__)
        # then deserialized pic = Pic(**json.loads(jsonpic))


class Model:

    def __init__(self, configfile = DEFAULT_CONFIGFILE):
        self.__logger = logging.getLogger("model.Model")
        self.__logger.debug('creating an instance of Model')
        self.__config = DEFAULT_CONFIG
        self.__last_file_change = 0.0
        configfile = os.path.expanduser(configfile)
        self.__logger.info("Open config file: %s:",configfile)
        with open(configfile, 'r') as stream:
            try:
                conf = yaml.safe_load(stream)
                for section in ['viewer', 'model', 'mqtt']:
                    self.__config[section] = {**DEFAULT_CONFIG[section], **conf[section]}
                self.__logger.debug('config data = %s', self.__config)
            except yaml.YAMLError as exc:
                self.__logger.error("Can't parse yaml config file: %s: %s", configfile, exc)
        self.__file_list = []
        self.__number_of_files = 0
        self.__reload_files = False
        self.__file_index = 0
        self.__num_run_through = 0
        self.__get_files()
        model_config = self.get_model_config() # alias for brevity as used several times below
        try:
            locale.setlocale(locale.LC_TIME, model_config['locale'])
        except:
            self.__logger.error("error trying to set locale to {}".format(model_config['locale']))
        self.__load_geoloc = model_config['load_geoloc']
        self.__geo_reverse = GeoReverse(model_config['geo_key'], model_config['geo_file'], key_list=self.get_model_config()['key_list'])
        file_path = model_config['file_list_cache']
        self.__file_list_cache = {}
        if os.path.isfile(file_path):
            with open(file_path) as f:
                for line in f:
                    if line == '\n':
                        continue
                    pic = Pic(**json.loads(line))
                    self.__file_list_cache[pic.fname] = pic


    def get_viewer_config(self):
        return self.__config['viewer']

    def get_model_config(self):
        return self.__config['model']
    
    def get_mqtt_config(self):
        return self.__config['mqtt']
    
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
        return self.__config['model']['subdirectory']
    
    @subdirectory.setter
    def subdirectory(self, dir):
        pic_dir = self.get_model_config()['pic_dir']
        _, root = os.path.split(pic_dir)
        actual_dir = root
        if self.subdirectory != '':
            actual_dir = self.subdirectory
        if actual_dir != dir:
            if root == dir:
                self.__config['model']['subdirectory'] = ''
            else:
                self.__config['model']['subdirectory'] = dir
            self.__logger.info("Set subdirectory to: %s", self.__config['model']['subdirectory'])
            self.__reload_files = True
    
    def get_directory_list(self):
        pic_dir = os.path.expanduser(self.get_model_config()['pic_dir'])
        _, root = os.path.split(pic_dir)
        actual_dir = root
        if self.subdirectory != '':
            actual_dir = self.subdirectory
        subdir_list = next(os.walk(pic_dir))[1]
        subdir_list.insert(0,root)
        return actual_dir, subdir_list
    
    @property
    def shuffle(self):
        return self.__config['model']['shuffle']
    
    @shuffle.setter
    def shuffle(self, val:bool):
        self.__config['model']['shuffle'] = val
        if val == True:
            self.__shuffle_files()
        else:
            self.__sort_files()
    
    def check_for_file_changes(self):
    # check modification time of pic_dir and its sub folders
        update = False
        pic_dir = os.path.expanduser(self.get_model_config()['pic_dir'])
        sub_dir = self.get_model_config()['subdirectory']
        picture_dir = os.path.join(pic_dir, sub_dir)
        for root, _, _ in os.walk(picture_dir):
            mod_tm = os.stat(root).st_mtime
            if mod_tm > self.__last_file_change:
                self.__last_file_change = mod_tm
                self.__logger.info('files changed in %s at %s', pic_dir, self.__last_file_change)
                update = True
        if update == True:
            self.__reload_files = True
        self.__logger.debug('Check for file changes = %s', update)
        return update
    
    def __get_image_date(self, file_path_name):
        file_path_name = os.path.expanduser(file_path_name)
        dt = os.path.getmtime(file_path_name) # use file last modified date as default
        try:
            exifs = GetImageMeta(file_path_name)
            val = exifs.get_exif('EXIF DateTimeOriginal')
            if val['EXIF DateTimeOriginal'] != None:
                dt = time.mktime(time.strptime(val['EXIF DateTimeOriginal'], '%Y:%m:%d %H:%M:%S'))
        except OSError as e:
            self.__logger.warning("Can't extract exif data from file: \"%s\"", file_path_name)
            self.__logger.warning("Cause: %s", e.args[1])
        return round(dt, 2) # 10ms saves storing lots of decimal places!

    def __get_image_attr(self, file_path_name):
        orientation = 1
        image_attr_list = {}
        try:
            exifs = GetImageMeta(file_path_name)
            orientation = exifs.get_orientation()
            size = exifs.get_size()
            for exif in self.get_model_config()['image_attr']:
                if (exif == 'PICFRAME GPS'):
                    image_attr_list.update(exifs.get_locaction())
                else:
                    image_attr_list.update(exifs.get_exif(exif))
        except OSError as e:
            self.__logger.warning("Can't extract exif data from file: \"%s\"", file_path_name)
            self.__logger.warning("Cause: %s", e.args[1])
        return size, orientation, image_attr_list

    def __get_files(self):
        self.__file_list = []
        picture_dir = os.path.join(os.path.expanduser(self.get_model_config()['pic_dir']), self.get_model_config()['subdirectory'])
        for root, _dirnames, filenames in os.walk(picture_dir):
            mod_tm = os.stat(root).st_mtime # time of alteration in a directory
            if mod_tm > self.__last_file_change:
                self.__last_file_change = mod_tm
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in EXTENSIONS and not '.AppleDouble' in root and not filename.startswith('.'):
                    file_path_name = os.path.join(root, filename)
                    # dt = self.__get_image_date(file_path_name)
                    # __file_list just holds file_path and mdate
                    self.__file_list.append([file_path_name, os.path.getmtime(file_path_name)])
        if len(self.__file_list) == 0:
            img = os.path.expanduser(self.get_model_config()['no_files_img'])
            mtime = os.path.getmtime(img)
            dt = self.__get_image_date(img)
            self.__file_list.append([img, mtime])
        else: 
            if self.get_model_config()['shuffle']:
                self.__shuffle_files()
            else:
                self.__sort_files()
        self.__number_of_files = len(self.__file_list)
        self.__file_index = 0
        self.__num_run_through = 0
        self.__reload_files = False

    def set_next_file_to_previous_file(self):
        self.__file_index = (self.__file_index - 2) % self.get_number_of_files()

    def get_next_file(self, date_from = None, date_to = None):
        if self.__reload_files == True:
            self.__get_files()

        if self.__file_index == self.__number_of_files:
            self.__num_run_through += 1
            if self.get_model_config()['shuffle'] and (self.__num_run_through >= self.get_model_config()['reshuffle_num']):
                self.__num_run_through = 0
                self.__shuffle_files()
            self.__file_index = 0

        found = False
        for _ in range(0,self.get_number_of_files()):
            (fname, mtime) = self.__file_list[self.__file_index]
            mtime = round(mtime, 2) # save space in cache
            if fname in self.__file_list_cache: #check cache first TODO use sqlite db
                pic = self.__file_list_cache[fname]
                pic.mtime = mtime # in case it's changed
            else: # exif info hasn't been extracted yet
                pic = Pic(fname, mtime=mtime)
                (w, h), orientation, image_attr = self.__get_image_attr(pic.fname)
                pic.orientation = orientation
                pic.image_attr = image_attr
                pic.aspect =  h / w if orientation == 6 or orientation == 8 else w / h
                pic.aspect = round(pic.aspect, 4) # accurate to 1 part in 10,000
                if ('latitude' in image_attr and 'longitude' in image_attr and
                    type(image_attr['latitude']) is float and type(image_attr['longitude']) is float):
                    pic.lat = int(image_attr['latitude'] * 10000.0 + 0.5) # hold as ints, used as keys in description table
                    pic.lon = int(image_attr['longitude'] * 10000.0 + 0.5)

                dt = self.__get_image_date(pic.fname)
                pic.dt = dt
                pic.fdt = time.strftime(self.get_viewer_config()['show_text_fm'], time.localtime(dt))
                self.__file_list_cache[pic.fname] = pic
                file_path = self.get_model_config()['file_list_cache']
                with open(file_path, 'a+') as f:
                    f.write(json.dumps(pic, default=lambda o : o.__dict__) + "\n")
            if date_from is not None:
                if pic.dt < date_from:
                    self.__file_index = (self.__file_index + 1) % self.get_number_of_files()
                    continue
            if date_to is not None:
                if pic.dt > date_to:
                    self.__file_index = (self.__file_index + 1) % self.get_number_of_files()
                    continue
            found = True
            #TODO check on mechanism for getting geo location description. At moment wait until pic has been selected
            if self.__load_geoloc and pic.lat is not None and pic.lon is not None:
                pic.location = self.__geo_reverse.get_address(pic.lat, pic.lon)
            break
        if not found: #TODO to get here requires every image to have exif extracted
            file = os.path.expanduser(self.get_model_config()['no_files_img'])
            return Pic(fname=file) # don't do exif lookup on no_files_img
        self.__file_index  += 1
        self.__logger.info('Next file in list: %s', pic.fname)
        self.__logger.debug('Image attributes: %s', pic.image_attr)
        return pic
        

    def __shuffle_files(self):
        self.__file_list.sort(key=lambda x: x[1]) # will be later files last
        recent_n = self.get_model_config()['recent_n']
        temp_list_first = self.__file_list[-recent_n:]
        temp_list_last = self.__file_list[:-recent_n]
        random.seed()
        random.shuffle(temp_list_first)
        random.shuffle(temp_list_last)
        self.__file_list = temp_list_first + temp_list_last

    def __sort_files(self):
        self.__file_list.sort() # if not shuffled; sort by name

    def get_number_of_files(self):
        return self.__number_of_files
