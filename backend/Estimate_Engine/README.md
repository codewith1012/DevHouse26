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

Then open the local Streamlit URL, enter an issue id such as `KAN-15`, and use the tabs to:

- run requirement estimation
- send commit, PR, test-failure, and rework signals
- poll unseen `extension_events`
- close the feedback loop
- inspect the consolidated dashboard view

## API

- `POST /estimate`
- `POST /estimate/from-issue/{issue_id}`
- `POST /signals/commit`
- `POST /signals/extension`
- `POST /signals/pr`
- `POST /signals/test-failure`
- `POST /signals/rework`
- `GET /estimate/history/{issue_id}`
- `GET /dashboard/{issue_id}`
- `POST /estimate/poll-extension-events`
- `POST /feedback/close-issue`
- `GET /feedback/summary`
- `GET /estimate/{id}`
- `POST /update-from-commit`

## Notes

- Current storage uses an in-memory repository for fast prototyping.
- `POST /estimate/from-issue/{issue_id}` reads the requirement from `req_code_mapping`, computes `heuristic_score`, `llm_score`, `final_score`, `confidence`, `uncertainty`, and `estimate_breakdown`, then writes those values back to Supabase.
- `POST /signals/commit` stores a commit event in `development_signals`, analyzes commit impact, applies a commit-aware delta to the estimate, and appends to `estimate_history` when the score changes.
- `POST /signals/extension` accepts the telemetry extension payload shape directly, maps it into the commit signal flow, and uses `issue_id` or `linked_issue` from the extension event to locate the requirement row.
- `POST /signals/pr`, `POST /signals/test-failure`, and `POST /signals/rework` let the engine ingest broader development signals beyond commits.
- `GET /estimate/history/{issue_id}` returns the score timeline for one issue.
- `GET /dashboard/{issue_id}` returns the current estimate, drift level, latest feedback error, recent signals, estimate history, and extension polling visibility in one response.
- `POST /feedback/close-issue` computes an actual-effort proxy and stores prediction error in `estimate_feedback`.
- `GET /feedback/summary` returns average error metrics plus adaptive heuristic/LLM weights derived from historical feedback.
- If `EXTENSION_POLL_ENABLED=true`, the app polls `extension_events` in the background and processes unseen events automatically.
- If `final_score` changes, the backend appends a record to `estimate_history` with the old score, new score, reason, and timestamp.
- Ollama calls are optional; when disabled or unavailable, the service falls back to a local stub estimate.
