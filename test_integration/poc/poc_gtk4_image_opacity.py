#!/usr/bin/env python3
"""PoC: stack two GTK4 image windows and render the top image translucent.

This is a compositor sanity check for #686. It does not use GStreamer or pi3d.
Run it under labwc/Wayland with two JPG/PNG files. If transparency works, the
bottom image should be visible through the top image.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402


logger = logging.getLogger("gtk4_image_opacity_poc")


def _existing_file(path: str) -> Path:
    image_path = Path(path).expanduser()
    if not image_path.is_file():
        raise argparse.ArgumentTypeError(f"Image file does not exist: {path}")
    return image_path


class ImageOpacityPoC:
    def __init__(
        self,
        bottom_image: Path,
        top_image: Path,
        *,
        opacity: float,
        width: int,
        height: int,
        fullscreen: bool,
    ) -> None:
        self.bottom_image = bottom_image
        self.top_image = top_image
        self.opacity = max(0.0, min(1.0, opacity))
        self.width = width
        self.height = height
        self.fullscreen = fullscreen
        self.app = Gtk.Application(application_id="org.picframe.poc.imageopacity")
        self.app.connect("activate", self._on_activate)
        self.bottom_window: Gtk.ApplicationWindow | None = None
        self.top_window: Gtk.ApplicationWindow | None = None

    def run(self) -> int:
        return self.app.run([])

    def _on_activate(self, app: Gtk.Application) -> None:
        self._install_css()
        self.bottom_window = self._create_image_window(
            app,
            title="picframe-opacity-bottom",
            image_path=self.bottom_image,
            opacity=1.0,
            transparent=False,
        )
        self.top_window = self._create_image_window(
            app,
            title="picframe-opacity-top",
            image_path=self.top_image,
            opacity=self.opacity,
            transparent=True,
        )

        self._present_window(self.bottom_window)
        GLib.timeout_add(300, self._present_top_window)
        logger.info(
            "Showing bottom=%s and top=%s at opacity %.2f.",
            self.bottom_image,
            self.top_image,
            self.opacity,
        )

    def _install_css(self) -> None:
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(
            b"""
            window.transparent-window {
                background-color: rgba(0, 0, 0, 0);
            }
            window.opaque-window {
                background-color: black;
            }
            """
        )
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("No GDK display available. Are you running under Wayland/labwc?")
        Gtk.StyleContext.add_provider_for_display(
            display,
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _create_image_window(
        self,
        app: Gtk.Application,
        *,
        title: str,
        image_path: Path,
        opacity: float,
        transparent: bool,
    ) -> Gtk.ApplicationWindow:
        window = Gtk.ApplicationWindow(application=app, title=title)
        window.set_decorated(False)
        window.set_default_size(self.width, self.height)
        window.add_css_class("transparent-window" if transparent else "opaque-window")

        picture = Gtk.Picture.new_for_filename(str(image_path))
        picture.set_hexpand(True)
        picture.set_vexpand(True)
        picture.set_can_shrink(True)
        picture.set_opacity(opacity)
        if hasattr(Gtk, "ContentFit"):
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        window.set_child(picture)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self._on_key_pressed)
        window.add_controller(key_controller)
        return window

    def _present_window(self, window: Gtk.ApplicationWindow) -> None:
        if self.fullscreen:
            window.fullscreen()
        window.present()

    def _present_top_window(self) -> bool:
        if self.top_window is not None:
            self._present_window(self.top_window)
        return False

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_q, Gdk.KEY_Q):
            self.app.quit()
            return True
        return False


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Show two GTK4 image windows. The top window has a transparent "
            "background and draws its image at partial opacity."
        )
    )
    parser.add_argument("bottom_image", type=_existing_file)
    parser.add_argument("top_image", type=_existing_file)
    parser.add_argument(
        "--opacity",
        type=float,
        default=0.5,
        help="Opacity for the top image, from 0.0 to 1.0. Default: 0.5.",
    )
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Do not request fullscreen. Positioning is compositor-controlled on Wayland.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    args = parse_args(argv)
    poc = ImageOpacityPoC(
        args.bottom_image,
        args.top_image,
        opacity=args.opacity,
        width=args.width,
        height=args.height,
        fullscreen=not args.windowed,
    )
    return poc.run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
