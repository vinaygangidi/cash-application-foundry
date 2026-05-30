import json
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.cash_app import run_cash_application

app = FastAPI(title="Cash Application Foundry API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class AnalyzeRequest(BaseModel):
    bank_data: dict
    ar_data: dict


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cash-application-foundry"}


@app.get("/demo-data")
async def demo_data():
    bank_statement = json.loads((FIXTURES_DIR / "bank_statement.json").read_text())
    open_ar = json.loads((FIXTURES_DIR / "open_ar.json").read_text())
    return {"bank_statement": bank_statement, "open_ar": open_ar}


@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    async def event_stream():
        try:
            async for event in run_cash_application(request.bank_data, request.ar_data):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
