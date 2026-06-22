from metatron_installer.envfile import atomic_write, merge_env

TEMPLATE = """\
# Database
POSTGRES_PASSWORD=metatron_dev
LLM_PROVIDER=ollama

# Secrets
FERNET_KEY=
"""


def test_replaces_existing_key_in_place_keeping_comments():
    out = merge_env(TEMPLATE, {"POSTGRES_PASSWORD": "s3cret", "FERNET_KEY": "abc"})
    lines = out.splitlines()
    assert "# Database" in lines
    assert "POSTGRES_PASSWORD=s3cret" in lines
    assert "FERNET_KEY=abc" in lines
    # comment for Secrets preserved
    assert "# Secrets" in lines


def test_appends_unknown_key():
    out = merge_env(TEMPLATE, {"NEW_KEY": "v"})
    assert out.rstrip().endswith("NEW_KEY=v")


def test_does_not_touch_unrelated_keys():
    out = merge_env(TEMPLATE, {"FERNET_KEY": "abc"})
    assert "LLM_PROVIDER=ollama" in out


def test_no_double_trailing_newline_when_template_ends_blank():
    out = merge_env("A=1\n\n", {"A": "2"})
    assert out.endswith("2\n")
    assert not out.endswith("\n\n")


def test_atomic_write_creates_file(tmp_path):
    target = tmp_path / ".env"
    atomic_write(target, "A=1\n")
    assert target.read_text() == "A=1\n"


def test_atomic_write_overwrites_existing(tmp_path):
    target = tmp_path / ".env"
    target.write_text("OLD=1\n")
    atomic_write(target, "NEW=2\n")
    assert target.read_text() == "NEW=2\n"
