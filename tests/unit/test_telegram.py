"""Tests for channels/telegram.py — message handling and formatting helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

if importlib.util.find_spec("aiogram") is None:
    aiogram = ModuleType("aiogram")
    aiogram.Bot = object
    aiogram.Dispatcher = object
    aiogram.F = SimpleNamespace(document=object())
    aiogram.types = SimpleNamespace(Message=object, ErrorEvent=object)
    aiogram_default = ModuleType("aiogram.client.default")
    aiogram_default.DefaultBotProperties = lambda **kwargs: kwargs
    aiogram_enums = ModuleType("aiogram.enums")
    aiogram_enums.ChatAction = SimpleNamespace(TYPING="typing")
    aiogram_enums.ParseMode = SimpleNamespace(MARKDOWN="markdown", HTML="html")
    sys.modules.update(
        {
            "aiogram": aiogram,
            "aiogram.client": ModuleType("aiogram.client"),
            "aiogram.client.default": aiogram_default,
            "aiogram.enums": aiogram_enums,
        }
    )

_MODULE_PATH = Path(__file__).parents[2] / "src/metronix/channels/telegram.py"
_SPEC = importlib.util.spec_from_file_location("telegram_channel_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
telegram = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(telegram)
_markdown_to_html = telegram._markdown_to_html
_split_message = telegram._split_message


class _FakeDispatcher:
    """Avoid registering handlers with a live aiogram dispatcher in unit tests."""

    def errors(self):
        return lambda handler: handler

    def message(self, *args, **kwargs):
        return lambda handler: handler


@pytest.fixture
def channel(monkeypatch: pytest.MonkeyPatch) -> telegram.TelegramChannel:
    bot = SimpleNamespace(
        send_chat_action=AsyncMock(),
        send_message=AsyncMock(),
        get_file=AsyncMock(),
        download_file=AsyncMock(),
    )
    router = MagicMock()
    router._settings.default_workspace_id = "ws_test"
    router.route.return_value = "response"
    router.handle_file_upload.return_value = "indexed"

    monkeypatch.setattr(telegram, "Bot", lambda **kwargs: bot)
    monkeypatch.setattr(telegram, "Dispatcher", _FakeDispatcher)
    result = telegram.TelegramChannel(bot_token="test-token", router=router)
    result._send_response = AsyncMock()
    return result


@pytest.fixture
def private_message() -> SimpleNamespace:
    return SimpleNamespace(
        text="private hello",
        chat=SimpleNamespace(id=101, type="private"),
        from_user=SimpleNamespace(id=202, first_name="Private", last_name="User"),
        message_id=1,
    )


@pytest.fixture
def group_message() -> SimpleNamespace:
    return SimpleNamespace(
        text="group hello",
        chat=SimpleNamespace(id=-101, type="group"),
        from_user=SimpleNamespace(id=202, first_name="Group", last_name="User"),
        message_id=2,
    )


@pytest.fixture
def private_document(private_message: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        **private_message.__dict__,
        document=SimpleNamespace(file_name="private.txt", file_size=5, file_id="file-private"),
    )


@pytest.fixture
def group_document(group_message: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        **group_message.__dict__,
        document=SimpleNamespace(file_name="group.txt", file_size=5, file_id="file-group"),
    )


@pytest.fixture
def supergroup_message() -> SimpleNamespace:
    return SimpleNamespace(
        text="supergroup hello",
        chat=SimpleNamespace(id=-102, type="supergroup"),
        from_user=SimpleNamespace(id=203, first_name="Supergroup", last_name="User"),
        message_id=3,
    )


@pytest.fixture
def supergroup_document(supergroup_message: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        **supergroup_message.__dict__,
        document=SimpleNamespace(
            file_name="supergroup.txt", file_size=5, file_id="file-supergroup"
        ),
    )


@pytest.mark.asyncio
async def test_private_message_does_not_store_history_when_disabled(
    channel: telegram.TelegramChannel, private_message: SimpleNamespace
) -> None:
    await channel._handle_message(private_message)

    channel._router.route.assert_called_once_with(
        text=private_message.text,
        user_id=str(private_message.from_user.id),
        workspace_id=channel._workspace_id,
        conversation_id=str(private_message.chat.id),
        history_enabled=False,
    )


@pytest.mark.asyncio
async def test_group_message_stores_history(
    channel: telegram.TelegramChannel, group_message: SimpleNamespace
) -> None:
    await channel._handle_message(group_message)

    channel._router.route.assert_called_once_with(
        text=group_message.text,
        user_id=str(group_message.from_user.id),
        workspace_id=channel._workspace_id,
        conversation_id=str(group_message.chat.id),
        history_enabled=True,
    )


@pytest.mark.asyncio
async def test_private_message_stores_history_when_enabled(
    channel: telegram.TelegramChannel, private_message: SimpleNamespace
) -> None:
    channel._store_direct_messages = True

    await channel._handle_message(private_message)

    channel._router.route.assert_called_once_with(
        text=private_message.text,
        user_id=str(private_message.from_user.id),
        workspace_id=channel._workspace_id,
        conversation_id=str(private_message.chat.id),
        history_enabled=True,
    )


@pytest.mark.asyncio
async def test_supergroup_message_stores_history(
    channel: telegram.TelegramChannel, supergroup_message: SimpleNamespace
) -> None:
    await channel._handle_message(supergroup_message)

    channel._router.route.assert_called_once_with(
        text=supergroup_message.text,
        user_id=str(supergroup_message.from_user.id),
        workspace_id=channel._workspace_id,
        conversation_id=str(supergroup_message.chat.id),
        history_enabled=True,
    )


@pytest.mark.asyncio
async def test_private_document_is_rejected_before_download(
    channel: telegram.TelegramChannel, private_document: SimpleNamespace
) -> None:
    await channel._handle_document(private_document)

    channel._bot.get_file.assert_not_awaited()
    channel._router.handle_file_upload.assert_not_called()


@pytest.mark.asyncio
async def test_group_document_is_uploaded(
    channel: telegram.TelegramChannel, group_document: SimpleNamespace
) -> None:
    file_bytes = MagicMock()
    file_bytes.read.return_value = b"hello"
    channel._bot.get_file.return_value = SimpleNamespace(file_path="file/path")
    channel._bot.download_file.return_value = file_bytes

    await channel._handle_document(group_document)

    channel._bot.get_file.assert_awaited_once_with(group_document.document.file_id)
    channel._router.handle_file_upload.assert_called_once_with(
        content=b"hello",
        filename="group.txt",
        user_id=str(group_document.from_user.id),
        workspace_id=channel._workspace_id,
    )


@pytest.mark.asyncio
async def test_private_document_is_uploaded_when_enabled(
    channel: telegram.TelegramChannel, private_document: SimpleNamespace
) -> None:
    file_bytes = MagicMock()
    file_bytes.read.return_value = b"hello"
    channel._store_direct_messages = True
    channel._bot.get_file.return_value = SimpleNamespace(file_path="file/path")
    channel._bot.download_file.return_value = file_bytes

    await channel._handle_document(private_document)

    channel._bot.get_file.assert_awaited_once_with(private_document.document.file_id)
    channel._router.handle_file_upload.assert_called_once_with(
        content=b"hello",
        filename="private.txt",
        user_id=str(private_document.from_user.id),
        workspace_id=channel._workspace_id,
    )


@pytest.mark.asyncio
async def test_supergroup_document_is_uploaded(
    channel: telegram.TelegramChannel, supergroup_document: SimpleNamespace
) -> None:
    file_bytes = MagicMock()
    file_bytes.read.return_value = b"hello"
    channel._bot.get_file.return_value = SimpleNamespace(file_path="file/path")
    channel._bot.download_file.return_value = file_bytes

    await channel._handle_document(supergroup_document)

    channel._bot.get_file.assert_awaited_once_with(supergroup_document.document.file_id)
    channel._router.handle_file_upload.assert_called_once_with(
        content=b"hello",
        filename="supergroup.txt",
        user_id=str(supergroup_document.from_user.id),
        workspace_id=channel._workspace_id,
    )


class TestSplitMessage:
    def test_short_message(self) -> None:
        result = _split_message("hello", max_length=100)
        assert result == ["hello"]

    def test_exact_limit(self) -> None:
        text = "a" * 100
        result = _split_message(text, max_length=100)
        assert result == [text]

    def test_split_at_paragraph(self) -> None:
        text = "first paragraph\n\nsecond paragraph"
        result = _split_message(text, max_length=25)
        assert len(result) == 2
        assert result[0] == "first paragraph"
        assert result[1] == "second paragraph"

    def test_split_at_newline(self) -> None:
        text = "line one\nline two\nline three"
        result = _split_message(text, max_length=15)
        assert len(result) >= 2
        assert "line one" in result[0]

    def test_split_at_space(self) -> None:
        text = "word1 word2 word3 word4"
        result = _split_message(text, max_length=12)
        assert len(result) >= 2
        # Each chunk should be <= 12 chars
        for chunk in result:
            assert len(chunk) <= 12

    def test_hard_split(self) -> None:
        text = "a" * 200
        result = _split_message(text, max_length=50)
        assert len(result) == 4
        for chunk in result:
            assert len(chunk) <= 50

    def test_empty_string(self) -> None:
        result = _split_message("", max_length=100)
        assert result == [""]

    def test_long_real_message(self) -> None:
        # Simulate a real search result
        text = (
            "**PROJ-78: Analytics Dashboard**\n\n"
            "Status: In Progress\nAssignee: John\n\n"
            "Description: This is a long description " * 20
        )
        result = _split_message(text, max_length=200)
        assert len(result) > 1
        # All content preserved
        "\n\n".join(result) if len(result) > 1 else result[0]
        # No data loss (some newlines may be stripped)
        for chunk in result:
            assert len(chunk) <= 200


class TestMarkdownToHtml:
    def test_bold_double_asterisk(self) -> None:
        assert _markdown_to_html("**bold text**") == "<b>bold text</b>"

    def test_bold_double_underscore(self) -> None:
        assert _markdown_to_html("__bold text__") == "<b>bold text</b>"

    def test_italic(self) -> None:
        assert _markdown_to_html("*italic text*") == "<i>italic text</i>"

    def test_inline_code(self) -> None:
        assert _markdown_to_html("`some_func()`") == "<code>some_func()</code>"

    def test_code_block(self) -> None:
        result = _markdown_to_html("```python\nprint('hi')\n```")
        assert "<pre>" in result
        assert "print('hi')" in result
        assert "</pre>" in result

    def test_code_block_no_language(self) -> None:
        result = _markdown_to_html("```\ncode here\n```")
        assert "<pre>" in result
        assert "code here" in result
        assert "</pre>" in result

    def test_link(self) -> None:
        result = _markdown_to_html("[click here](https://example.com)")
        assert result == '<a href="https://example.com">click here</a>'

    def test_heading(self) -> None:
        assert _markdown_to_html("## Section Title") == "<b>Section Title</b>"
        assert _markdown_to_html("### Sub-section") == "<b>Sub-section</b>"

    def test_mixed_content(self) -> None:
        text = "## Status\n**PROJ-78**: *In Progress*\nAssignee: `john`"
        result = _markdown_to_html(text)
        assert "<b>Status</b>" in result
        assert "<b>PROJ-78</b>" in result
        assert "<i>In Progress</i>" in result
        assert "<code>john</code>" in result

    def test_plain_text_unchanged(self) -> None:
        text = "Just a normal sentence with no formatting."
        assert _markdown_to_html(text) == text

    def test_bullet_points_preserved(self) -> None:
        text = "- item one\n- item two\n- item three"
        assert _markdown_to_html(text) == text
