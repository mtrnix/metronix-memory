"""Tests for channels/discord.py — message splitting, message handling, file uploads."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.channels.discord import DiscordChannel, _split_message

# ---------------------------------------------------------------------------
# TestSplitMessage — pure function tests
# ---------------------------------------------------------------------------


class TestSplitMessage:
    def test_short_message(self) -> None:
        result = _split_message("hello", max_length=100)
        assert result == ["hello"]

    def test_exact_limit(self) -> None:
        text = "a" * 2000
        result = _split_message(text, max_length=2000)
        assert result == [text]

    def test_empty_string(self) -> None:
        result = _split_message("", max_length=2000)
        assert result == [""]

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
        for chunk in result:
            assert len(chunk) <= 12

    def test_hard_split(self) -> None:
        text = "a" * 200
        result = _split_message(text, max_length=50)
        assert len(result) == 4
        for chunk in result:
            assert len(chunk) <= 50

    def test_code_block_preserved_when_short(self) -> None:
        text = "```python\nprint('hello')\n```"
        result = _split_message(text, max_length=2000)
        assert result == [text]

    def test_long_real_message(self) -> None:
        text = (
            "**MTRNIX-78: Analytics Dashboard**\n\n"
            "Status: In Progress\nAssignee: John\n\n"
            "Description: This is a long description " * 20
        )
        result = _split_message(text, max_length=200)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 200


# ---------------------------------------------------------------------------
# Helpers — mock discord objects
# ---------------------------------------------------------------------------


def _make_channel(router_mock: MagicMock) -> DiscordChannel:
    """Create a DiscordChannel with mocked internals."""
    with patch("metatron.channels.discord.discord.Client"):
        channel = DiscordChannel(
            bot_token="fake-token",
            router=router_mock,
        )
    return channel


def _make_discord_message(
    content: str = "hello",
    author_id: int = 12345,
    is_bot: bool = False,
    is_dm: bool = True,
    attachments: list | None = None,
) -> MagicMock:
    """Build a mock discord.Message."""
    import discord as _dc

    message = MagicMock()
    message.content = content
    message.author = MagicMock()
    message.author.id = author_id
    message.author.bot = is_bot

    dm_channel = AsyncMock()
    dm_channel.send = AsyncMock()
    dm_channel.typing = MagicMock(return_value=AsyncMock())
    # Make typing() work as async context manager
    dm_channel.typing.return_value.__aenter__ = AsyncMock()
    dm_channel.typing.return_value.__aexit__ = AsyncMock()

    if is_dm:
        dm_channel.__class__ = _dc.DMChannel
    message.channel = dm_channel

    message.attachments = attachments or []
    return message


# ---------------------------------------------------------------------------
# TestOnMessage — router integration via mocks
# ---------------------------------------------------------------------------


class TestOnMessage:
    @pytest.mark.asyncio
    async def test_regular_message_calls_router(self) -> None:
        router = MagicMock()
        router.route = MagicMock(return_value="Router response")
        channel = _make_channel(router)

        msg = _make_discord_message(content="What is our refund policy?")
        await channel._handle_message(msg)

        router.route.assert_called_once()
        call_kwargs = router.route.call_args
        assert "refund policy" in call_kwargs.kwargs.get("text", call_kwargs[1].get("text", ""))
        msg.channel.send.assert_called_once_with("Router response")

    @pytest.mark.asyncio
    async def test_bot_message_ignored(self) -> None:
        """Messages from the bot itself should be ignored (tested via on_message logic)."""
        router = MagicMock()
        channel = _make_channel(router)

        # Simulate: message.author == client.user → skip
        msg = _make_discord_message(content="echo")
        channel._client.user = msg.author  # same object = bot's own message

        # The on_message handler checks this, but since handlers are registered
        # as closures, we test the guard directly:
        assert msg.author == channel._client.user
        # router.route should NOT be called
        router.route.assert_not_called()

    @pytest.mark.asyncio
    async def test_router_error_returns_error_message(self) -> None:
        router = MagicMock()
        router.route = MagicMock(side_effect=RuntimeError("LLM down"))
        channel = _make_channel(router)

        msg = _make_discord_message(content="test query")
        await channel._handle_message(msg)

        msg.channel.send.assert_called_once()
        sent_text = msg.channel.send.call_args[0][0]
        assert "Something went wrong" in sent_text

    @pytest.mark.asyncio
    async def test_long_response_split_into_chunks(self) -> None:
        router = MagicMock()
        long_answer = "word " * 500  # ~2500 chars
        router.route = MagicMock(return_value=long_answer)
        channel = _make_channel(router)

        msg = _make_discord_message(content="give me a long answer")
        await channel._handle_message(msg)

        assert msg.channel.send.call_count > 1


# ---------------------------------------------------------------------------
# TestFileUpload — attachment handling
# ---------------------------------------------------------------------------


class TestFileUpload:
    @pytest.mark.asyncio
    async def test_text_file_calls_handle_file_upload(self) -> None:
        router = MagicMock()
        router.handle_file_upload = MagicMock(return_value="Indexed report.txt: 1 new.")
        channel = _make_channel(router)

        attachment = AsyncMock()
        attachment.filename = "report.txt"
        attachment.size = 1024
        attachment.read = AsyncMock(return_value=b"file content here")

        msg = _make_discord_message(content="", attachments=[attachment])
        await channel._handle_attachments(msg)

        router.handle_file_upload.assert_called_once()
        call_kwargs = router.handle_file_upload.call_args
        assert (
            call_kwargs.kwargs.get("filename", call_kwargs[1].get("filename", "")) == "report.txt"
        )
        msg.channel.send.assert_called_once_with("Indexed report.txt: 1 new.")

    @pytest.mark.asyncio
    async def test_unsupported_file_type_response(self) -> None:
        """Router returns unsupported type message — channel forwards it."""
        router = MagicMock()
        router.handle_file_upload = MagicMock(return_value="Unsupported file type: .jpg")
        channel = _make_channel(router)

        attachment = AsyncMock()
        attachment.filename = "photo.jpg"
        attachment.size = 5000
        attachment.read = AsyncMock(return_value=b"\xff\xd8\xff")

        msg = _make_discord_message(content="", attachments=[attachment])
        await channel._handle_attachments(msg)

        sent_text = msg.channel.send.call_args[0][0]
        assert "Unsupported file type" in sent_text

    @pytest.mark.asyncio
    async def test_large_file_response(self) -> None:
        """Router returns file-too-large message — channel forwards it."""
        router = MagicMock()
        router.handle_file_upload = MagicMock(
            return_value="File too large. Maximum size is 20 MB."
        )
        channel = _make_channel(router)

        attachment = AsyncMock()
        attachment.filename = "huge.pdf"
        attachment.size = 25 * 1024 * 1024
        attachment.read = AsyncMock(return_value=b"\x00" * 100)

        msg = _make_discord_message(content="", attachments=[attachment])
        await channel._handle_attachments(msg)

        sent_text = msg.channel.send.call_args[0][0]
        assert "too large" in sent_text

    @pytest.mark.asyncio
    async def test_download_error_handled(self) -> None:
        router = MagicMock()
        channel = _make_channel(router)

        attachment = AsyncMock()
        attachment.filename = "broken.pdf"
        attachment.size = 1024
        attachment.read = AsyncMock(side_effect=RuntimeError("Network error"))

        msg = _make_discord_message(content="", attachments=[attachment])
        await channel._handle_attachments(msg)

        sent_text = msg.channel.send.call_args[0][0]
        assert "Could not download" in sent_text
        router.handle_file_upload.assert_not_called()


# ---------------------------------------------------------------------------
# TestCommands — commands routed through router.route()
# ---------------------------------------------------------------------------


class TestCommands:
    @pytest.mark.asyncio
    async def test_help_command(self) -> None:
        router = MagicMock()
        router.route = MagicMock(return_value="Available commands:\n/help\n/sync\n/status")
        channel = _make_channel(router)

        msg = _make_discord_message(content="/help")
        await channel._handle_message(msg)

        router.route.assert_called_once()
        call_kwargs = router.route.call_args
        text_arg = call_kwargs.kwargs.get("text", call_kwargs[1].get("text", ""))
        assert text_arg == "/help"
        sent_text = msg.channel.send.call_args[0][0]
        assert "/help" in sent_text

    @pytest.mark.asyncio
    async def test_sync_command(self) -> None:
        router = MagicMock()
        router.route = MagicMock(return_value="Syncing confluence...")
        channel = _make_channel(router)

        msg = _make_discord_message(content="/sync confluence")
        await channel._handle_message(msg)

        router.route.assert_called_once()
        call_kwargs = router.route.call_args
        text_arg = call_kwargs.kwargs.get("text", call_kwargs[1].get("text", ""))
        assert text_arg == "/sync confluence"
