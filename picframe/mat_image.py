from PIL import Image, ImageOps, ImageDraw
from ninepatch import Ninepatch
import numpy as np
import random
import logging
import time

class MatImage:

    # region Constructor

    def __init__(self, display_size, mat_type = None, outer_mat_color = None,
                resource_folder='.', inner_mat_color = None, outer_mat_border = 75,
                inner_mat_border = 40, outer_mat_use_texture = True,
                inner_mat_use_texture = False, auto_inner_mat_color = True):

        self.__mat_types = ['float', 'float_polaroid', 'float_color_wrap', 'single_bevel', 'double_bevel', 'double_flat']

        self.__logger = logging.getLogger("mat_image.MatImage")

        self.auto_inner_mat_color = auto_inner_mat_color
        self.display_size = display_size
        self.inner_mat_border = inner_mat_border
        self.inner_mat_color = inner_mat_color
        self.mat_type = mat_type
        self.outer_mat_border = outer_mat_border
        self.outer_mat_color = outer_mat_color
        self.outer_mat_use_texture = outer_mat_use_texture
        self.inner_mat_use_texture = inner_mat_use_texture

        # --- Matting resources ---
        self.__mat_texture = Image.open('{0}/mat_texture.jpg'.format(resource_folder)).convert("L")
        self.__9patch_bevel = Ninepatch('{0}/9_patch_bevel.png'.format(resource_folder))
        self.__9patch_drop_shadow = Ninepatch('{0}/9_patch_drop_shadow.png'.format(resource_folder))
        self.__9patch_inner_shadow = Ninepatch('{0}/9_patch_inner_shadow.png'.format(resource_folder))
        self.__9patch_highlight = Ninepatch('{0}/9_patch_highlight.png'.format(resource_folder))

    # endregion Constructor

    # region Public Properties

    @property
    def display_size(self):
        return self.__display_size

    @display_size.setter
    def display_size(self, val):
        self.__display_size = val
        self.__display_width, self.__display_height = val

    @property
    def display_width(self):
        return self.__display_width

    @property
    def display_height(self):
        return self.__display_height

    @property
    def outer_mat_border(self):
        return self.__outer_mat_border

    @outer_mat_border.setter
    def outer_mat_border(self, val):
        self.__outer_mat_border = val

    @property
    def inner_mat_border(self):
        return self.__inner_mat_border

    @inner_mat_border.setter
    def inner_mat_border(self, val):
        self.__inner_mat_border = val

    @property
    def outer_mat_color(self):
        return self.__outer_mat_color

    @outer_mat_color.setter
    def outer_mat_color(self, val):
        self.__outer_mat_color = val

    @property
    def inner_mat_color(self):
        return self.__inner_mat_color

    @inner_mat_color.setter
    def inner_mat_color(self, val):
        self.__inner_mat_color = val

    @property
    def mat_type(self):
        return self.__mat_type

    @mat_type.setter
    def mat_type(self, val):
        self.__mat_type = self.__get_mat_type_from_user_string(val)

    @property
    def mat_types(self):
        return self.__mat_types

    @property
    def outer_mat_use_texture(self):
        return self.__outer_mat_use_texture

    @outer_mat_use_texture.setter
    def outer_mat_use_texture(self, val):
        self.__outer_mat_use_texture = val

    @property
    def inner_mat_use_texture(self):
        return self.__inner_mat_use_texture

    @inner_mat_use_texture.setter
    def inner_mat_use_texture(self, val):
        self.__inner_mat_use_texture = val

    # endregion Pubic Properties

    # region Public Methods

    def mat_image(self, images):

        # Randomly pick a mat type from those specified by the User
        mat_type = random.choice(self.mat_type)

        # If a mat color wasn't specified, get one
        if not self.outer_mat_color:
            self.__outer_mat_color_save = self.__get_outer_mat_color(images[0])
        else:
            self.__outer_mat_color_save = tuple(self.outer_mat_color)

        if mat_type == 'float':
            image = self.__style_float(images)
        elif mat_type == 'float_polaroid':
            image = self.__style_float_polaroid(images)
        elif mat_type == 'float_color_wrap':
            image = self.__style_float_color_wrap(images)
        elif mat_type == 'single_bevel':
            image = self.__style_single_mat_bevel(images)
        elif mat_type == 'double_bevel':
            image = self.__style_double_mat_bevel(images)
        elif mat_type == 'double_flat':
            image = self.__style_double_mat_flat(images)
        else: image = None

        return image

    # endregion Public Methods

    # region Matting Styles

    def __style_float(self, images):
        pic_count = len(images)
        pic_wid = (self.display_width / pic_count) - (((pic_count + 1) / pic_count) * self.outer_mat_border)
        pic_height = self.display_height - (self.outer_mat_border * 2)

        final_images = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, self.__outer_mat_color_save, auto_adjust=True)
            image = self.__add_drop_shadow(image)
            final_images.append(image)

        return self.__layout_images(final_images)

    def __style_float_polaroid(self, images):
        border_width = 18
        pic_count = len(images)
        pic_wid = (self.display_width / pic_count) - (((pic_count + 1) / pic_count) * self.outer_mat_border) - (border_width * 2)
        pic_height = self.display_height - (self.outer_mat_border * 2) - (border_width * 2)

        final_images = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, self.__outer_mat_color_save)
            image = ImageOps.expand(image, border_width)
            self.__add_image_outline(image, (210,210,210), outline_width=border_width)
            image = self.__add_drop_shadow(image)
            final_images.append(image)

        return self.__layout_images(final_images)

    def __style_float_color_wrap(self, images):
        border_width = 18
        pic_count = len(images)
        pic_wid = (self.display_width / pic_count) - (((pic_count + 1) / pic_count) * self.outer_mat_border) - (border_width * 2)
        pic_height = self.display_height - (self.outer_mat_border * 2) - (border_width * 2)

        final_images = []
        for image in images:
            color = self.__get_darker_shade(self.__outer_mat_color_save, 0.35)
            color2 = self.__get_darker_shade(self.__outer_mat_color_save, 0.2)
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, color2)
            image = ImageOps.expand(image, border_width)
            self.__add_image_outline(image, color, outline_width=border_width)
            highlight = self.__9patch_highlight.render(image.width, image.height)
            image.paste(highlight, (0,0), highlight)
            image = self.__add_drop_shadow(image)
            final_images.append(image)

        return self.__layout_images(final_images)


    def __style_single_mat_bevel(self, images):
        bevel_wid = 5
        pic_count = len(images)
        pic_wid = (self.display_width / pic_count) - (((pic_count + 1) / pic_count) * self.outer_mat_border) - (bevel_wid * 2)
        pic_height = self.display_height - (self.outer_mat_border * 2) - (bevel_wid * 2)

        final_images = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            image = self.__add_outer_bevel(image)
            final_images.append(image)

        return self.__layout_images(final_images)


    def __style_double_mat_bevel(self, images):
        bevel_wid = 5
        pic_count = len(images)
        pic_wid = (self.display_width / pic_count) - (((pic_count + 1) / pic_count) * self.outer_mat_border) - (self.inner_mat_border * 2) - (bevel_wid * 4)
        pic_height = self.display_height - (self.outer_mat_border * 2) - (self.inner_mat_border * 2) - (bevel_wid * 4)

        final_images = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            mat_size = (image.width + (self.inner_mat_border * 2) + (bevel_wid * 2), image.height + (self.inner_mat_border * 2) + (bevel_wid * 2))
            mat_image = self.__get_inner_mat(mat_size)
            mat_image = self.__add_outer_bevel(mat_image)
            image = self.__add_outer_bevel(image)
            mat_image.paste(image, (self.inner_mat_border + bevel_wid, self.inner_mat_border + bevel_wid))
            final_images.append(mat_image)

        return self.__layout_images(final_images)


    def __style_double_mat_flat(self, images):
        pic_count = len(images)
        pic_wid = (self.display_width / pic_count) - (((pic_count + 1) / pic_count) * self.outer_mat_border) - (self.inner_mat_border * 2)
        pic_height = self.display_height - (self.outer_mat_border * 2) - (self.inner_mat_border * 2)

        final_images = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, self.__outer_mat_color_save)
            mat_size = (image.width + (self.inner_mat_border * 2), image.height + (self.inner_mat_border * 2))
            mat_image = self.__get_inner_mat(mat_size)
            mat_image = self.__add_inner_shadow(mat_image)
            mat_image.paste(image, (self.inner_mat_border, self.inner_mat_border))
            final_images.append(mat_image)

        return self.__layout_images(final_images)

    # endregion Matting styles

    # region Helper Methods

    def __get_mat_type_from_user_string(self, mat_type_string):
        if mat_type_string == None: mat_type_string = ''

        final = []
        mat_type_string = mat_type_string.replace(',', "") # remove commas from the string
        for type in mat_type_string.split():
            if type in self.mat_types:
                final.append(type)
            else:
                self.__logger.debug('Skipping invalid mat type: %s', type)

        if not final:
            self.__logger.debug('No valid mat types defined - using: %s', self.mat_types)
            final = self.mat_types

        return final

    def __scale_image(self, image, size=None):
        if size == None:
            width, height = self.display_size
        else:
            width, height = size

        scale = min(width/image.width, height/image.height)
        image = image.resize((int(image.width * scale), int(image.height * scale)), resample=Image.BICUBIC)
        return image


    def __get_outer_mat_color(self, image):
        k = KmeansNp(k=3, max_iterations=10, size=100)
        colors = k.run(image)
        return tuple(colors[0])


    """def __get_least_gray_color(self, colors):
        dist = -1
        color = colors[0]
        for this_color in colors:
            this_dist =  max(this_color) - min(this_color)
            if this_dist > dist:
                dist = this_dist
                color = this_color
        return tuple(map(int, color))"""


    def __get_darker_shade(self, rgb_color, fractional_percent = 0.5):
        return tuple(map(lambda c: int(c * fractional_percent), rgb_color))


    def __get_colorized_mat(self, color, use_texture):
        if use_texture:
            mat_img = self.__mat_texture.copy()
            mat_img = mat_img.resize(self.display_size, resample=Image.BICUBIC)
            mat_img = ImageOps.colorize(mat_img, black="black", white=color)
        else:
            mat_img = Image.new('RGB', self.display_size, color)

        return mat_img


    def __get_inner_mat(self, size):
        w,h = size

        # If the color wasn't specified, get one
        if not self.inner_mat_color:
            color = self.__get_darker_shade(self.__outer_mat_color_save, 0.50)
        else:
            color = tuple(self.inner_mat_color)

        mat = self.__get_colorized_mat(color, self.inner_mat_use_texture)
        mat = mat.crop((0, 0, w, h))

        return mat


    def __add_outer_bevel(self, image, expand = True):
        if expand:
            image = ImageOps.expand(image, 5)
        outer_bevel_image = self.__9patch_bevel.render(image.width, image.height)
        image.paste(outer_bevel_image, (0,0), outer_bevel_image)
        return image


    def __add_inner_shadow(self, image):
        inner_shadow_image = self.__9patch_inner_shadow.render(image.width, image.height)
        image.paste(inner_shadow_image, (0,0), inner_shadow_image)
        return image


    def __add_image_outline(self, img, mat_base_color, outline_width=1, auto_adjust = False):
        if auto_adjust:
            # Calculate the outline color from the mat_color
            brightness = sum(mat_base_color[0:3]) / 3
            outline_color_offset = 30 if brightness < 127 else -30
            outline_color = tuple(map(lambda x: x + outline_color_offset, mat_base_color))
        else:
            outline_color = mat_base_color

        rect = ImageDraw.Draw(img)
        shape = [0, 0, img.width-1, img.height-1]
        rect.rectangle(shape, outline=outline_color, width=outline_width)


    def __add_drop_shadow(self, image):
        shadow_offset = 15
        mod_image = Image.new('RGBA', (image.width + shadow_offset, image.height + shadow_offset), (0,0,0,0))
        shadow_image = self.__9patch_drop_shadow.render(mod_image.width, mod_image.height)
        mod_image.paste(shadow_image, (0,0), shadow_image)
        mod_image.paste(image, (0,0))
        return mod_image


    def __layout_images(self, images):
        mat_image = self.__get_colorized_mat(self.__outer_mat_color_save, self.outer_mat_use_texture)
        total_wid = self.outer_mat_border * (len(images) + 1)
        for image in images:
            total_wid += image.width

        xloc = int((mat_image.width - total_wid) / 2)
        for image in images:
            xloc += self.outer_mat_border
            yloc =  int((mat_image.height -  image.height) / 2)
            if image.mode == 'RGBA':
                mat_image.paste(image, (xloc, yloc), image)
            else:
                mat_image.paste(image, (xloc, yloc))
            xloc += image.width

        return mat_image

    # endregion Helper functions

# region Automatic Color Selection ----

"""class Cluster(object):

    def __init__(self):
        self.pixels = []
        self.centroid = None

    def addPoint(self, pixel):
        self.pixels.append(pixel)

    def setNewCentroid(self):
        R = [colour[0] for colour in self.pixels]
        G = [colour[1] for colour in self.pixels]
        B = [colour[2] for colour in self.pixels]

        R = sum(R) / len(R)
        G = sum(G) / len(G)
        B = sum(B) / len(B)

        self.centroid = (R, G, B)
        self.pixels = []

        return self.centroid


class Kmeans(object):

    def __init__(self, k=3, max_iterations=5, min_distance=5.0, size=200):
        self.k = k
        self.max_iterations = max_iterations
        self.min_distance = min_distance
        self.size = (size, size)

    def run(self, image):
        image = image.copy()
        image.thumbnail(self.size)
        if image.mode != 'RGB':
            image = image.convert('RGB') # JAG, some numpy manipulations here don't expect an Alpha channel
        self.image = image

        self.pixels = np.array(image.getdata(), dtype=np.float)

        self.clusters = [None for i in range(self.k)]
        self.oldClusters = None

        randomPixels = random.sample(list(self.pixels), self.k)

        for idx in range(self.k):
            self.clusters[idx] = Cluster()
            self.clusters[idx].centroid = randomPixels[idx]

        iterations = 0
        self.start_clusters = [c.centroid for c in self.clusters] # make copy

        while self.shouldExit(iterations) is False:

            self.oldClusters = [cluster.centroid for cluster in self.clusters]

            for pixel in self.pixels:
                self.assignClusters(pixel)

            for cluster in self.clusters:
                if not cluster.pixels: continue
                cluster.setNewCentroid()

            iterations += 1

        return [cluster.centroid for cluster in self.clusters]

    def assignClusters(self, pixel):
        shortest = float('Inf')
        for cluster in self.clusters:
            distance = self.calcDistance(cluster.centroid, pixel)
            if distance < shortest:
                shortest = distance
                nearest = cluster

        nearest.addPoint(pixel)

    def calcDistance(self, a, b):
        result = np.sqrt(sum((a - b) ** 2))
        return result

    def shouldExit(self, iterations):

        if self.oldClusters is None:
            return False

        for idx in range(self.k):
            dist = self.calcDistance(
                np.array(self.clusters[idx].centroid),
                np.array(self.oldClusters[idx])
            )
            if dist < self.min_distance:
                return True

        if iterations <= self.max_iterations:
            return False

        return True"""

class KmeansNp:
    def __init__(self, k=3, max_iterations=5, min_distance=5.0, size=200):
        self.k = k
        self.max_iterations = max_iterations
        self.min_distance = min_distance
        self.size = (size, size)

    def run(self, image, start_clusters=None):
        image = image.copy()
        image.thumbnail(self.size)
        im = np.array(image, dtype=np.float)[:,:,:3]
        # following section can be used to give the clusters location as well as colour proximity
        #(ix0, ix1) = np.indices(im.shape[:2]) # vert,horiz pixel locations
        #ix0.shape = ix0.shape + (1,) # make same dim as im
        #ix1.shape = ix1.shape + (1,) # make same dim as im
        #im = np.append(im, ix0, axis=2) # TODO multiply by scale rel to rgb scale
        #im = np.append(im, ix1, axis=2) # im now r,g,b,u,v
        d = im.shape[-1] # 3 or 5 if u,v added
        im = im.reshape(-1, d) #NB need to use floats to avoid coercing to uint8 scrambling subtractions
        n = len(im)
        if start_clusters is None:
            centroids = im[np.random.choice(np.arange(n), self.k)]
        else:
            centroids = np.array(start_clusters, dtype=np.float)
        old_centroids = centroids.copy()
        for i in range(self.max_iterations):
            im.shape = (1, n, d) # add dimension to allow broadcasting
            centroids.shape = (self.k, 1, d) # ditto
            dists = (((im - centroids) ** 2).sum(axis=2)) ** 0.5 # euclidean distance - manhattan might be fine and faster
            ix = np.argmin(dists, axis=0) # indices of nearest centroid for each pixel
            im.shape = (n, d) # reduce dimensions for mean
            centroids.shape = (self.k, d) # ditto
            counts = np.unique(ix, return_counts=True)[1] # count the number of each index
            to_keep = [] # discard any centroids with no pixels nearest to them
            for j in range(self.k): # write back average location of all nearest pixels
                j_pixels = im[ix == j] # view into im where ix points to centroid j
                if len(j_pixels) > 0: # error if try to get mean zero length array TODO remove groups with few pixels?
                    centroids[j] = j_pixels.mean(axis=0)
                    to_keep.append(j)
            if len(to_keep) < len(centroids): # this will be relatively rare
                for j in to_keep[::-1]: # delete in reverse order of index
                    centroids = np.delete(centroids, j, axis=0)
                    old_centroids = np.delete(old_centroids, j, axis=0)
            movement = ((((centroids - old_centroids) ** 2).sum(axis=1)) ** 0.5).max()
            if movement < self.min_distance:
                break
            old_centroids = centroids.copy()

        c_max, c_min = centroids[:,:3].max(axis=1), centroids[:,:3].min(axis=1) # max, min for each centroid
        #c_lum = 0.5 * (c_max + c_min)
        #c_sat = (c_max - c_min) / (255.0 - np.abs(c_lum * 2.0 - 255.0)) # should check for lum == 255
        c_sat = c_max - c_min # value used previously includes element of lum TODO bias more to lighter using (1.5 * c_max - c_min)
        ix_order = np.argsort(c_sat)[::-1] # indices to sorted values - reversed
        return centroids[ix_order, :3].astype(np.uint8)

if __name__ == "__main__":

    save_folder = '/home/pi/pic_save'
    file1 = '/home/pi/Pictures/Sagelight/2011-01-22_12-05-18-10_edited.jpg'
    file2 = '/home/pi/Pictures/Sagelight/2011-01-22_12-06-07-10_edited.jpg'
    image1 = Image.open(file1)
    image2 = Image.open(file2)
    images = (image1, image2)

    matter = MatImage((1920, 1080))

    for mat_type in matter.mat_types:
        matter.mat_type = mat_type
        img = matter.mat_image(images)
        img.save('{0}/{1}_texture.jpg'.format(save_folder, mat_type))