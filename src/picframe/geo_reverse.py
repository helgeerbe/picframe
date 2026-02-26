import json
import urllib.request
import locale
import logging
import time

#
# Looked into
# - https://operations.osmfoundation.org/policies/nominatim/
#
# Actions:
#  A. Nominatim wants you to use an application specific User-Agent, so here we are:
#  B. Enforce the Nominatim timing requirement
#
URL = "https://nominatim.openstreetmap.org/reverse?format=geojson&lat={}&lon={}&zoom={}&email={}&accept-language={}"
HEADERS = {
    # fake? 'User-Agent' : 'Mozilla/5.0 (X11; Linux x86_64; rv:147.0) Gecko/20100101 Firefox/147.0',
    # A. Application agent
    'User-Agent' : 'Picframe-the-DIY-software patched by InI4',
    # 'Accept'     : '*/*',
    # 'Accept-Encoding' : 'gzip, deflate, br, zstd',
    # 'Accept-Encoding' : 'zstd',
    # 'Accept-Language' : 'en-US,en;q=0.9'
}
MINIMUM_INTERVAL = 2.0 # Actually 1.0 is ok, just to be kind

class GeoReverse:
    def __init__(self, geo_key, zoom=18, key_list=None):
        self.__logger = logging.getLogger("geo_reverse.GeoReverse")
        self.__geo_key = geo_key
        self.__zoom = zoom
        self.__key_list = key_list
        self.__language = locale.getlocale()[0][:2]
        self.__lastRequest = 0 # FSN properly distance the request

    def get_address(self, lat, lon):
        url = URL.format(lat, lon, self.__zoom, self.__geo_key, self.__language)

        # B. Enforce the Nominatim timing requirement
        dt = time.time() - self.__lastRequest
        if dt < MINIMUM_INTERVAL :
            dt = MINIMUM_INTERVAL - dt
            self.__logger.warning("Sleep %.3f", dt)
            time.sleep(dt)

        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=30.0) as req:
                self.__lastRequest = time.time()
                data = json.loads(req.read().decode())
            adr = data['features'][0]['properties']['address']

            # some experimentation might be needed to get a good set of alternatives in key_list
            adr_list = []
            if self.__key_list is not None:
                for part in self.__key_list:
                    for option in part:
                        if option in adr:
                            adr_list.append(adr[option])
                            break  # add just the first one from the options
            else:
                adr_list = adr.values()
            return ", ".join(adr_list)
        except Exception as e:  # TODO return different thing for different exceptions
            self.__logger.error("lat=%f, lon=%f -> %s", lat, lon, e)
            return ""

