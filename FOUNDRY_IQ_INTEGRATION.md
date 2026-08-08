# Foundry IQ Integration for Agents League

## Overview

This document outlines how to integrate **Microsoft Foundry IQ** (agentic knowledge retrieval) into the Cash Application Foundry system for the Agents League Hackathon (Reasoning Agents track).

**Submission Track:** Reasoning Agents (multi-step reasoning pipeline)
**Microsoft IQ Layer:** Foundry IQ (enterprise knowledge retrieval with permissions)
**Deadline:** June 14, 2026

---

## What is Foundry IQ?

Foundry IQ provides:
- **Semantic search** across multiple enterprise data sources (contracts, customer profiles, invoice history, compliance registers)
- **Permissions enforcement** — only retrieve data the querying agent is authorized to see
- **Source citations** — every answer is grounded in specific documents, reducing hallucination
- **RAG pipeline** — retrieval-augmented generation for factual accuracy

**Current gap in Cash App:** Agent 2 (AR Ledger) and Agent 3 (Reconciliation) work from static JSON. With Foundry IQ, they query live enterprise sources.

---

## Integration Points

### 1. **AR Ledger Agent (Agent 2)** — Query Customer Master Data

**Today:** Reads a static `open_ar.json` file with invoices + aliases

**With Foundry IQ:**
```
Query Foundry for:
  • Customer master data (names, aliases, parent/subsidiary relationships)
  • Open invoices by customer
  • Payment terms and credit limits
  • Dispute/hold status
```

**Benefit:** Agent 2 retrieves *current* invoice state instead of static demo data. Grounded in real enterprise data.

**Implementation:**
```python
# In ar_ledger_agent.py system prompt:
foundry_context = client.search_knowledge(
    query="Open invoices for customer Greenfield Technologies",
    filters={"status": "OPEN"},
    limit=50
)
# Foundry returns: [invoice_1, invoice_2, ...] with citations
```

---

### 2. **Reconciliation Agent (Agent 3)** — Retrieve Contract Terms & Deduction History

**Today:** Tries 8 matching strategies on static data

**With Foundry IQ:**
```
Query Foundry for:
  • Contract terms (freight allowance rates, early-pay discounts)
  • Historical deductions for this customer
  • Factoring agent registry
  • Intercompany netting agreements
```

**Benefit:** Agent 3 doesn't guess at deduction legitimacy—it grounds the match logic in actual contract terms retrieved from Foundry.

**Example:**
```
Transaction: Customer paid $29,250 (invoice is $29,500, $250 short)

Without Foundry:
  Agent 3 guesses: "Might be freight? Might be damage claim?"
  
With Foundry:
  Foundry retrieves: "Contract INV-29500 allows 1.5% freight deduction"
  Agent 3 matches: $250 = 0.85% of $29,500 → likely freight
  Output includes: "Matched via freight deduction (see contract INV-29500-clause-7.2)"
```

---

### 3. **Mismatch Reasoning Agent (Agent 4)** — Ground Exception Analysis in Evidence

**Today:** Reasons about edge cases from Agent 3's output

**With Foundry IQ:**
```
Query Foundry for:
  • Similar past disputes from this vendor
  • Vendor risk profile
  • Compliance holds / legal disputes
  • OFAC / sanctions registry
```

**Benefit:** Agent 4 doesn't just reason abstractly—every recommendation is backed by cited evidence from Foundry.

**Example:**
```
Transaction flagged as "possible unauthorized short pay"

Foundry queries:
  • Historical short pays from this vendor: found 3 past incidents (Q1-Q2)
  • Vendor risk profile: "Greenfield has history of aggressive deduction claims"
  • Dispute history: none currently active
  
Agent 4 output:
  "Recommend escalation to deductions team. Similar pattern from vendor in Q1-Q2.
   Source: Foundry vendor_risk_registry, dispute_history_2024"
```

---

## Architecture: Foundry IQ Integration

### Client Setup
```python
# New file: backend/agents/foundry_client.py

from azure.ai.foundry import FoundryClient, SearchFilter
from azure.identity import DefaultAzureCredential

class FoundryIQClient:
    def __init__(self, endpoint: str, index_name: str = "cash_app_knowledge"):
        self.client = FoundryClient(
            credential=DefaultAzureCredential(),
            endpoint=endpoint
        )
        self.index_name = index_name
    
    def search_invoices(self, customer_id: str, status: str = None):
        """Retrieve invoices from Foundry knowledge base"""
        filters = [SearchFilter("customer_id", "eq", customer_id)]
        if status:
            filters.append(SearchFilter("status", "eq", status))
        
        results = self.client.search(
            index=self.index_name,
            query=f"invoices for customer {customer_id}",
            filters=filters,
            top=50
        )
        return results
    
    def search_contract_terms(self, invoice_id: str):
        """Retrieve contract terms for an invoice"""
        results = self.client.search(
            index=self.index_name,
            query=f"contract terms for invoice {invoice_id}",
            filters=[SearchFilter("doc_type", "eq", "contract")],
            top=5
        )
        return results
    
    def search_vendor_history(self, vendor_name: str):
        """Retrieve vendor dispute/deduction history"""
        results = self.client.search(
            index=self.index_name,
            query=f"deduction history and disputes for {vendor_name}",
            filters=[SearchFilter("doc_type", "in", ["dispute", "deduction"])],
            top=20
        )
        return results
    
    def search_compliance(self, transaction_id: str):
        """Check for compliance holds, OFAC flags, legal holds"""
        results = self.client.search(
            index=self.index_name,
            query=f"compliance holds for transaction {transaction_id}",
            filters=[SearchFilter("doc_type", "in", ["compliance", "hold", "ofac"])],
            top=10
        )
        return results
```

### Agent Prompts (Updated)

**AR Ledger Agent (Agent 2):**
```python
# Before running Agent 3, query Foundry to enrich the ledger
foundry_results = foundry_client.search_invoices(customer_id="*")
# Inject Foundry results into system prompt as context
```

**Reconciliation Agent (Agent 3):**
```python
# When evaluating a transaction, query Foundry for contract terms
contract_terms = foundry_client.search_contract_terms(invoice_id=txn["invoice_id"])
# Include contract evidence in matching strategy
```

**Mismatch Reasoning Agent (Agent 4):**
```python
# For flagged exceptions, query vendor history and compliance
vendor_history = foundry_client.search_vendor_history(vendor_name=txn["payer"])
compliance_check = foundry_client.search_compliance(transaction_id=txn["id"])
# Ground the reasoning in cited sources
```

---

## Knowledge Base Schema (What to Index in Foundry)

### Documents to Index:

1. **Customer Master Data**
   ```json
   {
     "doc_type": "customer",
     "customer_id": "CUST-001",
     "name": "Greenfield Technology Solutions LLC",
     "aliases": ["GREENFIELD TECH SOLUT", "Greenfield Tech"],
     "parent_customer_id": null,
     "factoring_agent": null,
     "credit_limit": 500000
   }
   ```

2. **Invoices**
   ```json
   {
     "doc_type": "invoice",
     "invoice_id": "INV-29500",
     "customer_id": "CUST-001",
     "amount": 29500,
     "status": "OPEN",
     "payment_terms": "2/10 NET 30",
     "created_date": "2026-05-01"
   }
   ```

3. **Contracts**
   ```json
   {
     "doc_type": "contract",
     "contract_id": "CST-2024-001",
     "customer_id": "CUST-001",
     "freight_allowance_pct": 1.5,
     "damage_claim_process": "documented_with_carrier",
     "dispute_clause": "..."
   }
   ```

4. **Vendor Profiles**
   ```json
   {
     "doc_type": "vendor_profile",
     "vendor_name": "Greenfield Technology Solutions",
     "risk_level": "medium",
     "deduction_pattern": "2-3% freight claims typical",
     "past_disputes_count": 3
   }
   ```

5. **Compliance Registry**
   ```json
   {
     "doc_type": "compliance",
     "invoice_id": "INV-29500",
     "holds": ["legal_dispute_123"],
     "ofac_status": "clear",
     "payment_blocked": false
   }
   ```

---

## MVP Implementation (For Agents League)

**Phase 1 (Week 1-2):**
1. Set up Foundry IQ knowledge base with sample data (contracts, customer master, vendor profiles)
2. Implement `foundry_client.py` with basic search methods
3. Update Agent 2 (AR Ledger) to query Foundry for customer + invoice data
4. Update Agent 4 (Mismatch Reasoning) to cite Foundry sources

**Phase 2 (Submission):**
1. Demo video shows:
   - Agent 2 retrieving live customer data from Foundry
   - Agent 4 reasoning about edge cases with Foundry-sourced evidence
   - Each decision includes citation: `(Foundry: vendor_profile_2024, confidence 0.92)`
2. README documents Foundry integration and knowledge base schema

**Phase 3 (Post-Hackathon):**
- Integrate Agent 3 (Reconciliation) fully with contract term retrieval
- Add real document ingestion (PDF contracts → Foundry via Document Intelligence)
- Implement permissions enforcement per user/company

---

## Why This Wins on Judging Criteria

| Criterion | Benefit |
|-----------|---------|
| **Accuracy & Relevance (20%)** | Foundry grounds every decision in enterprise data, not static demo files |
| **Reasoning & Multi-step Thinking (20%)** | 5 agents + Foundry retrieval = clear, traceable reasoning chain |
| **Creativity & Originality (15%)** | Thinking of AR reconciliation as a retrieval + reasoning problem is novel |
| **User Experience & Presentation (15%)** | Demo shows live Foundry queries with cited sources → professional, auditable |
| **Reliability & Safety (20%)** | Foundry enforces permissions + compliance checks before agents process data |

---

## Environment Setup

Add to `backend/.env`:

```
# Foundry IQ Configuration
FOUNDRY_ENDPOINT=https://your-foundry-project.services.ai.azure.com
FOUNDRY_INDEX_NAME=cash_app_knowledge
FOUNDRY_API_VERSION=2024-12-01-preview
```

---

## Next Steps

1. **Verify Foundry access** — Do you have an Azure AI Foundry project with Foundry IQ enabled?
2. **Create knowledge base** — Decide: manual JSON seed, or ingest sample contracts/invoices?
3. **Build foundry_client.py** — Implement search methods
4. **Update agent prompts** — Inject Foundry results into system context
5. **Test E2E** — Run demo with Foundry retrieval enabled
6. **Record demo video** — Show agent + Foundry interaction
7. **Submit before June 14**

---

## References

- [Microsoft Foundry IQ Documentation](https://learn.microsoft.com/en-us/azure/ai-foundry/)
- [Agents League Discord](https://aka.ms/agentsleague/discord)
- [Reasoning Agents Track](https://aka.ms/agentsleague/aisf)
