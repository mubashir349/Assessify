"""phase 9: lenient roster (email, roll number, date of birth optional; phone; PIN)

Revision ID: c4e9a7d2b351
Revises: e8a79c7ba991
Create Date: 2026-11-10 14:30:00

The roll number stays unique inside one test, but only when it is filled in. SQL Server lets a plain unique
constraint hold one NULL only, so it becomes a filtered unique index (WHERE roll_number IS NOT NULL).

Existing candidates keep their data and keep signing in with their date of birth.
Downgrading fails if some candidate has no email, roll number or date of birth (fill those in first).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4e9a7d2b351'
down_revision = 'e8a79c7ba991'
branch_labels = None
depends_on = None

ROLL_FILLED = sa.text("roll_number IS NOT NULL")


def upgrade():
    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.drop_constraint('uq_candidates_test_roll', type_='unique')
        batch_op.alter_column('email', existing_type=sa.String(length=255), nullable=True)
        batch_op.alter_column('roll_number', existing_type=sa.Unicode(length=50), nullable=True)
        batch_op.alter_column('date_of_birth', existing_type=sa.Date(), nullable=True)
        batch_op.add_column(sa.Column('phone', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('pin', sa.String(length=6), nullable=True))
    op.create_index('uq_candidates_test_roll', 'candidates', ['test_id', 'roll_number'], unique=True,
                    mssql_where=ROLL_FILLED, sqlite_where=ROLL_FILLED)


def downgrade():
    op.drop_index('uq_candidates_test_roll', table_name='candidates')
    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.drop_column('pin')
        batch_op.drop_column('phone')
        batch_op.alter_column('date_of_birth', existing_type=sa.Date(), nullable=False)
        batch_op.alter_column('roll_number', existing_type=sa.Unicode(length=50), nullable=False)
        batch_op.alter_column('email', existing_type=sa.String(length=255), nullable=False)
        batch_op.create_unique_constraint('uq_candidates_test_roll', ['test_id', 'roll_number'])
