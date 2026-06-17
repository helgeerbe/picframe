"""GStreamer pipeline builders used by the video worker."""

from __future__ import annotations

import logging
from typing import Any

from picframe.core.renderers.gtk_video_presenter import GtkVideoPresenter

logger = logging.getLogger(__name__)


class GstPipelineBuilder:
    """Builds GTK4 video pipelines and delegates presentation to GTK."""

    def __init__(self, gst: Any, presenter: GtkVideoPresenter) -> None:
        self._gst = gst
        self._presenter = presenter
        self.last_failure: str | None = None

    def build_gtk_playbin_pipeline(
        self,
        uri: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        fit_display: bool = False,
        host_background: list[float] | tuple[float, ...] | None = None,
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
    ) -> Any | None:
        self.last_failure = None
        Gtk = self._presenter._ensure_gtk()
        if Gtk is None:
            self.last_failure = self._presenter.last_failure or "GTK4 could not be initialized"
            return None

        playbin = self._gst.ElementFactory.make("playbin", "player")
        video_sink = self._gst.ElementFactory.make("gtk4paintablesink", "sink")
        audio_sink = self._gst.ElementFactory.make("fakesink", "audiosink")
        if playbin is None or video_sink is None or audio_sink is None:
            logger.warning(
                "Could not create playbin/gtk4paintablesink/fakesink elements."
            )
            self.last_failure = "Could not create playbin, gtk4paintablesink, or fakesink"
            return None

        self._presenter._set_property_if_supported(audio_sink, "sync", False)
        self._presenter._set_property_if_supported(video_sink, "show-preroll-frame", True)

        try:
            playbin.set_property("uri", uri)
            playbin.set_property("flags", 0x00000001)
            playbin.set_property("video-sink", video_sink)
            playbin.set_property("audio-sink", audio_sink)
        except Exception as exc:
            logger.warning("Could not configure GTK playbin pipeline: %s", exc)
            self.last_failure = f"Could not configure GTK playbin: {exc}"
            return None

        paintable = self._sink_paintable(video_sink)
        if paintable is None:
            return None

        self._presenter._configure_gtk_paintable(paintable)
        if not self._presenter.present_paintable(
            Gtk,
            video_sink,
            paintable,
            x,
            y,
            w,
            h,
            set_sink_window_size=True,
            content_fit=self._content_fit(
                fit_display,
                host_backdrop_path=host_backdrop_path,
            ),
            host_background=host_background,
            host_backdrop_path=host_backdrop_path,
            host_backdrop_rect=host_backdrop_rect,
        ):
            self.last_failure = (
                self._presenter.last_failure or "GTK4 paintable window presentation failed"
            )
            return None
        return playbin

    def build_gtk_compatible_pipeline_description(
        self,
        uri: str,
        w: int,
        h: int,
        *,
        force_software_decoders: bool,
        fit_display: bool = False,
    ) -> str:
        force_sw = " force-sw-decoders=true" if force_software_decoders else ""

        return (
            f'uridecodebin name=decoder uri="{uri}"{force_sw} '
            "decoder. ! "
            "queue name=video_queue ! "
            "videoconvert ! "
            "video/x-raw,format=RGBA,pixel-aspect-ratio=1/1 ! "
            "gtk4paintablesink name=sink"
        )

    def build_gtk_compatible_pipeline(
        self,
        uri: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        force_software_decoders: bool,
        fit_display: bool = False,
        host_background: list[float] | tuple[float, ...] | None = None,
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
    ) -> Any | None:
        self.last_failure = None
        Gtk = self._presenter._ensure_gtk()
        if Gtk is None:
            self.last_failure = self._presenter.last_failure or "GTK4 could not be initialized"
            return None

        _, _, widget_w, widget_h = self._presenter.video_widget_geometry(
            x,
            y,
            w,
            h,
        )
        pipeline_description = self.build_gtk_compatible_pipeline_description(
            uri,
            widget_w,
            widget_h,
            force_software_decoders=force_software_decoders,
            fit_display=fit_display,
        )
        logger.info(
            "GTK-compatible video pipeline for %s,%s %sx%s fit_display=%s: %s",
            x,
            y,
            w,
            h,
            fit_display,
            pipeline_description,
        )

        try:
            pipeline = self._gst.parse_launch(pipeline_description)
        except Exception as exc:
            logger.warning("Could not create GTK-compatible pipeline: %s", exc)
            self.last_failure = f"Could not create GTK-compatible pipeline: {exc}"
            return None

        try:
            video_sink = pipeline.get_by_name("sink")
        except Exception as exc:
            logger.warning("GTK-compatible pipeline did not expose a sink: %s", exc)
            self.last_failure = f"GTK-compatible pipeline did not expose a sink: {exc}"
            return None
        if video_sink is None:
            logger.warning("GTK-compatible pipeline did not expose a sink.")
            self.last_failure = "GTK-compatible pipeline did not expose a sink"
            return None

        self._presenter._set_property_if_supported(video_sink, "show-preroll-frame", True)
        paintable = self._sink_paintable(video_sink)
        if paintable is None:
            return None

        self._presenter._configure_gtk_paintable(paintable)
        if not self._presenter.present_paintable(
            Gtk,
            video_sink,
            paintable,
            x,
            y,
            w,
            h,
            set_sink_window_size=True,
            content_fit=self._content_fit(
                fit_display,
                host_backdrop_path=host_backdrop_path,
            ),
            host_background=host_background,
            host_backdrop_path=host_backdrop_path,
            host_backdrop_rect=host_backdrop_rect,
        ):
            self.last_failure = (
                self._presenter.last_failure or "GTK4 paintable window presentation failed"
            )
            return None
        return pipeline

    @staticmethod
    def _content_fit(fit_display: bool, *, host_backdrop_path: str | None) -> str:
        if fit_display or host_backdrop_path:
            return "fill"
        return "contain"

    def _sink_paintable(self, video_sink: Any) -> Any | None:
        try:
            paintable = video_sink.get_property("paintable")
        except Exception as exc:
            logger.warning("gtk4paintablesink did not provide a paintable: %s", exc)
            self.last_failure = f"gtk4paintablesink paintable lookup failed: {exc}"
            return None
        if paintable is None:
            logger.warning("gtk4paintablesink did not provide a paintable.")
            self.last_failure = "gtk4paintablesink did not provide a paintable"
            return None
        return paintable
