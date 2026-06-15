import pytest

from picframe.core.renderers.animation_controller import (
    AnimationController,
    AnimationState,
    RenderState,
)


@pytest.fixture
def config():
    return {
        "fps": 20,
        "time_fade": 2.0,
        "time_delay": 200.0,
        "show_text_tm": 10.0,
        "kenburns": False
    }

def test_initial_state(config):
    controller = AnimationController(config)
    state = controller.update(0.0)
    assert state.render_state == RenderState.STATIC
    assert state.image_alpha == 1.0
    assert state.text_alpha == 0.0
    assert state.frames_to_render == 0

def test_start_transition(config):
    controller = AnimationController(config)
    controller.start_transition(100.0)
    state = controller.update(100.0)
    assert state.render_state == RenderState.TRANSITIONING
    assert state.image_alpha > 0.0 # It increments immediately on update
    assert state.text_alpha == 0.0

def test_start_transition_hides_existing_text(config):
    controller = AnimationController(config)
    controller._text_alpha = 1.0

    controller.start_transition(100.0)
    state = controller.update(100.0)

    assert state.render_state == RenderState.TRANSITIONING
    assert state.text_alpha == 0.0

def test_transition_completion(config):
    controller = AnimationController(config)
    controller.start_transition(100.0)
    
    # Fast forward to end of transition
    state = controller.update(100.0)
    for _ in range(39): # 20 fps * 2.0s = 40 frames
        state = controller.update(100.0)
        
    assert state.render_state == RenderState.TEXT_ANIMATING
    assert state.image_alpha == 1.0

def test_kenburns_transition(config):
    config["kenburns"] = True
    controller = AnimationController(config)
    controller.start_transition(100.0, kb_xstep=0.1, kb_ystep=0.1)
    
    # Fast forward to end of transition
    state = controller.update(100.0)
    for _ in range(39):
        state = controller.update(100.0)
        
    assert state.render_state == RenderState.KEN_BURNS
    assert state.image_alpha == 1.0
    
    # Next update should move to TEXT_ANIMATING
    state = controller.update(101.0)
    assert state.render_state == RenderState.TEXT_ANIMATING

def test_text_animation(config):
    controller = AnimationController(config)
    controller.update_text_config(True, False)
    
    # Force state to TEXT_ANIMATING
    controller._state = RenderState.TEXT_ANIMATING
    
    # Fast forward text fade in (1.0s at 20fps = 20 frames)
    state = controller.update(100.0)
    for _ in range(19):
        state = controller.update(100.0)
        
    assert state.render_state == RenderState.STATIC
    assert state.text_alpha == 1.0

def test_text_fade_out(config):
    controller = AnimationController(config)
    controller.update_text_config(True, False)
    
    # Force state to STATIC with text fully visible and timer expired
    controller._state = RenderState.STATIC
    controller._text_alpha = 1.0
    controller._text_timer = 90.0
    
    # Update at time > timer
    state = controller.update(100.0)
    assert state.text_alpha < 1.0 # Should start fading out

def test_suspend(config):
    controller = AnimationController(config)
    controller.suspend()
    state = controller.update(100.0)
    assert state.render_state == RenderState.SUSPENDED

def test_force_redraw(config):
    controller = AnimationController(config)
    controller.force_redraw(5)
    state = controller.update(100.0)
    assert state.frames_to_render == 5 # Pre-decremented value returned

def test_video_handoff_ready_without_text(config):
    controller = AnimationController(config)
    controller._show_text = False
    state = AnimationState(
        render_state=RenderState.STATIC,
        image_alpha=1.0,
        text_alpha=0.0,
        kenburns_x=0.0,
        kenburns_y=0.0,
        frames_to_render=0,
    )

    assert controller.video_handoff_ready(state)

def test_video_handoff_waits_for_text_fade_out_and_clean_frames(config):
    controller = AnimationController(config)
    controller._show_text = True
    visible_state = AnimationState(
        render_state=RenderState.STATIC,
        image_alpha=1.0,
        text_alpha=1.0,
        kenburns_x=0.0,
        kenburns_y=0.0,
        frames_to_render=0,
    )
    fading_state = AnimationState(
        render_state=RenderState.STATIC,
        image_alpha=1.0,
        text_alpha=0.5,
        kenburns_x=0.0,
        kenburns_y=0.0,
        frames_to_render=0,
    )
    clean_frame_state = AnimationState(
        render_state=RenderState.STATIC,
        image_alpha=1.0,
        text_alpha=0.0,
        kenburns_x=0.0,
        kenburns_y=0.0,
        frames_to_render=1,
    )
    ready_state = AnimationState(
        render_state=RenderState.STATIC,
        image_alpha=1.0,
        text_alpha=0.0,
        kenburns_x=0.0,
        kenburns_y=0.0,
        frames_to_render=0,
    )

    assert not controller.video_handoff_ready(visible_state)
    assert not controller.video_handoff_ready(fading_state)
    assert not controller.video_handoff_ready(clean_frame_state)

    controller._frames_to_render = 1
    assert not controller.video_handoff_ready(ready_state)

    controller._frames_to_render = 0
    assert controller.video_handoff_ready(ready_state)
