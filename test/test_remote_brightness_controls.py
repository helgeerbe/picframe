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


def test_remote_video_preview_is_poster_first_and_expanded_video_only() -> None:
    remote_view = Path("frontend/src/views/RemoteView.vue").read_text()
    player_store = Path("frontend/src/stores/player.ts").read_text()

    assert "media_type?: 'image' | 'video' | string" in player_store
    assert "const isVideoMedia" in remote_view
    assert "url.pathname = '/media/poster'" in remote_view
    assert "const mediaVideoSrc" in remote_view
    assert "const openExpandedVideo" in remote_view
    assert ':src="mediaPosterSrc(selectedMediaItem)"' in remote_view
    assert ':src="mediaVideoSrc(selectedMediaItem)"' in remote_view
    assert '@click.stop="openExpandedVideo"' in remote_view
    assert ':autoplay="expandedVideoAutoplay"' in remote_view
    assert "remote.playVideo" in remote_view
    assert 'preload="metadata"' in remote_view
    assert "fixed right-5 top-5" not in remote_view
    assert "mb-3 flex h-12 shrink-0 justify-end" in remote_view
    assert "min-h-0 flex-1 w-full" in remote_view
    assert remote_view.count('v-if="isVideoMedia(item)"') >= 3
    assert remote_view.count('@error="handleVideoPosterError(item)"') >= 3

    preview_section = remote_view[
        remote_view.index("<!-- Image Preview Area -->") : remote_view.index(
            "<!-- Controls Area -->"
        )
    ]
    assert "isVideoMedia(selectedMediaItem)" in preview_section
    assert preview_section.index("mediaPosterSrc(selectedMediaItem)") < (
        preview_section.index("mediaImageSrc(selectedMediaItem)")
    )
    assert "<video" not in preview_section


def test_remote_current_media_tags_are_touch_accessible() -> None:
    remote_view = Path("frontend/src/views/RemoteView.vue").read_text()
    en_locale = Path("frontend/src/locales/en.json").read_text()
    de_locale = Path("frontend/src/locales/de.json").read_text()

    assert "const isMediaOverlayPinned = ref(false)" in remote_view
    assert "isMediaOverlayPinned.value = false" in remote_view
    assert "const toggleMediaOverlay" in remote_view
    assert 'v-if="currentMediaTags.length"' in remote_view
    assert ':aria-expanded="isMediaOverlayPinned"' in remote_view
    assert 'aria-controls="remote-current-media-tags"' in remote_view
    assert '@click.stop="toggleMediaOverlay"' in remote_view
    assert 'id="remote-current-media-tags"' in remote_view
    assert "group-hover:grid-rows-[1fr]" in remote_view
    assert "grid-rows-[1fr] opacity-100" in remote_view
    assert '@click.stop="setTagFilter(tag, $event)"' in remote_view
    assert '"showTags": "Show tags"' in en_locale
    assert '"hideTags": "Hide tags"' in en_locale
    assert '"showTags": "Tags anzeigen"' in de_locale
    assert '"hideTags": "Tags ausblenden"' in de_locale
