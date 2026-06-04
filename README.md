# Cash Application Foundry

Automate cash application and accounts receivable reconciliation with AI. Process 35 transactions in 56 seconds instead of 6 hours.

## Quick Start

Live Demo: https://cash-application-foundry.vercel.app

## Documentation

All documentation is available as an interactive GitHub Pages website:

**View Documentation:** https://vinaygangidi.github.io/cash-application-foundry/

Or read directly from the `/docs` folder in this repository:
- **index.md** / **INDEX.md** - Navigation guide for all documentation
- **how-it-works.md** - Complete explanation for non-technical readers
- **QUICK_VISUAL_GUIDE.md** - One-page visual summary with diagrams
- **IMPLEMENTATION_GUIDE.md** - Setup, configuration, API reference
- **SYSTEM_DESIGN.md** - Technical architecture and design details

## For Different Audiences

**Executives / Stakeholders**
Read: docs/how-it-works.md (Sections 1-4, then Real-World Impact)
Time: 15 minutes
Learn: Business value, time savings, audit compliance

**Sales / Marketing**
Read: docs/QUICK_VISUAL_GUIDE.md then docs/how-it-works.md
Time: 20 minutes
Learn: How to pitch to customers, before/after comparison

**Finance / AR Teams**
Read: docs/how-it-works.md then IMPLEMENTATION_GUIDE.md
Time: 30 minutes
Learn: How the system works, how to use it

**Developers / Architects**
Read: SYSTEM_DESIGN.md then IMPLEMENTATION_GUIDE.md
Time: 1 hour
Learn: Complete technical architecture and API

**Auditors / Compliance**
Read: SYSTEM_DESIGN.md (Sections 7-8) then docs/how-it-works.md (Compliance section)
Time: 20 minutes
Learn: Security model, audit trail, compliance controls

**New Team Members**
Read: docs/QUICK_VISUAL_GUIDE.md then docs/how-it-works.md then setup from IMPLEMENTATION_GUIDE.md
Time: 1-2 hours
Learn: System overview, then try locally with demo data

## Repository Structure

```
backend/
  agents/          # 5 specialized AI agents
  data/            # Demo data and samples
  main.py          # FastAPI backend
  requirements.txt
  Dockerfile

frontend/
  app/page.js      # React/Next.js UI
  package.json

docs/
  INDEX.md         # Master navigation guide
  how-it-works.md  # Complete explanation
  QUICK_VISUAL_GUIDE.md  # One-page summary

IMPLEMENTATION_GUIDE.md     # Setup and API reference
SYSTEM_DESIGN.md          # Technical details
```

## Key Features

- Processes 35 transactions in 56 seconds (vs 6 hours manual)
- 100% accurate matching with code-verified math
- Handles 35 edge cases (freight deductions, SWIFT truncation, factoring, etc)
- Immutable 7-year audit trail
- Compliant with OFAC pre-checks and holds
- Azure-native (data stays in your tenant)

## What the System Does

Matches bank statement payments to open invoices automatically. Handles complex scenarios that normally require experienced analysts:

- Partial payments with deductions
- Truncated customer names from wire transfers
- Factoring agent payments
- Multi-invoice bundles
- Currency conversions
- And 30 more edge cases

## Getting Started Locally

Requirements: Python 3.11+, Node.js 18+, Git

1. Clone the repo
   ```
   git clone https://github.com/vinaygangidi/cash-application-foundry.git
   cd cash-application-foundry
   ```

2. Backend setup
   ```
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn main:app --port 8001 --reload
   ```

3. Frontend setup (new terminal)
   ```
   cd frontend
   npm install
   NEXT_PUBLIC_API_URL=http://localhost:8001 npm run dev
   ```

4. Open http://localhost:3000

See IMPLEMENTATION_GUIDE.md for detailed setup, configuration, and troubleshooting.

## Deployment

Backend: Railway
Frontend: Vercel

See IMPLEMENTATION_GUIDE.md > Deployment section for instructions.

## Contact

Author: Vinay Gangidi
Email: vinay.gangidi@gmail.com

Built for Microsoft Build AI Hackathon 2026
Theme: Agent Swarms
