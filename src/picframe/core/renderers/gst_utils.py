"""
Utility functions for GStreamer integration and hardware discovery.
"""

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    class Gst:
        Caps = Any
        Registry = Any
        ElementFactory = Any
        PadDirection = Any
        ELEMENT_METADATA_KLASS = Any

try:
    import gi  # type: ignore
    gi.require_version('Gst', '1.0')  # type: ignore
    from gi.repository import Gst  # type: ignore
    GST_AVAILABLE = True
except ImportError:
    Gst = Any  # type: ignore
    GST_AVAILABLE = False


def ffprobe_codec_to_gst_caps(
    codec: str | None, 
    width: int | None = None, 
    height: int | None = None, 
    framerate: float | None = None
) -> str | None:
    """
    Translates an ffprobe codec name and video properties to a GStreamer caps string.
    
    Args:
        codec: The codec name from ffprobe (e.g., 'h264', 'hevc').
        width: The video width in pixels.
        height: The video height in pixels.
        framerate: The video framerate.
        
    Returns:
        A GStreamer caps string (e.g., 'video/x-h264, width=1920, height=1080'),
        or None if the codec is missing.
    """
    if not codec:
        return None
        
    codec_map = {
        "h264": "video/x-h264",
        "hevc": "video/x-h265",
        "vp8": "video/x-vp8",
        "vp9": "video/x-vp9",
        "mpeg4": "video/mpeg, mpegversion=4",
        "mjpeg": "image/jpeg",
        "av1": "video/x-av1",
    }
    
    base_caps = codec_map.get(codec.lower(), f"video/x-{codec.lower()}")
    
    caps_parts = [base_caps]
    if width is not None:
        caps_parts.append(f"width={width}")
    if height is not None:
        caps_parts.append(f"height={height}")
        
    return ", ".join(caps_parts)


def get_hardware_decoders_caps() -> list[Any]:
    """
    Queries the GStreamer registry for hardware video decoders and returns their sink pad template caps.
    
    Returns:
        A list of Gst.Caps objects representing the capabilities of available hardware decoders.
    """
    if not GST_AVAILABLE:
        return []
        
    registry = Gst.Registry.get() # type: ignore # pylint: disable=no-member
    features = registry.get_feature_list(Gst.ElementFactory) # type: ignore # pylint: disable=no-member
    
    hw_caps = []
    for factory in features:
        klass = factory.get_metadata(Gst.ELEMENT_METADATA_KLASS)
        if not klass:
            continue
        # Look for Video Decoders that are Hardware accelerated
        if "Decoder" in klass and "Video" in klass and "Hardware" in klass:
            for template in factory.get_static_pad_templates():
                if template.direction == Gst.PadDirection.SINK: # type: ignore # pylint: disable=no-member
                    caps = template.get_caps()
                    if caps:
                        hw_caps.append(caps)
                        
    return hw_caps


def is_hardware_supported(media_caps_str: str) -> bool:
    """
    Checks if the given media caps are supported by any available hardware decoder.
    
    Args:
        media_caps_str: The GStreamer caps string representing the media.
        
    Returns:
        True if a hardware decoder supports the caps, False otherwise.
    """
    if not GST_AVAILABLE or not media_caps_str:
        return False
        
    media_caps = Gst.Caps.from_string(media_caps_str) # type: ignore # pylint: disable=no-member
    if not media_caps:
        return False
        
    hw_caps_list = get_hardware_decoders_caps()
    for hw_caps in hw_caps_list:
        if hw_caps.can_intersect(media_caps):
            intersection = hw_caps.intersect(media_caps)
            if not intersection.is_empty():
                return True
                
    return False

def find_best_element(element_types: List[str]) -> Optional[str]:
    """
    Finds the best available GStreamer element from a list of preferred types.
    Useful for finding hardware-accelerated converters/scalers.
    
    Args:
        element_types: A list of GStreamer element names in order of preference.
        
    Returns:
        The name of the first available element, or None if none are found.
    """
    if not GST_AVAILABLE:
        return None
        
    registry = Gst.Registry.get() # type: ignore # pylint: disable=no-member
    for elem_name in element_types:
        factory = registry.lookup_feature(elem_name)
        if factory:
            return elem_name
    return None
