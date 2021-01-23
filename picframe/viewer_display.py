
import pi3d
from pi3d.Texture import MAX_SIZE
import math
import time
import subprocess
import logging
import os
from PIL import Image, ImageFilter
from picframe import exif2dict

CODEPOINTS = '1234567890AÄÀBCÇDÈÉÊEFGHIÍJKLMNÑOÓÖPQRSTUÚÙÜVWXYZ., _-/abcdefghijklmnñopqrstuvwxyzáéèêàçíóúäöüß' # limit to 49 ie 7x7 grid_size

class ViewerDisplay:

    def __init__(self, config):
        self.__logger = logging.getLogger("viewer_display.ViewerDisplay")
        self.__blur_amount = config['blur_amount']
        self.__blur_zoom = config['blur_zoom']  
        self.__blur_edges = config['blur_edges']
        self.__edge_alpha = config['edge_alpha']
        self.__fps = config['fps']
        self.__background = config['background'] 
        self.__blend_type = config['blend_type']
        self.__font_file = os.path.expanduser(config['font_file'])
        self.__shader = os.path.expanduser(config['shader'])
        self.__show_names_tm = config['show_names_tm']
        self.__fit = config['fit']
        self.__auto_resize = config['auto_resize']
        self.__kenburns = config['kenburns']
        if self.__kenburns:
            self.__kb_up = True
            self.__fit = False
            self.__blur_edges = False
        if self.__blur_zoom < 1.0:
            self.__blur_zoom = 1.0
        self.__alpha = 0.0 # alpha - proportion front image to back
        self.__delta_alpha = 1.0
        self.__display = None
        self.__slide = None
        self.__xstep = None
        self.__ystep = None
        self.__text = None
        self.__textblock = None
        self.__text_bkg = None
        self.__sfg = None # slide for background
        self.__sbg = None # slide for foreground
        self.__next_tm = 0.0
        self.__name_tm = 0.0
        self.__in_transition = False

    @property
    def display_is_on(self):
        cmd = ["vcgencmd", "display_power"]
        state = str(subprocess.check_output(cmd))
        if (state.find("display_power=1") != -1):
            return True
        else:
            return False

    @display_is_on.setter
    def display_is_on(self, on_off):
        cmd = ["vcgencmd", "display_power", "0"]
        if on_off == True:
            cmd = ["vcgencmd", "display_power", "1"]   
        subprocess.call(cmd)

    def __tex_load(self, filename, orientation = 1, size=None):
        try:
            im = Image.open(filename)
            (w, h) = im.size
            max_dimension = MAX_SIZE # TODO changing MAX_SIZE causes serious crash on linux laptop!
            if not self.__auto_resize: # turned off for 4K display - will cause issues on RPi before v4
                max_dimension = 3840 # TODO check if mipmapping should be turned off with this setting.
            if w > max_dimension:
                im = im.resize((max_dimension, int(h * max_dimension / w)), resample=Image.BICUBIC)
            elif h > max_dimension:
                im = im.resize((int(w * max_dimension / h), max_dimension), resample=Image.BICUBIC)
            if orientation == 2:
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 3:
                im = im.transpose(Image.ROTATE_180) # rotations are clockwise
            elif orientation == 4:
                im = im.transpose(Image.FLIP_TOP_BOTTOM)
            elif orientation == 5:
                im = im.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_270)
            elif orientation == 6:
                im = im.transpose(Image.ROTATE_270)
            elif orientation == 7:
                im = im.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_90)
            elif orientation == 8:
                im = im.transpose(Image.ROTATE_90)
            if self.__blur_edges and size is not None:
                wh_rat = (size[0] * im.size[1]) / (size[1] * im.size[0])
                if abs(wh_rat - 1.0) > 0.01: # make a blurred background
                    (sc_b, sc_f) = (size[1] / im.size[1], size[0] / im.size[0])
                    if wh_rat > 1.0:
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
            tex = pi3d.Texture(im, blend=True, m_repeat=True, automatic_resize=self.__auto_resize,
                                free_after_load=True)
            #tex = pi3d.Texture(im, blend=True, m_repeat=True, automatic_resize=config.AUTO_RESIZE,
            #                    mipmap=config.AUTO_RESIZE, free_after_load=True) # poss try this if still some artifacts with full resolution
        except Exception as e:
            self.__logger.warning("Can't create tex from file: \"%s\"", filename)
            self.__logger.warning("Cause: %s", e.args[1])
            tex = None
        return tex

    def __tidy_name(self, path_name):
        name = os.path.basename(path_name)
        name = ''.join([c for c in name if c in CODEPOINTS])
        return name

    def is_in_transition(self):
        return self.__in_transition

    def slideshow_start(self):
        self.__display = pi3d.Display.create(x=0, y=0, frames_per_second=self.__fps,
              display_config=pi3d.DISPLAY_CONFIG_HIDE_CURSOR, background=self.__background)
        camera = pi3d.Camera(is_3d=False)
        shader = pi3d.Shader(self.__shader)
        self.__slide = pi3d.Sprite(camera=camera, w=self.__display.width, h=self.__display.height, z=5.0)
        self.__slide.set_shader(shader)
        self.__slide.unif[47] = self.__edge_alpha
        self.__slide.unif[54] = self.__blend_type
        
        # PointText and TextBlock. If SHOW_NAMES_TM <= 0 then this is just used for no images message
        grid_size = math.ceil(len(CODEPOINTS) ** 0.5)
        font = pi3d.Font(self.__font_file, codepoints=CODEPOINTS, grid_size=grid_size, shadow_radius=4.0,
                        shadow=(0,0,0,128))
        self.__text = pi3d.PointText(font, camera, max_chars=200, point_size=50)
        self.__textblock = pi3d.TextBlock(x=-int(self.__display.width) * 0.5 + 50, y=-int(self.__display.height) * 0.4,
                                z=0.1, rot=0.0, char_count=199,
                                text_format="{}".format(" "), size=0.99, 
                                spacing="F", space=0.02, colour=(1.0, 1.0, 1.0, 1.0))
        self.__text.add_text_block(self.__textblock)
        back_shader = pi3d.Shader("mat_flat")
        self.__text_bkg = pi3d.Sprite(w=self.__display.width, h=90, y=-self.__display.height * 0.4 - 20, z=4.0)
        self.__text_bkg.set_shader(back_shader)
        self.__text_bkg.set_material((0, 0, 0))


    def slideshow_is_running(self, filename = None, orientation = 1, time_delay = 200.0, fade_time = 10.0):
        tm = time.time()
        if filename is not None:
            self.__sbg = self.__sfg
            self.__sfg = None
            self.__next_tm = tm + time_delay
            self.__name_tm = tm + self.__show_names_tm
            self.__sfg = self.__tex_load(filename, orientation, (self.__display.width, self.__display.height))
            self.__alpha = 0.0
            self.__delta_alpha = 1.0 / (self.__fps * fade_time) # delta alpha
            # set the file name as the description
            if self.__show_names_tm > 0.0:
                self.__textblock.set_text(text_format="{}".format(self.__tidy_name(filename)))
                self.__text.regen()
            else: # could have a NO IMAGES selected and being drawn
                self.__textblock.set_text(text_format="{}".format(" "))
                self.__textblock.colouring.set_colour(alpha=0.0)
                self.__text.regen()

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
                self.__xstep, self.__ystep = (self.__slide.unif[i] * 2.0 / time_delay for i in (48, 49))
                self.__slide.unif[48] = 0.0
                self.__slide.unif[49] = 0.0
                self.__kb_up = not self.__kb_up

        if self.__kenburns:
            t_factor = self.__next_tm - tm
            if self.__kb_up:
                t_factor = time_delay - t_factor
            self.__slide.unif[48] = self.__xstep * t_factor
            self.__slide.unif[49] = self.__ystep * t_factor

        if self.__alpha < 1.0: # transition is happening
            self.__in_transition = True
            self.__alpha += self.__delta_alpha
            if self.__alpha > 1.0:
                self.__alpha = 1.0
            self.__slide.unif[44] = self.__alpha * self.__alpha * (3.0 - 2.0 * self.__alpha)
        else: # no transition effect safe to resuffle etc
            self.__in_transition = False

        self.__slide.draw()

        if tm < self.__name_tm:
            # this sets alpha for the TextBlock from 0 to 1 then back to 0
            dt = (self.__show_names_tm - self.__name_tm + tm + 0.1) / self.__show_names_tm
            ramp_pt = max(4.0, self.__show_names_tm / 4.0)
            alpha = max(0.0, min(1.0, ramp_pt * (self.__alpha- abs(1.0 - 2.0 * dt)))) # cap text alpha at image alpha
            self.__textblock.colouring.set_colour(alpha=alpha)
            self.__text.regen()
            self.__text_bkg.set_alpha(alpha * 0.6)
            if len(self.__textblock.text_format.strip()) > 0: #only draw background if text there
                self.__text_bkg.draw()

        self.__text.draw()
        return self.__display.loop_running()

    def slideshow_stop(self):
        self.__display.destroy()
      