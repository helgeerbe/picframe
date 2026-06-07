from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "picframe"

REMOVED_LEGACY_MODULES = {
    "controller",
    "get_image_meta",
    "image_cache",
    "interface_http",
    "interface_mqtt",
    "interface_peripherals",
    "model",
    "start",
    "video_metadata",
    "video_player",
    "video_streamer",
    "viewer_display",
}


def test_legacy_runtime_modules_are_removed() -> None:
    for module_name in REMOVED_LEGACY_MODULES:
        assert not (SRC_ROOT / f"{module_name}.py").exists()


def test_next_gen_paths_do_not_import_removed_legacy_modules() -> None:
    checked_roots = [
        SRC_ROOT / "api",
        SRC_ROOT / "core",
        SRC_ROOT / "infrastructure",
        SRC_ROOT / "main.py",
    ]
    legacy_import_tokens = {
        f"picframe.{module_name}" for module_name in REMOVED_LEGACY_MODULES
    } | {
        f"from picframe import {module_name}" for module_name in REMOVED_LEGACY_MODULES
    }

    for root in checked_roots:
        paths = [root] if root.is_file() else list(root.rglob("*.py"))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for token in legacy_import_tokens:
                assert token not in text, f"{path} imports removed legacy module via {token}"
