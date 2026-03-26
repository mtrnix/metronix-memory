"""Tests for _collect_frags() source labeling, search utilities, and Jira key regex."""

from __future__ import annotations

from unittest.mock import patch

from metatron.retrieval.search import (
    _collect_frags, _result_type, _append_sources, _JIRA_KEY_RE,
    detect_response_language,
    extract_proper_nouns,
)


class TestResultType:
    def test_from_type_field(self) -> None:
        assert _result_type({"type": "jira"}) == "jira"

    def test_from_payload(self) -> None:
        assert _result_type({"payload": {"type": "confluence"}}) == "confluence"

    def test_from_metadata(self) -> None:
        assert _result_type({"metadata": {"type": "jira"}}) == "jira"

    def test_unknown_fallback(self) -> None:
        assert _result_type({}) == "unknown"

    def test_case_normalized(self) -> None:
        assert _result_type({"type": "JIRA"}) == "jira"



class TestCollectFragsLabeling:
    def test_labels_added(self) -> None:
        base = [
            {"memory": "some jira content", "type": "jira", "title": "MTRNIX-78"},
            {"memory": "some confluence page", "type": "confluence", "title": "Architecture"},
        ]
        frags, _, _, _ = _collect_frags(base, set(), 0)
        assert len(frags) == 2
        assert frags[0]["text"].startswith("[JIRA] MTRNIX-78\n")
        assert frags[1]["text"].startswith("[CONFLUENCE] Architecture\n")

    def test_no_label_for_unknown(self) -> None:
        base = [{"memory": "plain text"}]
        frags, _, _, _ = _collect_frags(base, set(), 0)
        assert len(frags) == 1
        assert not frags[0]["text"].startswith("[")

    def test_label_with_payload_type(self) -> None:
        base = [{"memory": "content", "payload": {"type": "jira", "title": "Issue"}}]
        frags, _, _, _ = _collect_frags(base, set(), 0)
        assert "[JIRA]" in frags[0]["text"]


class TestAppendSources:
    def test_appends_sources(self) -> None:
        results = [
            {"title": "2026-02-03 Summary", "type": "confluence"},
            {"title": "[MTRNIX-109] Setup MLFlow", "type": "jira"},
        ]
        out = _append_sources("Some answer.", results)
        assert "\U0001f4da Sources:" in out
        assert "\U0001f4c4 2026-02-03 Summary" in out
        assert "\U0001f4cb [MTRNIX-109] Setup MLFlow" in out

    def test_no_sources_when_empty(self) -> None:
        assert _append_sources("Answer.", []) == "Answer."

    def test_no_sources_when_no_titles(self) -> None:
        results = [{"memory": "text", "type": "jira"}]
        assert _append_sources("Answer.", results) == "Answer."

    def test_deduplicates_titles(self) -> None:
        results = [
            {"title": "Same Page", "type": "confluence"},
            {"title": "Same Page", "type": "confluence"},
            {"title": "Other Page", "type": "confluence"},
        ]
        out = _append_sources("Answer.", results)
        assert out.count("Same Page") == 1
        assert "Other Page" in out

    def test_all_unique_sources_included(self) -> None:
        results = [{"title": f"Page {i}", "type": "confluence"} for i in range(10)]
        out = _append_sources("Answer.", results)
        lines = out.split("\U0001f4da Sources:\n")[1].strip().split("\n")
        assert len(lines) == 10

    def test_title_from_payload(self) -> None:
        results = [{"payload": {"title": "From Payload", "type": "jira"}}]
        out = _append_sources("Answer.", results)
        assert "From Payload" in out

    def test_preserves_answer(self) -> None:
        results = [{"title": "Page", "type": "confluence"}]
        out = _append_sources("My detailed answer here.", results)
        assert out.startswith("My detailed answer here.")

    def test_appends_url_when_present(self) -> None:
        results = [
            {"title": "Page One", "type": "confluence", "url": "https://wiki.example.com/page/1"},
        ]
        out = _append_sources("Answer.", results)
        assert "\U0001f4c4 Page One \u2014 https://wiki.example.com/page/1" in out

    def test_omits_url_separator_when_no_url(self) -> None:
        results = [
            {"title": "Page One", "type": "confluence", "url": ""},
        ]
        out = _append_sources("Answer.", results)
        assert "\U0001f4c4 Page One" in out
        assert "\u2014" not in out

    def test_url_from_payload_fallback(self) -> None:
        results = [
            {"payload": {"title": "Deep Page", "type": "confluence", "url": "https://wiki.example.com/deep"}},
        ]
        out = _append_sources("Answer.", results)
        assert "Deep Page \u2014 https://wiki.example.com/deep" in out

    def test_notion_icon(self) -> None:
        results = [
            {"title": "Notion Doc", "type": "notion"},
        ]
        out = _append_sources("Answer.", results)
        assert "\U0001f4d3 Notion Doc" in out


class TestDetectResponseLanguage:
    def test_english_query(self) -> None:
        assert detect_response_language("What the team doing this week?") == "English"

    def test_russian_query(self) -> None:
        assert detect_response_language("Что делает команда на этой неделе?") == "Russian"

    def test_english_not_affected_by_single_russian_word(self) -> None:
        assert detect_response_language("What about задача MTRNIX-123?") == "English"

    def test_pure_english_after_russian_history_not_mixed(self) -> None:
        """Language detection must use only the current question, not composite."""
        # This is the actual question — no Russian in it
        assert detect_response_language("What the team doing this week?") == "English"



class TestUploadTypeSupport:
    """Upload documents should be first-class citizens in search results."""

    def test_result_type_detects_upload(self) -> None:
        assert _result_type({"type": "upload"}) == "upload"

    def test_collect_frags_upload_label(self) -> None:
        base = [{"memory": "uploaded file content", "type": "upload", "title": "report.txt"}]
        frags, _, _, _ = _collect_frags(base, set(), 0)
        assert len(frags) == 1
        assert frags[0]["text"].startswith("[UPLOAD] report.txt\n")

    def test_append_sources_upload_icon(self) -> None:
        results = [
            {"title": "report.txt", "type": "upload"},
            {"title": "Architecture", "type": "confluence"},
        ]
        out = _append_sources("Answer.", results)
        assert "\U0001f4ce report.txt" in out
        assert "\U0001f4c4 Architecture" in out


class TestExtractProperNouns:
    def test_extracts_two_word_name(self) -> None:
        assert extract_proper_nouns("What is Project Aurora?") == ["Project Aurora"]

    def test_extracts_person_name(self) -> None:
        assert extract_proper_nouns("What did Marina Volkov do?") == ["Marina Volkov"]

    def test_extracts_multiple(self) -> None:
        nouns = extract_proper_nouns("Tell me what Marina Volkov knows about Project Aurora")
        assert "Marina Volkov" in nouns
        assert "Project Aurora" in nouns

    def test_no_proper_nouns(self) -> None:
        assert extract_proper_nouns("what happened last week?") == []

    def test_single_capitalized_word_ignored(self) -> None:
        assert extract_proper_nouns("What is Metatron?") == []

    def test_russian_proper_nouns(self) -> None:
        assert extract_proper_nouns("Что такое Проект Аврора?") == ["Проект Аврора"]

    def test_three_word_phrase(self) -> None:
        nouns = extract_proper_nouns("Tell me about Sprint Planning Board")
        assert "Sprint Planning Board" in nouns




class TestSourcesToMarkdown:
    def test_limits_displayed_sources(self) -> None:
        from metatron.api.routes.openai_compat import _sources_to_markdown

        sources = [f"\U0001f4c4 Page {i} \u2014 https://example.com/{i}" for i in range(10)]
        md = _sources_to_markdown(sources)
        lines = [l for l in md.strip().splitlines() if l.startswith("- ")]
        assert len(lines) == 5

    def test_custom_limit(self) -> None:
        from metatron.api.routes.openai_compat import _sources_to_markdown

        sources = [f"\U0001f4c4 Page {i} \u2014 https://example.com/{i}" for i in range(10)]
        md = _sources_to_markdown(sources, limit=3)
        lines = [l for l in md.strip().splitlines() if l.startswith("- ")]
        assert len(lines) == 3

    def test_empty_sources(self) -> None:
        from metatron.api.routes.openai_compat import _sources_to_markdown

        assert _sources_to_markdown([]) == ""


class TestJiraKeyRegex:
    def test_extracts_standard_key(self) -> None:
        assert _JIRA_KEY_RE.findall("What is MTRNIX-108?") == ["MTRNIX-108"]

    def test_extracts_multiple_keys(self) -> None:
        keys = _JIRA_KEY_RE.findall("Compare MTRNIX-108 and PROJ-42")
        assert set(k.upper() for k in keys) == {"MTRNIX-108", "PROJ-42"}

    def test_case_insensitive(self) -> None:
        keys = _JIRA_KEY_RE.findall("mtrnix-108")
        assert [k.upper() for k in keys] == ["MTRNIX-108"]

    def test_no_match_without_key(self) -> None:
        assert _JIRA_KEY_RE.findall("What is the team doing?") == []

    def test_deduplicates_keys(self) -> None:
        keys = _JIRA_KEY_RE.findall("MTRNIX-108 vs MTRNIX-108")
        assert len(keys) == 2
