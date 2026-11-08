"""Phase 8: builds assessify-azure.zip for Azure App Service (Linux, Python 3.12), see docs/DEPLOY.md.

    python deploy/make_azure_zip.py            (run inside backend/, works on Windows too)

The zip holds the backend at its top level (requirements.txt, run.py, app/, migrations/ ...) and the pages in
frontend/, so Azure installs the packages itself and one app serves both. Never packed: .env, venv, tests,
__pycache__, *.db and the zip itself.
"""
import os
import sys
import zipfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(os.path.dirname(BACKEND), "frontend")
OUT = os.path.join(BACKEND, "assessify-azure.zip")
SKIP_DIRS = {"venv", ".venv", "tests", "__pycache__", ".pytest_cache", "instance", "uploads"}
SKIP_FILES = {".env", "assessify-azure.zip"}
SKIP_ENDINGS = (".pyc", ".db", ".sqlite", ".log")


def add_tree(z: zipfile.ZipFile, root: str, prefix: str) -> int:
    count = 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            if name in SKIP_FILES or name.endswith(SKIP_ENDINGS):
                continue
            path = os.path.join(folder, name)
            z.write(path, os.path.join(prefix, os.path.relpath(path, root)).replace(os.sep, "/"))
            count += 1
    return count


def main() -> int:
    if not os.path.isdir(FRONTEND):
        print(f"frontend folder not found next to backend: {FRONTEND}")
        return 1
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        n = add_tree(z, BACKEND, "") + add_tree(z, FRONTEND, "frontend")
    print(f"{OUT}: {n} files, {os.path.getsize(OUT) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
