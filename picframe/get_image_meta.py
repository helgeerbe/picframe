import logging
import os
from PIL import Image
from PIL.Image import Exif
from PIL.ExifTags import TAGS, GPSTAGS
from pi_heif import register_heif_opener
from fractions import Fraction


register_heif_opener()

class GetImageMeta:

    def __init__(self, filename):
        self.__logger = logging.getLogger("get_image_meta.GetImageMeta")
        self.__tags = {}
        self.__filename = filename # in case no exif data in which case needed for size
        image = self.get_image_object(filename)
        if image:
            exif = image.getexif()
            self.__do_image_tags(exif)
            self.__do_exif_tags(exif)
            self.__do_geo_tags(exif)
            self.__do_iptc_keywords()
            try:
                xmp = image.getxmp()
                if len(xmp) > 0:
                    self.__do_xmp_keywords(xmp)
            except Exception as e:
                xmp = {}
                self.__logger.warning("PILL getxmp() failed: %s -> %s", filename, e)
                

    def __do_image_tags(self, exif):
        tags =  {
            "Image " + str(TAGS.get(key, key)): value
            for key, value in exif.items()
        }
        self.__tags.update(tags)

    def __do_exif_tags(self, exif):
        for key, value in TAGS.items():
            if value == "ExifOffset":
                break
        info = exif.get_ifd(key)
        tags =  {
            "EXIF " +  str(TAGS.get(key, key)): value
            for key, value in info.items()
        }
        self.__tags.update(tags)

    def __do_geo_tags(self, exif):
        for key, value in TAGS.items():
            if value == "GPSInfo":
                break
        gps_info = exif.get_ifd(key)
        tags =  {
            "GPS " + str(GPSTAGS.get(key, key)): value
            for key, value in gps_info.items()
        }
        self.__tags.update(tags)
    
    def __find_xmp_key(self, key, dic):
        for k, v in dic.items():
            if key == k:
                return v
            elif isinstance(v, dict):
                val = self.__find_xmp_key(key, v) 
                if val:
                    return val 
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, dict):
                        val = self.__find_xmp_key(key, x) 
                        if val:
                            return val 
        return None
    
    def __do_xmp_keywords(self, xmp):
        try:
            # title
            val = self.__find_xmp_key('Headline', xmp)
            if val and isinstance(val, str) and len(val) > 0:
                self.__tags['IPTC Object Name'] = val
            # caption
            try:
                val = self.__find_xmp_key('description', xmp)
                if val:
                    val = val['Alt']['li']['text']
                    if val and isinstance(val, str) and len(val) > 0:
                        self.__tags['IPTC Caption/Abstract'] = val
            except KeyError:
                pass
            # tags
            try: 
                val = self.__find_xmp_key('subject', xmp)
                if val:
                    val = val['Bag']['li']
                    if val and isinstance(val, list) and len(val) > 0:
                        tags = ''
                        for tag in val:
                            tags += tag +  ","
                        self.__tags['IPTC Keywords'] = tags 
            except KeyError:
                pass
        except Exception as e:
            self.__logger.warning("xmp loading has failed: %s -> %s", self.__filename, e)

    def __do_iptc_keywords(self):
        try:
            from iptcinfo3 import IPTCInfo
            iptcinfo_logger = logging.getLogger('iptcinfo') # turn off useless log infos
            iptcinfo_logger.setLevel(logging.ERROR)
            with open(self.__filename, 'rb') as fh:
                iptc = IPTCInfo(fh, force=True, out_charset='utf-8') # TODO put IPTC read in separate function
                # tags
                val = iptc['keywords']
                if val is not None and len(val) > 0:
                    keywords = ''
                    for key in iptc['keywords']:
                        keywords += key.decode('utf-8')  + ','  # decode binary strings
                    self.__tags['IPTC Keywords'] = keywords
                # caption
                val = iptc['caption/abstract']
                if val is not None and len(val) > 0:
                    self.__tags['IPTC Caption/Abstract'] = iptc['caption/abstract'].decode('utf8')
                # title
                val = iptc['object name']
                if val is not None and len(val) > 0:
                    self.__tags['IPTC Object Name'] = iptc['object name'].decode('utf-8')
        except Exception as e:
            self.__logger.warning("IPTC loading has failed - if you want to use this you will need to install iptcinfo3 %s -> %s",
                                  self.__filename, e)

    def has_exif(self):
        if self.__tags == {}:
            return False
        else:
            return True

    def __get_if_exist(self, key):
        if key in self.__tags:
            return self.__tags[key]
        return None

    def __convert_to_degrees(self, value):
        (deg, min, sec) = value
        return deg + (min / 60.0) + (sec / 3600.0)

    def get_location(self):
        gps = {"latitude": None, "longitude": None}
        lat = None
        lon = None

        gps_latitude = self.__get_if_exist('GPS GPSLatitude')
        gps_latitude_ref = self.__get_if_exist('GPS GPSLatitudeRef')
        gps_longitude = self.__get_if_exist('GPS GPSLongitude')
        gps_longitude_ref = self.__get_if_exist('GPS GPSLongitudeRef')

        try:
            if gps_latitude and gps_latitude_ref and gps_longitude and gps_longitude_ref:
                lat = self.__convert_to_degrees(gps_latitude)
                if len(gps_latitude_ref) > 0 and gps_latitude_ref[0] == 'S':
                    # assume zero length string means N
                    lat = 0 - lat
                gps["latitude"] = lat
                lon = self.__convert_to_degrees(gps_longitude)
                if len(gps_longitude_ref) and gps_longitude_ref[0] == 'W':
                    lon = 0 - lon
                gps["longitude"] = lon
        except Exception as e:
            self.__logger.warning("get_location failed on %s -> %s", self.__filename, e)
        return gps

    def get_orientation(self):
        try:
            val = self.__get_if_exist('Image Orientation')
            if val is not None:
                return val
            else:
                return 1
        except Exception as e:
            self.__logger.warning("get_orientation failed on %s -> %s", self.__filename, e)
            return 1

    def get_exif(self, key):
        try:
            iso_keys = ['EXIF ISOSpeedRatings', 'EXIF PhotographicSensitivity', 'EXIF ISO'] # ISO prior 2.2, ISOSpeedRatings 2.2, PhotographicSensitivity 2.3
            if key in iso_keys:
                for iso in iso_keys:
                    val = self.__get_if_exist(iso)
                    if val:
                        break
            else:
                val = self.__get_if_exist(key)

            if val is None:
                grp, tag = key.split(" ", 1)
                if grp == "EXIF":
                    newkey = "Image" + " " + tag
                    val = self.__get_if_exist(newkey)
                elif grp == "Image":
                    newkey = "EXIF" + " " + tag
                    val = self.__get_if_exist(newkey)
            if val:
                if key == "EXIF ExposureTime":
                    val = str(Fraction(val))
                elif key == "EXIF FocalLength":
                    val = str(val)
                elif key == "EXIF FNumber":
                    val = float(val)
                return val
        except Exception as e:
            self.__logger.warning("get_exif failed on %s -> %s", self.__filename, e)
            return None

    def get_size(self):
        try: # corrupt image file might crash app
            return GetImageMeta.get_image_object(self.__filename).size
        except Exception as e:
            self.__logger.warning("get_size failed on %s -> %s", self.__filename, e)
            return (0, 0)

    @staticmethod
    def get_image_object(fname):
        ext = os.path.splitext(fname)[1].lower()
        try:
            image = Image.open(fname)
            if image.mode not in ("RGB", "RGBA"): # mat system needs RGB or more
                image = image.convert("RGB")
        #raise # the system should be able to withstand files being moved etc without crashing
        except Exception as e:
            logger = logging.getLogger("get_image_meta.GetImageMeta")
            logger.warning("Can't open file: \"%s\"", fname)
            logger.warning("Cause: %s", e)
            image = None
        return image