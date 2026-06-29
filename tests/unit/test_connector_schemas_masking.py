from metronix.connectors.schemas import (
    mask_secrets,
    merge_config,
    validate_config_for_update,
)


def test_mask_secrets_reveals_last_four_for_long_secret():
    masked = mask_secrets("confluence", {"api_token": "abcdef1234wxyz"})
    assert masked["api_token"] == "***wxyz"


def test_mask_secrets_hides_short_secret_fully():
    masked = mask_secrets("confluence", {"api_token": "abcd"})
    assert masked["api_token"] == "***"


def test_mask_secrets_leaves_non_secret_and_empty_untouched():
    masked = mask_secrets(
        "confluence",
        {"url": "https://x.atlassian.net", "api_token": ""},
    )
    assert masked["url"] == "https://x.atlassian.net"
    assert masked["api_token"] == ""


def test_merge_config_preserves_old_secret_for_legacy_mask():
    merged = merge_config(
        "confluence",
        {"api_token": "REAL-SECRET"},
        {"api_token": "***"},
    )
    assert merged["api_token"] == "REAL-SECRET"


def test_merge_config_preserves_old_secret_for_last4_mask():
    merged = merge_config(
        "confluence",
        {"api_token": "REAL-SECRET-wxyz"},
        {"api_token": "***wxyz"},
    )
    assert merged["api_token"] == "REAL-SECRET-wxyz"


def test_merge_config_keeps_new_real_secret():
    merged = merge_config(
        "confluence",
        {"api_token": "OLD"},
        {"api_token": "NEW-TOKEN"},
    )
    assert merged["api_token"] == "NEW-TOKEN"


def test_validate_for_update_accepts_masked_secret_as_present():
    errors = validate_config_for_update(
        "confluence",
        {"url": "https://x.atlassian.net", "username": "u", "api_token": "***wxyz"},
    )
    assert errors == []


def test_validate_for_update_flags_missing_required_non_secret():
    errors = validate_config_for_update(
        "confluence",
        {"username": "u", "api_token": "***wxyz"},
    )
    assert any("URL" in e for e in errors)
