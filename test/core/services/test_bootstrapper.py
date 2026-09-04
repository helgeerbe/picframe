from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.services.bootstrapper import EnvironmentBootstrapper


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path / ".picframe"


def test_bootstrapper_initialization(temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    assert bootstrapper.base_dir == temp_dir
    assert bootstrapper.data_dir == temp_dir / "data"
    assert bootstrapper.config_db_path == temp_dir / "data" / "config.db3"
    assert bootstrapper.media_db_path == temp_dir / "data" / "media_cache.db3"


def test_create_directories(temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    bootstrapper._create_directories()
    assert bootstrapper.data_dir.exists()
    assert bootstrapper.data_dir.is_dir()


def test_copy_assets(temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir / "user_dir"))
    bootstrapper._create_directories()

    # Create fake package directory structure
    fake_pkg_dir = temp_dir / "fake_picframe"
    fake_data_dir = fake_pkg_dir / "data"
    fake_html_dir = fake_pkg_dir / "html"

    fake_data_dir.mkdir(parents=True)
    (fake_data_dir / "test.txt").touch()
    (fake_data_dir / "test_dir").mkdir()
    (fake_data_dir / "test_dir" / "inner.txt").touch()
    (fake_data_dir / "no_pictures.jpg").touch()

    fake_html_dir.mkdir(parents=True)
    (fake_html_dir / "index.html").touch()

    with patch("picframe.__file__", str(fake_pkg_dir / "__init__.py")):
        bootstrapper._copy_assets()

    # Assert files were copied
    assert (bootstrapper.data_dir / "test.txt").exists()
    assert (bootstrapper.data_dir / "test_dir").is_dir()
    assert (bootstrapper.data_dir / "test_dir" / "inner.txt").exists()
    assert (bootstrapper.data_dir / "no_pictures.jpg").exists()
    assert (bootstrapper.base_dir / "html" / "index.html").exists()


@patch("picframe.core.services.bootstrapper.input")
def test_prompt_deletion_keep(mock_input: MagicMock, temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    test_file = temp_dir / "test.db"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()

    mock_input.return_value = "n"
    result = bootstrapper._prompt_deletion(test_file, "Test")

    assert result is False
    assert test_file.exists()


@patch("picframe.core.services.bootstrapper.input")
def test_prompt_deletion_delete(mock_input: MagicMock, temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    test_file = temp_dir / "test.db"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()

    mock_input.return_value = "y"
    result = bootstrapper._prompt_deletion(test_file, "Test")

    assert result is True
    assert not test_file.exists()


def test_prompt_deletion_force(temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir), force=True)
    test_file = temp_dir / "test.db"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()

    result = bootstrapper._prompt_deletion(test_file, "Test")

    assert result is True
    assert not test_file.exists()


def test_bootstrap_full(temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))

    with (
        patch.object(bootstrapper, "_create_directories") as mock_create_dir,
        patch.object(bootstrapper, "_copy_assets") as mock_copy_assets,
        patch.object(bootstrapper, "_copy_overlay_plugins") as mock_copy_plugins,
        patch.object(bootstrapper, "_prompt_deletion", return_value=True) as mock_prompt,
        patch("picframe.core.services.bootstrapper.SQLiteConfigRepository") as mock_config_repo,
        patch("picframe.core.services.bootstrapper.SQLiteMediaRepository"),
        patch.object(bootstrapper, "_seed_default_config") as mock_seed,
    ):
        # Mock the repo to return empty config so seeding is triggered
        mock_repo_instance = mock_config_repo.return_value
        mock_repo_instance.get_all_app_config.return_value = {}

        bootstrapper.bootstrap()

        mock_create_dir.assert_called_once()
        mock_copy_assets.assert_called_once()
        mock_copy_plugins.assert_called_once()
        assert mock_prompt.call_count == 2
        mock_seed.assert_called_once_with(mock_repo_instance)


def test_copy_overlay_plugins_copies_builtins(tmp_path: Path) -> None:
    """Built-in overlay plugins are copied to ``~/.picframe/overlay-plugins`` on init (#739)."""
    bootstrapper = EnvironmentBootstrapper(base_dir=str(tmp_path / ".picframe"))
    bootstrapper._create_directories()
    bootstrapper._copy_overlay_plugins()

    plugins_dest = bootstrapper.base_dir / "overlay-plugins"
    assert plugins_dest.is_dir()
    # The three built-in plugins must be present with their manifest + entry.
    for plugin_id in ("clock", "weather", "meta"):
        assert (plugins_dest / plugin_id / "plugin.json").is_file(), plugin_id
        assert (plugins_dest / plugin_id / "index.html").is_file(), plugin_id


def test_copy_overlay_plugins_overwrites_existing(tmp_path: Path) -> None:
    """Re-init force-overwrites built-in plugin dirs (updates propagate) but keeps user plugins."""
    bootstrapper = EnvironmentBootstrapper(base_dir=str(tmp_path / ".picframe"))
    bootstrapper._create_directories()
    bootstrapper._copy_overlay_plugins()
    plugins_dest = bootstrapper.base_dir / "overlay-plugins"

    # Simulate a user modification inside a built-in plugin dir.
    (plugins_dest / "clock" / "user-edit.txt").write_text("mine", encoding="utf-8")
    # Add a user-created plugin that is NOT built-in.
    (plugins_dest / "myplugin").mkdir()
    (plugins_dest / "myplugin" / "plugin.json").write_text("{}", encoding="utf-8")

    bootstrapper._copy_overlay_plugins()

    # Built-in clock dir was overwritten: user edit gone, manifest refreshed.
    assert not (plugins_dest / "clock" / "user-edit.txt").exists()
    assert (plugins_dest / "clock" / "plugin.json").is_file()
    # User-created plugin is preserved.
    assert (plugins_dest / "myplugin" / "plugin.json").is_file()


def test_default_config_yaml_validates_through_app_config() -> None:
    """The seed YAML must survive AppConfig validation so `picframe init` re-seeding works.

    Guards against YAML 1.1 bool coercion of unquoted values like ``off``/``on``
    into Python bools for string-typed fields (e.g. ``viewer.clock_extra_source``),
    which would raise a Pydantic ValidationError during seeding.
    """

    import yaml

    import picframe
    from picframe.api.models import AppConfig

    pkg_dir = Path(picframe.__file__).parent
    default_yaml = pkg_dir / "config" / "default_config.yaml"
    raw = yaml.safe_load(default_yaml.read_text())
    config = AppConfig(**raw)
    assert config.overlay.enabled is False
    assert config.overlay.backend == "webkit"
    assert config.overlay.enabled_plugins == ["clock", "meta"]
    assert config.overlay.visible_plugins == ["clock"]
    assert config.overlay.enabled_input_types == ["touch", "mouse", "keyboard"]
    assert config.overlay.idle_hide_seconds == 5.0
    assert config.overlay.plugin_config == {}
    assert config.overlay.plugin_layout == {}
