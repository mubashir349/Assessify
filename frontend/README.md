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

## Demo notes
- Backend-less demo: login, institution signups, fields/departments, draft questions and the question bank are stored in the browser (`localStorage`) via `assets/js/store.js`.
- New institutions register on `aptitude/institution-signup.html` and stay **pending** until the Super Admin approves them.
- Demo Super Admin login: `superadmin@assessai.com` (any password) on `aptitude/institution-login.html`.
- Fields (Undergraduate) / Departments (Masters, PhD) are added by the institution after approval, under *Fields & Departments*.
- `candidate-start.html?demo=1` bypasses the fixed-time gate for previews.
