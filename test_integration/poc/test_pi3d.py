import pi3d
import time
import os
from PIL import Image

if __name__ == "__main__":
    DISPLAY = pi3d.Display.create(
        x=0, y=0, w=800, h=600, frames_per_second=60,
        display_config=pi3d.DISPLAY_CONFIG_HIDE_CURSOR | pi3d.DISPLAY_CONFIG_NO_FRAME,
        background=(0.5, 0.0, 0.0, 1.0), use_glx=False, use_sdl2=True
    )
    CAMERA = pi3d.Camera(is_3d=False)
    SHADER = pi3d.Shader("src/picframe/data/shaders/blend_new")

    texture_path = os.path.abspath("test/images/AlleExif.JPG")
    im = Image.open(texture_path)
    texture = pi3d.Texture(im, blend=True, m_repeat=True, free_after_load=True)

    sprite = pi3d.Sprite(camera=CAMERA, w=800, h=600, z=5.0)
    sprite.set_shader(SHADER)
    sprite.set_textures([texture, texture])

    # Set uniforms required by blend_new shader
    sprite.unif[42] = 1.0 # w_rat_f
    sprite.unif[43] = 1.0 # h_rat_f
    sprite.unif[44] = 1.0 # alpha
    sprite.unif[45] = 1.0 # w_rat_b
    sprite.unif[46] = 1.0 # h_rat_b
    sprite.unif[47] = 0.5 # edge_alpha
    sprite.unif[48] = 0.0 # x_off_f
    sprite.unif[49] = 0.0 # y_off_f
    sprite.unif[51] = 0.0 # x_off_b
    sprite.unif[52] = 0.0 # y_off_b
    sprite.unif[54] = 0.0 # blend_type
    sprite.unif[55] = 1.0 # brightness

    start = time.time()
    while DISPLAY.loop_running() and time.time() - start < 5.0:
        sprite.draw()

    DISPLAY.destroy()
