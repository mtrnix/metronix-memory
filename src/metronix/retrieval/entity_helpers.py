"""Entity resolution helpers - DB-interacting and typed-matching functions."""

import contextlib

import structlog

from metronix.retrieval.entity_resolver import (
    ENABLE_SEMANTIC_MATCHING,
    _is_person_type,
    _tokenize_name,
    find_semantic_match,
    find_typo_match,
)

logger = structlog.get_logger()


def get_all_entities(session, workspace_id: str | None = None) -> list[str]:  # type: ignore[type-arg]
    """Get all entity names from the graph."""
    if workspace_id:
        result = session.run(
            "MATCH (e:Entity) WHERE e.workspace_id = $ws RETURN e.name",
            {"ws": workspace_id},
        )
    else:
        result = session.run("MATCH (e:Entity) RETURN e.name")
    return [r[0] for r in result if r[0]]


def find_semantic_match_typed(
    name: str,
    existing: list[str],
    threshold: float = 0.88,
    entity_type: str | None = None,
) -> str | None:
    """Typed wrapper that reduces candidate set before semantic matching."""
    if not ENABLE_SEMANTIC_MATCHING or not existing:
        return None

    candidates = existing
    if _is_person_type(entity_type):
        tokens = _tokenize_name(name)
        if len(tokens) >= 2:
            surname = tokens[-1]
            filtered = [e for e in existing if surname in _tokenize_name(e)]
            if filtered:
                candidates = filtered
        elif len(tokens) == 1:
            first = tokens[0]
            filtered = [e for e in existing if first in _tokenize_name(e)]
            if filtered:
                candidates = filtered

    if len(candidates) > 50:
        logger.debug("semantic_match_typed_skipped", name=name, count=len(candidates))
        return None

    return find_semantic_match(name, candidates, threshold)


def resolve_entity_with_existing(
    name: str,
    existing: list[str],
    entity_type: str | None = None,
    typo_threshold: float = 90,
    semantic_threshold: float = 0.88,
) -> tuple[str, str | None]:
    """Resolve entity against a pre-fetched list (no DB query).

    Returns (canonical_name, alias_to).
    """
    for e in existing:
        if e.lower() == (name or "").lower():
            return (e, None)

    typo_match = find_typo_match(name, existing, typo_threshold, entity_type=entity_type)
    if typo_match:
        return (typo_match, None)

    with contextlib.suppress(Exception):
        semantic_match = find_semantic_match_typed(
            name,
            existing,
            semantic_threshold,
            entity_type=entity_type,
        )
        if semantic_match:
            if _is_person_type(entity_type):
                return (semantic_match, None)
            return (name, semantic_match)

    return (name, None)


def resolve_entity(
    name: str,
    session,  # type: ignore[type-arg]
    workspace_id: str | None = None,
    entity_type: str | None = None,
    typo_threshold: float = 90,
    semantic_threshold: float = 0.88,
) -> tuple[str, str | None]:
    """Resolve an entity: check for typos and synonyms.

    Returns (canonical_name, alias_to). Resolution order:
    1. Exact match -> (name, None)
    2. Typo (>90%) -> (existing_name, None)
    3. Synonym (>0.88) -> (name, existing_name)
    4. New entity -> (name, None)
    """
    # TODO: async migration
    existing = get_all_entities(session, workspace_id)

    for e in existing:
        if e.lower() == name.lower():
            return (e, None)

    typo_match = find_typo_match(name, existing, typo_threshold, entity_type=entity_type)
    if typo_match:
        logger.info("entity_typo_resolved", name=name, match=typo_match)
        return (typo_match, None)

    logger.debug("checking_semantic_match", name=name)
    try:
        semantic_match = find_semantic_match_typed(
            name,
            existing,
            semantic_threshold,
            entity_type=entity_type,
        )
        if semantic_match:
            if _is_person_type(entity_type):
                logger.info("person_semantic_resolved", name=name, match=semantic_match)
                return (semantic_match, None)
            logger.info("entity_synonym_found", name=name, match=semantic_match)
            return (name, semantic_match)
    except Exception as e:
        logger.warning("semantic_match_failed", name=name, error=str(e))

    return (name, None)


def create_alias(
    session,
    entity1: str,
    entity2: str,
    workspace_id: str | None = None,  # type: ignore[type-arg]
) -> None:
    """Create a bidirectional ALIAS relationship between entities."""
    if workspace_id:
        session.run(
            "MATCH (e1:Entity {name: $e1, workspace_id: $ws}) "
            "MATCH (e2:Entity {name: $e2, workspace_id: $ws}) "
            "MERGE (e1)-[:ALIAS]->(e2) "
            "MERGE (e2)-[:ALIAS]->(e1)",
            {"e1": entity1, "e2": entity2, "ws": workspace_id},
        )
    else:
        session.run(
            "MATCH (e1:Entity {name: $e1}) "
            "MATCH (e2:Entity {name: $e2}) "
            "MERGE (e1)-[:ALIAS]->(e2) "
            "MERGE (e2)-[:ALIAS]->(e1)",
            {"e1": entity1, "e2": entity2},
        )
    logger.info("alias_created", entity1=entity1, entity2=entity2, workspace_id=workspace_id)


def link_entities_manually(session, name1: str, name2: str) -> bool:  # type: ignore[type-arg]
    """Manually link two entities as synonyms. Returns True if created."""
    result = session.run(
        "MATCH (e1:Entity {name: $n1}) MATCH (e2:Entity {name: $n2}) RETURN e1.name, e2.name",
        {"n1": name1, "n2": name2},
    )
    record = result.single()
    if not record:
        return False
    create_alias(session, name1, name2)
    return True
