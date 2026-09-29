"""Initial schema: meetings, transcript segments with a per-meeting sequence, insights.

Databases created by the application's former ``Base.metadata.create_all()``
startup hook already have these tables, minus ``transcript_segments.sequence``
and ``ix_meetings_started_at``. On such a database this revision adds the
missing pieces (numbering existing segments by timestamp) instead of failing
on CREATE TABLE, so it can be brought under Alembic without manual steps.

Revision ID: 0001
Revises:
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEQUENCE_CONSTRAINT = "uq_transcript_segments_meeting_sequence"
STARTED_AT_INDEX = "ix_meetings_started_at"


def upgrade() -> None:
    if op.get_context().as_sql:
        existing: set[str] = set()
        inspector = None
    else:
        inspector = sa.inspect(op.get_bind())
        existing = set(inspector.get_table_names())

    if "meetings" not in existing:
        op.create_table(
            "meetings",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if inspector is None or STARTED_AT_INDEX not in {
        index["name"] for index in inspector.get_indexes("meetings")
    }:
        op.create_index(STARTED_AT_INDEX, "meetings", ["started_at"])

    if "transcript_segments" not in existing:
        op.create_table(
            "transcript_segments",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("meeting_id", sa.String(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("speaker", sa.String(length=100), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("timestamp", sa.Float(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("is_final", sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("meeting_id", "sequence", name=SEQUENCE_CONSTRAINT),
        )
    elif inspector is not None:
        _add_sequence_to_legacy_segments(inspector)

    if "meeting_insights" not in existing:
        op.create_table(
            "meeting_insights",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("meeting_id", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("action_items", sa.JSON(), nullable=False),
            sa.Column("decisions", sa.JSON(), nullable=False),
            sa.Column("questions_raised", sa.JSON(), nullable=False),
            sa.Column("follow_up_email", sa.Text(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("meeting_id"),
        )


def _add_sequence_to_legacy_segments(inspector: sa.Inspector) -> None:
    columns = {column["name"] for column in inspector.get_columns("transcript_segments")}
    if "sequence" not in columns:
        op.add_column("transcript_segments", sa.Column("sequence", sa.Integer(), nullable=True))
        # Timestamps restarted at zero on every reconnect before this revision,
        # so this order is the best available approximation for old rows.
        op.execute(
            """
            UPDATE transcript_segments AS segment
            SET sequence = ordered.position
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY meeting_id ORDER BY "timestamp", id)
                           AS position
                FROM transcript_segments
            ) AS ordered
            WHERE segment.id = ordered.id
            """
        )
        op.alter_column("transcript_segments", "sequence", nullable=False)

    constraints = {c["name"] for c in inspector.get_unique_constraints("transcript_segments")}
    if SEQUENCE_CONSTRAINT not in constraints:
        op.create_unique_constraint(
            SEQUENCE_CONSTRAINT, "transcript_segments", ["meeting_id", "sequence"]
        )


def downgrade() -> None:
    op.drop_table("meeting_insights")
    op.drop_table("transcript_segments")
    op.drop_index(STARTED_AT_INDEX, table_name="meetings")
    op.drop_table("meetings")
