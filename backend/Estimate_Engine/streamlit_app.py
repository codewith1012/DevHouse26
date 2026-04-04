import json

import requests
import streamlit as st


st.set_page_config(page_title="Estimate Engine Tester", page_icon="EE", layout="wide")

DEFAULT_API_BASE = "http://127.0.0.1:8000"


def call_api(method: str, url: str, json_body: dict | None = None, timeout: int = 60) -> tuple[bool, dict | list | str]:
    try:
        response = requests.request(method=method, url=url, json=json_body, timeout=timeout)
        response.raise_for_status()
        try:
            return True, response.json()
        except ValueError:
            return True, response.text
    except requests.HTTPError:
        try:
            return False, response.json()
        except ValueError:
            return False, response.text
    except requests.RequestException as exc:
        return False, str(exc)


def render_result(ok: bool, result: dict | list | str, success_message: str) -> None:
    if ok:
        st.success(success_message)
        if isinstance(result, (dict, list)):
            st.code(json.dumps(result, indent=2), language="json")
        else:
            st.code(str(result))
    else:
        st.error("Request failed.")
        if isinstance(result, (dict, list)):
            st.code(json.dumps(result, indent=2), language="json")
        else:
            st.code(str(result))


def render_dashboard(data: dict) -> None:
    current = data.get("current_estimate") or {}
    left, mid, right = st.columns(3)
    with left:
        st.metric("Final Score", current.get("final_score", 0))
        st.metric("Heuristic Score", current.get("heuristic_score", 0))
    with mid:
        st.metric("LLM Score", current.get("llm_score", 0))
        st.metric("Confidence", current.get("confidence", 0))
    with right:
        st.metric("Drift Level", data.get("drift_level", "unknown"))
        st.metric("Uncertainty", current.get("uncertainty", "unknown"))

    st.markdown("### Current Breakdown")
    st.dataframe(current.get("estimate_breakdown", []), use_container_width=True)

    st.markdown("### Feedback Summary")
    feedback_summary = data.get("feedback_summary") or {}
    summary_cols = st.columns(4)
    summary_cols[0].metric("Samples", feedback_summary.get("total_samples", 0))
    summary_cols[1].metric("Avg Abs Error", feedback_summary.get("avg_absolute_error", 0))
    summary_cols[2].metric("Avg Rel Error", feedback_summary.get("avg_relative_error", 0))
    summary_cols[3].metric("Avg Actual Proxy", feedback_summary.get("avg_actual_effort_proxy", 0))
    st.caption(f"Adaptive weights: {json.dumps((feedback_summary.get('adaptive_weights') or {}), indent=2)}")

    st.markdown("### Latest Feedback Error")
    st.code(json.dumps(data.get("feedback_error"), indent=2), language="json") if data.get("feedback_error") else st.info("No feedback record yet.")

    st.markdown("### Recent Signal Timeline")
    st.dataframe(data.get("recent_signal_timeline", []), use_container_width=True)

    st.markdown("### Estimate History")
    st.dataframe(data.get("estimate_history", []), use_container_width=True)

    poll_status = data.get("poll_status") or {}
    st.markdown("### Extension Poll Status")
    poll_cols = st.columns(2)
    poll_cols[0].metric("Pending Extension Events", poll_status.get("pending_events", 0))
    poll_cols[1].metric("Processed Signal Count", len(poll_status.get("recent_processed_signal_ids", [])))
    st.write("Pending Event IDs")
    st.code(json.dumps(poll_status.get("pending_event_ids", []), indent=2), language="json")
    st.write("Recent Processed Signal IDs")
    st.code(json.dumps(poll_status.get("recent_processed_signal_ids", []), indent=2), language="json")
    st.write("Recent Processed Signals")
    st.dataframe(poll_status.get("recent_processed_signals", []), use_container_width=True)


st.title("Estimate Engine Tester")
st.caption("End-to-end tester for requirements, development signals, feedback learning, and extension polling.")

with st.sidebar:
    st.header("Connection")
    api_base = st.text_input("FastAPI base URL", value=DEFAULT_API_BASE).rstrip("/")
    issue_id = st.text_input("Issue ID", value="KAN-15")
    if st.button("Check Health", use_container_width=True):
        ok, result = call_api("GET", f"{api_base}/health")
        render_result(ok, result, "Backend is reachable.")

tabs = st.tabs(["Estimate", "Signals", "Feedback", "Dashboard"])

with tabs[0]:
    st.subheader("Requirement Estimate")
    if st.button("Run Estimate From Issue", type="primary"):
        ok, result = call_api("POST", f"{api_base}/estimate/from-issue/{issue_id}")
        if ok and isinstance(result, dict):
            left, right = st.columns(2)
            left.metric("Heuristic Score", result.get("heuristic_score"))
            left.metric("LLM Score", result.get("llm_score"))
            right.metric("Final Score", result.get("final_score"))
            right.metric("Confidence", result.get("confidence"))
            st.dataframe(result.get("estimate_breakdown", []), use_container_width=True)
        render_result(ok, result, f"Estimate completed for {issue_id}.")

with tabs[1]:
    st.subheader("Development Signals")
    signal_tab_commit, signal_tab_pr, signal_tab_test, signal_tab_rework, signal_tab_poll = st.tabs(
        ["Commit", "PR", "Test Failure", "Rework", "Poll Extension Events"]
    )

    with signal_tab_commit:
        commit_sha = st.text_input("Commit SHA", value="demo-commit-001")
        commit_message = st.text_input("Commit Message", value="KAN-15 add validation and tests")
        commit_files = st.text_area("Changed Files", value="backend/addition.py\nbackend/test_addition.py")
        commit_lines_added = st.number_input("Lines Added", min_value=0, value=20)
        commit_lines_deleted = st.number_input("Lines Deleted", min_value=0, value=5)
        if st.button("Send Commit Signal"):
            payload = {
                "issue_id": issue_id,
                "commit_sha": commit_sha,
                "commit_message": commit_message,
                "changed_files": [line.strip() for line in commit_files.splitlines() if line.strip()],
                "files_added": 1,
                "files_deleted": 0,
                "lines_added": int(commit_lines_added),
                "lines_deleted": int(commit_lines_deleted),
                "tests_changed": 1 if "test" in commit_files.lower() else 0,
            }
            ok, result = call_api("POST", f"{api_base}/signals/commit", payload)
            render_result(ok, result, "Commit signal processed.")

    with signal_tab_pr:
        pr_title = st.text_input("PR Title", value="KAN-15 add validation workflow", key="pr_title")
        pr_number = st.number_input("PR Number", min_value=0, value=15)
        pr_comments = st.number_input("Review Comments", min_value=0, value=3)
        pr_rounds = st.number_input("Review Rounds", min_value=1, value=1)
        pr_files = st.text_area("PR Changed Files", value="backend/addition.py\nbackend/test_addition.py", key="pr_files")
        pr_labels = st.text_input("PR Labels (comma-separated)", value="backend,needs-review")
        pr_reopened = st.checkbox("PR Reopened", value=False)
        if st.button("Send PR Signal"):
            payload = {
                "issue_id": issue_id,
                "pr_number": int(pr_number),
                "title": pr_title,
                "review_comments": int(pr_comments),
                "review_rounds": int(pr_rounds),
                "lines_added": 35,
                "lines_deleted": 8,
                "changed_files": [line.strip() for line in pr_files.splitlines() if line.strip()],
                "labels": [label.strip() for label in pr_labels.split(",") if label.strip()],
                "is_reopened": pr_reopened,
            }
            ok, result = call_api("POST", f"{api_base}/signals/pr", payload)
            render_result(ok, result, "PR signal processed.")

    with signal_tab_test:
        suite = st.text_input("Suite", value="backend")
        failed_tests = st.number_input("Failed Tests", min_value=0, value=4)
        failing_files = st.text_area("Failing Files", value="backend/test_addition.py")
        error_types = st.text_input("Error Types (comma-separated)", value="assertion,timeout")
        severity = st.selectbox("Severity", ["low", "medium", "high", "critical"], index=1)
        if st.button("Send Test Failure Signal"):
            payload = {
                "issue_id": issue_id,
                "suite": suite,
                "failed_tests": int(failed_tests),
                "failing_files": [line.strip() for line in failing_files.splitlines() if line.strip()],
                "error_types": [label.strip() for label in error_types.split(",") if label.strip()],
                "severity": severity,
            }
            ok, result = call_api("POST", f"{api_base}/signals/test-failure", payload)
            render_result(ok, result, "Test failure signal processed.")

    with signal_tab_rework:
        reason = st.text_area("Rework Reason", value="Reviewer requested extra validation and edge-case handling.")
        reopened = st.checkbox("Issue Reopened", value=True)
        review_comments = st.number_input("Review Comments Count", min_value=0, value=5, key="rework_comments")
        changed_files = st.text_area("Rework Changed Files", value="backend/addition.py\nbackend/validator.py", key="rework_files")
        if st.button("Send Rework Signal"):
            payload = {
                "issue_id": issue_id,
                "reason": reason,
                "reopened": reopened,
                "review_comments": int(review_comments),
                "changed_files": [line.strip() for line in changed_files.splitlines() if line.strip()],
            }
            ok, result = call_api("POST", f"{api_base}/signals/rework", payload)
            render_result(ok, result, "Rework signal processed.")

    with signal_tab_poll:
        st.write("Use this to manually poll unseen rows from `extension_events` and inspect dedup visibility.")
        if st.button("Poll Extension Events"):
            ok, result = call_api("POST", f"{api_base}/estimate/poll-extension-events", timeout=90)
            render_result(ok, result, "Extension events polled.")

with tabs[2]:
    st.subheader("Feedback Loop")
    actual_hours = st.number_input("Actual Hours (optional, 0 to use proxy)", min_value=0.0, value=0.0, step=0.5)
    if st.button("Close Feedback Loop"):
        payload = {"issue_id": issue_id, "status": "done", "actual_hours": None if actual_hours == 0 else actual_hours}
        ok, result = call_api("POST", f"{api_base}/feedback/close-issue", payload)
        render_result(ok, result, "Feedback record created.")

    if st.button("Get Feedback Summary"):
        ok, result = call_api("GET", f"{api_base}/feedback/summary")
        render_result(ok, result, "Feedback summary loaded.")

with tabs[3]:
    st.subheader("Issue Dashboard")
    if st.button("Load Dashboard"):
        ok, result = call_api("GET", f"{api_base}/dashboard/{issue_id}")
        if ok and isinstance(result, dict):
            render_dashboard(result)
        else:
            render_result(ok, result, "Dashboard loaded.")
