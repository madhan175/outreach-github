# ReachFlow – Automated Outreach Pipeline

ReachFlow is a full-stack outreach automation platform that discovers target companies, finds decision-maker contacts, enriches lead data, and executes email outreach campaigns through Brevo.

The platform consists of a FastAPI backend that orchestrates the outreach pipeline and a React frontend that provides real-time monitoring, run history, and campaign controls.

---

## Repository

```bash
git clone https://github.com/madhan175/outreach-github.git
cd outreach-github
cd backend 
cd frontend 


```

---

## Architecture

```text
┌─────────────┐
│ React UI    │
│ (Vite)      │
└──────┬──────┘
       │ REST + SSE
       ▼
┌─────────────┐
│ FastAPI     │
│ Backend     │
└──────┬──────┘
       │
 ┌─────┼─────────────────────┐
 ▼     ▼                     ▼
Apollo Prospeo           Brevo
Company Contact          Email
Search  Enrichment       Delivery
```

---

## Features

### Lead Discovery

* Search companies using Apollo
* Generate lookalike companies
* Domain-based prospecting

### Contact Enrichment

* Find decision-makers
* Enrich contact information
* Validate email addresses

### Outreach Automation

* Brevo campaign creation
* Transactional email fallback
* Sender verification support
* Marketing list integration

### Real-Time Monitoring

* Live pipeline logs
* Server-Sent Events (SSE)
* Run history tracking
* Status monitoring

### Safety Controls

* Dry-run mode
* Manual send confirmation
* Campaign validation
* Error recovery and fallbacks

---

## Project Structure

```text
reachflow/
│
├── backend/
│   ├── api.py
│   ├── requirements.txt
│   └── .env
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
│
├── stages/
│   ├── stage1_apollo.py
│   ├── stage2_prospeo.py
│   └── stage4_brevo.py
│
├── utils/
│
└── README.md
```

---

## Technology Stack

### Backend

* Python 3.10+
* FastAPI
* Uvicorn
* Requests
* SSE Streaming

### Frontend

* React
* Vite
* JavaScript
* CSS

### Integrations

* Apollo API
* Prospeo API
* Brevo API

---

## Environment Variables

Create a `.env` file:

```env
APOLLO_API_KEY=your_apollo_api_key
PROSPEO_API_KEY=your_prospeo_api_key

BREVO_API_KEY=your_brevo_api_key
BREVO_SENDER_EMAIL=your_sender_email
BREVO_SENDER_NAME=your_sender_name
BREVO_CAMPAIGN_LIST_IDS=5
```

---

## Backend Setup

### Create Virtual Environment

```powershell
python -m venv .venv
. .venv/Scripts/Activate.ps1
```

### Install Dependencies

```powershell
cd backend
pip install -r requirements.txt
```

### Start Backend

```powershell
uvicorn api:app --reload --port 8000
```

Backend URL:

```text
http://localhost:8000
```

Swagger Documentation:

```text
http://localhost:8000/docs
```

---

## Frontend Setup

Install dependencies:

```bash
cd frontend
npm install
```

Run development server:

```bash
npm run dev
```

Frontend URL:

```text
http://localhost:5173
```

---

## API Endpoints

### Health Check

```http
GET /api/health
```

### Create Pipeline Run

```http
POST /api/run
```

Request:

```json
{
  "domain": "stripe.com",
  "limit": 5,
  "dry_run": false
}
```

### Get Run

```http
GET /api/run/{id}
```

### List Runs

```http
GET /api/runs
```

### Live Logs

```http
GET /api/stream/{id}
```

### Confirm Send

```http
POST /api/send/{id}
```

### Cancel Run

```http
POST /api/cancel/{id}
```

---

## Pipeline Flow

### Stage 1 – Apollo

Input:

```text
stripe.com
```

Output:

```text
Lookalike companies
```

### Stage 2 – Prospeo

Input:

```text
Company domains
```

Output:

```text
Decision-maker contacts
Verified emails
```

### Stage 3 – Brevo

Input:

```text
Contacts
```

Output:

```text
Campaign creation
Email delivery
Tracking
```

---

## Testing

The project has been tested end-to-end.

Completed validation:

* API integrations verified
* Contact enrichment tested
* Campaign creation tested
* Sender verification tested
* SSE log streaming tested
* Frontend-backend communication verified

### Result

```text
All test cases passed successfully.
```

---

## Security

* Environment variables stored locally
* API keys excluded from Git
* Dry-run safety mode enabled
* Manual send confirmation required
* Brevo sender validation supported

---

## Production Recommendations

Before deployment:

* Replace in-memory storage with PostgreSQL
* Add JWT authentication
* Add rate limiting
* Configure HTTPS
* Add monitoring and logging
* Deploy with Docker
* Use Gunicorn + Uvicorn workers

Example:

```bash
gunicorn -k uvicorn.workers.UvicornWorker api:app
```

---

## Future Enhancements

* CRM integration
* Multi-user support
* Campaign analytics dashboard
* Scheduled outreach
* AI-generated email personalization
* PostgreSQL persistence
* Docker deployment

---

## Author

Madhan D

GitHub:
https://github.com/madhan175

---

## License

This project is provided for educational and evaluation purposes.
