"""Shared extension objects. Created here, attached to the app in create_app()."""
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

# Named constraints: SQL Server migrations can only drop/alter constraints that have names.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING))
migrate = Migrate()
cors = CORS()
jwt = JWTManager()


def commit_keep() -> None:
    """Commit without throwing away the loaded objects (Phase 8, load test). Use it only where what was just written
    is exactly what the answer sends back, so reloading everything after the commit would be wasted work."""
    session = db.session()
    session.expire_on_commit = False
    try:
        session.commit()
    finally:
        session.expire_on_commit = True
