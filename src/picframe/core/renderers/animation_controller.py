"""
Animation Controller Module.

This module provides the `AnimationController` class, which manages the state machine
and tweening logic for the rendering pipeline. It handles image transitions, Ken Burns
effects, and text overlay animations, ensuring smooth visual updates.
"""

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class RenderState(Enum):
    """Enumeration of possible rendering states."""
    IDLE = auto()
    TRANSITIONING = auto()
    KEN_BURNS = auto()
    TEXT_ANIMATING = auto()
    STATIC = auto()
    SUSPENDED = auto()

@dataclass
class AnimationState:
    """Data Transfer Object representing the current state of all animations."""
    render_state: RenderState
    image_alpha: float
    text_alpha: float
    kenburns_x: float
    kenburns_y: float
    frames_to_render: int


class AnimationController:
    """
    Manages the animation state machine and tweening logic for the renderer.
    """
    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the AnimationController with configuration settings.

        Args:
            config: A dictionary containing animation configuration parameters
                    (e.g., fps, time_fade, time_delay, kenburns).
        """
        self._logger = logging.getLogger(__name__)
        self._fps = int(config.get("fps", 20))
        self._fade_time = float(config.get("time_fade", 2.0))
        self._time_delay = float(config.get("time_delay", 200.0))
        self._text_fade_time = 1.0
        self._text_show_time = float(config.get("show_text_tm", 10.0))
        self._kenburns = bool(config.get("kenburns", False))
        
        self._state = RenderState.STATIC
        self._image_alpha = 1.0
        self._text_alpha = 0.0
        self._text_timer = 0.0
        self._frames_to_render = 0
        
        self._kb_xstep = 0.0
        self._kb_ystep = 0.0
        self._kb_x = 0.0
        self._kb_y = 0.0
        self._next_tm = 0.0
        
        self._show_text = False

    def start_transition(
        self, current_time: float, kb_xstep: float = 0.0, kb_ystep: float = 0.0
    ) -> None:
        """
        Initiate a new image transition.

        Args:
            current_time: The current system time in seconds.
            kb_xstep: The Ken Burns X-axis step value.
            kb_ystep: The Ken Burns Y-axis step value.
        """
        self._state = RenderState.TRANSITIONING
        self._image_alpha = 0.0
        self._next_tm = current_time + self._time_delay
        self._kb_xstep = kb_xstep
        self._kb_ystep = kb_ystep
        self._kb_x = 0.0
        self._kb_y = 0.0

    def suspend(self) -> None:
        """Suspend animations (e.g., for video playback)."""
        self._state = RenderState.SUSPENDED

    def resume(self) -> None:
        """Resume animations after suspension."""
        if self._state == RenderState.SUSPENDED:
            self._state = RenderState.STATIC

    def force_redraw(self, frames: int = 2) -> None:
        """
        Force the renderer to draw a specific number of frames.

        Args:
            frames: The number of frames to force redraw. Defaults to 2.
        """
        self._frames_to_render = frames

    def update_text_config(self, show_text: bool, text_changed: bool) -> None:
        """
        Update text overlay configuration and trigger animations if needed.

        Args:
            show_text: Whether the text overlay should be visible.
            text_changed: Whether the text content has changed.
        """
        old_show_text = self._show_text
        self._show_text = show_text
        
        if self._state == RenderState.STATIC:
            if show_text and (not old_show_text or text_changed):
                self._state = RenderState.TEXT_ANIMATING
                self._text_alpha = 0.0
        elif self._state == RenderState.TEXT_ANIMATING and not show_text:
            self._state = RenderState.STATIC

    def update(self, current_time: float) -> AnimationState:
        """
        Calculate the current animation state based on elapsed time.

        Args:
            current_time: The current system time in seconds.

        Returns:
            An AnimationState object containing the updated animation values.
        """
        current_frames_to_render = self._frames_to_render
        if self._frames_to_render > 0:
            self._frames_to_render -= 1

        current_state = self._state

        # Image Transition
        if current_state == RenderState.TRANSITIONING:
            delta_alpha = 1.0 / (self._fps * self._fade_time) if self._fade_time > 0.5 else 1.0
            self._image_alpha += delta_alpha
            if self._image_alpha >= 1.0:
                self._image_alpha = 1.0
                if self._kenburns:
                    self._state = RenderState.KEN_BURNS
                else:
                    self._state = RenderState.TEXT_ANIMATING
                    self._text_alpha = 0.0

        # Ken Burns Tweening
        if self._kenburns and self._image_alpha >= 1.0:
            t_factor = self._time_delay - self._fade_time - self._next_tm + current_time
            self._kb_x = self._kb_x * 0.95 + self._kb_xstep * t_factor * 0.05
            self._kb_y = self._kb_y * 0.95 + self._kb_ystep * t_factor * 0.05

        # State Machine Progression
        if current_state == RenderState.KEN_BURNS:
            self._state = RenderState.TEXT_ANIMATING
            self._text_alpha = 0.0

        elif current_state == RenderState.TEXT_ANIMATING:
            if self._show_text:
                self._text_alpha += 1.0 / (self._fps * self._text_fade_time)
                if self._text_alpha >= 1.0:
                    self._text_alpha = 1.0
                    self._state = RenderState.STATIC
                    self._text_timer = current_time + self._text_show_time
            else:
                self._state = RenderState.STATIC

        elif current_state == RenderState.STATIC:
            if self._show_text and current_time >= self._text_timer:
                self._text_alpha -= 1.0 / (self._fps * self._text_fade_time)
                if self._text_alpha <= 0.0:
                    self._text_alpha = 0.0

        return AnimationState(
            render_state=self._state,
            image_alpha=self._image_alpha,
            text_alpha=self._text_alpha,
            kenburns_x=self._kb_x,
            kenburns_y=self._kb_y,
            frames_to_render=current_frames_to_render
        )
