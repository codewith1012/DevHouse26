from models.schemas import CommitUpdateRequest


class DriftEngine:
    def summarize_commit_impact(self, payload: CommitUpdateRequest) -> str:
        files_changed = len(payload.changed_files)
        message = payload.commit_message.strip() or "No commit message provided"
        return (
            f"Commit impact review: {files_changed} changed files. "
            f"Latest commit message: {message}"
        )


drift_engine = DriftEngine()
