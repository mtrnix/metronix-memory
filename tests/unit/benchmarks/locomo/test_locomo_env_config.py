from __future__ import annotations

from pathlib import Path

from benchmarks.locomo.scripts.env_config import _parse_env_file


def test_parse_env_file_ignores_comments_and_quotes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comment\nFOO=bar\nBAZ="quoted"\nEMPTY=\n',
        encoding="utf-8",
    )
    values = _parse_env_file(env_file)
    assert values == {"FOO": "bar", "BAZ": "quoted", "EMPTY": ""}


def test_parse_env_file_strips_inline_comments_like_compose(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "A=value   # trailing comment\n"
        "B=   # empty then comment\n"
        "C=#immediate\n"
        "D=value#nospace\n"
        'E="quoted # hash"\n'
        "F='single # hash'\n"
        'G="quoted" # comment\n'
        "H=http://host/path#fragment\n",
        encoding="utf-8",
    )
    values = _parse_env_file(env_file)
    assert values == {
        "A": "value",
        "B": "",
        "C": "",
        "D": "value#nospace",
        "E": "quoted # hash",
        "F": "single # hash",
        "G": "quoted",
        "H": "http://host/path#fragment",
    }
