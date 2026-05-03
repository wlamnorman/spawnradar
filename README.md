# SpawnRadar

SpawnRadar was a creator discovery and outreach SaaS for indie game developers.

I am shutting it down as a business and keeping this repository as a product and engineering showcase.

## Tech stack

- Backend: Python, FastAPI, Jinja2, APScheduler
- Frontend: Server-rendered HTML, vanilla JavaScript, CSS
- Database: SQLite
- Email: Resend
- Payments: Paddle
- Deployment: Docker + Fly.io

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r dev-requirements.txt
pip install -r requirements.txt
cp env-example .env
make dev
```

## Postmortem

### What I built
- Creator discovery and outreach workflow for indie game developers.
- Matching flow using game metadata, tags, and free-text summaries.
- Payments, auth, email, API integrations, data ingestion, and internal workflow tooling.

### Outcome
- Around 35 people tried it.
- 0 paying customers.
- Positive feedback, but no meaningful retention.

### What I learned
- A pain point can be real without being strong enough to support a self-serve SaaS.
- Indie devs may agree with the workflow idea and still not adopt another tool.
- Low-budget, skeptical users often need more hand-holding than a solo founder can provide cheaply.

## Product showcase

### Homepage
Marketing landing page and top-level positioning.

![Homepage](images/homepage.png)

### Define game: step 1
First step of the game definition and setup flow.

![Define game 1](images/define-game1.png)

### Define game: step 2
More detailed game metadata and matching inputs.

![Define game 2](images/define-game2.png)

### Dashboard
Main dashboard for managing games and account state.

![Dashboard](images/dashboard.png)

### Matches
Ranked creator matches with fit signals and outreach workflow.

![Matches](images/matches.png)

### How it works
Public explanation page for the matching workflow.

![How it works](images/how-it-works.png)

### Billing
Subscription and payment management flow.

![Billing](images/billing.png)

## License

No open-source license has been added yet.

Unless and until I add a LICENSE file, this repository is provided as a public code showcase only.

Indie game developers may study the code and use it privately for their own internal projects, experiments, or learning.

Redistribution, resale, sublicensing, public reposting, and use as part of a competing commercial product or service are not permitted without explicit permission.
