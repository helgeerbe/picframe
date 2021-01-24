import os
import json
import urllib.request
import locale
import logging

URL = "https://nominatim.openstreetmap.org/reverse?format=geojson&lat={}&lon={}&zoom={}&email={}&accept-language={}"

class GeoReverse:
    def __init__(self, geo_key, file_path, zoom=18, key_list=None):
        self.__logger = logging.getLogger("geo_reverse.GeoReverse")
        self.__geo_key = geo_key
        self.__zoom = zoom
        self.__key_list = key_list
        self.__file_path = file_path
        self.__geo_locations = {}
        if os.path.isfile(file_path):
            with open(file_path) as f:
                for line in f:
                    if line == '\n':
                        continue
                    (name, var) = line.partition('=')[::2]
                    self.__geo_locations[name] = var.rstrip('\n')
        self.__language = locale.getlocale()[0][:2]

    def get_address(self, lat, lon):
        lat_lon = "{},{}".format(lat, lon)
        if lat_lon in self.__geo_locations:
            return self.__geo_locations[lat_lon]
        else:
            try:
                with urllib.request.urlopen(URL.format(lat / 10000.0, lon / 10000.0, self.__zoom, self.__geo_key, self.__language)) as req:
                        data = json.loads(req.read().decode())
                adr = data['features'][0]['properties']['address']
                # some experimentation might be needed to get a good set of alternatives in key_list
                formatted_address = ""
                if self.__key_list is not None:
                    comma = ""
                    for part in self.__key_list:
                        for option in part:
                            if option in adr:
                                formatted_address = "{}{}{}".format(formatted_address, comma, adr[option])
                                comma = ", "
                                break # add just the first one from the options
                else:
                    formatted_address = ", ".join(adr.values())

                if len(formatted_address) > 0:
                    self.__geo_locations[lat_lon] = formatted_address
                    with open(self.__file_path, 'a+') as f:
                        f.write("{}={}\n".format(lat_lon, formatted_address))
                    return formatted_address
            except Exception as e:
                self.__logger.error(e)
                return "Location Not Available"
