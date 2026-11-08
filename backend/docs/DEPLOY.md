# Deploying Assessify (Phase 8)

One app serves both the API (`/api/v1/...`) and the pages (`/aptitude/...`), so there is only one address to open.
Pick one of three ways:

| Way | Cost | Good for |
|---|---|---|
| **A. Azure for Students** (App Service + Azure SQL) | B1 plan about $13/month from the free $100 student credit; Azure SQL free offer | the real demo on a public `https://<name>.azurewebsites.net` address |
| **B. A Windows PC or lab server** (`python serve.py`) | free | an exam in one lab / campus network |
| **C. Docker** (`docker compose`) | free | any Linux server or a PC with Docker Desktop |

Whichever you pick, finish with the **mock exam check** at the end of this page: that is Phase 8's "done when".

---

## Settings every production copy needs

| Setting | Value |
|---|---|
| `FLASK_ENV` | `production` (the server then refuses to start with a default or example `SECRET_KEY`) |
| `SECRET_KEY` | your own: `python -c "import secrets; print(secrets.token_hex(32))"`. Never reuse the one in `.env.example`. |
| `JWT_COOKIE_CSRF` | `true` |
| `JWT_COOKIE_SECURE` | `true` on https (Azure); `false` only on a plain-http lab network |
| `FRONTEND_URL` | the address people open, e.g. `https://assessify-ned.azurewebsites.net` |
| `TRUST_PROXY_HOPS` | `1` behind Azure / nginx / a tunnel, else `0` |
| `MAIL_BACKEND` + `MAIL_*` | `smtp` to really send result emails (see Phase 7 in the README) |
| `AI_PROVIDER`, `GEMINI_API_KEY` | as on your PC, if question generation should work |

When the server starts in production it prints warnings for anything weak (plain http cookies, CSRF off, console mail).

---

## A. Azure for Students

Not tried from here (no Azure account); the steps follow Azure's own guides. Tell us where a screen looks different.

### 1. Credit
Sign up at https://azure.microsoft.com/free/students with your university email: $100 for 12 months, no card.

### 2. Database: Azure SQL (free offer)
1. Portal → **Create a resource** → **SQL Database**. On the first page press **Apply offer** (free: 100,000
   vCore-seconds and 32 GB a month, enough for a class project).
2. Resource group: new, `assessify-rg`. Database name: `AssessifyDB`. Server: **Create new**, a name like
   `assessify-ned-sql`, region close to you (e.g. *Central India* or *UAE North*), authentication **SQL
   authentication**, an admin login and a strong password. Write both down.
3. **Networking**: Public endpoint, **Allow Azure services and resources to access this server = Yes**, **Add current
   client IP address = Yes** (so your PC can seed it).
4. Create. The server address is `assessify-ned-sql.database.windows.net`.

### 3. Fill the database from your own PC
In `backend/.env` on your PC, temporarily point at Azure (keep a copy of your local values):
```
DB_SERVER=tcp:assessify-ned-sql.database.windows.net,1433
DB_NAME=AssessifyDB
DB_TRUSTED=no
DB_USER=<sql admin login>
DB_PASSWORD=<sql admin password>
DB_TRUST_CERT=no
SUPER_ADMIN_EMAIL=...        # the platform owner account seed.py creates
SUPER_ADMIN_PASSWORD=...
```
```powershell
.\venv\Scripts\Activate.ps1
flask --app run db upgrade        # creates every table on Azure SQL
python seed.py                    # the Super Admin
```
Then switch `.env` back to your local database.

### 4. Web app
1. Portal → **Create a resource** → **Web App**. Resource group `assessify-rg`, name e.g. `assessify-ned`
   (the address becomes `https://assessify-ned.azurewebsites.net`), **Publish: Code**, **Runtime: Python 3.12**,
   **OS: Linux**, same region as the database.
2. Pricing plan: **Basic B1**. (Free F1 has 60 CPU minutes a day: fine to look at the pages, too weak for an exam.)
3. Create, then open the web app:
   - **Settings → Environment variables → App settings**, add:
     ```
     FLASK_ENV=production
     SECRET_KEY=<new random value>
     DB_SERVER=tcp:assessify-ned-sql.database.windows.net,1433
     DB_NAME=AssessifyDB
     DB_TRUSTED=no
     DB_USER=<sql admin login>
     DB_PASSWORD=<sql admin password>
     DB_TRUST_CERT=no
     FRONTEND_URL=https://assessify-ned.azurewebsites.net
     JWT_COOKIE_SECURE=true
     JWT_COOKIE_CSRF=true
     TRUST_PROXY_HOPS=1
     SCM_DO_BUILD_DURING_DEPLOYMENT=true
     MAIL_BACKEND=console        (or smtp + MAIL_* to really send)
     ```
   - **Settings → Configuration → General settings → Startup Command**:
     ```
     flask --app run db upgrade && gunicorn -w 2 --threads 8 --timeout 120 --keep-alive 30 --bind=0.0.0.0:8000 run:app
     ```
   - Save (the app restarts).

### 5. Upload the code
```powershell
cd backend
python deploy/make_azure_zip.py          # makes backend\assessify-azure.zip (no .env, no venv, no tests)
```
Upload it with the Azure CLI (install once: `winget install Microsoft.AzureCLI`, then `az login`):
```powershell
az webapp deploy --resource-group assessify-rg --name assessify-ned --src-path assessify-azure.zip --type zip
```
Azure installs `requirements.txt` itself (2 to 5 minutes). Then open
`https://assessify-ned.azurewebsites.net/api/v1/health/db`: it should say `"status": "ok"` and name the database.

### 6. First use
Open `https://assessify-ned.azurewebsites.net/aptitude/institution-signup.html`, register the institution, approve
it as the Super Admin, then add fields, questions, a test and candidates as usual. For a quick demo bank, run on your
PC with `.env` pointing at Azure (step 3): `python seed_phase6.py <institution admin email>`.

### Problems
- **Application error / 503 right after deploy**: *Log stream* in the web app shows why. Usually a missing setting.
- `Can't open lib 'ODBC Driver 18 for SQL Server'`: add the app setting `DB_DRIVER=ODBC Driver 17 for SQL Server`.
- `Login timeout expired` from your PC: add your current IP in the SQL server's **Networking** page (home IPs change).
- The server refuses to start with `SECRET_KEY`: you used the default or the `.env.example` key; make a new one.
- Stop paying when the project is over: delete the resource group `assessify-rg`.

---

## B. A Windows PC or lab server

For an exam inside one network (lab, campus Wi-Fi). Candidates open `http://<this PC's IP>:8000/aptitude/candidate-login.html`.

1. Use the PC that already has SQL Server and the project (Phase 0 setup).
2. In `backend/.env`: `FLASK_ENV=production`, a new `SECRET_KEY`, `JWT_COOKIE_CSRF=true`,
   `FRONTEND_URL=http://<this PC's IP>:8000`. Keep `JWT_COOKIE_SECURE=false` (plain http; you will see a warning).
3. Run:
   ```powershell
   .\venv\Scripts\Activate.ps1
   flask --app run db upgrade
   python serve.py                    # waitress, port 8000 (PORT=... to change)
   ```
4. Allow port 8000 once (PowerShell as Administrator):
   `New-NetFirewallRule -DisplayName "Assessify 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`
5. Find the IP with `ipconfig` (IPv4 Address).

One waitress process handled 300 candidates with no errors in the load test, but when all 300 sign in and start in
the same minute they wait 4 to 7 seconds. Let candidates sign in over a few minutes before the start time, or use
way A or C (several processes) for bigger groups. See [LOAD-TEST.md](LOAD-TEST.md).

---

## C. Docker

From the repository root, on a machine with Docker:
```bash
cp deploy.env.example deploy.env       # fill in SECRET_KEY, DB_PASSWORD, FRONTEND_URL ...
docker compose up -d --build
docker compose exec app python seed.py # Super Admin
```
The site is on port 8000 (`APP_PORT` to change). SQL Server Express runs in its own container with its data in the
`sqldata` volume. The app image runs `flask db upgrade` and then gunicorn (`WEB_CONCURRENCY` processes, default 2).
Put it behind https (nginx, Caddy or a tunnel) and set `JWT_COOKIE_SECURE=true` and `TRUST_PROXY_HOPS=1`.

---

## Done when: a full mock exam on the deployed copy

From any PC with the project's venv (it only uses the public API, like the pages):
```powershell
cd backend
python loadtest/mock_exam.py https://assessify-ned.azurewebsites.net <institution admin email> "<password>"
```
It needs approved Mathematics questions in the admin's *Pre-Engineering* (Undergraduate) field
(`python seed_phase6.py <admin email>` adds them). It then:
1. signs the admin in and creates and publishes "Mock Exam <time>", opening 75 seconds later;
2. adds 5 candidates, signs each one in and waits at the time gate;
3. starts the test for everyone; candidate 1 leaves the window, is locked, cannot answer, and the admin unlocks them;
4. everyone answers and submits and reads their result;
5. the admin checks the Live Monitor, the report, the CSV export, and sends the result emails.

It prints one line per step and ends with `PASS` (or `FAIL` and the reason). Then open the pages yourself:
Reports → the Mock Exam shows the 5 results.
