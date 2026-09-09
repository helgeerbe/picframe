"""Tests for the WebKitOverlayRenderer IPC client (mocked worker + probe)."""

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.events.dto import (
    RENDER_PARK_VIDEO_REVEAL,
    RENDER_PROMOTE_VIDEO_REVEAL,
    RENDER_WAKE_VIDEO_REVEAL,
    Command,
    CommandEvent,
    CurrentMediaChangedEvent,
    DisplayPowerEvent,
    OverlayConfigChangedEvent,
    RenderCommand,
    SystemErrorEvent,
)
from picframe.core.models.media import DisplayItem, MediaItem, MediaType
from picframe.core.models.overlay import PluginDescriptor
from picframe.core.renderers import webkit_overlay_renderer as wor
from picframe.core.renderers.overlay_ipc import (
    INPUT_ACTION_DISPLAY_OFF,
    INPUT_ACTION_NEXT,
    INPUT_ACTION_PREV,
    INPUT_ACTION_REBOOT_HOST,
    INPUT_ACTION_RESTART_SERVICE,
    INPUT_ACTION_SHUTDOWN_HOST,
    INPUT_ACTION_TOGGLE,
    InputEvent,
    MediaChangedCommand,
    OverlayErrorEvent,
    ReadyEvent,
    SetConfigCommand,
    VisiblePluginsChangedEvent,
)
from picframe.core.renderers.webkit_overlay_renderer import (
    WebKitOverlayRenderer,
    _command_for_input_action,
    _layer_shell_typelib_present,
    _resolve_layer_shell_so,
)
from picframe.infrastructure.overlay.plugin_loader import PluginLoader


@pytest.fixture
def mock_publisher() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_subscriber() -> MagicMock:
    return MagicMock()


@pytest.fixture
def plugin_loader(tmp_path) -> PluginLoader:
    return PluginLoader(tmp_path)


@pytest.fixture(autouse=True)
def disable_listener_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real IPC listener thread from spinning against a mocked conn."""
    monkeypatch.setattr(WebKitOverlayRenderer, "_listen_for_events", lambda self: None)


def make_renderer(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    *,
    available: bool = True,
) -> WebKitOverlayRenderer:
    renderer = WebKitOverlayRenderer(
        event_publisher=mock_publisher,
        event_subscriber=mock_subscriber,
        plugin_loader=plugin_loader,
        html_dir=str(tmp_path),
        plugin_dir=str(tmp_path),
        ws_port=9000,
        overlay_config={"enabled": True},
    )
    renderer._availability = available
    return renderer


@patch("picframe.core.renderers.webkit_overlay_renderer.subprocess.Popen")
@patch("picframe.core.renderers.webkit_overlay_renderer.Client")
@patch("picframe.core.renderers.webkit_overlay_renderer.os.path.exists", return_value=True)
def test_start_spawns_worker_and_applies_initial_config(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The resolver shells out to ldconfig (subprocess.run -> Popen); since Popen
    # is mocked here, short-circuit it so no LD_PRELOAD is injected.
    monkeypatch.setattr(wor, "_resolve_layer_shell_so", lambda: None)
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)

    renderer.start()

    mock_popen.assert_called_once()
    args = mock_popen.call_args[0][0]
    assert "--socket" in args and "--html-dir" in args and "--plugin-dir" in args
    assert mock_popen.call_args.kwargs["env"]["GDK_BACKEND"] == "wayland"
    subscribed_types = {call.args[0] for call in mock_subscriber.subscribe.call_args_list}
    assert OverlayConfigChangedEvent in subscribed_types
    assert RenderCommand in subscribed_types
    assert CurrentMediaChangedEvent in subscribed_types
    sent = mock_client.return_value.send.call_args_list[-1][0][0]
    assert '"type": "set_config"' in sent


def test_start_when_unavailable_publishes_system_error_and_does_not_spawn(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(
        mock_publisher, mock_subscriber, plugin_loader, tmp_path, available=False
    )
    with patch.object(wor, "subprocess") as mock_sub:
        renderer.start()
        mock_sub.Popen.assert_not_called()
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args[0][0]
    assert isinstance(event, SystemErrorEvent)
    assert event.code == "webkit_unavailable"


def test_is_available_caches_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_probe() -> bool:
        calls["n"] += 1
        return False

    monkeypatch.setattr(wor, "_probe_webkit", fake_probe)
    renderer = WebKitOverlayRenderer(MagicMock(), MagicMock(), PluginLoader("/tmp"), "/h", "/p")
    assert renderer.is_available() is False
    assert renderer.is_available() is False
    assert calls["n"] == 1


def test_list_plugins_delegates_to_loader(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    assert renderer.list_plugins() == []
    with patch.object(plugin_loader, "list_plugins", return_value=[PluginDescriptor(id="clock")]):
        assert [p.id for p in renderer.list_plugins()] == ["clock"]


def test_handle_input_event_translates_to_command_event(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    cases = {
        INPUT_ACTION_PREV: Command.PREV,
        INPUT_ACTION_NEXT: Command.NEXT,
        INPUT_ACTION_TOGGLE: Command.PLAY,
    }
    for action, expected in cases.items():
        mock_publisher.reset_mock()
        renderer._handle_event(InputEvent(action=action))
        mock_publisher.publish.assert_called_once()
        event = mock_publisher.publish.call_args[0][0]
        assert isinstance(event, CommandEvent)
        assert event.command == expected


def test_handle_input_event_unknown_action_publishes_nothing(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._handle_event(InputEvent(action="bogus"))
    mock_publisher.publish.assert_not_called()


def test_handle_ready_event_does_not_publish(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._handle_event(ReadyEvent())
    mock_publisher.publish.assert_not_called()


def test_handle_error_event_publishes_system_error(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._handle_event(OverlayErrorEvent(details="doh", code="webkit_unavailable"))
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args[0][0]
    assert isinstance(event, SystemErrorEvent)
    assert event.message == "doh"
    assert event.code == "webkit_unavailable"


def test_handle_visible_plugins_changed_publishes_set_config(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    """A dock-driven visible-plugin change is republished as the exact
    ``CommandEvent(SET_CONFIG, {overlay: {visible_plugins}})`` the Remote/
    Appearance REST endpoint publishes, so ConfigService persists it to
    ``config.db3`` and both UIs refresh through ``OverlayConfigChangedEvent``
    (#765)."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._handle_event(VisiblePluginsChangedEvent(visible_plugins=("clock", "text")))
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args[0][0]
    assert isinstance(event, CommandEvent)
    assert event.command == Command.SET_CONFIG
    assert event.payload == {"overlay": {"visible_plugins": ["clock", "text"]}}


def test_handle_visible_plugins_changed_empty_publishes_empty_list(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    """Collapsing every panel persists an empty list (dock-only), not a drop
    of the key (#765)."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._handle_event(VisiblePluginsChangedEvent(visible_plugins=()))
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args[0][0]
    assert isinstance(event, CommandEvent)
    assert event.command == Command.SET_CONFIG
    assert event.payload == {"overlay": {"visible_plugins": []}}


def test_render_command_promote_sets_opacity_zero(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    with patch.object(renderer, "set_opacity") as mock_opacity:
        renderer._on_render_command(
            RenderCommand(image_path="x", render_action=RENDER_PROMOTE_VIDEO_REVEAL)
        )
        mock_opacity.assert_called_once_with(0.0)


def test_render_command_park_and_wake_set_opacity_one(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    with patch.object(renderer, "set_opacity") as mock_opacity:
        renderer._on_render_command(
            RenderCommand(image_path="x", render_action=RENDER_PARK_VIDEO_REVEAL)
        )
        renderer._on_render_command(
            RenderCommand(image_path="x", render_action=RENDER_WAKE_VIDEO_REVEAL)
        )
        assert mock_opacity.call_args_list == [((1.0,),), ((1.0,),)]


def test_render_command_unrelated_action_does_not_change_opacity(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    with patch.object(renderer, "set_opacity") as mock_opacity:
        renderer._on_render_command(RenderCommand(image_path="x", render_action=None))
        mock_opacity.assert_not_called()


def test_overlay_config_changed_forwards_set_config(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    with patch.object(renderer, "_send_command") as mock_send:
        renderer._on_overlay_config_changed(
            OverlayConfigChangedEvent(
                overlay_config={"enabled_plugins": ["clock"]}, updated_plugin_id=None
            )
        )
        mock_send.assert_called_once()
        cmd = mock_send.call_args[0][0]
        assert isinstance(cmd, SetConfigCommand)
        # #757: the renderer injects the live blend time (time_fade) into the
        # worker config so the shell's media_change wake-after-blend driver
        # waits for the image crossfade.
        assert cmd.config == {"enabled_plugins": ["clock"], "time_fade": 2.0}
        assert renderer._overlay_config == {"enabled_plugins": ["clock"]}
        assert renderer._time_fade == 2.0


def test_worker_config_injects_time_fade(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    """The config pushed to the worker carries time_fade for the shell (#757)."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._time_fade = 7.5
    renderer._overlay_config = {"enabled": True, "enabled_plugins": ["text"]}
    cfg = renderer._worker_config()
    assert cfg["enabled"] is True
    assert cfg["time_fade"] == 7.5
    # The original overlay config dict is not mutated.
    assert "time_fade" not in renderer._overlay_config


def test_renderer_config_updated_updates_time_fade_and_repushes(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    """A RendererConfigUpdatedEvent updates time_fade and re-pushes config (#757)."""
    from picframe.core.events.dto import RendererConfig, RendererConfigUpdatedEvent

    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._running = True
    renderer._overlay_config = {"enabled": True}
    with patch.object(renderer, "_send_command") as mock_send:
        renderer._on_renderer_config_updated(
            RendererConfigUpdatedEvent(config=RendererConfig(time_fade=12.0))
        )
        assert renderer._time_fade == 12.0
        mock_send.assert_called_once()
        cmd = mock_send.call_args[0][0]
        assert isinstance(cmd, SetConfigCommand)
        assert cmd.config["time_fade"] == 12.0


def test_renderer_config_updated_skips_push_when_not_running(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    from picframe.core.events.dto import RendererConfig, RendererConfigUpdatedEvent

    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._running = False
    with patch.object(renderer, "_send_command") as mock_send:
        renderer._on_renderer_config_updated(
            RendererConfigUpdatedEvent(config=RendererConfig(time_fade=9.0))
        )
        assert renderer._time_fade == 9.0
        mock_send.assert_not_called()


def _make_media_item(**overrides) -> MediaItem:
    """Build a minimal ``MediaItem`` for media-change tests."""
    defaults: dict[str, Any] = dict(
        filepath="/photos/IMG_001.jpg",
        filename="IMG_001.jpg",
        directory_id=1,
        media_type=MediaType.IMAGE,
        file_size=1024,
        last_modified=0.0,
    )
    defaults.update(overrides)
    return MediaItem(**defaults)


def test_media_changed_forwards_media_changed_command(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    """A ``CurrentMediaChangedEvent`` sends a ``MediaChangedCommand`` with the
    primary media item mapped to the ``CurrentMedia`` shape (#757)."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._running = True
    item = _make_media_item(
        latitude=48.1,
        longitude=11.6,
        location="Munich, Germany",
        title="Sunset",
        caption="A nice sunset",
        make="Canon",
        model="EOS R6",
    )
    display = DisplayItem.single(item)
    with patch.object(renderer, "_send_command") as mock_send:
        renderer._on_media_changed(CurrentMediaChangedEvent(media_item=display))
        mock_send.assert_called_once()
        cmd = mock_send.call_args[0][0]
        assert isinstance(cmd, MediaChangedCommand)
        assert cmd.media["file_path"] == "/photos/IMG_001.jpg"
        assert cmd.media["media_type"] == "image"
        assert cmd.media["location"] == {"lat": 48.1, "lon": 11.6}
        # The resolved location-name string surfaces as ``location_name`` in exif.
        assert cmd.media["exif"]["location_name"] == "Munich, Germany"
        assert cmd.media["exif"]["title"] == "Sunset"
        assert cmd.media["exif"]["caption"] == "A nice sunset"
        assert cmd.media["exif"]["make"] == "Canon"


def test_media_changed_skips_push_when_not_running(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    """Before the worker is up (or after a stop) media events are dropped."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._running = False
    item = _make_media_item()
    with patch.object(renderer, "_send_command") as mock_send:
        renderer._on_media_changed(CurrentMediaChangedEvent(media_item=DisplayItem.single(item)))
        mock_send.assert_not_called()


def test_display_item_to_overlay_dict_video_type() -> None:
    """A video ``MediaItem`` maps to ``media_type == "video"``."""
    item = _make_media_item(media_type=MediaType.VIDEO, filepath="/v/clip.mp4")
    media = wor._display_item_to_overlay_dict(DisplayItem.single(item))
    assert media["media_type"] == "video"
    assert media["file_path"] == "/v/clip.mp4"


def test_display_item_to_overlay_dict_no_location() -> None:
    """A ``MediaItem`` without GPS coords yields ``location is None``."""
    item = _make_media_item()
    media = wor._display_item_to_overlay_dict(DisplayItem.single(item))
    assert media["location"] is None


def test_display_item_to_overlay_dict_unknown_payload_returns_placeholder() -> None:
    """An unexpected payload shape never crashes the listener."""
    media = wor._display_item_to_overlay_dict({"not": "a display item"})
    assert media["file_path"] == "no_pictures.jpg"


def test_set_opacity_sends_set_opacity_command(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._conn = MagicMock()
    renderer.set_opacity(0.25)
    sent = renderer._conn.send.call_args[0][0]
    assert '"type": "set_opacity"' in sent
    assert "0.25" in sent


@patch("picframe.core.renderers.webkit_overlay_renderer.subprocess.Popen")
@patch("picframe.core.renderers.webkit_overlay_renderer.Client")
@patch("picframe.core.renderers.webkit_overlay_renderer.os.path.exists", return_value=True)
def test_stop_unsubscribes_and_sends_shutdown_and_terminates(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wor, "_resolve_layer_shell_so", lambda: None)
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer.start()
    conn = renderer._conn
    renderer.stop()
    unsubscribed_types = {call.args[0] for call in mock_subscriber.unsubscribe.call_args_list}
    assert OverlayConfigChangedEvent in unsubscribed_types
    assert RenderCommand in unsubscribed_types
    assert CurrentMediaChangedEvent in unsubscribed_types
    sent = conn.send.call_args_list[-1][0][0]
    assert '"type": "shutdown"' in sent
    mock_popen.return_value.terminate.assert_called_once()


def test_command_for_input_action_mapping() -> None:
    assert _command_for_input_action(INPUT_ACTION_PREV) == Command.PREV
    assert _command_for_input_action(INPUT_ACTION_NEXT) == Command.NEXT
    assert _command_for_input_action(INPUT_ACTION_TOGGLE) == Command.PLAY
    # Danger-menu actions (#763) map to system/display commands.
    assert _command_for_input_action(INPUT_ACTION_DISPLAY_OFF) == Command.DISPLAY_OFF
    assert _command_for_input_action(INPUT_ACTION_RESTART_SERVICE) == Command.RESTART_SERVICE
    assert _command_for_input_action(INPUT_ACTION_REBOOT_HOST) == Command.REBOOT_HOST
    assert _command_for_input_action(INPUT_ACTION_SHUTDOWN_HOST) == Command.SHUTDOWN_HOST
    assert _command_for_input_action("??") is None


def test_worker_environment_sets_gdk_backend_wayland(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    monkeypatch.setattr(wor, "_resolve_layer_shell_so", lambda: None)
    env = renderer._worker_environment()
    assert env["GDK_BACKEND"] == "wayland"
    assert "LD_PRELOAD" not in env


def test_worker_environment_preloads_layer_shell_so(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    so_path = "/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0"
    monkeypatch.setattr(wor, "_resolve_layer_shell_so", lambda: so_path)
    env = renderer._worker_environment()
    assert env["GDK_BACKEND"] == "wayland"
    assert env["LD_PRELOAD"] == so_path


def test_worker_environment_preserves_existing_ld_preload(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    monkeypatch.setenv("LD_PRELOAD", "/usr/lib/preexisting.so")
    so_path = "/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0"
    monkeypatch.setattr(wor, "_resolve_layer_shell_so", lambda: so_path)
    env = renderer._worker_environment()
    assert env["LD_PRELOAD"] == f"{so_path}:/usr/lib/preexisting.so"


def test_resolve_layer_shell_so_returns_none_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate an ldconfig that has no gtk4-layer-shell entry and no fallback dir.
    def _empty_ldconfig(*_args: Any, **_kwargs: Any) -> Any:
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        return m

    monkeypatch.setattr(wor.subprocess, "run", _empty_ldconfig)
    monkeypatch.setattr(wor.os.path, "exists", lambda p: False)
    assert _resolve_layer_shell_so() is None


def test_resolve_layer_shell_so_parses_ldconfig_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _ldconfig(*_args: Any, **_kwargs: Any) -> Any:
        m = MagicMock()
        m.returncode = 0
        m.stdout = (
            "\tlibgtk4-layer-shell.so.0 (libc6,AArch64) "
            "=> /usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0\n"
        )
        return m

    monkeypatch.setattr(wor.subprocess, "run", _ldconfig)
    monkeypatch.setattr(
        wor.os.path,
        "exists",
        lambda p: p == "/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0",
    )
    assert _resolve_layer_shell_so() == "/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0"


def test_layer_shell_typelib_present_returns_bool() -> None:
    """The probe returns a bool whether or not gi/the typelib is installed."""
    assert isinstance(_layer_shell_typelib_present(), bool)


def test_worker_environment_warns_when_typelib_present_but_so_missing(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Typelib installed + runtime .so absent is the "no clock" failure mode;
    surface it at WARNING level so it is not buried in INFO-piped worker logs."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    monkeypatch.setattr(wor, "_resolve_layer_shell_so", lambda: None)
    monkeypatch.setattr(wor, "_layer_shell_typelib_present", lambda: True)
    with caplog.at_level(logging.WARNING, logger=wor.logger.name):
        env = renderer._worker_environment()
    assert env["GDK_BACKEND"] == "wayland"
    assert "LD_PRELOAD" not in env
    assert any("libgtk4-layer-shell0" in r.message for r in caplog.records)


def test_worker_environment_no_warning_when_both_typelib_and_so_absent(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """On dev boxes / OSes without the package at all, keep quiet (graceful)."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    monkeypatch.setattr(wor, "_resolve_layer_shell_so", lambda: None)
    monkeypatch.setattr(wor, "_layer_shell_typelib_present", lambda: False)
    with caplog.at_level(logging.WARNING, logger=wor.logger.name):
        env = renderer._worker_environment()
    assert "LD_PRELOAD" not in env
    assert not any("libgtk4-layer-shell0" in r.message for r in caplog.records)


def test_worker_environment_no_warning_when_so_resolved(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the runtime .so is found and preloaded there is nothing to warn."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    so_path = "/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0"
    monkeypatch.setattr(wor, "_resolve_layer_shell_so", lambda: so_path)
    # Even if the typelib probe would say True, the resolved .so wins.
    monkeypatch.setattr(wor, "_layer_shell_typelib_present", lambda: True)
    with caplog.at_level(logging.WARNING, logger=wor.logger.name):
        env = renderer._worker_environment()
    assert env["LD_PRELOAD"] == so_path
    assert not any("libgtk4-layer-shell0" in r.message for r in caplog.records)


class _SyncThread:
    """A drop-in for ``threading.Thread`` that runs ``target`` synchronously.

    Makes the display-power-on restart path deterministic in tests (no real
    worker thread, no real subprocess).
    """

    def __init__(self, target=None, args=(), kwargs=None, daemon=False) -> None:
        self._target = target

    def start(self) -> None:
        if self._target is not None:
            self._target()

    def join(self, timeout=None) -> None:  # noqa: D401 - matches Thread API
        return None


def test_display_power_on_restarts_worker(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On display power-on (worker running) the renderer respawns the worker."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._running = True  # simulate a live worker without spawning a subprocess
    monkeypatch.setattr(wor.threading, "Thread", _SyncThread)
    with (
        patch.object(renderer, "_unsubscribe_events") as mock_unsub,
        patch.object(renderer, "_cleanup") as mock_cleanup,
        patch.object(renderer, "start") as mock_start,
    ):
        renderer._on_display_power_event(DisplayPowerEvent(power_on=True))
        mock_unsub.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_start.assert_called_once()
    assert renderer._restarting is False


def test_display_power_off_does_not_restart_worker(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A display power-off event must not respawn the worker."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._running = True
    monkeypatch.setattr(wor.threading, "Thread", _SyncThread)
    with patch.object(renderer, "stop") as mock_stop, patch.object(renderer, "start") as mock_start:
        renderer._on_display_power_event(DisplayPowerEvent(power_on=False))
        mock_stop.assert_not_called()
        mock_start.assert_not_called()
    assert renderer._restarting is False


def test_display_power_on_noop_when_overlay_not_running(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Display power-on never auto-enables a disabled/stopped overlay."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._stopped = True  # overlay intentionally stopped (shutdown)
    monkeypatch.setattr(wor.threading, "Thread", _SyncThread)
    with patch.object(renderer, "stop") as mock_stop, patch.object(renderer, "start") as mock_start:
        renderer._on_display_power_event(DisplayPowerEvent(power_on=True))
        mock_stop.assert_not_called()
        mock_start.assert_not_called()
    assert renderer._restarting is False


def test_display_power_on_restarts_after_worker_crash(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Power-on respawns even when the worker died (_running=False, _stopped=False).

    This is the external power-cycle case (#755): the monitor's power button
    destroys the Wayland output, the worker subprocess crashes, the IPC
    listener gets EOFError and sets ``_running = False`` — but the overlay was
    NOT intentionally stopped. The handler must still respawn.
    """
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._running = False  # worker crashed (IPC EOF); NOT intentionally stopped
    renderer._stopped = False
    monkeypatch.setattr(wor.threading, "Thread", _SyncThread)
    with (
        patch.object(renderer, "_unsubscribe_events") as mock_unsub,
        patch.object(renderer, "_cleanup") as mock_cleanup,
        patch.object(renderer, "start") as mock_start,
    ):
        renderer._on_display_power_event(DisplayPowerEvent(power_on=True))
        mock_unsub.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_start.assert_called_once()
    assert renderer._restarting is False


def test_display_power_on_guard_skips_concurrent_restart(
    mock_publisher: MagicMock,
    mock_subscriber: MagicMock,
    plugin_loader: PluginLoader,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second power-on event while a restart is in flight is dropped."""
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer._running = True
    renderer._restarting = True  # a restart is already underway
    monkeypatch.setattr(wor.threading, "Thread", _SyncThread)
    with patch.object(renderer, "stop") as mock_stop, patch.object(renderer, "start") as mock_start:
        renderer._on_display_power_event(DisplayPowerEvent(power_on=True))
        mock_stop.assert_not_called()
        mock_start.assert_not_called()
    # The in-flight flag must be left untouched by the skipped attempt.
    assert renderer._restarting is True
    renderer._restarting = False  # tidy up so the fixture's renderer is clean
