from fastapi import FastAPI

from routes.estimate import router as estimate_router
from services.extension_poller import extension_poller


app = FastAPI(
    title="Estimate Engine API",
    version="0.1.0",
    description="Backend service for requirement estimation using heuristics plus Ollama.",
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event() -> None:
    await extension_poller.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await extension_poller.stop()


app.include_router(estimate_router)
