#!/usr/bin/env python

import exifread
import logging

class Exif2Dict:


    def __init__(self, filename):
        self.__logger = logging.getLogger("exif2dict.Exif2Dict")
        self.__tags = {}
        try:
            with open(filename, 'rb') as fh:
                self.__tags = exifread.process_file(fh, details=False)
        except OSError as e:
            self.__logger.warning("Can't open file: \"%s\"", filename)
            self.__logger.warning("Cause: %s", e.args[1])
            raise

    def has_exif(self):
        if self.__tags == {}:
            return False
        else:
            return True

    def __get_if_exist(self, key):
        if key in self.__tags:
            return self.__tags[key]
        return None

    def __convert_to_degress(self, value):
        d = float(value.values[0].num) / float(value.values[0].den)
        m = float(value.values[1].num) / float(value.values[1].den)
        s = float(value.values[2].num) / float(value.values[2].den)
        return d + (m / 60.0) + (s / 3600.0)
        
    def get_locaction(self):
        gps = {"latitude": None, "longitude": None}
        lat = None
        lon = None

        gps_latitude = self.__get_if_exist('GPS GPSLatitude')
        gps_latitude_ref = self.__get_if_exist('GPS GPSLatitudeRef')
        gps_longitude = self.__get_if_exist('GPS GPSLongitude')
        gps_longitude_ref = self.__get_if_exist('GPS GPSLongitudeRef')

        if gps_latitude and gps_latitude_ref and gps_longitude and gps_longitude_ref:
            lat = self.__convert_to_degress(gps_latitude)
            if gps_latitude_ref.values[0] != 'N':
                lat = 0 - lat
            gps["latitude"] = lat
            lon = self.__convert_to_degress(gps_longitude)
            if gps_longitude_ref.values[0] != 'E':
                lon = 0 - lon
            gps["longitude"] = lon
        return gps
    
    def get_exif(self, key):
        exif = {}
        val = self.__get_if_exist(key)
        if val:
            if key == 'EXIF FNumber':
                val = val.values[0].num / val.values[0].den
            else:
                val = val.printable
        exif[key] = val
        return exif
