"""Phase 10: loads the institution directory (the signup search list) from data/institution_directory.csv.

    python seed_directory.py                 # backend/data/institution_directory.csv
    python seed_directory.py my_list.csv     # another file with the same columns

Columns: institution, short_name, type, website, email_domain, campus, city
  - one row per campus; rows with the same institution name belong together
  - type: University, College, School, Institute or Training Center
  - email_domain: the official email domain(s), several separated by commas. Leave it EMPTY when you are not sure:
    a wrong domain stops that institution's real admins from signing up.

Safe to run again: existing rows are updated, new ones added, nothing is deleted. Institutions added by the
Super Admin's approvals are kept.
"""
import csv
import sys
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models.directory import SOURCE_SEED, DirectoryCampus, DirectoryInstitution
from app.models.institution import INSTITUTION_TYPES

DEFAULT_FILE = Path(__file__).parent / "data" / "institution_directory.csv"


def load(path: Path) -> tuple[int, int, int]:
    added_inst = added_campus = updated = 0
    by_name = {i.name.lower(): i for i in DirectoryInstitution.query.all()}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            name = (row.get("institution") or "").strip()
            campus = (row.get("campus") or "").strip() or "Main Campus"
            city = (row.get("city") or "").strip()
            itype = (row.get("type") or "").strip()
            if not name or not city:
                print(f"  line {line}: skipped (institution and city are required)")
                continue
            if itype not in INSTITUTION_TYPES:
                print(f"  line {line}: skipped ({name}: type must be one of {', '.join(INSTITUTION_TYPES)})")
                continue
            fields = {"short_name": (row.get("short_name") or "").strip() or None, "type": itype,
                      "website": (row.get("website") or "").strip() or None,
                      "email_domain": (row.get("email_domain") or "").replace(" ", "").lower() or None}
            inst = by_name.get(name.lower())
            if inst is None:
                inst = DirectoryInstitution(name=name, source=SOURCE_SEED, **fields)
                db.session.add(inst)
                by_name[name.lower()] = inst
                added_inst += 1
            else:
                changed = any(getattr(inst, k) != v for k, v in fields.items())
                for k, v in fields.items():
                    setattr(inst, k, v)
                updated += changed
            if not any(c.campus_name.lower() == campus.lower() and c.city.lower() == city.lower() for c in inst.campuses):
                inst.campuses.append(DirectoryCampus(campus_name=campus, city=city))
                added_campus += 1
    db.session.commit()
    return added_inst, added_campus, updated


if __name__ == "__main__":
    file = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FILE
    app = create_app()
    with app.app_context():
        a, c, u = load(file)
        total = DirectoryInstitution.query.count()
        campuses = DirectoryCampus.query.count()
        print(f"Directory: {a} institutions added, {u} updated, {c} campuses added. "
              f"Now {total} institutions with {campuses} campuses.")
