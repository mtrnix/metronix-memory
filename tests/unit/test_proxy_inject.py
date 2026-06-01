"""inject_into_system (MTRNIX-372 P3)."""

from metatron.proxy.inject import inject_into_system


def test_appends_to_existing_system() -> None:
    msgs = [
        {"role": "system", "content": "You are Bob."},
        {"role": "user", "content": "hi"},
    ]
    out = inject_into_system(msgs, "<preferences>\n- x\n</preferences>")
    assert out[0]["role"] == "system"
    assert out[0]["content"].startswith("You are Bob.")
    assert "<preferences>" in out[0]["content"]
    assert out[1] == {"role": "user", "content": "hi"}
    # original list not mutated
    assert "<preferences>" not in msgs[0]["content"]


def test_prepends_system_when_absent() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    out = inject_into_system(msgs, "<preferences>\n- x\n</preferences>")
    assert out[0]["role"] == "system"
    assert "<preferences>" in out[0]["content"]
    assert out[1] == {"role": "user", "content": "hi"}


def test_empty_enrichment_is_noop() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    out = inject_into_system(msgs, "")
    assert out == msgs
