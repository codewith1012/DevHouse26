from fastapi import FastAPI

from routes.estimate import router as estimate_router


app = FastAPI(
    title="Estimate Engine API",
    version="0.1.0",
    description="Backend service for requirement estimation using heuristics plus Ollama.",
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(estimate_router)
