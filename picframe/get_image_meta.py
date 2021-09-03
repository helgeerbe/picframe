import exifread
import logging
import os
from PIL import Image

class GetImageMeta:

    def __init__(self, filename):
        self.__logger = logging.getLogger("get_image_meta.GetImageMeta")
        self.__tags = {}
        self.__filename = filename # in case no exif data in which case needed for size
        try:
            with open(filename, 'rb') as fh:
                self.__tags = exifread.process_file(fh, details=False)
        except OSError as e:
            self.__logger.warning("Can't open file: \"%s\"", filename)
            self.__logger.warning("Cause: %s", e)
            #raise # the system should be able to withstand files being moved etc without crashing
        except Exception as e:
            self.__logger.warning("exifread doesn't manage well and gives AttributeError for heif files %s -> %s",
                                  filename, e)
        self.__do_iptc_keywords()

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
        (deg, min, sec) = value.values
        d = float(deg.num) / float(deg.den if deg.den > 0 else 1) #TODO better catching?
        m = float(min.num) / float(min.den if min.den > 0 else 1)
        s = float(sec.num) / float(sec.den if sec.den > 0 else 1)
        return d + (m / 60.0) + (s / 3600.0)

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
                if len(gps_latitude_ref.values) > 0 and gps_latitude_ref.values[0] == 'S':
                    # assume zero length string means N
                    lat = 0 - lat
                gps["latitude"] = lat
                lon = self.__convert_to_degrees(gps_longitude)
                if len(gps_longitude_ref.values) and gps_longitude_ref.values[0] == 'W':
                    lon = 0 - lon
                gps["longitude"] = lon
        except Exception as e:
            self.__logger.warning("get_location failed on %s -> %s", self.__filename, e)
        return gps

    def get_orientation(self):
        try:
            val = self.__get_if_exist('Image Orientation')
            if val is not None:
                return int(val.values[0])
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
            if val is not None:
                if key == 'EXIF FNumber':
                    val = round(val.values[0].num / val.values[0].den, 1)
                elif key in ['IPTC Keywords',  'IPTC Caption/Abstract',  'IPTC Object Name']:
                    return val
                else:
                    val = val.printable
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
            if ext in ('.heif','.heic'):
                try:
                    import pyheif

                    heif_file = pyheif.read(fname)
                    image = Image.frombytes(heif_file.mode, heif_file.size, heif_file.data,
                                            "raw", heif_file.mode, heif_file.stride)
                    if image.mode not in ("RGB", "RGBA"):
                        image = image.convert("RGB")
                    return image
                except:
                    logger = logging.getLogger("get_image_meta.GetImageMeta")
                    logger.warning("Failed attempt to convert %s \n** Have you installed pyheif? **", fname)
            else:
                try:
                    image = Image.open(fname)
                    if image.mode not in ("RGB", "RGBA"): # mat system needs RGB or more
                        image = image.convert("RGB")
                except: # for whatever reason
                    image = None
                return image