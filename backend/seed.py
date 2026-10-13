"""Creates the platform Super Admin. Run once:  python seed.py

Reads SUPER_ADMIN_EMAIL / SUPER_ADMIN_NAME / SUPER_ADMIN_PASSWORD from .env if present,
otherwise asks in the terminal. The password is never stored in code."""
import getpass
import os
import sys

from app import create_app
from app.extensions import db
from app.models.user import ROLE_SUPER_ADMIN, User


def main() -> int:
    email = (os.getenv("SUPER_ADMIN_EMAIL") or input("Super Admin email: ")).strip().lower()
    name = os.getenv("SUPER_ADMIN_NAME") or "Platform Super Admin"
    password = os.getenv("SUPER_ADMIN_PASSWORD") or getpass.getpass("Super Admin password (min 10 chars): ")
    if "@" not in email or len(password) < 10:
        print("Need a valid email and a password of at least 10 characters.")
        return 1

    app = create_app()
    with app.app_context():
        if User.query.filter_by(email=email).first():
            print(f"{email} already exists - nothing to do.")
            return 0
        user = User(full_name=name, email=email, role=ROLE_SUPER_ADMIN, institution_id=None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"Super Admin created: {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
