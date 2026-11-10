"""Phase 9 demo data: a messy university-style roster to try the lenient import.

    python seed_phase9.py <institution admin email>

1. Runs the Phase 5 seed (publishes "Phase 5 Demo Test" once; one field, so no field column is needed).
2. Writes demo_roster_messy.csv next to this file: 10 rows with odd headings ("Student Name", "Gmail", "Mobile",
   "Reg No", "D.O.B"), an extra "Father Name" column, missing emails / phones / dates of birth, an Excel date
   number, and four real mistakes. Import it on the Roster page; the preview should say
   "6 ready · 4 need fixing · 3 with warnings".
Nothing here is needed in production."""
import os
import sys

import seed_phase5

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_roster_messy.csv")
CSV_TEXT = """Sr No,Student Name,Father Name,Gmail,Mobile,Reg No,D.O.B
1,AHMED RAZA,Raza Ali,ahmed.raza@example.com,0300-1234567,REG-101,14/03/2008
2,sana fatima,Fatima Bibi,,3217654321,REG-102,
3,Bilal Hussain,Hussain Shah,bilal.h@example.com,,REG-103,39400
4,Mehak Iqbal,Iqbal Ahmed,mehak.iqbal@example.com,+92 333 1112223,REG-104,03/04/2007
5,Ahmed Raza,Raza Khan,ahmed.khan@example.com,,REG-105,2008-01-01
6,Usman Ghani,Ghani Gul,N/A,-,,2007-09-09
7,Hira Shah,Shah Jee,hira.shah@example.com,,REG-101,
8,Zara Malik,Malik Riaz,zara@mail,,REG-108,
9,Kamran Akmal,Akmal Butt,kamran@example.com,0300-1234567,REG-109,2007-12-12
10,Fatima Noor,Noor Din,,,REG-110,31/02/2007
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    if seed_phase5.main() != 0:
        return 1
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(CSV_TEXT)
    print(f"Wrote {CSV_PATH}: import it on the Roster page of \"{seed_phase5.TEST_NAME}\".")
    print("Expected preview: 6 ready, 4 need fixing (rows 7, 8, 9, 11), 3 warnings (rows 5, 6, 10).")
    print("Sana Fatima has no date of birth: she signs in with the PIN shown on the roster / slip.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
