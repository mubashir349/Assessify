# Assessify — AI-Powered Assessment & Learning Platform (Frontend)

Static HTML/CSS/JS frontend. Two modes on one platform:

- **Course mode** — Teacher / Student (coming next)
- **Aptitude mode** — Institution Admin + Candidate (`aptitude/`)

## Run locally
Open `index.html` in a browser (keep the folder structure intact so `assets/` loads).

## Structure
```
index.html            Master gateway (two frontdoors)
aptitude/             Aptitude mode pages (candidate + institution admin)
assets/css/           theme.css (shared) + one CSS file per page
assets/js/            main.js / admin-shell.js (shared) + one JS file per page
```

## Run with the backend
Run `python run.py` in `backend/` and open http://127.0.0.1:5000/ (the backend serves this folder), or use VS Code
Live Server on `http://127.0.0.1:5500` with the backend on port 5000. Use `127.0.0.1` for both so the login cookie works.

## What is real vs demo
- **Real (backend + SQL Server):** login, institution signup/approval (Phase 1), fields / departments + subjects (Phase 2),
  PDF upload, AI question generation, Draft Review and the approved-only Question Bank (Phase 3).
  These pages talk to the API through `assets/js/api.js` — nothing about them is kept in `localStorage`.
- **Still demo (`assets/js/store.js`, browser storage):** Aptitude Tests, Candidate Roster, Live Monitor, Reports and the
  candidate pages — their backend phases are not built yet.
- `candidate-start.html?demo=1` bypasses the fixed-time gate for previews.
