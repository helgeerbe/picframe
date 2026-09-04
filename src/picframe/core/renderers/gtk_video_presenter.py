"""GTK4 video presentation helpers for GStreamer playback."""

from __future__ import annotations

import logging
import os
from typing import Any

from picframe.core.renderers.gst_playback_policy import PlaybackPolicy

logger = logging.getLogger(__name__)

GTK_PRESENTATION_UNAVAILABLE_CODE = "gtk_presentation_unavailable"
EOS_GTK_WINDOW_OPACITY = 0.99
STARTUP_GTK_WINDOW_OPACITY = 0.0
GTK_TRANSPARENT_HOST_CLASS = "picframe-transparent-video-host"
GTK_OPAQUE_HOST_CLASS = "picframe-opaque-video-host"
GTK_PAUSE_OVERLAY_CLASS = "picframe-video-pause-overlay"


class GtkVideoPresenter:
    """Owns GTK4 window, host, paintable, and opacity handoff state."""

    def __init__(
        self,
        hardware_model: str,
        gst: Any,
        glib: Any,
        gi_module: Any,
        *,
        gst_available: bool,
    ) -> None:
        self._hardware_model = hardware_model
        self._gst = gst
        self._glib = glib
        self._gi = gi_module
        self._gst_available = gst_available
        self._gtk: Any | None = None
        self._gdk: Any | None = None
        self._gtk_window: Any = None
        self._gtk_host: Any = None
        self._gtk_sink_widget: Any = None
        self._gtk_video_sink: Any = None
        self._gtk_pause_label: Any = None
        self._gtk_pump_source_id: int | None = None
        self._gtk_presentation_failure: str | None = None

    @property
    def gtk(self) -> Any | None:
        return self._gtk

    @gtk.setter
    def gtk(self, value: Any | None) -> None:
        self._gtk = value

    @property
    def gdk(self) -> Any | None:
        return self._gdk

    @gdk.setter
    def gdk(self, value: Any | None) -> None:
        self._gdk = value

    @property
    def window(self) -> Any:
        return self._gtk_window

    @window.setter
    def window(self, value: Any) -> None:
        self._gtk_window = value

    @property
    def host(self) -> Any:
        return self._gtk_host

    @host.setter
    def host(self, value: Any) -> None:
        self._gtk_host = value

    @property
    def sink_widget(self) -> Any:
        return self._gtk_sink_widget

    @sink_widget.setter
    def sink_widget(self, value: Any) -> None:
        self._gtk_sink_widget = value

    @property
    def video_sink(self) -> Any:
        return self._gtk_video_sink

    @video_sink.setter
    def video_sink(self, value: Any) -> None:
        self._gtk_video_sink = value

    @property
    def pump_source_id(self) -> int | None:
        return self._gtk_pump_source_id

    @pump_source_id.setter
    def pump_source_id(self, value: int | None) -> None:
        self._gtk_pump_source_id = value

    @property
    def last_failure(self) -> str | None:
        return self._gtk_presentation_failure

    @last_failure.setter
    def last_failure(self, value: str | None) -> None:
        self._gtk_presentation_failure = value

    def present_paintable(
        self,
        Gtk: Any,
        video_sink: Any,
        paintable: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        set_sink_window_size: bool,
        content_fit: str,
        host_background: list[float] | tuple[float, ...] | None = None,
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
    ) -> bool:
        return self._present_gtk_paintable_sink(
            Gtk,
            video_sink,
            paintable,
            x,
            y,
            w,
            h,
            set_sink_window_size=set_sink_window_size,
            content_fit=content_fit,
            host_background=host_background,
            host_backdrop_path=host_backdrop_path,
            host_backdrop_rect=host_backdrop_rect,
        )

    def reveal(self) -> None:
        self._reveal_gtk_video_window()

    def apply_eos_opacity_probe(self, pipeline: Any) -> None:
        self._apply_gtk_eos_opacity_probe(pipeline)

    def set_pause_overlay(self, visible: bool, text: str = "") -> None:
        label = self._gtk_pause_label
        if label is None:
            return
        try:
            if visible and text:
                set_label = getattr(label, "set_label", None)
                if callable(set_label):
                    set_label(text)
            set_visible = getattr(label, "set_visible", None)
            if callable(set_visible):
                set_visible(bool(visible))
            if visible and self._gtk_window is not None:
                present = getattr(self._gtk_window, "present", None)
                if callable(present):
                    present()
            self._pump_gtk_events()
        except Exception as exc:
            logger.debug("Could not update GTK pause overlay: %s", exc)

    def destroy(self) -> None:
        self._destroy_gtk_video_window()

    def video_widget_geometry(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> tuple[int, int, int, int]:
        return self._gtk_video_widget_geometry(x, y, w, h)

    def _ensure_gtk(self) -> Any | None:
        if self._gtk is not None:
            return self._gtk
        try:
            Gtk, Gdk = self._init_gtk4()
        except Exception as exc:
            logger.warning("GTK4 unavailable for gtk4paintablesink presentation: %s", exc)
            self._gtk_presentation_failure = f"GTK4 initialization failed: {exc}"
            return None
        self._gtk = Gtk
        self._gdk = Gdk
        self._gtk_presentation_failure = None
        return self._gtk

    def _init_gtk4(self) -> tuple[Any, Any]:
        self._gi.require_version("Gtk", "4.0")
        self._gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, Gtk

        self._initialize_gtk(Gtk)
        return Gtk, Gdk

    @staticmethod
    def _initialize_gtk(Gtk: Any) -> None:
        if hasattr(Gtk, "init_check"):
            try:
                init_result = Gtk.init_check()
            except TypeError:
                init_result = Gtk.init_check([])
            gtk_initialized = (
                bool(init_result[0]) if isinstance(init_result, tuple) else bool(init_result)
            )
            if not gtk_initialized:
                raise RuntimeError("Gtk.init_check returned False")
        else:
            try:
                Gtk.init()
            except TypeError:
                Gtk.init([])

    @staticmethod
    def _set_property_if_supported(element: Any, property_name: str, value: Any) -> None:
        if element is None:
            return
        try:
            if element.find_property(property_name) is None:
                return
        except Exception:
            return
        try:
            element.set_property(property_name, value)
        except Exception as exc:
            logger.debug("Could not set %s on %s: %s", property_name, element, exc)

    def _present_gtk_paintable_sink(
        self,
        Gtk: Any,
        video_sink: Any,
        paintable: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        set_sink_window_size: bool,
        content_fit: str,
        host_background: list[float] | tuple[float, ...] | None = None,
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
    ) -> bool:
        has_backdrop = bool(host_backdrop_path)
        fullscreen_video = self._gtk_geometry_is_fullscreen(x, y, w, h)
        transparent_host = (
            self._gtk_video_host_uses_transparency() and fullscreen_video and not has_backdrop
        )
        fixed_host = True
        _, _, widget_w, widget_h = self._gtk_video_widget_geometry(
            x,
            y,
            w,
            h,
        )
        picture = self._create_gtk_video_picture(Gtk, paintable, content_fit=content_fit)
        widget = picture

        self._pin_gtk_video_widget(Gtk, widget)

        if set_sink_window_size:
            self._set_property_if_supported(video_sink, "window-width", widget_w)
            self._set_property_if_supported(video_sink, "window-height", widget_h)
        logger.info(
            "GTK4 video paintable content-fit=%s widget-size=%sx%s.",
            content_fit,
            widget_w,
            widget_h,
        )
        try:
            widget.set_size_request(widget_w, widget_h)
        except Exception:
            pass
        window = Gtk.Window(title="picframe-video")
        self._configure_gtk_video_window(window, transparent=transparent_host)
        self._configure_gtk_video_host_background(
            window,
            transparent=transparent_host,
            host_background=host_background,
        )
        host = None
        if fixed_host:
            host_x, host_y, host_w, host_h = self._gtk_fixed_host_child_rect(
                x,
                y,
                w,
                h,
                fullscreen=fullscreen_video,
                transparent=transparent_host,
            )
            host = self._create_gtk_fixed_video_host(
                Gtk,
                window,
                widget,
                host_x,
                host_y,
                host_w,
                host_h,
                transparent=transparent_host,
                host_background=host_background,
                host_backdrop_path=host_backdrop_path,
                host_backdrop_rect=host_backdrop_rect,
            )
            window.set_child(host)
            self._apply_gtk_host_window_geometry(window, x, y, w, h)
        else:
            window.set_child(widget)
            self._apply_gtk_window_geometry(
                window,
                x,
                y,
                w,
                h,
                fullscreen=fullscreen_video,
                widget=widget,
            )
        self._present_gtk_video_window(
            window,
            fullscreen=fullscreen_video or fixed_host,
            opacity=STARTUP_GTK_WINDOW_OPACITY,
        )
        self._log_gtk_window_diagnostics(
            window,
            widget,
            x,
            y,
            w,
            h,
            fullscreen_video,
            fixed_host=fixed_host,
            host_transparent=transparent_host,
        )
        self._hide_gtk_cursor(window, widget)

        if not self._gtk_window_matches_geometry(
            window,
            x,
            y,
            w,
            h,
            fullscreen=fullscreen_video,
            widget=widget,
            fixed_host=fixed_host,
            host_transparent=transparent_host,
        ):
            logger.warning(
                "GTK video window geometry did not match requested "
                "%s,%s %sx%s; continuing with GTK4 presentation.",
                x,
                y,
                w,
                h,
            )

        self._gtk_window = window
        self._gtk_host = host
        self._gtk_sink_widget = widget
        self._gtk_video_sink = video_sink
        self._start_gtk_pump()
        logger.info("GTK4 video window geometry confirmed at %s,%s %sx%s.", x, y, w, h)
        return True

    def _create_gtk_video_picture(
        self,
        Gtk: Any,
        paintable: Any,
        *,
        content_fit: str = "contain",
    ) -> Any:
        if hasattr(Gtk.Picture, "new_for_paintable"):
            picture = Gtk.Picture.new_for_paintable(paintable)
        else:
            picture = Gtk.Picture()
            picture.set_paintable(paintable)
        try:
            picture.set_can_shrink(True)
        except Exception:
            pass
        if hasattr(Gtk, "ContentFit"):
            try:
                fit = Gtk.ContentFit.FILL if content_fit == "fill" else Gtk.ContentFit.CONTAIN
                picture.set_content_fit(fit)
            except Exception:
                pass
        else:
            try:
                picture.set_keep_aspect_ratio(content_fit != "fill")
            except Exception:
                pass
        return picture

    @staticmethod
    def _pin_gtk_video_widget(Gtk: Any, widget: Any) -> None:
        try:
            widget.set_hexpand(True)
            widget.set_vexpand(True)
        except Exception:
            pass
        try:
            widget.set_halign(Gtk.Align.START)
            widget.set_valign(Gtk.Align.START)
        except Exception:
            pass

    def _configure_gtk_paintable(self, paintable: Any) -> None:
        self._set_property_if_supported(paintable, "force-aspect-ratio", True)
        try:
            force_aspect_ratio = paintable.get_property("force-aspect-ratio")
        except Exception:
            force_aspect_ratio = "unknown"
        logger.info("GTK4 paintable force-aspect-ratio=%s.", force_aspect_ratio)

    def _gtk_geometry_is_fullscreen(self, x: int, y: int, w: int, h: int) -> bool:
        if x != 0 or y != 0:
            return False
        if w <= 0 or h <= 0:
            return True

        monitor_geometry = self._gtk_primary_monitor_geometry()
        if monitor_geometry is None:
            return False
        monitor_x, monitor_y, monitor_w, monitor_h = monitor_geometry
        return monitor_x == 0 and monitor_y == 0 and monitor_w == w and monitor_h == h

    def _gtk_primary_monitor_geometry(self) -> tuple[int, int, int, int] | None:
        monitor = self._gtk_primary_monitor()
        if monitor is None:
            return None
        try:
            geometry = monitor.get_geometry()
            return (
                int(getattr(geometry, "x", 0)),
                int(getattr(geometry, "y", 0)),
                int(getattr(geometry, "width")),
                int(getattr(geometry, "height")),
            )
        except Exception:
            return None

    def _gtk_primary_monitor(self) -> Any | None:
        Gdk = self._gdk
        if Gdk is None:
            return None
        try:
            display = Gdk.Display.get_default()
            if display is None:
                return None
            monitor = None
            if hasattr(display, "get_primary_monitor"):
                monitor = display.get_primary_monitor()
            if monitor is None and hasattr(display, "get_monitor"):
                monitor = display.get_monitor(0)
            if monitor is None and hasattr(display, "get_monitors"):
                monitors = display.get_monitors()
                if hasattr(monitors, "get_item"):
                    monitor = monitors.get_item(0)
                elif hasattr(monitors, "__getitem__"):
                    monitor = monitors[0]
            return monitor
        except Exception:
            return None

    def _configure_gtk_video_window(self, window: Any, *, transparent: bool = True) -> None:
        window.set_decorated(False)
        set_app_paintable = getattr(window, "set_app_paintable", None)
        if callable(set_app_paintable):
            set_app_paintable(transparent)
        for method_name, value in (
            ("set_deletable", False),
            ("set_resizable", False),
            ("set_hide_on_close", True),
            ("set_skip_taskbar_hint", True),
            ("set_skip_pager_hint", True),
            ("set_focusable", True),
            ("set_can_focus", True),
            ("set_focus_on_map", True),
        ):
            method = getattr(window, method_name, None)
            if not callable(method):
                continue
            try:
                method(value)
            except Exception:
                pass

    def _gtk_video_host_uses_transparency(self) -> bool:
        if PlaybackPolicy.raspberry_pi_model_family(self._hardware_model) is not None:
            return True
        desktop_text = " ".join(
            os.environ.get(name, "")
            for name in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "WAYLAND_DISPLAY")
        ).lower()
        if "labwc" in desktop_text:
            return True
        return self._find_labwc_pid() is not None

    @staticmethod
    def _find_labwc_pid() -> int | None:
        pid = os.getpid()
        seen: set[int] = set()
        while pid > 1 and pid not in seen:
            seen.add(pid)
            try:
                with open(f"/proc/{pid}/comm", encoding="utf-8") as comm_file:
                    comm = comm_file.read().strip()
                if comm == "labwc":
                    return pid
                with open(f"/proc/{pid}/status", encoding="utf-8") as status_file:
                    status = status_file.read()
            except OSError:
                return None

            parent_pid = None
            for line in status.splitlines():
                if line.startswith("PPid:"):
                    try:
                        parent_pid = int(line.split()[1])
                    except (IndexError, ValueError):
                        return None
                    break
            if parent_pid is None or parent_pid == pid:
                return None
            pid = parent_pid
        return None

    def _configure_gtk_video_host_background(
        self,
        window: Any,
        *,
        transparent: bool,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> None:
        Gdk = self._gdk
        Gtk = self._gtk
        if Gdk is None or Gtk is None:
            return
        self._set_gtk_video_host_background(
            window,
            transparent=transparent,
            host_background=host_background,
        )
        logger.info(
            "GTK video host background=%s.",
            "transparent" if transparent else self._gtk_opaque_host_background_css(host_background),
        )

    def _set_gtk_video_host_background(
        self,
        widget: Any,
        *,
        transparent: bool,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> None:
        Gdk = self._gdk
        Gtk = self._gtk
        if Gdk is None or Gtk is None:
            return
        try:
            display = Gdk.Display.get_default()
            if display is None:
                return
            opaque_background = self._gtk_opaque_host_background_css(host_background)
            css_provider = Gtk.CssProvider()
            css_provider.load_from_data(
                f"""
                window.{GTK_TRANSPARENT_HOST_CLASS},
                .{GTK_TRANSPARENT_HOST_CLASS} {{
                    background-color: rgba(0, 0, 0, 0);
                }}
                window.{GTK_OPAQUE_HOST_CLASS},
                .{GTK_OPAQUE_HOST_CLASS} {{
                    background-color: {opaque_background};
                }}
                .{GTK_PAUSE_OVERLAY_CLASS} {{
                    color: rgba(255, 255, 255, 0.96);
                    background-color: rgba(0, 0, 0, 0.58);
                    border-radius: 6px;
                    font-size: 42px;
                    font-weight: 700;
                    padding: 10px 24px;
                }}
                """.encode()
            )
            Gtk.StyleContext.add_provider_for_display(
                display,
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            selected_class = GTK_TRANSPARENT_HOST_CLASS if transparent else GTK_OPAQUE_HOST_CLASS
            remove_css_class = getattr(widget, "remove_css_class", None)
            if callable(remove_css_class):
                remove_css_class(GTK_TRANSPARENT_HOST_CLASS)
                remove_css_class(GTK_OPAQUE_HOST_CLASS)
            add_css_class = getattr(widget, "add_css_class", None)
            if callable(add_css_class):
                add_css_class(selected_class)
        except Exception as exc:
            logger.debug("Could not configure GTK video host background: %s", exc)

    @staticmethod
    def _gtk_opaque_host_background_css(
        host_background: list[float] | tuple[float, ...] | None,
    ) -> str:
        try:
            if host_background is None or len(host_background) < 3:
                return "rgba(0, 0, 0, 1)"
            rgb = tuple(float(host_background[index]) for index in range(3))
        except (TypeError, ValueError):
            return "rgba(0, 0, 0, 1)"
        channels = tuple(round(max(0.0, min(1.0, value)) * 255) for value in rgb)
        return f"rgba({channels[0]}, {channels[1]}, {channels[2]}, 1)"

    def _create_gtk_fixed_video_host(
        self,
        Gtk: Any,
        window: Any,
        widget: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        transparent: bool = True,
        host_background: list[float] | tuple[float, ...] | None = None,
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
    ) -> Any:
        host = Gtk.Fixed()
        self._gtk_pause_label = None
        widget_x, widget_y, widget_w, widget_h = self._gtk_video_widget_geometry(
            x,
            y,
            w,
            h,
        )
        self._set_gtk_video_host_background(
            host,
            transparent=transparent,
            host_background=host_background,
        )
        try:
            host.set_hexpand(True)
            host.set_vexpand(True)
        except Exception:
            pass
        self._pin_gtk_video_widget(Gtk, widget)
        try:
            widget.set_size_request(widget_w, widget_h)
        except Exception:
            pass
        try:
            _, _, host_w, host_h = self._gtk_video_host_geometry(x, y, w, h)
            window.set_default_size(host_w, host_h)
            host.set_size_request(host_w, host_h)
        except Exception:
            host_w, host_h = max(1, w), max(1, h)
        if host_backdrop_path:
            backdrop = self._create_gtk_backdrop_picture(
                Gtk,
                host_backdrop_path,
                host_backdrop_rect,
                fallback_size=(host_w, host_h),
            )
            if backdrop is not None:
                backdrop_x, backdrop_y, backdrop_w, backdrop_h = self._normalize_gtk_rect(
                    host_backdrop_rect, (0, 0, host_w, host_h)
                )
                try:
                    backdrop.set_size_request(backdrop_w, backdrop_h)
                except Exception:
                    pass
                try:
                    host.put(backdrop, backdrop_x, backdrop_y)
                except Exception:
                    logger.debug(
                        "Could not place GTK video backdrop at %s,%s.",
                        backdrop_x,
                        backdrop_y,
                    )
        try:
            host.put(widget, widget_x, widget_y)
        except Exception:
            logger.warning(
                "Could not place GTK video widget at %s,%s; custom geometry may fail.",
                widget_x,
                widget_y,
            )
        pause_label = self._create_gtk_pause_label(Gtk, "PAUSED", host_w, host_h)
        if pause_label is not None:
            label_w, label_h = self._gtk_pause_overlay_size(host_w, host_h)
            label_x = max(0, (host_w - label_w) // 2)
            label_y = max(0, (host_h - label_h) // 2)
            try:
                host.put(pause_label, label_x, label_y)
                self._gtk_pause_label = pause_label
            except Exception:
                logger.debug(
                    "Could not place GTK pause overlay at %s,%s.",
                    label_x,
                    label_y,
                )
        return host

    @staticmethod
    def _gtk_pause_overlay_size(host_w: int, host_h: int) -> tuple[int, int]:
        width = min(max(220, host_w // 5), max(1, host_w))
        height = min(max(72, host_h // 9), max(1, host_h))
        return width, height

    def _create_gtk_pause_label(
        self,
        Gtk: Any,
        text: str,
        host_w: int,
        host_h: int,
    ) -> Any | None:
        try:
            label = Gtk.Label(label=text)
            label_w, label_h = self._gtk_pause_overlay_size(host_w, host_h)
            try:
                label.set_size_request(label_w, label_h)
            except Exception:
                pass
            for method_name, value in (
                ("set_xalign", 0.5),
                ("set_yalign", 0.5),
            ):
                method = getattr(label, method_name, None)
                if callable(method):
                    try:
                        method(value)
                    except Exception:
                        pass
            justification = getattr(getattr(Gtk, "Justification", None), "CENTER", None)
            set_justify = getattr(label, "set_justify", None)
            if callable(set_justify) and justification is not None:
                try:
                    set_justify(justification)
                except Exception:
                    pass
            add_css_class = getattr(label, "add_css_class", None)
            if callable(add_css_class):
                add_css_class(GTK_PAUSE_OVERLAY_CLASS)
            set_can_target = getattr(label, "set_can_target", None)
            if callable(set_can_target):
                set_can_target(False)
            label.set_visible(False)
            return label
        except Exception as exc:
            logger.debug("Could not create GTK pause overlay label: %s", exc)
            return None

    def _create_gtk_backdrop_picture(
        self,
        Gtk: Any,
        path: str,
        rect: tuple[int, int, int, int] | list[int] | None,
        *,
        fallback_size: tuple[int, int],
    ) -> Any | None:
        if not os.path.exists(path):
            logger.debug("GTK video backdrop does not exist: %s", path)
            return None
        try:
            if hasattr(Gtk.Picture, "new_for_filename"):
                picture = Gtk.Picture.new_for_filename(path)
            else:
                picture = Gtk.Picture()
                set_filename = getattr(picture, "set_filename", None)
                if not callable(set_filename):
                    return None
                set_filename(path)
            _, _, width, height = self._normalize_gtk_rect(
                rect,
                (0, 0, fallback_size[0], fallback_size[1]),
            )
            try:
                picture.set_size_request(width, height)
            except Exception:
                pass
            if hasattr(Gtk, "ContentFit"):
                try:
                    picture.set_content_fit(Gtk.ContentFit.FILL)
                except Exception:
                    pass
            else:
                try:
                    picture.set_keep_aspect_ratio(False)
                except Exception:
                    pass
            return picture
        except Exception as exc:
            logger.debug("Could not create GTK video backdrop: %s", exc)
            return None

    @staticmethod
    def _normalize_gtk_rect(
        rect: tuple[int, int, int, int] | list[int] | None,
        fallback: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        try:
            if rect is None or len(rect) != 4:
                return fallback
            x, y, w, h = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
            if w <= 0 or h <= 0:
                return fallback
            return x, y, w, h
        except (TypeError, ValueError, IndexError):
            return fallback

    def _apply_gtk_eos_opacity_probe(self, pipeline: Any) -> None:
        if self._gtk_window is None:
            return
        try:
            if pipeline is not None:
                pipeline.set_state(self._gst.State.PAUSED)
        except Exception as exc:
            logger.debug("Could not pause GTK4 video pipeline at EOS: %s", exc)
        try:
            set_opacity = getattr(self._gtk_window, "set_opacity", None)
            if not callable(set_opacity):
                return
            logger.info(
                "GTK4 EOS opacity probe: setting window opacity to %.3f.",
                EOS_GTK_WINDOW_OPACITY,
            )
            set_opacity(EOS_GTK_WINDOW_OPACITY)
            self._pump_gtk_events()
        except Exception as exc:
            logger.debug("Could not apply GTK4 EOS opacity probe: %s", exc)

    def _gtk_video_host_geometry(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> tuple[int, int, int, int]:
        monitor_geometry = self._gtk_primary_monitor_geometry()
        if monitor_geometry is not None:
            return monitor_geometry
        return (0, 0, max(1, w, x + w), max(1, h, y + h))

    def _gtk_video_widget_geometry(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> tuple[int, int, int, int]:
        if w > 0 and h > 0:
            return (x, y, w, h)
        _, _, host_w, host_h = self._gtk_video_host_geometry(x, y, w, h)
        return (0, 0, host_w, host_h)

    def _gtk_fixed_host_child_rect(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        fullscreen: bool,
        transparent: bool,
    ) -> tuple[int, int, int, int]:
        if fullscreen and not transparent:
            _, _, host_w, host_h = self._gtk_video_host_geometry(x, y, w, h)
            return (0, 0, host_w, host_h)
        return (x, y, w, h)

    def _apply_gtk_host_window_geometry(
        self,
        window: Any,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> None:
        _, _, host_w, host_h = self._gtk_video_host_geometry(x, y, w, h)
        self._apply_gtk_window_geometry(
            window,
            0,
            0,
            host_w,
            host_h,
            fullscreen=True,
        )

    @staticmethod
    def _apply_gtk_window_geometry(
        window: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        fullscreen: bool,
        widget: Any | None = None,
    ) -> None:
        if fullscreen:
            if w > 0 and h > 0:
                window.set_default_size(w, h)
                if widget is not None:
                    try:
                        widget.set_size_request(w, h)
                    except Exception:
                        pass
            set_fullscreened = getattr(window, "set_fullscreened", None)
            if callable(set_fullscreened):
                set_fullscreened(True)
            window.fullscreen()
            return
        if widget is not None:
            try:
                widget.set_size_request(w, h)
            except Exception:
                pass
        window.set_default_size(w, h)

    def _present_gtk_video_window(
        self,
        window: Any,
        *,
        fullscreen: bool,
        opacity: float = 1.0,
    ) -> None:
        try:
            set_opacity = getattr(window, "set_opacity", None)
            if callable(set_opacity):
                set_opacity(opacity)
            if fullscreen:
                set_fullscreened = getattr(window, "set_fullscreened", None)
                if callable(set_fullscreened):
                    set_fullscreened(True)
                window.fullscreen()
            present = getattr(window, "present", None)
            if callable(present):
                present()
            self._focus_gtk_video_window(window)
            if fullscreen:
                self._pump_gtk_events()
                window.fullscreen()
                if callable(present):
                    present()
                self._focus_gtk_video_window(window)
        except Exception as exc:
            logger.debug("Could not present GTK video window: %s", exc)
        self._pump_gtk_events()

    def _reveal_gtk_video_window(self) -> None:
        window = self._gtk_window
        if window is None:
            return
        try:
            set_opacity = getattr(window, "set_opacity", None)
            if callable(set_opacity):
                set_opacity(1.0)
            present = getattr(window, "present", None)
            if callable(present):
                present()
            self._focus_gtk_video_window(window)
        except Exception as exc:
            logger.debug("Could not reveal GTK video window: %s", exc)
        self._pump_gtk_events()

    @staticmethod
    def _focus_gtk_video_window(window: Any) -> None:
        for method_name in ("grab_focus", "present"):
            method = getattr(window, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass

    def _log_gtk_window_diagnostics(
        self,
        window: Any,
        widget: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        fullscreen: bool,
        *,
        fixed_host: bool = False,
        host_transparent: bool = True,
    ) -> None:
        try:
            actual_w, actual_h = window.get_size()
        except Exception:
            actual_w, actual_h = None, None
        try:
            actual_x, actual_y = window.get_position()
        except Exception:
            actual_x, actual_y = None, None
        try:
            allocation = widget.get_allocation()
            widget_w = int(getattr(allocation, "width"))
            widget_h = int(getattr(allocation, "height"))
        except Exception:
            widget_w, widget_h = None, None
        try:
            widget_pos = widget.translate_coordinates(window, 0, 0)
            if widget_pos is None:
                widget_x, widget_y = None, None
            else:
                widget_x, widget_y = int(widget_pos[0]), int(widget_pos[1])
        except Exception:
            widget_x, widget_y = None, None

        logger.info(
            "GTK video window mode=%s requested=%s,%s %sx%s actual=%s,%s %sx%s "
            "widget=%sx%s widget_at=%s,%s",
            "fullscreen" if fullscreen else "custom",
            x,
            y,
            w,
            h,
            actual_x,
            actual_y,
            actual_w,
            actual_h,
            widget_w,
            widget_h,
            widget_x,
            widget_y,
        )
        if fixed_host:
            logger.info(
                "GTK video uses monitor-sized %s host with fixed child placement.",
                "transparent" if host_transparent else "opaque",
            )

    def _hide_gtk_cursor(self, window: Any, widget: Any) -> None:
        try:
            for target in (widget, window):
                set_cursor_from_name = getattr(target, "set_cursor_from_name", None)
                if callable(set_cursor_from_name):
                    set_cursor_from_name("none")
        except Exception as exc:
            logger.debug("Could not hide GTK video cursor: %s", exc)

    def _gtk_window_matches_geometry(
        self,
        window: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        fullscreen: bool = False,
        widget: Any | None = None,
        fixed_host: bool = False,
        host_transparent: bool = True,
    ) -> bool:
        self._pump_gtk_events()
        if fixed_host:
            if fullscreen:
                return True
            if widget is None:
                return False
            expected_x, expected_y, expected_w, expected_h = self._gtk_fixed_host_child_rect(
                x,
                y,
                w,
                h,
                fullscreen=fullscreen,
                transparent=host_transparent,
            )
            try:
                allocation = widget.get_allocation()
                widget_w = int(getattr(allocation, "width"))
                widget_h = int(getattr(allocation, "height"))
            except Exception:
                return False
            if widget_w != expected_w or widget_h != expected_h:
                return False
            try:
                widget_pos = widget.translate_coordinates(window, 0, 0)
            except Exception:
                widget_pos = None
            if widget_pos is None:
                return True
            return int(widget_pos[0]) == expected_x and int(widget_pos[1]) == expected_y

        if fullscreen:
            return True

        return True

    def _start_gtk_pump(self) -> None:
        if self._gtk_pump_source_id is not None or not self._gst_available:
            return
        try:
            self._gtk_pump_source_id = self._glib.timeout_add(16, self._pump_gtk_events_tick)
        except Exception:
            self._gtk_pump_source_id = None

    def _stop_gtk_pump(self) -> None:
        if self._gtk_pump_source_id is None or not self._gst_available:
            return
        try:
            self._glib.source_remove(self._gtk_pump_source_id)
        except Exception:
            pass
        self._gtk_pump_source_id = None

    def _pump_gtk_events_tick(self) -> bool:
        self._pump_gtk_events()
        return self._gtk_window is not None

    def _pump_gtk_events(self) -> None:
        if self._gtk is None:
            return
        try:
            context = self._glib.MainContext.default()
            while context.pending():
                context.iteration(False)
        except Exception:
            pass

    def _destroy_gtk_video_window(self) -> None:
        self._stop_gtk_pump()
        if self._gtk_window is not None:
            try:
                set_visible = getattr(self._gtk_window, "set_visible", None)
                if callable(set_visible):
                    set_visible(False)
                self._gtk_window.destroy()
            except Exception as exc:
                logger.debug("Could not destroy GTK video window: %s", exc)
        self._gtk_window = None
        self._gtk_host = None
        self._gtk_sink_widget = None
        self._gtk_video_sink = None
        self._gtk_pause_label = None
        self._pump_gtk_events()
