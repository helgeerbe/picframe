#!/usr/bin/env python
# -*- coding: utf-8 -*-
import time
import os
import logging
import json
import threading
from functools import partial

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer #py3
    import urllib.parse as urlparse
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer #py2
    import urlparse

EXTENSIONS = [".jpg", ".jpeg", ".png", ".heif", ".heic"]

class RequestHandler(BaseHTTPRequestHandler):

    def __init__(self, pic_dir, no_files_img, controller, *args, **kwargs):
            self._pic_dir = pic_dir
            self._no_files_img = no_files_img
            self._controller = controller
            # BaseHTTPRequestHandler calls do_GET **inside** __init__ !!!
            # So we have to call super().__init__ after setting attributes.
            super().__init__(*args, **kwargs)

    def do_GET(self):
        try:
            path_split = self.path.split("?")
            page_ok = False
            if len(path_split) == 1: # i.e. no ? - just serve index.html or image
                if path_split[0] != "/": # serve static page from html_path...
                    html_page = path_split[0].strip("/")
                else:
                    html_page = "index.html"
                _, extension = os.path.splitext(html_page)
                if extension.lower() in EXTENSIONS:
                    # load only images that are located in the actual seleced path
                    page = self._pic_dir
                    if self._controller.subdirectory != '':
                        page = os.path.join(page, self._controller.subdirectory)
                    _, image = os.path.split(html_page)
                    image = urlparse.unquote(image)
                    page = os.path.join(page, image)
                    if not os.path.isfile(page):
                        page = self._no_files_img
                    content_type = "image" #TODO send MIME subtypes?
                else:
                    page = os.path.join(self.server._html_path, html_page)
                    content_type = "text/html"
                page = urlparse.unquote(page)
                if os.path.isfile(page):
                    self.send_response(200)
                    self.send_header('Content-type', content_type)
                    #TODO check if html or js - in which case application/javascript
                    # really should filter out attempts to render all other file types (jpg etc?)
                    self.end_headers()
                    with open(page, "rb") as f:
                        page_bytes = f.read()
                        self.wfile.write(page_bytes)
                    self.connection.close()
                    page_ok = True
            else: # server type request - get or set info
                start_time = time.time()
                message = {}
                self.send_response(200)
                self.server._logger.debug('http request from: ' + self.client_address[0])

                for key, value in dict(urlparse.parse_qsl(path_split[1], True)).items():
                    self.send_header('Content-type', 'text')
                    self.end_headers()
                    if key == "all":
                        for subkey in self.server._setters:
                            message[subkey] = getattr(self.server._controller, subkey)
                    elif key in dir(self.server._controller):
                        if key in self.server._setters: # can info back from controller
                            message[key] = getattr(self.server._controller, key)
                        lwr_val = value.lower()
                        if lwr_val in ("true", "on", "yes"): # this only works for simple values *not* json style kwargs
                            value = True
                        elif lwr_val in ("false", "off", "no"):
                            value = False
                        try:
                            if key in self.server._setters:
                                setattr(self.server._controller, key, value)
                            else:
                                value = value.replace("\'", "\"") # only " permitted in json
                                # value must be json kwargs
                                getattr(self.server._controller, key)(**json.loads(value))
                        except Exception as e:
                            message['ERROR'] = 'Excepton:{}>{};'.format(key, e)

                    self.wfile.write(bytes(json.dumps(message), "utf8"))
                    self.connection.close()
                    page_ok = True

                self.server._logger.info(message)
                self.server._logger.debug("request finished in:  %s seconds" %
                              (time.time() - start_time))
            if not page_ok:
                self.send_response(404)
                self.connection.close()
        except Exception as e:
            self.server._logger.warning(e)
            self.send_response(400)
            self.connection.close()

        return


    def log_request(self, code):
        pass


    def do_POST(self):
        self.do_GET()


    def end_headers(self):
        try:
            super().end_headers()
        except BrokenPipeError as e:
            self.connection.close()
            self.server._logger.error('httpserver error: {}'.format(e))


class InterfaceHttp(HTTPServer):
    def __init__(self, controller, html_path, pic_dir, no_files_img, port=9000):
        handler = partial(RequestHandler, os.path.expanduser(pic_dir), os.path.expanduser(no_files_img), controller)
        super(InterfaceHttp, self).__init__(("0.0.0.0", port), handler)
        # NB name mangling throws a spanner in the works here!!!!!
        # *no* __dunders
        self._logger = logging.getLogger("simple_server.InterfaceHttp")
        self._logger.info("creating an instance of InterfaceHttp")
        self._controller = controller
        self._html_path = os.path.expanduser(html_path)
        self._setters = ["paused", "subdirectory", "date_from", "date_to",
                         "display_is_on", "shuffle", "fade_time", "time_delay",
                         "brightness", "location_filter"] #TODO can this be done with dir() and getattr() to avoid hard coding?
        self.__keep_looping = True
        t = threading.Thread(target=self.__loop)
        t.start()

    def __loop(self):
        while self.__keep_looping:
            self.handle_request()
            time.sleep(0.1)

    def stop(self):
        self.__keep_looping = False
