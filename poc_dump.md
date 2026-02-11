### ./config.py
```python
"""
Централизованная конфигурация для всех сервисов Metatron.

Переменные окружения (опционально):
  METATRON_HOST      - основной хост (default: metattron.ximi.group)
  RABBITMQ_HOST      - хост RabbitMQ (default: METATRON_HOST)
  MEMGRAPH_HOST      - хост Memgraph (default: METATRON_HOST)
  QDRANT_HOST        - хост Qdrant (default: METATRON_HOST)
  OLLAMA_HOST        - хост Ollama (default: METATRON_HOST)

Для локальной разработки:
  export METATRON_HOST=localhost
  
Или для отдельных сервисов:
  export RABBITMQ_HOST=localhost
  export MEMGRAPH_HOST=localhost
"""
import os

# Автозагрузка .env если есть python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv не установлен, используем только os.environ

# =============================================================================
# CENTRAL CONFIG (с поддержкой env vars)
# =============================================================================

# Основной хост (production по умолчанию)
METATRON_HOST = os.getenv("METATRON_HOST", "metattron.ximi.group")

# RabbitMQ
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", METATRON_HOST)
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "metatron")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "metatron")

# Memgraph
MEMGRAPH_HOST = os.getenv("MEMGRAPH_HOST", METATRON_HOST)
MEMGRAPH_PORT = int(os.getenv("MEMGRAPH_PORT", "7687"))
MEMGRAPH_URI = f"bolt://{MEMGRAPH_HOST}:{MEMGRAPH_PORT}"
MEMGRAPH_USER = os.getenv("MEMGRAPH_USER", "user")
MEMGRAPH_PASS = os.getenv("MEMGRAPH_PASS", "pass")

# Ollama (embeddings)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", METATRON_HOST)
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_URL = f"{OLLAMA_HOST}:{OLLAMA_PORT}"

# Qdrant (vector store)
QDRANT_HOST = os.getenv("QDRANT_HOST", METATRON_HOST)
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

# Queues
CONFLUENCE_QUEUE = os.getenv("CONFLUENCE_QUEUE", "confluence_pages")
JIRA_QUEUE = os.getenv("JIRA_QUEUE", "jira_issues")

```

### ./entity_resolver.py
```python
"""
Entity Resolver - модуль для разрешения синонимов сущностей.

Использует:
- rapidfuzz для обнаружения опечаток (> 90% совпадение)
- Ollama embeddings для семантического сходства (> 0.88)

Env variables:
- ENABLE_SEMANTIC_MATCHING=true/false - включить/выключить семантический поиск (default: true)
"""

import os
import math
import re
import logging
from typing import Optional, Tuple, List

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Семантический поиск включен по умолчанию (использует Ollama, который уже запущен)
ENABLE_SEMANTIC_MATCHING = os.getenv("ENABLE_SEMANTIC_MATCHING", "true").lower() == "true"

# Минимальная карта никнеймов (можно расширять под вашу доменную область)
_NICKNAME_MAP = {
    # EN
    "kostya": "konstantin",
    # RU
    "костя": "константин",
}


def _is_person_type(entity_type: Optional[str]) -> bool:
    return (entity_type or "").strip().lower() in {"person", "human", "employee", "user"}


def _tokenize_name(name: str) -> List[str]:
    """
    Tokenize a name into normalized tokens.
    - Keeps words from parentheses as tokens ("Konstantin (Kostya)" -> ["konstantin","kostya"])
    - Removes punctuation
    - Applies a small nickname map
    """
    s = (name or "").strip().lower()
    if not s:
        return []

    # Keep alnum/space/hyphen/parentheses, drop other punctuation
    s = re.sub(r"[^\w\s()\-]", " ", s, flags=re.UNICODE)
    # Convert parentheses to spaces (keep contents)
    s = s.replace("(", " ").replace(")", " ")
    s = " ".join(s.split())

    tokens = [t for t in re.split(r"[\s\-]+", s) if t]
    tokens = [_NICKNAME_MAP.get(t, t) for t in tokens]
    return tokens


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)


def get_all_entities(session, workspace_id: Optional[str] = None) -> list[str]:
    """
    Получает список всех имён сущностей из графа.

    Args:
        session: Neo4j session
        workspace_id: Optional workspace filter. If None, returns all entities.

    Returns:
        List of entity names
    """
    if workspace_id:
        result = session.run(
            "MATCH (e:Entity) WHERE e.workspace_id = $workspace_id RETURN e.name AS name",
            {"workspace_id": workspace_id}
        )
    else:
        result = session.run("MATCH (e:Entity) RETURN e.name AS name")
    return [r["name"] for r in result if r["name"]]


def _normalize_entity_name(name: str) -> str:
    """
    Normalize entity names for robust matching:
    - Normalize punctuation/whitespace
    - Lowercase
    - Apply nickname normalization (e.g. Kostya -> Konstantin)

    IMPORTANT: we keep words from parentheses as tokens to help matching,
    but the final normalized string is token-based.
    """
    return " ".join(_tokenize_name(name))


def find_typo_match(
    name: str,
    existing: list[str],
    threshold: float = 90,
    entity_type: Optional[str] = None,
) -> Optional[str]:
    """
    Ищет опечатку через rapidfuzz.
    Возвращает имя существующей сущности если совпадение > threshold.
    """
    if not existing:
        return None

    # Person heuristic: avoid risky merges for single-token names (only first name).
    # If it maps uniquely to exactly one existing full name in the workspace — merge to it.
    if _is_person_type(entity_type):
        in_tokens = _tokenize_name(name)
        if len(in_tokens) == 1:
            t = in_tokens[0]
            candidates = []
            for ex in existing:
                ex_tokens = _tokenize_name(ex)
                if t in ex_tokens and len(ex_tokens) >= 2:
                    candidates.append(ex)
            if len(candidates) == 1:
                logger.debug(f"Person short-name unique match: '{name}' → '{candidates[0]}'")
                return candidates[0]
            return None

    best_match = None
    best_score = 0
    norm_name = _normalize_entity_name(name)

    for existing_name in existing:
        norm_existing = _normalize_entity_name(existing_name)
        if not norm_existing or not norm_name:
            continue
        # token_* handles word reordering: "Kuzmin Konstantin" vs "Konstantin Kuzmin"
        score = max(
            fuzz.ratio(norm_name, norm_existing),
            fuzz.token_sort_ratio(norm_name, norm_existing),
            fuzz.token_set_ratio(norm_name, norm_existing),
        )
        if score > best_score:
            best_score = score
            best_match = existing_name

    if best_score >= threshold:
        logger.debug(f"Typo match: '{name}' → '{best_match}' (score: {best_score})")
        return best_match

    return None


def find_semantic_match(name: str, existing: list[str], threshold: float = 0.88) -> Optional[str]:
    """
    Ищет семантически похожую сущность через Ollama embeddings.
    Возвращает имя если cosine similarity > threshold.

    Uses the same Ollama model as document embeddings (nomic-embed-text).
    """
    if not ENABLE_SEMANTIC_MATCHING:
        return None

    if not existing:
        return None

    # Skip semantic matching if too many candidates (performance)
    if len(existing) > 50:
        logger.debug(f"Skipping semantic match for '{name}': too many candidates ({len(existing)})")
        return None

    try:
        from metatron.utils import get_cached_embedding

        logger.debug(f"Getting embedding for '{name}'...")
        # Get embedding for the new entity name
        name_emb = get_cached_embedding(name)
        logger.debug(f"Got embedding for '{name}', comparing with {len(existing)} existing...")

        best_match = None
        best_score = 0.0

        # Compare with each existing entity
        for existing_name in existing:
            existing_emb = get_cached_embedding(existing_name)
            score = cosine_similarity(name_emb, existing_emb)

            if score > best_score:
                best_score = score
                best_match = existing_name

        if best_score >= threshold:
            logger.debug(f"Semantic match: '{name}' → '{best_match}' (score: {best_score:.3f})")
            return best_match

    except Exception as e:
        logger.warning(f"Semantic matching error for '{name}': {e}")
        return None

    return None


def resolve_entity(
    name: str,
    session,
    workspace_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    typo_threshold: float = 90,
    semantic_threshold: float = 0.88
) -> Tuple[str, Optional[str]]:
    """
    Разрешает сущность: проверяет на опечатки и синонимы.

    Args:
        name: Entity name to resolve
        session: Neo4j session
        workspace_id: Optional workspace filter. If None, searches across all workspaces.
        typo_threshold: Threshold for typo matching (0-100)
        semantic_threshold: Threshold for semantic similarity (0-1)

    Returns:
        Tuple[canonical_name, alias_to]:
        - canonical_name: имя для использования (существующее или новое)
        - alias_to: если не None, нужно создать ALIAS связь к этой сущности

    Логика:
    1. Точное совпадение → (name, None)
    2. Опечатка (rapidfuzz > 90%) → (existing_name, None) - используем существующее
    3. Синоним (semantic > 0.88) → (name, existing_name) - создаём новую + ALIAS
    4. Новая сущность → (name, None)
    """
    existing = get_all_entities(session, workspace_id)

    # 1. Точное совпадение (case-insensitive)
    for e in existing:
        if e.lower() == name.lower():
            return (e, None)

    # 2. Опечатка
    typo_match = find_typo_match(name, existing, typo_threshold, entity_type=entity_type)
    if typo_match:
        logger.info(f"Entity '{name}' resolved as typo of '{typo_match}'")
        return (typo_match, None)

    # 3. Семантическое сходство (skip if disabled or problematic)
    logger.debug(f"resolve_entity: checking semantic match for '{name}'...")
    try:
        semantic_match = find_semantic_match_typed(
            name,
            existing,
            semantic_threshold,
            entity_type=entity_type,
        )
        if semantic_match:
            # For people, prefer true dedup (use existing canonical) rather than creating a new alias node.
            if _is_person_type(entity_type):
                logger.info(f"Person '{name}' resolved semantically to '{semantic_match}'")
                return (semantic_match, None)
            logger.info(f"Entity '{name}' is synonym of '{semantic_match}' - creating ALIAS")
            return (name, semantic_match)
    except Exception as e:
        logger.warning(f"Semantic matching failed for '{name}': {e}")

    # 4. Новая сущность
    return (name, None)


def create_alias(session, entity1: str, entity2: str, workspace_id: Optional[str] = None) -> None:
    """
    Создаёт двустороннюю связь ALIAS между сущностями.

    Args:
        session: Neo4j session
        entity1: First entity name
        entity2: Second entity name
        workspace_id: Optional workspace filter. If provided, ensures entities belong to workspace.
    """
    if workspace_id:
        session.run(
            """
            MATCH (e1:Entity {name: $name1, workspace_id: $workspace_id})
            MATCH (e2:Entity {name: $name2, workspace_id: $workspace_id})
            MERGE (e1)-[:ALIAS]->(e2)
            MERGE (e2)-[:ALIAS]->(e1)
            """,
            {"name1": entity1, "name2": entity2, "workspace_id": workspace_id}
        )
    else:
        session.run(
            """
            MATCH (e1:Entity {name: $name1})
            MATCH (e2:Entity {name: $name2})
            MERGE (e1)-[:ALIAS]->(e2)
            MERGE (e2)-[:ALIAS]->(e1)
            """,
            {"name1": entity1, "name2": entity2}
        )
    logger.info(f"Created ALIAS: '{entity1}' ↔ '{entity2}'" + (f" (workspace: {workspace_id})" if workspace_id else ""))


def find_semantic_match_typed(
    name: str,
    existing: list[str],
    threshold: float = 0.88,
    entity_type: Optional[str] = None,
) -> Optional[str]:
    """
    Typed wrapper around find_semantic_match() that can reduce candidate set.
    This keeps the original function signature stable for older call sites.
    """
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

    # Hard cap to avoid N^2 embedding calls
    if len(candidates) > 50:
        logger.debug(f"Skipping semantic match for '{name}': too many candidates ({len(candidates)})")
        return None

    return find_semantic_match(name, candidates, threshold)


def resolve_entity_with_existing(
    name: str,
    existing: List[str],
    entity_type: Optional[str] = None,
    typo_threshold: float = 90,
    semantic_threshold: float = 0.88,
) -> Tuple[str, Optional[str]]:
    """
    Resolve entity against a pre-fetched list of existing entity names (no DB query).

    Returns (canonical_name, alias_to).
    """
    for e in existing:
        if e.lower() == (name or "").lower():
            return (e, None)

    typo_match = find_typo_match(name, existing, typo_threshold, entity_type=entity_type)
    if typo_match:
        return (typo_match, None)

    try:
        semantic_match = find_semantic_match_typed(name, existing, semantic_threshold, entity_type=entity_type)
        if semantic_match:
            if _is_person_type(entity_type):
                return (semantic_match, None)
            return (name, semantic_match)
    except Exception:
        pass

    return (name, None)


def link_entities_manually(session, name1: str, name2: str) -> bool:
    """
    Ручное связывание двух сущностей как синонимов.
    Возвращает True если связь создана.
    """
    # Проверяем что обе сущности существуют
    result = session.run(
        """
        MATCH (e1:Entity {name: $name1})
        MATCH (e2:Entity {name: $name2})
        RETURN e1.name AS n1, e2.name AS n2
        """,
        {"name1": name1, "name2": name2}
    )

    record = result.single()
    if not record:
        return False

    create_alias(session, name1, name2)
    return True
```

### ./get_data_from_rabbitmq.py
```python
#!/usr/bin/env python3
"""
Полный рабочий пример потребителя RabbitMQ на Python с pika.
Поддерживает аутентификацию, обработку ошибок, graceful shutdown.
"""

import pika
import sys
import time
import json
import signal
import threading
from typing import Callable, Optional, Union
from ftfy import fix_text
from dataclasses import dataclass, field
from html import unescape
from markdownify import markdownify as html_to_md

from config import (
    RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS,
    CONFLUENCE_QUEUE, JIRA_QUEUE
)


@dataclass
class RabbitMQConfig:
    """Конфигурация подключения к RabbitMQ"""
    host: str = field(default_factory=lambda: RABBITMQ_HOST)
    port: int = field(default_factory=lambda: RABBITMQ_PORT)
    username: str = field(default_factory=lambda: RABBITMQ_USER)
    password: str = field(default_factory=lambda: RABBITMQ_PASS)
    virtual_host: str = '/'
    queue_name: str = 'test_queue'
    durable: bool = True
    prefetch_count: int = 1
    reconnect_delay: int = 5


class RabbitMQConsumer:
    """Класс потребителя сообщений RabbitMQ с автоматическим переподключением"""

    def __init__(self, config: RabbitMQConfig, message_handler: Optional[Callable] = None):
        self.config = config
        self.connection = None
        self.channel = None
        self._stopping = False
        self._thread = None

        # Обработчик сообщений по умолчанию
        self.message_handler = message_handler or self._default_handler

    def _default_handler(self, ch, method, properties, body):
        """Обработчик сообщений по умолчанию"""
        try:
            message = body.decode('utf-8')
            print(f"📥 Получено сообщение [{method.routing_key}] (delivery_tag={method.delivery_tag}):")
            print(f"   {message}")

            # Подтверждаем получение
            ch.basic_ack(delivery_tag=method.delivery_tag)
            print("   ✅ Сообщение обработано\n")

        except Exception as e:
            print(f"   ❌ Ошибка обработки: {e}")
            # Отклоняем сообщение с возвратом в очередь
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    def connect(self) -> bool:
        try:
            credentials = pika.PlainCredentials(
                username=self.config.username,
                password=self.config.password
            )

            parameters = pika.ConnectionParameters(
                host=self.config.host,
                port=self.config.port,
                virtual_host=self.config.virtual_host,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300,
            )

            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()

            # fair dispatch
            self.channel.basic_qos(prefetch_count=self.config.prefetch_count)

            # декларация очереди строго под твоё описание
            self.channel.queue_declare(
                queue=self.config.queue_name,
                durable=True,
                arguments={
                    "x-queue-type": "classic",  # совпадает с UI
                },
            )

            print(f"✅ Подключено к {self.config.host}:{self.config.port}")
            print(f"   Очередь: {self.config.queue_name} (classic, durable)")
            return True

        except Exception as e:
            print(f"❌ Ошибка подключения/объявления очереди: {e}")
            return False

    def start_consuming(self):
        """Запуск потребления сообщений"""
        queue_name = self.config.queue_name

        def callback(ch, method, properties, body):
            try:
                if queue_name == JIRA_QUEUE:
                    jira_data = process_jira_message(body)
                    md = jira_to_markdown(jira_data)
                    print(f"📋 Jira Issue: {jira_data['key']}")
                else:
                    # Confluence и прочие HTML-based
                    md = process_rabbitmq_message(body)
                    print(f"📄 Confluence Page")
                
                print(md)
                print("-" * 50)
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                print(f"❌ Ошибка обработки: {e}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        self.channel.basic_consume(
            queue=queue_name,
            on_message_callback=callback
        )

        print(f"🚀 Ожидание сообщений в очереди '{queue_name}'...")
        print("   Нажмите Ctrl+C для остановки\n")

        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """Graceful остановка"""
        print("\n🛑 Остановка потребителя...")
        self._stopping = True

        if self.channel:
            self.channel.stop_consuming()
            self.channel.close()

        if self.connection and not self.connection.is_closed:
            self.connection.close()

        print("✅ Потребитель остановлен")

    def run(self):
        """Основной цикл с автоматическим переподключением"""
        while not self._stopping:
            if not self.connect():
                print(f"⏳ Переподключение через {self.config.reconnect_delay} сек...")
                time.sleep(self.config.reconnect_delay)
                continue

            try:
                self.start_consuming()
            except KeyboardInterrupt:
                break
            except pika.exceptions.AMQPConnectionError:
                print("🔄 Соединение потеряно, переподключение...")
                continue
            except Exception as e:
                print(f"❌ Неожиданная ошибка: {e}")
                time.sleep(self.config.reconnect_delay)

        self.stop()


consumer = None  # global для signal handler

def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown"""
    print("\n🛑 Получен сигнал остановки...")
    if consumer:
        consumer.stop()
    sys.exit(0)


def decode_unicode_escapes(text: str) -> str:
    """
    Превращает '\\u0412...' в реальные символы.
    Вход: обычная строка с backslash-u последовательностями.
    """
    # unescape на случай &amp; и т.п.
    text = unescape(text)
    # главное — unicode_escape
    return text.encode("utf-8").decode("unicode_escape")


def html_to_markdown(text: str) -> str:
    """
    Конвертация HTML в Markdown.
    """
    return html_to_md(text, heading_style="ATX")

def process_rabbitmq_message(
    body: Union[bytes, str],
) -> str:
    # 0. bytes -> str
    if isinstance(body, bytes):
        raw_text = body.decode("utf-8", errors="replace")
    else:
        raw_text = body

    # 1. декодирование \uXXXX
    decoded_unicode = unescape(raw_text)
    decoded_unicode = decoded_unicode.encode("utf-8").decode("unicode_escape")
    decoded_unicode = fix_text(decoded_unicode)
    # 2. (здесь можно вставить резолв упоминаний, если нужен)
    html_with_mentions = decoded_unicode

    # 3. HTML -> Markdown
    markdown_text = html_to_md(html_with_mentions, heading_style="ATX")
    markdown_text = markdown_text.strip()

    # 4. 🔴 ВАЖНО: чистим суррогаты ПЕРЕД любым .encode('utf-8')
    markdown_text = normalize_text(markdown_text)

    return markdown_text

def normalize_text(s: str) -> str:
    """
    Убирает суррогаты, максимально сохраняя байты.
    """
    return s.encode("utf-8", "replace").decode("utf-8")


def extract_adf_text(adf_node) -> str:
    """
    Извлекает текст из Atlassian Document Format (ADF).
    ADF используется в Jira для description и comments.
    """
    if adf_node is None:
        return ""
    
    if isinstance(adf_node, str):
        return adf_node
    
    if isinstance(adf_node, dict):
        if adf_node.get("type") == "text":
            return adf_node.get("text", "")
        
        content = adf_node.get("content", [])
        texts = [extract_adf_text(child) for child in content]
        
        # Добавляем переносы для блочных элементов
        block_types = {"paragraph", "heading", "bulletList", "orderedList", "listItem", "codeBlock"}
        if adf_node.get("type") in block_types:
            return "\n".join(filter(None, texts)) + "\n"
        
        return "".join(texts)
    
    if isinstance(adf_node, list):
        return "".join(extract_adf_text(item) for item in adf_node)
    
    return ""


def process_jira_message(body: Union[bytes, str]) -> dict:
    """
    Обработка сообщения из Jira.
    Возвращает структурированный словарь с данными issue.
    """
    if isinstance(body, bytes):
        raw_text = body.decode("utf-8", errors="replace")
    else:
        raw_text = body

    data = json.loads(raw_text)
    
    fields = data.get("fields", {})
    
    # Извлекаем description (ADF формат)
    description_adf = fields.get("description")
    description_text = extract_adf_text(description_adf).strip() if description_adf else ""
    
    # Извлекаем комментарии
    comments_data = fields.get("comment", {}).get("comments", [])
    comments = []
    for c in comments_data:
        author = c.get("author", {}).get("displayName", "Unknown")
        created = c.get("created", "")
        body_adf = c.get("body")
        text = extract_adf_text(body_adf).strip() if body_adf else ""
        comments.append({
            "author": author,
            "created": created,
            "text": text
        })
    
    # Changelog
    changelog_histories = data.get("changelog", {}).get("histories", [])
    changes = []
    for h in changelog_histories:
        author = h.get("author", {}).get("displayName", "Unknown")
        created = h.get("created", "")
        items = h.get("items", [])
        for item in items:
            changes.append({
                "author": author,
                "created": created,
                "field": item.get("field", ""),
                "from": item.get("fromString", ""),
                "to": item.get("toString", "")
            })
    
    result = {
        "id": data.get("id"),
        "key": data.get("key"),
        "summary": fields.get("summary", ""),
        "status": fields.get("status", {}).get("name", ""),
        "assignee": fields.get("assignee", {}).get("displayName") if fields.get("assignee") else None,
        "reporter": fields.get("reporter", {}).get("displayName") if fields.get("reporter") else None,
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "priority": fields.get("priority", {}).get("name") if fields.get("priority") else None,
        "issuetype": fields.get("issuetype", {}).get("name") if fields.get("issuetype") else None,
        "description": description_text,
        "comments": comments,
        "changes": changes,
    }
    
    return result


def jira_to_markdown(jira_data: dict) -> str:
    """
    Конвертирует структуру Jira issue в Markdown.
    """
    lines = []
    
    lines.append(f"# [{jira_data['key']}] {jira_data['summary']}")
    lines.append("")
    lines.append(f"**Статус:** {jira_data['status']}")
    
    if jira_data.get('issuetype'):
        lines.append(f"**Тип:** {jira_data['issuetype']}")
    if jira_data.get('priority'):
        lines.append(f"**Приоритет:** {jira_data['priority']}")
    if jira_data.get('assignee'):
        lines.append(f"**Исполнитель:** {jira_data['assignee']}")
    if jira_data.get('reporter'):
        lines.append(f"**Автор:** {jira_data['reporter']}")
    if jira_data.get('created'):
        lines.append(f"**Создано:** {jira_data['created']}")
    if jira_data.get('updated'):
        lines.append(f"**Обновлено:** {jira_data['updated']}")
    
    lines.append("")
    
    if jira_data.get('description'):
        lines.append("## Описание")
        lines.append("")
        lines.append(jira_data['description'])
        lines.append("")
    
    if jira_data.get('comments'):
        lines.append("## Комментарии")
        lines.append("")
        for c in jira_data['comments']:
            lines.append(f"**{c['author']}** ({c['created']}):")
            lines.append(c['text'])
            lines.append("")
    
    if jira_data.get('changes'):
        lines.append("## История изменений")
        lines.append("")
        for ch in jira_data['changes'][-10:]:  # последние 10 изменений
            lines.append(f"- {ch['created']}: {ch['author']} изменил **{ch['field']}**: {ch['from']} → {ch['to']}")
        lines.append("")
    
    return "\n".join(lines)


def drain_queue(queue_name: str, config: RabbitMQConfig = None) -> list:
    """
    Вытаскивает все сообщения из очереди без удаления (peek mode с auto_ack=False).
    Возвращает список обработанных объектов.
    """
    if config is None:
        config = RabbitMQConfig()
    
    credentials = pika.PlainCredentials(config.username, config.password)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=config.host,
            port=config.port,
            credentials=credentials,
            virtual_host=config.virtual_host,
            heartbeat=600,
            blocked_connection_timeout=300,
        )
    )
    channel = connection.channel()
    
    messages = []
    while True:
        method, props, body = channel.basic_get(queue=queue_name, auto_ack=True)
        if not method:
            break
        
        try:
            if queue_name == JIRA_QUEUE:
                data = process_jira_message(body)
            else:
                # Для Confluence возвращаем и raw data, и markdown
                raw = json.loads(body.decode("utf-8", errors="replace"))
                data = {
                    "raw": raw,
                    "markdown": process_rabbitmq_message(body)
                }
            messages.append(data)
        except Exception as e:
            print(f"⚠️ Ошибка парсинга сообщения: {e}")
            continue
    
    connection.close()
    return messages


def drain_all_queues(config: RabbitMQConfig = None) -> dict:
    """
    Вытаскивает данные из обеих очередей.
    """
    confluence = drain_queue(CONFLUENCE_QUEUE, config)
    jira = drain_queue(JIRA_QUEUE, config)
    
    print(f"📄 Confluence: {len(confluence)} страниц")
    print(f"📋 Jira: {len(jira)} issues")
    
    return {
        "confluence": confluence,
        "jira": jira,
    }


def main():
    """Точка входа"""
    import argparse
    
    parser = argparse.ArgumentParser(description="RabbitMQ Consumer для Confluence и Jira")
    parser.add_argument(
        "--queue", "-q",
        choices=["confluence", "jira", "both"],
        default="confluence",
        help="Какую очередь слушать (default: confluence)"
    )
    parser.add_argument(
        "--drain", "-d",
        action="store_true",
        help="Вытащить все сообщения разом (batch mode)"
    )
    args = parser.parse_args()
    
    # Конфигурация (использует defaults из config.py)
    config = RabbitMQConfig()
    
    # Drain mode
    if args.drain:
        if args.queue == "both":
            result = drain_all_queues(config)
            print(f"\nВсего: {len(result['confluence'])} Confluence + {len(result['jira'])} Jira")
        elif args.queue == "jira":
            issues = drain_queue(JIRA_QUEUE, config)
            print(f"📋 Получено {len(issues)} Jira issues")
            for issue in issues:
                print(jira_to_markdown(issue))
                print("-" * 50)
        else:
            pages = drain_queue(CONFLUENCE_QUEUE, config)
            print(f"📄 Получено {len(pages)} Confluence pages")
            for page in pages:
                print(page.get("markdown", ""))
                print("-" * 50)
        return
    
    # Streaming mode
    queue_map = {
        "confluence": CONFLUENCE_QUEUE,
        "jira": JIRA_QUEUE,
    }
    
    if args.queue == "both":
        print("⚠️ Streaming mode поддерживает только одну очередь. Используйте --drain для обеих.")
        return
    
    config.queue_name = queue_map[args.queue]
    
    # Регистрация обработчика Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    # Создание потребителя
    global consumer
    consumer = RabbitMQConsumer(config)

    try:
        consumer.run()
    except KeyboardInterrupt:
        consumer.stop()


# Дополнительный пример: кастомный обработчик JSON сообщений
def json_message_handler(ch, method, properties, body):
    """Пример обработки JSON сообщений"""
    try:
        data = json.loads(body)
        print(f"📦 JSON сообщение: {json.dumps(data, indent=2, ensure_ascii=False)}")
        print(f"   Headers: {dict(properties.headers) if properties.headers else 'нет'}")

        # Ваша бизнес-логика здесь
        # Например: сохранить в БД, отправить уведомление и т.д.

        ch.basic_ack(delivery_tag=method.delivery_tag)
        print("   ✅ JSON обработано\n")

    except json.JSONDecodeError:
        print("   ❌ Неверный JSON")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # Отбрасываем
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


if __name__ == '__main__':
    main()
```

### ./metatron/__init__.py
```python
"""
Metatron - Hybrid RAG system combining vector search and knowledge graph.

This package provides:
- Document processing (HTML, Jira, Confluence)
- Vector indexing (Qdrant via Mem0)
- Graph indexing (Memgraph)
- Hybrid search with date filtering
- RabbitMQ consumers for real-time ingestion
"""

__version__ = "0.2.0"

from metatron.config import (
    RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS,
    MEMGRAPH_URI, MEMGRAPH_USER, MEMGRAPH_PASS,
    OLLAMA_URL, QDRANT_HOST, QDRANT_PORT,
    CONFLUENCE_QUEUE, JIRA_QUEUE,
)

from metatron.utils import bg_print, safe_input, normalize_text, chunk_text, set_quiet_mode

from metatron.processing import (
    extract_date_from_text,
    process_rabbitmq_message,
    extract_title_from_markdown,
)

from metatron.indexers import (
    get_hybrid_store,
    write_doc_graph_to_memgraph,
    write_jira_graph_to_memgraph,
    get_graph_entities,
    get_all_workspace_entities,
)

from metatron.search import (
    search_with_date_filter,
    hybrid_search_and_answer,
)

__all__ = [
    # Config
    "RABBITMQ_HOST", "RABBITMQ_PORT", "RABBITMQ_USER", "RABBITMQ_PASS",
    "MEMGRAPH_URI", "MEMGRAPH_USER", "MEMGRAPH_PASS",
    "OLLAMA_URL", "QDRANT_HOST", "QDRANT_PORT",
    "CONFLUENCE_QUEUE", "JIRA_QUEUE",
    # Utils
    "bg_print", "safe_input", "normalize_text", "chunk_text", "set_quiet_mode",
    # Processing
    "extract_date_from_text", "process_rabbitmq_message", "extract_title_from_markdown",
    # Indexers (workspace-aware)
    "get_hybrid_store", "write_doc_graph_to_memgraph", "write_jira_graph_to_memgraph",
    "get_graph_entities", "get_all_workspace_entities",
    # Search (workspace-aware)
    "search_with_date_filter", "hybrid_search_and_answer",
]

```

### ./metatron/api.py
```python
"""
FastAPI backend for the MTRNIX hybrid QA/chat system.

Features:
- Upload user documents (text, HTML, CSV, Excel) -> vector store + Memgraph
- Hybrid question answering (vector + graph) with date filtering
- Workspace isolation for multi-tenant data separation
- RabbitMQ consumers (Confluence + Jira) run automatically
- Serves frontend at `/`

Run:
    python start.py
    # or
    uvicorn metatron.api:app --reload --port 8000
"""
from pathlib import Path
from typing import Dict, List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import threading
import time

from metatron.config import CONFLUENCE_QUEUE, JIRA_QUEUE
from metatron.indexers.hybrid_store_workspace import get_hybrid_store
from metatron.indexers.memgraph_workspace import write_doc_graph_to_memgraph
from metatron.search import hybrid_search_and_answer
from metatron.processing import (
    process_rabbitmq_message,
    extract_title_from_markdown,
    extract_date_from_text,
    process_tabular_file,
    is_tabular_file,
)
from metatron.consumers import RabbitMQConfig, ConfluenceConsumer, JiraConsumer
from metatron.utils import chunk_text, get_embedding_cache_stats, clear_embedding_cache, build_doc_label
from metatron.workspaces import get_workspace_manager
from metatron.metrics import get_metrics, reset_metrics, timed

# Import workspace router
from metatron.api_workspaces import router as workspace_router
# Import admin router
from metatron.api_admin import router as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup: auto-start RabbitMQ consumers
    _start_consumers()
    yield
    # Shutdown: stop consumers
    _stop_consumers()


app = FastAPI(title="MTRNIX Chat", version="2.0.0", lifespan=lifespan)

# Include workspace management router
app.include_router(workspace_router)
# Include admin router
app.include_router(admin_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Frontend static files
frontend_dir = Path(__file__).parent.parent / "frontend"
frontend_dir.mkdir(parents=True, exist_ok=True)
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


# ============================================================================
# Request/Response Models
# ============================================================================

class ChatRequest(BaseModel):
    """Chat request with workspace support."""
    question: str = Field(..., min_length=1)
    workspace_id: Optional[str] = Field(None, description="Workspace ID (uses active workspace if not provided)")
    user_id: str = "user"
    top_k: int = Field(5, ge=1, le=20)
    history_turns: int = Field(6, ge=0, le=20)


class UploadResponse(BaseModel):
    """Upload response with workspace info."""
    status: str
    file_name: str
    chunks: int
    workspace_id: str
    graph_extracted: bool = True


class ChatResponse(BaseModel):
    """Chat response with workspace info."""
    answer: str
    workspace_id: str


class RabbitMQStatus(BaseModel):
    status: str
    last_error: Optional[str] = None
    confluence_running: bool = False
    jira_running: bool = False


# ============================================================================
# State
# ============================================================================

rb_state = {
    "status": "idle",
    "last_error": None,
}
jira_state = {
    "status": "idle",
    "last_error": None,
}
confluence_consumer: Optional[ConfluenceConsumer] = None
jira_consumer: Optional[JiraConsumer] = None
confluence_thread: Optional[threading.Thread] = None
jira_thread: Optional[threading.Thread] = None

conversation_history: Dict[str, List[Dict[str, str]]] = {}
history_lock = threading.Lock()


# ============================================================================
# Document Ingestion (Workspace-Aware)
# ============================================================================

@timed("document_ingest")
def ingest_text(
    text: str,
    file_name: str,
    user_id: str = "user",
    workspace_id: Optional[str] = None,
    extract_graph: bool = True
) -> dict:
    """
    Send text to workspace-specific Qdrant collection + optionally write entities to Memgraph.

    Args:
        text: Document text
        file_name: Document name
        user_id: User identifier
        workspace_id: Workspace identifier (uses active workspace if not provided)
        extract_graph: If True, extract entities/relationships via LLM (slow, +20-30s)

    Returns:
        Dict with chunks count, workspace_id, and graph_extracted flag
    """
    # Get workspace
    manager = get_workspace_manager()
    if workspace_id is None:
        workspace = manager.get_active_workspace(user_id)
        workspace_id = workspace.workspace_id
    else:
        workspace = manager.get_workspace(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace '{workspace_id}' not found")

    normalized_text = text or ""
    if not normalized_text.strip():
        raise ValueError("Document is empty")

    # Get workspace-specific hybrid store
    store = get_hybrid_store(workspace_id)
    chunks = chunk_text(normalized_text, max_chars=2500, overlap=200)

    # Extract date for metadata
    doc_date = extract_date_from_text(file_name) or extract_date_from_text(normalized_text[:500])
    doc_label, upload_time = build_doc_label(
        source_id=file_name,
        user_id=user_id,
        workspace_id=workspace_id,
    )

    metadata = {
        "title": file_name,
        "type": "confluence",  # Manual uploads treated as confluence
        "workspace_id": workspace_id,
        "user_id": user_id,
        "doc_label": doc_label,
    }
    if doc_date:
        metadata["date"] = doc_date

    # Add chunks to workspace-specific Qdrant collection
    for chunk in chunks:
        store.add_document(
            text=chunk,
            metadata=metadata,
            doc_id=doc_label
        )

    # Extract knowledge graph (optional, slow)
    if extract_graph:
        graph_text = chunks[0] if len(normalized_text) > 8000 else normalized_text
        write_doc_graph_to_memgraph(
            text=graph_text,
            file_name=file_name,
            user_id=user_id,
            workspace_id=workspace_id,
            doc_label=doc_label,
            upload_time=upload_time,
        )

    return {"chunks": len(chunks), "workspace_id": workspace_id, "graph_extracted": extract_graph}


# ============================================================================
# Endpoints
# ============================================================================

@app.get("/health")
def healthcheck():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    """
    Get application metrics.

    Returns timing statistics, request counters, and cache stats.
    """
    data = get_metrics()
    data["embedding_cache"] = get_embedding_cache_stats()
    return data


@app.post("/metrics/reset")
def metrics_reset():
    """Reset all metrics counters and caches."""
    reset_metrics()
    clear_embedding_cache()
    return {"status": "reset"}


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve frontend HTML."""
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return HTMLResponse(
        "<h3>MTRNIX backend is running.</h3>"
        "<p>API docs: <a href='/docs'>/docs</a></p>",
        status_code=200
    )


def is_html_file(filename: str) -> bool:
    """Check if file is HTML by extension."""
    return filename.lower().endswith((".html", ".htm"))


@app.post("/api/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Form("user"),
    workspace_id: Optional[str] = Form(None),
    extract_graph: bool = Form(True),
):
    """
    Upload and index a document to a workspace.

    Supported formats:
    - Text files (.txt, .md) - indexed as-is
    - HTML files (.html, .htm) - auto-converted to markdown
    - CSV files (.csv) - converted to key-value text
    - Excel files (.xlsx, .xls) - converted to key-value text

    Args:
        workspace_id: Target workspace (uses active workspace if not provided)
        extract_graph: If True, extract entities and relationships for knowledge graph.
                       Slower (+20-30s per doc) but enables relationship-based search.
    """
    raw_bytes = await file.read()
    if raw_bytes is None:
        raise HTTPException(status_code=400, detail="No file content provided")

    file_name = file.filename or "document.txt"

    # Handle tabular files (CSV, Excel)
    if is_tabular_file(file_name):
        try:
            text, metadata = process_tabular_file(raw_bytes, file_name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to parse tabular file: {e}")
    elif is_html_file(file_name):
        # Auto-convert HTML to Markdown
        text = raw_bytes.decode("utf-8", errors="replace")
        text = process_rabbitmq_message(text)
        file_name = extract_title_from_markdown(text, raw_bytes) or file_name
    else:
        text = raw_bytes.decode("utf-8", errors="replace")

    try:
        result = ingest_text(
            text=text,
            file_name=file_name,
            user_id=user_id,
            workspace_id=workspace_id,
            extract_graph=extract_graph
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"status": "ok", "file_name": file_name, **result}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Hybrid search with conversation history and workspace isolation."""
    # Get workspace_id for response
    manager = get_workspace_manager()
    if req.workspace_id:
        workspace_id = req.workspace_id
    else:
        workspace = manager.get_active_workspace(req.user_id)
        workspace_id = workspace.workspace_id

    with history_lock:
        history = conversation_history.get(req.user_id, [])[-req.history_turns:]

    # Build composite query with history (limit size to prevent context overflow)
    MAX_HISTORY_CHARS = 4000
    history_lines = []
    total_history_chars = 0

    for turn in reversed(history):
        user_msg = turn.get('user', '')[:500]
        line = f"Previous question: {user_msg}"
        if total_history_chars + len(line) > MAX_HISTORY_CHARS:
            break
        history_lines.insert(0, line)
        total_history_chars += len(line)

    composite_query = (
        "\n".join(history_lines + [f"Current question: {req.question}"])
        if history_lines
        else req.question
    )

    try:
        answer = hybrid_search_and_answer(
            query=composite_query,
            user_id=req.user_id,
            workspace_id=req.workspace_id,
            k=req.top_k, intent_query=req.question
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Store in history
    with history_lock:
        hist = conversation_history.setdefault(req.user_id, [])
        hist.append({"user": req.question, "assistant": answer[:2000]})
        if len(hist) > 20:
            del hist[:-20]

        if len(conversation_history) > 100:
            oldest = list(conversation_history.keys())[:50]
            for uid in oldest:
                del conversation_history[uid]

    return {"answer": answer, "workspace_id": workspace_id}


# ============================================================================
# RabbitMQ Consumer Management
# ============================================================================

@app.get("/api/rabbitmq/status", response_model=RabbitMQStatus)
def rabbitmq_status():
    """Get RabbitMQ consumers status."""
    return rb_state


def _start_confluence_consumer():
    """Internal: start Confluence RabbitMQ consumer."""
    global confluence_consumer, confluence_thread

    if rb_state["status"] == "running":
        return

    rb_state.update({"status": "running", "last_error": None})

    def run_confluence():
        global confluence_consumer
        try:
            confluence_consumer = ConfluenceConsumer(
                RabbitMQConfig(queue_name=CONFLUENCE_QUEUE),
                user_id="user"
            )
            confluence_consumer.run()
        except Exception as exc:
            rb_state.update({"status": "error", "last_error": str(exc)})
        finally:
            rb_state["status"] = "stopped"

    confluence_thread = threading.Thread(target=run_confluence, daemon=True)
    confluence_thread.start()


def _stop_confluence_consumer():
    """Internal: stop Confluence RabbitMQ consumer."""
    if confluence_consumer:
        confluence_consumer.stop()
    if confluence_thread and confluence_thread.is_alive():
        for _ in range(10):
            if not confluence_thread.is_alive():
                break
            time.sleep(0.1)
    rb_state["status"] = "stopped"


def _start_jira_consumer():
    """Internal: start Jira RabbitMQ consumer."""
    global jira_consumer, jira_thread

    if jira_state["status"] == "running":
        return

    jira_state.update({"status": "running", "last_error": None})

    def run_jira():
        global jira_consumer
        try:
            jira_consumer = JiraConsumer(
                RabbitMQConfig(queue_name=JIRA_QUEUE),
                user_id="user"
            )
            jira_consumer.run()
        except Exception as exc:
            jira_state.update({"status": "error", "last_error": str(exc)})
        finally:
            jira_state["status"] = "stopped"

    jira_thread = threading.Thread(target=run_jira, daemon=True)
    jira_thread.start()


def _stop_jira_consumer():
    """Internal: stop Jira RabbitMQ consumer."""
    if jira_consumer:
        jira_consumer.stop()
    if jira_thread and jira_thread.is_alive():
        for _ in range(10):
            if not jira_thread.is_alive():
                break
            time.sleep(0.1)
    jira_state["status"] = "stopped"


def _start_consumers():
    """Internal: start both consumers."""
    _start_confluence_consumer()
    _start_jira_consumer()


def _stop_consumers():
    """Internal: stop both consumers."""
    _stop_confluence_consumer()
    _stop_jira_consumer()


@app.post("/api/rabbitmq/start")
def rabbitmq_start():
    """Start Confluence RabbitMQ consumer."""
    _start_confluence_consumer()
    return {"status": rb_state["status"], "last_error": rb_state["last_error"]}


@app.post("/api/rabbitmq/stop")
def rabbitmq_stop():
    """Stop Confluence RabbitMQ consumer."""
    _stop_confluence_consumer()
    return {"status": rb_state["status"], "last_error": rb_state["last_error"]}


# ============================================================================
# Jira Consumer Endpoints
# ============================================================================

@app.get("/api/jira/status")
def jira_status():
    """Get Jira consumer status."""
    return jira_state


@app.post("/api/jira/start")
def jira_start():
    """Start Jira RabbitMQ consumer."""
    _start_jira_consumer()
    return jira_state


@app.post("/api/jira/stop")
def jira_stop():
    """Stop Jira RabbitMQ consumer."""
    _stop_jira_consumer()
    return jira_state

```

### ./metatron/api_admin.py
```python
"""
Admin API endpoints for Metatron.

Provides administrative operations including:
- Database cleanup (Qdrant + Memgraph)
- System diagnostics

All endpoints require ALLOW_CLEANUP=true environment variable for destructive operations.
"""
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel, Field

from metatron.config import setup_logging
from metatron.db.cleanup import (
    cleanup_workspace,
    cleanup_all,
    get_cleanup_preview,
    CleanupError,
    ALLOW_CLEANUP,
)

logger = setup_logging(__name__)


# ============================================================================
# Request/Response Models
# ============================================================================

class CleanupPreviewResponse(BaseModel):
    """Response model for cleanup preview."""
    cleanup_allowed: bool
    qdrant: Dict
    memgraph: Dict


class CleanupResponse(BaseModel):
    """Response model for cleanup operation."""
    status: str
    qdrant: Optional[Dict] = None
    memgraph: Optional[Dict] = None
    workspace_id: Optional[str] = None
    workspaces: Optional[Dict] = None
    store_cache: Optional[Dict] = None


class WorkspaceCleanupRequest(BaseModel):
    """Request model for workspace cleanup."""
    workspace_id: str = Field(..., description="Workspace ID to clean up")


# ============================================================================
# Router
# ============================================================================

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/cleanup/preview", response_model=CleanupPreviewResponse)
def preview_cleanup() -> CleanupPreviewResponse:
    """
    Preview what data would be deleted.

    Returns counts of collections, points, nodes, and relationships
    that would be affected by a cleanup operation.

    This is a safe, read-only operation.
    """
    preview = get_cleanup_preview()
    return CleanupPreviewResponse(**preview)


@router.delete("/cleanup/workspace/{workspace_id}", response_model=CleanupResponse)
def cleanup_workspace_endpoint(
    workspace_id: str,
    x_confirm_cleanup: Optional[str] = Header(None, description="Set to 'yes' to confirm cleanup")
) -> CleanupResponse:
    """
    Delete all data for a specific workspace.

    WARNING: This permanently deletes all Qdrant vectors and Memgraph nodes
    for the specified workspace. This action cannot be undone.

    Requirements:
    - Environment variable ALLOW_CLEANUP=true must be set
    - Header X-Confirm-Cleanup: yes must be provided
    """
    if x_confirm_cleanup != "yes":
        raise HTTPException(
            status_code=400,
            detail="Cleanup requires header 'X-Confirm-Cleanup: yes'"
        )

    try:
        result = cleanup_workspace(workspace_id, confirm=True)
        return CleanupResponse(**result)
    except CleanupError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Cleanup error for workspace '{workspace_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cleanup/all", response_model=CleanupResponse)
def cleanup_all_endpoint(
    x_confirm_cleanup: Optional[str] = Header(None, description="Set to 'DELETE-ALL-DATA' to confirm")
) -> CleanupResponse:
    """
    Delete ALL data from ALL databases.

    WARNING: This permanently deletes ALL Qdrant collections and ALL Memgraph nodes
    across ALL workspaces. This action cannot be undone.

    Requirements:
    - Environment variable ALLOW_CLEANUP=true must be set
    - Header X-Confirm-Cleanup: DELETE-ALL-DATA must be provided
    """
    if x_confirm_cleanup != "DELETE-ALL-DATA":
        raise HTTPException(
            status_code=400,
            detail="Full cleanup requires header 'X-Confirm-Cleanup: DELETE-ALL-DATA'"
        )

    try:
        result = cleanup_all(confirm=True)
        return CleanupResponse(**result)
    except CleanupError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Full cleanup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def admin_status() -> Dict:
    """
    Get admin/system status.

    Returns information about cleanup permissions and database connectivity.
    """
    status = {
        "cleanup_allowed": ALLOW_CLEANUP,
        "databases": {}
    }

    # Check Qdrant connectivity
    try:
        from metatron.db.cleanup import get_qdrant_client, list_qdrant_collections
        client = get_qdrant_client()
        collections = list_qdrant_collections()
        status["databases"]["qdrant"] = {
            "status": "connected",
            "collections_count": len(collections)
        }
    except Exception as e:
        status["databases"]["qdrant"] = {
            "status": "error",
            "error": str(e)
        }

    # Check Memgraph connectivity
    try:
        from metatron.db import get_memgraph_driver
        driver = get_memgraph_driver()
        with driver.session() as session:
            result = session.run("RETURN 1 AS ok")
            result.single()
        status["databases"]["memgraph"] = {
            "status": "connected"
        }
    except Exception as e:
        status["databases"]["memgraph"] = {
            "status": "error",
            "error": str(e)
        }

    return status
```

### ./metatron/api_workspaces.py
```python
"""
Workspace API endpoints for Metatron.

Provides REST API for workspace management including:
- Create/list/delete workspaces
- Activate workspace for user
- Get workspace statistics
"""
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from metatron.config import setup_logging
from metatron.workspaces import get_workspace_manager, Workspace, WorkspaceStats

logger = setup_logging(__name__)


# ============================================================================
# Request/Response Models
# ============================================================================

class WorkspaceCreateRequest(BaseModel):
    """Request model for creating a workspace."""
    name: str = Field(..., min_length=1, max_length=100, description="Workspace name")
    description: Optional[str] = Field(None, max_length=500, description="Workspace description")
    user_id: str = Field("user", description="User ID (owner)")
    workspace_id: Optional[str] = Field(None, description="Custom workspace ID (auto-generated if not provided)")


class WorkspaceResponse(BaseModel):
    """Response model for workspace data."""
    workspace_id: str
    name: str
    description: Optional[str]
    created_at: str
    user_id: str
    is_active: bool
    config: Optional[Dict] = None


class WorkspaceListResponse(BaseModel):
    """Response model for workspace list."""
    workspaces: List[WorkspaceResponse]
    count: int


class WorkspaceStatsResponse(BaseModel):
    """Response model for workspace statistics."""
    workspace_id: str
    name: str
    file_count: int  # Unique files (by title)
    chunk_count: int  # Total chunks in Qdrant
    entity_count: int
    jira_issue_count: int
    last_upload_time: Optional[str]


class ActivateWorkspaceResponse(BaseModel):
    """Response model for workspace activation."""
    workspace_id: str
    name: str
    status: str


# ============================================================================
# Router
# ============================================================================

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


# ============================================================================
# Endpoints
# ============================================================================

@router.post("", response_model=WorkspaceResponse, status_code=201)
def create_workspace(req: WorkspaceCreateRequest) -> WorkspaceResponse:
    """
    Create a new workspace.
    
    Creates a new isolated workspace with its own Qdrant collection and Memgraph subgraph.
    All documents uploaded to this workspace will be isolated from other workspaces.
    """
    manager = get_workspace_manager()
    
    try:
        workspace = manager.create_workspace(
            name=req.name,
            description=req.description,
            user_id=req.user_id,
            workspace_id=req.workspace_id
        )
        return WorkspaceResponse(**workspace.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    user_id: Optional[str] = Query(None, description="Filter by user ID")
) -> WorkspaceListResponse:
    """
    List all workspaces.
    
    Returns all workspaces accessible to the user.
    If user_id is provided, filters to that user's workspaces plus the default workspace.
    """
    manager = get_workspace_manager()
    workspaces = manager.list_workspaces(user_id=user_id)
    
    return WorkspaceListResponse(
        workspaces=[WorkspaceResponse(**ws.to_dict()) for ws in workspaces],
        count=len(workspaces)
    )


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(workspace_id: str) -> WorkspaceResponse:
    """
    Get workspace details.
    
    Returns detailed information about a specific workspace.
    """
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    
    return WorkspaceResponse(**workspace.to_dict())


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: str, user_id: str = Query("user")) -> Dict[str, str]:
    """
    Delete a workspace.
    
    WARNING: This will permanently delete the workspace's Qdrant collection
    and all associated graph data. This action cannot be undone.
    
    The default workspace cannot be deleted.
    """
    manager = get_workspace_manager()
    
    # Check if workspace exists
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    
    # Check ownership (optional - can be removed if not needed)
    if workspace.user_id != user_id and not workspace.is_default():
        raise HTTPException(status_code=403, detail="You don't have permission to delete this workspace")
    
    try:
        deleted = manager.delete_workspace(workspace_id)
        if not deleted:
            raise HTTPException(status_code=400, detail=f"Failed to delete workspace '{workspace_id}'")

        # Also delete Qdrant collection and Memgraph data
        from metatron.indexers.hybrid_store_workspace import get_hybrid_store
        from metatron.indexers.memgraph_workspace import delete_workspace_graph

        # Collect errors instead of silently ignoring them
        errors = []

        # Delete Qdrant collection
        try:
            store = get_hybrid_store(workspace_id)
            store.delete()
        except Exception as e:
            logger.error(f"Failed to delete Qdrant collection for workspace '{workspace_id}': {e}")
            errors.append(f"Qdrant: {e}")

        # Delete Memgraph data
        try:
            delete_workspace_graph(workspace_id)
        except Exception as e:
            logger.error(f"Failed to delete Memgraph data for workspace '{workspace_id}': {e}")
            errors.append(f"Memgraph: {e}")

        # Report partial failure to user
        if errors:
            raise HTTPException(
                status_code=500,
                detail=f"Workspace metadata deleted, but data cleanup failed: {'; '.join(errors)}"
            )

        return {"status": "deleted", "workspace_id": workspace_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{workspace_id}/activate", response_model=ActivateWorkspaceResponse)
def activate_workspace(
    workspace_id: str,
    user_id: str = Query("user", description="User ID to activate workspace for")
) -> ActivateWorkspaceResponse:
    """
    Set active workspace for a user.
    
    Sets the specified workspace as active for the given user.
    All subsequent API calls without an explicit workspace_id will use this workspace.
    """
    manager = get_workspace_manager()
    
    # Check if workspace exists
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    
    # Activate workspace
    success = manager.set_active_workspace(user_id, workspace_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to activate workspace '{workspace_id}'")
    
    return ActivateWorkspaceResponse(
        workspace_id=workspace_id,
        name=workspace.name,
        status="activated"
    )


@router.get("/{workspace_id}/stats", response_model=WorkspaceStatsResponse)
def get_workspace_stats(workspace_id: str) -> WorkspaceStatsResponse:
    """
    Get workspace statistics.

    Returns statistics about files, chunks, entities, and other data in the workspace.
    """
    manager = get_workspace_manager()

    # Check if workspace exists
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")

    # Get base stats from manager
    base_stats = manager.get_workspace_stats(workspace_id)

    # Get Qdrant stats (files and chunks)
    file_count = 0
    chunk_count = 0
    try:
        from metatron.indexers.hybrid_store_workspace import get_hybrid_store
        store = get_hybrid_store(workspace_id)
        qdrant_stats = store.get_stats()
        file_count = qdrant_stats.get("file_count", 0)
        chunk_count = qdrant_stats.get("chunk_count", 0)
    except Exception as e:
        logger.warning(f"Failed to get Qdrant stats for workspace '{workspace_id}': {e}")

    # Get Memgraph stats (entities, jira issues)
    entity_count = 0
    jira_issue_count = 0
    try:
        from metatron.db import get_memgraph_driver

        driver = get_memgraph_driver()
        with driver.session() as session:
            # Count entities
            result = session.run(
                "MATCH (e:Entity {workspace_id: $workspace_id}) RETURN count(e) AS count",
                {"workspace_id": workspace_id}
            )
            entity_count = result.single()["count"]

            # Count Jira issues
            result = session.run(
                "MATCH (j:JiraIssue {workspace_id: $workspace_id}) RETURN count(j) AS count",
                {"workspace_id": workspace_id}
            )
            jira_issue_count = result.single()["count"]
    except Exception as e:
        logger.warning(f"Failed to get Memgraph stats for workspace '{workspace_id}': {e}")

    return WorkspaceStatsResponse(
        workspace_id=workspace_id,
        name=workspace.name,
        file_count=file_count,
        chunk_count=chunk_count,
        entity_count=entity_count,
        jira_issue_count=jira_issue_count,
        last_upload_time=base_stats.last_upload_time,
    )
```

### ./metatron/config.py
```python
"""
Централизованная конфигурация для всех сервисов Metatron.

Переменные окружения (опционально):
  ENV                - окружение: development, staging, production (default: development)
  METATRON_HOST      - основной хост (default: metattron.ximi.group)
  RABBITMQ_HOST      - хост RabbitMQ (default: METATRON_HOST)
  MEMGRAPH_HOST      - хост Memgraph (default: METATRON_HOST)
  QDRANT_HOST        - хост Qdrant (default: METATRON_HOST)
  OLLAMA_HOST        - хост Ollama (default: METATRON_HOST)

Для локальной разработки:
  export METATRON_HOST=localhost

Или для отдельных сервисов:
  export RABBITMQ_HOST=localhost
  export MEMGRAPH_HOST=localhost

Production режим (ENV=production):
  - Предупреждения если используются дефолтные пароли
  - Обязательная проверка credentials

Логирование:
  LOG_LEVEL          - уровень логирования (default: INFO)
  LOG_FORMAT         - формат: json, text (default: text)
"""
import os
import logging
import sys

# Автозагрузка .env если есть python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv не установлен, используем только os.environ

# =============================================================================
# Environment Detection
# =============================================================================

ENV = os.getenv("ENV", "development")  # development, staging, production

# =============================================================================
# Logging Configuration
# =============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "text")  # text or json


def setup_logging(name: str = None) -> logging.Logger:
    """
    Get a configured logger for a module.

    Args:
        name: Logger name (usually __name__ from the calling module)

    Returns:
        Configured logger instance

    Usage:
        from metatron.config import setup_logging
        logger = setup_logging(__name__)
        logger.info("Message")
    """
    logger = logging.getLogger(name or "metatron")

    # Only configure if not already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)

        if LOG_FORMAT == "json":
            # JSON format for production/structured logging
            fmt = '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
        else:
            # Human-readable format for development
            fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

        handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        logger.propagate = False

    return logger


# Root logger for metatron package
_root_logger = setup_logging("metatron")


def _require_env(key: str, default: str = None) -> str:
    """
    Get environment variable with optional default.

    In production (ENV=production), raises error if variable is not set
    and no default is provided, or if using insecure defaults for credentials.

    Args:
        key: Environment variable name
        default: Default value for development

    Returns:
        Environment variable value or default

    Raises:
        ValueError: If required variable is not set in production
    """
    value = os.getenv(key, default)

    if ENV == "production":
        # Check for missing required values
        if value is None:
            raise ValueError(
                f"Required environment variable {key} is not set. "
                f"Please configure it for production environment."
            )
        # Warn about insecure defaults for credential-like variables
        if default and value == default and any(x in key.upper() for x in ["PASS", "KEY", "SECRET", "TOKEN"]):
            import warnings
            warnings.warn(
                f"Environment variable {key} is using default value in production. "
                f"Please set a secure value.",
                RuntimeWarning
            )

    return value or default


# =============================================================================
# CENTRAL CONFIG (с поддержкой env vars)
# =============================================================================

# Основной хост (production по умолчанию)
METATRON_HOST = os.getenv("METATRON_HOST", "metattron.ximi.group")

# RabbitMQ
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", METATRON_HOST)
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = _require_env("RABBITMQ_USER", "metatron")
RABBITMQ_PASS = _require_env("RABBITMQ_PASS", "metatron")

# Memgraph
MEMGRAPH_HOST = os.getenv("MEMGRAPH_HOST", METATRON_HOST)
MEMGRAPH_PORT = int(os.getenv("MEMGRAPH_PORT", "7687"))
MEMGRAPH_URI = f"bolt://{MEMGRAPH_HOST}:{MEMGRAPH_PORT}"
MEMGRAPH_USER = _require_env("MEMGRAPH_USER", "user")
MEMGRAPH_PASS = _require_env("MEMGRAPH_PASS", "pass")

# Ollama (embeddings)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", METATRON_HOST)
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_URL = f"{OLLAMA_HOST}:{OLLAMA_PORT}"

# Qdrant (vector store)
QDRANT_HOST = os.getenv("QDRANT_HOST", METATRON_HOST)
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

# PostgreSQL (application data: users, configs, connections)
# Format: postgresql://user:password@host:port/database
POSTGRES_URL = os.getenv("POSTGRES_URL", "")

# Queues

CONFLUENCE_QUEUE = os.getenv("CONFLUENCE_QUEUE", "confluence_pages")
JIRA_QUEUE = os.getenv("JIRA_QUEUE", "jira_issues")

# =============================================================================
# LLM Configuration
# =============================================================================

# Provider selection: deepseek, openrouter, ollama, custom
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
LLM_MODEL = os.getenv("LLM_MODEL", "")  # Empty = use provider default

# Fallback provider (optional) - used when primary fails
LLM_FALLBACK_PROVIDER = os.getenv("LLM_FALLBACK_PROVIDER", "")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")

# DeepSeek
DEEPSEEK_API_KEY = _require_env("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# OpenRouter (access to Claude, GPT, Llama, etc.)
OPENROUTER_API_KEY = _require_env("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")

# Ollama (local LLM for chat, separate from embeddings)
OLLAMA_LLM_HOST = os.getenv("OLLAMA_LLM_HOST", "")  # Falls back to OLLAMA_HOST if empty
OLLAMA_LLM_PORT = os.getenv("OLLAMA_LLM_PORT", "")  # Falls back to OLLAMA_PORT if empty
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3")

# Custom OpenAI-compatible server
CUSTOM_LLM_URL = os.getenv("CUSTOM_LLM_URL", "")  # Full URL to /v1/chat/completions
CUSTOM_LLM_API_KEY = _require_env("CUSTOM_LLM_API_KEY", "")
CUSTOM_LLM_MODEL = os.getenv("CUSTOM_LLM_MODEL", "default")

# =============================================================================
# Workspace Configuration
# =============================================================================

# Default workspace settings
DEFAULT_WORKSPACE_ID = os.getenv("DEFAULT_WORKSPACE_ID", "MTRNIX")
DEFAULT_WORKSPACE_NAME = os.getenv("DEFAULT_WORKSPACE_NAME", "MTRNIX Workspace")

# Persist workspaces to Memgraph (enables sync between local and server)
WORKSPACE_PERSISTENCE = os.getenv("WORKSPACE_PERSISTENCE", "memgraph")  # memgraph, file, none

# =============================================================================
# Search Configuration
# =============================================================================

# Context limits for LLM (to fit in context window)
SEARCH_MAX_TOTAL_CHARS = int(os.getenv("SEARCH_MAX_TOTAL_CHARS", "40000"))  # ~16k tokens
SEARCH_MAX_FRAGMENT_CHARS = int(os.getenv("SEARCH_MAX_FRAGMENT_CHARS", "8000"))  # Per-fragment limit

# Search pool sizing
SEARCH_POOL_MULTIPLIER = int(os.getenv("SEARCH_POOL_MULTIPLIER", "3"))  # k * multiplier
SEARCH_POOL_MIN = int(os.getenv("SEARCH_POOL_MIN", "15"))  # Minimum pool size

# Date search limits
SEARCH_DATE_MULTIPLIER = int(os.getenv("SEARCH_DATE_MULTIPLIER", "2"))  # k * multiplier for date queries

# Jira search limits
SEARCH_JIRA_MULTIPLIER = int(os.getenv("SEARCH_JIRA_MULTIPLIER", "2"))  # k * multiplier for Jira queries

# Graph enrichment limits
SEARCH_GRAPH_RELATIONS_LIMIT = int(os.getenv("SEARCH_GRAPH_RELATIONS_LIMIT", "200"))  # Max relations to fetch
SEARCH_GRAPH_DEPTH = int(os.getenv("SEARCH_GRAPH_DEPTH", "5"))  # Graph traversal depth
SEARCH_RELATED_DOCS_LIMIT = int(os.getenv("SEARCH_RELATED_DOCS_LIMIT", "20"))  # Extra docs by graph labels

# Result prioritization
SEARCH_CONTEXT_EXTRA = int(os.getenv("SEARCH_CONTEXT_EXTRA", "5"))  # Extra results for LLM context

```

### ./metatron/consumers/__init__.py
```python
"""
RabbitMQ consumers for data ingestion.
"""
from metatron.consumers.base import RabbitMQConfig
from metatron.consumers.confluence import ConfluenceConsumer
from metatron.consumers.jira import JiraConsumer

__all__ = [
    "RabbitMQConfig",
    "ConfluenceConsumer",
    "JiraConsumer",
]

```

### ./metatron/consumers/base.py
```python
"""
Base RabbitMQ consumer configuration.
"""
from dataclasses import dataclass, field
from metatron.config import RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS


@dataclass
class RabbitMQConfig:
    """Configuration for RabbitMQ connection."""
    host: str = field(default_factory=lambda: RABBITMQ_HOST)
    port: int = field(default_factory=lambda: RABBITMQ_PORT)
    username: str = field(default_factory=lambda: RABBITMQ_USER)
    password: str = field(default_factory=lambda: RABBITMQ_PASS)
    virtual_host: str = "/"
    queue_name: str = "default_queue"
    reconnect_delay: int = 5
    prefetch_count: int = 1

```

### ./metatron/consumers/confluence.py
```python
"""
RabbitMQ consumer for Confluence pages.
"""
import json
import time
import traceback

import pika

from metatron.consumers.base import RabbitMQConfig
from metatron.utils import bg_print, chunk_text, build_doc_label
from metatron.processing import process_rabbitmq_message, extract_title_from_markdown, extract_date_from_text, translate_to_english
from metatron.indexers import write_doc_graph_to_memgraph, get_hybrid_store


class ConfluenceConsumer:
    """
    RabbitMQ consumer for Confluence pages.
    
    For each message:
    - Process HTML via process_rabbitmq_message
    - Extract document title from H1 header
    - Add to mem0 (vector + embeddings)
    - Write graph (entities/relations) to Memgraph
    """

    def __init__(self, config: RabbitMQConfig, user_id: str = "user"):
        self.config = config
        self.connection = None
        self.channel = None
        self._stopping = False
        self.user_id = user_id
        self._processed_ids: set[str] = set()

    def _get_message_id(self, body: bytes) -> str:
        """Extract unique message ID for deduplication."""
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                return data.get("id", "") or data.get("key", "") or str(hash(body))
        except Exception:
            pass
        return str(hash(body))

    def connect(self) -> bool:
        """Connect to RabbitMQ."""
        try:
            credentials = pika.PlainCredentials(
                username=self.config.username,
                password=self.config.password,
            )
            parameters = pika.ConnectionParameters(
                host=self.config.host,
                port=self.config.port,
                virtual_host=self.config.virtual_host,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300,
            )
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            self.channel.basic_qos(prefetch_count=self.config.prefetch_count)
            self.channel.queue_declare(
                queue=self.config.queue_name,
                durable=True,
                arguments={"x-queue-type": "classic"},
            )
            bg_print(f"✅ RabbitMQ: Connected to {self.config.host}:{self.config.port}")
            bg_print(f"   Queue: {self.config.queue_name} (classic, durable)")
            return True
        except Exception as e:
            bg_print(f"❌ RabbitMQ: Connection error: {e}")
            return False

    def start_consuming(self):
        """Start consuming messages from RabbitMQ."""
        store = get_hybrid_store()
        
        def callback(ch, method, properties, body):
            msg_id = self._get_message_id(body)
            
            # Deduplication
            if msg_id in self._processed_ids:
                bg_print(f"   ⏭️ Skipping duplicate: {msg_id[:50]}...")
                try:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    pass
                return
            
            # ACK immediately to avoid requeue on connection loss
            try:
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                bg_print(f"   ⚠️ ACK failed, continuing: {e}")
            
            self._processed_ids.add(msg_id)
            
            try:
                # 1) Process HTML
                md_text = process_rabbitmq_message(body)
                title = extract_title_from_markdown(md_text, body)
                bg_print(f"\n📥 RabbitMQ: Confluence page: {title}")

                # 2) Extract date for metadata
                doc_date = extract_date_from_text(title)

                # 3) Add title to content
                if title and not md_text.startswith(f"# {title}"):
                    md_text = f"# {title}\n\n{md_text}"

                # 4) Translate to English for embedding
                bg_print(f"   → translating to English...")
                md_text_en = translate_to_english(md_text)

                # 5) Add to hybrid store (dense + BM25 sparse vectors)
                chunks = chunk_text(md_text_en, max_chars=2500, overlap=200)
                
                doc_label, upload_time = build_doc_label(
                    source_id=msg_id,
                    user_id=self.user_id,
                )

                metadata = {"title": title, "type": "confluence", "doc_label": doc_label}
                if doc_date:
                    metadata["date"] = doc_date

                for i, chunk in enumerate(chunks):
                    chunk_name = f"{title}_chunk_{i+1}" if len(chunks) > 1 else title
                    bg_print(f"   → adding chunk {i+1}/{len(chunks)}: {chunk_name} [hybrid]")
                    try:
                        chunk_metadata = {**metadata}
                        if len(chunks) > 1:
                            chunk_metadata["chunk"] = i + 1
                        store.add_document(
                            text=chunk,
                            metadata=chunk_metadata,
                            doc_id=f"{msg_id}_{i}" if len(chunks) > 1 else msg_id
                        )
                    except Exception as e:
                        bg_print(f"   ✗ Error adding chunk to hybrid store: {e}")

                # 6) Build graph and write to Memgraph (use English text)
                bg_print("   → extracting graph + writing to Memgraph...")
                write_doc_graph_to_memgraph(
                    text=md_text_en,
                    file_name=title,
                    user_id=self.user_id,
                    doc_label=doc_label,
                    upload_time=upload_time,
                )

                bg_print("   ✅ Done\n")
            except Exception as e:
                bg_print("   ❌ Error processing message:")
                traceback.print_exc()

        self.channel.basic_consume(
            queue=self.config.queue_name, on_message_callback=callback
        )
        bg_print(f"🚀 RabbitMQ: Waiting for messages in '{self.config.queue_name}'...\n")
        self.channel.start_consuming()

    def run(self):
        """Main loop with automatic reconnection."""
        while not self._stopping:
            if not self.connect():
                bg_print(f"⏳ RabbitMQ: Reconnecting in {self.config.reconnect_delay} sec...")
                time.sleep(self.config.reconnect_delay)
                continue
            try:
                self.start_consuming()
            except KeyboardInterrupt:
                break
            except pika.exceptions.AMQPConnectionError:
                bg_print("🔄 RabbitMQ: Connection lost, reconnecting...")
                continue
            except Exception as e:
                bg_print(f"❌ RabbitMQ: Unexpected error: {e}")
                time.sleep(self.config.reconnect_delay)
        self.stop()

    def stop(self):
        """Graceful stop."""
        self._stopping = True
        try:
            if self.channel:
                self.channel.stop_consuming()
                self.channel.close()
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except Exception:
            pass
        bg_print("✅ RabbitMQ: Confluence consumer stopped")

```

### ./metatron/consumers/jira.py
```python
"""
RabbitMQ consumer for Jira issues.
"""
import json
import time
import traceback

import pika

from metatron.consumers.base import RabbitMQConfig
from metatron.utils import bg_print, chunk_text, build_doc_label
from metatron.processing import extract_date_from_text, translate_to_english
from metatron.indexers import write_jira_graph_to_memgraph, get_hybrid_store

# Import Jira processing from existing module
from get_data_from_rabbitmq import process_jira_message, jira_to_markdown


class JiraConsumer:
    """
    RabbitMQ consumer for Jira issues.
    
    For each message:
    - Parse JSON via process_jira_message
    - Convert to markdown for mem0
    - Add to mem0 (vector + embeddings)
    - Write graph (entities/relations) to Memgraph
    """

    def __init__(self, config: RabbitMQConfig, user_id: str = "user"):
        self.config = config
        self.connection = None
        self.channel = None
        self._stopping = False
        self.user_id = user_id
        self._processed_ids: set[str] = set()

    def _get_message_id(self, body: bytes) -> str:
        """Extract unique message ID for deduplication."""
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                return data.get("key", "") or data.get("id", "") or str(hash(body))
        except Exception:
            pass
        return str(hash(body))

    def connect(self) -> bool:
        """Connect to RabbitMQ."""
        try:
            credentials = pika.PlainCredentials(
                username=self.config.username,
                password=self.config.password,
            )
            parameters = pika.ConnectionParameters(
                host=self.config.host,
                port=self.config.port,
                virtual_host=self.config.virtual_host,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300,
            )
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            self.channel.basic_qos(prefetch_count=self.config.prefetch_count)
            self.channel.queue_declare(
                queue=self.config.queue_name,
                durable=True,
                arguments={"x-queue-type": "classic"},
            )
            bg_print(f"✅ RabbitMQ: Jira consumer connected to {self.config.host}:{self.config.port}")
            bg_print(f"   Queue: {self.config.queue_name} (classic, durable)")
            return True
        except Exception as e:
            bg_print(f"❌ RabbitMQ: Jira consumer connection error: {e}")
            return False

    def start_consuming(self):
        """Start consuming messages from RabbitMQ."""
        store = get_hybrid_store()
        
        def callback(ch, method, properties, body):
            msg_id = self._get_message_id(body)
            
            # Deduplication
            if msg_id in self._processed_ids:
                bg_print(f"   ⏭️ Skipping duplicate Jira: {msg_id}")
                try:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    pass
                return
            
            # ACK immediately to avoid requeue on connection loss
            try:
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                bg_print(f"   ⚠️ ACK failed, continuing: {e}")
            
            self._processed_ids.add(msg_id)
            
            try:
                # 1) Parse Jira issue
                jira_data = process_jira_message(body)
                issue_key = jira_data.get("key", "UNKNOWN")
                summary = jira_data.get("summary", "")
                bg_print(f"\n📋 RabbitMQ: Jira issue: {issue_key} - {summary}")

                # 2) Convert to markdown
                md_text = jira_to_markdown(jira_data)
                doc_name = f"JIRA_{issue_key}"

                # 3) Extract creation date for metadata
                created = jira_data.get("created", "")
                jira_date = extract_date_from_text(created) if created else None
                
                doc_label, upload_time = build_doc_label(
                    source_id=issue_key,
                    user_id=self.user_id,
                )

                metadata = {
                    "title": doc_name,
                    "issue_key": issue_key,
                    "type": "jira",
                    "doc_label": doc_label,
                }
                if jira_date:
                    metadata["date"] = jira_date

                # 4) Translate to English for embedding
                bg_print(f"   → translating to English...")
                md_text_en = translate_to_english(md_text)

                # 5) Add to hybrid store (dense + BM25 sparse vectors)
                chunks = chunk_text(md_text_en, max_chars=2500, overlap=200)

                for i, chunk in enumerate(chunks):
                    chunk_name = f"{doc_name}_chunk_{i+1}" if len(chunks) > 1 else doc_name
                    bg_print(f"   → adding chunk {i+1}/{len(chunks)}: {chunk_name} [hybrid]")
                    try:
                        chunk_metadata = {**metadata}
                        if len(chunks) > 1:
                            chunk_metadata["chunk"] = i + 1
                        store.add_document(
                            text=chunk,
                            metadata=chunk_metadata,
                            doc_id=f"{issue_key}_{i}" if len(chunks) > 1 else issue_key
                        )
                    except Exception as e:
                        bg_print(f"   ✗ Error adding chunk to hybrid store: {e}")

                # 6) Build graph and write to Memgraph (use English text)
                bg_print("   → extracting graph + writing to Memgraph...")
                write_jira_graph_to_memgraph(
                    jira_data=jira_data,
                    markdown_text=md_text_en,
                    user_id=self.user_id,
                    doc_label=doc_label,
                    upload_time=upload_time,
                )

                bg_print("   ✅ Done\n")
            except Exception as e:
                bg_print("   ❌ Error processing Jira message:")
                traceback.print_exc()

        self.channel.basic_consume(
            queue=self.config.queue_name, on_message_callback=callback
        )
        bg_print(f"🚀 RabbitMQ: Waiting for Jira issues in '{self.config.queue_name}'...\n")
        self.channel.start_consuming()

    def run(self):
        """Main loop with automatic reconnection."""
        while not self._stopping:
            if not self.connect():
                bg_print(f"⏳ RabbitMQ: Jira consumer reconnecting in {self.config.reconnect_delay} sec...")
                time.sleep(self.config.reconnect_delay)
                continue
            try:
                self.start_consuming()
            except KeyboardInterrupt:
                break
            except pika.exceptions.AMQPConnectionError:
                bg_print("🔄 RabbitMQ: Jira consumer connection lost, reconnecting...")
                continue
            except Exception as e:
                bg_print(f"❌ RabbitMQ: Jira consumer unexpected error: {e}")
                time.sleep(self.config.reconnect_delay)
        self.stop()

    def stop(self):
        """Graceful stop."""
        self._stopping = True
        try:
            if self.channel:
                self.channel.stop_consuming()
                self.channel.close()
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except Exception:
            pass
        bg_print("✅ RabbitMQ: Jira consumer stopped")

```

### ./metatron/db/__init__.py
```python
"""
Database connection management for Metatron.
"""
from .memgraph import get_memgraph_driver, close_memgraph_driver
from .cleanup import (
    cleanup_workspace,
    cleanup_all,
    get_cleanup_preview,
    CleanupError,
)

__all__ = [
    "get_memgraph_driver",
    "close_memgraph_driver",
    "cleanup_workspace",
    "cleanup_all",
    "get_cleanup_preview",
    "CleanupError",
]
```

### ./metatron/db/cleanup.py
```python
"""
Database cleanup utilities for Metatron.

Provides functions to clear data from Qdrant and Memgraph databases,
either for a specific workspace or all data.

Safety features:
- Requires explicit confirmation
- ALLOW_CLEANUP env var must be true in production
- All operations are logged

Usage:
    from metatron.db.cleanup import cleanup_workspace, cleanup_all

    # Clear specific workspace
    cleanup_workspace("ws_123")

    # Clear all data
    cleanup_all(confirm=True)
"""
import os
from typing import Dict, List, Optional

from qdrant_client import QdrantClient

from metatron.config import (
    QDRANT_HOST,
    QDRANT_PORT,
    DEFAULT_WORKSPACE_ID,
    setup_logging,
)
from metatron.db.memgraph import get_memgraph_driver

logger = setup_logging(__name__)

# Safety: require explicit env var to allow cleanup in production
ALLOW_CLEANUP = os.getenv("ALLOW_CLEANUP", "false").lower() == "true"


class CleanupError(Exception):
    """Error during cleanup operation."""
    pass


def _check_cleanup_allowed() -> None:
    """Check if cleanup is allowed in current environment."""
    if not ALLOW_CLEANUP:
        raise CleanupError(
            "Cleanup is disabled. Set ALLOW_CLEANUP=true to enable. "
            "WARNING: This will permanently delete data!"
        )


def get_qdrant_client() -> QdrantClient:
    """Get Qdrant client instance."""
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60)


def list_qdrant_collections() -> List[str]:
    """List all Qdrant collections."""
    client = get_qdrant_client()
    collections = client.get_collections().collections
    return [c.name for c in collections]


def cleanup_qdrant_workspace(workspace_id: str) -> Dict:
    """
    Delete Qdrant collection for a specific workspace.

    Args:
        workspace_id: Workspace identifier

    Returns:
        Dict with status and details
    """
    from metatron.indexers.hybrid_store_workspace import get_collection_name

    collection_name = get_collection_name(workspace_id)
    client = get_qdrant_client()

    try:
        # Check if collection exists
        collections = [c.name for c in client.get_collections().collections]
        if collection_name not in collections:
            return {
                "status": "skipped",
                "collection": collection_name,
                "reason": "Collection does not exist"
            }

        # Get point count before deletion
        info = client.get_collection(collection_name)
        points_count = info.points_count

        # Delete collection
        client.delete_collection(collection_name)
        logger.info(f"Deleted Qdrant collection '{collection_name}' ({points_count} points)")

        return {
            "status": "deleted",
            "collection": collection_name,
            "points_deleted": points_count
        }
    except Exception as e:
        logger.error(f"Error deleting Qdrant collection '{collection_name}': {e}")
        return {
            "status": "error",
            "collection": collection_name,
            "error": str(e)
        }


def cleanup_qdrant_all() -> Dict:
    """
    Delete ALL Qdrant collections (metatron-related).

    Returns:
        Dict with status and details for each collection
    """
    client = get_qdrant_client()
    collections = list_qdrant_collections()

    # Filter to only metatron collections (mem_docs_hybrid*)
    metatron_collections = [c for c in collections if c.startswith("mem_docs_hybrid")]

    results = []
    total_points = 0

    for collection_name in metatron_collections:
        try:
            info = client.get_collection(collection_name)
            points_count = info.points_count
            total_points += points_count

            client.delete_collection(collection_name)
            logger.info(f"Deleted Qdrant collection '{collection_name}' ({points_count} points)")

            results.append({
                "collection": collection_name,
                "status": "deleted",
                "points_deleted": points_count
            })
        except Exception as e:
            logger.error(f"Error deleting collection '{collection_name}': {e}")
            results.append({
                "collection": collection_name,
                "status": "error",
                "error": str(e)
            })

    return {
        "status": "completed",
        "collections_deleted": len([r for r in results if r["status"] == "deleted"]),
        "total_points_deleted": total_points,
        "details": results
    }


def cleanup_memgraph_workspace(workspace_id: str) -> Dict:
    """
    Delete all Memgraph nodes and relationships for a specific workspace.

    Args:
        workspace_id: Workspace identifier

    Returns:
        Dict with status and details
    """
    driver = get_memgraph_driver()

    try:
        with driver.session() as session:
            # Count before deletion
            result = session.run(
                """
                MATCH (n)
                WHERE n.workspace_id = $workspace_id
                RETURN count(n) AS node_count
                """,
                {"workspace_id": workspace_id}
            )
            node_count = result.single()["node_count"]

            if node_count == 0:
                return {
                    "status": "skipped",
                    "workspace_id": workspace_id,
                    "reason": "No nodes found for workspace"
                }

            # Delete all nodes and relationships for workspace
            # DETACH DELETE removes the node and all its relationships
            session.run(
                """
                MATCH (n)
                WHERE n.workspace_id = $workspace_id
                DETACH DELETE n
                """,
                {"workspace_id": workspace_id}
            )

            logger.info(f"Deleted {node_count} Memgraph nodes for workspace '{workspace_id}'")

            return {
                "status": "deleted",
                "workspace_id": workspace_id,
                "nodes_deleted": node_count
            }
    except Exception as e:
        logger.error(f"Error deleting Memgraph data for workspace '{workspace_id}': {e}")
        return {
            "status": "error",
            "workspace_id": workspace_id,
            "error": str(e)
        }


def cleanup_memgraph_all() -> Dict:
    """
    Delete ALL nodes and relationships from Memgraph.

    Returns:
        Dict with status and details
    """
    driver = get_memgraph_driver()

    try:
        with driver.session() as session:
            # Count before deletion
            result = session.run("MATCH (n) RETURN count(n) AS node_count")
            node_count = result.single()["node_count"]

            result = session.run("MATCH ()-[r]->() RETURN count(r) AS rel_count")
            rel_count = result.single()["rel_count"]

            if node_count == 0:
                return {
                    "status": "skipped",
                    "reason": "Database is already empty"
                }

            # Delete all nodes and relationships
            session.run("MATCH (n) DETACH DELETE n")

            logger.info(f"Deleted all Memgraph data: {node_count} nodes, {rel_count} relationships")

            return {
                "status": "deleted",
                "nodes_deleted": node_count,
                "relationships_deleted": rel_count
            }
    except Exception as e:
        logger.error(f"Error deleting all Memgraph data: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def cleanup_workspace(workspace_id: str, confirm: bool = False) -> Dict:
    """
    Clean up all data for a specific workspace (Qdrant + Memgraph).

    Args:
        workspace_id: Workspace identifier
        confirm: Must be True to actually perform cleanup

    Returns:
        Dict with status and details

    Raises:
        CleanupError: If cleanup is not allowed or not confirmed
    """
    _check_cleanup_allowed()

    if not confirm:
        raise CleanupError("Cleanup requires confirm=True")

    if not workspace_id:
        raise CleanupError("workspace_id is required")

    logger.warning(f"Starting cleanup for workspace '{workspace_id}'...")

    results = {
        "workspace_id": workspace_id,
        "qdrant": cleanup_qdrant_workspace(workspace_id),
        "memgraph": cleanup_memgraph_workspace(workspace_id),
    }

    # Determine overall status
    statuses = [results["qdrant"]["status"], results["memgraph"]["status"]]
    if "error" in statuses:
        results["status"] = "partial"
    elif all(s == "skipped" for s in statuses):
        results["status"] = "skipped"
    else:
        results["status"] = "completed"

    logger.info(f"Cleanup for workspace '{workspace_id}' completed: {results['status']}")
    return results


def cleanup_all(confirm: bool = False) -> Dict:
    """
    Clean up ALL data from all databases (Qdrant + Memgraph).

    WARNING: This will permanently delete ALL data!

    Args:
        confirm: Must be True to actually perform cleanup

    Returns:
        Dict with status and details

    Raises:
        CleanupError: If cleanup is not allowed or not confirmed
    """
    _check_cleanup_allowed()

    if not confirm:
        raise CleanupError(
            "Full cleanup requires confirm=True. "
            "WARNING: This will delete ALL data from ALL workspaces!"
        )

    logger.warning("Starting FULL cleanup of all databases...")

    results = {
        "qdrant": cleanup_qdrant_all(),
        "memgraph": cleanup_memgraph_all(),
    }

    # Clear workspace manager cache
    try:
        from metatron.workspaces import get_workspace_manager
        manager = get_workspace_manager()
        # Reset to only default workspace
        manager._workspaces = {}
        manager._ensure_default_workspace()
        results["workspaces"] = {"status": "reset", "message": "Workspace cache cleared"}
        logger.info("Workspace manager cache cleared")
    except Exception as e:
        logger.error(f"Error clearing workspace cache: {e}")
        results["workspaces"] = {"status": "error", "error": str(e)}

    # Clear hybrid store cache
    try:
        from metatron.indexers.hybrid_store_workspace import clear_store_cache
        clear_store_cache()
        results["store_cache"] = {"status": "cleared"}
        logger.info("Hybrid store cache cleared")
    except Exception as e:
        logger.error(f"Error clearing store cache: {e}")
        results["store_cache"] = {"status": "error", "error": str(e)}

    # Determine overall status
    if results["qdrant"]["status"] == "error" or results["memgraph"]["status"] == "error":
        results["status"] = "partial"
    else:
        results["status"] = "completed"

    logger.warning(f"FULL cleanup completed: {results['status']}")
    return results


def get_cleanup_preview() -> Dict:
    """
    Get preview of what would be deleted (dry run).

    Returns:
        Dict with counts of data that would be deleted
    """
    preview = {
        "qdrant": {"collections": [], "total_points": 0},
        "memgraph": {"nodes": 0, "relationships": 0, "workspaces": []},
    }

    # Qdrant preview
    try:
        client = get_qdrant_client()
        collections = list_qdrant_collections()
        metatron_collections = [c for c in collections if c.startswith("mem_docs_hybrid")]

        for collection_name in metatron_collections:
            try:
                info = client.get_collection(collection_name)
                preview["qdrant"]["collections"].append({
                    "name": collection_name,
                    "points": info.points_count
                })
                preview["qdrant"]["total_points"] += info.points_count
            except Exception:
                pass
    except Exception as e:
        preview["qdrant"]["error"] = str(e)

    # Memgraph preview
    try:
        driver = get_memgraph_driver()
        with driver.session() as session:
            # Total counts
            result = session.run("MATCH (n) RETURN count(n) AS count")
            preview["memgraph"]["nodes"] = result.single()["count"]

            result = session.run("MATCH ()-[r]->() RETURN count(r) AS count")
            preview["memgraph"]["relationships"] = result.single()["count"]

            # Per-workspace counts
            result = session.run(
                """
                MATCH (n)
                WHERE n.workspace_id IS NOT NULL
                RETURN n.workspace_id AS workspace_id, count(n) AS count
                ORDER BY count DESC
                """
            )
            for record in result:
                preview["memgraph"]["workspaces"].append({
                    "workspace_id": record["workspace_id"],
                    "nodes": record["count"]
                })
    except Exception as e:
        preview["memgraph"]["error"] = str(e)

    preview["cleanup_allowed"] = ALLOW_CLEANUP
    return preview
```

### ./metatron/db/memgraph.py
```python
"""
Memgraph/Neo4j connection management.

Provides a singleton driver with connection pooling to avoid
creating new TCP connections for each operation.

Usage:
    from metatron.db import get_memgraph_driver

    driver = get_memgraph_driver()
    with driver.session() as session:
        result = session.run("MATCH (n) RETURN n LIMIT 10")
        ...

    # Driver is reused across all calls - no need to close after each use
    # Call close_memgraph_driver() only on application shutdown
"""
import atexit
from threading import Lock

from neo4j import GraphDatabase

from metatron.config import (
    MEMGRAPH_URI,
    MEMGRAPH_USER,
    MEMGRAPH_PASS,
    setup_logging,
)

logger = setup_logging(__name__)

_driver = None
_driver_lock = Lock()


def get_memgraph_driver():
    """
    Get shared Memgraph/Neo4j driver instance.

    Creates driver on first call with connection pooling configured.
    Subsequent calls return the same driver instance.

    Returns:
        Neo4j driver instance

    Example:
        driver = get_memgraph_driver()
        with driver.session() as session:
            session.run("MATCH (n) RETURN count(n)")
    """
    global _driver

    if _driver is None:
        with _driver_lock:
            if _driver is None:
                _driver = GraphDatabase.driver(
                    MEMGRAPH_URI,
                    auth=(MEMGRAPH_USER, MEMGRAPH_PASS),
                    max_connection_pool_size=50,
                    connection_acquisition_timeout=30,
                )
                logger.info(f"Memgraph driver initialized: {MEMGRAPH_URI} (pool_size=50)")

    return _driver


def close_memgraph_driver() -> None:
    """
    Close the shared Memgraph driver.

    Call this on application shutdown to cleanly close all connections.
    After calling this, get_memgraph_driver() will create a new driver.
    """
    global _driver

    if _driver is not None:
        with _driver_lock:
            if _driver is not None:
                _driver.close()
                _driver = None
                logger.info("Memgraph driver closed")


# Register cleanup on interpreter exit
atexit.register(close_memgraph_driver)
```

### ./metatron/indexers/__init__.py
```python
"""
Document indexers for Qdrant and Memgraph.

All indexers are workspace-aware, supporting multi-tenant data isolation.
"""
from metatron.indexers.memgraph_workspace import (
    extract_graph_from_text,
    write_doc_graph_to_memgraph,
    write_jira_graph_to_memgraph,
    get_graph_entities,
    get_entities_by_doc_labels,
    get_all_workspace_entities,
    get_graph_relationships,
    get_doc_labels_by_entities,
    get_related_documents,
    delete_workspace_graph,
)
from metatron.indexers.hybrid_store_workspace import (
    HybridVectorStore,
    get_hybrid_store,
    BASE_COLLECTION_NAME as HYBRID_COLLECTION_NAME,
)
from metatron.indexers.bm25 import (
    compute_bm25_sparse_vector,
    compute_query_sparse_vector,
    tokenize,
)

__all__ = [
    # Graph operations (workspace-aware)
    "extract_graph_from_text",
    "write_doc_graph_to_memgraph",
    "write_jira_graph_to_memgraph",
    "get_graph_entities",
    "get_entities_by_doc_labels",
    "get_all_workspace_entities",
    "get_graph_relationships",
    "get_doc_labels_by_entities",
    "get_related_documents",
    "delete_workspace_graph",
    # Hybrid search (workspace-aware)
    "HybridVectorStore",
    "get_hybrid_store",
    "HYBRID_COLLECTION_NAME",
    # BM25
    "compute_bm25_sparse_vector",
    "compute_query_sparse_vector",
    "tokenize",
]
```

### ./metatron/indexers/bm25.py
```python
"""
BM25 Sparse Vector generation for Qdrant hybrid search.

BM25 (Best Matching 25) is a ranking function used in information retrieval.
This module generates sparse vectors compatible with Qdrant's sparse vector search.
"""
import re
import math
from collections import Counter
from typing import Dict, List, Tuple

# Simple tokenizer that handles English and transliterated text
def tokenize(text: str) -> List[str]:
    """
    Tokenize text into words.
    Handles English text, removes punctuation, lowercases.
    """
    # Lowercase
    text = text.lower()
    # Remove special characters, keep only alphanumeric and spaces
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Split into words
    words = text.split()
    # Filter short words and stopwords
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
        'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
        'would', 'could', 'should', 'may', 'might', 'must', 'shall', 'can',
        'this', 'that', 'these', 'those', 'it', 'its', 'i', 'me', 'my', 'we',
        'our', 'you', 'your', 'he', 'him', 'his', 'she', 'her', 'they', 'them',
        'their', 'what', 'which', 'who', 'whom', 'when', 'where', 'why', 'how',
        'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some',
        'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too',
        'very', 'just', 'also', 'now', 'here', 'there', 'then', 'once'
    }
    return [w for w in words if len(w) > 2 and w not in stopwords]


# Vocabulary for consistent hashing (use large prime for less collisions)
VOCAB_SIZE = 30000


def word_to_index(word: str) -> int:
    """Convert word to index using hash."""
    return hash(word) % VOCAB_SIZE


def compute_bm25_sparse_vector(
    text: str,
    k1: float = 1.5,
    b: float = 0.75,
    avgdl: float = 256.0,
) -> Tuple[List[int], List[float]]:
    """
    Compute BM25 sparse vector for a document.
    
    Args:
        text: Document text
        k1: Term frequency saturation parameter (default 1.5)
        b: Length normalization parameter (default 0.75)
        avgdl: Average document length (default 256 tokens)
        
    Returns:
        Tuple of (indices, values) for sparse vector
    """
    tokens = tokenize(text)
    if not tokens:
        return [], []
    
    doc_len = len(tokens)
    term_freqs = Counter(tokens)
    
    indices = []
    values = []
    
    # Use dict to aggregate values for hash collisions
    index_values: Dict[int, float] = {}

    for term, freq in term_freqs.items():
        # BM25 term frequency component
        tf_component = (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * doc_len / avgdl))

        # We don't have IDF (corpus-level), so use just TF component
        # IDF would require knowing document frequencies across all docs
        # For sparse vectors, TF is sufficient for keyword matching

        idx = word_to_index(term)
        # Aggregate values if hash collision (different words -> same index)
        index_values[idx] = index_values.get(idx, 0.0) + float(tf_component)

    indices = list(index_values.keys())
    values = list(index_values.values())

    return indices, values


def compute_query_sparse_vector(query: str) -> Tuple[List[int], List[float]]:
    """
    Compute sparse vector for a query.
    Queries use simpler weighting (just presence).
    
    Args:
        query: Search query
        
    Returns:
        Tuple of (indices, values) for sparse vector
    """
    tokens = tokenize(query)
    if not tokens:
        return [], []
    
    # For queries, we just use term presence with equal weights
    term_freqs = Counter(tokens)

    # Use dict to aggregate values for hash collisions
    index_values: Dict[int, float] = {}

    for term, freq in term_freqs.items():
        idx = word_to_index(term)
        # Query terms all get weight 1.0 (or freq if repeated)
        # Aggregate values if hash collision
        index_values[idx] = index_values.get(idx, 0.0) + float(freq)

    indices = list(index_values.keys())
    values = list(index_values.values())

    return indices, values


# For Qdrant SparseVector format
def to_qdrant_sparse(indices: List[int], values: List[float]) -> dict:
    """Convert to Qdrant SparseVector format."""
    return {"indices": indices, "values": values}

```

### ./metatron/indexers/hybrid_store_workspace.py
```python
"""
Hybrid Vector Store for Qdrant with Workspace Support.

This module provides a workspace-aware indexer that creates separate Qdrant collections
for each workspace, enabling complete data isolation between different datasets.
"""
import uuid
from threading import Lock
from typing import List, Dict, Optional, Any

from qdrant_client import QdrantClient

from qdrant_client.models import (
    VectorParams,
    SparseVectorParams,
    Distance,
    PointStruct,
    SparseVector,
    Prefetch,
    FusionQuery,
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
)

from metatron.config import QDRANT_HOST, QDRANT_PORT, DEFAULT_WORKSPACE_ID, setup_logging
from metatron.indexers.bm25 import compute_bm25_sparse_vector, compute_query_sparse_vector
from metatron.utils import normalize_workspace_id, get_cached_embedding

logger = setup_logging(__name__)


# Base collection name (without workspace suffix)
BASE_COLLECTION_NAME = "mem_docs_hybrid"
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "bm25"
DENSE_DIM = 768  # nomic-embed-text dimensions


def get_collection_name(workspace_id: str = None) -> str:
    """
    Get Qdrant collection name for a workspace.

    Args:
        workspace_id: Workspace identifier (None or "default" uses DEFAULT_WORKSPACE_ID)

    Returns:
        Collection name

    Note:
        For backward compatibility, the default workspace uses the original
        collection name without suffix (mem_docs_hybrid).
    """
    workspace_id = normalize_workspace_id(workspace_id)
    # Default workspace uses base collection for backward compatibility
    if workspace_id == DEFAULT_WORKSPACE_ID:
        return BASE_COLLECTION_NAME
    return f"{BASE_COLLECTION_NAME}_{workspace_id}"


class HybridVectorStore:
    """
    Workspace-aware hybrid vector store combining dense (semantic) and sparse (BM25) vectors.
    Each workspace gets its own Qdrant collection for complete data isolation.
    """
    
    def __init__(self, workspace_id: str = None):
        """
        Initialize hybrid vector store for a specific workspace.

        Args:
            workspace_id: Workspace identifier (None uses DEFAULT_WORKSPACE_ID)
        """
        self.workspace_id = workspace_id or DEFAULT_WORKSPACE_ID
        self.collection_name = get_collection_name(workspace_id)
        self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60)
        self._ensure_collection()
    
    def _ensure_collection(self):
        """Create collection if it doesn't exist with hybrid vector config."""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        
        if not exists:
            logger.info(f"Creating hybrid collection for workspace '{self.workspace_id}': {self.collection_name}")
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    DENSE_VECTOR_NAME: VectorParams(
                        size=DENSE_DIM,
                        distance=Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: SparseVectorParams()
                }
            )
            logger.info(f"Collection created with dense ({DENSE_DIM}d) + sparse (BM25) vectors")
        else:
            logger.debug(f"Collection exists for workspace '{self.workspace_id}': {self.collection_name}")
    
    def get_dense_embedding(self, text: str) -> List[float]:
        """Get dense embedding from Ollama with caching."""
        return get_cached_embedding(text)

    def _format_result(self, point, score: float) -> Dict:
        payload = point.payload or {}
        data = payload.get("data") or payload.get("memory") or ""
        return {
            "id": str(point.id),
            "score": score,
            "memory": data,
            "data": data,
            "title": payload.get("title", ""),
            "type": payload.get("type", ""),
            "date": payload.get("date", ""),
            "doc_label": payload.get("doc_label", ""),
            "workspace_id": payload.get("workspace_id", ""),
            "payload": payload,
        }
    
    def add_document(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None
    ) -> str:
        """
        Add document with both dense and sparse vectors to workspace collection.
        
        Args:
            text: Document text
            metadata: Optional metadata dict (title, date, type, etc.)
            doc_id: Optional document ID (stored in metadata, UUID generated for Qdrant)
            
        Returns:
            Document ID (UUID)
        """
        # Qdrant requires UUID for point IDs
        qdrant_id = str(uuid.uuid4())
        
        # Store original doc_id in metadata for reference
        if doc_id is not None:
            if metadata is None:
                metadata = {}
            metadata["original_id"] = doc_id
        
        # Add workspace_id to metadata for tracking
        if metadata is None:
            metadata = {}
        metadata["workspace_id"] = self.workspace_id
        
        # Generate dense embedding
        dense_vector = self.get_dense_embedding(text)
        
        # Generate sparse BM25 vector
        sparse_indices, sparse_values = compute_bm25_sparse_vector(text)
        
        # Build payload
        payload = metadata or {}
        payload["data"] = text
        payload["memory"] = text  # For compatibility with existing code
        
        # Create point with named vectors
        point = PointStruct(
            id=qdrant_id,  # Use UUID for Qdrant
            vector={
                DENSE_VECTOR_NAME: dense_vector,
                SPARSE_VECTOR_NAME: SparseVector(
                    indices=sparse_indices,
                    values=sparse_values
                )
            },
            payload=payload
        )
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=[point]
        )
        
        return qdrant_id
    
    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        filter_conditions: Optional[Filter] = None,
        dense_weight: float = 0.7,
        sparse_weight: float = 0.3
    ) -> List[Dict]:
        """
        Hybrid search combining dense (semantic) and sparse (BM25) vectors.
        Uses Reciprocal Rank Fusion (RRF) to combine results.
        
        Args:
            query: Search query
            limit: Number of results
            filter_conditions: Optional Qdrant filter
            dense_weight: Weight for dense vector results (0-1)
            sparse_weight: Weight for sparse vector results (0-1)
            
        Returns:
            List of search results with payload
        """
        # Get query vectors
        dense_query = self.get_dense_embedding(query)
        sparse_indices, sparse_values = compute_query_sparse_vector(query)
        
        # Use prefetch + fusion for hybrid search
        try:
            results = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    Prefetch(
                        query=dense_query,
                        using=DENSE_VECTOR_NAME,
                        limit=limit * 3,  # Overfetch for fusion
                        filter=filter_conditions
                    ),
                    Prefetch(
                        query=SparseVector(indices=sparse_indices, values=sparse_values),
                        using=SPARSE_VECTOR_NAME,
                        limit=limit * 3,
                        filter=filter_conditions
                    )
                ],
                query=FusionQuery(fusion="rrf"),  # Reciprocal Rank Fusion
                limit=limit,
                with_payload=True
            )
            
            return [
                self._format_result(point, point.score)
                for point in results.points
            ]
        except Exception as e:
            logger.warning(f"Hybrid search error for workspace '{self.workspace_id}': {e}, falling back to dense search")
            # Fallback to dense-only search
            return self.dense_search(query, limit=limit, filter_conditions=filter_conditions)
    
    def dense_search(
        self,
        query: str,
        limit: int = 10,
        filter_conditions: Optional[Filter] = None
    ) -> List[Dict]:
        """Fallback: dense-only search."""
        dense_query = self.get_dense_embedding(query)

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=dense_query,
            using=DENSE_VECTOR_NAME,
            limit=limit,
            query_filter=filter_conditions,
            with_payload=True
        )

        return [
            self._format_result(point, point.score)
            for point in results.points
        ]
    
    def keyword_search(
        self,
        query: str,
        limit: int = 10,
        filter_conditions: Optional[Filter] = None
    ) -> List[Dict]:
        """Sparse-only (keyword/BM25) search."""
        sparse_indices, sparse_values = compute_query_sparse_vector(query)

        if not sparse_indices:
            return []

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=SparseVector(indices=sparse_indices, values=sparse_values),
            using=SPARSE_VECTOR_NAME,
            limit=limit,
            query_filter=filter_conditions,
            with_payload=True
        )

        return [
            self._format_result(point, point.score)
            for point in results.points
        ]
    
    def search_by_date(self, dates: List[str], limit: int = 10) -> List[Dict]:
        """Search by date filter using MatchAny (more efficient than multiple MatchValue)."""
        if not dates:
            return []

        # Use MatchAny instead of multiple should[MatchValue] conditions
        # This is more efficient for date ranges
        filter_cond = Filter(
            must=[
                FieldCondition(
                    key="date",
                    match=MatchAny(any=dates)
                )
            ]
        )
        
        results, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=filter_cond,
            limit=limit,
            with_payload=True,
            with_vectors=False
        )
        
        return [
            self._format_result(point, 1.0)
            for point in results
        ]
    
    def search_by_type(self, doc_type: str, limit: int = 10) -> List[Dict]:
        """Search by document type filter."""
        filter_cond = Filter(
            must=[FieldCondition(key="type", match=MatchValue(value=doc_type))]
        )
        
        results, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=filter_cond,
            limit=limit,
            with_payload=True,
            with_vectors=False
        )
        
        return [
            self._format_result(point, 1.0)
            for point in results
        ]

    def search_by_doc_labels(self, doc_labels: List[str], limit: int = 10) -> List[Dict]:
        """Search by document label filter."""
        labels = [label for label in doc_labels if label]
        if not labels:
            return []

        match = MatchAny(any=labels) if len(labels) > 1 else MatchValue(value=labels[0])
        filter_cond = Filter(
            must=[FieldCondition(key="doc_label", match=match)]
        )

        results, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=filter_cond,
            limit=limit,
            with_payload=True,
            with_vectors=False
        )

        return [self._format_result(point, 1.0) for point in results]
    
    def get_collection_info(self) -> Dict:
        """Get collection statistics."""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "workspace_id": self.workspace_id,
                "points_count": info.points_count,
                "status": str(info.status)
            }
        except Exception as e:
            logger.error(f"Error getting collection info for workspace '{self.workspace_id}': {e}")
            return {
                "name": self.collection_name,
                "workspace_id": self.workspace_id,
                "points_count": 0,
                "status": "error"
            }

    def get_stats(self) -> Dict:
        """
        Get detailed statistics: chunk count and unique file count.

        Returns:
            Dict with chunk_count and file_count
        """
        try:
            info = self.client.get_collection(self.collection_name)
            chunk_count = info.points_count

            # Get unique titles (files)
            file_count = 0
            if chunk_count > 0:
                titles = set()
                offset = None
                while True:
                    results, offset = self.client.scroll(
                        collection_name=self.collection_name,
                        limit=100,
                        offset=offset,
                        with_payload=["title"],
                    )
                    for point in results:
                        title = point.payload.get("title")
                        if title:
                            titles.add(title)
                    if offset is None:
                        break
                file_count = len(titles)

            return {
                "chunk_count": chunk_count,
                "file_count": file_count,
            }
        except Exception as e:
            logger.error(f"Error getting stats for workspace '{self.workspace_id}': {e}")
            return {
                "chunk_count": 0,
                "file_count": 0,
            }

    def clear(self):
        """Delete and recreate collection for this workspace."""
        try:
            self.client.delete_collection(self.collection_name)
            logger.info(f"Collection {self.collection_name} deleted")
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")

        self._ensure_collection()
        logger.info(f"Collection {self.collection_name} recreated")
    
    def delete(self):
        """
        Delete the collection for this workspace.

        Note: This is permanent and cannot be undone.
        Use with caution!
        """
        try:
            self.client.delete_collection(self.collection_name)
            logger.info(f"Collection {self.collection_name} deleted permanently")
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")


# Global instances per workspace
_hybrid_stores: Dict[str, HybridVectorStore] = {}
_store_lock = Lock()  # Initialize at module level to avoid race condition


def get_hybrid_store(workspace_id: str = None) -> HybridVectorStore:
    """
    Get or create HybridVectorStore instance for a workspace.

    Args:
        workspace_id: Workspace identifier (None uses DEFAULT_WORKSPACE_ID)

    Returns:
        HybridVectorStore instance for the workspace
    """
    global _hybrid_stores

    workspace_id = normalize_workspace_id(workspace_id)

    if workspace_id not in _hybrid_stores:
        with _store_lock:
            # Double-check locking pattern
            if workspace_id not in _hybrid_stores:
                _hybrid_stores[workspace_id] = HybridVectorStore(workspace_id)

    return _hybrid_stores[workspace_id]


def clear_store_cache():
    """Clear all cached HybridVectorStore instances."""
    global _hybrid_stores
    _hybrid_stores = {}
```

### ./metatron/indexers/memgraph_workspace.py
```python
"""
Memgraph graph database indexer with Workspace Support.

This module provides workspace-aware graph operations that add workspace_id
to all nodes and relationships, enabling complete data isolation between workspaces.
"""
import json
from datetime import datetime, UTC
from typing import List, Dict, Optional

from metatron.config import DEFAULT_WORKSPACE_ID, setup_logging
from metatron.db import get_memgraph_driver
from metatron.llm import chat_completion
from metatron.utils import bg_print, normalize_workspace_id, build_doc_label

logger = setup_logging(__name__)


def extract_graph_from_text(text: str, max_text_length: int = 8000) -> dict:
    """
    Extract entities and relationships from text via configured LLM provider.

    Args:
        text: Text to extract graph from
        max_text_length: Maximum text length to send to LLM (default 8000 chars)

    Returns:
        Dict with 'entities' and 'relationships' lists
    """
    import time

    # Truncate text if too long
    if len(text) > max_text_length:
        text = text[:max_text_length] + "..."
        logger.warning(f"Text truncated to {max_text_length} chars for graph extraction")

    prompt = f"""
Извлеки из текста сущности и их связи. Верни ТОЛЬКО JSON:

{{
"entities": [
{{"name": "ximi_company", "type": "organization"}},
{{"name": "nordtek", "type": "organization"}}
],
"relationships": [
{{"source": "ximi_company", "target": "распределённая_платформа_для_управления_городскими_энергетическими_сетями", "type": "разрабатывает_алгоритмы_прогнозирования_нагрузки"}}
]
}}

Текст:

\"\"\"{text}\"\"\"
"""

    # Retry logic for LLM calls
    last_error = None
    for attempt in range(3):
        try:
            content = chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "Ты извлекаешь граф знаний из текста. Верни только JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                json_mode=True,
                timeout=120,  # Increased timeout for graph extraction
            )
            logger.debug(f"LLM raw response ({len(content)} chars): {content[:500]}...")
            break
        except Exception as e:
            last_error = e
            if attempt < 2:
                wait_time = 2 * (attempt + 1)
                logger.warning(f"Graph extraction retry {attempt + 1}/3 after {wait_time}s: {e}")
                time.sleep(wait_time)
            else:
                logger.error(f"Graph extraction failed after 3 attempts: {e}")
                return {"entities": [], "relationships": []}

    # Clean up response - handle markdown blocks, thinking tags, etc.
    content = content.strip()

    # Remove thinking blocks from reasoning models (deepseek-r1, etc.)
    if "<think>" in content:
        # Extract content after </think>
        parts = content.split("</think>")
        if len(parts) > 1:
            content = parts[-1].strip()

    # Remove markdown code blocks
    if "```" in content:
        # Try to extract JSON from code block
        import re
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if json_match:
            content = json_match.group(1).strip()

    # Try to find JSON object in the content
    if not content.startswith("{"):
        # Look for first { and last }
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            content = content[start:end + 1]

    if not content:
        logger.warning("Empty content after cleanup, no graph extracted")
        return {"entities": [], "relationships": []}

    logger.info(f"Parsing JSON from LLM response ({len(content)} chars)")

    try:
        data = json.loads(content)
        entities = data.get("entities", [])
        relationships = data.get("relationships", [])
        logger.info(f"Extracted {len(entities)} entities, {len(relationships)} relationships")
        return {
            "entities": entities,
            "relationships": relationships,
        }
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse graph JSON: {e}. Content: {content[:500]}...")
        return {"entities": [], "relationships": []}
    except Exception as e:
        logger.error(f"Unexpected error parsing graph: {e}. Content type: {type(content)}")
        return {"entities": [], "relationships": []}


def write_doc_graph_to_memgraph(
    text: str,
    file_name: str,
    user_id: str = "user",
    workspace_id: str = None,
    doc_label: Optional[str] = None,
    upload_time: Optional[str] = None,
) -> None:
    """
    Write document to Memgraph with workspace isolation:
    1) Call LLM → entities + relationships
    2) Create :Document node with metadata (including workspace_id)
    3) Create :Entity nodes and relationships (with workspace_id)

    Args:
        text: Document text
        file_name: Document name
        user_id: User identifier
        workspace_id: Workspace identifier for isolation (None uses DEFAULT_WORKSPACE_ID)
    """
    # Lazy import to avoid circular dependency
    from entity_resolver import resolve_entity, create_alias

    workspace_id = normalize_workspace_id(workspace_id)

    if doc_label is None:
        doc_label, upload_time = build_doc_label(
            source_id=file_name,
            user_id=user_id,
            workspace_id=workspace_id,
            upload_time=upload_time,
        )
    elif upload_time is None:
        upload_time = datetime.now(UTC).isoformat()

    graph = extract_graph_from_text(text)
    entities = graph["entities"]
    relationships = graph["relationships"]

    doc_id = doc_label

    logger.info(f"Writing graph to Memgraph: {len(entities)} entities, {len(relationships)} relationships")

    driver = get_memgraph_driver()
    with driver.session() as session:
        logger.debug("Creating document node...")
        # Document node with workspace_id
        session.run(
            """
MERGE (u:User {user_id: $user_id, workspace_id: $workspace_id})
MERGE (d:Document {doc_id: $doc_id})
SET d.file_name = $file_name,
    d.upload_time = $upload_time,
    d.raw_text = $text,
    d.doc_label = $doc_label,
    d.workspace_id = $workspace_id,
    d.user_id = $user_id
MERGE (u)-[:UPLOADED]->(d)
            """,
            {
                "user_id": user_id,
                "workspace_id": workspace_id,
                "doc_id": doc_id,
                "file_name": file_name,
                "upload_time": upload_time,
                "text": text,
                "doc_label": doc_label,
            },
        )

        # Entities with synonym resolution and workspace_id
        logger.info(f"Processing {len(entities)} entities with synonym resolution...")

        # Get existing entities ONCE (optimization - avoid N queries)
        from entity_resolver import get_all_entities, resolve_entity_with_existing
        existing_entities = get_all_entities(session, workspace_id)
        logger.debug(f"Found {len(existing_entities)} existing entities in workspace")

        for i, ent in enumerate(entities):
            raw_name = ent.get("name")
            if not raw_name:
                continue

            logger.debug(f"Resolving entity {i+1}/{len(entities)}: {raw_name}")
            entity_type = ent.get("type", "unknown")
            canonical_name, alias_to = resolve_entity_with_existing(
                raw_name,
                existing_entities,
                entity_type=entity_type,
            )

            # Add new entity to list for subsequent iterations
            if canonical_name == raw_name and raw_name not in existing_entities:
                existing_entities.append(raw_name)

            session.run(
                """
MATCH (d:Document {doc_id: $doc_id})
MERGE (e:Entity {name: $name, workspace_id: $workspace_id})
SET e.type = $type,
    e.user_id = $user_id,
    e.doc_labels = CASE
        WHEN e.doc_labels IS NULL THEN [$doc_label]
        WHEN $doc_label IN e.doc_labels THEN e.doc_labels
        ELSE e.doc_labels + [$doc_label]
    END
MERGE (d)-[:MENTIONS]->(e)
                """,
                {
                    "doc_id": doc_id,
                    "name": canonical_name,
                    "type": entity_type,
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "doc_label": doc_label,
                },
            )

            if alias_to:
                create_alias(session, canonical_name, alias_to, workspace_id)

        # Relationships between entities (with workspace filtering)
        for rel in relationships:
            session.run(
                """
MERGE (e1:Entity {name: $source, workspace_id: $workspace_id})
MERGE (e2:Entity {name: $target, workspace_id: $workspace_id})
SET e1.doc_labels = CASE
    WHEN e1.doc_labels IS NULL THEN [$doc_label]
    WHEN $doc_label IN e1.doc_labels THEN e1.doc_labels
    ELSE e1.doc_labels + [$doc_label]
END,
    e2.doc_labels = CASE
    WHEN e2.doc_labels IS NULL THEN [$doc_label]
    WHEN $doc_label IN e2.doc_labels THEN e2.doc_labels
    ELSE e2.doc_labels + [$doc_label]
END
MERGE (e1)-[r:RELATION {type: $rel_type, workspace_id: $workspace_id}]->(e2)
                """,
                {
                    "source": rel.get("source"),
                    "target": rel.get("target"),
                    "rel_type": rel.get("type"),
                    "workspace_id": workspace_id,
                    "doc_label": doc_label,
                },
            )

    bg_print(f"✓ Graph for document '{file_name}' written to Memgraph (workspace: {workspace_id})")


def write_jira_graph_to_memgraph(
    jira_data: dict,
    markdown_text: str,
    user_id: str = "user",
    workspace_id: str = None,
    doc_label: Optional[str] = None,
    upload_time: Optional[str] = None,
) -> None:
    """
    Write Jira issue to Memgraph with workspace isolation:
    1) Create :JiraIssue node with metadata (including workspace_id)
    2) Extract entities/relationships via LLM
    3) Link with participants (assignee, reporter)

    Args:
        jira_data: Parsed Jira issue data
        markdown_text: Markdown representation of the issue
        user_id: User identifier
        workspace_id: Workspace identifier for isolation (None uses DEFAULT_WORKSPACE_ID)
    """
    from entity_resolver import resolve_entity, create_alias

    workspace_id = normalize_workspace_id(workspace_id)

    issue_key = jira_data.get("key", "UNKNOWN")
    if doc_label is None:
        doc_label, upload_time = build_doc_label(
            source_id=issue_key,
            user_id=user_id,
            workspace_id=workspace_id,
            upload_time=upload_time,
        )
    elif upload_time is None:
        upload_time = datetime.now(UTC).isoformat()

    doc_id = doc_label

    driver = get_memgraph_driver()
    with driver.session() as session:
        # Jira issue node with workspace_id
        session.run(
            """
MERGE (u:User {user_id: $user_id, workspace_id: $workspace_id})
MERGE (j:JiraIssue {issue_key: $issue_key, workspace_id: $workspace_id})
SET j.doc_id = $doc_id,
    j.doc_label = $doc_label,
    j.summary = $summary,
    j.status = $status,
    j.priority = $priority,
    j.issuetype = $issuetype,
    j.assignee = $assignee,
    j.reporter = $reporter,
    j.created = $created,
    j.updated = $updated,
    j.description = $description,
    j.upload_time = $upload_time,
    j.raw_text = $raw_text,
    j.user_id = $user_id
MERGE (u)-[:TRACKS]->(j)
            """,
            {
                "user_id": user_id,
                "workspace_id": workspace_id,
                "doc_id": doc_id,
                "doc_label": doc_label,
                "issue_key": issue_key,
                "summary": jira_data.get("summary", ""),
                "status": jira_data.get("status", ""),
                "priority": jira_data.get("priority"),
                "issuetype": jira_data.get("issuetype"),
                "assignee": jira_data.get("assignee"),
                "reporter": jira_data.get("reporter"),
                "created": jira_data.get("created"),
                "updated": jira_data.get("updated"),
                "description": jira_data.get("description", "")[:2000],
                "upload_time": upload_time,
                "raw_text": markdown_text,
            },
        )

        # Link with assignee as Entity(type=person) (workspace-aware, dedup-aware)
        if jira_data.get("assignee"):
            from entity_resolver import get_all_entities, resolve_entity_with_existing
            existing_entities = get_all_entities(session, workspace_id)
            canonical_name, alias_to = resolve_entity_with_existing(
                jira_data["assignee"], existing_entities, entity_type="person"
            )
            session.run(
                """
MATCH (j:JiraIssue {issue_key: $issue_key, workspace_id: $workspace_id})
MERGE (p:Entity {name: $name, workspace_id: $workspace_id})
SET p.type = COALESCE(p.type, "person"),
    p.user_id = $user_id,
    p.doc_labels = CASE
        WHEN p.doc_labels IS NULL THEN [$doc_label]
        WHEN $doc_label IN p.doc_labels THEN p.doc_labels
        ELSE p.doc_labels + [$doc_label]
    END
MERGE (p)-[:ASSIGNED_TO]->(j)
                """,
                {
                    "issue_key": issue_key,
                    "name": canonical_name,
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "doc_label": doc_label,
                },
            )
            if alias_to:
                create_alias(session, canonical_name, alias_to, workspace_id)

        # Link with reporter as Entity(type=person) (workspace-aware)
        if jira_data.get("reporter"):
            from entity_resolver import get_all_entities, resolve_entity_with_existing
            existing_entities = get_all_entities(session, workspace_id)
            canonical_name, alias_to = resolve_entity_with_existing(
                jira_data["reporter"], existing_entities, entity_type="person"
            )
            session.run(
                """
MATCH (j:JiraIssue {issue_key: $issue_key, workspace_id: $workspace_id})
MERGE (p:Entity {name: $name, workspace_id: $workspace_id})
SET p.type = COALESCE(p.type, "person"),
    p.user_id = $user_id,
    p.doc_labels = CASE
        WHEN p.doc_labels IS NULL THEN [$doc_label]
        WHEN $doc_label IN p.doc_labels THEN p.doc_labels
        ELSE p.doc_labels + [$doc_label]
    END
MERGE (p)-[:REPORTED]->(j)
                """,
                {
                    "issue_key": issue_key,
                    "name": canonical_name,
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "doc_label": doc_label,
                },
            )
            if alias_to:
                create_alias(session, canonical_name, alias_to, workspace_id)

        # Extract entities from description and comments
        text_for_graph = markdown_text[:6000]
        if text_for_graph.strip():
            try:
                graph = extract_graph_from_text(text_for_graph)
                entities = graph.get("entities", [])
                relationships = graph.get("relationships", [])

                from entity_resolver import get_all_entities, resolve_entity_with_existing
                existing_entities = get_all_entities(session, workspace_id)

                for ent in entities:
                    raw_name = ent.get("name")
                    if not raw_name:
                        continue
                    canonical_name, alias_to = resolve_entity_with_existing(
                        raw_name,
                        existing_entities,
                        entity_type=ent.get("type", "unknown"),
                    )
                    session.run(
                        """
MATCH (j:JiraIssue {issue_key: $issue_key, workspace_id: $workspace_id})
MERGE (e:Entity {name: $name, workspace_id: $workspace_id})
SET e.type = $type,
    e.user_id = $user_id,
    e.doc_labels = CASE
        WHEN e.doc_labels IS NULL THEN [$doc_label]
        WHEN $doc_label IN e.doc_labels THEN e.doc_labels
        ELSE e.doc_labels + [$doc_label]
    END
MERGE (j)-[:MENTIONS]->(e)
                        """,
                        {
                            "issue_key": issue_key,
                            "name": canonical_name,
                            "type": ent.get("type", "unknown"),
                            "workspace_id": workspace_id,
                            "user_id": user_id,
                            "doc_label": doc_label,
                        },
                    )
                    if alias_to:
                        create_alias(session, canonical_name, alias_to, workspace_id)

                for rel in relationships:
                    session.run(
                        """
MERGE (e1:Entity {name: $source, workspace_id: $workspace_id})
MERGE (e2:Entity {name: $target, workspace_id: $workspace_id})
MERGE (e1)-[r:RELATION {type: $rel_type, workspace_id: $workspace_id}]->(e2)
                        """,
                        {
                            "source": rel.get("source"),
                            "target": rel.get("target"),
                            "rel_type": rel.get("type"),
                            "workspace_id": workspace_id,
                        },
                    )
            except Exception as e:
                bg_print(f"   ⚠️ Graph extraction failed: {e}")

    bg_print(f"✓ Jira issue '{issue_key}' written to Memgraph (workspace: {workspace_id})")


def get_graph_entities(
    texts: List[str],
    workspace_id: str = None
) -> List[Dict]:
    """
    Get entities mentioned in documents for a specific workspace.

    Args:
        texts: List of document texts to search for entities
        workspace_id: Workspace identifier (None uses DEFAULT_WORKSPACE_ID)

    Returns:
        List of entities with names, types, and aliases

    Note:
        For backward compatibility, default workspace also matches
        documents/entities without workspace_id property.
    """
    workspace_id = normalize_workspace_id(workspace_id)

    driver = get_memgraph_driver()
    with driver.session() as s:
        # For default workspace, also match old data without workspace_id
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                """
MATCH (d:Document)-[:MENTIONS]->(e:Entity)
WHERE d.raw_text IN $texts
  AND (d.workspace_id = $workspace_id OR d.workspace_id IS NULL)
OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity)
WITH e, alias
RETURN DISTINCT
e.name AS name,
e.type AS type,
COLLECT(DISTINCT alias.name) AS aliases
                """,
                {"texts": texts, "workspace_id": workspace_id},
            )
        else:
            # Strict workspace filtering for non-default workspaces
            ent_res = s.run(
                """
MATCH (d:Document)-[:MENTIONS]->(e:Entity)
WHERE d.raw_text IN $texts AND d.workspace_id = $workspace_id AND e.workspace_id = $workspace_id
OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity)
WHERE alias.workspace_id = $workspace_id
WITH e, alias
RETURN DISTINCT
e.name AS name,
e.type AS type,
COLLECT(DISTINCT alias.name) AS aliases
                """,
                {"texts": texts, "workspace_id": workspace_id},
            )

        entities = []
        for r in ent_res:
            entities.append(
                {
                    "name": r["name"],
                    "type": r["type"],
                    "aliases": [a for a in r["aliases"] if a],
                }
            )

        return entities


def get_entities_by_doc_labels(
    doc_labels: List[str],
    workspace_id: str = None
) -> List[Dict]:
    """
    Get entities mentioned in documents by doc_label for a specific workspace.
    """
    labels = [label for label in doc_labels if label]
    if not labels:
        return []

    workspace_id = normalize_workspace_id(workspace_id)

    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                """
MATCH (d)
WHERE (d:Document OR d:JiraIssue)
  AND d.doc_label IN $labels
  AND (d.workspace_id = $workspace_id OR d.workspace_id IS NULL)
MATCH (d)-[:MENTIONS]->(e:Entity)
OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity)
WITH e, alias
RETURN DISTINCT
e.name AS name,
e.type AS type,
COLLECT(DISTINCT alias.name) AS aliases
                """,
                {"labels": labels, "workspace_id": workspace_id},
            )
        else:
            ent_res = s.run(
                """
MATCH (d)
WHERE (d:Document OR d:JiraIssue)
  AND d.doc_label IN $labels
  AND d.workspace_id = $workspace_id
MATCH (d)-[:MENTIONS]->(e:Entity)
WHERE e.workspace_id = $workspace_id
OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity)
WHERE alias.workspace_id = $workspace_id
WITH e, alias
RETURN DISTINCT
e.name AS name,
e.type AS type,
COLLECT(DISTINCT alias.name) AS aliases
                """,
                {"labels": labels, "workspace_id": workspace_id},
            )

        entities = []
        for r in ent_res:
            entities.append(
                {
                    "name": r["name"],
                    "type": r["type"],
                    "aliases": [a for a in r["aliases"] if a],
                }
            )

        return entities


def get_all_workspace_entities(workspace_id: str = None, limit: int = 100) -> List[Dict]:
    """
    Get all entities in a workspace.

    Args:
        workspace_id: Workspace identifier (None uses DEFAULT_WORKSPACE_ID)
        limit: Maximum number of entities to return

    Returns:
        List of entities with names and types
    """
    workspace_id = normalize_workspace_id(workspace_id)

    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            res = s.run(
                """
MATCH (e:Entity)
WHERE e.workspace_id = $workspace_id OR e.workspace_id IS NULL
RETURN DISTINCT e.name AS name, e.type AS type
LIMIT $limit
                """,
                {"workspace_id": workspace_id, "limit": limit},
            )
        else:
            res = s.run(
                """
MATCH (e:Entity)
WHERE e.workspace_id = $workspace_id
RETURN DISTINCT e.name AS name, e.type AS type
LIMIT $limit
                """,
                {"workspace_id": workspace_id, "limit": limit},
            )

        return [{"name": r["name"], "type": r["type"]} for r in res]


def get_graph_relationships(
    entity_names: List[str],
    workspace_id: str = None,
    max_depth: int = 5,
) -> List[Dict]:
    """
    Get relationships for entities in a specific workspace.

    Args:
        entity_names: List of entity names to search for
        workspace_id: Workspace identifier (None uses DEFAULT_WORKSPACE_ID)

    Returns:
        List of relationships with source, target, and type

    Note:
        For backward compatibility, default workspace also matches
        entities without workspace_id property.
    """
    workspace_id = normalize_workspace_id(workspace_id)
    depth = max(1, min(max_depth, 5))

    driver = get_memgraph_driver()
    with driver.session() as s:
        # For default workspace, also match old data without workspace_id
        if workspace_id == DEFAULT_WORKSPACE_ID:
            rel_res = s.run(
                f"""
MATCH p = (e:Entity)-[rels:RELATION*1..{depth}]-(e2:Entity)
WHERE e.name IN $names
UNWIND range(0, size(rels)-1) AS idx
WITH rels[idx] AS r, nodes(p)[idx] AS n1, nodes(p)[idx+1] AS n2
WHERE n1.name IS NOT NULL AND n2.name IS NOT NULL
RETURN DISTINCT n1.name AS source, n2.name AS target, r.type AS rel_type
LIMIT 200
                """,
                {"names": entity_names},
            )
        else:
            # Strict workspace filtering for non-default workspaces
            rel_res = s.run(
                f"""
MATCH p = (e:Entity)-[rels:RELATION*1..{depth}]-(e2:Entity)
WHERE e.name IN $names
  AND e.workspace_id = $workspace_id
  AND e2.workspace_id = $workspace_id
UNWIND range(0, size(rels)-1) AS idx
WITH rels[idx] AS r, nodes(p)[idx] AS n1, nodes(p)[idx+1] AS n2
WHERE n1.name IS NOT NULL AND n2.name IS NOT NULL
RETURN DISTINCT n1.name AS source, n2.name AS target, r.type AS rel_type
LIMIT 200
                """,
                {"names": entity_names, "workspace_id": workspace_id},
            )

        relationships = [
            {"source": r["source"], "target": r["target"], "type": r["rel_type"]}
            for r in rel_res
        ]

        return relationships


def get_doc_labels_by_entities(
    entity_names: List[str],
    workspace_id: str = None
) -> List[Dict]:
    """
    Get document labels for documents linked to entities in a specific workspace.
    """
    if not entity_names:
        return []

    workspace_id = normalize_workspace_id(workspace_id)

    driver = get_memgraph_driver()
    with driver.session() as s:
        # Prefer Entity.doc_labels (new format). Fallback to graph traversal (old format).
        if workspace_id == DEFAULT_WORKSPACE_ID:
            doc_res = s.run(
                """
MATCH (e:Entity)
WHERE e.name IN $names AND (e.workspace_id = $workspace_id OR e.workspace_id IS NULL)
WITH DISTINCT e
UNWIND COALESCE(e.doc_labels, []) AS dl
WITH DISTINCT dl AS doc_label
WHERE doc_label IS NOT NULL AND doc_label <> ""
MATCH (d)
WHERE (d:Document OR d:JiraIssue)
  AND d.doc_label = doc_label
  AND (d.workspace_id = $workspace_id OR d.workspace_id IS NULL)
RETURN DISTINCT
d.doc_label AS doc_label,
COALESCE(d.file_name, d.issue_key, d.summary, d.doc_id) AS title
UNION
MATCH (e:Entity)
WHERE e.name IN $names AND (e.workspace_id = $workspace_id OR e.workspace_id IS NULL)
MATCH (e)<-[:MENTIONS]-(d)
WHERE (d:Document OR d:JiraIssue)
  AND d.doc_label IS NOT NULL
  AND (d.workspace_id = $workspace_id OR d.workspace_id IS NULL)
RETURN DISTINCT
d.doc_label AS doc_label,
COALESCE(d.file_name, d.issue_key, d.summary, d.doc_id) AS title
                """,
                {"names": entity_names, "workspace_id": workspace_id},
            )
        else:
            doc_res = s.run(
                """
MATCH (e:Entity)
WHERE e.name IN $names AND e.workspace_id = $workspace_id
WITH DISTINCT e
UNWIND COALESCE(e.doc_labels, []) AS dl
WITH DISTINCT dl AS doc_label
WHERE doc_label IS NOT NULL AND doc_label <> ""
MATCH (d)
WHERE (d:Document OR d:JiraIssue)
  AND d.doc_label = doc_label
  AND d.workspace_id = $workspace_id
RETURN DISTINCT
d.doc_label AS doc_label,
COALESCE(d.file_name, d.issue_key, d.summary, d.doc_id) AS title
UNION
MATCH (e:Entity)
WHERE e.name IN $names AND e.workspace_id = $workspace_id
MATCH (e)<-[:MENTIONS]-(d)
WHERE (d:Document OR d:JiraIssue)
  AND d.doc_label IS NOT NULL
  AND d.workspace_id = $workspace_id
RETURN DISTINCT
d.doc_label AS doc_label,
COALESCE(d.file_name, d.issue_key, d.summary, d.doc_id) AS title
                """,
                {"names": entity_names, "workspace_id": workspace_id},
            )

        return [{"doc_label": r["doc_label"], "title": r["title"]} for r in doc_res]


def get_related_documents(
    texts: List[str],
    workspace_id: str = None
) -> List[Dict]:
    """
    Get other documents linked through entities in a specific workspace.

    Args:
        texts: List of document texts to search for
        workspace_id: Workspace identifier (None uses DEFAULT_WORKSPACE_ID)

    Returns:
        List of related documents with doc_id and file_name

    Note:
        For backward compatibility, default workspace also matches
        documents without workspace_id property.
    """
    workspace_id = normalize_workspace_id(workspace_id)

    driver = get_memgraph_driver()
    with driver.session() as s:
        # For default workspace, also match old data without workspace_id
        if workspace_id == DEFAULT_WORKSPACE_ID:
            doc_res = s.run(
                """
MATCH (d1:Document)-[:MENTIONS]->(e:Entity)
WHERE d1.raw_text IN $texts
OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity)
WITH COALESCE(alias, e) AS linked_entity
MATCH (linked_entity)<-[:MENTIONS]-(d2:Document)
RETURN DISTINCT d2.doc_id AS doc_id, d2.file_name AS file_name
                """,
                {"texts": texts},
            )
        else:
            # Strict workspace filtering for non-default workspaces
            doc_res = s.run(
                """
MATCH (d1:Document)-[:MENTIONS]->(e:Entity)
WHERE d1.raw_text IN $texts AND d1.workspace_id = $workspace_id AND e.workspace_id = $workspace_id
OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity)
WHERE alias.workspace_id = $workspace_id
WITH COALESCE(alias, e) AS linked_entity
MATCH (linked_entity)<-[:MENTIONS]-(d2:Document)
WHERE d2.workspace_id = $workspace_id
RETURN DISTINCT d2.doc_id AS doc_id, d2.file_name AS file_name
                """,
                {"texts": texts, "workspace_id": workspace_id},
            )

        documents = [
            {"doc_id": r["doc_id"], "file_name": r["file_name"]} for r in doc_res
        ]

        return documents


def delete_workspace_graph(workspace_id: str) -> None:
    """
    Delete all graph data for a specific workspace.

    WARNING: This is permanent and cannot be undone!

    Args:
        workspace_id: Workspace identifier to delete
    """
    driver = get_memgraph_driver()
    with driver.session() as session:
        # Delete all nodes and relationships for the workspace
        session.run(
            """
MATCH (n)
WHERE n.workspace_id = $workspace_id
DETACH DELETE n
            """,
            {"workspace_id": workspace_id}
        )

        logger.info(f"Deleted all graph data for workspace '{workspace_id}'")
```

### ./metatron/llm/__init__.py
```python
"""
Multi-provider LLM abstraction for Metatron.

Usage:
    from metatron.llm import chat_completion

    # Simple usage - uses configured provider
    result = chat_completion(
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"}
        ]
    )
    print(result)  # "Hello! How can I help you today?"

    # With options
    result = chat_completion(
        messages=[...],
        temperature=0.1,
        max_tokens=500,
        json_mode=True  # Request JSON output
    )

    # Direct provider access
    from metatron.llm import get_llm

    llm = get_llm()
    response = llm.chat_completion(messages=[...])
    print(response.content)
    print(response.model, response.provider)

Configuration via environment variables:
    LLM_PROVIDER=deepseek|openrouter|ollama|custom
    LLM_MODEL=model-name (optional, uses provider default)

    # Fallback (optional)
    LLM_FALLBACK_PROVIDER=ollama
    LLM_FALLBACK_MODEL=llama3

    # Provider-specific
    DEEPSEEK_API_KEY=sk-xxx
    OPENROUTER_API_KEY=sk-xxx
    OLLAMA_LLM_HOST=http://localhost:11434
    OLLAMA_LLM_MODEL=llama3
    CUSTOM_LLM_URL=http://server:8080/v1/chat/completions
"""
import logging
from typing import List, Dict, Union, Optional, Any

from .base import (
    LLMProvider,
    LLMResponse,
    Message,
    LLMError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMAuthenticationError,
)
from .provider import (
    get_llm,
    create_provider,
    get_provider_class,
    get_fallback_provider,
    _get_cached_fallback,
    PROVIDERS,
)
from metatron.metrics import timed

logger = logging.getLogger(__name__)

__all__ = [
    # Public API
    "chat_completion",
    "get_llm",
    # Provider management
    "create_provider",
    "get_provider_class",
    "get_fallback_provider",
    "PROVIDERS",
    # Types and exceptions
    "LLMProvider",
    "LLMResponse",
    "Message",
    "LLMError",
    "LLMConnectionError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
]


@timed("llm_completion")
def chat_completion(
    messages: List[Union[Dict[str, str], Message]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    timeout: int = 60,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    use_fallback: bool = True,
    **kwargs
) -> str:
    """
    Send a chat completion request to the configured LLM provider.

    This is the main entry point for LLM calls. It handles provider
    selection, fallback on failure, and returns just the response content.

    Args:
        messages: List of messages, either as dicts {"role": "...", "content": "..."}
                 or Message objects
        temperature: Sampling temperature (0-2, default 0.7)
        max_tokens: Maximum tokens in response (optional)
        json_mode: Request JSON output format (default False)
        timeout: Request timeout in seconds (default 60)
        provider: Provider name override (optional)
        model: Model name override (optional)
        use_fallback: Whether to try fallback provider on failure (default True)
        **kwargs: Additional provider-specific parameters

    Returns:
        Response content as string

    Raises:
        LLMError: If all providers fail

    Example:
        # Basic usage
        answer = chat_completion([
            {"role": "system", "content": "Answer concisely."},
            {"role": "user", "content": "What is Python?"}
        ])

        # With JSON mode
        data = chat_completion(
            messages=[{"role": "user", "content": "Return JSON with name and age"}],
            json_mode=True,
            temperature=0.1
        )
    """
    # Convert dicts to Message objects
    msg_objects: List[Message] = []
    for m in messages:
        if isinstance(m, Message):
            msg_objects.append(m)
        elif isinstance(m, dict):
            role = m.get("role")
            content = m.get("content")
            if not role or content is None:
                raise ValueError(f"Invalid message format: missing 'role' or 'content' in {m}")
            msg_objects.append(Message(role=role, content=content))
        else:
            raise ValueError(f"Invalid message type: {type(m)}")

    # Get primary provider
    llm = get_llm(provider_name=provider, model=model)

    try:
        response = llm.chat_completion(
            messages=msg_objects,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            timeout=timeout,
            **kwargs
        )
        return response.content

    except (LLMConnectionError, LLMAuthenticationError, LLMRateLimitError) as e:
        logger.warning(f"Primary LLM ({llm.name}) failed: {e}")

        if not use_fallback:
            raise

        # Try fallback provider
        fallback = _get_cached_fallback()
        if fallback and fallback.is_available():
            logger.info(f"Trying fallback provider: {fallback.name}")
            try:
                response = fallback.chat_completion(
                    messages=msg_objects,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    timeout=timeout,
                    **kwargs
                )
                return response.content
            except LLMError as fallback_error:
                logger.error(f"Fallback LLM ({fallback.name}) also failed: {fallback_error}")
                # Raise original error, but note fallback failure
                raise LLMError(
                    f"Primary ({llm.name}) and fallback ({fallback.name}) providers both failed. "
                    f"Primary error: {e}. Fallback error: {fallback_error}"
                ) from e

        # No fallback available
        raise
```

### ./metatron/llm/base.py
```python
"""
Base classes and types for LLM provider abstraction.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


class LLMError(Exception):
    """Base exception for LLM-related errors."""
    pass


class LLMConnectionError(LLMError):
    """Raised when connection to LLM provider fails."""
    pass


class LLMRateLimitError(LLMError):
    """Raised when rate limit is exceeded."""
    pass


class LLMAuthenticationError(LLMError):
    """Raised when authentication fails."""
    pass


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str
    model: str
    provider: str
    usage: Dict[str, int] = field(default_factory=dict)
    raw_response: Optional[Dict[str, Any]] = None

    @property
    def prompt_tokens(self) -> int:
        return self.usage.get("prompt_tokens", 0)

    @property
    def completion_tokens(self) -> int:
        return self.usage.get("completion_tokens", 0)

    @property
    def total_tokens(self) -> int:
        return self.usage.get("total_tokens", 0)


@dataclass
class Message:
    """Chat message."""
    role: str  # "system", "user", "assistant"
    content: str


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str = "base"

    def __init__(self, model: Optional[str] = None, **kwargs):
        """
        Initialize the provider.

        Args:
            model: Model name to use (provider-specific)
            **kwargs: Additional provider-specific configuration
        """
        self.model = model or self.default_model
        self.config = kwargs

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model for this provider."""
        pass

    @abstractmethod
    def chat_completion(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
        timeout: int = 60,
        **kwargs
    ) -> LLMResponse:
        """
        Send a chat completion request.

        Args:
            messages: List of messages in the conversation
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
            json_mode: Request JSON output format
            timeout: Request timeout in seconds
            **kwargs: Additional provider-specific parameters

        Returns:
            LLMResponse with the model's response

        Raises:
            LLMConnectionError: If connection fails
            LLMRateLimitError: If rate limit is exceeded
            LLMAuthenticationError: If authentication fails
            LLMError: For other errors
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is properly configured and available."""
        pass

    def _messages_to_dicts(self, messages: List[Message]) -> List[Dict[str, str]]:
        """Convert Message objects to dicts for API calls."""
        return [{"role": m.role, "content": m.content} for m in messages]
```

### ./metatron/llm/provider.py
```python
"""
LLM provider factory with fallback support.
"""
import os
import logging
from typing import Optional, Dict, Type

from .base import LLMProvider, LLMError, LLMConnectionError, LLMAuthenticationError
from .providers import (
    DeepSeekProvider,
    OpenRouterProvider,
    OllamaProvider,
    CustomProvider,
)

logger = logging.getLogger(__name__)

# Registry of available providers
PROVIDERS: Dict[str, Type[LLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "custom": CustomProvider,
}


def get_provider_class(name: str) -> Type[LLMProvider]:
    """Get provider class by name."""
    provider_class = PROVIDERS.get(name.lower())
    if not provider_class:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Unknown LLM provider: {name}. Available: {available}")
    return provider_class


def create_provider(
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> LLMProvider:
    """
    Create an LLM provider instance.

    Args:
        provider_name: Provider name (deepseek, openrouter, ollama, custom)
                      Falls back to LLM_PROVIDER env var, then "deepseek"
        model: Model name override (provider-specific)
               Falls back to LLM_MODEL env var, then provider default
        **kwargs: Additional provider-specific configuration

    Returns:
        Configured LLMProvider instance
    """
    provider_name = provider_name or os.getenv("LLM_PROVIDER", "deepseek")
    model = model or os.getenv("LLM_MODEL")

    provider_class = get_provider_class(provider_name)
    return provider_class(model=model, **kwargs)


def get_fallback_provider() -> Optional[LLMProvider]:
    """
    Get fallback provider if configured.

    Returns:
        LLMProvider instance or None if not configured
    """
    fallback_name = os.getenv("LLM_FALLBACK_PROVIDER")
    if not fallback_name:
        return None

    fallback_model = os.getenv("LLM_FALLBACK_MODEL")

    try:
        provider = create_provider(fallback_name, fallback_model)
        if provider.is_available():
            return provider
        logger.warning(f"Fallback provider '{fallback_name}' not available")
    except Exception as e:
        logger.warning(f"Failed to create fallback provider '{fallback_name}': {e}")

    return None


# Cached primary and fallback providers
_primary_provider: Optional[LLMProvider] = None
_fallback_provider: Optional[LLMProvider] = None


def get_llm(
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    use_cache: bool = True,
    **kwargs
) -> LLMProvider:
    """
    Get an LLM provider instance.

    Uses cached instance by default for efficiency.

    Args:
        provider_name: Provider name override
        model: Model name override
        use_cache: Whether to use cached provider instance
        **kwargs: Additional provider-specific configuration

    Returns:
        Configured LLMProvider instance
    """
    global _primary_provider

    # Return cached provider if available and no overrides
    if use_cache and _primary_provider and not provider_name and not model and not kwargs:
        return _primary_provider

    provider = create_provider(provider_name, model, **kwargs)

    # Cache if no overrides
    if use_cache and not provider_name and not model and not kwargs:
        _primary_provider = provider

    return provider


def _get_cached_fallback() -> Optional[LLMProvider]:
    """Get cached fallback provider."""
    global _fallback_provider

    if _fallback_provider is None:
        _fallback_provider = get_fallback_provider()

    return _fallback_provider
```

### ./metatron/llm/providers/__init__.py
```python
"""
LLM provider implementations.
"""
from .deepseek import DeepSeekProvider
from .openrouter import OpenRouterProvider
from .ollama import OllamaProvider
from .custom import CustomProvider

__all__ = [
    "DeepSeekProvider",
    "OpenRouterProvider",
    "OllamaProvider",
    "CustomProvider",
]
```

### ./metatron/llm/providers/custom.py
```python
"""
Custom LLM provider for self-hosted OpenAI-compatible APIs.

Works with any server that implements the OpenAI chat completions API,
such as vLLM, text-generation-webui, LocalAI, etc.
"""
import os
from typing import List, Optional

import requests

from metatron.utils import get_http_session
from ..base import (
    LLMProvider,
    LLMResponse,
    Message,
    LLMError,
    LLMConnectionError,
    LLMAuthenticationError,
)


class CustomProvider(LLMProvider):
    """Custom OpenAI-compatible API provider."""

    name = "custom"

    def __init__(
        self,
        model: Optional[str] = None,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize Custom provider.

        Args:
            model: Model name (server-specific)
            api_url: Full URL to chat completions endpoint
            api_key: Optional API key for authentication
        """
        super().__init__(model, **kwargs)
        self.api_url = api_url or os.getenv("CUSTOM_LLM_URL", "")
        self.api_key = api_key or os.getenv("CUSTOM_LLM_API_KEY", "")

    @property
    def default_model(self) -> str:
        return os.getenv("CUSTOM_LLM_MODEL", "default")

    def is_available(self) -> bool:
        """Check if custom API endpoint is configured."""
        return bool(self.api_url)

    def chat_completion(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
        timeout: int = 60,
        **kwargs
    ) -> LLMResponse:
        """Send chat completion request to custom API."""
        if not self.api_url:
            raise LLMConnectionError("CUSTOM_LLM_URL not configured")

        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": self._messages_to_dicts(messages),
            "temperature": temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            session = get_http_session()
            resp = session.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            if resp.status_code == 401:
                raise LLMAuthenticationError("Custom API authentication failed")

            resp.raise_for_status()
            data = resp.json()

            # Handle OpenAI-compatible response format
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            return LLMResponse(
                content=content.strip(),
                model=self.model,
                provider=self.name,
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                raw_response=data,
            )

        except requests.exceptions.Timeout:
            raise LLMConnectionError(f"Custom API timeout after {timeout}s")
        except requests.exceptions.ConnectionError as e:
            raise LLMConnectionError(f"Failed to connect to custom API at {self.api_url}: {e}")
        except requests.exceptions.HTTPError as e:
            raise LLMError(f"Custom API error: {e}")
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected response format from custom API: {e}")
```

### ./metatron/llm/providers/deepseek.py
```python
"""
DeepSeek LLM provider implementation.
"""
import os
from typing import List, Optional

import requests

from metatron.utils import get_http_session
from ..base import (
    LLMProvider,
    LLMResponse,
    Message,
    LLMError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMAuthenticationError,
)


class DeepSeekProvider(LLMProvider):
    """DeepSeek API provider."""

    name = "deepseek"
    API_URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None, **kwargs):
        """
        Initialize DeepSeek provider.

        Args:
            model: Model name (default: deepseek-chat)
            api_key: API key (falls back to DEEPSEEK_API_KEY env var)
        """
        super().__init__(model, **kwargs)
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")

    @property
    def default_model(self) -> str:
        return os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def is_available(self) -> bool:
        """Check if DeepSeek API is configured."""
        return bool(self.api_key)

    def chat_completion(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
        timeout: int = 60,
        **kwargs
    ) -> LLMResponse:
        """Send chat completion request to DeepSeek API."""
        if not self.api_key:
            raise LLMAuthenticationError("DEEPSEEK_API_KEY not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": self._messages_to_dicts(messages),
            "temperature": temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        import time

        last_error = None
        for attempt in range(3):
            try:
                session = get_http_session()
                resp = session.post(
                    self.API_URL,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )

                if resp.status_code == 401:
                    raise LLMAuthenticationError("Invalid DeepSeek API key")
                if resp.status_code == 429:
                    raise LLMRateLimitError("DeepSeek rate limit exceeded")

                resp.raise_for_status()
                data = resp.json()

                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})

                return LLMResponse(
                    content=content.strip(),
                    model=self.model,
                    provider=self.name,
                    usage={
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    },
                    raw_response=data,
                )

            except requests.exceptions.Timeout:
                last_error = LLMConnectionError(f"DeepSeek API timeout after {timeout}s")
            except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
                last_error = LLMConnectionError(f"DeepSeek connection error: {e}")
            except requests.exceptions.HTTPError as e:
                raise LLMError(f"DeepSeek API error: {e}")
            except Exception as e:
                # Catch urllib3 ProtocolError, RemoteDisconnected, etc.
                if "disconnected" in str(e).lower() or "RemoteDisconnected" in str(type(e).__name__):
                    last_error = LLMConnectionError(f"DeepSeek server disconnected: {e}")
                else:
                    raise LLMError(f"DeepSeek API error: {e}")

            # Retry with backoff
            if attempt < 2:
                wait = 2 * (attempt + 1)
                time.sleep(wait)

        raise last_error
```

### ./metatron/llm/providers/ollama.py
```python
"""
Ollama LLM provider implementation.

Ollama runs models locally, useful for privacy and offline operation.
"""
import os
from typing import List, Optional

import requests

from metatron.utils import get_http_session
from ..base import (
    LLMProvider,
    LLMResponse,
    Message,
    LLMError,
    LLMConnectionError,
)


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    name = "ollama"

    def __init__(self, model: Optional[str] = None, host: Optional[str] = None, **kwargs):
        """
        Initialize Ollama provider.

        Args:
            model: Model name (e.g., "llama3", "mistral", "codellama")
            host: Ollama server URL (falls back to OLLAMA_LLM_HOST env var)
        """
        super().__init__(model, **kwargs)

        # Build host URL from env vars (compatible with existing config)
        default_host = os.getenv("OLLAMA_LLM_HOST")
        if not default_host:
            # Fall back to OLLAMA_HOST (used for embeddings) if LLM-specific not set
            ollama_host = os.getenv("OLLAMA_HOST", "localhost")
            ollama_port = os.getenv("OLLAMA_LLM_PORT", os.getenv("OLLAMA_PORT", "11434"))
            default_host = f"http://{ollama_host}:{ollama_port}"

        self.host = host or default_host
        # Ensure host has http prefix
        if not self.host.startswith(("http://", "https://")):
            self.host = f"http://{self.host}"

    @property
    def default_model(self) -> str:
        return os.getenv("OLLAMA_LLM_MODEL", "llama3")

    @property
    def api_url(self) -> str:
        return f"{self.host}/api/chat"

    def is_available(self) -> bool:
        """Check if Ollama server is running and model is available."""
        try:
            session = get_http_session()
            resp = session.get(f"{self.host}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False

            # Check if our model is in the list
            models = resp.json().get("models", [])
            model_names = [m.get("name", "").split(":")[0] for m in models]
            return self.model.split(":")[0] in model_names
        except Exception:
            return False

    def chat_completion(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
        timeout: int = 120,  # Ollama can be slow for first request
        **kwargs
    ) -> LLMResponse:
        """Send chat completion request to Ollama."""
        payload = {
            "model": self.model,
            "messages": self._messages_to_dicts(messages),
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        if json_mode:
            payload["format"] = "json"

        try:
            session = get_http_session()
            resp = session.post(
                self.api_url,
                json=payload,
                timeout=timeout,
            )

            resp.raise_for_status()
            data = resp.json()

            content = data.get("message", {}).get("content", "")

            # Ollama doesn't always return usage info
            eval_count = data.get("eval_count", 0)
            prompt_eval_count = data.get("prompt_eval_count", 0)

            return LLMResponse(
                content=content.strip(),
                model=self.model,
                provider=self.name,
                usage={
                    "prompt_tokens": prompt_eval_count,
                    "completion_tokens": eval_count,
                    "total_tokens": prompt_eval_count + eval_count,
                },
                raw_response=data,
            )

        except requests.exceptions.Timeout:
            raise LLMConnectionError(f"Ollama timeout after {timeout}s - is the model loaded?")
        except requests.exceptions.ConnectionError as e:
            raise LLMConnectionError(f"Failed to connect to Ollama at {self.host}: {e}")
        except requests.exceptions.HTTPError as e:
            raise LLMError(f"Ollama error: {e}")
```

### ./metatron/llm/providers/openrouter.py
```python
"""
OpenRouter LLM provider implementation.

OpenRouter provides access to multiple models (Claude, GPT, Llama, etc.)
through a unified API.
"""
import os
from typing import List, Optional

import requests

from metatron.utils import get_http_session
from ..base import (
    LLMProvider,
    LLMResponse,
    Message,
    LLMError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMAuthenticationError,
)


class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider - access multiple models via one API."""

    name = "openrouter"
    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None, **kwargs):
        """
        Initialize OpenRouter provider.

        Args:
            model: Model name (e.g., "anthropic/claude-3-haiku", "meta-llama/llama-3-70b-instruct")
            api_key: API key (falls back to OPENROUTER_API_KEY env var)
        """
        super().__init__(model, **kwargs)
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.site_url = kwargs.get("site_url", os.getenv("OPENROUTER_SITE_URL", ""))
        self.app_name = kwargs.get("app_name", os.getenv("OPENROUTER_APP_NAME", "Metatron"))

    @property
    def default_model(self) -> str:
        return os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")

    def is_available(self) -> bool:
        """Check if OpenRouter API is configured."""
        return bool(self.api_key)

    def chat_completion(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
        timeout: int = 60,
        **kwargs
    ) -> LLMResponse:
        """Send chat completion request to OpenRouter API."""
        if not self.api_key:
            raise LLMAuthenticationError("OPENROUTER_API_KEY not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.app_name,
        }

        payload = {
            "model": self.model,
            "messages": self._messages_to_dicts(messages),
            "temperature": temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            session = get_http_session()
            resp = session.post(
                self.API_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            if resp.status_code == 401:
                raise LLMAuthenticationError("Invalid OpenRouter API key")
            if resp.status_code == 429:
                raise LLMRateLimitError("OpenRouter rate limit exceeded")
            if resp.status_code == 404:
                # Model not found or invalid endpoint
                error_detail = resp.text[:500] if resp.text else "No details"
                raise LLMError(f"OpenRouter model '{self.model}' not found. Details: {error_detail}")

            if resp.status_code == 400:
                # Bad request - often json_mode not supported
                error_detail = resp.text[:500] if resp.text else "No details"
                # If json_mode was requested, retry without it
                if json_mode and "response_format" in error_detail.lower() or "json" in error_detail.lower():
                    payload.pop("response_format", None)
                    resp = session.post(
                        self.API_URL,
                        headers=headers,
                        json=payload,
                        timeout=timeout,
                    )
                    if resp.status_code != 200:
                        raise LLMError(f"OpenRouter error (retry without json_mode): {resp.text[:300]}")
                else:
                    raise LLMError(f"OpenRouter bad request: {error_detail}")

            resp.raise_for_status()
            data = resp.json()

            # Check for error in response body
            if "error" in data:
                error_msg = data["error"].get("message", str(data["error"]))
                raise LLMError(f"OpenRouter error: {error_msg}")

            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            return LLMResponse(
                content=content.strip(),
                model=self.model,
                provider=self.name,
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                raw_response=data,
            )

        except requests.exceptions.Timeout:
            raise LLMConnectionError(f"OpenRouter API timeout after {timeout}s")
        except requests.exceptions.ConnectionError as e:
            raise LLMConnectionError(f"Failed to connect to OpenRouter API: {e}")
        except requests.exceptions.HTTPError as e:
            raise LLMError(f"OpenRouter API error: {e}")
```

### ./metatron/main.py
```python
"""
Metatron - Main CLI entry point.

Usage:
    python -m metatron.main

Note: For production use, run the API server instead:
    python start.py
"""
import warnings
warnings.filterwarnings("ignore")

import os
import signal
import threading
from glob import glob

from metatron.config import CONFLUENCE_QUEUE, JIRA_QUEUE
from metatron.consumers import RabbitMQConfig, ConfluenceConsumer, JiraConsumer
from metatron.search import hybrid_search_and_answer
from metatron.indexers import get_hybrid_store, write_doc_graph_to_memgraph, get_all_workspace_entities
from metatron.utils import safe_input, chunk_text
from metatron.processing import extract_date_from_text


def load_document(path: str, user_id: str = "user", workspace_id: str = None) -> bool:
    """
    Load a document from file into the hybrid store and graph.

    Args:
        path: Path to file (txt, md)
        user_id: User identifier
        workspace_id: Workspace ID (uses default if not provided)

    Returns:
        True if successful, False otherwise
    """
    if not os.path.isfile(path):
        print(f"   ❌ File not found: {path}")
        return False

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        file_name = os.path.basename(path)
        doc_date = extract_date_from_text(file_name) or extract_date_from_text(text[:500])

        # Chunk the text
        chunks = chunk_text(text, max_chars=2500, overlap=200)

        # Get hybrid store
        store = get_hybrid_store(workspace_id)

        # Add chunks to store
        metadata = {"title": file_name, "type": "document"}
        if doc_date:
            metadata["date"] = doc_date

        for i, chunk in enumerate(chunks):
            doc_id = f"{file_name}_{i}" if len(chunks) > 1 else file_name
            chunk_meta = {**metadata}
            if len(chunks) > 1:
                chunk_meta["chunk"] = i + 1
            store.add_document(text=chunk, metadata=chunk_meta, doc_id=doc_id)
            print(f"   → added chunk {i+1}/{len(chunks)}")

        # Write to graph
        print("   → extracting graph...")
        write_doc_graph_to_memgraph(text, file_name, user_id, workspace_id)
        print(f"   ✅ Loaded: {file_name}")
        return True

    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def run_cli():
    """Run interactive CLI menu."""
    user_id = "user"

    # Configure consumers
    confluence_config = RabbitMQConfig(queue_name=CONFLUENCE_QUEUE)
    jira_config = RabbitMQConfig(queue_name=JIRA_QUEUE)

    confluence_consumer = ConfluenceConsumer(confluence_config, user_id=user_id)
    jira_consumer = JiraConsumer(jira_config, user_id=user_id)

    def handle_sigint(signum, frame):
        print("\n🛑 Stopping...")
        confluence_consumer.stop()
        jira_consumer.stop()
        raise SystemExit

    signal.signal(signal.SIGINT, handle_sigint)

    # Start consumers in background threads
    confluence_thread = threading.Thread(target=confluence_consumer.run, daemon=True)
    jira_thread = threading.Thread(target=jira_consumer.run, daemon=True)
    confluence_thread.start()
    jira_thread.start()

    print("\n" + "=" * 60)
    print("🤖 METATRON - Hybrid RAG System")
    print("=" * 60)
    print("RabbitMQ consumers running in background.")
    print("=" * 60)

    while True:
        print("\n📌 Menu:")
        print("  1) Load document from file")
        print("  2) Load folder")
        print("  3) Ask question (hybrid search)")
        print("  4) Show all entities")
        print("  5) Exit")
        
        choice = safe_input("> ").strip()

        if choice == "1":
            path = safe_input("Enter file path: ").strip()
            if path:
                load_document(path, user_id=user_id)

        elif choice == "2":
            folder = safe_input("Enter folder path: ").strip()
            if folder and os.path.isdir(folder):
                files = glob(os.path.join(folder, "*.txt")) + glob(os.path.join(folder, "*.md"))
                print(f"Found {len(files)} files")
                for f in files:
                    print(f"\nLoading: {f}")
                    load_document(f, user_id=user_id)

        elif choice == "3":
            question = safe_input("Enter question: ").strip()
            if question:
                print("\n🔍 Searching...")
                try:
                    answer = hybrid_search_and_answer(question, user_id=user_id)
                    print("\n📝 Answer:")
                    print(answer)
                except Exception as e:
                    print(f"❌ Error: {e}")

        elif choice == "4":
            # Get all entities from default workspace
            entities = get_all_workspace_entities(workspace_id=None, limit=100)
            print(f"\n📊 Found {len(entities)} entities:")
            for ent in entities[:50]:
                print(f"  - {ent['name']} ({ent.get('type', '?')})")
            if len(entities) > 50:
                print(f"  ... and {len(entities) - 50} more")

        elif choice == "5":
            print("👋 Goodbye!")
            confluence_consumer.stop()
            jira_consumer.stop()
            break

        else:
            print("❓ Unknown choice")


if __name__ == "__main__":
    run_cli()

```

### ./metatron/metrics.py
```python
"""
Metrics and observability for Metatron.

Provides timing decorators and request counters for monitoring system health.

Usage:
    from metatron.metrics import timed, get_metrics, reset_metrics

    @timed
    def my_function():
        ...

    # Get current metrics
    stats = get_metrics()
    print(stats["search"]["count"], stats["search"]["avg_duration"])

Future improvements:
    - Add Prometheus support via prometheus_client library
    - Add OpenTelemetry tracing for distributed systems
    - Add histogram metrics for latency percentiles (p50, p95, p99)
"""
import time
import threading
from functools import wraps
from typing import Dict, Any, Callable, TypeVar
from dataclasses import dataclass, field
from collections import defaultdict

from metatron.config import setup_logging

logger = setup_logging(__name__)

T = TypeVar('T')


@dataclass
class OperationMetrics:
    """Metrics for a single operation type."""
    count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_duration: float = 0.0
    min_duration: float = float('inf')
    max_duration: float = 0.0
    last_error: str = ""

    @property
    def avg_duration(self) -> float:
        """Average duration in seconds."""
        return self.total_duration / self.count if self.count > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "count": self.count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "total_duration_sec": round(self.total_duration, 3),
            "avg_duration_sec": round(self.avg_duration, 3),
            "min_duration_sec": round(self.min_duration, 3) if self.min_duration != float('inf') else 0,
            "max_duration_sec": round(self.max_duration, 3),
            "success_rate": round(self.success_count / self.count * 100, 1) if self.count > 0 else 0,
            "last_error": self.last_error,
        }


class MetricsCollector:
    """Thread-safe metrics collector."""

    def __init__(self):
        self._metrics: Dict[str, OperationMetrics] = defaultdict(OperationMetrics)
        self._lock = threading.Lock()
        self._start_time = time.time()

    def record_success(self, operation: str, duration: float) -> None:
        """Record a successful operation."""
        with self._lock:
            m = self._metrics[operation]
            m.count += 1
            m.success_count += 1
            m.total_duration += duration
            m.min_duration = min(m.min_duration, duration)
            m.max_duration = max(m.max_duration, duration)

    def record_error(self, operation: str, duration: float, error: str) -> None:
        """Record a failed operation."""
        with self._lock:
            m = self._metrics[operation]
            m.count += 1
            m.error_count += 1
            m.total_duration += duration
            m.min_duration = min(m.min_duration, duration)
            m.max_duration = max(m.max_duration, duration)
            m.last_error = error[:200]  # Truncate long errors

    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics as dictionary."""
        with self._lock:
            uptime = time.time() - self._start_time
            return {
                "uptime_sec": round(uptime, 1),
                "operations": {
                    name: metrics.to_dict()
                    for name, metrics in self._metrics.items()
                }
            }

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._metrics.clear()
            self._start_time = time.time()


# Global metrics collector
_collector = MetricsCollector()


def get_metrics() -> Dict[str, Any]:
    """Get current metrics."""
    return _collector.get_metrics()


def reset_metrics() -> None:
    """Reset all metrics."""
    _collector.reset()


def timed(operation_name: str = None, log_args: bool = False):
    """
    Decorator to measure and log function execution time.

    Args:
        operation_name: Custom name for the operation (default: function name)
        log_args: Whether to log function arguments (careful with sensitive data)

    Usage:
        @timed()
        def my_function():
            ...

        @timed("custom_operation_name")
        def another_function():
            ...

        @timed(log_args=True)
        def function_with_args(query: str):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        name = operation_name or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            start = time.perf_counter()

            # Build log prefix with args if requested
            if log_args and args:
                # Skip 'self' for methods
                display_args = args[1:] if args and hasattr(args[0], '__class__') else args
                arg_str = str(display_args)[:100]
                log_prefix = f"{name}({arg_str})"
            else:
                log_prefix = name

            try:
                result = func(*args, **kwargs)
                duration = time.perf_counter() - start

                _collector.record_success(name, duration)

                # Log with appropriate level based on duration
                if duration > 5.0:
                    logger.warning(f"{log_prefix} completed in {duration:.3f}s (slow)")
                elif duration > 1.0:
                    logger.info(f"{log_prefix} completed in {duration:.3f}s")
                else:
                    logger.debug(f"{log_prefix} completed in {duration:.3f}s")

                return result

            except Exception as e:
                duration = time.perf_counter() - start
                error_msg = str(e)

                _collector.record_error(name, duration, error_msg)
                logger.error(f"{log_prefix} failed after {duration:.3f}s: {error_msg}")

                raise

        return wrapper

    # Handle @timed without parentheses
    if callable(operation_name):
        func = operation_name
        operation_name = None
        return decorator(func)

    return decorator


# Convenience function for manual timing
class Timer:
    """
    Context manager for manual timing.

    Usage:
        with Timer("my_operation") as t:
            do_something()
        print(f"Took {t.duration:.3f}s")
    """

    def __init__(self, operation_name: str, log: bool = True):
        self.operation_name = operation_name
        self.log = log
        self.start = 0.0
        self.duration = 0.0
        self._success = True
        self._error = ""

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.duration = time.perf_counter() - self.start

        if exc_type is not None:
            self._success = False
            self._error = str(exc_val)
            _collector.record_error(self.operation_name, self.duration, self._error)
            if self.log:
                logger.error(f"{self.operation_name} failed after {self.duration:.3f}s: {self._error}")
        else:
            _collector.record_success(self.operation_name, self.duration)
            if self.log:
                logger.debug(f"{self.operation_name} completed in {self.duration:.3f}s")

        return False  # Don't suppress exceptions
```

### ./metatron/postgres/__init__.py
```python
"""
PostgreSQL storage module for Metatron.

Provides SQLAlchemy-based ORM for application data:
- Workspaces
- Users
- Connections/Integrations
- Configurations

Usage:
    from metatron.postgres import get_session, Workspace, User

    with get_session() as session:
        workspace = session.query(Workspace).filter_by(name="test").first()
"""
from .connection import (
    get_engine,
    get_session,
    init_db,
    close_db,
)
from .models import (
    Base,
    Workspace,
    User,
    WorkspaceMember,
    Connection,
    Config,
)

__all__ = [
    # Connection
    "get_engine",
    "get_session",
    "init_db",
    "close_db",
    # Models
    "Base",
    "Workspace",
    "User",
    "WorkspaceMember",
    "Connection",
    "Config",
]
```

### ./metatron/postgres/connection.py
```python
"""
PostgreSQL connection management for Metatron.

Provides SQLAlchemy engine and session management with connection pooling.

Usage:
    from metatron.postgres import get_session, init_db

    # Initialize database (create tables)
    init_db()

    # Use session context manager
    with get_session() as session:
        result = session.query(Workspace).all()

    # Or get session manually
    session = get_session()
    try:
        # ... work with session
        session.commit()
    finally:
        session.close()
"""
import atexit
from contextlib import contextmanager
from threading import Lock
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from metatron.config import POSTGRES_URL, setup_logging

logger = setup_logging(__name__)

_engine = None
_session_factory = None
_engine_lock = Lock()


def get_engine():
    """
    Get shared SQLAlchemy engine instance.

    Creates engine on first call with connection pooling configured.
    Subsequent calls return the same engine instance.

    Returns:
        SQLAlchemy Engine instance
    """
    global _engine

    if _engine is None:
        with _engine_lock:
            if _engine is None:
                if not POSTGRES_URL:
                    raise ValueError(
                        "POSTGRES_URL is not configured. "
                        "Set it in .env or environment variables."
                    )

                _engine = create_engine(
                    POSTGRES_URL,
                    pool_size=10,
                    max_overflow=20,
                    pool_pre_ping=True,  # Verify connections before use
                    pool_recycle=3600,   # Recycle connections after 1 hour
                    echo=False,          # Set True for SQL debugging
                )
                logger.info(f"PostgreSQL engine initialized (pool_size=10)")

    return _engine


def get_session_factory():
    """Get or create session factory."""
    global _session_factory

    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
        )

    return _session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Get a database session as context manager.

    Automatically commits on success, rolls back on exception.

    Usage:
        with get_session() as session:
            workspace = Workspace(name="test")
            session.add(workspace)
            # auto-commits on exit

    Yields:
        SQLAlchemy Session instance
    """
    factory = get_session_factory()
    session = factory()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """
    Initialize database - create all tables.

    Call this on application startup to ensure tables exist.
    Safe to call multiple times (uses CREATE IF NOT EXISTS).
    """
    from .models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("PostgreSQL tables initialized")


def close_db() -> None:
    """
    Close database connections.

    Call this on application shutdown to cleanly close all connections.
    """
    global _engine, _session_factory

    if _engine is not None:
        with _engine_lock:
            if _engine is not None:
                _engine.dispose()
                _engine = None
                _session_factory = None
                logger.info("PostgreSQL engine closed")


# Register cleanup on interpreter exit
atexit.register(close_db)
```

### ./metatron/postgres/models.py
```python
"""
SQLAlchemy models for Metatron PostgreSQL storage.

Models:
- Workspace: Project/tenant isolation
- User: User accounts
- WorkspaceMember: User-Workspace relationship
- Connection: External integrations (Jira, Confluence, etc.)
- Config: Key-value configuration storage
"""
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import (
    Column,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Integer,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Workspace(Base):
    """
    Workspace model for project/tenant isolation.

    Each workspace has its own:
    - Qdrant collection (vectors)
    - Memgraph subgraph (entities/relationships)
    - Configurations
    - Member access
    """
    __tablename__ = "workspaces"

    id = Column(String(64), primary_key=True)  # e.g., "ws_abc123" or "MTRNIX"
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=True)  # URL-friendly name
    description = Column(Text, nullable=True)

    is_default = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(64), nullable=True)  # User ID

    # Relationships
    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    connections = relationship("Connection", back_populates="workspace", cascade="all, delete-orphan")
    configs = relationship("Config", back_populates="workspace", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_workspaces_slug", "slug"),
        Index("ix_workspaces_is_default", "is_default"),
    )

    def __repr__(self):
        return f"<Workspace(id={self.id!r}, name={self.name!r})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
        }


class User(Base):
    """
    User model for authentication and access control.
    """
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)  # e.g., "user_abc123"
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(100), nullable=True)
    password_hash = Column(String(255), nullable=True)  # Nullable for SSO users

    role = Column(String(20), default="user", nullable=False)  # admin, user
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    # Relationships
    memberships = relationship("WorkspaceMember", back_populates="user", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_is_active", "is_active"),
    )

    def __repr__(self):
        return f"<User(id={self.id!r}, email={self.email!r})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excludes password_hash)."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class WorkspaceMember(Base):
    """
    User membership in a workspace with role.
    """
    __tablename__ = "workspace_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    role = Column(String(20), default="member", nullable=False)  # owner, admin, member
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="memberships")

    # Constraints
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
        Index("ix_workspace_members_user", "user_id"),
    )

    def __repr__(self):
        return f"<WorkspaceMember(workspace={self.workspace_id!r}, user={self.user_id!r}, role={self.role!r})>"


class Connection(Base):
    """
    External integration connection (Jira, Confluence, Google Docs, etc.).
    """
    __tablename__ = "connections"

    id = Column(String(64), primary_key=True)  # e.g., "conn_abc123"
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)

    type = Column(String(50), nullable=False)  # jira, confluence, gdocs, slack, etc.
    name = Column(String(100), nullable=True)  # Human-readable name

    # Configuration stored as JSON (credentials, URLs, etc.)
    config = Column(JSON, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="connections")

    # Indexes
    __table_args__ = (
        Index("ix_connections_workspace", "workspace_id"),
        Index("ix_connections_type", "type"),
    )

    def __repr__(self):
        return f"<Connection(id={self.id!r}, type={self.type!r}, workspace={self.workspace_id!r})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excludes sensitive config)."""
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "type": self.type,
            "name": self.name,
            "is_active": self.is_active,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Config(Base):
    """
    Key-value configuration storage per workspace.

    Can store workspace settings, LLM preferences, search parameters, etc.
    """
    __tablename__ = "configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)

    key = Column(String(100), nullable=False)  # e.g., "llm_provider", "search_limit"
    value = Column(JSON, nullable=True)  # JSON value for flexibility

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="configs")

    # Constraints
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_workspace_config_key"),
        Index("ix_configs_workspace", "workspace_id"),
    )

    def __repr__(self):
        return f"<Config(workspace={self.workspace_id!r}, key={self.key!r})>"
```

### ./metatron/processing/__init__.py
```python
"""
Document processing utilities.
"""
from metatron.processing.dates import (
    extract_date_from_text,
    extract_date_range,
    get_dates_in_range,
    MONTHS_RU,
    MONTHS_RU_TO_NUM,
)
from metatron.processing.html import process_rabbitmq_message
from metatron.processing.titles import extract_title_from_body, extract_title_from_markdown
from metatron.processing.translation import translate_to_english, translate_to_russian, is_russian
from metatron.processing.tabular import process_tabular_file, is_tabular_file

__all__ = [
    "extract_date_from_text",
    "extract_date_range",
    "get_dates_in_range",
    "MONTHS_RU",
    "MONTHS_RU_TO_NUM",
    "process_rabbitmq_message",
    "extract_title_from_body",
    "extract_title_from_markdown",
    "translate_to_english",
    "translate_to_russian",
    "is_russian",
    "process_tabular_file",
    "is_tabular_file",
]

```

### ./metatron/processing/dates.py
```python
"""
Date extraction and parsing utilities.
"""
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, List

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}

MONTHS_RU_TO_NUM = {v: k for k, v in MONTHS_RU.items()}

# English month names
MONTHS_EN = {
    1: "january", 2: "february", 3: "march", 4: "april",
    5: "may", 6: "june", 7: "july", 8: "august",
    9: "september", 10: "october", 11: "november", 12: "december"
}

MONTHS_EN_TO_NUM = {v: k for k, v in MONTHS_EN.items()}

# Days of week (Monday=0, Sunday=6)
DAYS_RU = {
    "понедельник": 0, "вторник": 1, "среда": 2, "среду": 2,
    "четверг": 3, "пятница": 4, "пятницу": 4,
    "суббота": 5, "субботу": 5, "воскресенье": 6
}

DAYS_EN = {
    "monday": 0, "tuesday": 1, "wednesday": 2,
    "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
}


def extract_date_from_text(text: str) -> Optional[str]:
    """
    Extract single ISO date (YYYY-MM-DD) from text.
    
    Supports:
        - ISO format: '2025-12-25'
        - Russian format: '25 декабря', '25 декабря 2025'
        - English format: 'December 25', 'December 25th', '25 December 2025'
        
    Args:
        text: Text to extract date from
        
    Returns:
        ISO date string or None
    """
    # ISO format
    iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if iso_match:
        return iso_match.group(1)
    
    # Russian format: "25 декабря" or "25 декабря 2025"
    ru_date = re.search(
        r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(\d{4}))?',
        text, re.IGNORECASE
    )
    if ru_date:
        day = int(ru_date.group(1))
        month = MONTHS_RU_TO_NUM.get(ru_date.group(2).lower(), 0)
        year = ru_date.group(3) or "2025"
        if month:
            return f"{year}-{month:02d}-{day:02d}"
    
    # English format: "December 25" or "December 25th" or "December 25, 2025"
    en_date1 = re.search(
        r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:[,\s]+(\d{4}))?',
        text, re.IGNORECASE
    )
    if en_date1:
        month = MONTHS_EN_TO_NUM.get(en_date1.group(1).lower(), 0)
        day = int(en_date1.group(2))
        year = en_date1.group(3) or "2025"
        if month:
            return f"{year}-{month:02d}-{day:02d}"
    
    # English format: "25 December" or "25th December 2025"
    en_date2 = re.search(
        r'(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+(\d{4}))?',
        text, re.IGNORECASE
    )
    if en_date2:
        day = int(en_date2.group(1))
        month = MONTHS_EN_TO_NUM.get(en_date2.group(2).lower(), 0)
        year = en_date2.group(3) or "2025"
        if month:
            return f"{year}-{month:02d}-{day:02d}"
    
    return None


def extract_date_range(text: str) -> Optional[Tuple[str, str]]:
    """
    Extract date range from text.
    
    Supports:
        - Relative: 'последняя неделя', 'прошлая неделя', 'последние 7 дней'
        - Relative: 'вчера', 'позавчера', 'сегодня'
        - Range: 'с 20 по 26 декабря'
        
    Args:
        text: Text to extract date range from
        
    Returns:
        Tuple of (start_date, end_date) in ISO format, or None
    """
    text_lower = text.lower()
    today = datetime.now()
    
    # "прошлый год", "в прошлом году", "последний год"
    if re.search(r'прошл\w*\s+год|в\s+прошлом\s+году|последн\w*\s+год', text_lower):
        last_year = today.year - 1
        start = datetime(last_year, 1, 1)
        end = datetime(last_year, 12, 31)
        return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    # "прошлый месяц", "в прошлом месяце", "последний месяц"
    if re.search(r'прошл\w*\s+месяц|в\s+прошлом\s+месяце|последн\w*\s+месяц', text_lower):
        # First day of current month
        first_of_current = today.replace(day=1)
        # Last day of previous month
        last_of_prev = first_of_current - timedelta(days=1)
        # First day of previous month
        first_of_prev = last_of_prev.replace(day=1)
        return (first_of_prev.strftime("%Y-%m-%d"), last_of_prev.strftime("%Y-%m-%d"))

    # "последняя неделя", "прошлая неделя", "на прошлой неделе"
    if re.search(r'последн\w*\s+недел|прошл\w*\s+недел', text_lower):
        end = today
        start = today - timedelta(days=7)
        return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    
    # "последние N дней"
    days_match = re.search(r'последни\w*\s+(\d+)\s+дн', text_lower)
    if days_match:
        days = int(days_match.group(1))
        end = today
        start = today - timedelta(days=days)
        return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    
    # "позавчера" (check before "вчера" since it contains "вчера")
    if "позавчера" in text_lower:
        day_before = today - timedelta(days=2)
        d = day_before.strftime("%Y-%m-%d")
        return (d, d)
    
    # "вчера"
    if "вчера" in text_lower:
        yesterday = today - timedelta(days=1)
        d = yesterday.strftime("%Y-%m-%d")
        return (d, d)
    
    # "сегодня"
    if "сегодня" in text_lower:
        d = today.strftime("%Y-%m-%d")
        return (d, d)
    
    # "с 20 по 26 декабря"
    range_match = re.search(
        r'с\s+(\d{1,2})\s+по\s+(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(\d{4}))?',
        text_lower
    )
    if range_match:
        day1, day2 = int(range_match.group(1)), int(range_match.group(2))
        month = MONTHS_RU_TO_NUM.get(range_match.group(3), 0)
        year = range_match.group(4) or str(today.year)
        if month:
            return (f"{year}-{month:02d}-{day1:02d}", f"{year}-{month:02d}-{day2:02d}")
    
    # === ENGLISH RELATIVE DATES ===

    # "last year"
    if "last year" in text_lower:
        last_year = today.year - 1
        start = datetime(last_year, 1, 1)
        end = datetime(last_year, 12, 31)
        return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    # "last month"
    if "last month" in text_lower:
        first_of_current = today.replace(day=1)
        last_of_prev = first_of_current - timedelta(days=1)
        first_of_prev = last_of_prev.replace(day=1)
        return (first_of_prev.strftime("%Y-%m-%d"), last_of_prev.strftime("%Y-%m-%d"))

    # "last week"
    if "last week" in text_lower:
        end = today
        start = today - timedelta(days=7)
        return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    
    # "yesterday"
    if "yesterday" in text_lower:
        yesterday = today - timedelta(days=1)
        d = yesterday.strftime("%Y-%m-%d")
        return (d, d)
    
    # "today"
    if "today" in text_lower:
        d = today.strftime("%Y-%m-%d")
        return (d, d)
    
    # "last N days"
    en_days_match = re.search(r'last\s+(\d+)\s+days?', text_lower)
    if en_days_match:
        days = int(en_days_match.group(1))
        end = today
        start = today - timedelta(days=days)
        return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    
    # === DAY OF WEEK (Russian) ===
    # "прошлый четверг", "в прошлую пятницу", "на прошлой неделе в среду"
    for day_name, day_num in DAYS_RU.items():
        if day_name in text_lower and ("прошл" in text_lower or "последн" in text_lower):
            # Find last occurrence of this weekday
            days_back = (today.weekday() - day_num) % 7
            if days_back == 0:
                days_back = 7  # If same day, go back a week
            target = today - timedelta(days=days_back)
            d = target.strftime("%Y-%m-%d")
            return (d, d)
    
    # === DAY OF WEEK (English) ===
    # "last Thursday", "last Monday"
    for day_name, day_num in DAYS_EN.items():
        if day_name in text_lower and "last" in text_lower:
            days_back = (today.weekday() - day_num) % 7
            if days_back == 0:
                days_back = 7
            target = today - timedelta(days=days_back)
            d = target.strftime("%Y-%m-%d")
            return (d, d)
    
    return None


def get_dates_in_range(start_date: str, end_date: str) -> List[str]:
    """
    Generate list of dates between start and end (inclusive).
    
    Args:
        start_date: Start date in ISO format
        end_date: End date in ISO format
        
    Returns:
        List of dates in ISO format
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    
    return dates

```

### ./metatron/processing/html.py
```python
"""
HTML processing and conversion to Markdown.
"""
import json
from typing import Union

from ftfy import fix_text
from html import unescape
from markdownify import markdownify as html_to_md

from metatron.utils import normalize_text


def process_rabbitmq_message(body: Union[bytes, str]) -> str:
    """
    Full processing of Confluence message from RabbitMQ (Airbyte):
    
    1) bytes|str → str
    2) Parse JSON, extract HTML from body.storage.value
    3) Decode \\uXXXX sequences to unicode
    4) Fix mojibake (â → →) via ftfy
    5) Convert HTML → Markdown
    6) Clean garbage characters
    
    Args:
        body: Raw message body from RabbitMQ
        
    Returns:
        Cleaned Markdown text
    """
    if isinstance(body, bytes):
        raw_text = body.decode("utf-8", errors="replace")
    else:
        raw_text = body

    # Try parsing as JSON (Airbyte format)
    html_content = raw_text
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict):
            # Extract HTML from body.storage.value
            html_content = data.get("body", {}).get("storage", {}).get("value", "")
            if not html_content:
                # Fallback to body.view.value
                html_content = data.get("body", {}).get("view", {}).get("value", "")
            if not html_content:
                # If no body, use title as fallback
                html_content = f"<h1>{data.get('title', 'Untitled')}</h1>"
    except (json.JSONDecodeError, TypeError):
        pass  # Not JSON — use as is

    # Decode \uXXXX → real unicode
    decoded = unescape(html_content)
    try:
        decoded = decoded.encode("utf-8").decode("unicode_escape")
    except Exception:
        pass  # If decoding error — keep as is

    # ftfy fixes mojibake like â€™
    decoded = fix_text(decoded)

    # HTML → Markdown
    markdown_text = html_to_md(decoded, heading_style="ATX").strip()

    # Clean problematic characters
    markdown_text = normalize_text(markdown_text)

    return markdown_text

```

### ./metatron/processing/tabular.py
```python
"""
Tabular data processing (CSV, Excel).

Converts tabular data to text format suitable for RAG indexing.
Each row is converted to key-value pairs for better semantic search.
"""
import io
from typing import List, Optional, Tuple

import pandas as pd

from metatron.config import setup_logging

logger = setup_logging(__name__)


def parse_csv(content: bytes, encoding: str = "utf-8") -> pd.DataFrame:
    """
    Parse CSV content into DataFrame.

    Args:
        content: Raw CSV bytes
        encoding: Text encoding (default utf-8)

    Returns:
        Parsed DataFrame
    """
    try:
        return pd.read_csv(io.BytesIO(content), encoding=encoding)
    except UnicodeDecodeError:
        # Try common encodings
        for enc in ["cp1251", "latin-1", "utf-16"]:
            try:
                return pd.read_csv(io.BytesIO(content), encoding=enc)
            except (UnicodeDecodeError, Exception):
                continue
        raise ValueError("Could not decode CSV with any supported encoding")


def parse_excel(content: bytes) -> pd.DataFrame:
    """
    Parse Excel content into DataFrame.

    Supports .xlsx (openpyxl) and .xls (xlrd if installed).

    Args:
        content: Raw Excel bytes

    Returns:
        Parsed DataFrame (first sheet)
    """
    return pd.read_excel(io.BytesIO(content), engine="openpyxl")


def dataframe_to_text(
    df: pd.DataFrame,
    max_rows: Optional[int] = None,
    include_row_numbers: bool = True,
) -> str:
    """
    Convert DataFrame to key-value text format.

    Each row becomes a line like:
    "Row 1: Column1: Value1, Column2: Value2, Column3: Value3"

    Args:
        df: Input DataFrame
        max_rows: Maximum rows to process (None = all)
        include_row_numbers: Include "Row N:" prefix

    Returns:
        Text representation of the table
    """
    if df.empty:
        return ""

    # Clean column names
    df.columns = [str(col).strip() for col in df.columns]

    # Limit rows if specified
    if max_rows and len(df) > max_rows:
        df = df.head(max_rows)
        logger.warning(f"Truncated table to {max_rows} rows")

    lines = []
    for idx, row in df.iterrows():
        pairs = []
        for col in df.columns:
            value = row[col]
            # Skip empty/NaN values
            if pd.isna(value) or str(value).strip() == "":
                continue
            # Clean and truncate long values
            value_str = str(value).strip()
            if len(value_str) > 500:
                value_str = value_str[:500] + "..."
            pairs.append(f"{col}: {value_str}")

        if pairs:
            row_text = ", ".join(pairs)
            if include_row_numbers:
                row_num = idx + 1 if isinstance(idx, int) else idx
                lines.append(f"Row {row_num}: {row_text}")
            else:
                lines.append(row_text)

    return "\n".join(lines)


def process_tabular_file(
    content: bytes,
    filename: str,
    max_rows: Optional[int] = 10000,
) -> Tuple[str, dict]:
    """
    Process CSV or Excel file and convert to text.

    Args:
        content: Raw file bytes
        filename: Original filename (used to detect format)
        max_rows: Maximum rows to process

    Returns:
        Tuple of (text_content, metadata)

    Raises:
        ValueError: If file format is not supported
    """
    filename_lower = filename.lower()

    # Detect format and parse
    if filename_lower.endswith(".csv"):
        df = parse_csv(content)
        file_type = "csv"
    elif filename_lower.endswith((".xlsx", ".xls")):
        df = parse_excel(content)
        file_type = "excel"
    else:
        raise ValueError(f"Unsupported tabular format: {filename}")

    # Convert to text
    text = dataframe_to_text(df, max_rows=max_rows)

    # Build metadata
    metadata = {
        "type": file_type,
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
    }

    logger.info(f"Processed {file_type} file '{filename}': {len(df)} rows, {len(df.columns)} columns")

    return text, metadata


def is_tabular_file(filename: str) -> bool:
    """Check if filename indicates a tabular format."""
    return filename.lower().endswith((".csv", ".xlsx", ".xls"))
```

### ./metatron/processing/titles.py
```python
"""
Title extraction from documents.
"""
import json
from typing import Optional, Union


def extract_title_from_body(body: Union[bytes, str]) -> Optional[str]:
    """
    Extract title from JSON message body (Confluence/Jira).
    
    Args:
        body: Raw message body
        
    Returns:
        Title string or None
    """
    try:
        if isinstance(body, bytes):
            raw = body.decode("utf-8", errors="replace")
        else:
            raw = body
        data = json.loads(raw)
        if isinstance(data, dict):
            return data.get("title") or data.get("key")
    except Exception:
        pass
    return None


def extract_title_from_markdown(md: str, body: Union[bytes, str] = None) -> str:
    """
    Extract title from document.
    
    Priority:
    1) title from JSON body (if provided)
    2) First '# ' header in markdown
    3) First non-empty line
    4) Default fallback
    
    Args:
        md: Markdown text
        body: Optional raw message body for JSON title extraction
        
    Returns:
        Document title
    """
    title = None
    
    if body:
        title = extract_title_from_body(body)
    
    if not title:
        lines = [l.strip() for l in md.splitlines()]
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break
        if not title:
            for line in lines:
                if line:
                    title = line[:80].strip()
                    break
    
    return title or "confluence_page"

```

### ./metatron/processing/translation.py
```python
"""
Translation utilities for multilingual support.
"""
from metatron.llm import chat_completion


def is_russian(text: str) -> bool:
    """Check if text contains Cyrillic characters (Russian)."""
    return any('\u0400' <= c <= '\u04FF' for c in text)


def is_english(text: str) -> bool:
    """Check if text is primarily English (Latin characters)."""
    latin_count = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    return latin_count > len(text) * 0.3


def translate_to_english(text: str) -> str:
    """
    Translate text to English using configured LLM provider.
    Returns original text if already English or translation fails.
    """
    if not text or not is_russian(text):
        return text

    try:
        result = chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "Translate the following text to English. Preserve formatting, names, and technical terms. Return ONLY the translation."
                },
                {"role": "user", "content": text}
            ],
            temperature=0.1,
            max_tokens=4000,
            timeout=60,
        )
        return result.strip()
    except Exception:
        pass
    return text


def translate_to_russian(text: str) -> str:
    """
    Translate text to Russian using configured LLM provider.
    Returns original text if already Russian or translation fails.
    """
    if not text or is_russian(text):
        return text

    try:
        result = chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "Translate the following text to Russian. Return ONLY the translation."
                },
                {"role": "user", "content": text}
            ],
            temperature=0.1,
            max_tokens=200,
            timeout=10,
        )
        return result.strip()
    except Exception:
        pass
    return text
```

### ./metatron/search/__init__.py
```python
"""
Search functionality.

All search functions are workspace-aware for multi-tenant data isolation.
"""
from metatron.search.hybrid import (
    HYBRID_SYSTEM_PROMPT,
    search_with_date_filter,
    hybrid_search_and_answer,
    translate_query_to_english,
    is_jira_query,
    is_jira_result,
    prioritize_results,
)

__all__ = [
    # Main search functions
    "HYBRID_SYSTEM_PROMPT",
    "search_with_date_filter",
    "hybrid_search_and_answer",
    # Helper functions
    "translate_query_to_english",
    "is_jira_query",
    "is_jira_result",
    "prioritize_results",
]

```

### ./metatron/search/hybrid.py
```python
"""
Hybrid search combining vector search (Qdrant) and graph search (Memgraph).

Search priority:
- Confluence/Documents first (main source of facts)
- Jira issues second (supplementary, surfaced for Jira-specific queries)

This module uses HybridVectorStore with BM25 sparse vectors
for better keyword matching combined with semantic search.

All functions are workspace-aware for multi-tenant data isolation.
"""
import json
import re
from typing import Any, Dict, List, Literal, Optional

from metatron.config import (
    setup_logging,
    SEARCH_MAX_TOTAL_CHARS,
    SEARCH_MAX_FRAGMENT_CHARS,
    SEARCH_POOL_MULTIPLIER,
    SEARCH_POOL_MIN,
    SEARCH_DATE_MULTIPLIER,
    SEARCH_JIRA_MULTIPLIER,
    SEARCH_GRAPH_RELATIONS_LIMIT,
    SEARCH_GRAPH_DEPTH,
    SEARCH_RELATED_DOCS_LIMIT,
    SEARCH_CONTEXT_EXTRA,
)
from metatron.llm import chat_completion
from metatron.processing import extract_date_from_text, extract_date_range, get_dates_in_range
from pydantic import BaseModel, Field
from metatron.indexers.hybrid_store_workspace import get_hybrid_store
from metatron.indexers.memgraph_workspace import (
    get_graph_entities,
    get_entities_by_doc_labels,
    get_graph_relationships,
    get_doc_labels_by_entities,
    get_related_documents,
)
from metatron.workspaces import get_workspace_manager
from metatron.metrics import timed

logger = setup_logging(__name__)


# ============================================================================
# Query Translation (Russian -> English)
# ============================================================================

@timed("translate_query")
def translate_query_to_english(query: str) -> str:
    """
    Translate Russian query to English for vector search.
    Documents are stored in English, so Russian queries need translation.
    Returns original query if already English or translation fails.
    """
    # Skip if query is English (no Cyrillic)
    if not any('\u0400' <= c <= '\u04FF' for c in query):
        return query

    try:
        translated = chat_completion(
            messages=[
                {"role": "system", "content": "Translate the following query to English. Return ONLY the translation, nothing else."},
                {"role": "user", "content": query}
            ],
            temperature=0.1,
            max_tokens=200,
            timeout=10,
        )
        return translated.strip()
    except Exception:
        pass
    return query


# ============================================================================
# Schema-guided routing + answer generation (team workflow)
# ============================================================================

def _extract_json_object(s: str) -> str:
    """
    Best-effort extraction of a JSON object from an LLM response.
    Handles code fences and leading text.
    """
    if not s:
        return "{}"
    # Drop common code fences
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    # Keep the outermost {...}
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return "{}"
    return s[start : end + 1]


def _extract_doc_labels(results: List[Dict]) -> List[str]:
    labels = []
    for mem in results:
        label = mem.get("doc_label")
        if not label:
            payload = mem.get("payload") or {}
            label = payload.get("doc_label")
        if label:
            labels.append(label)
    # Preserve order, remove duplicates
    return list(dict.fromkeys(labels))


class TeamWorkflowRoutingDecision(BaseModel):
    route: Literal["schema_guided_team_workflow", "default"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = ""


class TeamWorkflowSchemaAnswer(BaseModel):
    # NOTE: Placeholder schema — you can refine fields/steps later.
    time_period_the_user_asks: str
    who_is_asking: Literal[
        "Owner",
        "CEO",
        "analyst",
        "software-engineer",
        "DevOps",
        "guest",
        "worker",
    ]
    summary: str
    what_has_been_done: str
    next_steps: str
    blocker_and_risks: str



TEAM_WORKFLOW_ROUTING_SYSTEM_PROMPT = """
You are a routing classifier for a hybrid RAG assistant.
Decide whether the user's question is about team work / team workflow (processes, collaboration, roles, ceremonies, handoffs, sprint flow, delivery workflow).
Return STRICT JSON only (no markdown, no code fences).
"""


def should_use_team_workflow_schema(question: str) -> bool:
    """
    Returns True only when the question is about team work / team workflow.

    Implementation:
    - Fast keyword gate (avoids false positives + saves LLM calls)
    - If keyword gate triggers, confirm via DeepSeek JSON classifier
    """
    q = (question or "").strip()
    if not q:
        return False

    ql = q.lower()
    keyword_gate = [
        "team work",
        "teamwork",
        "team workflow",
        "workflow",
        "process",
        "processes",
        "collaboration",
        "handoff",
        "handoffs",
        "ceremony",
        "ceremonies",
        "sprint",
        "standup",
        "retrospective",
        "planning",
        "kanban",
        "scrum",
        "команд",
        "команда",
        "воркфлоу",
        "процесс",
        "процессы",
        "взаимодействие",
        "согласование",
        "передача",
    ]
    if not any(k in ql for k in keyword_gate):
        return False

    content = chat_completion(
        messages=[
            {"role": "system", "content": TEAM_WORKFLOW_ROUTING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "User question:\n"
                    f"{q}\n\n"
                    "Return JSON with fields:\n"
                    '- route: "schema_guided_team_workflow" or "default"\n'
                    "- confidence: number 0..1\n"
                    "- rationale: short string\n"
                ),
            },
        ],
        temperature=0.1,
        max_tokens=200,
        json_mode=True,
        timeout=20,
    )
    decision = TeamWorkflowRoutingDecision.model_validate_json(_extract_json_object(content))
    return decision.route == "schema_guided_team_workflow"


TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT = """
You are a hybrid RAG assistant. The user asked about team work / team workflow.
You MUST generate the response using the provided JSON schema (no markdown, no code fences).
Keep the final 'answer' concise and actionable.
CRITICAL: Match the 'answer' language to the question language.
"""


# ============================================================================
# Jira Detection Helpers
# ============================================================================

def is_jira_result(mem: dict) -> bool:
    """Check if a search result is from Jira."""
    # Check top-level type (from our date filtering)
    t = (mem.get("type") or "").lower()
    if t == "jira":
        return True
    # Check nested metadata (from mem0 search)
    meta = mem.get("metadata") or {}
    t = (meta.get("type") or "").lower()
    if t == "jira":
        return True
    # Fallback: heuristic on content (MTRNIX-123 pattern)
    mem_text = (mem.get("memory") or mem.get("data") or "")[:100]
    return bool(re.search(r"\b[A-Z]{2,}-\d+\b", mem_text))


def is_jira_query(query: str) -> bool:
    """Check if query is Jira-specific."""
    ql = query.lower()
    jira_keywords = ["jira", "ticket", "issue", "bug", "task", "mtrnix-", "тикет", "задача"]
    return (
        any(w in ql for w in jira_keywords)
        or bool(re.search(r"\b[A-Z]{2,}-\d+\b", query, flags=re.IGNORECASE))
    )


def prioritize_results(results: list, query: str, k: int) -> list:
    """
    Prioritize search results:
    - For Jira queries: Jira first, then docs for context
    - For date-based queries: include both docs and Jira (user wants everything from that period)
    - For other queries: docs first, Jira as supplement
    """
    jira_hits = [m for m in results if is_jira_result(m)]
    doc_hits = [m for m in results if not is_jira_result(m)]

    if is_jira_query(query):
        # Jira question: Jira first, then docs for context
        merged = jira_hits + doc_hits
    else:
        # Non-Jira question: docs first, then Jira for additional context
        # Don't completely exclude Jira - it may contain relevant info (especially for date queries)
        merged = doc_hits + jira_hits

    # Keep surplus for graph/LLM context
    return merged[:max(k + SEARCH_CONTEXT_EXTRA, SEARCH_POOL_MIN)]


HYBRID_SYSTEM_PROMPT = """
You are a hybrid question-answering system that combines vector search results and knowledge graph data.

You have:
1) User's question
2) Relevant text fragments from vector database
3) Entities and relationships from graph database
4) List of related documents

Your task:
- Answer the user's question in the SAME LANGUAGE as the question.
- Use text fragments as the primary source of facts.
- Confluence pages are the main source of information.
- Jira tickets (MTRNIX-XXX) are supplementary, less important than Confluence.
- Use entities and relationships from the graph to clarify context and explain connections.
- If there are non-trivial dependencies between entities, mention them.
- Do not invent facts that are not in the provided fragments.
- Respond with coherent text, not JSON or raw data listings.
- If the user greets you or engages in small talk (e.g., "Hello", "Hi", "Привет"), respond warmly and briefly describe your capabilities: you are a knowledge assistant that can answer questions about documents, find information by dates and topics, and explain relationships between entities in the knowledge base. In this case, DO NOT mention or reference any search results - just introduce yourself.

CRITICAL: Match the response language to the question language. English question = English answer. Russian question = Russian answer.

"""


@timed("search")
def search_with_date_filter(
    query: str,
    user_id: str = "user",
    k: int = 5,
    workspace_id: Optional[str] = None,
) -> list:
    """
    Hybrid search with date filtering (workspace-aware).

    Uses HybridVectorStore which combines:
    - Dense vectors (semantic search via nomic-embed-text)
    - Sparse vectors (BM25 keyword search)
    - Reciprocal Rank Fusion for combining results

    Supports:
        - Single date: '25 декабря', '2025-12-25'
        - Date ranges: 'последняя неделя', 'с 20 по 26 декабря'
        - Jira-specific queries: direct filter on type='jira'

    Args:
        query: Search query
        user_id: User identifier
        k: Number of results to return
        workspace_id: Workspace ID (uses active workspace if not provided)

    Returns:
        List of search results
    """
    # Get workspace
    if workspace_id is None:
        manager = get_workspace_manager()
        workspace = manager.get_active_workspace(user_id)
        workspace_id = workspace.workspace_id

    store = get_hybrid_store(workspace_id)
    
    # 1) Check for date range first (e.g., "последняя неделя")
    date_range = extract_date_range(query)
    if date_range:
        dates_list = get_dates_in_range(date_range[0], date_range[1])
        date_docs = store.search_by_date(dates_list, limit=k * SEARCH_DATE_MULTIPLIER)
        
        if date_docs:
            # Also run hybrid search to get related docs
            hybrid_results = store.hybrid_search(query, limit=k)
            seen = set(hash(d["memory"][:200]) for d in date_docs if d["memory"])
            for r in hybrid_results:
                content = r.get("memory") or ""
                if content:
                    h = hash(content[:200])
                    if h not in seen:
                        seen.add(h)
                        date_docs.append(r)
            return date_docs[:k]
    
    # 2) Check for single date
    target_date = extract_date_from_text(query)
    if target_date:
        date_docs = store.search_by_date([target_date], limit=k)
        
        if date_docs:
            # Fill remaining with hybrid search
            if len(date_docs) < k:
                hybrid_results = store.hybrid_search(query, limit=k)
                seen = set(hash(d["memory"][:200]) for d in date_docs if d["memory"])
                for r in hybrid_results:
                    content = r.get("memory") or ""
                    if content:
                        h = hash(content[:200])
                        if h not in seen:
                            seen.add(h)
                            date_docs.append(r)
            return date_docs[:k]
    
    # 3) For Jira-specific queries, get Jira results directly + hybrid search
    if is_jira_query(query):
        jira_docs = store.search_by_type("jira", limit=k * SEARCH_JIRA_MULTIPLIER)

        if jira_docs:
            # Also get hybrid search results for context
            hybrid_results = store.hybrid_search(query, limit=k)
            seen = set(hash(d["memory"][:200]) for d in jira_docs if d["memory"])
            for r in hybrid_results:
                content = r.get("memory") or ""
                if content:
                    h = hash(content[:200])
                    if h not in seen:
                        seen.add(h)
                        jira_docs.append(r)
            return jira_docs[:k * SEARCH_JIRA_MULTIPLIER]
    
    # 4) Regular hybrid search (dense + BM25 sparse)
    return store.hybrid_search(query, limit=k)


@timed("hybrid_search_and_answer")
def hybrid_search_and_answer(
    query: str,
    user_id: str = "user",
    k: int = 5,
    workspace_id: Optional[str] = None,
    intent_query: Optional[str] = None,
) -> str:
    """
    Hybrid search (workspace-aware):
    1) Translate query to English (if Russian)
    2) Vector search with date filtering (Qdrant) - larger pool
    3) Prioritize Confluence over Jira
    4) Graph enrichment (Memgraph) - entities and relationships
    5) LLM generates final answer

    Note: Jira tickets are less important than Confluence pages.

    Args:
        query: User question
        user_id: User identifier
        k: Number of vector results
        workspace_id: Workspace ID (uses active workspace if not provided)

    Returns:
        Generated answer
    """
    # Decide whether to use schema-guided generation based on the *current* user question
    routing_question = (intent_query or query or "").strip()
    use_schema_guided = should_use_team_workflow_schema(routing_question)

    # Get workspace
    if workspace_id is None:
        manager = get_workspace_manager()
        workspace = manager.get_active_workspace(user_id)
        workspace_id = workspace.workspace_id

    # 0) Detect query language and translate if needed
    is_russian_query = any('\u0400' <= c <= '\u04FF' for c in routing_question)
    response_language = "Russian" if is_russian_query else "English"
    search_query = translate_query_to_english(query) if is_russian_query else query

    # 1) Search with larger pool to avoid missing Jira issues
    pool_size = max(k * SEARCH_POOL_MULTIPLIER, SEARCH_POOL_MIN)
    raw_results = search_with_date_filter(
        search_query, user_id=user_id, k=pool_size, workspace_id=workspace_id
    )

    # 2) Prioritize: Confluence first, Jira second
    base = prioritize_results(raw_results, query, k)

    # 3) Truncate fragments to fit context limit (~16k tokens, safe margin)
    base_fragments = []
    total_chars = 0
    seen_text_hashes = set()
    for mem in base:
        text = mem.get("memory") or mem.get("data") or ""
        # Truncate individual fragment if too long
        if len(text) > SEARCH_MAX_FRAGMENT_CHARS:
            text = text[:SEARCH_MAX_FRAGMENT_CHARS] + "..."
        text_hash = hash(text[:200])
        if text_hash in seen_text_hashes:
            continue
        if total_chars + len(text) > SEARCH_MAX_TOTAL_CHARS:
            break
        base_fragments.append(text)
        seen_text_hashes.add(text_hash)
        total_chars += len(text)

    # 4) Graph enrichment using doc_label (fallback to text if legacy data)
    base_doc_labels = _extract_doc_labels(base)
    graph_entities = []
    graph_rels = []
    graph_docs = []
    entity_names = set()

    if base_doc_labels:
        graph_entities = get_entities_by_doc_labels(base_doc_labels, workspace_id)
    else:
        graph_entities = get_graph_entities(base_fragments, workspace_id)

    for ent in graph_entities:
        name = ent.get("name")
        if name:
            entity_names.add(name)
        for alias in ent.get("aliases", []) or []:
            entity_names.add(alias)

    if entity_names:
        graph_rels = get_graph_relationships(
            list(entity_names),
            workspace_id,
            max_depth=SEARCH_GRAPH_DEPTH,
        )
        for rel in graph_rels:
            if rel.get("source"):
                entity_names.add(rel["source"])
            if rel.get("target"):
                entity_names.add(rel["target"])

        if base_doc_labels:
            graph_docs = get_doc_labels_by_entities(list(entity_names), workspace_id)
        else:
            graph_docs = get_related_documents(base_fragments, workspace_id)

    # 5) Expand context with related document labels (if available)
    if base_doc_labels and graph_docs:
        related_labels = [
            d["doc_label"] for d in graph_docs
            if d.get("doc_label")
        ]
        extra_labels = [l for l in related_labels if l not in base_doc_labels]
        if extra_labels:
            store = get_hybrid_store(workspace_id)
            extra_results = store.search_by_doc_labels(
                extra_labels,
                limit=SEARCH_RELATED_DOCS_LIMIT,
            )
            for mem in extra_results:
                text = mem.get("memory") or mem.get("data") or ""
                if len(text) > SEARCH_MAX_FRAGMENT_CHARS:
                    text = text[:SEARCH_MAX_FRAGMENT_CHARS] + "..."
                text_hash = hash(text[:200])
                if text_hash in seen_text_hashes:
                    continue
                if total_chars + len(text) > SEARCH_MAX_TOTAL_CHARS:
                    break
                base_fragments.append(text)
                seen_text_hashes.add(text_hash)
                total_chars += len(text)

    # 5) Generate answer with LLM
    user_content = (
        f"RESPOND IN {response_language.upper()} ONLY.\n\n"
        "User question:\n"
        f"{query}\n\n"
        "Vector search results (texts):\n"
        f"{json.dumps(base_fragments, ensure_ascii=False, indent=2)}\n\n"
        "Graph entities:\n"
        f"{json.dumps(graph_entities, ensure_ascii=False, indent=2)}\n\n"
        "Entity relationships:\n"
        f"{json.dumps(graph_rels, ensure_ascii=False, indent=2)}\n\n"
        "Related documents:\n"
        f"{json.dumps(graph_docs, ensure_ascii=False, indent=2)}\n\n"
        f"Provide a coherent answer in {response_language}."
    )

    if use_schema_guided:
        schema_content = (
            f"RESPOND IN {response_language.upper()} ONLY.\n\n"
            "User question:\n"
            f"{routing_question}\n\n"
            "Vector search results (texts):\n"
            f"{json.dumps(base_fragments, ensure_ascii=False, indent=2)}\n\n"
            "Graph entities:\n"
            f"{json.dumps(graph_entities, ensure_ascii=False, indent=2)}\n\n"
            "Entity relationships:\n"
            f"{json.dumps(graph_rels, ensure_ascii=False, indent=2)}\n\n"
            "Related documents:\n"
            f"{json.dumps(graph_docs, ensure_ascii=False, indent=2)}\n\n"
            "Return STRICT JSON with this schema:\n"
            "{\n"
            '  "question": string,\n'
            '  "intent": "team_workflow",\n'
            '  "steps": [string, ...],\n'
            '  "key_points": [string, ...],\n'
            '  "risks": [string, ...],\n'
            '  "answer": string\n'
            "}\n\n"
            "IMPORTANT: 'steps' can be placeholder steps for now.\n"
        )
        content = chat_completion(
            messages=[
                {"role": "system", "content": TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT},
                {"role": "user", "content": schema_content},
            ],
            temperature=0.2,
            json_mode=True,
            timeout=60,
        )
        schema_answer = TeamWorkflowSchemaAnswer.model_validate_json(_extract_json_object(content))
        return schema_answer.answer.strip()

    answer = chat_completion(
        messages=[
            {"role": "system", "content": HYBRID_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        timeout=60,
    )

    return answer.strip()

```

### ./metatron/utils.py
```python
"""
Utility functions for Metatron.
"""
import time
import threading
import logging
from datetime import datetime, UTC
from typing import List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from cachetools import TTLCache

from metatron.config import setup_logging, DEFAULT_WORKSPACE_ID, OLLAMA_URL

logger = setup_logging(__name__)

_quiet_mode = False
_print_lock = threading.Lock()


def set_quiet_mode(quiet: bool) -> None:
    """Set quiet mode for background printing."""
    global _quiet_mode
    _quiet_mode = quiet


def bg_print(*args, **kwargs) -> None:
    """
    Print for background threads - silent in quiet mode.

    Deprecated: Use logger.info() directly instead.
    This function now uses logging internally for consistency.
    """
    if not _quiet_mode:
        message = " ".join(str(arg) for arg in args)
        logger.info(message)


def safe_input(prompt: str = "") -> str:
    """Safe input wrapper."""
    return input(prompt)


def normalize_text(s: str) -> str:
    """Remove invalid characters (surrogates, etc.)."""
    return s.encode("utf-8", "ignore").decode("utf-8")


def normalize_workspace_id(workspace_id: str = None) -> str:
    """
    Normalize workspace ID to canonical form.

    Args:
        workspace_id: Raw workspace ID (None, "default", or actual ID)

    Returns:
        Normalized workspace ID (DEFAULT_WORKSPACE_ID for None/"default", stripped otherwise)

    Examples:
        normalize_workspace_id(None)        -> DEFAULT_WORKSPACE_ID
        normalize_workspace_id("default")   -> DEFAULT_WORKSPACE_ID
        normalize_workspace_id("  my-ws ")  -> "my-ws"
        normalize_workspace_id("MTRNIX")    -> "MTRNIX"
    """
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


def build_doc_label(
    source_id: str,
    user_id: str = "user",
    workspace_id: Optional[str] = None,
    upload_time: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Build a stable document label to link vector and graph representations.

    Returns:
        Tuple of (doc_label, upload_time)
    """
    workspace_id = normalize_workspace_id(workspace_id)
    if upload_time is None:
        upload_time = datetime.now(UTC).isoformat()
    doc_label = f"{workspace_id}:{user_id}:{source_id}:{upload_time}"
    return doc_label, upload_time


def chunk_text(text: str, max_chars: int = 2500, overlap: int = 200) -> list[str]:
    """
    Split text into overlapping chunks.

    Args:
        text: Text to split
        max_chars: Maximum characters per chunk
        overlap: Overlap between chunks

    Returns:
        List of text chunks
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap

    return chunks


# ============================================================================
# HTTP Connection Pooling
# ============================================================================

_http_session: requests.Session = None
_http_session_lock = threading.Lock()


def get_http_session() -> requests.Session:
    """
    Get shared HTTP session with connection pooling.

    Uses connection pooling to reuse TCP connections and avoid socket exhaustion
    during high-volume operations (e.g., mass document indexing).

    Features:
        - Connection pooling (10 connections, 20 max per host)
        - Automatic retries (3 attempts with exponential backoff)
        - Thread-safe singleton

    Returns:
        Configured requests.Session instance

    Example:
        session = get_http_session()
        resp = session.post("http://ollama:11434/api/embeddings", json={...})
    """
    global _http_session

    if _http_session is None:
        with _http_session_lock:
            if _http_session is None:
                _http_session = requests.Session()

                # Retry strategy: 3 attempts with exponential backoff
                retry = Retry(
                    total=3,
                    backoff_factor=0.5,
                    status_forcelist=[502, 503, 504],
                    allowed_methods=["GET", "POST"],
                )

                # Connection pooling adapter
                adapter = HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=20,
                    max_retries=retry,
                )

                _http_session.mount("http://", adapter)
                _http_session.mount("https://", adapter)

                logger.debug("HTTP session initialized with connection pooling")

    return _http_session


def close_http_session() -> None:
    """Close the shared HTTP session (for cleanup on shutdown)."""
    global _http_session

    if _http_session is not None:
        with _http_session_lock:
            if _http_session is not None:
                _http_session.close()
                _http_session = None
                logger.debug("HTTP session closed")


# ============================================================================
# Embedding Cache
# ============================================================================

# Cache: 1000 embeddings, 1 hour TTL
# Memory: ~3MB for 1000 x 768-dim vectors
_embedding_cache: TTLCache = TTLCache(maxsize=1000, ttl=3600)
_embedding_cache_lock = threading.Lock()

# Stats for monitoring
_embedding_cache_hits = 0
_embedding_cache_misses = 0


def get_cached_embedding(text: str, model: str = "nomic-embed-text:latest") -> List[float]:
    """
    Get dense embedding with caching.

    Uses TTL cache to avoid redundant Ollama API calls for repeated text.
    Thread-safe with lock protection.

    Args:
        text: Text to embed
        model: Ollama embedding model name

    Returns:
        List of floats (embedding vector)

    Example:
        embedding = get_cached_embedding("Hello world")
        # Second call returns cached result
        embedding2 = get_cached_embedding("Hello world")
    """
    global _embedding_cache_hits, _embedding_cache_misses

    # Use text hash as cache key (text can be very long)
    cache_key = hash((text, model))

    # Check cache first
    with _embedding_cache_lock:
        if cache_key in _embedding_cache:
            _embedding_cache_hits += 1
            return _embedding_cache[cache_key]

    # Cache miss - fetch from Ollama with retry
    _embedding_cache_misses += 1

    session = get_http_session()
    last_error = None

    for attempt in range(3):
        try:
            resp = session.post(
                f"http://{OLLAMA_URL}/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=30
            )
            resp.raise_for_status()
            embedding = resp.json()["embedding"]
            break
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(1 * (attempt + 1))  # 1s, 2s backoff
                logger.warning(f"Embedding retry {attempt + 1}/3: {e}")
            else:
                logger.error(f"Embedding failed after 3 attempts: {e}")
                raise

    # Store in cache
    with _embedding_cache_lock:
        _embedding_cache[cache_key] = embedding

    return embedding


def get_embedding_cache_stats() -> dict:
    """Get embedding cache statistics."""
    return {
        "size": len(_embedding_cache),
        "maxsize": _embedding_cache.maxsize,
        "ttl": _embedding_cache.ttl,
        "hits": _embedding_cache_hits,
        "misses": _embedding_cache_misses,
        "hit_rate": round(_embedding_cache_hits / max(_embedding_cache_hits + _embedding_cache_misses, 1) * 100, 1),
    }


def clear_embedding_cache() -> None:
    """Clear embedding cache."""
    global _embedding_cache_hits, _embedding_cache_misses

    with _embedding_cache_lock:
        _embedding_cache.clear()
        _embedding_cache_hits = 0
        _embedding_cache_misses = 0
        logger.debug("Embedding cache cleared")

```

### ./metatron/workspaces/__init__.py
```python
"""
Workspace management module for Metatron.

Provides isolation between different datasets by allowing users to create
separate workspaces with independent Qdrant collections and Memgraph subgraphs.
"""

from .manager import WorkspaceManager, get_workspace_manager
from .models import Workspace, WorkspaceStats

__all__ = [
    "WorkspaceManager",
    "get_workspace_manager",
    "Workspace",
    "WorkspaceStats",
]
```

### ./metatron/workspaces/manager.py
```python
"""
Workspace manager for handling workspace operations.

Manages workspace creation, deletion, listing, and activation.
Supports persistent storage in Memgraph for sync between local and server.
"""
import uuid
import logging
from typing import Dict, List, Optional
from threading import Lock

from metatron.config import (
    DEFAULT_WORKSPACE_ID,
    DEFAULT_WORKSPACE_NAME,
    WORKSPACE_PERSISTENCE,
)
from metatron.utils import normalize_workspace_id
from .models import Workspace, WorkspaceStats

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """
    Manager for workspace operations.

    Supports both in-memory and persistent storage (Memgraph).
    When using Memgraph persistence, workspaces are synced between
    local development and server environments.
    """

    def __init__(self, use_persistence: bool = True):
        """
        Initialize workspace manager.

        Args:
            use_persistence: Whether to use persistent storage (default: True)
        """
        self._workspaces: Dict[str, Workspace] = {}
        self._active_workspace: Dict[str, str] = {}  # user_id -> workspace_id
        self._lock = Lock()
        self._stats: Dict[str, WorkspaceStats] = {}

        # Persistence layer
        self._persistence = None
        self._use_persistence = use_persistence and WORKSPACE_PERSISTENCE == "memgraph"

        if self._use_persistence:
            try:
                from .persistence import get_workspace_persistence
                self._persistence = get_workspace_persistence()
                self._load_from_persistence()
                logger.info("Workspace persistence enabled (Memgraph)")
            except Exception as e:
                logger.warning(f"Failed to initialize persistence, using in-memory: {e}")
                self._use_persistence = False

        # Ensure default workspace exists
        self._ensure_default_workspace()

    def _load_from_persistence(self):
        """Load workspaces and stats from persistent storage."""
        if not self._persistence:
            return

        try:
            workspaces = self._persistence.load_all_workspaces()
            for ws in workspaces:
                self._workspaces[ws.workspace_id] = ws
            logger.info(f"Loaded {len(workspaces)} workspaces from Memgraph")
        except Exception as e:
            logger.error(f"Failed to load workspaces from persistence: {e}")

        # Load stats
        try:
            self._stats = self._persistence.load_all_workspace_stats()
            logger.info(f"Loaded stats for {len(self._stats)} workspaces from Memgraph")
        except Exception as e:
            logger.error(f"Failed to load workspace stats from persistence: {e}")

    def _ensure_default_workspace(self):
        """Ensure default workspace exists."""
        default_id = DEFAULT_WORKSPACE_ID

        if default_id not in self._workspaces:
            default = Workspace(
                workspace_id=default_id,
                name=DEFAULT_WORKSPACE_NAME,
                description=f"Main workspace for {default_id} project",
                user_id="system"
            )
            self._workspaces[default_id] = default

            # Save to persistence
            if self._persistence:
                try:
                    self._persistence.save_workspace(default)
                except Exception as e:
                    logger.warning(f"Failed to persist default workspace: {e}")

            logger.info(f"Created default workspace: {default_id}")

    def create_workspace(
        self,
        name: str,
        description: Optional[str] = None,
        user_id: str = "user",
        workspace_id: Optional[str] = None
    ) -> Workspace:
        """
        Create a new workspace.

        Args:
            name: Human-readable name
            description: Optional description
            user_id: Owner user ID
            workspace_id: Optional custom workspace ID (auto-generated if not provided)

        Returns:
            Created workspace

        Raises:
            ValueError: If workspace with same ID already exists
        """
        with self._lock:
            if workspace_id is None:
                workspace_id = f"ws_{uuid.uuid4().hex[:8]}"

            if workspace_id in self._workspaces:
                raise ValueError(f"Workspace '{workspace_id}' already exists")

            workspace = Workspace(
                workspace_id=workspace_id,
                name=name,
                description=description,
                user_id=user_id
            )

            self._workspaces[workspace_id] = workspace

            # Save to persistence
            if self._persistence:
                try:
                    self._persistence.save_workspace(workspace)
                except Exception as e:
                    logger.warning(f"Failed to persist workspace: {e}")

            return workspace

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        """
        Get workspace by ID.

        Args:
            workspace_id: Workspace ID (or "default" as alias for DEFAULT_WORKSPACE_ID)

        Returns:
            Workspace if found, None otherwise
        """
        workspace_id = normalize_workspace_id(workspace_id)
        return self._workspaces.get(workspace_id)

    def list_workspaces(self, user_id: Optional[str] = None) -> List[Workspace]:
        """
        List all workspaces.

        Args:
            user_id: Optional user ID to filter by

        Returns:
            List of workspaces
        """
        workspaces = list(self._workspaces.values())

        if user_id:
            default_id = DEFAULT_WORKSPACE_ID
            workspaces = [
                w for w in workspaces
                if w.user_id == user_id or w.workspace_id == default_id
            ]

        # Sort by creation time (newest first)
        workspaces.sort(key=lambda w: w.created_at or "", reverse=True)

        return workspaces

    def delete_workspace(self, workspace_id: str) -> bool:
        """
        Delete a workspace.

        Args:
            workspace_id: Workspace ID to delete

        Returns:
            True if deleted, False if not found

        Raises:
            ValueError: If trying to delete default workspace
        """
        default_id = DEFAULT_WORKSPACE_ID

        with self._lock:
            if workspace_id == default_id:
                raise ValueError(f"Cannot delete default workspace '{default_id}'")

            if workspace_id not in self._workspaces:
                return False

            # Deactivate for all users
            for uid, ws_id in list(self._active_workspace.items()):
                if ws_id == workspace_id:
                    self._active_workspace[uid] = default_id
                    if self._persistence:
                        try:
                            self._persistence.save_active_workspace(uid, default_id)
                        except Exception:
                            pass

            del self._workspaces[workspace_id]

            # Delete from persistence
            if self._persistence:
                try:
                    self._persistence.delete_workspace(workspace_id)
                except Exception as e:
                    logger.warning(f"Failed to delete workspace from persistence: {e}")

            return True

    def set_active_workspace(self, user_id: str, workspace_id: str) -> bool:
        """
        Set active workspace for a user.

        Args:
            user_id: User ID
            workspace_id: Workspace ID to activate

        Returns:
            True if set successfully, False if workspace not found
        """
        if workspace_id not in self._workspaces:
            return False

        with self._lock:
            self._active_workspace[user_id] = workspace_id

            # Save to persistence
            if self._persistence:
                try:
                    self._persistence.save_active_workspace(user_id, workspace_id)
                except Exception as e:
                    logger.warning(f"Failed to persist active workspace: {e}")

            return True

    def get_active_workspace(self, user_id: str) -> Workspace:
        """
        Get active workspace for a user.

        Args:
            user_id: User ID

        Returns:
            Active workspace (defaults to DEFAULT_WORKSPACE_ID if not set)
        """
        default_id = DEFAULT_WORKSPACE_ID

        # Check local cache first
        workspace_id = self._active_workspace.get(user_id)

        # If not in cache, try to load from persistence
        if workspace_id is None and self._persistence:
            try:
                workspace_id = self._persistence.load_active_workspace(user_id)
                if workspace_id:
                    self._active_workspace[user_id] = workspace_id
            except Exception:
                pass

        # Fall back to default
        if workspace_id is None:
            workspace_id = default_id

        return self._workspaces.get(workspace_id, self._workspaces[default_id])

    def update_workspace_stats(self, workspace_id: str, stats: WorkspaceStats) -> None:
        """
        Update workspace statistics.

        Args:
            workspace_id: Workspace ID
            stats: New statistics
        """
        self._stats[workspace_id] = stats

        # Persist to storage
        if self._persistence:
            try:
                self._persistence.save_workspace_stats(workspace_id, stats)
            except Exception as e:
                logger.warning(f"Failed to persist workspace stats: {e}")

    def get_workspace_stats(self, workspace_id: str) -> WorkspaceStats:
        """
        Get workspace statistics.

        Args:
            workspace_id: Workspace ID

        Returns:
            Workspace statistics (empty if not available)
        """
        # Check memory cache first
        if workspace_id in self._stats:
            return self._stats[workspace_id]

        # Try to load from persistence
        if self._persistence:
            try:
                stats = self._persistence.load_workspace_stats(workspace_id)
                if stats:
                    self._stats[workspace_id] = stats
                    return stats
            except Exception as e:
                logger.warning(f"Failed to load workspace stats from persistence: {e}")

        return WorkspaceStats()

    def workspace_exists(self, workspace_id: str) -> bool:
        """
        Check if workspace exists.

        Args:
            workspace_id: Workspace ID (or "default" as alias for DEFAULT_WORKSPACE_ID)

        Returns:
            True if workspace exists
        """
        workspace_id = normalize_workspace_id(workspace_id)
        return workspace_id in self._workspaces

    def refresh_from_persistence(self) -> None:
        """Reload workspaces from persistent storage."""
        if self._persistence:
            self._load_from_persistence()
            self._ensure_default_workspace()


# Global instance
_workspace_manager: Optional[WorkspaceManager] = None
_manager_lock = Lock()


def get_workspace_manager() -> WorkspaceManager:
    """
    Get or create global workspace manager instance.

    Returns:
        WorkspaceManager instance
    """
    global _workspace_manager

    if _workspace_manager is None:
        with _manager_lock:
            if _workspace_manager is None:
                _workspace_manager = WorkspaceManager()

    return _workspace_manager
```

### ./metatron/workspaces/models.py
```python
"""
Data models for workspace management.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
import json


@dataclass
class WorkspaceStats:
    """Statistics for a workspace."""
    document_count: int = 0
    entity_count: int = 0
    jira_issue_count: int = 0
    last_upload_time: Optional[str] = None
    total_chunks: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkspaceStats":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class Workspace:
    """Workspace model for data isolation."""
    workspace_id: str  # Unique identifier (UUID or slug)
    name: str  # Human-readable name
    description: Optional[str] = None
    created_at: Optional[str] = None
    user_id: str = "user"
    is_active: bool = True
    config: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Set default values."""
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.config is None:
            self.config = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Workspace":
        """Create from dictionary."""
        return cls(**data)
    
    def get_qdrant_collection_name(self) -> str:
        """Get Qdrant collection name for this workspace."""
        return f"mem_docs_hybrid_{self.workspace_id}"
    
    def is_default(self) -> bool:
        """Check if this is the default workspace."""
        from metatron.config import DEFAULT_WORKSPACE_ID
        return self.workspace_id == DEFAULT_WORKSPACE_ID
```

### ./metatron/workspaces/persistence.py
```python
"""
Workspace persistence layer.

Stores workspace metadata in Memgraph for sync between local and server.
"""
import json
import logging
from typing import List, Optional, Callable, TypeVar, Dict
from datetime import datetime, timezone
from functools import wraps

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from metatron.config import MEMGRAPH_URI, MEMGRAPH_USER, MEMGRAPH_PASS

from .models import Workspace, WorkspaceStats

logger = logging.getLogger(__name__)

# Type variable for generic return type
T = TypeVar('T')


def with_retry(max_attempts: int = 3, reconnect: bool = True):
    """
    Decorator for retrying database operations on connection errors.

    Args:
        max_attempts: Maximum number of retry attempts
        reconnect: Whether to reconnect on failure

    Handles:
        - ServiceUnavailable: Memgraph/Neo4j connection lost
        - SessionExpired: Session timeout
        - BrokenPipeError: Connection broken
        - ConnectionError: Generic connection issues
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self, *args, **kwargs) -> T:
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(self, *args, **kwargs)
                except (ServiceUnavailable, SessionExpired, BrokenPipeError, ConnectionError) as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_attempts}): {e}. Retrying..."
                        )
                        if reconnect:
                            self._close()
                    else:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                except Exception as e:
                    # Check for connection-related errors in message
                    error_msg = str(e).lower()
                    if any(x in error_msg for x in ["broken pipe", "connection", "failed to write"]):
                        last_error = e
                        if attempt < max_attempts - 1:
                            logger.warning(
                                f"{func.__name__} connection error (attempt {attempt + 1}/{max_attempts}): {e}. Retrying..."
                            )
                            if reconnect:
                                self._close()
                            continue
                    logger.error(f"{func.__name__} failed: {e}")
                    raise
            # All retries exhausted
            if last_error:
                raise last_error
        return wrapper
    return decorator


class MemgraphWorkspacePersistence:
    """Persist workspaces to Memgraph graph database."""

    def __init__(self):
        self._driver = None

    def _get_driver(self):
        """Get or create Neo4j/Memgraph driver."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                MEMGRAPH_URI,
                auth=(MEMGRAPH_USER, MEMGRAPH_PASS)
            )
        return self._driver

    def _close(self):
        """Close driver connection."""
        if self._driver:
            self._driver.close()
            self._driver = None

    @with_retry(max_attempts=3)
    def save_workspace(self, workspace: Workspace) -> None:
        """
        Save or update workspace in Memgraph.

        Args:
            workspace: Workspace to save
        """
        driver = self._get_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (w:Workspace {workspace_id: $workspace_id})
                SET w.name = $name,
                    w.description = $description,
                    w.created_at = $created_at,
                    w.user_id = $user_id,
                    w.is_active = $is_active,
                    w.config = $config,
                    w.updated_at = $updated_at
                """,
                {
                    "workspace_id": workspace.workspace_id,
                    "name": workspace.name,
                    "description": workspace.description or "",
                    "created_at": workspace.created_at,
                    "user_id": workspace.user_id,
                    "is_active": workspace.is_active,
                    "config": json.dumps(workspace.config or {}),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            logger.debug(f"Saved workspace '{workspace.workspace_id}' to Memgraph")

    @with_retry(max_attempts=3)
    def load_workspace(self, workspace_id: str) -> Optional[Workspace]:
        """
        Load workspace from Memgraph.

        Args:
            workspace_id: Workspace ID to load

        Returns:
            Workspace if found, None otherwise
        """
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (w:Workspace {workspace_id: $workspace_id})
                RETURN w
                """,
                {"workspace_id": workspace_id}
            )
            record = result.single()
            if record:
                node = record["w"]
                return self._node_to_workspace(node)
            return None

    @with_retry(max_attempts=3)
    def load_all_workspaces(self) -> List[Workspace]:
        """
        Load all workspaces from Memgraph.

        Returns:
            List of all workspaces
        """
        driver = self._get_driver()
        workspaces = []
        with driver.session() as session:
            result = session.run("MATCH (w:Workspace) RETURN w")
            for record in result:
                node = record["w"]
                workspace = self._node_to_workspace(node)
                if workspace:
                    workspaces.append(workspace)
            logger.debug(f"Loaded {len(workspaces)} workspaces from Memgraph")
        return workspaces

    @with_retry(max_attempts=3)
    def delete_workspace(self, workspace_id: str) -> bool:
        """
        Delete workspace from Memgraph.

        Args:
            workspace_id: Workspace ID to delete

        Returns:
            True if deleted, False otherwise
        """
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (w:Workspace {workspace_id: $workspace_id})
                DELETE w
                RETURN count(w) as deleted
                """,
                {"workspace_id": workspace_id}
            )
            record = result.single()
            deleted = record["deleted"] > 0 if record else False
            if deleted:
                logger.debug(f"Deleted workspace '{workspace_id}' from Memgraph")
            return deleted

    @with_retry(max_attempts=3)
    def save_active_workspace(self, user_id: str, workspace_id: str) -> None:
        """
        Save active workspace setting for a user.

        Args:
            user_id: User ID
            workspace_id: Active workspace ID
        """
        driver = self._get_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (s:WorkspaceSetting {user_id: $user_id})
                SET s.active_workspace_id = $workspace_id,
                    s.updated_at = $updated_at
                """,
                {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    @with_retry(max_attempts=3)
    def load_active_workspace(self, user_id: str) -> Optional[str]:
        """
        Load active workspace setting for a user.

        Args:
            user_id: User ID

        Returns:
            Active workspace ID or None
        """
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (s:WorkspaceSetting {user_id: $user_id})
                RETURN s.active_workspace_id as workspace_id
                """,
                {"user_id": user_id}
            )
            record = result.single()
            if record:
                return record["workspace_id"]
            return None

    @with_retry(max_attempts=3)
    def save_workspace_stats(self, workspace_id: str, stats: WorkspaceStats) -> None:
        """
        Save workspace statistics to Memgraph.

        Args:
            workspace_id: Workspace ID
            stats: Statistics to save
        """
        driver = self._get_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (s:WorkspaceStats {workspace_id: $workspace_id})
                SET s.document_count = $document_count,
                    s.entity_count = $entity_count,
                    s.jira_issue_count = $jira_issue_count,
                    s.total_chunks = $total_chunks,
                    s.last_upload_time = $last_upload_time,
                    s.updated_at = $updated_at
                """,
                {
                    "workspace_id": workspace_id,
                    "document_count": stats.document_count,
                    "entity_count": stats.entity_count,
                    "jira_issue_count": stats.jira_issue_count,
                    "total_chunks": stats.total_chunks,
                    "last_upload_time": stats.last_upload_time,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            logger.debug(f"Saved stats for workspace '{workspace_id}'")

    @with_retry(max_attempts=3)
    def load_workspace_stats(self, workspace_id: str) -> Optional[WorkspaceStats]:
        """
        Load workspace statistics from Memgraph.

        Args:
            workspace_id: Workspace ID

        Returns:
            WorkspaceStats if found, None otherwise
        """
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (s:WorkspaceStats {workspace_id: $workspace_id})
                RETURN s
                """,
                {"workspace_id": workspace_id}
            )
            record = result.single()
            if record:
                node = record["s"]
                return WorkspaceStats(
                    document_count=node.get("document_count", 0),
                    entity_count=node.get("entity_count", 0),
                    jira_issue_count=node.get("jira_issue_count", 0),
                    total_chunks=node.get("total_chunks", 0),
                    last_upload_time=node.get("last_upload_time"),
                )
            return None

    @with_retry(max_attempts=3)
    def load_all_workspace_stats(self) -> Dict[str, WorkspaceStats]:
        """
        Load all workspace statistics from Memgraph.

        Returns:
            Dict mapping workspace_id to WorkspaceStats
        """
        driver = self._get_driver()
        stats_dict = {}
        with driver.session() as session:
            result = session.run("MATCH (s:WorkspaceStats) RETURN s")
            for record in result:
                node = record["s"]
                workspace_id = node.get("workspace_id")
                if workspace_id:
                    stats_dict[workspace_id] = WorkspaceStats(
                        document_count=node.get("document_count", 0),
                        entity_count=node.get("entity_count", 0),
                        jira_issue_count=node.get("jira_issue_count", 0),
                        total_chunks=node.get("total_chunks", 0),
                        last_upload_time=node.get("last_upload_time"),
                    )
            logger.debug(f"Loaded stats for {len(stats_dict)} workspaces")
        return stats_dict

    def _node_to_workspace(self, node) -> Optional[Workspace]:
        """Convert Memgraph node to Workspace object."""
        try:
            config_str = node.get("config", "{}")
            config = json.loads(config_str) if config_str else {}

            return Workspace(
                workspace_id=node["workspace_id"],
                name=node.get("name", ""),
                description=node.get("description") or None,
                created_at=node.get("created_at"),
                user_id=node.get("user_id", "user"),
                is_active=node.get("is_active", True),
                config=config,
            )
        except Exception as e:
            logger.error(f"Failed to convert node to workspace: {e}")
            return None


# Singleton instance
_persistence: Optional[MemgraphWorkspacePersistence] = None


def get_workspace_persistence() -> MemgraphWorkspacePersistence:
    """Get workspace persistence instance."""
    global _persistence
    if _persistence is None:
        _persistence = MemgraphWorkspacePersistence()
    return _persistence
```

### ./scripts/cleanup.py
```python
#!/usr/bin/env python3
"""
Database cleanup CLI for Metatron.

Usage:
    # Preview what would be deleted
    python scripts/cleanup.py --preview

    # Clean specific workspace
    ALLOW_CLEANUP=true python scripts/cleanup.py --workspace ws_123

    # Clean ALL data (dangerous!)
    ALLOW_CLEANUP=true python scripts/cleanup.py --all

Examples:
    # Safe preview (no data deleted)
    python scripts/cleanup.py --preview

    # Delete workspace data
    ALLOW_CLEANUP=true python scripts/cleanup.py --workspace ws_561e2673 --yes

    # Delete everything (requires typing confirmation)
    ALLOW_CLEANUP=true python scripts/cleanup.py --all
"""
import argparse
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metatron.db.cleanup import (
    cleanup_workspace,
    cleanup_all,
    get_cleanup_preview,
    CleanupError,
    ALLOW_CLEANUP,
)


def print_preview(preview: dict) -> None:
    """Pretty print cleanup preview."""
    print("\n" + "=" * 60)
    print("📊 CLEANUP PREVIEW")
    print("=" * 60)

    print(f"\n🔐 Cleanup allowed: {preview['cleanup_allowed']}")
    if not preview['cleanup_allowed']:
        print("   Set ALLOW_CLEANUP=true to enable cleanup operations")

    # Qdrant
    print("\n📦 Qdrant:")
    qdrant = preview.get("qdrant", {})
    if "error" in qdrant:
        print(f"   ❌ Error: {qdrant['error']}")
    else:
        collections = qdrant.get("collections", [])
        total_points = qdrant.get("total_points", 0)
        print(f"   Collections: {len(collections)}")
        print(f"   Total points: {total_points}")
        for col in collections:
            print(f"      - {col['name']}: {col['points']} points")

    # Memgraph
    print("\n🔷 Memgraph:")
    memgraph = preview.get("memgraph", {})
    if "error" in memgraph:
        print(f"   ❌ Error: {memgraph['error']}")
    else:
        print(f"   Nodes: {memgraph.get('nodes', 0)}")
        print(f"   Relationships: {memgraph.get('relationships', 0)}")
        workspaces = memgraph.get("workspaces", [])
        if workspaces:
            print("   Per workspace:")
            for ws in workspaces[:10]:
                print(f"      - {ws['workspace_id']}: {ws['nodes']} nodes")
            if len(workspaces) > 10:
                print(f"      ... and {len(workspaces) - 10} more workspaces")

    print("\n" + "=" * 60)


def print_result(result: dict, operation: str) -> None:
    """Pretty print cleanup result."""
    print("\n" + "=" * 60)
    print(f"🧹 CLEANUP RESULT: {operation}")
    print("=" * 60)

    status = result.get("status", "unknown")
    status_emoji = "✅" if status == "completed" else "⚠️" if status == "partial" else "⏭️"
    print(f"\nStatus: {status_emoji} {status}")

    # Qdrant result
    if "qdrant" in result:
        qdrant = result["qdrant"]
        print(f"\n📦 Qdrant: {qdrant.get('status', 'unknown')}")
        if qdrant.get("status") == "deleted":
            print(f"   Points deleted: {qdrant.get('points_deleted', 0)}")
        elif qdrant.get("status") == "completed":
            print(f"   Collections deleted: {qdrant.get('collections_deleted', 0)}")
            print(f"   Total points deleted: {qdrant.get('total_points_deleted', 0)}")
        elif qdrant.get("error"):
            print(f"   ❌ Error: {qdrant['error']}")

    # Memgraph result
    if "memgraph" in result:
        memgraph = result["memgraph"]
        print(f"\n🔷 Memgraph: {memgraph.get('status', 'unknown')}")
        if memgraph.get("status") == "deleted":
            print(f"   Nodes deleted: {memgraph.get('nodes_deleted', 0)}")
            if "relationships_deleted" in memgraph:
                print(f"   Relationships deleted: {memgraph.get('relationships_deleted', 0)}")
        elif memgraph.get("error"):
            print(f"   ❌ Error: {memgraph['error']}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Metatron database cleanup utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--preview",
        action="store_true",
        help="Preview what would be deleted (safe, no changes)"
    )
    group.add_argument(
        "--workspace",
        type=str,
        metavar="ID",
        help="Clean specific workspace by ID"
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Clean ALL data from ALL databases (dangerous!)"
    )

    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt (for workspace cleanup only)"
    )

    args = parser.parse_args()

    # Preview mode - always safe
    if args.preview:
        preview = get_cleanup_preview()
        print_preview(preview)
        return 0

    # Check if cleanup is allowed
    if not ALLOW_CLEANUP:
        print("\n❌ Cleanup is disabled!")
        print("   Set ALLOW_CLEANUP=true environment variable to enable.")
        print("\n   Example:")
        print("   ALLOW_CLEANUP=true python scripts/cleanup.py --preview")
        return 1

    # Workspace cleanup
    if args.workspace:
        workspace_id = args.workspace

        if not args.yes:
            print(f"\n⚠️  WARNING: This will delete ALL data for workspace '{workspace_id}'!")
            print("   This action cannot be undone.\n")
            confirm = input(f"Type '{workspace_id}' to confirm: ").strip()
            if confirm != workspace_id:
                print("\n❌ Cleanup cancelled.")
                return 1

        try:
            result = cleanup_workspace(workspace_id, confirm=True)
            print_result(result, f"Workspace: {workspace_id}")
            return 0 if result["status"] == "completed" else 1
        except CleanupError as e:
            print(f"\n❌ Error: {e}")
            return 1

    # Full cleanup
    if args.all:
        print("\n" + "🚨" * 20)
        print("\n⚠️  DANGER: This will delete ALL data from ALL databases!")
        print("   - All Qdrant collections (vectors)")
        print("   - All Memgraph nodes and relationships (graph)")
        print("   - All workspaces except default")
        print("\n   This action CANNOT be undone!")
        print("\n" + "🚨" * 20)

        confirm = input("\nType 'DELETE ALL DATA' to confirm: ").strip()
        if confirm != "DELETE ALL DATA":
            print("\n❌ Cleanup cancelled.")
            return 1

        try:
            result = cleanup_all(confirm=True)
            print_result(result, "ALL DATA")
            return 0 if result["status"] == "completed" else 1
        except CleanupError as e:
            print(f"\n❌ Error: {e}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
```

### ./start.py
```python
#!/usr/bin/env python3
"""
Metatron API Server - main startup script.

Usage: python start.py
"""
import os
import sys

print("=" * 70)
print("  METATRON API SERVER")
print("=" * 70)
print()

# Load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Check LLM provider configuration
llm_provider = os.environ.get("LLM_PROVIDER", "deepseek")
llm_configured = False

if llm_provider == "deepseek" and os.environ.get("DEEPSEEK_API_KEY"):
    llm_configured = True
    print(f"  LLM: DeepSeek (model: {os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')})")
elif llm_provider == "openrouter" and os.environ.get("OPENROUTER_API_KEY"):
    llm_configured = True
    print(f"  LLM: OpenRouter (model: {os.environ.get('OPENROUTER_MODEL', 'meta-llama/llama-3.1-8b-instruct')})")
elif llm_provider == "ollama":
    llm_configured = True
    print(f"  LLM: Ollama (model: {os.environ.get('OLLAMA_LLM_MODEL', 'llama3')})")
elif llm_provider == "custom" and os.environ.get("CUSTOM_LLM_URL"):
    llm_configured = True
    print(f"  LLM: Custom ({os.environ.get('CUSTOM_LLM_URL')})")

if not llm_configured:
    print("  WARNING: LLM provider not configured!")
    print()
    print("  Configure one of the providers in .env:")
    print("    # DeepSeek (default)")
    print("    DEEPSEEK_API_KEY=sk-xxx")
    print()
    print("    # Or OpenRouter")
    print("    LLM_PROVIDER=openrouter")
    print("    OPENROUTER_API_KEY=sk-or-xxx")
    print()
    print("    # Or local Ollama")
    print("    LLM_PROVIDER=ollama")
    print("    OLLAMA_LLM_MODEL=llama3")
    print()

print()
print("=" * 70)
print("  Server starting on http://0.0.0.0:8000")
print("  Open in browser: http://localhost:8000")
print("  API docs: http://localhost:8000/docs")
print("=" * 70)
print()
print("  Press Ctrl+C to stop")
print()

if __name__ == "__main__":
    import uvicorn
    from metatron.api import app

    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### ./vizualize_graph.py
```python
# visualize_graph.py

from neo4j import GraphDatabase
import matplotlib.pyplot as plt
import networkx as nx


NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "user"
NEO4J_PASS = "pass"


def load_graph_from_memgraph(limit_entities: int = 50, limit_rels: int = 200):
    """
    Забираем из Memgraph:
    - узлы Entity и Document
    - связи MENTIONS и RELATION
    Строим networkx.Graph.
    """
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    G = nx.DiGraph()

    try:
        with driver.session() as session:
            # Узлы-сущности
            ent_res = session.run(
                """
                MATCH (e:Entity)
                RETURN e.name AS name, e.type AS type
                LIMIT $limit_entities
                """,
                {"limit_entities": limit_entities},
            )
            for r in ent_res:
                G.add_node(r["name"], label=r["name"], ntype="entity", etype=r["type"])

            # Узлы-документы
            doc_res = session.run(
                """
                MATCH (d:Document)
                RETURN d.doc_id AS id, d.file_name AS file_name
                LIMIT 100
                """
            )
            for r in doc_res:
                doc_label = r["file_name"] or r["id"]
                G.add_node(r["id"], label=doc_label, ntype="document")

            # Связи Document -[MENTIONS]-> Entity
            mention_res = session.run(
                """
                MATCH (d:Document)-[:MENTIONS]->(e:Entity)
                RETURN d.doc_id AS doc_id, e.name AS ent_name
                LIMIT $limit_rels
                """,
                {"limit_rels": limit_rels},
            )
            for r in mention_res:
                if G.has_node(r["doc_id"]) and G.has_node(r["ent_name"]):
                    G.add_edge(r["doc_id"], r["ent_name"], etype="MENTIONS")

            # Связи Entity -[RELATION {type: ...}]-> Entity
            rel_res = session.run(
                """
                MATCH (e1:Entity)-[r:RELATION]->(e2:Entity)
                RETURN e1.name AS source, e2.name AS target, r.type AS rel_type
                LIMIT $limit_rels
                """,
                {"limit_rels": limit_rels},
            )
            for r in rel_res:
                if G.has_node(r["source"]) and G.has_node(r["target"]):
                    G.add_edge(
                        r["source"],
                        r["target"],
                        etype="RELATION",
                        rtype=r["rel_type"],
                    )
    finally:
        driver.close()

    return G


def visualize_graph(G: nx.DiGraph):
    """
    Простейшая визуализация:
    - документы — квадратами
    - сущности — кругами
    - подписи узлов — label
    - подписи рёбер RELATION — type связи
    """
    plt.figure(figsize=(14, 10))
    pos = nx.spring_layout(G, k=0.7, iterations=50)

    # Разделяем узлы по типу
    doc_nodes = [n for n, d in G.nodes(data=True) if d.get("ntype") == "document"]
    ent_nodes = [n for n, d in G.nodes(data=True) if d.get("ntype") == "entity"]

    # Документы
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=doc_nodes,
        node_shape="s",
        node_color="#ffcc00",
        node_size=800,
        label="Documents",
    )

    # Сущности
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=ent_nodes,
        node_shape="o",
        node_color="#1f78b4",
        node_size=600,
        label="Entities",
    )

    # Рёбра
    nx.draw_networkx_edges(G, pos, edge_color="#999999", arrows=True, arrowsize=15)

    # Подписи узлов
    labels = {n: d.get("label", n) for n, d in G.nodes(data=True)}
    nx.draw_networkx_labels(G, pos, labels, font_size=8)

    # Подписи рёбер только для RELATION
    edge_labels = {}
    for u, v, d in G.edges(data=True):
        if d.get("etype") == "RELATION":
            edge_labels[(u, v)] = d.get("rtype", "")
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=7)

    plt.axis("off")
    plt.legend(scatterpoints=1)
    plt.title("Document–Entity Graph from Memgraph")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    G = load_graph_from_memgraph(limit_entities=100, limit_rels=200)
    print(f"Loaded graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    visualize_graph(G)
```

### requirements.txt
```
# =============================================================================
# Metatron - All Dependencies (for backward compatibility)
# =============================================================================
#
# RECOMMENDED: Use split requirements for faster installs:
#   pip install -r requirements/base.txt     # Core (~25 packages)
#   pip install -r requirements/dev.txt      # Core + Testing
#   pip install -r requirements/prod.txt     # Production (base + gunicorn)
#
# This file includes all dependencies for full compatibility.
# =============================================================================

-r requirements/prod.txt
-r requirements/dev.txt
```

### docker-compose.yml
```
version: "3"

services:
  memgraph:
    image: memgraph/memgraph-mage:latest
    container_name: memgraph-mage
    ports:
      - "7687:7687"
      - "7444:7444"
    volumes:
      - mg_lib:/var/lib/memgraph
      - mg_log:/var/log/memgraph
      - mg_etc:/etc/memgraph
    environment:
      - MEMGRAPH_USER=user
      - MEMGRAPH_PASSWORD=pass
    command: ["--log-level=TRACE"]
    healthcheck:
      test: ["CMD-SHELL", "echo 'RETURN 0;' | mgconsole || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 3

  lab:
    image: memgraph/lab:latest
    container_name: memgraph-lab
    ports:
      - "3000:3000" # Web UI
    depends_on:
      - memgraph
    environment:
      - QUICK_CONNECT_MG_HOST=memgraph
      - QUICK_CONNECT_MG_PORT=7687

  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_storage:/qdrant/storage
    environment:
      QDRANT__SERVICE__GRPC_PORT: 6334

volumes:
  mg_lib:
  mg_log:
  mg_etc:
  qdrant_storage:
```

### .env.example
```
# =============================================================================
# Metatron Environment Configuration
# =============================================================================
# Скопируй в .env и настрой под своё окружение:
#   cp .env.example .env
#
# Для локальной разработки раскомментируй METATRON_HOST=localhost
# =============================================================================

# Основной хост (влияет на все сервисы, если не переопределены)
# METATRON_HOST=localhost
METATRON_HOST=metattron.ximi.group

# -----------------------------------------------------------------------------
# RabbitMQ
# -----------------------------------------------------------------------------
# RABBITMQ_HOST=localhost
# RABBITMQ_PORT=5672
# RABBITMQ_USER=metatron
# RABBITMQ_PASS=metatron

# -----------------------------------------------------------------------------
# Memgraph (Graph DB)
# -----------------------------------------------------------------------------
# MEMGRAPH_HOST=localhost
# MEMGRAPH_PORT=7687
# MEMGRAPH_USER=user
# MEMGRAPH_PASS=pass

# -----------------------------------------------------------------------------
# Qdrant (Vector DB)
# -----------------------------------------------------------------------------
# QDRANT_HOST=localhost
# QDRANT_PORT=6333

# -----------------------------------------------------------------------------
# Ollama (Embeddings)
# -----------------------------------------------------------------------------
# OLLAMA_HOST=localhost
# OLLAMA_PORT=11434

# =============================================================================
# LLM Configuration (Multi-Provider Support)
# =============================================================================
# Provider selection: deepseek (default), openrouter, ollama, custom
# LLM_PROVIDER=deepseek

# Optional: Override the model (each provider has sensible defaults)
# LLM_MODEL=deepseek-chat

# Optional: Fallback provider when primary fails
# LLM_FALLBACK_PROVIDER=ollama
# LLM_FALLBACK_MODEL=llama3

# -----------------------------------------------------------------------------
# DeepSeek (default provider)
# -----------------------------------------------------------------------------
DEEPSEEK_API_KEY=sk-your-key-here
# DEEPSEEK_MODEL=deepseek-chat

# -----------------------------------------------------------------------------
# OpenRouter (access to Claude, GPT, Llama, Mistral, etc.)
# -----------------------------------------------------------------------------
# OPENROUTER_API_KEY=sk-or-xxx
# OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct
# Other models: anthropic/claude-3-haiku, openai/gpt-4-turbo, mistralai/mistral-7b-instruct

# -----------------------------------------------------------------------------
# Ollama (local LLM for chat - separate from embeddings)
# -----------------------------------------------------------------------------
# OLLAMA_LLM_HOST=http://localhost:11434  # Falls back to OLLAMA_HOST if not set
# OLLAMA_LLM_MODEL=llama3
# Other models: mistral, codellama, phi, gemma

# -----------------------------------------------------------------------------
# Custom OpenAI-compatible server (vLLM, LocalAI, text-generation-webui, etc.)
# -----------------------------------------------------------------------------
# CUSTOM_LLM_URL=http://localhost:8080/v1/chat/completions
# CUSTOM_LLM_API_KEY=  # Optional, some servers don't require auth
# CUSTOM_LLM_MODEL=default

# =============================================================================
# Workspace Configuration
# =============================================================================
# Default workspace (used for main project data)
DEFAULT_WORKSPACE_ID=MTRNIX
DEFAULT_WORKSPACE_NAME=MTRNIX Workspace

# Persistence: memgraph (shared between local/server), file, none
WORKSPACE_PERSISTENCE=memgraph

# -----------------------------------------------------------------------------
# Queues (обычно менять не нужно)
# -----------------------------------------------------------------------------
# CONFLUENCE_QUEUE=confluence_pages
# JIRA_QUEUE=jira_issues
```

### Dockerfile
```
FROM python:3.12-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

ENV DEEPSEEK_API_KEY="sk-79e82614397c4a3ca9cb1c39ce4480ff"
ENV METATRON_HOST="metattron.ximi.group"

CMD ["uvicorn", "metatron.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

