import logging
import os
import time
from unittest.mock import patch, MagicMock

import pytest

logging.basicConfig(level=logging.DEBUG)

@pytest.fixture
def test_video_path():
    # Provide a path to a small test video file in your test directory
    test_file = os.path.join(os.path.dirname(__file__), "videos/SampleVideo_720x480_1mb.mp4")
    if not os.path.exists(test_file):
        pytest.skip("Test video file not found: test.mp4 %s" % test_file)
    return test_file

@patch("subprocess.Popen")
def test_video_player_play(mock_popen, test_video_path):
    """Test starting the video player and playing a video file."""
    # Mock the Popen instance and its stdin/stdout
    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdout = MagicMock()
    # Simulate the player sending state messages
    mock_proc.stdout.__iter__.return_value = iter([
        "STATE:PLAYING\n",
        "STATE:ENDED\n"
        "STATE:STOPPED\n",
    ])
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc

    # Import here to avoid circular import issues
    from picframe.video_streamer import VideoStreamer

    # Create the VideoStreamer and play a video
    streamer = VideoStreamer(0, 0, 320, 240, fit_display=False)
    streamer.play(test_video_path)

    # Check that the correct commands were sent to the player
    calls = [call[0][0] for call in mock_proc.stdin.write.call_args_list]
    assert any("load" in c for c in calls)

    # Simulate stopping the video
    streamer.stop()
    calls = [call[0][0] for call in mock_proc.stdin.write.call_args_list]
    assert any("stop" in c for c in calls)

    # Simulate killing the player
    streamer.kill()
    assert mock_proc.terminate.called

@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true",
    reason="Skipped on GitHub Actions CI"
)
def test_video_player_integration(test_video_path):
    """Test starting the video player and playing a video file."""

    # Import here to avoid circular import issues
    from picframe.video_streamer import VideoStreamer

    # Create the VideoStreamer and play a video
    streamer = VideoStreamer(0, 0, 320, 240, fit_display=False)
    assert streamer.player_alive()
    streamer.play(test_video_path)
    time.sleep(3)  # Allow some time for the player to start
    streamer.pause(True)
    time.sleep(3)  # Allow some time for the player to pause
    assert streamer.is_playing() 
    streamer.pause(False)
    time.sleep(2)  # Allow some time for the player to start
    streamer.stop()
    assert streamer.is_playing() is False
    streamer.kill()
    assert streamer.player_alive() is False
