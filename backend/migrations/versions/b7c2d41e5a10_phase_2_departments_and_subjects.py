"""phase 2: departments and subjects

Revision ID: b7c2d41e5a10
Revises: 81a3992619aa
Create Date: 2026-10-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c2d41e5a10'
down_revision = '81a3992619aa'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('departments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('mode', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("mode IN ('general','field')", name=op.f('ck_departments_mode_valid')),
    sa.CheckConstraint("level IN ('Undergraduate','Masters','PhD')", name=op.f('ck_departments_level_valid')),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], name=op.f('fk_departments_institution_id_institutions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_departments')),
    sa.UniqueConstraint('institution_id', 'level', 'name', name='uq_departments_institution_level_name')
    )
    with op.batch_alter_table('departments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_departments_institution_id'), ['institution_id'], unique=False)

    op.create_table('subjects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_subjects_department_id_departments'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subjects')),
    sa.UniqueConstraint('department_id', 'name', name='uq_subjects_department_name')
    )
    with op.batch_alter_table('subjects', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_subjects_department_id'), ['department_id'], unique=False)


def downgrade():
    with op.batch_alter_table('subjects', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_subjects_department_id'))
    op.drop_table('subjects')
    with op.batch_alter_table('departments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_departments_institution_id'))
    op.drop_table('departments')
