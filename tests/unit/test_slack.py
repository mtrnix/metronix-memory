"""Tests for channels/slack.py — message splitting, message handling, file uploads."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.channels.slack import SlackChannel, _split_message

# ---------------------------------------------------------------------------
# TestSplitMessage — pure function tests
# ---------------------------------------------------------------------------


class TestSplitMessage:
    def test_short_message(self) -> None:
        result = _split_message("hello", max_length=100)
        assert result == ["hello"]

    def test_exact_limit(self) -> None:
        text = "a" * 4000
        result = _split_message(text, max_length=4000)
        assert result == [text]

    def test_empty_string(self) -> None:
        result = _split_message("", max_length=4000)
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
# Helpers — mock slack objects
# ---------------------------------------------------------------------------


def _make_channel(router_mock: MagicMock) -> SlackChannel:
    """Create a SlackChannel with mocked internals."""
    with (
        patch("metatron.channels.slack.AsyncApp"),
        patch("metatron.channels.slack.AsyncSocketModeHandler"),
    ):
        channel = SlackChannel(
            bot_token="xoxb-fake",
            app_token="xapp-fake",
            router=router_mock,
        )
    return channel


# ---------------------------------------------------------------------------
# TestOnMessage — router integration via mocks
# ---------------------------------------------------------------------------


class TestOnMessage:
    @pytest.mark.asyncio
    async def test_regular_message_calls_router(self) -> None:
        router = MagicMock()
        router.route = MagicMock(return_value="Router response")
        channel = _make_channel(router)

        say = AsyncMock()
        await channel._handle_message("What is our policy?", "U123", say)

        router.route.assert_called_once()
        call_kwargs = router.route.call_args
        assert "policy" in call_kwargs.kwargs.get("text", call_kwargs[1].get("text", ""))
        say.assert_called_once_with("Router response")

    @pytest.mark.asyncio
    async def test_router_error_returns_error_message(self) -> None:
        router = MagicMock()
        router.route = MagicMock(side_effect=RuntimeError("LLM down"))
        channel = _make_channel(router)

        say = AsyncMock()
        await channel._handle_message("test query", "U123", say)

        say.assert_called_once()
        sent_text = say.call_args[0][0]
        assert "Something went wrong" in sent_text

    @pytest.mark.asyncio
    async def test_long_response_split_into_chunks(self) -> None:
        router = MagicMock()
        long_answer = "word " * 1000  # ~5000 chars
        router.route = MagicMock(return_value=long_answer)
        channel = _make_channel(router)

        say = AsyncMock()
        await channel._handle_message("give me a long answer", "U123", say)

        assert say.call_count > 1


# ---------------------------------------------------------------------------
# TestFileUpload — attachment handling
# ---------------------------------------------------------------------------


class TestFileUpload:
    @pytest.mark.asyncio
    async def test_file_calls_handle_file_upload(self) -> None:
        router = MagicMock()
        router.handle_file_upload = MagicMock(return_value="Indexed report.txt: 1 new.")
        channel = _make_channel(router)

        say = AsyncMock()
        files = [
            {
                "name": "report.txt",
                "size": 1024,
                "url_private_download": "https://files.slack.com/fake/report.txt",
            }
        ]

        with patch("metatron.channels.slack.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.content = b"file content here"
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_cls.return_value = mock_client

            await channel._handle_files(files, "U123", say)

        router.handle_file_upload.assert_called_once()
        call_kwargs = router.handle_file_upload.call_args
        assert (
            call_kwargs.kwargs.get("filename", call_kwargs[1].get("filename", "")) == "report.txt"
        )

    @pytest.mark.asyncio
    async def test_unsupported_file_type_response(self) -> None:
        router = MagicMock()
        router.handle_file_upload = MagicMock(return_value="Unsupported file type: .jpg")
        channel = _make_channel(router)

        say = AsyncMock()
        files = [
            {
                "name": "photo.jpg",
                "size": 5000,
                "url_private_download": "https://files.slack.com/fake/photo.jpg",
            }
        ]

        with patch("metatron.channels.slack.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.content = b"\xff\xd8\xff"
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_cls.return_value = mock_client

            await channel._handle_files(files, "U123", say)

        sent_text = say.call_args[0][0]
        assert "Unsupported file type" in sent_text

    @pytest.mark.asyncio
    async def test_download_error_handled(self) -> None:
        router = MagicMock()
        channel = _make_channel(router)

        say = AsyncMock()
        files = [
            {
                "name": "broken.pdf",
                "size": 1024,
                "url_private_download": "https://files.slack.com/fake/broken.pdf",
            }
        ]

        with patch("metatron.channels.slack.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=RuntimeError("Network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await channel._handle_files(files, "U123", say)

        sent_text = say.call_args[0][0]
        assert "Could not download" in sent_text
        router.handle_file_upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_url_handled(self) -> None:
        router = MagicMock()
        channel = _make_channel(router)

        say = AsyncMock()
        files = [{"name": "nourl.txt", "size": 100}]

        await channel._handle_files(files, "U123", say)

        sent_text = say.call_args[0][0]
        assert "Could not get download URL" in sent_text


# ---------------------------------------------------------------------------
# TestCommands — commands routed through router.route()
# ---------------------------------------------------------------------------


class TestCommands:
    @pytest.mark.asyncio
    async def test_help_command(self) -> None:
        router = MagicMock()
        router.route = MagicMock(return_value="Available commands:\n/help\n/sync\n/status")
        channel = _make_channel(router)

        say = AsyncMock()
        await channel._handle_message("/help", "U123", say)

        router.route.assert_called_once()
        call_kwargs = router.route.call_args
        text_arg = call_kwargs.kwargs.get("text", call_kwargs[1].get("text", ""))
        assert text_arg == "/help"

    @pytest.mark.asyncio
    async def test_sync_command(self) -> None:
        router = MagicMock()
        router.route = MagicMock(return_value="Syncing confluence...")
        channel = _make_channel(router)

        say = AsyncMock()
        await channel._handle_message("/sync confluence", "U123", say)

        router.route.assert_called_once()
        call_kwargs = router.route.call_args
        text_arg = call_kwargs.kwargs.get("text", call_kwargs[1].get("text", ""))
        assert text_arg == "/sync confluence"
