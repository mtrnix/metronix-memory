"""Add explicit server-side grants for workspace-scoped agents.

Revision ID: 032
Revises: 031
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "032"
down_revision: str | None = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_access_grants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("principal_user_id", sa.String(128), nullable=False),
        sa.Column("capability", sa.String(16), nullable=False),
        sa.Column("grant_type", sa.String(16), nullable=False),
        sa.Column("granted_by_user_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "capability IN ('read', 'write', 'admin')", name="ck_agent_access_capability"
        ),
        sa.CheckConstraint(
            "grant_type IN ('owner', 'delegate')", name="ck_agent_access_grant_type"
        ),
    )
    op.create_index(
        "ix_agent_access_grants_lookup",
        "agent_access_grants",
        ["workspace_id", "agent_id", "principal_user_id"],
    )
    op.create_index(
        "uq_agent_access_grants_active",
        "agent_access_grants",
        ["workspace_id", "agent_id", "principal_user_id", "capability", "grant_type"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.execute(
        """
        INSERT INTO agent_access_grants (
            id, workspace_id, agent_id, principal_user_id, capability,
            grant_type, granted_by_user_id
        )
        SELECT
            'owner_' || md5(workspace_id || ':' || id || ':' || created_by),
            workspace_id, id, created_by, 'admin', 'owner', created_by
        FROM agents
        WHERE created_by <> '' AND created_by <> 'system'
        """
    )


def downgrade() -> None:
    op.drop_index("uq_agent_access_grants_active", table_name="agent_access_grants")
    op.drop_index("ix_agent_access_grants_lookup", table_name="agent_access_grants")
    op.drop_table("agent_access_grants")
