#!/usr/bin/env python
# -*- coding: utf-8 -*-
import time
import os
import logging
import json
import threading
import base64
import io
from PIL import Image

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer  # py3
    import urllib.parse as urlparse
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer  # py2
    import urlparse

try:
    from pi_heif import register_heif_opener
except ImportError:
    register_heif_opener = None

EXTENSIONS = [".jpg", ".jpeg", ".png"]
EXTENSION_TO_MIMETYPE = {
    # Videos
    '.mp4': 'video/mp4',
    '.mkv': 'video/x-matroska',
    '.flv': 'video/x-flv',
    '.mov': 'video/quicktime',
    '.avi': 'video/x-msvideo',
    '.webm': 'video/webm',
    '.hevc': 'video/mp4',  # HEVC usually wrapped in MP4 container

    # Images
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png'
}
if register_heif_opener is not None:
    EXTENSIONS += [".heif", ".heic"]
    EXTENSION_TO_MIMETYPE.update({
        '.heif': 'image/heif',
        '.heic': 'image/heic'
    })

def heif_to_jpg(fname):
    try:
        try:
            from pi_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            register_heif_opener = None

        image = Image.open(fname)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="JPEG")  # default 75% quality
        buf.seek(0)
        return buf.read()
    except Exception:
        logger = logging.getLogger("interface_http.heif_to_jpg")
        logger.warning("Failed attempt to convert %s \n** Have you installed pi_heif? **", fname)
        return b""  # this will not render as a page and will generate error TODO serve specific page with explicit error


def frame_to_jpg(fname):
    logger = logging.getLogger("interface_http.frame_to_jpg")
    try:
        from picframe.video_streamer import VideoFrameExtractor

        extractor = VideoFrameExtractor(fname, 1, 1, fit_display=False)
        image = extractor.get_first_frame_as_image()
        if image is None:
            logger.warning("Failed to extract frames from %s \n** Have you installed ffmpeg? **", fname)
            return b""

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="JPEG")  # default 75% quality
        buf.seek(0)
        return buf.read()
    except Exception:
        logger.warning("Failed attempt to convert %s \n** Have you installed ffmpeg? **", fname)
        return b""  # this will not render as a page and will generate error TODO serve specific page with explicit error



class RequestHandler(BaseHTTPRequestHandler):

    def do_AUTHHEAD(self):
        if self.server._auth is not None:
            if self.headers.get("Authorization") == None:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Restricted"')
                self.send_header("Content-type", "text/html")
                self.end_headers()
                response_message = "Error: No authorization header received. Please provide valid credentials.\n"
                self.wfile.write(response_message.encode('utf-8'))
                self.connection.close()
                return False
            elif self.headers.get("Authorization") != "Basic " + self.server._auth:
                self.send_response(403)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                response_message = "Error: Invalid authentication credentials. Access denied.\n"
                self.wfile.write(response_message.encode('utf-8'))
                self.connection.close()
                return False
        return True

    def do_GET(self):  # noqa: C901
        if not self.do_AUTHHEAD():
            source_ip = self.client_address[0]
            log_message = f"Authentication failed for source IP: {source_ip}"
            self.server._logger.warning(log_message)
            return
        try:
            path_split = self.path.split("?")
            page_ok = False
            if len(path_split) == 1:  # i.e. no ? - just serve index.html or image
                if path_split[0] != "/":  # serve static page from html_path...
                    html_page = path_split[0].strip("/")
                else:
                    html_page = "index.html"
                _, extension = os.path.splitext(html_page)
                if extension not in [".html", ".js", ".css"]:
                    # NB homeassistant needs to pass url ending in an image extension
                    # in order to trigger streaming whatever is the currently showing image
                    if html_page in ["current_image", "current_image_original"]:
                        page = self.server._controller.get_current_path()
                    else:
                        page = os.path.join(self.server._pic_dir, html_page)
                    extension = os.path.splitext(page)[1].lower()
                    content_type = EXTENSION_TO_MIMETYPE.get(extension, 'application/octet-stream')
                    if html_page != "current_image_original":
                        from picframe.video_streamer import VIDEO_EXTENSIONS
                        if extension in ('.heic', '.heif'):
                            # as current_image may be heic
                            page_bytes = heif_to_jpg(page)
                            content_type = EXTENSION_TO_MIMETYPE['.jpg']
                            is_bytes = True
                        elif extension in VIDEO_EXTENSIONS:
                            # as current_image may be video
                            page_bytes = frame_to_jpg(page)
                            content_type = EXTENSION_TO_MIMETYPE['.jpg']
                            is_bytes = True
                        else:
                            is_bytes = False
                    else:
                        is_bytes = False
                else:
                    page = os.path.join(self.server._html_path, html_page)
                    content_type = "text/html"
                    is_bytes = False
                page = urlparse.unquote(page)
                if (not is_bytes and os.path.isfile(page)) or is_bytes:
                    self.send_response(200)
                    self.send_header('Content-type', content_type)
                    filename = os.path.basename(page)
                    if is_bytes:
                        filename += ".jpg"
                    filename_encoded = urlparse.quote(filename)
                    self.send_header('Content-Disposition', f'inline; filename="{filename}"; filename*=utf-8\'\'{filename_encoded}')
                    # TODO check if html or js - in which case application/javascript
                    # really should filter out attempts to render all other file types (jpg etc?)
                    self.end_headers()
                    if is_bytes:
                        self.wfile.write(page_bytes)
                    else:
                        with open(page, "rb") as f:
                            page_bytes = f.read()
                            self.wfile.write(page_bytes)
                    self.connection.close()
                    page_ok = True
            else:  # server type request - get or set info
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
                        if value != "" or key in ("subdirectory", "location_filter", "tags_filter"):  # parse_qsl can return empty string for value when just querying
                            lwr_val = value.lower()
                            if lwr_val in ("true", "on", "yes"):  # this only works for simple values *not* json style kwargs # noqa: E501
                                value = True
                            elif lwr_val in ("false", "off", "no"):
                                value = False
                            try:
                                if key in self.server._setters:
                                    setattr(self.server._controller, key, value)
                                else:
                                    value = value.replace("\'", "\"")  # only " permitted in json
                                    # value must be json kwargs
                                    getattr(self.server._controller, key)(**json.loads(value))
                            except Exception as e:
                                message['ERROR'] = 'Excepton:{}>{};'.format(key, e)
                        if key in self.server._setters:  # can get info back from controller TODO
                            message[key] = getattr(self.server._controller, key)

                    self.wfile.write(bytes(json.dumps(message), "utf8"))
                    self.connection.close()
                    page_ok = True

                self.server._logger.info(message)
                self.server._logger.debug("request finished in:  %s seconds" % (time.time() - start_time))
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
    def __init__(
            self,
            controller,
            html_path,
            pic_dir,
            no_files_img,
            port=9000,
            auth=False,
            username=None,
            password=None,
        ):
        super(InterfaceHttp, self).__init__(("0.0.0.0", port), RequestHandler)
        # NB name mangling throws a spanner in the works here!!!!!
        # *no* __dunders
        self._logger = logging.getLogger("simple_server.InterfaceHttp")
        self._logger.info("creating an instance of InterfaceHttp")
        self._controller = controller
        self._pic_dir = os.path.expanduser(pic_dir)
        self._no_files_img = os.path.expanduser(no_files_img)
        self._html_path = os.path.expanduser(html_path)
        self._auth = None
        if auth:
            self._auth = base64.b64encode(f"{username}:{password}".encode()).decode()
        # TODO check below works with all decorated methods.. seems to work
        controller_class = controller.__class__
        self._setters = [method for method in dir(controller_class)
                         if 'setter' in dir(getattr(controller_class, method))]
        t = threading.Thread(target=self.serve_forever)
        t.start()

    def stop(self):
        t = threading.Thread(target=self.shutdown, daemon=True)
        t.start()
