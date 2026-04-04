from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from routers import jira
from services.jira_sync import get_jira_client
import asyncio
import uvicorn
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="DevPulse Backend")

# Allow all origins for hackathon / VS Code extension access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(jira.router)


async def run_startup_backfill() -> None:
    try:
        client = get_jira_client()
        await asyncio.to_thread(client.backfill_missing_requirement_embeddings)
    except Exception as exc:
        print(f"[ERROR] Startup Jira embedding backfill failed: {exc}")

@app.on_event("startup")
async def startup_event():
    """
    Triggers JIRA sync.
    We removed the bulk-sync on startup because downloading AI models + fetching whole
    Jira boards blocks the fastAPI server and causes Render 502 Timeouts!
    The webhook covers new tickets anyway.
    """
    print("[INFO] Server starting successfully...")
    try:
        get_jira_client()
        print("[INFO] Jira client + embedding model are warm.")
        asyncio.create_task(run_startup_backfill())
    except Exception as exc:
        print(f"[ERROR] Failed to warm Jira client/model: {exc}")
    # client = JiraClient()
    # try:
    #     count = client.sync_all_tickets()
    #     print(f"[INFO] Startup sync complete. Synced {count} tickets.")
    # except Exception as e:
    #     print(f"[ERROR] Startup sync failed: {e}")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """
    Silences the browser's automatic favicon.ico request.
    """
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "devpulse-backend",
        "timestamp": os.popen('date /t' if os.name == 'nt' else 'date').read().strip()
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
