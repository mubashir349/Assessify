"""One-time fix for "multiple heads": the old admit-card migration (e7a2c91d4b58) was merged into
7b79df321fc9 (phase 11 payments, subscriptions and admit card emails).

Run in backend/ with the venv on, AFTER deleting migrations/versions/e7a2c91d4b58_phase_11_admit_card_emails.py:
    python fix_migration.py
    flask --app run db upgrade
"""
from sqlalchemy import inspect, text

from app import create_app
from app.extensions import db

OLD, BASE = "e7a2c91d4b58", "84db737b6a44"

app = create_app()
with app.app_context():
    version = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    print(f"Database is at: {version}")
    if version == OLD:
        if inspect(db.engine).has_table("admit_card_emails"):
            rows = db.session.execute(text("SELECT COUNT(*) FROM admit_card_emails")).scalar()
            db.session.execute(text("DROP TABLE admit_card_emails"))
            print(f"Dropped the old admit_card_emails table ({rows} log rows). The new migration makes it again.")
        db.session.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": BASE})
        db.session.commit()
        print(f"Database moved back to {BASE}. Now run:  flask --app run db upgrade")
    else:
        print("Nothing to fix in the database. Now run:  flask --app run db upgrade")
