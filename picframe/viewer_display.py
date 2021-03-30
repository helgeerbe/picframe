import sys
sys.path.insert(1, '/home/patrick/python/pi3d')
import pi3d
#from pi3d.Texture import MAX_SIZE
import math
import time
import subprocess
import logging
import os
import numpy as np
from PIL import Image, ImageFilter, ImageFile
from picframe import mat_image

# supported display modes for display switch
dpms_mode = ("unsupported", "pi", "x_dpms")

# utility functions with no dependency on ViewerDisplay properties
def txt_to_bit(txt):
    txt_map = {"title":1, "caption":2, "name":4, "date":8, "location":16, "folder":32}
    if txt in txt_map:
        return txt_map[txt]
    return 0

def parse_show_text(txt):
    show_text = 0
    txt = txt.lower()
    for txt_key in ("title", "caption", "name", "date", "location", "folder"):
        if txt_key in txt:
            show_text |= txt_to_bit(txt_key)
    return show_text

class ViewerDisplay:

    def __init__(self, config):
        self.__logger = logging.getLogger("viewer_display.ViewerDisplay")
        self.__blur_amount = config['blur_amount']
        self.__blur_zoom = config['blur_zoom']
        self.__blur_edges = config['blur_edges']
        self.__edge_alpha = config['edge_alpha']

        self.__mat_images, self.__mat_images_tol = self.__get_mat_image_control_values(config['mat_images'])
        self.__mat_type = config['mat_type']
        self.__outer_mat_color = config['outer_mat_color']
        self.__inner_mat_color = config['inner_mat_color']
        self.__outer_mat_border = config['outer_mat_border']
        self.__inner_mat_border = config['inner_mat_border']
        self.__outer_mat_use_texture = config['outer_mat_use_texture']
        self.__inner_mat_use_texture = config['inner_mat_use_texture']
        self.__mat_resource_folder = os.path.expanduser(config['mat_resource_folder'])

        self.__fps = config['fps']
        self.__background = config['background']
        self.__blend_type = {"blend":0.0, "burn":1.0, "bump":2.0}[config['blend_type']]
        self.__font_file = os.path.expanduser(config['font_file'])
        self.__shader = os.path.expanduser(config['shader'])
        self.__show_text_tm = config['show_text_tm']
        self.__show_text_fm = config['show_text_fm']
        self.__show_text_sz = config['show_text_sz']
        self.__show_text = parse_show_text(config['show_text'])
        self.__text_justify = config['text_justify'].upper()
        self.__fit = config['fit']
        #self.__auto_resize = config['auto_resize']
        self.__kenburns = config['kenburns']
        if self.__kenburns:
            self.__kb_up = True
            self.__fit = False
            self.__blur_edges = False
        if self.__blur_zoom < 1.0:
            self.__blur_zoom = 1.0
        self.__display_x = int(config['display_x'])
        self.__display_y = int(config['display_y'])
        self.__display_w = None if config['display_w'] is None else int(config['display_w'])
        self.__display_h = None if config['display_h'] is None else int(config['display_h'])
        self.__use_glx = config['use_glx']
        #self.__codepoints = config['codepoints']
        self.__alpha = 0.0 # alpha - proportion front image to back
        self.__delta_alpha = 1.0
        self.__display = None
        self.__slide = None
        self.__xstep = None
        self.__ystep = None
        #self.__text = None
        self.__textblocks = None
        self.__text_bkg = None
        self.__sfg = None # slide for background
        self.__sbg = None # slide for foreground
        self.__next_tm = 0.0
        self.__name_tm = 0.0
        self.__in_transition = False
        self.__matter = None
        ImageFile.LOAD_TRUNCATED_IMAGES = True # occasional damaged file hangs app

    @property
    def display_is_on(self):
        try: # vcgencmd only applies to raspberry pi
            state = str(subprocess.check_output(["vcgencmd", "display_power"]))
            if (state.find("display_power=1") != -1):
                return True
            else:
                return False
        except Exception as e:
            self.__logger.debug("Display ON/OFF is vcgencmd, but an error occurred")
            self.__logger.debug("Cause: %s", e)
            try: # try xset on linux, DPMS has to be enabled
                output = subprocess.check_output(["xset" , "-display", ":0", "-q"])
                if output.find(b'Monitor is On') != -1:
                    return True
                else:
                    return False
            except Exception as e:
                self.__logger.debug("Display ON/OFF is X with dpms enabled, but an error occurred")
                self.__logger.debug("Cause: %s", e)
                self.__logger.warning("Display ON/OFF is not supported for this platform.")
        return True

    @display_is_on.setter
    def display_is_on(self, on_off):
        try: # vcgencmd only applies to raspberry pi
            if on_off == True:
                subprocess.call(["vcgencmd", "display_power", "1"])
            else:
                subprocess.call(["vcgencmd", "display_power", "0"])
        except Exception as e:
            self.__logger.debug("Display ON/OFF is vcgencmd, but an error occured")
            self.__logger.debug("Cause: %s", e)
            try: # try xset on linux, DPMS has to be enabled
                if on_off == True:
                    subprocess.call(["xset" , "-display", ":0", "dpms", "force", "on"])
                else:
                    subprocess.call(["xset" , "-display", ":0", "dpms", "force", "off"])
            except Exception as e:
                self.__logger.debug("Display ON/OFF is xset via dpms, but an error occured")
                self.__logger.debug("Cause: %s", e)
                self.__logger.warning("Display ON/OFF is not supported for this platform.")

    def set_show_text(self, txt_key=None, val="ON"):
        if txt_key is None:
            self.__show_text = 0 # no arguments signals turning all off
        else:
            bit = txt_to_bit(txt_key) # convert field name to relevant bit 1,2,4,8,16 etc
            if val == "ON":
                self.__show_text |= bit # turn it on
            else: #TODO anything else ok to turn it off?
                bits = 65535 ^ bit
                self.__show_text &= bits # turn it off

    def text_is_on(self, txt_key):
        return self.__show_text & txt_to_bit(txt_key)

    def reset_name_tm(self, pic=None, paused=None, side=0, pair=False):
        # only extend i.e. if after initial fade in
        if pic is not None and paused is not None: # text needs to be refreshed
            self.__make_text(pic, paused, side, pair)
        self.__name_tm = max(self.__name_tm, time.time() + self.__show_text_tm)

    def set_brightness(self, val):
        self.__slide.unif[55] = val # take immediate effect

    def get_brightness(self):
        return float("{:.2f}".format(self.__slide.unif[55])) # TODO There seems to be a rounding issue. set 0.77 get 0.7699999809265137


    def __check_heif_then_open(self, fname):
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
                self.__logger.warning("Failed attempt to convert %s \n** Have you installed pyheif? **", fname)
        else:
            try:
                image = Image.open(fname)
                if image.mode not in ("RGB", "RGBA"): # mat system needs RGB or more
                    image = image.convert("RGB")
            except: # for whatever reason
                image = None
            return image

    # Concatenate the specified images horizontally. Clip the taller
    # image to the height of the shorter image.
    def __create_image_pair(self, im1, im2):
        sep = 8 # separation between the images
        # scale widest image to same width as narrower to avoid drastic cropping on mismatched images
        if im1.width > im2.width:
            im1 = im1.resize((im2.width, int(im1.height * im2.width / im1.width)), resample=Image.BICUBIC)
        else:
            im2 = im2.resize((im1.width, int(im2.height * im1.width / im2.width)), resample=Image.BICUBIC)
        dst = Image.new('RGB', (im1.width + im2.width + sep, min(im1.height, im2.height)))
        dst.paste(im1, (0, 0))
        dst.paste(im2, (im1.width + sep, 0))
        return dst

    def __orientate_image(self, im, orientation):
        if orientation == 2:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        elif orientation == 3:
            im = im.transpose(Image.ROTATE_180) # rotations are clockwise
        elif orientation == 4:
            im = im.transpose(Image.FLIP_TOP_BOTTOM)
        elif orientation == 5:
            im = im.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_90)
        elif orientation == 6:
            im = im.transpose(Image.ROTATE_270)
        elif orientation == 7:
            im = im.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_270)
        elif orientation == 8:
            im = im.transpose(Image.ROTATE_90)
        return im


    def __get_mat_image_control_values(self, mat_images_value):
        on = True
        val = 0.01
        org_val = str(mat_images_value).lower()
        if org_val in ('true', 'yes', 'on'):
            val = -1
        elif org_val in ('false', 'no', 'off'):
            on = False
        else:
            try:
                val = float(org_val)
            except:
                self.__logger.warning("Invalid value for config option 'mat_images'. Using default.")
        return(on, val)


    def __get_aspect_diff(self, screen_size, image_size):
        screen_aspect = screen_size[0] / screen_size[1]
        image_aspect = image_size[0] / image_size[1]

        if screen_aspect > image_aspect:
            diff_aspect = 1 - (image_aspect / screen_aspect)
        else:
            diff_aspect = 1 - (screen_aspect / image_aspect)

        return (screen_aspect, image_aspect, diff_aspect)


    def __tex_load(self, pics, size=None):
        try:
            if self.__mat_images and self.__matter == None:
                self.__matter = mat_image.MatImage(
                    display_size = (self.__display.width , self.__display.height),
                    resource_folder=self.__mat_resource_folder,
                    mat_type = self.__mat_type,
                    outer_mat_color = self.__outer_mat_color,
                    inner_mat_color = self.__inner_mat_color,
                    outer_mat_border = self.__outer_mat_border,
                    inner_mat_border = self.__inner_mat_border,
                    outer_mat_use_texture = self.__outer_mat_use_texture,
                    inner_mat_use_texture = self.__inner_mat_use_texture)

            # Load the image(s) and correct their orientation as necessary
            if pics[0]:
                im = self.__check_heif_then_open(pics[0].fname)
                if pics[0].orientation != 1:
                     im = self.__orientate_image(im, pics[0].orientation)
                if im is None:
                    return None
            if pics[1]:
                im2 = self.__check_heif_then_open(pics[1].fname)
                if pics[1].orientation != 1:
                     im2 = self.__orientate_image(im2, pics[1].orientation)

            screen_aspect, image_aspect, diff_aspect = self.__get_aspect_diff(size, im.size)

            if self.__mat_images and diff_aspect > self.__mat_images_tol:
                if not pics[1]:
                    im = self.__matter.mat_image((im,))
                else:
                    im = self.__matter.mat_image((im, im2))
            else:
                if pics[1]: #i.e portrait pair
                    im = self.__create_image_pair(im, im2)



            (w, h) = im.size
            # no longer allow automatic resize to be turned off - but GL_MAX_TEXTURE_SIZE used by Texture
            #max_dimension = MAX_SIZE # TODO changing MAX_SIZE causes serious crash on linux laptop!
            #if not self.__auto_resize: # turned off for 4K display - will cause issues on RPi before v4
            #    max_dimension = 3840 # TODO check if mipmapping should be turned off with this setting.
            #if w > max_dimension:
            #    im = im.resize((max_dimension, int(h * max_dimension / w)), resample=Image.BICUBIC)
            #elif h > max_dimension:
            #    im = im.resize((int(w * max_dimension / h), max_dimension), resample=Image.BICUBIC)

            screen_aspect, image_aspect, diff_aspect = self.__get_aspect_diff(size, im.size)

            if self.__blur_edges and size:
                if diff_aspect > 0.01:
                    (sc_b, sc_f) = (size[1] / im.size[1], size[0] / im.size[0])
                    if screen_aspect > image_aspect:
                        (sc_b, sc_f) = (sc_f, sc_b) # swap round
                    (w, h) =  (round(size[0] / sc_b / self.__blur_zoom), round(size[1] / sc_b / self.__blur_zoom))
                    (x, y) = (round(0.5 * (im.size[0] - w)), round(0.5 * (im.size[1] - h)))
                    box = (x, y, x + w, y + h)
                    blr_sz = (int(x * 512 / size[0]) for x in size)
                    im_b = im.resize(size, resample=0, box=box).resize(blr_sz)
                    im_b = im_b.filter(ImageFilter.GaussianBlur(self.__blur_amount))
                    im_b = im_b.resize(size, resample=Image.BICUBIC)
                    im_b.putalpha(round(255 * self.__edge_alpha))  # to apply the same EDGE_ALPHA as the no blur method.
                    im = im.resize((int(x * sc_f) for x in im.size), resample=Image.BICUBIC)
                    """resize can use Image.LANCZOS (alias for Image.ANTIALIAS) for resampling
                    for better rendering of high-contranst diagonal lines. NB downscaled large
                    images are rescaled near the start of this try block if w or h > max_dimension
                    so those lines might need changing too.
                    """
                    im_b.paste(im, box=(round(0.5 * (im_b.size[0] - im.size[0])),
                                        round(0.5 * (im_b.size[1] - im.size[1]))))
                    im = im_b # have to do this as paste applies in place
            tex = pi3d.Texture(im, blend=True, m_repeat=True, free_after_load=True)
            #tex = pi3d.Texture(im, blend=True, m_repeat=True, automatic_resize=config.AUTO_RESIZE,
            #                    mipmap=config.AUTO_RESIZE, free_after_load=True) # poss try this if still some artifacts with full resolution
        except Exception as e:
            self.__logger.warning("Can't create tex from file: \"%s\" or \"%s\"", pics[0].fname, pics[1])
            self.__logger.warning("Cause: %s", e)
            tex = None
            #raise # only re-raise errors here while debugging
        return tex

    def __sanitize_string(self, path_name):
        name = os.path.basename(path_name)
        #name = ''.join([c for c in name if c in self.__codepoints])
        return name

    def __make_text(self, pic, paused, side=0, pair=False):
        # if side 0 and pair False then this is a full width text and put into
        # __textblocks[0] otherwise it is half width and put into __textblocks[position]
        info_strings = []
        if pic is not None and (self.__show_text > 0 or paused): #was SHOW_TEXT_TM > 0.0
            if (self.__show_text & 1) == 1 and pic.title is not None: # title
                info_strings.append(self.__sanitize_string(pic.title))
            if (self.__show_text & 2) == 2 and pic.caption is not None: # caption
                info_strings.append(self.__sanitize_string(pic.caption))
            if (self.__show_text & 4) == 4: # name
                info_strings.append(self.__sanitize_string(pic.fname))
            if (self.__show_text & 8) == 8 and pic.exif_datetime > 0: # date
                fdt = time.strftime(self.__show_text_fm, time.localtime(pic.exif_datetime))
                info_strings.append(fdt)
            if (self.__show_text & 16) == 16 and pic.location is not None: # location
                info_strings.append(pic.location) #TODO need to sanitize and check longer than 0 for real
            if (self.__show_text & 32) == 32: # folder
                info_strings.append(self.__sanitize_string(os.path.basename(os.path.dirname(pic.fname))))
            if paused:
                info_strings.append("PAUSED")
        final_string = " • ".join(info_strings)

        block = None
        if len(final_string) > 0:
            if side == 0 and not pair:
                c_rng = self.__display.width - 100 # range for x loc from L to R justified
            else:
                c_rng = self.__display.width * 0.5 - 100 # range for x loc from L to R justified
            block = pi3d.FixedString(self.__font_file, final_string, font_size=self.__show_text_sz,
                                    shader=self.__flat_shader, justify=self.__text_justify, width=c_rng)
            adj_x = (c_rng - block.sprite.width) // 2 # half amount of space outside sprite
            if self.__text_justify == "L":
                adj_x *= -1
            elif self.__text_justify == "C":
                adj_x = 0
            if side == 0 and not pair: # i.e. full width
                x = adj_x
            else:
                x = adj_x + int(self.__display.width * 0.25 * (-1.0 if side == 0 else 1.0))
            y = (block.sprite.height - self.__display.height + self.__show_text_sz) // 2
            block.sprite.position(x, y, 0.1)
            block.sprite.set_alpha(0.0)
        self.__textblocks[side] = block

    def is_in_transition(self):
        return self.__in_transition

    def slideshow_start(self):
        self.__display = pi3d.Display.create(x=self.__display_x, y=self.__display_y,
              w=self.__display_w, h=self.__display_h, frames_per_second=self.__fps,
              display_config=pi3d.DISPLAY_CONFIG_HIDE_CURSOR, background=self.__background, use_glx=self.__use_glx)
        camera = pi3d.Camera(is_3d=False)
        shader = pi3d.Shader(self.__shader)
        self.__slide = pi3d.Sprite(camera=camera, w=self.__display.width, h=self.__display.height, z=5.0)
        self.__slide.set_shader(shader)
        self.__slide.unif[47] = self.__edge_alpha
        self.__slide.unif[54] = float(self.__blend_type)
        self.__slide.unif[55] = 1.0 #brightness
        self.__textblocks = [None, None]

        bkg_ht = min(self.__display.width, self.__display.height) // 4
        text_bkg_array = np.zeros((bkg_ht, 1, 4), dtype=np.uint8)
        text_bkg_array[:,:,3] = np.linspace(0, 120, bkg_ht).reshape(-1, 1)
        text_bkg_tex = pi3d.Texture(text_bkg_array, blend=True, mipmap=False, free_after_load=True)

        self.__flat_shader = pi3d.Shader("uv_flat")
        self.__text_bkg = pi3d.Sprite(w=self.__display.width, h=bkg_ht, y=-int(self.__display.height) // 2 + bkg_ht // 2, z=4.0)
        self.__text_bkg.set_draw_details(self.__flat_shader, [text_bkg_tex])


    def slideshow_is_running(self, pics=None, time_delay = 200.0, fade_time = 10.0, paused=False):
        loop_running = self.__display.loop_running()
        tm = time.time()
        if pics is not None:
            self.__sbg = self.__sfg # if the first tex_load fails then __sfg might be Null TODO should fn return if None?
            self.__next_tm = tm + time_delay
            self.__name_tm = tm + fade_time + float(self.__show_text_tm) # text starts after slide transition
            new_sfg = self.__tex_load(pics, (self.__display.width, self.__display.height))
            if new_sfg is not None: # this is a possible return value which needs to be caught
                self.__sfg = new_sfg
            else:
                return (True, False) # return early
            self.__alpha = 0.0
            self.__delta_alpha = 1.0 / (self.__fps * fade_time) # delta alpha
            # set the file name as the description
            if self.__show_text_tm > 0.0:
                for i, pic in enumerate(pics):
                    self.__make_text(pic, paused, i, pics[1] is not None) # send even if pic is None to clear previous text
            else: # could have a NO IMAGES selected and being drawn
                for block in range(2):
                    self.__textblocks[block] = None

            if self.__sbg is None: # first time through
                self.__sbg = self.__sfg
            self.__slide.set_textures([self.__sfg, self.__sbg])
            self.__slide.unif[45:47] = self.__slide.unif[42:44] # transfer front width and height factors to back
            self.__slide.unif[51:53] = self.__slide.unif[48:50] # transfer front width and height offsets
            wh_rat = (self.__display.width * self.__sfg.iy) / (self.__display.height * self.__sfg.ix)
            if (wh_rat > 1.0 and self.__fit) or (wh_rat <= 1.0 and not self.__fit):
                sz1, sz2, os1, os2 = 42, 43, 48, 49
            else:
                sz1, sz2, os1, os2 = 43, 42, 49, 48
                wh_rat = 1.0 / wh_rat
            self.__slide.unif[sz1] = wh_rat
            self.__slide.unif[sz2] = 1.0
            self.__slide.unif[os1] = (wh_rat - 1.0) * 0.5
            self.__slide.unif[os2] = 0.0
            if self.__kenburns:
                self.__xstep, self.__ystep = (self.__slide.unif[i] * 2.0 / (time_delay - fade_time) for i in (48, 49))
                self.__slide.unif[48] = 0.0
                self.__slide.unif[49] = 0.0
                #self.__kb_up = not self.__kb_up # just go in one direction

        if self.__kenburns and self.__alpha >= 1.0:
            t_factor = time_delay - fade_time - self.__next_tm + tm
            #t_factor = self.__next_tm - tm
            #if self.__kb_up:
            #    t_factor = time_delay - t_factor
            # add exponentially smoothed tweening in case of timing delays etc. to avoid 'jumps'
            self.__slide.unif[48] = self.__slide.unif[48] * 0.95 + self.__xstep * t_factor * 0.05
            self.__slide.unif[49] = self.__slide.unif[49] * 0.95 + self.__ystep * t_factor * 0.05

        if self.__alpha < 1.0: # transition is happening
            self.__alpha += self.__delta_alpha
            if self.__alpha > 1.0:
                self.__alpha = 1.0
            self.__slide.unif[44] = self.__alpha * self.__alpha * (3.0 - 2.0 * self.__alpha)

        if (self.__next_tm - tm) < 5.0 or self.__alpha < 1.0:
            self.__in_transition = True # set __in_transition True a few seconds *before* end of previous slide
        else: # no transition effect safe to update database, resuffle etc
            self.__in_transition = False

        self.__slide.draw()

        if self.__alpha >= 1.0 and tm < self.__name_tm:
            # this sets alpha for the TextBlock from 0 to 1 then back to 0
            dt = (self.__show_text_tm - self.__name_tm + tm + 0.1) / self.__show_text_tm
            ramp_pt = max(4.0, self.__show_text_tm / 4.0)
            alpha = max(0.0, min(1.0, ramp_pt * (self.__alpha- abs(1.0 - 2.0 * dt)))) # cap text alpha at image alpha
            for block in self.__textblocks:
                if block is not None:
                    block.sprite.set_alpha(alpha)
            self.__text_bkg.set_alpha(alpha)
            if any(block is not None for block in self.__textblocks): #txt_len > 0: #only draw background if text there
                self.__text_bkg.draw()

        for block in self.__textblocks:
            if block is not None:
                block.sprite.draw()
        return (loop_running, False) # now returns tuple with skip image flag added

    def slideshow_stop(self):
        self.__display.destroy()