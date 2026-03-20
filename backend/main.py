from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import jira
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
