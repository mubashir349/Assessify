"""Sets a new password for the platform Super Admin (or lists them if you forgot the email).

    python reset_admin_password.py                 -> shows Super Admin emails, then asks which one
    python reset_admin_password.py you@example.com -> asks for the new password for that account

The new password is typed in the terminal (hidden), never stored in code or .env."""
import getpass
import sys

from app import create_app
from app.extensions import db
from app.models.user import ROLE_SUPER_ADMIN, User


def main() -> int:
    app = create_app()
    with app.app_context():
        admins = User.query.filter_by(role=ROLE_SUPER_ADMIN).order_by(User.id).all()
        if not admins:
            print("No Super Admin exists yet. Create one with:  python seed.py")
            return 1
        print("Super Admin accounts: " + ", ".join(a.email for a in admins))
        email = (sys.argv[1] if len(sys.argv) > 1 else input("Email to reset: ")).strip().lower()
        user = next((a for a in admins if a.email.lower() == email), None)
        if user is None:
            print(f"{email} is not a Super Admin.")
            return 1
        pw = getpass.getpass("New password (min 10 chars, hidden while typing): ")
        if len(pw) < 10:
            print("Password must be at least 10 characters. Nothing changed.")
            return 1
        if getpass.getpass("Type it again: ") != pw:
            print("The two passwords do not match. Nothing changed.")
            return 1
        user.set_password(pw)
        user.is_active = True
        db.session.commit()
        print(f"Password changed for {user.email}. Restart run.py if sign-in still says 'too many attempts'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
