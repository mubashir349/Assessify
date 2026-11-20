"""Roster status and safe removal; manual question-bank title metadata.

Revision ID: a91b2c3d4e5f
Revises: 7b79df321fc9
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "a91b2c3d4e5f"
down_revision = "7b79df321fc9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("candidates", schema=None) as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=12), nullable=False,
                                      server_default=sa.text("'Active'")))
        batch_op.add_column(sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch_op.create_check_constraint("ck_candidates_status_valid",
                                         "status IN ('Active','Inactive','Pending')")
        batch_op.drop_index("uq_candidates_test_roll")
        batch_op.create_index(
            "uq_candidates_test_roll", ["test_id", "roll_number"], unique=True,
            mssql_where=sa.text("is_deleted = 0 AND roll_number IS NOT NULL"),
            sqlite_where=sa.text("is_deleted = 0 AND roll_number IS NOT NULL"),
        )
        batch_op.create_index("ix_candidates_test_status_deleted", ["test_id", "status", "is_deleted"], unique=False)
        batch_op.create_index("ix_candidates_status", ["status"], unique=False)
        batch_op.create_index("ix_candidates_is_deleted", ["is_deleted"], unique=False)

    with op.batch_alter_table("generation_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("bank_title", sa.Unicode(length=150), nullable=True))


def downgrade():
    with op.batch_alter_table("generation_attempts", schema=None) as batch_op:
        batch_op.drop_column("bank_title")

    with op.batch_alter_table("candidates", schema=None) as batch_op:
        batch_op.drop_index("ix_candidates_is_deleted")
        batch_op.drop_index("ix_candidates_status")
        batch_op.drop_index("ix_candidates_test_status_deleted")
        batch_op.drop_index("uq_candidates_test_roll")
        batch_op.create_index("uq_candidates_test_roll", ["test_id", "roll_number"], unique=True,
                              mssql_where=sa.text("roll_number IS NOT NULL"),
                              sqlite_where=sa.text("roll_number IS NOT NULL"))
        batch_op.drop_constraint("ck_candidates_status_valid", type_="check")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("is_deleted")
        batch_op.drop_column("status")
