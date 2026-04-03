import { SignalSession } from './types';

export class SignalAggregator {
    private session!: SignalSession;
    private sessionStartTime!: number;

    constructor() {
        this.resetSession();
    }

    public resetSession(): void {
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

    public addFilesOpened(count: number = 1): void {
        this.session.files_opened += count;
    }

    public addFileModified(): void {
        this.session.files_modified += 1;
    }

    public addLinesChanged(added: number, deleted: number): void {
        if (added > 0 || deleted > 0) {
            this.session.lines_added += added;
            this.session.lines_deleted += deleted;
            
            // Heuristic for refactor: many lines deleted and added at once
            if (added > 20 && deleted > 20) {
                this.session.refactor_events += 1;
            }
        }
    }
    
    public updateDuration(): void {
        const now = Date.now();
        const durationMinutes = Math.floor((now - this.sessionStartTime) / 60000);
        this.session.editing_duration_minutes = durationMinutes;
    }

    public getSession(): SignalSession {
        this.updateDuration();
        return this.session;
    }
}
