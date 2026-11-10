"""phase 10: institution directory, email codes, proof, admin phone and designation removed

Revision ID: 84db737b6a44
Revises: c4e9a7d2b351
Create Date: 2026-11-10 15:53:39.696934

New tables: directory_institutions + directory_campuses (the signup search list, filled by seed_directory.py),
email_otps (signup email codes, hashed) and institution_proofs (proof document of an institution without official
email). Existing institutions get the new columns with 0 / NULL and keep working.

users.phone and users.designation (institution admins only) are removed; the values in them are deleted.
Downgrading brings the two columns back, empty.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


# revision identifiers, used by Alembic.
revision = '84db737b6a44'
down_revision = 'c4e9a7d2b351'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('directory_institutions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Unicode(length=200), nullable=False),
    sa.Column('short_name', sa.Unicode(length=40), nullable=True),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('website', sa.String(length=255), nullable=True),
    sa.Column('email_domain', sa.String(length=255), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_directory_institutions')),
    sa.UniqueConstraint('name', name=op.f('uq_directory_institutions_name'))
    )
    op.create_table('email_otps',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('verified_at', sa.DateTime(), nullable=True),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_otps'))
    )
    with op.batch_alter_table('email_otps', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_email_otps_email'), ['email'], unique=False)

    op.create_table('directory_campuses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('directory_institution_id', sa.Integer(), nullable=False),
    sa.Column('campus_name', sa.Unicode(length=120), nullable=False),
    sa.Column('city', sa.Unicode(length=120), nullable=False),
    sa.Column('address', sa.Unicode(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['directory_institution_id'], ['directory_institutions.id'], name=op.f('fk_directory_campuses_directory_institution_id_directory_institutions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_directory_campuses')),
    sa.UniqueConstraint('directory_institution_id', 'campus_name', 'city', name='uq_campus_name_city')
    )
    with op.batch_alter_table('directory_campuses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_directory_campuses_directory_institution_id'), ['directory_institution_id'], unique=False)

    op.create_table('institution_proofs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.Unicode(length=200), nullable=False),
    sa.Column('content_type', sa.String(length=60), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('data', sa.LargeBinary().with_variant(mssql.VARBINARY('max'), 'mssql'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], name=op.f('fk_institution_proofs_institution_id_institutions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_institution_proofs')),
    sa.UniqueConstraint('institution_id', name=op.f('uq_institution_proofs_institution_id'))
    )
    with op.batch_alter_table('institutions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('directory_campus_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('directory_institution_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('campus_name', sa.Unicode(length=120), nullable=True))
        batch_op.add_column(sa.Column('from_directory', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('email_domain_verified', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('no_official_email', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.create_index(batch_op.f('ix_institutions_directory_campus_id'), ['directory_campus_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_institutions_directory_institution_id_directory_institutions'), 'directory_institutions', ['directory_institution_id'], ['id'])
        batch_op.create_foreign_key(batch_op.f('fk_institutions_directory_campus_id_directory_campuses'), 'directory_campuses', ['directory_campus_id'], ['id'])

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('phone')
        batch_op.drop_column('designation')



def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('designation', sa.VARCHAR(length=120), nullable=True))
        batch_op.add_column(sa.Column('phone', sa.VARCHAR(length=30), nullable=True))

    with op.batch_alter_table('institutions', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_institutions_directory_campus_id_directory_campuses'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('fk_institutions_directory_institution_id_directory_institutions'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_institutions_directory_campus_id'))
        batch_op.drop_column('no_official_email', mssql_drop_default=True)  # SQL Server: DEFAULT first
        batch_op.drop_column('email_domain_verified', mssql_drop_default=True)  # SQL Server: DEFAULT first
        batch_op.drop_column('from_directory', mssql_drop_default=True)  # SQL Server: DEFAULT first
        batch_op.drop_column('campus_name')
        batch_op.drop_column('directory_institution_id')
        batch_op.drop_column('directory_campus_id')

    op.drop_table('institution_proofs')
    with op.batch_alter_table('directory_campuses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_directory_campuses_directory_institution_id'))

    op.drop_table('directory_campuses')
    with op.batch_alter_table('email_otps', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_email_otps_email'))

    op.drop_table('email_otps')
    op.drop_table('directory_institutions')
