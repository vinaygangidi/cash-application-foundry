---
layout: default
title: Implementation Guide
---

# Cash Application Foundry - Implementation Guide

Complete guide for setup, configuration, API reference, and troubleshooting.

## Quick Setup

### Requirements
- Python 3.11 or higher
- Node.js 18 or higher  
- Git

### Backend Setup

1. Clone the repository
   git clone https://github.com/vinaygangidi/cash-application-foundry.git
   cd cash-application-foundry

2. Set up Python environment
   cd backend
   python -m venv .venv
   source .venv/bin/activate  (Mac/Linux)
   .venv\Scripts\activate      (Windows)

3. Install dependencies
   pip install -r requirements.txt

4. Configure environment variables
   cp .env.example .env
   
   For demo mode only:
   USE_FIXTURES=true
   
   For live Azure mode:
   AZURE_AI_ENDPOINT=https://your-resource.services.ai.azure.com
   AZURE_API_KEY=your_api_key_here
   AZURE_OPENAI_API_VERSION=2024-12-01-preview
   USE_FIXTURES=false

5. Start the backend
   uvicorn main:app --port 8001 --reload

### Frontend Setup (Separate Terminal)

1. Navigate to frontend
   cd frontend

2. Install dependencies
   npm install

3. Start development server
   NEXT_PUBLIC_API_URL=http://localhost:8001 npm run dev

4. Open browser
   http://localhost:3000

## Configuration Reference

### Environment Variables

Backend (.env file):

USE_FIXTURES
  Type: boolean (true/false)
  Purpose: Run in demo mode without Azure
  Default: true
  Example: USE_FIXTURES=true

AZURE_AI_ENDPOINT
  Type: string
  Purpose: Azure AI Foundry endpoint URL
  Example: https://your-resource.services.ai.azure.com
  Required for: Live Azure mode

AZURE_API_KEY
  Type: string
  Purpose: Azure API authentication key
  Required for: Live Azure mode
  Note: Use DefaultAzureCredential in production instead

AZURE_OPENAI_API_VERSION
  Type: string
  Purpose: OpenAI API version
  Default: 2024-12-01-preview
  Example: 2024-12-01-preview

AZURE_STORAGE_ACCOUNT_URL
  Type: string
  Purpose: Azure Blob Storage URL for audit trail
  Example: https://yourstore.blob.core.windows.net
  Optional: System works without this, but audit trail disabled

APPLICATIONINSIGHTS_CONNECTION_STRING
  Type: string
  Purpose: Azure Application Insights monitoring
  Optional: Monitoring disabled if not set

Frontend (.env.local file):

NEXT_PUBLIC_API_URL
  Type: string
  Purpose: Backend API endpoint URL
  Development: http://localhost:8001
  Production: https://your-railway-app.up.railway.app

### Model Configuration

Each agent can use different models via environment variables:

MODEL_BANK_AGENT (default: gpt-4o-mini)
MODEL_AR_AGENT (default: gpt-4o-mini)
MODEL_RECON_AGENT (default: gpt-4o)
MODEL_MISMATCH_AGENT (default: gpt-4o)
MODEL_POSTING_AGENT (default: gpt-4o)

Override example:
export MODEL_BANK_AGENT=gpt-4o
uvicorn main:app --reload

## API Reference

### POST /analyze

Trigger the 5-agent cash application pipeline.

Request:
```json
{
  "bank_data": {
    "statement_date": "2025-06-01",
    "bank_account": "1234567890",
    "transactions": [
      {
        "id": "TXN-001",
        "date": "2025-06-01",
        "payer": "CUSTOMER NAME",
        "amount": 50000.00,
        "currency": "USD",
        "remittance": "INV-1001"
      }
    ]
  },
  "ar_data": {
    "invoices": [
      {
        "id": "INV-1001",
        "customer_name": "Customer Legal Name",
        "amount": 50000.00,
        "due_date": "2025-07-01",
        "status": "open"
      }
    ],
    "holds": [],
    "disputes": []
  }
}
```

Response (Server-Sent Events - Streaming):
```
data: {"event": "agent_start", "agent": "BankStatementIntelligenceAgent", "model": "gpt-4o-mini"}
data: {"event": "token_delta", "delta": "Processing..."}
data: {"event": "agent_complete", "agent": "BankStatementIntelligenceAgent", "output": {...}}
...
data: {"event": "swarm_complete", "results": {...}}
data: [DONE]
```

### GET /health

Check service status and configuration.

Response:
```json
{
  "status": "ok",
  "service": "cash-application-foundry",
  "azure_blob_storage": true,
  "azure_app_insights": true,
  "use_fixtures": false,
  "sample_count": 1
}
```

### GET /demo-data

Load sample dataset for testing.

Query Parameters:
sample (default: 01)

Response:
```json
{
  "bank_statement": {...},
  "open_ar": {...},
  "sample_id": "01"
}
```

### GET /samples

List all available sample datasets.

Response:
```json
{
  "samples": [
    {
      "id": "01",
      "name": "Demo Data",
      "description": "35 transactions across 38 open invoices"
    }
  ]
}
```

## Troubleshooting

### Backend Fails to Start

Error: Module not found
Solution: pip install -r requirements.txt
Verify: pip list | grep fastapi

Error: Port 8001 already in use
Solution 1: uvicorn main:app --port 8002
Solution 2: Find process using port: lsof -i :8001
            Kill process: kill -9 <PID>

Error: AZURE_AI_ENDPOINT not configured
Solution: See Configuration Reference section above
Verify: echo $AZURE_AI_ENDPOINT (should show URL)

### Frontend Cannot Connect to Backend

Error: Failed to fetch from /analyze
Solution: Verify NEXT_PUBLIC_API_URL is set correctly
Verify: echo $NEXT_PUBLIC_API_URL
Check: Backend is running on port 8001
Check: CORS is enabled in FastAPI (should be by default)

### Agents Time Out

Error: Agent X takes too long or never completes
Solution: Increase MAX_TOKENS in agent file
File: backend/agents/[agent_name].py
Line: MAX_TOKENS = 2000 (increase this)

Error: Azure API timeout
Solution: Check internet connection
Solution: Verify Azure AI endpoint is accessible
Solution: Check Azure quota limits

### JSON Parsing Fails

Error: Failed to extract JSON from agent response
Solution: Review agent prompt in backend/agents/[agent_name].py
Solution: Increase MAX_TOKENS for that agent
Solution: Check Azure API response status

### Demo Mode Issues

Error: Cannot load fixtures
Solution: Verify files exist: backend/data/bank_statement.json
Solution: Check file permissions: chmod 644 backend/data/*.json
Solution: USE_FIXTURES=true is set correctly

### Azure Authentication Fails

Error: DefaultAzureCredential failed
Solution: Use API Key instead: AZURE_API_KEY=your_key
Solution: Verify Service Principal has correct roles
Solution: Check: az account show (CLI)

## Customization

### Change Matching Strategies

File: backend/agents/reconciliation_agent.py
Section: Matching Strategies in system prompt

To add a new strategy:
1. Define the logic in the prompt
2. Update the 8-strategy list
3. Restart backend: uvicorn main:app --reload
4. Test with demo data

### Change Risk Tiers

File: backend/agents/mismatch_agent.py
Section: Risk tier assignment in system prompt

To modify thresholds:
1. Update risk_tier logic
2. Update SLA hours for each tier
3. Restart and test

### Change GL Accounts

File: backend/agents/posting_agent.py
Search for: gl_account
Update GL codes to match your chart of accounts

### Change Workqueue Assignment

File: backend/agents/posting_agent.py
Search for: assign_to
Update assignment logic based on your team structure

### Add Custom Flags

File: backend/agents/bank_statement_agent.py
Add to the flags detection section:

if [your_condition]:
    flags.append("YOUR_FLAG_NAME")

Then update frontend:
File: frontend/app/page.js
Search for: FLAG_BADGE
Add entry for your new flag

## Deployment

### Local Testing

1. Set USE_FIXTURES=true in .env
2. Run both backend and frontend
3. Click Load Demo Data
4. Click Run Cash Application
5. Verify all 5 agents complete successfully

### Deploy Backend to Railway

1. Create Railway account: railway.app
2. Connect GitHub repository
3. Set root directory: /backend
4. Add environment variables in Railway dashboard:
   AZURE_AI_ENDPOINT
   AZURE_API_KEY
   AZURE_OPENAI_API_VERSION
   AZURE_STORAGE_ACCOUNT_URL (optional)
   APPLICATIONINSIGHTS_CONNECTION_STRING (optional)
5. Railway auto-detects Dockerfile and deploys
6. Get public URL from Railway dashboard

### Deploy Frontend to Vercel

1. Create Vercel account: vercel.com
2. Connect GitHub repository
3. Set root directory: /frontend
4. Add environment variable:
   NEXT_PUBLIC_API_URL=https://your-railway-url
5. Deploy automatically on git push

### Scale to Production

Phase 1 (Now): Single container, demo + live Azure
Phase 2 (3 months): Async queue, multiple workers, PostgreSQL
Phase 3 (12 months): Auto-scaling, ERP connectors, fine-tuning

See SYSTEM_DESIGN.md for full scaling roadmap.

## Performance Tuning

### Slow Agent Responses

Check which agent is slow in frontend UI
Increase MAX_TOKENS in that agent file
Example: Agent 3 max_tokens = 4000

### High Token Usage

Review agent prompts
Remove unnecessary instructions
Consider using GPT-4o-mini for more agents

### Memory Issues

Reduce sample size for testing
Implement batching for large datasets
Monitor Azure quota usage

## Common Customizations

### Change Model for Specific Agent

File: backend/agents/bank_statement_agent.py
Line: DEFAULT_MODEL = "gpt-4o-mini"
Change to: DEFAULT_MODEL = "gpt-4o"
Restart backend

### Add New Matching Strategy

File: backend/agents/reconciliation_agent.py
Add to matching strategies list in prompt
Test with demo data
Verify all 35 transactions process correctly

### Modify Customer Matching

File: backend/agents/ar_ledger_agent.py
Update alias generation logic
Customize fuzzy matching threshold

### Change Output Format

File: backend/agents/posting_agent.py
Modify workqueue item structure
Update frontend to display new fields

## Code Structure

backend/
  agents/
    cash_app.py (orchestrator)
    bank_statement_agent.py (Agent 1)
    ar_ledger_agent.py (Agent 2)
    reconciliation_agent.py (Agent 3)
    mismatch_agent.py (Agent 4)
    posting_agent.py (Agent 5)
  data/
    bank_statement.json (demo)
    open_ar.json (demo)
  main.py (FastAPI app)
  requirements.txt
  Dockerfile

frontend/
  app/
    page.js (React component)
  package.json

## Support & Resources

Documentation:
- System Design: SYSTEM_DESIGN.md
- How It Works: docs/how-it-works.md
- Quick Visual: docs/QUICK_VISUAL_GUIDE.md

GitHub Repository:
https://github.com/vinaygangidi/cash-application-foundry

Issues & Questions:
Report at: github.com/vinaygangidi/cash-application-foundry/issues

## Testing Checklist

Before deployment:
- Backend starts without errors
- Frontend connects to backend
- All 5 agents complete successfully
- Demo data processes in under 2 minutes
- Workqueue items are generated
- Each item has priority and assignment
- JSON output is valid
- No errors in browser console
- No errors in backend logs
