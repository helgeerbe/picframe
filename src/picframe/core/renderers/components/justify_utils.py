"""Shared justification helpers for overlay renderers.

Centralises the edge-based L/R x-positioning logic so that text and clock
renderers stay consistent (#728, Sourcery feedback on PR #729).
"""

from __future__ import annotations


def edge_justify_x(
    center_x: float,
    justify: str,
    width: int,
    sprite_width: float,
) -> float:
    """Return the x position for an overlay sprite with edge-based justification.

    For ``L`` and ``R`` the sprite is shifted so it sits at the left/right edge
    of the available ``width`` rather than near the horizontal center.  For
    ``C`` the sprite stays at ``center_x``.

    Args:
        center_x: The horizontal center of the render area (or pair-half).
        justify: One of ``"L"``, ``"C"``, ``"R"``.
        width: The available width for the text block (already clamped to
            ``max(font_size * 4, render_w - margins)``).
        sprite_width: The rendered width of the pi3d FixedString sprite.

    Returns:
        The x coordinate to pass to ``sprite.position()``.
    """
    if justify in ("L", "R"):
        offset = width // 2 - int(sprite_width) // 2
        if justify == "L":
            return center_x - offset
        return center_x + offset
    return center_x
