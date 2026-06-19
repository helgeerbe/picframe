"""Source guards for Remote brightness command behavior."""

from pathlib import Path


def test_remote_brightness_slider_commits_on_change_not_input() -> None:
    remote_view = Path("frontend/src/views/RemoteView.vue").read_text()
    player_store = Path("frontend/src/stores/player.ts").read_text()

    assert '@input="handleBrightnessPreview"' in remote_view
    assert '@change="handleBrightnessCommit"' in remote_view
    assert '@input="handleBrightnessChange"' not in remote_view
    assert "playerStore.previewBrightness(readBrightnessEventValue(event))" in remote_view
    assert "playerStore.setBrightness(readBrightnessEventValue(event))" in remote_view
    assert "function previewBrightness" in player_store
    assert "sendCommand('SET_BRIGHTNESS'" in player_store
