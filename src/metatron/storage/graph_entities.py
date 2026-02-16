"""Entity type normalization and name validation for knowledge graph.

Ensures consistent entity types and filters out garbage entity names
before writing to Memgraph.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

ALLOWED_ENTITY_TYPES: list[str] = [
    "Person",
    "Organization",
    "Project",
    "Task",
    "Technology",
    "Document",
    "Concept",
    "Service",
    "Event",
    "Location",
]

_ALLOWED_LOWER: set[str] = {t.lower() for t in ALLOWED_ENTITY_TYPES}

TYPE_ALIASES: dict[str, str] = {
    # Technology
    "tool": "Technology", "software": "Technology", "framework": "Technology",
    "library": "Technology", "database": "Technology", "language": "Technology",
    "tool/software": "Technology", "tool/system": "Technology",
    "tool/framework": "Technology", "tool/technology": "Technology",
    "tool/platform": "Technology", "library/tool": "Technology",
    "programming language": "Technology", "ai model": "Technology",
    "model": "Technology", "embedding model": "Technology",
    "language model": "Technology", "llm model": "Technology",
    "model type": "Technology", "model/technology": "Technology",
    "model/service": "Technology", "graph database": "Technology",
    "softwarecomponent": "Technology", "software/plugin": "Technology",
    "software/server": "Technology", "software type": "Technology",
    "software platform": "Technology", "software/platform": "Technology",
    "software/interface": "Technology", "algorithm": "Technology",
    "protocol": "Technology", "data format": "Technology",
    "file format": "Technology", "fileformat": "Technology",
    "documentformat": "Technology", "format": "Technology",
    "data type": "Technology", "datastructure": "Technology",
    "data structure": "Technology", "hardware": "Technology",
    "инструмент": "Technology", "библиотека": "Technology",
    "технология": "Technology",
    # Task
    "task/issue": "Task", "task/process": "Task", "workitem": "Task",
    "jira issue": "Task", "jiraissue": "Task", "jira_task": "Task",
    "work item": "Task", "issue": "Task", "task id": "Task",
    "issue id": "Task", "issue key": "Task", "issue/key": "Task",
    "issue_type": "Task", "bug": "Task", "story": "Task",
    "task/issue identifier": "Task", "task/description": "Task",
    "taskdescription": "Task", "tasktitle": "Task",
    "deployment task": "Task", "задача": "Task",
    "тип задачи": "Task", "описание задачи": "Task",
    # Project
    "epic": "Project", "initiative": "Project", "project/task": "Project",
    "project/feature": "Project", "project/initiative": "Project",
    "project/system": "Project", "project/topic": "Project",
    "проект": "Project", "эпик": "Project",
    # Person
    "user": "Person", "developer": "Person", "engineer": "Person",
    "assignee": "Person", "github user": "Person",
    "пользователь": "Person", "разработчик": "Person",
    "сотрудник": "Person", "участник": "Person",
    # Organization
    "team": "Organization", "company": "Organization",
    "department": "Organization", "user group": "Organization",
    "organization/service": "Organization",
    "organization/project": "Organization",
    # Event
    "meeting": "Event", "release": "Event", "deadline": "Event",
    "milestone": "Event", "событие": "Event",
    # Service
    "api": "Service", "system": "Service", "platform": "Service",
    "microservice": "Service", "service/endpoint": "Service",
    "system/application": "Service", "system/project": "Service",
    "system/process": "Service", "systemcomponent": "Service",
    "system_component": "Service", "система": "Service",
    "компонент": "Service", "component": "Service",
    "архитектурный компонент": "Service",
    "architecturecomponent": "Service",
    "technical component": "Service", "infrastructure": "Service",
    "модуль": "Service", "module": "Service",
    # Document
    "spec": "Document", "report": "Document", "rfc": "Document",
    "documentation": "Document", "documentation/resource": "Document",
    "notebook": "Document", "attachment": "Document",
    "artifact": "Document", "артефакт": "Document",
    "development artifact": "Document", "developmentartifact": "Document",
    "file": "Document", "файл": "Document",
    "repository": "Document", "branch": "Document",
    "repository branch": "Document",
    # Concept
    "idea": "Concept", "pattern": "Concept", "methodology": "Concept",
    "technique": "Concept", "strategy": "Concept",
    "process": "Concept", "process/technique": "Concept",
    "process/phase": "Concept", "process phase": "Concept",
    "development approach": "Concept", "development phase": "Concept",
    "research topic": "Concept", "research area": "Concept",
    "research paper": "Concept", "research objective": "Concept",
    "research scope": "Concept", "research/development": "Concept",
    "topic": "Concept", "domain": "Concept",
    "capability": "Concept", "functionality": "Concept",
    "функциональность": "Concept", "feature": "Concept",
    "use case": "Concept", "usecase": "Concept",
    "goal": "Concept", "goal/requirement": "Concept",
    "design": "Concept", "architecture": "Concept",
    "role": "Concept", "роль": "Concept",
    "status": "Concept", "статус": "Concept",
    "priority": "Concept", "label": "Concept", "метка": "Concept",
    # Location
    "environment": "Location", "region": "Location",
    "deployment": "Location",
}


def normalize_entity_type(raw_type: str) -> str:
    """Normalize a freeform entity type to the fixed taxonomy.

    Returns one of ALLOWED_ENTITY_TYPES, falling back to "Concept"
    for unrecognized types.
    """
    if not raw_type:
        return "Concept"
    normalized = raw_type.lower().strip()
    if normalized in TYPE_ALIASES:
        return TYPE_ALIASES[normalized]
    if normalized in _ALLOWED_LOWER:
        for allowed in ALLOWED_ENTITY_TYPES:
            if normalized == allowed.lower():
                return allowed
    return "Concept"


def is_valid_entity_name(name: str) -> bool:
    """Check if an entity name is valid for the knowledge graph.

    Filters out URLs, file paths, code identifiers, and names that are
    too short or too long to be meaningful entities.
    """
    if not name or not name.strip():
        return False
    name = name.strip()
    if len(name) < 2:
        return False
    if len(name) > 80:
        return False
    if name.startswith(("http://", "https://", "/")):
        return False
    if "/" in name and len(name) > 30:
        return False
    if name.count("_") > 3:
        return False
    return True
