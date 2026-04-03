# Estimate Engine

FastAPI backend for:

- receiving requirements
- extracting heuristic features
- calling Ollama
- combining heuristic and LLM estimates
- storing estimates
- handling commit-driven updates
- returning results to the frontend

## Structure

```text
Estimate_Engine/
├── main.py
├── routes/
├── services/
├── models/
└── database/
```

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

## Test with Streamlit

```powershell
streamlit run streamlit_app.py
```

Then open the local Streamlit URL, enter an issue id such as `KAN-15`, and click `Run Estimate`.

## API

- `POST /estimate`
- `POST /estimate/from-issue/{issue_id}`
- `GET /estimate/{id}`
- `POST /update-from-commit`

## Notes

- Current storage uses an in-memory repository for fast prototyping.
- `POST /estimate/from-issue/{issue_id}` reads the requirement from `req_code_mapping`, computes `heuristic_score`, `llm_score`, `final_score`, `confidence`, `uncertainty`, and `estimate_breakdown`, then writes those values back to Supabase.
- If `final_score` changes, the backend appends a record to `estimate_history` with the old score, new score, reason, and timestamp.
- Ollama calls are optional; when disabled or unavailable, the service falls back to a local stub estimate.
