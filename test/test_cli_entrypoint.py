import sys
import tomllib
from pathlib import Path

import pytest

from picframe import main as picframe_main


def test_package_console_script_points_to_next_gen_cli() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert pyproject["project"]["scripts"]["picframe"] == "picframe.main:main"


@pytest.mark.parametrize(
    "argv",
    [
        ["picframe", "--help"],
        ["picframe", "init", "--help"],
        ["picframe", "run", "--help"],
    ],
)
def test_next_gen_cli_help_commands(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc_info:
        picframe_main.main()

    assert exc_info.value.code == 0
