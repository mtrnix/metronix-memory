"""Tests for person name alias resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from metatron.retrieval.aliases import NAME_ALIASES, resolve_person_name


class TestResolvePersonName:
    def test_russian_nickname_resolves(self) -> None:
        result = resolve_person_name("Женя")
        assert result == ["Evgeny Shcherbinin"]

    def test_case_insensitive(self) -> None:
        assert resolve_person_name("женя") == ["Evgeny Shcherbinin"]
        assert resolve_person_name("ЖЕНЯ") == ["Evgeny Shcherbinin"]

    def test_english_first_name_resolves(self) -> None:
        result = resolve_person_name("evgeny")
        assert result == ["Evgeny Shcherbinin"]

    def test_surname_resolves(self) -> None:
        result = resolve_person_name("shcherbinin")
        assert result == ["Evgeny Shcherbinin"]

    def test_unknown_name_returns_capitalized(self) -> None:
        result = resolve_person_name("unknown_person")
        assert result == ["Unknown_person"]

    def test_whitespace_stripped(self) -> None:
        result = resolve_person_name("  женя  ")
        assert result == ["Evgeny Shcherbinin"]

    def test_multiple_team_members(self) -> None:
        """Each alias resolves to the correct person."""
        assert resolve_person_name("сергей")[0] == "Seliverstov Sergej"
        assert resolve_person_name("костя")[0] == "Kuzmin Konstantin"
        assert resolve_person_name("вадим")[0] == "Pozdnyakov Vadim"
        assert resolve_person_name("андрей")[0] == "Andrew Ermakov"

    def test_aliases_dict_all_lowercase_keys(self) -> None:
        """All keys in NAME_ALIASES should be lowercase."""
        for key in NAME_ALIASES:
            assert key == key.lower(), f"Key '{key}' is not lowercase"


class TestAliasIntegration:
    @patch("metatron.retrieval.search.get_hybrid_store")
    @patch("metatron.retrieval.search.expand_query", side_effect=lambda q: q)
    @patch("metatron.retrieval.search.search_with_date_filter", return_value=[])
    @patch("metatron.retrieval.search.get_graph_entities", return_value=[])
    @patch("metatron.retrieval.search.chat_completion", return_value="Answer about Evgeny")
    def test_russian_nickname_triggers_assignee_search(
        self, mock_llm, mock_gents, mock_sdf, mock_expand, mock_store
    ) -> None:
        """'Что делает Женя?' should search by assignee 'Evgeny Shcherbinin'."""
        store_instance = MagicMock()
        store_instance.search_by_status.return_value = []
        store_instance.search_by_assignee.return_value = [
            {"memory": "Task X", "data": "Task X", "title": "MTRNIX-10",
             "type": "jira", "score": 1.0, "payload": {}}
        ]
        mock_store.return_value = store_instance

        from metatron.retrieval.search import hybrid_search_and_answer
        hybrid_search_and_answer(
            query="Что делает Женя?", intent_query="Что делает Женя?"
        )

        # Should have called search_by_assignee with the resolved name
        calls = store_instance.search_by_assignee.call_args_list
        searched_names = [c.args[0] if c.args else c.kwargs.get("assignee") for c in calls]
        assert "Evgeny Shcherbinin" in searched_names
