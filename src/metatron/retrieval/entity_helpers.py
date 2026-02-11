"""Entity resolution helpers - DB-interacting and typed-matching functions."""

from typing import List, Optional, Tuple

import structlog

from metatron.retrieval.entity_resolver import (
    ENABLE_SEMANTIC_MATCHING,
    _is_person_type,
    _tokenize_name,
    find_semantic_match,
    find_typo_match,
)

logger = structlog.get_logger()


def get_all_entities(session, workspace_id: Optional[str] = None) -> list[str]:  # type: ignore[type-arg]
    """Get all entity names from the graph."""
    # TODO: async migration
    if workspace_id:
        result = session.run(
            "MATCH (e:Entity) WHERE e.workspace_id = $workspace_id "
            "RETURN e.name AS name",
            {"workspace_id": workspace_id},
        )
    else:
        result = session.run("MATCH (e:Entity) RETURN e.name AS name")
    return [r["name"] for r in result if r["name"]]


def find_semantic_match_typed(
    name: str,
    existing: list[str],
    threshold: float = 0.88,
    entity_type: Optional[str] = None,
) -> Optional[str]:
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
    existing: List[str],
    entity_type: Optional[str] = None,
    typo_threshold: float = 90,
    semantic_threshold: float = 0.88,
) -> Tuple[str, Optional[str]]:
    """Resolve entity against a pre-fetched list (no DB query).

    Returns (canonical_name, alias_to).
    """
    for e in existing:
        if e.lower() == (name or "").lower():
            return (e, None)

    typo_match = find_typo_match(name, existing, typo_threshold, entity_type=entity_type)
    if typo_match:
        return (typo_match, None)

    try:
        semantic_match = find_semantic_match_typed(
            name, existing, semantic_threshold, entity_type=entity_type,
        )
        if semantic_match:
            if _is_person_type(entity_type):
                return (semantic_match, None)
            return (name, semantic_match)
    except Exception:
        pass

    return (name, None)


def resolve_entity(
    name: str,
    session,  # type: ignore[type-arg]
    workspace_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    typo_threshold: float = 90,
    semantic_threshold: float = 0.88,
) -> Tuple[str, Optional[str]]:
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
            name, existing, semantic_threshold, entity_type=entity_type,
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
    session, entity1: str, entity2: str, workspace_id: Optional[str] = None,  # type: ignore[type-arg]
) -> None:
    """Create a bidirectional ALIAS relationship between entities."""
    # TODO: async migration
    if workspace_id:
        session.run(
            "MATCH (e1:Entity {name: $name1, workspace_id: $workspace_id}) "
            "MATCH (e2:Entity {name: $name2, workspace_id: $workspace_id}) "
            "MERGE (e1)-[:ALIAS]->(e2) "
            "MERGE (e2)-[:ALIAS]->(e1)",
            {"name1": entity1, "name2": entity2, "workspace_id": workspace_id},
        )
    else:
        session.run(
            "MATCH (e1:Entity {name: $name1}) "
            "MATCH (e2:Entity {name: $name2}) "
            "MERGE (e1)-[:ALIAS]->(e2) "
            "MERGE (e2)-[:ALIAS]->(e1)",
            {"name1": entity1, "name2": entity2},
        )
    logger.info("alias_created", entity1=entity1, entity2=entity2, workspace_id=workspace_id)


def link_entities_manually(session, name1: str, name2: str) -> bool:  # type: ignore[type-arg]
    """Manually link two entities as synonyms. Returns True if created."""
    # TODO: async migration
    result = session.run(
        "MATCH (e1:Entity {name: $name1}) "
        "MATCH (e2:Entity {name: $name2}) "
        "RETURN e1.name AS n1, e2.name AS n2",
        {"name1": name1, "name2": name2},
    )
    record = result.single()
    if not record:
        return False
    create_alias(session, name1, name2)
    return True
