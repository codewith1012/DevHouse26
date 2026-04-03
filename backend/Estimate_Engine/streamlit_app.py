import json

import requests
import streamlit as st


st.set_page_config(page_title="Estimate Engine Tester", page_icon="🧪", layout="wide")

DEFAULT_API_BASE = "http://127.0.0.1:8000"


def call_health(api_base: str) -> tuple[bool, str]:
    try:
        response = requests.get(f"{api_base}/health", timeout=10)
        response.raise_for_status()
        return True, response.text
    except requests.RequestException as exc:
        return False, str(exc)


def call_issue_estimate(api_base: str, issue_id: str) -> tuple[bool, dict | str]:
    try:
        response = requests.post(f"{api_base}/estimate/from-issue/{issue_id}", timeout=60)
        response.raise_for_status()
        return True, response.json()
    except requests.HTTPError:
        try:
            return False, response.json()
        except ValueError:
            return False, response.text
    except requests.RequestException as exc:
        return False, str(exc)


st.title("Estimate Engine Tester")
st.caption("Simple UI to test the FastAPI estimation backend against Supabase and Ollama.")

with st.sidebar:
    st.header("Connection")
    api_base = st.text_input("FastAPI base URL", value=DEFAULT_API_BASE).rstrip("/")
    issue_id = st.text_input("Issue ID", value="KAN-15")

    health_clicked = st.button("Check Health", use_container_width=True)
    estimate_clicked = st.button("Run Estimate", type="primary", use_container_width=True)

if health_clicked:
    ok, result = call_health(api_base)
    if ok:
        st.success("Backend is reachable.")
        st.code(result, language="json")
    else:
        st.error("Health check failed.")
        st.code(result)

st.subheader("Estimate Request")
st.write("Click `Run Estimate` to fetch the requirement from Supabase, score it, and write results back.")

if estimate_clicked:
    if not issue_id.strip():
        st.warning("Enter an issue id first.")
    else:
        with st.spinner(f"Scoring {issue_id}..."):
            ok, result = call_issue_estimate(api_base, issue_id.strip())

        if ok:
            st.success(f"Estimate completed for {issue_id}.")
            response = result
            left, right = st.columns(2)
            with left:
                st.metric("Heuristic Score", response.get("heuristic_score"))
                st.metric("LLM Score", response.get("llm_score"))
                st.metric("Final Score", response.get("final_score"))
            with right:
                st.metric("Confidence", response.get("confidence"))
                st.metric("Uncertainty", response.get("uncertainty"))
                st.metric("Status", response.get("status"))

            st.markdown("### Requirement")
            st.write(response.get("requirement", ""))

            st.markdown("### Estimate Breakdown")
            st.dataframe(response.get("estimate_breakdown", []), use_container_width=True)

            st.markdown("### Full Response")
            st.code(json.dumps(response, indent=2), language="json")
        else:
            st.error("Estimate request failed.")
            if isinstance(result, dict):
                st.code(json.dumps(result, indent=2), language="json")
            else:
                st.code(str(result))
