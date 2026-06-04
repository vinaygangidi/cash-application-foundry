---
layout: default
title: How It Works
---

# How Cash Application Foundry Works: A Complete Step-by-Step Guide

This guide explains what happens inside the system when you click "Run Cash Application". Written for non-technical stakeholders.

## The Big Picture

When you use Cash Application Foundry, here's what happens:

```
YOU (User)
    |
Click "Run Cash Application" with bank statement + open invoices
    |
Frontend (Your Browser) - React/Next.js
    |
FastAPI Backend - Railway Container
    |
Azure Cloud (5 AI Agents in Pipeline)
    |
Results Saved to Azure Storage
    |
Frontend Shows Results
    |
YOU see Workqueue Items Ready to Post
```

Let's break this down step by step.

## Complete Flow: What Happens When You Click "Run"

### PHASE 1: Your Browser (Frontend)

#### Step 1: You Upload Data

Your browser shows a simple upload screen. You load two JSON files:
- bank_statement.json (35 transactions from your bank)
- open_ar.json (38 open invoices you need to match)

The frontend loads these files and stores them in browser memory. You see a preview of 35 transactions and 38 invoices. Everything is ready to process.

#### Step 2: You Click "Run Cash Application"

React creates a special connection to the backend using SSE (Server-Sent Events). This keeps the connection open so you can see progress in real-time.

Your browser sends:
```
POST /analyze
{
  "bank_data": {
    "statement_date": "2025-06-01",
    "transactions": [...]
  },
  "ar_data": {
    "invoices": [...],
    "holds": [...],
    "disputes": [...]
  }
}
```

The connection stays open. Frontend waits for backend to process.

## PHASE 2: Backend Server (FastAPI)

#### Step 3: Backend Receives Request

The FastAPI backend at Railway receives your request. Here's what happens immediately:

1. Validates your JSON format is correct
2. Creates a unique run_id for this analysis (like: a7f3d5e2-1b4c-4d8e-9f2a...)
3. Records the current timestamp
4. Uploads your input data to Azure Blob Storage (audit trail starts)

The backend prepares to run the 5-agent pipeline.

#### Step 4: Backend Opens SSE Connection

FastAPI opens a streaming connection back to your frontend. This means:
- You stay connected (no need to refresh)
- Backend can push updates without frontend asking
- Every 10 seconds: backend sends "keepalive" message to prevent timeout
- Frontend receives real-time updates about agent progress

Frontend sees:
```
data: {"event": "ready"}
```

The connection is established and active.

## PHASE 3: The 5-Agent Pipeline (Azure AI Foundry)

Five AI agents run in sequence (one after another). Each one gets the output of the previous agent.

### Agent 1: Bank Statement Parser (GPT-4o-mini)

Model: GPT-4o-mini (fast, cheap)
Location: Azure OpenAI (your data stays in your tenant)
Input: 35 raw bank transactions
Task: Normalize and flag each one
Output: Clean transactions + flags
Time: 5 seconds

What it does:
- Cleans payer names (removes special characters, standardizes format)
- Parses remittance text (extracts invoice references)
- Detects problems (SWIFT truncation, stale checks, duplicates, FX issues)

Example of Agent 1's work:

Input transaction:
```
{
  "payer": "GREENFIELD TECH SOLUT",
  "amount": 29250.00,
  "remittance": "INV-1001 LESS FREIGHT"
}
```

Agent 1 output:
```
{
  "id": "TXN-001",
  "payer_original": "GREENFIELD TECH SOLUT",
  "payer_normalized": "GREENFIELD TECHNOLOGY SOLUTIONS",
  "amount": 29250.00,
  "remittance_parsed": "INV-1001",
  "flags": ["SWIFT_NAME_TRUNCATION"],
  "extracted_invoice_ref": "INV-1001",
  "severity": 2
}
```

Frontend shows:
```
Bank Statement Parser
Status: Done (5.2 seconds)
Tokens: 3,800
```

### Agent 2: AR Ledger Builder (GPT-4o-mini)

Model: GPT-4o-mini (fast, deterministic)
Input: Agent 1 output + 38 open invoices
Task: Build lookup structures for matching
Output: Customer aliases, invoice index, holds
Time: 6 seconds

What it does:
- Creates customer master (who is who)
- Builds invoice lookup (fast reference for matching)
- Captures holds and disputes (compliance)

Creates these lookup structures:
```
{
  "customer_aliases": {
    "GREENFIELD TECHNOLOGY SOLUTIONS": {
      "customer_id": "CUST-001",
      "aliases": ["GREENFIELD TECH", "GFT", "GREENFIELD TECH SOLUT"]
    }
  },
  "invoice_index": {
    "INV-1001": {
      "customer_id": "CUST-001",
      "amount": 29500.00,
      "aging_bucket": "current"
    }
  },
  "holds": {
    "INV-1002": {
      "reason": "OFAC_SCREENING",
      "escalate": "compliance"
    }
  }
}
```

Frontend shows:
```
Open AR Ledger
Status: Done (6.1 seconds)
Tokens: 4,200

Built lookup structures:
- 38 invoice index entries
- 12 customer aliases
- 2 compliance holds
```

### Agent 3: Reconciliation Engine (GPT-4o + Code Interpreter)

Model: GPT-4o + Code Interpreter (powerful, can run Python)
Input: Normalized transactions (Agent 1) + lookup structures (Agent 2)
Task: Match each transaction to an invoice
Output: Matched + unmatched transactions
Time: 30 seconds

The 8 Matching Strategies (tried in order, stops at first match):

1. Exact Match: amount equals invoice amount AND invoice reference matches
2. Invoice Match: Customer name + invoice reference match
3. Amount Match: Fuzzy name match + exact amount
4. Bundle Match: Sum of multiple invoices equals amount
5. Early Pay Discount: amount = invoice x (1 - discount percent)
6. Freight Deduction: amount = invoice - freight allowance
7. Credit Memo Netting: amount = invoice - credit balance
8. Fuzzy Match: Best guess on name + amount proximity

Example matching in action for TXN-001:

Transaction:
```
{
  "id": "TXN-001",
  "payer_normalized": "GREENFIELD TECHNOLOGY SOLUTIONS",
  "amount": 29250.00,
  "remittance_parsed": "INV-1001"
}
```

Agent 3 logic:
```
Strategy 1 (Exact Match):
  payer matches customer CUST-001? YES
  amount (29,250) equals invoice amount (29,500)? NO
  No match

Strategy 2 (Invoice Match):
  payer matches (after fuzzy matching)? YES
  invoice ref matches (INV-1001)? YES
  amount close (delta = 250)? YES
  Continue to see if freight deduction applies

Strategy 6 (Freight Deduction):
  Known rate for this customer: 0.85 percent of invoice
  29,500 x 0.85 percent = 250
  Agent 3 runs Python code:
    >>> invoice_amount = 29500
    >>> freight_rate = 0.0085
    >>> deduction = invoice_amount * freight_rate
    >>> received_amount = invoice_amount - deduction
    >>> print(f"Expected: {received_amount}, Actual: 29250")
    Expected: 29257.5, Actual: 29250
  MATCH! (small variance acceptable)
```

Agent 3 output:
```
{
  "matched": [
    {
      "txn_id": "TXN-001",
      "invoice_id": "INV-1001",
      "matched_amount": 29250.00,
      "method": "FREIGHT_DEDUCTION",
      "confidence": 0.70,
      "verified_by_code": true
    }
  ],
  "unmatched": [
    {
      "txn_id": "TXN-007",
      "amount": 5000.00,
      "reason": "NO_CUSTOMER_MATCH"
    }
  ]
}
```

Frontend shows:
```
Reconciliation Engine
Status: Done (30 seconds)
Model: gpt-4o + Code Interpreter
Tokens: 6,500

Matching Results:
- 28 transactions matched (80 percent)
- 7 transactions unmatched (20 percent)
- Math verified via Python code
- No hallucination on numbers
```

Why Code Interpreter matters:
Agent 3 does not just think "this looks like a match". It actually runs Python code to verify the math. No guessing. No approximation. Python proves it.

### Agent 4: Mismatch Reasoning (GPT-4o)

Model: GPT-4o (deep reasoning capability)
Input: Unmatched transactions from Agent 3
Task: Understand WHY each didn't match
Output: Business logic analysis + risk tier + routing
Time: 10 seconds

What it does:
- Analyzes each exception
- Determines root cause
- Assigns risk tier (LOW/MEDIUM/HIGH)
- Routes to correct team with SLA

Example exception reasoning for TXN-007:

Input (unmatched transaction):
```
{
  "txn_id": "TXN-007",
  "payer": "ACE CAPITAL PARTNERS",
  "amount": 5000.00
}
```

Agent 4 reasoning:
Payer is ACE Capital Partners.
No matching customer in our records.
But ACE Capital is a known factoring company.

This could be:
- A factored invoice (customer sold invoice to factor)
- Third-party payment (allowed by contract)
- Fraud (least likely)

Business judgment:
ACE Capital doesn't appear in our system, but its a known factor. One of our customers likely sold this invoice to ACE. This is a legitimate payment, but we need to identify which invoice was factored.

Risk assessment: MEDIUM (needs review, but legitimate)
SLA: 24 hours (next business day)
Route to: collections_team (they manage factoring relationships)

Agent 4 output:
```
{
  "txn_id": "TXN-007",
  "reason": "FACTORING_AGENT_PAYMENT",
  "reasoning": "Payer identified as ACE Capital Partners, a known invoicing factoring company. This indicates a factored invoice from one of our customers. Payment is legitimate but requires identification of original invoice and update to customer AR record.",
  "risk_tier": "MEDIUM",
  "sla_hours": 24,
  "escalate_to": "collections_team",
  "suggested_action": "Lookup ACE factor relationships, find original invoice"
}
```

Frontend shows:
```
Mismatch Reasoning
Status: Done (10 seconds)
Model: gpt-4o
Tokens: 4,000

Analyzed 7 exceptions:
- 2 HIGH risk (escalate now)
- 3 MEDIUM risk (review 24h)
- 2 LOW risk (auto-approvable)

Each with routing and SLA
```

### Agent 5: Cash Posting (GPT-4o)

Model: GPT-4o (structured output generation)
Input: All results from Agents 1-4
Task: Generate workqueue items + GL entries
Output: Ready-to-post instructions
Time: 5 seconds

What it does:
- Determines GL account for each item
- Decides if invoice closes, reduces balance, or holds
- Creates workqueue items with priority
- Assigns to right analyst or team
- Sets deadline based on SLA

Example workqueue item generation for TXN-001:

Agent 5 input (summary of all agents):
```
TXN-001 Matched to INV-1001:
- Matched amount: 29,250
- Freight deduction: 250
- Confidence: 70 percent
- Risk tier: MEDIUM
- Reason: Freight deduction needs verification
```

Agent 5 output:
```
{
  "id": "WQ-001",
  "action": "post_and_close",
  "txn_id": "TXN-001",
  "invoice_id": "INV-1001",
  "customer_id": "CUST-001",
  "customer_name": "Greenfield Technology Solutions LLC",
  "amount": 29250.00,
  "gl_account": "1010",
  "freight_deduction": 250.00,
  "deduction_gl_account": "5610",
  "priority": "MEDIUM",
  "assign_to": "analyst_1",
  "due_date": "2025-06-02",
  "notes": "Verify freight deduction with customer. Standard 0.85 percent rate applies.",
  "requires_approval": false
}
```

GL Accounts explained:
- 1010 = Cash (AR Clearing Account) - where the cash sits
- 5610 = Freight Allowance - where the deduction goes
- 9999 = Suspense Account - holds items pending review

Frontend shows:
```
Cash Posting
Status: Done (5 seconds)
Model: gpt-4o
Tokens: 5,500

Workqueue created:
- 28 items ready to post
- 5 items pending approval
- 2 items hold for compliance

Total amount to post: 1,225,000
```

## PHASE 4: Results Are Saved

Azure Blob Storage saves the audit trail:

run_id: a7f3d5e2-1b4c-4d8e-9f2a-...

Files saved:
- bank_statement.json (original input)
- open_ar.json (original input)
- results.json (all 5 agents outputs)
- agent_events.json (timing and model info)

Why store this?
- Audit trail (7-year compliance requirement)
- Immutable record (cannot be changed)
- Traceable decisions (why did Agent 3 decide X?)
- Regulatory requirement (SOX, finance audits)

## PHASE 5: Frontend Shows Results

All 5 agents completed.
Backend sends final SSE event:
```
data: {"event": "swarm_complete", "results": {...}}
```

Frontend receives complete results:
- All agent outputs
- Workqueue items
- Summary statistics

React renders:
- Agent completion status
- Token usage breakdown
- Workqueue table with items
- Transaction details (matched and unmatched)

What you see on screen:

```
CASH APPLICATION ANALYSIS COMPLETE

Pipeline Status:
Done: Bank Statement Parser (5 seconds)
Done: Open AR Ledger (6 seconds)
Done: Reconciliation Engine (30 seconds)
Done: Mismatch Reasoning (10 seconds)
Done: Cash Posting (5 seconds)

Total Time: 56 seconds

RESULTS SUMMARY

Transactions Processed: 35
Transactions Matched: 28 (80 percent)
Transactions Unmatched: 7 (20 percent)
Total Amount Processed: 1,250,000
Amount Ready to Post: 1,225,000
Amount On Hold: 25,000

WORKQUEUE ITEMS (Click to approve or reject)

HIGH PRIORITY: TXN-015 50,000 OFAC Hold
Assign: Compliance Team | Due: TODAY
[Approve] [Reject] [Override Note]

MEDIUM: TXN-001 29,250 Freight Deduction
Assign: Analyst 1 | Due: TOMORROW
[Approve] [Reject] [Override Note]

MEDIUM: TXN-007 5,000 Factoring
Assign: Collections | Due: TOMORROW
[Approve] [Reject] [Override Note]

... 25 more items ...

[Approve All] [Export to CSV] [Post to ERP]
```

## How the Pieces Talk to Each Other

### Frontend to Backend Communication

```
Frontend (React)                    Backend (FastAPI)
    |                                    |
    |--POST /analyze----------->       |
    |(bank_data + ar_data JSON)         |
    |                                    |
    |<--Establish SSE connection--------|
    |                                    |
    |<--Streaming agent updates---------|
    |   data: {"event": "token_delta"}  |
    |                                    |
    |<--More streaming updates----------|
    |   data: {"event": "agent_complete"}|
    |                                    |
    |<--Final results------------------|
    |   data: {"event": "swarm_complete"}|
    |                                    |
    |--React renders workqueue---------|
    |   (Connection closes)              |
```

Key: SSE (Server-Sent Events)
- Frontend opens a persistent connection
- Backend can push updates without frontend asking
- Perfect for showing live progress

### Backend to Azure AI Foundry Communication

```
Backend (FastAPI)              Azure OpenAI Service (LLM Models)
    |                                  |
Agent 1:                              |
    |--Call GPT-4o-mini----------->  |
    |   "Normalize these transactions" |
    |                                  |
    |<--Response (token by token)-----|
    |   {"delta": "The"}               |
    |   {"delta": " ..."}              |
    |   (Stream back to frontend)      |
    |                                  |
Agent 2:                              |
    |--Call GPT-4o-mini----------->  |
    |   "Build lookup tables"          |
    |   (+ Agent 1 output)             |
    |                                  |
    |<--Response (JSON)----------------|
    |   (Pass to Agent 3)              |
    |                                  |
Agent 3:                              |
    |--Call GPT-4o + Code--------->  |
    |   "Match transactions"           |
    |   (+ Agents 1 and 2 outputs)     |
    |                                  |
    |<--Response (JSON + Python execution)|
    |   (Pass to Agent 4)              |
    |                                  |
Agent 4:                              |
    |--Call GPT-4o----------->        |
    |   "Reason about unmatched items" |
    |   (+ Agent 3 output)             |
    |                                  |
    |<--Response (reasoning + routing)-|
    |   (Pass to Agent 5)              |
    |                                  |
Agent 5:                              |
    |--Call GPT-4o----------->        |
    |   "Generate workqueue items"     |
    |   (+ all previous outputs)       |
    |                                  |
    |<--Response (final workqueue)-----|
    |   (Return to frontend)           |
```

Key: Sequential Handoff
- Agent 1 output goes to Agent 2
- Agent 2 output goes to Agent 3
- And so on
- No parallel processing means clean audit trail

### Backend to Azure Blob Storage

```
Backend (FastAPI)              Azure Blob Storage (Audit Trail)
    |                                  |
    |--1. Start of run (step 3)------> |
    |   POST /bank_statement.json      |
    |   (run_id/bank_statement.json)   |
    |                                  |
    |--2. Also upload----------->     |
    |   POST /open_ar.json             |
    |   (run_id/open_ar.json)         |
    |                                  |
    |--3. End of pipeline-------->     |
    |   POST /results.json             |
    |   (run_id/results.json)         |
    |   (Contains all 5 agent outputs) |
    |                                  |
    |--4. Also upload----------->     |
    |   POST /agent_events.json        |
    |   (When each agent started/completed)|
    |                                  |
Storage Structure (your audit trail)  |
/cash-app-runs/                       |
  a7f3d5e2-1b4c.../                   |
    - bank_statement.json              |
    - open_ar.json                     |
    - results.json                     |
    - agent_events.json                |
```

Why this matters:
- Every run is saved
- Cannot be deleted or modified (immutable)
- Auditors can see exactly what happened
- Compliance for 7 years

## The Big Picture: How They Shake Hands Together

Timeline of a complete run:

```
TIME    WHAT IS HAPPENING

0:00    User clicks Run
        Frontend sends data to /analyze
        Backend receives, starts Agent 1

0:01    Agent 1 starts normalizing
        Backend calls GPT-4o-mini
        Azure AI processes
        Backend streams tokens to frontend
        Frontend shows progress

0:05    Agent 1 done
        Backend passes output to Agent 2
        Frontend shows Agent 1 complete

0:06    Agent 2 starts building lookups
        Backend calls GPT-4o-mini
        Azure AI processes
        Frontend shows progress

0:12    Agent 2 done
        Backend passes output to Agent 3
        Frontend shows Agent 2 complete
        Also saving to Azure Blob

0:13    Agent 3 starts matching
        Backend calls GPT-4o + Code
        Azure AI matches transactions
        Python verifies math
        Frontend shows progress

0:23    Keepalive every 10 seconds keeps connection alive
        Frontend shows "Still processing"

0:45    Agent 3 done
        28 matched, 7 unmatched
        Backend passes to Agent 4
        Frontend shows Agent 3 complete
        Saving intermediate results

0:46    Agent 4 starts reasoning
        Backend calls GPT-4o
        Azure AI analyzes exceptions
        Frontend shows progress

1:00    Agent 4 done
        7 exceptions analyzed
        Backend passes to Agent 5
        Frontend shows Agent 4 complete

1:01    Agent 5 starts generating workqueue
        Backend calls GPT-4o
        Azure AI creates items
        Assigns GL accounts
        Frontend shows progress

1:15    Agent 5 done
        35 workqueue items created
        Backend saves all results to Blob
        Frontend shows Agent 5 complete
        Azure Blob stores run_id/results.json

1:16    Pipeline complete
        Backend sends swarm complete event
        Frontend receives complete results
        Frontend renders workqueue table
        YOU see final results
```

Total execution time: 56 seconds (vs 5-6 hours manual)

## What Each Technology Does

Frontend (React/Next.js):
- Job: Be the User Interface
- You upload data here
- You click Run
- You see progress in real-time
- You see final workqueue
- You approve or reject items

Technology: React 18 (UI framework) and Next.js (web framework)
Hosted on: Vercel (CDN for fast loading)
Port: 3000 (your browser)

Backend (FastAPI):
- Job: Orchestrate the 5-agent pipeline
- Receives your request
- Manages SSE streaming connection
- Calls Azure AI Foundry for each agent
- Collects outputs
- Saves to Blob Storage
- Sends results back to frontend

Technology: FastAPI (lightweight Python web framework)
Hosted on: Railway (Docker container)
Port: 8001 (backend server)
Language: Python 3.11

Azure AI Foundry (LLM Models):
- Job: Run the AI agents
- Agent 1: GPT-4o-mini (normalize)
- Agent 2: GPT-4o-mini (build lookups)
- Agent 3: GPT-4o (match)
- Agent 4: GPT-4o (reason)
- Agent 5: GPT-4o (post)

Technology: Azure wrapper around OpenAI models
Hosted on: Microsoft Azure (data stays in-region)
Models: GPT-4o-mini and GPT-4o
Special: Code Interpreter for Agent 3 (runs Python)

Azure Blob Storage (Audit Trail):
- Job: Save immutable records
- Saves every input
- Saves every output
- Saves timing info
- Cannot be deleted
- Compliance requirement (7 years)

Technology: Azure cloud storage
Data organization: By run_id (unique per execution)
Retention: 7 years minimum
Access: Via Python SDK or Azure portal

Azure Application Insights (Monitoring):
- Job: Track performance and errors
- How long each agent took
- How many tokens used
- Error tracking
- Model routing decisions

Technology: Azure monitoring service
Integration: OpenTelemetry (auto-instrumented)
Queries: SQL-like queries to investigate

## Real-World Example: One Transaction Start to Finish

The Transaction:
```
{
  "id": "TXN-001",
  "date": "2025-06-01",
  "payer": "GREENFIELD TECH SOLUT",
  "amount": 29250.00,
  "remittance": "INV-1001 LESS FREIGHT"
}
```

Journey Through the Pipeline:

Step 1: Frontend
- You upload data with this transaction
- React stores in memory
- You click Run Cash Application
- React sends data to /analyze at localhost:8001
- Your browser sends POST request with TXN-001

Step 2: Backend Receives
- FastAPI receives request at /analyze endpoint
- Creates unique run_id
- Saves your data to Azure Blob
- Opens SSE connection to frontend
- Starts Agent 1

Step 3: Agent 1 (Bank Statement Parser)
- Backend: "Agent 1, normalize TXN-001"
- Azure AI: Calling GPT-4o-mini
- Prompt: Normalize payer GREENFIELD TECH SOLUT. Parse remittance INV-1001 LESS FREIGHT. Add any flags.
- GPT-4o-mini: Processing
- Tokens streaming to frontend
- Frontend sees tokens in real-time
- GPT-4o-mini: Done

Output:
```
{
  "id": "TXN-001",
  "payer_original": "GREENFIELD TECH SOLUT",
  "payer_normalized": "GREENFIELD TECHNOLOGY SOLUTIONS",
  "remittance_parsed": "INV-1001",
  "flags": ["SWIFT_NAME_TRUNCATION"]
}
```

Backend saves for Agent 2
Frontend shows Agent 1 complete

Step 4: Agent 2 (AR Ledger Builder)
- Backend: "Agent 2, here is Agent 1 output plus open invoices"
- Azure AI: Calling GPT-4o-mini
- Prompt: Build lookup. Payer GREENFIELD TECHNOLOGY SOLUTIONS matches customer Greenfield Technology Solutions LLC. Create alias map.
- GPT-4o-mini: Building lookup tables
- Output includes customer aliases and invoice index

Backend passes to Agent 3

Step 5: Agent 3 (Reconciliation Engine)
- Backend: "Agent 3, match TXN-001 to an invoice"
- Input: TXN-001 normalized data and lookup structures
- Azure AI: Calling GPT-4o with Code Interpreter
- GPT-4o: Trying matching strategies
- Strategy 1: Exact match? Amount 29,250 not equal to 29,500? No
- Strategy 2: Invoice match? Name matches, ref matches, amount close? Yes, delta = 250
- Could be freight deduction. Continue.
- Strategy 6: Freight deduction?
- Let me calculate with Python

Python code execution:
```
>>> invoice_amount = 29500
>>> freight_rate = 0.0085
>>> expected_deduction = 29500 * 0.0085
>>> expected_received = 29500 - expected_deduction
>>> print(f"Expected: {expected_received}")
Expected: 29257.5
>>> print(f"Actual: 29250")
Actual: 29250
>>> print(f"Variance: {abs(expected_received - 29250)}")
Variance: 7.5
MATCH FOUND! (Variance is acceptable)
```

Output:
```
{
  "txn_id": "TXN-001",
  "invoice_id": "INV-1001",
  "matched_amount": 29250.00,
  "method": "FREIGHT_DEDUCTION",
  "confidence": 0.70,
  "verified_by_code": true
}
```

Backend saves for Agent 4

Step 6: Agent 4 (Mismatch Reasoning)
- Backend: "Agent 4, TXN-001 is matched, so nothing for you here"
- Agent 4 continues with the 7 unmatched items

Step 7: Agent 5 (Cash Posting)
- Backend: "Agent 5, here is matched TXN-001"
- Input: TXN-001 matched to INV-1001 with 250 freight deduction
- Azure AI: Calling GPT-4o
- Prompt: Create workqueue item for TXN-001 matched to INV-1001. Amount 29,250, deduction 250 (freight). Determine GL accounts, priority, assignment.
- GPT-4o: Generating workqueue item

Output:
```
{
  "id": "WQ-001",
  "action": "post_and_close",
  "txn_id": "TXN-001",
  "invoice_id": "INV-1001",
  "customer_id": "CUST-001",
  "customer_name": "Greenfield Technology Solutions LLC",
  "amount": 29250.00,
  "gl_account": "1010",
  "freight_deduction": 250.00,
  "deduction_gl_account": "5610",
  "priority": "MEDIUM",
  "assign_to": "analyst_1",
  "due_date": "2025-06-02",
  "notes": "Verify freight deduction with customer..."
}
```

All agents done

Step 8: Results Saved to Blob
- Backend saves complete results
- PUT to Azure Blob: /cash-app-runs/a7f3d5e2-1b4c.../results.json
- Contains all 5 agents outputs
- PUT to Azure Blob: /cash-app-runs/a7f3d5e2-1b4c.../agent_events.json
- Timing info: Agent 1 took 5 seconds, Agent 3 took 30 seconds, etc.

Step 9: Frontend Shows Result
- Backend sends final SSE event
- data: {"event": "swarm_complete", "results": {...}}
- Frontend receives all results
- React renders workqueue table
- YOU see workqueue item

Final workqueue display:
```
WQ-001 | TXN-001 to INV-1001 | 29,250 plus 250 freight
GL: 1010 / 5610 | Priority: MEDIUM | Analyst: analyst_1
[Approve] [Reject] [Override]
```

## System Architecture Diagram

```
YOUR COMPUTER
    |
    |---Browser (Port 3000)
    |   React/Next.js Frontend
    |   - Upload data
    |   - Click Run
    |   - Watch progress (real-time)
    |   - See workqueue results
    |   - Approve or reject items
    |
    |---Internet
    |   HTTP POST + SSE Stream
    |
    V
RAILWAY CONTAINER (Backend)
    |
    |---FastAPI Backend (Port 8001)
    |   POST /analyze endpoint
    |   Orchestrates 5-agent pipeline
    |   Manages SSE stream
    |   Does:
    |   1. Receives your data
    |   2. Calls Agent 1
    |   3. Gets output, calls Agent 2
    |   4. Gets output, calls Agent 3
    |   5. Gets output, calls Agent 4
    |   6. Gets output, calls Agent 5
    |   7. Saves all results
    |   8. Sends back to frontend
    |
    |---Azure Cloud
    |   |
    |   |---Azure OpenAI (LLM Models)
    |   |   Agent 1: GPT-4o-mini
    |   |   Agent 2: GPT-4o-mini
    |   |   Agent 3: GPT-4o plus Code
    |   |   Agent 4: GPT-4o
    |   |   Agent 5: GPT-4o
    |   |
    |   |---Azure Blob Storage (Audit Trail)
    |   |   Saves every run
    |   |   - Inputs
    |   |   - Agent outputs
    |   |   - Timing info
    |   |   - 7-year archive
    |   |   - Immutable
```

## Security and Compliance

Data Protection:
- Your data is encrypted in transit (TLS 1.3)
- Your data is encrypted at rest (AES-256) in Azure
- Never leaves Azure tenant (not sent to OpenAI public cloud)
- Service Principal auth (no API keys stored in code)
- Audit trail saved immediately

Compliance:
OFAC Screening happens as a pre-check in Agent 3, before any AI processing.
If OFAC trigger: Hold transaction immediately, escalate to compliance team same-day, do not process further.

Audit Trail:
Everything saved to Blob:
- Inputs (what you uploaded)
- Agent decisions (why Agent 3 matched this way)
- Outputs (workqueue items)
- Timing (which agent took how long)
- Model routing (which model ran when)
- Immutable (cannot be changed)
- 7-year retention

Auditors can ask: "Why did Agent 3 post TXN-007 as 5K freight deduction?"
Answer: "Here is the agent output, the reasoning, the Python code verification."

## Layman's Summary

In the simplest possible terms:

1. You upload a bank statement (35 transactions) and open invoices (38 items) to a web app.

2. Frontend (React): Shows your data, you click Run, and opens a live connection to the backend.

3. Backend (FastAPI): Receives your data, creates a unique ID, saves your data for safety, and starts calling AI agents.

4. Agent 1 (GPT-4o-mini): Here are 35 messy payer names, let me clean them up. Done in 5 seconds.

5. Agent 2 (GPT-4o-mini): Here are 38 invoices and cleaned names, let me build a lookup table. Done in 6 seconds.

6. Agent 3 (GPT-4o plus Python): Here are cleaned transactions and a lookup table. Let me match each transaction to an invoice. If math does not add up, I will verify with Python code. Done in 30 seconds. Result: 28 matched, 7 unmatched.

7. Agent 4 (GPT-4o): For these 7 unmatched items, why did not they match? Are they legitimate? What is the risk? Assigns priority and routes to right team. Done in 10 seconds.

8. Agent 5 (GPT-4o): Now create workqueue items for all 35 transactions. Tell me which GL account, who should handle it, and when its due. Done in 5 seconds.

9. Backend saves everything to a vault (Azure Blob Storage) for audits, then sends results to Frontend.

10. You see a table of 35 workqueue items. You can approve, reject, or change any of them.

Total time: 56 seconds for what takes a human 5 to 6 hours.

## Key Concepts Explained in Plain English

Sequential vs Parallel:
- Sequential: Agent 1 finishes then Agent 2 starts then Agent 3 starts (what we do)
  Pro: Clean audit trail, each step depends on previous
  Con: Takes longer (but still 56 seconds vs 6 hours)
- Parallel: All agents run at same time
  Pro: Faster
  Con: Cannot verify dependencies, audit trail messy

SSE (Server-Sent Events):
- Backend pushes updates to frontend without frontend asking
- Like: Hey, Agent 1 just finished. vs Are you done yet? How about now?
- Keepalive: Every 10 seconds, backend sends I am still here so proxy does not timeout

Streaming Tokens:
- AI models generate text token by token (word by word)
- Instead of wait 30 seconds for full response, you see it live
- Like watching someone type vs getting an email

Code Interpreter:
- Agent 3 does not just say this looks like a match
- It actually runs Python code to verify the math
- No hallucination on numbers

Immutable Audit Trail:
- Everything saved to Blob Storage
- Cannot be deleted or modified
- Regulators can see exactly what happened
- Proof: Agent 3 matched TXN-007 because Python verified the math

## Performance Expectations

Pipeline execution:
Agent 1: 5 seconds (normalize)
Agent 2: 6 seconds (build lookups)
Agent 3: 30 seconds (match)
Agent 4: 10 seconds (reason)
Agent 5: 5 seconds (post)
TOTAL: 56 seconds

Token usage:
Agent 1: 1,200 in, 1,800 out
Agent 2: 1,500 in, 2,500 out
Agent 3: 4,000 in, 2,500 out
Agent 4: 2,500 in, 1,500 out
Agent 5: 3,500 in, 2,000 out
TOTAL: 15,200 in, 10,300 out = 25,500 tokens

Cost (Azure pricing):
Agent 1 and 2: Very cheap (using mini)
Agent 3: Medium (using GPT-4o plus Code)
Agent 4 and 5: Medium (using GPT-4o)
Total: About 15 cents per run (vs 60 cents if all used GPT-4o)

Scale:
1 transaction: About 2 seconds
100 transactions: About 200 seconds
1,000 transactions: Would need batching

## What Happens When You Approve a Workqueue Item

You (in Frontend): Click [Approve] on WQ-001

Frontend: POST /workqueue/WQ-001/approve

Backend: Receives approval

Backend: Prepares GL posting

Journal entry:
Debit: GL 1010 (Cash) 29,250
Credit: GL 1200 (AR) 29,250

Deduction entry:
Debit: GL 5610 (Freight) 250
Credit: GL 1200 (AR) 250

Backend: (In production) Posts to ERP (SAP/Oracle/NetSuite)
(In MVP) Shows Ready to post with GL entries

AR Analyst: Completes work in AR system

Done: Transaction posted, invoice closed

## Final Recap: The Complete Journey

START

You upload data
Frontend stores in memory
You click Run
React opens SSE connection

Backend: /analyze endpoint receives POST

Agent 1: Cleaned 35 transaction names

Agent 2: Built lookup table of invoices

Agent 3: Matched 28 transactions (verified with code)

Agent 4: Analyzed 7 unmatched items (risk routing)

Agent 5: Created 35 workqueue items (GL accounts)

Storage: Saved everything (audit trail secure)

Frontend: Showing you the workqueue

You: Reviewing and approving items

System: Posts to ERP (in production)

COMPLETE

Done in 56 seconds (vs 6 hours manual).

This is how the system works in plain English. No tech degree required.
