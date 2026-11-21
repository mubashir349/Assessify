"""Access codes and PINs exist only for Active students.

Inactive / Pending / removed students no longer hold a code: the column becomes nullable and its unique rule
applies only to issued codes (a filtered unique index, because SQL Server allows just one NULL in a plain unique
column). Existing non-Active students lose their code and PIN.

Revision ID: c5d8e1f2a3b4
Revises: a91b2c3d4e5f
Create Date: 2026-11-21
"""
from alembic import op
import sqlalchemy as sa

revision = "c5d8e1f2a3b4"
down_revision = "a91b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("candidates", schema=None) as batch_op:
        batch_op.drop_constraint("uq_candidates_access_code", type_="unique")
        batch_op.alter_column("access_code", existing_type=sa.String(length=20), nullable=True)
        batch_op.create_index(
            "uq_candidates_code_issued", ["access_code"], unique=True,
            mssql_where=sa.text("access_code IS NOT NULL"),
            sqlite_where=sa.text("access_code IS NOT NULL"),
        )
    op.execute("UPDATE candidates SET access_code = NULL, pin = NULL WHERE status <> 'Active' OR is_deleted = 1")


def downgrade():
    # Every row needs a code again: give those without one a placeholder that nobody can guess or use.
    if op.get_bind().dialect.name == "mssql":
        op.execute("UPDATE candidates SET access_code = 'X' + RIGHT('0000000' + CAST(id AS VARCHAR(10)), 7) "
                   "WHERE access_code IS NULL")
    else:
        op.execute("UPDATE candidates SET access_code = 'X' || substr('0000000' || id, -7) WHERE access_code IS NULL")
    with op.batch_alter_table("candidates", schema=None) as batch_op:
        batch_op.drop_index("uq_candidates_code_issued")
        batch_op.alter_column("access_code", existing_type=sa.String(length=20), nullable=False)
        batch_op.create_unique_constraint("uq_candidates_access_code", ["access_code"])
