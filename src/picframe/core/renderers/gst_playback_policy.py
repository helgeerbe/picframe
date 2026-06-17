"""Playback policy for GStreamer video pipelines."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from picframe.core.renderers.gst_utils import find_best_element

logger = logging.getLogger(__name__)

PIPELINE_COMPATIBLE = "compatible"
PIPELINE_HARDWARE_DIRECT = "hardware_direct"
PIPELINE_HARDWARE_PLAYBIN = "hardware_playbin"
PIPELINE_GTK_PLAYBIN = "gtk_playbin"
PIPELINE_GTK_COMPATIBLE = "gtk_compatible"
PIPELINE_SKIPPED = "skipped"
DEFAULT_SOFTWARE_DECODE_LIMIT = "1280x720"
UNSUPPORTED_MEDIA_CODE = "unsupported_media"


@dataclass(frozen=True)
class DecodeResolutionLimit:
    width: int
    height: int


@dataclass(frozen=True)
class DecodeHardwareLimit:
    width: int
    height: int
    max_fps: float | None
    model_family: str
    source: str


@dataclass(frozen=True)
class VideoStreamFacts:
    caps: Any | None
    caps_string: str | None
    codec: str | None
    width: int | None
    height: int | None
    framerate: float | None = None
    container: str | None = None


@dataclass(frozen=True)
class PlaybackDecision:
    pipeline_variant: str
    force_software_decoders: bool
    decision: str
    fallback_reason: str | None = None
    skip_reason: str | None = None
    error_code: str | None = None
    hardware_limit: str | None = None
    software_limit: str | None = None


RPI_HARDWARE_DECODE_LIMITS: dict[str, dict[str, DecodeHardwareLimit]] = {
    "pi5": {
        "h265": DecodeHardwareLimit(
            width=3840,
            height=2160,
            max_fps=60.0,
            model_family="Raspberry Pi 5 / Compute Module 5",
            source="official",
        ),
    },
    "pi4": {
        "h264": DecodeHardwareLimit(
            width=1920,
            height=1080,
            max_fps=60.0,
            model_family="Raspberry Pi 4 / 400 / Compute Module 4",
            source="official",
        ),
        "h265": DecodeHardwareLimit(
            width=3840,
            height=2160,
            max_fps=60.0,
            model_family="Raspberry Pi 4 / 400 / Compute Module 4",
            source="official",
        ),
    },
    "pi3": {
        "h264": DecodeHardwareLimit(
            width=1920,
            height=1080,
            max_fps=30.0,
            model_family="Raspberry Pi 3 / Compute Module 3",
            source="official",
        ),
    },
    "zero2": {
        "h264": DecodeHardwareLimit(
            width=1920,
            height=1080,
            max_fps=30.0,
            model_family="Raspberry Pi Zero 2 W",
            source="official",
        ),
    },
    "zero": {
        "h264": DecodeHardwareLimit(
            width=1920,
            height=1080,
            max_fps=30.0,
            model_family="Raspberry Pi Zero / Zero W / Zero WH",
            source="official",
        ),
    },
}


class GstHardwareSupport:
    """Small adapter around the GStreamer registry for decoder availability."""

    def __init__(
        self,
        gst: Any,
        find_element: Callable[[list[str]], str | None] = find_best_element,
    ) -> None:
        self._gst = gst
        self._find_element = find_element

    def hardware_decode_available_for_facts(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        if stream_facts is None or stream_facts.caps is None:
            return False
        codec = PlaybackPolicy.normalized_codec(
            stream_facts.codec,
        ) or PlaybackPolicy.codec_from_caps_string(stream_facts.caps_string)
        if codec == "h264":
            return self._find_element(["v4l2h264dec", "v4l2slh264dec"]) is not None
        if codec == "h265":
            return self._find_element(["v4l2slh265dec"]) is not None
        return self.hardware_decode_available_for_caps(stream_facts.caps)

    def hardware_decode_available_for_caps(self, caps: Any) -> bool:
        caps_str = caps.to_string()
        if "video/x-h264" in caps_str and self._find_element(
            ["v4l2h264dec", "v4l2slh264dec"]
        ):
            return True
        if "video/x-h265" in caps_str and self._find_element(["v4l2slh265dec"]):
            return True

        registry = self._gst.Registry.get()
        factories = registry.get_feature_list(self._gst.ElementFactory)
        for factory in factories:
            klass = factory.get_metadata(self._gst.ELEMENT_METADATA_KLASS)
            if not (klass and "Decoder" in klass and "Video" in klass and "Hardware" in klass):
                continue
            for template in factory.get_static_pad_templates():
                if template.direction != self._gst.PadDirection.SINK:
                    continue
                template_caps = template.get_caps()
                if template_caps and template_caps.can_intersect(caps):
                    return True
        return False


class PlaybackPolicy:
    """Selects the safe playback path for a video stream."""

    def __init__(
        self,
        hardware_model: str,
        hardware_decode_available_for_facts: Callable[[VideoStreamFacts | None], bool],
    ) -> None:
        self._hardware_model = hardware_model
        self._hardware_decode_available_for_facts = hardware_decode_available_for_facts

    def select_pipeline_variant(
        self,
        uri: str,
        sink_name: str,
        force_software_decoders: bool,
        stream_facts: VideoStreamFacts | None = None,
        max_software_decode_resolution: str | None = None,
    ) -> str:
        return self.select_playback_decision(
            uri,
            sink_name,
            force_software_decoders=force_software_decoders,
            max_software_decode_resolution=max_software_decode_resolution,
            stream_facts=stream_facts,
        ).pipeline_variant

    def select_playback_decision(
        self,
        uri: str,
        sink_name: str,
        *,
        force_software_decoders: bool,
        max_software_decode_resolution: str | None,
        stream_facts: VideoStreamFacts | None,
        fallback_reason: str | None = None,
    ) -> PlaybackDecision:
        software_limit = self.software_decode_limit(max_software_decode_resolution)
        software_limit_str = self.format_resolution_limit(software_limit)
        hardware_limit = self.known_hardware_decode_limit(stream_facts)
        hardware_limit_str = self.format_hardware_limit(hardware_limit)
        software_allowed = self.within_resolution_limit(
            stream_facts,
            software_limit,
            allow_rotation=True,
        )

        if force_software_decoders and self.requires_pi_hardware_only(stream_facts):
            return self.skip_decision(
                stream_facts,
                hardware_limit_str,
                software_limit_str,
                fallback_reason or "hardware_presentation_unsupported",
            )

        if force_software_decoders:
            if not software_allowed:
                return self.skip_decision(
                    stream_facts,
                    hardware_limit_str,
                    software_limit_str,
                    "software_limit_exceeded",
                )
            return PlaybackDecision(
                pipeline_variant=PIPELINE_COMPATIBLE,
                force_software_decoders=True,
                decision="software_fallback",
                fallback_reason=fallback_reason or "software_fallback",
                hardware_limit=hardware_limit_str,
                software_limit=software_limit_str,
            )

        hardware_rejection_reason = self.hardware_limit_rejection_reason(
            stream_facts,
            hardware_limit,
        )
        if hardware_rejection_reason is not None:
            if self.requires_pi_hardware_only(stream_facts):
                return self.skip_decision(
                    stream_facts,
                    hardware_limit_str,
                    software_limit_str,
                    hardware_rejection_reason,
                )
            if software_allowed:
                return PlaybackDecision(
                    pipeline_variant=PIPELINE_COMPATIBLE,
                    force_software_decoders=True,
                    decision="software_fallback",
                    fallback_reason=hardware_rejection_reason,
                    hardware_limit=hardware_limit_str,
                    software_limit=software_limit_str,
                )
            return self.skip_decision(
                stream_facts,
                hardware_limit_str,
                software_limit_str,
                hardware_rejection_reason,
            )

        hardware_available = self._hardware_decode_available_for_facts(stream_facts)
        if not hardware_available:
            if self.requires_pi_hardware_only(stream_facts):
                return self.skip_decision(
                    stream_facts,
                    hardware_limit_str,
                    software_limit_str,
                    "hardware_decoder_unavailable",
                )
            if software_allowed:
                return PlaybackDecision(
                    pipeline_variant=PIPELINE_COMPATIBLE,
                    force_software_decoders=True,
                    decision="software_fallback",
                    fallback_reason="hardware_decoder_unavailable",
                    hardware_limit=hardware_limit_str,
                    software_limit=software_limit_str,
                )
            return self.skip_decision(
                stream_facts,
                hardware_limit_str,
                software_limit_str,
                "hardware_decoder_unavailable",
            )

        unsupported_presentation = self.unsupported_hardware_presentation_reason(
            stream_facts,
            sink_name,
            uri,
        )
        if unsupported_presentation is not None:
            return self.skip_decision(
                stream_facts,
                hardware_limit_str,
                software_limit_str,
                unsupported_presentation,
            )

        if sink_name == "waylandsink":
            if self.uses_playbin_hardware_presentation(stream_facts):
                return PlaybackDecision(
                    pipeline_variant=PIPELINE_HARDWARE_PLAYBIN,
                    force_software_decoders=False,
                    decision="hardware_playbin",
                    hardware_limit=hardware_limit_str,
                    software_limit=software_limit_str,
                )
            if self.requires_compatible_hardware_presentation(stream_facts):
                return PlaybackDecision(
                    pipeline_variant=PIPELINE_COMPATIBLE,
                    force_software_decoders=False,
                    decision="hardware_compatible",
                    fallback_reason="hardware_direct_unsupported_caps",
                    hardware_limit=hardware_limit_str,
                    software_limit=software_limit_str,
                )
            return PlaybackDecision(
                pipeline_variant=PIPELINE_HARDWARE_DIRECT,
                force_software_decoders=False,
                decision="hardware_direct",
                hardware_limit=hardware_limit_str,
                software_limit=software_limit_str,
            )

        return PlaybackDecision(
            pipeline_variant=PIPELINE_COMPATIBLE,
            force_software_decoders=False,
            decision="hardware_compatible",
            hardware_limit=hardware_limit_str,
            software_limit=software_limit_str,
        )

    def requires_compatible_hardware_presentation(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        if stream_facts is None or self.normalized_codec(stream_facts.codec) != "h265":
            return False
        caps_string = (stream_facts.caps_string or "").lower()
        return (
            "profile=(string)main-10" in caps_string
            or "bit-depth-luma=(uint)10" in caps_string
            or "bt2100" in caps_string
        )

    def requires_pi_hardware_only(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        return (
            self.raspberry_pi_model_family(self._hardware_model) is not None
            and self.requires_compatible_hardware_presentation(stream_facts)
        )

    def uses_playbin_hardware_presentation(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        return (
            stream_facts is not None
            and self.normalized_codec(stream_facts.codec) == "h265"
            and not self.requires_compatible_hardware_presentation(stream_facts)
        )

    def unsupported_hardware_presentation_reason(
        self,
        stream_facts: VideoStreamFacts | None,
        sink_name: str,
        uri: str,
    ) -> str | None:
        if sink_name != "waylandsink":
            return None
        if stream_facts is None or self.normalized_codec(stream_facts.codec) != "h265":
            return None

        model = self._hardware_model.lower()
        is_pi4_like = (
            "raspberry pi 4" in model
            or "raspberry pi 400" in model
            or "compute module 4" in model
        )
        if not is_pi4_like:
            return None

        if self.requires_compatible_hardware_presentation(stream_facts):
            return "hardware_presentation_unsupported"
        container = stream_facts.container or self.container_hint_from_uri(uri)
        if (
            stream_facts.framerate is not None
            and stream_facts.framerate > 30.0
            and container in {"mov", "quicktime"}
        ):
            return "hardware_quicktime_framerate_unsupported"
        return None

    def known_hardware_decode_limit(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> DecodeHardwareLimit | None:
        if stream_facts is None or stream_facts.codec is None:
            return None

        model_family = self.raspberry_pi_model_family(self._hardware_model)
        codec = self.normalized_codec(stream_facts.codec) or self.codec_from_caps_string(
            stream_facts.caps_string
        )
        if model_family is None or codec is None:
            return None

        return RPI_HARDWARE_DECODE_LIMITS.get(model_family, {}).get(codec)

    def software_decode_limit(
        self,
        value: str | None,
    ) -> DecodeResolutionLimit | None:
        raw_value = value or DEFAULT_SOFTWARE_DECODE_LIMIT
        limit = self.parse_resolution_limit(raw_value)
        if limit is None:
            logger.warning(
                "Invalid max software decode resolution %r; using default %s.",
                raw_value,
                DEFAULT_SOFTWARE_DECODE_LIMIT,
            )
            return self.parse_resolution_limit(DEFAULT_SOFTWARE_DECODE_LIMIT)
        return limit

    def hardware_limit_rejection_reason(
        self,
        stream_facts: VideoStreamFacts | None,
        limit: DecodeHardwareLimit | None,
    ) -> str | None:
        if limit is None:
            return "hardware_unsupported_for_model"
        if not self.within_resolution_limit(
            stream_facts,
            limit,
            allow_rotation=False,
        ):
            return "hardware_limit_exceeded"
        if not self.within_hardware_framerate_limit(stream_facts, limit):
            return "hardware_framerate_exceeded"
        return None

    def skip_decision(
        self,
        stream_facts: VideoStreamFacts | None,
        hardware_limit: str | None,
        software_limit: str | None,
        fallback_reason: str,
    ) -> PlaybackDecision:
        dimensions = self.format_stream_dimensions(stream_facts)
        details = (
            f"Skipping video {dimensions}: exceeds safe hardware decode limit "
            f"{hardware_limit or 'unknown'} and software decode limit "
            f"{software_limit or 'unknown'}."
        )
        if fallback_reason == "hardware_unsupported_for_model":
            details = (
                f"Skipping video {dimensions}: this codec is not hardware decoded "
                "on this Raspberry Pi model or host, and software decode limit "
                f"is {software_limit or 'unknown'}."
            )
        if fallback_reason == "hardware_decoder_unavailable":
            details = (
                f"Skipping video {dimensions}: no matching GStreamer V4L2 "
                "hardware decoder is available, and software decode limit "
                f"is {software_limit or 'unknown'}."
            )
        if fallback_reason == "hardware_limit_exceeded":
            details = (
                f"Skipping video {dimensions}: exceeds safe hardware decode limit "
                f"{hardware_limit or 'unknown'} and software decode limit "
                f"{software_limit or 'unknown'}."
            )
        if fallback_reason == "hardware_framerate_exceeded":
            details = (
                f"Skipping video {dimensions}"
                f"{self.format_stream_framerate(stream_facts)}: exceeds safe "
                f"hardware decode limit {hardware_limit or 'unknown'} and "
                f"software decode limit {software_limit or 'unknown'}."
            )
        if fallback_reason == "hardware_presentation_unsupported":
            details = (
                f"Skipping video {dimensions}: HEVC Main 10/HDR hardware decode "
                "is available, but the decoded format cannot be presented smoothly "
                "on this Raspberry Pi display path."
            )
        if fallback_reason == "hardware_framerate_unsupported":
            details = (
                f"Skipping video {dimensions}"
                f"{self.format_stream_framerate(stream_facts)}: HEVC hardware "
                "decode is available, but this Raspberry Pi 4 Wayland display "
                "path is only validated up to 30 fps."
            )
        if fallback_reason == "hardware_quicktime_framerate_unsupported":
            details = (
                f"Skipping video {dimensions}"
                f"{self.format_stream_framerate(stream_facts)}: HEVC hardware "
                "decode is available, but this Raspberry Pi 4 Wayland display "
                "path cannot present this MOV/QuickTime 60 fps stream smoothly."
            )
        if fallback_reason == "software_limit_exceeded":
            details = (
                f"Skipping video {dimensions}: no suitable hardware decoder path "
                f"and software decode limit is {software_limit or 'unknown'}."
            )
        return PlaybackDecision(
            pipeline_variant=PIPELINE_SKIPPED,
            force_software_decoders=False,
            decision="skip",
            fallback_reason=fallback_reason,
            skip_reason=details,
            error_code=UNSUPPORTED_MEDIA_CODE,
            hardware_limit=hardware_limit,
            software_limit=software_limit,
        )

    @staticmethod
    def raspberry_pi_model_family(model: str) -> str | None:
        normalized = model.strip("\x00\n ").lower()
        if "raspberry pi" not in normalized and "compute module" not in normalized:
            return None
        if (
            "raspberry pi 5" in normalized
            or "raspberry pi 500" in normalized
            or "compute module 5" in normalized
        ):
            return "pi5"
        if (
            "raspberry pi 4" in normalized
            or "raspberry pi 400" in normalized
            or "compute module 4" in normalized
        ):
            return "pi4"
        if "raspberry pi 3" in normalized or "compute module 3" in normalized:
            return "pi3"
        if "raspberry pi zero 2" in normalized:
            return "zero2"
        if "raspberry pi zero" in normalized:
            return "zero"
        return None

    @staticmethod
    def normalized_codec(codec: str | None) -> str | None:
        if codec is None:
            return None
        normalized = codec.lower()
        if normalized == "hevc":
            return "h265"
        return normalized

    @staticmethod
    def parse_resolution_limit(value: str | None) -> DecodeResolutionLimit | None:
        if value is None:
            return None
        normalized = value.strip().lower().replace(" ", "")
        if normalized in {"", "none", "off", "unlimited"}:
            return None
        parts = normalized.split("x", maxsplit=1)
        if len(parts) != 2:
            return None
        try:
            width = int(parts[0])
            height = int(parts[1])
        except ValueError:
            return None
        if width <= 0 or height <= 0:
            return None
        return DecodeResolutionLimit(width=width, height=height)

    @staticmethod
    def format_resolution_limit(limit: DecodeResolutionLimit | None) -> str | None:
        if limit is None:
            return None
        return f"{limit.width}x{limit.height}"

    @staticmethod
    def format_hardware_limit(limit: DecodeHardwareLimit | None) -> str | None:
        if limit is None:
            return None
        if limit.max_fps is None:
            return f"{limit.width}x{limit.height}"
        return f"{limit.width}x{limit.height}@{limit.max_fps:g}"

    @staticmethod
    def within_resolution_limit(
        stream_facts: VideoStreamFacts | None,
        limit: DecodeResolutionLimit | DecodeHardwareLimit | None,
        *,
        allow_rotation: bool,
    ) -> bool:
        if stream_facts is None or limit is None:
            return True
        if stream_facts.width is None or stream_facts.height is None:
            return True

        width = stream_facts.width
        height = stream_facts.height
        if width <= limit.width and height <= limit.height:
            return True
        return allow_rotation and width <= limit.height and height <= limit.width

    @staticmethod
    def within_hardware_framerate_limit(
        stream_facts: VideoStreamFacts | None,
        limit: DecodeHardwareLimit | None,
    ) -> bool:
        if (
            stream_facts is None
            or stream_facts.framerate is None
            or limit is None
            or limit.max_fps is None
        ):
            return True
        return stream_facts.framerate <= limit.max_fps + 0.01

    @staticmethod
    def format_stream_dimensions(stream_facts: VideoStreamFacts | None) -> str:
        if (
            stream_facts is None
            or stream_facts.width is None
            or stream_facts.height is None
        ):
            return "with unknown resolution"
        return f"{stream_facts.width}x{stream_facts.height}"

    @staticmethod
    def format_stream_framerate(stream_facts: VideoStreamFacts | None) -> str:
        if stream_facts is None or stream_facts.framerate is None:
            return ""
        return f" at {stream_facts.framerate:g} fps"

    @staticmethod
    def codec_from_caps_string(caps_string: str | None) -> str | None:
        caps_string = (caps_string or "").lower()
        if "video/x-h264" in caps_string:
            return "h264"
        if "video/x-h265" in caps_string or "video/x-hevc" in caps_string:
            return "h265"
        return None

    @staticmethod
    def container_hint_from_uri(uri: str) -> str | None:
        try:
            path = unquote(urlparse(uri).path)
        except Exception:
            path = uri
        suffix = path.rsplit(".", maxsplit=1)[-1].lower() if "." in path else ""
        if suffix == "mov":
            return "quicktime"
        if suffix in {"mp4", "m4v"}:
            return "mp4"
        if suffix in {"mkv", "webm"}:
            return "matroska"
        return suffix or None
