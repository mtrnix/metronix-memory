"""Add chat_threads and chat_messages tables for persistent chat history (MTRNIX-353, T3).

Creates two tables to replace the in-memory ``_conversation_history`` used
by the legacy ``chat.py`` route. One thread per ``(workspace_id, user_id)``
pair in the MVP. Messages cascade-delete when the thread is deleted.

Revision ID: 022
Revises: 021
Create Date: 2026-05-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "022"
down_revision: str | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgcrypto provides gen_random_uuid() used for default PKs
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "chat_threads",
        sa.Column(
            "thread_id",
            sa.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_chat_threads_workspace_user",
        ),
    )
    op.create_index("ix_chat_threads_user_idx", "chat_threads", ["user_id"])
    op.create_index("ix_chat_threads_workspace_idx", "chat_threads", ["workspace_id"])

    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "thread_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("chat_threads.thread_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("citations_json", sa.JSON, nullable=True),
        sa.Column("tool_calls_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'tool')",
            name="ck_chat_messages_role",
        ),
    )
    op.create_index(
        "ix_chat_messages_thread_created_idx",
        "chat_messages",
        ["thread_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_thread_created_idx", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_threads_workspace_idx", table_name="chat_threads")
    op.drop_index("ix_chat_threads_user_idx", table_name="chat_threads")
    op.drop_table("chat_threads")
    # pgcrypto is intentionally NOT dropped — it may be used by other tables.
