"""Tests for the WebKitOverlayRenderer IPC client (mocked worker + probe)."""

from unittest.mock import MagicMock, patch

import pytest

from picframe.core.events.dto import (
    RENDER_PARK_VIDEO_REVEAL,
    RENDER_PROMOTE_VIDEO_REVEAL,
    RENDER_WAKE_VIDEO_REVEAL,
    Command,
    CommandEvent,
    OverlayConfigChangedEvent,
    RenderCommand,
    SystemErrorEvent,
)
from picframe.core.models.overlay import PluginDescriptor
from picframe.core.renderers import webkit_overlay_renderer as wor
from picframe.core.renderers.overlay_ipc import (
    INPUT_ACTION_HIDE,
    INPUT_ACTION_NEXT,
    INPUT_ACTION_PREV,
    INPUT_ACTION_TOGGLE,
    InputEvent,
    OverlayErrorEvent,
    ReadyEvent,
    SetConfigCommand,
)
from picframe.core.renderers.webkit_overlay_renderer import (
    WebKitOverlayRenderer,
    _command_for_input_action,
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
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)

    renderer.start()

    mock_popen.assert_called_once()
    args = mock_popen.call_args[0][0]
    assert "--socket" in args and "--html-dir" in args and "--plugin-dir" in args
    assert mock_popen.call_args.kwargs["env"]["GDK_BACKEND"] == "wayland"
    subscribed_types = {call.args[0] for call in mock_subscriber.subscribe.call_args_list}
    assert OverlayConfigChangedEvent in subscribed_types
    assert RenderCommand in subscribed_types
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
        INPUT_ACTION_HIDE: Command.STOP,
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
        assert cmd.config == {"enabled_plugins": ["clock"]}
        assert renderer._overlay_config == {"enabled_plugins": ["clock"]}


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
) -> None:
    renderer = make_renderer(mock_publisher, mock_subscriber, plugin_loader, tmp_path)
    renderer.start()
    conn = renderer._conn
    renderer.stop()
    unsubscribed_types = {call.args[0] for call in mock_subscriber.unsubscribe.call_args_list}
    assert OverlayConfigChangedEvent in unsubscribed_types
    assert RenderCommand in unsubscribed_types
    sent = conn.send.call_args_list[-1][0][0]
    assert '"type": "shutdown"' in sent
    mock_popen.return_value.terminate.assert_called_once()


def test_command_for_input_action_mapping() -> None:
    assert _command_for_input_action(INPUT_ACTION_PREV) == Command.PREV
    assert _command_for_input_action(INPUT_ACTION_NEXT) == Command.NEXT
    assert _command_for_input_action(INPUT_ACTION_TOGGLE) == Command.PLAY
    assert _command_for_input_action(INPUT_ACTION_HIDE) == Command.STOP
    assert _command_for_input_action("??") is None
