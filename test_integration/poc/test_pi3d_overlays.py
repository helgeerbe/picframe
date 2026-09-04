import time
import logging
import os
from picframe.core.renderers.pi3d_renderer import Pi3dRenderer
from picframe.core.events.dto import RenderCommand, OverlayConfig

logging.basicConfig(level=logging.DEBUG)

def main():
    config = {
        "display_x": 0,
        "display_y": 0,
        "display_w": 800,
        "display_h": 600,
        "fps": 20,
        "background": (0.0, 0.0, 0.0, 1.0),
        "use_glx": False,
        "use_sdl2": True,
        "shader": "src/picframe/data/shaders/blend_new",
        "blend_type": "blend",
        "edge_alpha": 0.5,
        "fit": False,
        "kenburns": False,
        "time_fade": 2.0,
        "time_delay": 200.0,
        "font_file": "src/picframe/data/fonts/NotoSans-Regular.ttf",
        "show_clock": True,
        "clock_format": "%H:%M:%S",
        "show_text": True,
        "text_string": "Test Image Metadata",
        "show_text_tm": 10.0
    }

    renderer = Pi3dRenderer(config)
    renderer.start()

    # Use the no_pictures.jpg image
    image_path = "src/picframe/data/no_pictures.jpg"
    
    if not os.path.exists(image_path):
        print(f"Error: Image not found at {image_path}")
        renderer.stop()
        return

    overlay_config = OverlayConfig(
        show_clock=True,
        clock_format="%H:%M:%S",
        show_text=True,
        text_string="Test Image Metadata"
    )

    command = RenderCommand(image_path=image_path, overlay=overlay_config)
    renderer.execute(command)

    print("Starting render loop. Press Ctrl+C to exit.")
    try:
        start_time = time.time()
        while time.time() - start_time < 15: # Run for 15 seconds
            if not renderer.render_frame():
                break
            time.sleep(1.0 / config["fps"])
    except KeyboardInterrupt:
        pass
    finally:
        renderer.stop()

if __name__ == "__main__":
    main()
