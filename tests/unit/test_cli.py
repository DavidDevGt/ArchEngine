import pytest

from archengine import __version__
from archengine.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_unimplemented_command_returns_nonzero() -> None:
    assert main(["validate", "x.yaml"]) == 2
