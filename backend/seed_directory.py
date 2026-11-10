"""Phase 10: loads the institution directory (the signup search list) from a CSV file in backend/data/.

    python seed_directory.py                 # backend/data/institution_directory.csv
    python seed_directory.py my_list.csv     # another file with the same columns, also kept in backend/data/

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

DATA_DIR = (Path(__file__).parent / "data").resolve()
DEFAULT_FILE = DATA_DIR / "institution_directory.csv"


def data_file(name: str | None) -> Path:
    """Only a file name inside backend/data/ is accepted (no folders, no '..'), so the script never reads elsewhere."""
    if not name:
        return DEFAULT_FILE
    safe = Path(name).name
    if not safe.lower().endswith(".csv"):
        raise SystemExit("Give the name of a .csv file inside backend/data/, e.g. my_list.csv")
    return DATA_DIR / safe


def _clean(row: dict, key: str) -> str:
    return (row.get(key) or "").strip()


def _parse(row: dict, line: int) -> dict | None:
    """One CSV row -> the values to save, or None (with a message) when the row can't be used."""
    name, city, itype = _clean(row, "institution"), _clean(row, "city"), _clean(row, "type")
    if not name or not city:
        print(f"  line {line}: skipped (institution and city are required)")
        return None
    if itype not in INSTITUTION_TYPES:
        print(f"  line {line}: skipped ({name}: type must be one of {', '.join(INSTITUTION_TYPES)})")
        return None
    return {"name": name, "city": city, "campus": _clean(row, "campus") or "Main Campus",
            "fields": {"short_name": _clean(row, "short_name") or None, "type": itype,
                       "website": _clean(row, "website") or None,
                       "email_domain": _clean(row, "email_domain").replace(" ", "").lower() or None}}


def _upsert_institution(by_name: dict, name: str, fields: dict) -> tuple[DirectoryInstitution, str]:
    """-> (institution, 'added' | 'updated' | '')"""
    inst = by_name.get(name.lower())
    if inst is None:
        inst = DirectoryInstitution(name=name, source=SOURCE_SEED, **fields)
        db.session.add(inst)
        by_name[name.lower()] = inst
        return inst, "added"
    changed = any(getattr(inst, k) != v for k, v in fields.items())
    for k, v in fields.items():
        setattr(inst, k, v)
    return inst, "updated" if changed else ""


def _add_campus(inst: DirectoryInstitution, campus: str, city: str) -> bool:
    if any(c.campus_name.lower() == campus.lower() and c.city.lower() == city.lower() for c in inst.campuses):
        return False
    inst.campuses.append(DirectoryCampus(campus_name=campus, city=city))
    return True


def load(path: Path) -> tuple[int, int, int]:
    counts = {"added": 0, "updated": 0, "": 0}
    campuses = 0
    by_name = {i.name.lower(): i for i in DirectoryInstitution.query.all()}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            item = _parse(row, line)
            if item is None:
                continue
            inst, what = _upsert_institution(by_name, item["name"], item["fields"])
            counts[what] += 1
            campuses += _add_campus(inst, item["campus"], item["city"])
    db.session.commit()
    return counts["added"], campuses, counts["updated"]


if __name__ == "__main__":
    file = data_file(sys.argv[1] if len(sys.argv) > 1 else None)
    app = create_app()
    with app.app_context():
        a, c, u = load(file)
        print(f"Directory: {a} institutions added, {u} updated, {c} campuses added. Now "
              f"{DirectoryInstitution.query.count()} institutions with {DirectoryCampus.query.count()} campuses.")
