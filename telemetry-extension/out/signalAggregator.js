"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SignalAggregator = void 0;
class SignalAggregator {
    session;
    sessionStartTime;
    constructor() {
        this.resetSession();
    }
    resetSession() {
        this.sessionStartTime = Date.now();
        this.session = {
            session_id: `sess_${Date.now()}`,
            files_opened: 0,
            files_modified: 0,
            lines_added: 0,
            lines_deleted: 0,
            editing_duration_minutes: 0,
            refactor_events: 0
        };
    }
    addFilesOpened(count = 1) {
        this.session.files_opened += count;
    }
    addFileModified() {
        this.session.files_modified += 1;
    }
    addLinesChanged(added, deleted) {
        if (added > 0 || deleted > 0) {
            this.session.lines_added += added;
            this.session.lines_deleted += deleted;
            // Heuristic for refactor: many lines deleted and added at once
            if (added > 20 && deleted > 20) {
                this.session.refactor_events += 1;
            }
        }
    }
    updateDuration() {
        const now = Date.now();
        const durationMinutes = Math.floor((now - this.sessionStartTime) / 60000);
        this.session.editing_duration_minutes = durationMinutes;
    }
    getSession() {
        this.updateDuration();
        return this.session;
    }
}
exports.SignalAggregator = SignalAggregator;
//# sourceMappingURL=signalAggregator.js.map