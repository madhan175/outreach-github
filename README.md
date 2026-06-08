# Outreach

This folder contains the React + Vite frontend used with the ReachFlow outreach backend.

This README gives quick setup and usage instructions for the full project (backend + frontend).

---

## Project layout

- `backed/` — FastAPI backend that runs the outreach pipeline (Apollo → Prospeo → Brevo).
- `my-app/` — React + Vite frontend that can show pipeline runs and logs.

---

## Requirements

- Python 3.10+ (for backend)
- Node.js 16+ and npm/yarn (for frontend)
- A Brevo account and API key if you intend to send real emails

## Backend setup (quick)

1. Create and activate a Python virtual environment in the workspace root:

```powershell
python -m venv .venv
. .venv/Scripts/Activate.ps1
```

2. Install backend dependencies:

```powershell
cd backed
pip install -r requirements.txt
```

3. Configure environment variables. Create `backend/.env` with at least the required keys:

APOLLO_API_KEY=your_apollo_api_key
PROSPEO_API_KEY=your_prospeo_api_key
BREVO_API_KEY=your_brevo_api_key

BREVO_SENDER_EMAIL=your_email@example.com
BREVO_SENDER_NAME=your_sender_name

BREVO_CAMPAIGN_LIST_IDS=5

4. Run the backend (development):

```powershell
cd backed
uvicorn main:app --reload --port 8000
```

The API health endpoint is `GET /api/health`.

## Frontend setup (quick)

1. Install dependencies and run the dev server:

```bash
cd my-app
npm install
npm run dev
```

2. The frontend dev server runs on `http://localhost:5173` by default.

---

## Using the outreach pipeline (backend API)

- Start the backend as above.
- The pipeline is triggered with `POST /api/run`.

Example run (dry run):

```bash
curl -X POST http://localhost:8000/api/run -H "Content-Type: application/json" -d '{"domain":"stripe.com","limit":3,"dry_run":true}'
```

This returns a `run_id`. You can stream live logs via Server-Sent Events at `/api/stream/{run_id}`.

To perform a real send (will actually send emails), create a run with `dry_run=false` and then call:

```bash
curl -X POST http://localhost:8000/api/send/{run_id}
```

Notes & safety
- The backend includes a safety checkpoint: runs created with `dry_run=false` will pause at a checkpoint and only proceed to send when `/api/send/{run_id}` is called.
- Brevo may block API calls if your public IP is not authorised (account security setting). If you see a 401 mentioning `authorised_ips` or `unrecognised IP`, add the public IP shown in logs to: https://app.brevo.com/security/authorised_ips

## Common troubleshooting

- Missing API keys: ensure `backed/.env` contains the required keys. The backend prints guidance if keys are missing.
- IP blocking: see the Brevo authorised IPs message above.
- If campaign creation fails but transactional sends are allowed, the pipeline will fall back to sending per-contact transactional emails.

## Gitignore and repo files
This repository includes a `.gitignore` at the workspace root to exclude local envs, node_modules, build artifacts and secrets (see workspace root `.gitignore`).

---

If you'd like, I can also add a top-level `README.md` that focuses on the backend and deployment; tell me what you'd prefer to appear first.
