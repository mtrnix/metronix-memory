"""Tests for AliasRegistry — auto-generated person name aliases from connector data."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from metatron.agent.router import AgentRouter
from metatron.agent.sessions import SessionManager
from metatron.core.models import Document
from metatron.ingestion.pipeline import _register_persons
from metatron.retrieval.alias_registry import AliasRegistry, reset_alias_registry
from metatron.retrieval.aliases import NAME_ALIASES, seed_custom_aliases


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset module-level singleton before/after each test."""
    reset_alias_registry()
    yield
    reset_alias_registry()


@pytest.fixture
def registry(tmp_path):
    """Create a fresh AliasRegistry in a temp directory."""
    return AliasRegistry(state_dir=str(tmp_path))


class TestRegisterPerson:
    def test_stores_name_parts(self, registry: AliasRegistry) -> None:
        registry.register_person("Kuzmin Konstantin")
        result = registry.resolve("kuzmin")
        assert result == ["Kuzmin Konstantin"]

    def test_stores_email_prefix(self, registry: AliasRegistry) -> None:
        registry.register_person("Kuzmin Konstantin", email="kostya@example.com")
        result = registry.resolve("kostya")
        assert result == ["Kuzmin Konstantin"]

    def test_skips_empty_name(self, registry: AliasRegistry) -> None:
        registry.register_person("")
        registry.register_person("  ")
        assert registry.person_count == 0

    def test_skips_duplicate(self, registry: AliasRegistry) -> None:
        registry.register_person("Kuzmin Konstantin")
        registry.register_person("Kuzmin Konstantin")
        assert registry.person_count == 1


class TestResolve:
    def test_matches_first_name(self, registry: AliasRegistry) -> None:
        registry.register_person("Kuzmin Konstantin")
        assert registry.resolve("konstantin") == ["Kuzmin Konstantin"]

    def test_matches_last_name(self, registry: AliasRegistry) -> None:
        registry.register_person("Kuzmin Konstantin")
        assert registry.resolve("kuzmin") == ["Kuzmin Konstantin"]

    def test_matches_email_prefix(self, registry: AliasRegistry) -> None:
        registry.register_person("Andrew Ermakov", email="andrew.ermakov@org.com")
        assert registry.resolve("andrew.ermakov") == ["Andrew Ermakov"]

    def test_matches_substring_min_3_chars(self, registry: AliasRegistry) -> None:
        registry.register_person("Seliverstov Sergej")
        assert registry.resolve("seliver") == ["Seliverstov Sergej"]
        # 2 chars should NOT match
        assert registry.resolve("se") == []

    def test_custom_alias_takes_priority(self, registry: AliasRegistry) -> None:
        registry.register_person("Evgeny Shcherbinin")
        registry.add_custom_alias("женя", "Evgeny Shcherbinin")
        result = registry.resolve("женя")
        assert result == ["Evgeny Shcherbinin"]

    def test_returns_empty_for_unknown(self, registry: AliasRegistry) -> None:
        registry.register_person("Kuzmin Konstantin")
        assert registry.resolve("unknown_person") == []

    def test_case_insensitive(self, registry: AliasRegistry) -> None:
        registry.register_person("Kuzmin Konstantin")
        assert registry.resolve("KUZMIN") == ["Kuzmin Konstantin"]
        assert registry.resolve("Kuzmin") == ["Kuzmin Konstantin"]

    def test_empty_query_returns_empty(self, registry: AliasRegistry) -> None:
        registry.register_person("Kuzmin Konstantin")
        assert registry.resolve("") == []
        assert registry.resolve("  ") == []


class TestRussianCaseNormalization:
    """Test that Russian case endings are stripped for alias resolution.

    The registry stores English display names from Jira, so Russian aliases
    must be added as custom aliases. Case stripping then resolves inflected
    forms like "вадима" → stem "вадим" → custom alias → "Pozdnyakov Vadim".
    """

    @pytest.fixture(autouse=True)
    def _register_vadim(self, registry: AliasRegistry) -> None:
        registry.register_person("Pozdnyakov Vadim")
        registry.add_custom_alias("вадим", "Pozdnyakov Vadim")

    def test_genitive_vadima(self, registry: AliasRegistry) -> None:
        assert registry.resolve("вадима") == ["Pozdnyakov Vadim"]

    def test_instrumental_vadimom(self, registry: AliasRegistry) -> None:
        assert registry.resolve("вадимом") == ["Pozdnyakov Vadim"]

    def test_dative_vadimu(self, registry: AliasRegistry) -> None:
        assert registry.resolve("вадиму") == ["Pozdnyakov Vadim"]

    def test_prepositional_vadime(self, registry: AliasRegistry) -> None:
        assert registry.resolve("вадиме") == ["Pozdnyakov Vadim"]

    def test_nominative_unchanged(self, registry: AliasRegistry) -> None:
        assert registry.resolve("вадим") == ["Pozdnyakov Vadim"]

    def test_non_russian_unaffected(self, registry: AliasRegistry) -> None:
        assert registry.resolve("vadim") == ["Pozdnyakov Vadim"]
        assert registry.resolve("xyz_unknown") == []


class TestPersistence:
    def test_save_and_reload(self, tmp_path) -> None:
        reg1 = AliasRegistry(state_dir=str(tmp_path))
        reg1.register_person("Kuzmin Konstantin", email="kostya@org.com")
        reg1.add_custom_alias("костя", "Kuzmin Konstantin")

        # Create new instance from same dir — should load persisted data
        reg2 = AliasRegistry(state_dir=str(tmp_path))
        assert reg2.resolve("kuzmin") == ["Kuzmin Konstantin"]
        assert reg2.resolve("костя") == ["Kuzmin Konstantin"]
        assert reg2.resolve("kostya") == ["Kuzmin Konstantin"]
        assert reg2.person_count == 1

    def test_handles_corrupted_file(self, tmp_path) -> None:
        (tmp_path / "person_aliases.json").write_text("not json{{{")
        reg = AliasRegistry(state_dir=str(tmp_path))
        assert reg.person_count == 0
        # Should still work after corruption
        reg.register_person("Test Person")
        assert reg.person_count == 1


class TestSeedCustomAliases:
    def test_seeds_all_hardcoded_aliases(self, registry: AliasRegistry) -> None:
        added = seed_custom_aliases(registry)
        assert added == len(NAME_ALIASES)
        # Spot-check a few
        assert registry.resolve("женя") == ["Evgeny Shcherbinin"]
        assert registry.resolve("костя") == ["Kuzmin Konstantin"]
        assert registry.resolve("вова") == ["Vladimir Belykh"]

    def test_seed_is_idempotent(self, registry: AliasRegistry) -> None:
        seed_custom_aliases(registry)
        seed_custom_aliases(registry)
        # Should still resolve correctly
        assert registry.resolve("женя") == ["Evgeny Shcherbinin"]


class TestFallbackIntegration:
    """Test that search.py falls back to hardcoded aliases when registry is empty."""

    def test_fallback_to_hardcoded(self, registry: AliasRegistry) -> None:
        """Empty registry returns nothing; hardcoded resolve_person_name works."""
        from metatron.retrieval.aliases import resolve_person_name

        # Registry has no data — resolve returns empty
        assert registry.resolve("женя") == []
        # Fallback to hardcoded
        assert resolve_person_name("женя") == ["Evgeny Shcherbinin"]

    def test_registry_overrides_hardcoded(self, registry: AliasRegistry) -> None:
        """When registry has data, it takes priority over hardcoded."""
        # Register a different "Evgeny" person
        registry.register_person("Evgeny Petrov")
        registry.add_custom_alias("женя", "Evgeny Petrov")
        assert registry.resolve("женя") == ["Evgeny Petrov"]


class TestRegisterPersonsFromDocs:
    """Test that _register_persons works for all connector types."""

    def test_jira_doc_registers_assignee_and_reporter(self, tmp_path) -> None:
        reg = AliasRegistry(state_dir=str(tmp_path))
        doc = Document(
            source_type="jira",
            source_id="PROJ-1",
            workspace_id="ws",
            title="[PROJ-1] Task",
            content="body",
            metadata={
                "type": "jira",
                "assignee": "Kuzmin Konstantin",
                "assignee_email": "kostya@org.com",
                "reporter": "Andrew Ermakov",
                "reporter_email": "andrew@org.com",
            },
        )
        with patch("metatron.retrieval.alias_registry.get_alias_registry", return_value=reg):
            _register_persons(doc)
        assert reg.resolve("kuzmin") == ["Kuzmin Konstantin"]
        assert reg.resolve("andrew") == ["Andrew Ermakov"]
        assert reg.resolve("kostya") == ["Kuzmin Konstantin"]

    def test_confluence_doc_registers_author(self, tmp_path) -> None:
        reg = AliasRegistry(state_dir=str(tmp_path))
        doc = Document(
            source_type="confluence",
            source_id="12345",
            workspace_id="ws",
            title="Architecture Guide",
            content="body",
            metadata={
                "type": "confluence",
                "author": "Seliverstov Sergej",
                "author_email": "sergej@org.com",
                "last_modified_by": "Pozdnyakov Vadim",
                "last_modified_by_email": "vadim@org.com",
            },
        )
        with patch("metatron.retrieval.alias_registry.get_alias_registry", return_value=reg):
            _register_persons(doc)
        assert reg.resolve("seliverstov") == ["Seliverstov Sergej"]
        assert reg.resolve("sergej") == ["Seliverstov Sergej"]
        assert reg.resolve("vadim") == ["Pozdnyakov Vadim"]

    def test_mixed_sources_populate_same_registry(self, tmp_path) -> None:
        reg = AliasRegistry(state_dir=str(tmp_path))
        jira_doc = Document(
            source_type="jira",
            source_id="PROJ-1",
            workspace_id="ws",
            title="Task",
            content="body",
            metadata={"type": "jira", "assignee": "Kuzmin Konstantin"},
        )
        confluence_doc = Document(
            source_type="confluence",
            source_id="99",
            workspace_id="ws",
            title="Page",
            content="body",
            metadata={"type": "confluence", "author": "Seliverstov Sergej"},
        )
        with patch("metatron.retrieval.alias_registry.get_alias_registry", return_value=reg):
            _register_persons(jira_doc)
            _register_persons(confluence_doc)
        assert reg.person_count == 2
        assert reg.resolve("kuzmin") == ["Kuzmin Konstantin"]
        assert reg.resolve("seliverstov") == ["Seliverstov Sergej"]

    def test_empty_metadata_fields_are_skipped(self, tmp_path) -> None:
        reg = AliasRegistry(state_dir=str(tmp_path))
        doc = Document(
            source_type="jira",
            source_id="PROJ-2",
            workspace_id="ws",
            title="Unassigned",
            content="body",
            metadata={"type": "jira", "assignee": "", "reporter": ""},
        )
        with patch("metatron.retrieval.alias_registry.get_alias_registry", return_value=reg):
            _register_persons(doc)
        assert reg.person_count == 0


# ---------------------------------------------------------------------------
# Helpers for Qdrant mock
# ---------------------------------------------------------------------------


@dataclass
class _FakePoint:
    """Mimics qdrant_client Record returned by scroll()."""

    payload: dict


def _make_mock_store(points: list[dict]) -> MagicMock:
    """Build a mock QdrantVectorStore whose client.scroll yields given points."""
    store = MagicMock()
    store.collection_name = "test_collection"
    fake_points = [_FakePoint(payload=p) for p in points]
    # First call returns all points + offset=None (single page)
    store.client.scroll.return_value = (fake_points, None)
    return store


class TestPopulateFromQdrant:
    def test_registers_persons_from_points(self, tmp_path) -> None:
        reg = AliasRegistry(state_dir=str(tmp_path))
        store = _make_mock_store(
            [
                {
                    "assignee": "Kuzmin Konstantin",
                    "assignee_email": "kostya@org.com",
                    "reporter": "Andrew Ermakov",
                },
                {"assignee": "Kuzmin Konstantin"},  # duplicate — should be skipped
                {"author": "Seliverstov Sergej", "author_email": "sergej@org.com"},
            ]
        )
        added = reg.populate_from_qdrant(store)
        assert added == 3
        assert reg.resolve("kuzmin") == ["Kuzmin Konstantin"]
        assert reg.resolve("andrew") == ["Andrew Ermakov"]
        assert reg.resolve("sergej") == ["Seliverstov Sergej"]

    def test_skips_empty_payloads(self, tmp_path) -> None:
        reg = AliasRegistry(state_dir=str(tmp_path))
        store = _make_mock_store(
            [
                {"assignee": "", "reporter": ""},
                {"type": "confluence"},  # no person fields
                {},
            ]
        )
        added = reg.populate_from_qdrant(store)
        assert added == 0

    def test_paginates_through_multiple_pages(self, tmp_path) -> None:
        reg = AliasRegistry(state_dir=str(tmp_path))
        store = MagicMock()
        store.collection_name = "test"

        page1 = [_FakePoint(payload={"assignee": "Person One"})]
        page2 = [_FakePoint(payload={"assignee": "Person Two"})]

        # First call: returns page1 + offset for next page
        # Second call: returns page2 + None (end)
        store.client.scroll.side_effect = [
            (page1, "next_offset"),
            (page2, None),
        ]
        added = reg.populate_from_qdrant(store)
        assert added == 2
        assert store.client.scroll.call_count == 2

    def test_returns_zero_for_empty_collection(self, tmp_path) -> None:
        reg = AliasRegistry(state_dir=str(tmp_path))
        store = _make_mock_store([])
        added = reg.populate_from_qdrant(store)
        assert added == 0
        assert reg.person_count == 0


class TestRebuildAliasesCommand:
    @pytest.fixture
    def router(self, tmp_path):
        SessionManager.reset_instance()
        s = MagicMock()
        s.default_workspace_id = "TEST_WS"
        s.llm_provider = "deepseek"
        s.llm_fallback_provider = ""
        r = AgentRouter(settings=s, sessions=SessionManager())
        yield r
        SessionManager.reset_instance()

    @patch("metatron.storage.qdrant.get_hybrid_store")
    @patch("metatron.retrieval.alias_registry.get_alias_registry")
    def test_rebuild_aliases_reports_count(
        self,
        mock_get_registry: MagicMock,
        mock_get_store: MagicMock,
        router: AgentRouter,
        tmp_path,
    ) -> None:
        reg = AliasRegistry(state_dir=str(tmp_path))
        mock_get_registry.return_value = reg
        mock_get_store.return_value = _make_mock_store(
            [
                {"assignee": "Alice Smith"},
                {"reporter": "Bob Jones"},
            ]
        )
        result = router.route("/rebuild-aliases", user_id="u1")
        assert "2 new persons found" in result
        assert "total" in result

    @patch("metatron.storage.qdrant.get_hybrid_store")
    @patch("metatron.retrieval.alias_registry.get_alias_registry")
    def test_rebuild_aliases_qdrant_error(
        self,
        mock_get_registry: MagicMock,
        mock_get_store: MagicMock,
        router: AgentRouter,
        tmp_path,
    ) -> None:
        mock_get_registry.return_value = AliasRegistry(state_dir=str(tmp_path))
        mock_get_store.side_effect = RuntimeError("Qdrant down")
        result = router.route("/rebuild-aliases", user_id="u1")
        assert "Failed to scan Qdrant" in result

    def test_help_includes_rebuild_aliases(self, router: AgentRouter) -> None:
        result = router.route("/help", user_id="u1")
        assert "/rebuild-aliases" in result
