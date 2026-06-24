from metronix.export.render import slugify_segment, unique_slug


def test_slug_strips_path_chars():
    assert "/" not in slugify_segment("a/b/../c")
    assert "\\" not in slugify_segment("a\\b")
    assert slugify_segment("..") not in ("", ".", "..")


def test_slug_non_empty_for_garbage():
    assert slugify_segment("***") != ""
    assert slugify_segment("") != ""


def test_unique_slug_collision_suffix():
    used: set[str] = set()
    a = unique_slug("agent/one", used)
    b = unique_slug("agent/one", used)  # same raw -> same slug -> collision
    assert a != b
    assert a in used and b in used
