export interface SignalSession {
    session_id: string;
    files_opened: number;
    files_modified: number;
    lines_added: number;
    lines_deleted: number;
    editing_duration_minutes: number;
    refactor_events: number;
}

export interface CommitFile {
    file_path: string;
    file_extension: string;
    change_type: string;
    additions: number;
    deletions: number;
    language: string;
    patch: string;
    module: string;
    directory: string;
    commit_id: string;
}

export interface PresenceData {
    attendance_pct: number;
    total_checks: number;
    present_checks: number;
    session_duration_seconds: number;
    session_start: string;
}

// Supabase schema-aligned event
export interface SupaBaseEvent {
    id?: string;
    event_type: string;
    schema_version: string;
    developer_id: string;
    commit_id: string;
    author: string;
    author_email: string;
    message: string;
    repository_owner: string | null;
    repository_name: string;
    timestamp: string; // ISO format
    branch: string;
    additions: number;
    deletions: number;
    commit_type: string;
    parent_commit_id: string | null;
    commit_category: string;
    commit_message_length: number;
    total_changes: number;
    commit_size: number;
    is_merge_commit: boolean;
    linked_issue: string | null;
    issue_id?: string | null;
    pull_request_number: number | null;
    pr_title: string | null;
    pr_labels: string[];
    files: CommitFile[];
    files_changed_count?: number;
    net_loc?: number;
    diff_patch?: string;
    files_json?: any;
    modules_touched?: string[];
    attendance_pct?: number;
    presence_total_checks?: number;
    presence_present_count?: number;
    session_duration_secs?: number;
    session_start?: string;
    // Legacy/Signal fields preserved for local logic
    active_minutes: number;
    idle_minutes: number;
    focus_ratio: number;
    debug_session_count: number;
}

export interface ExtensionConfig {
    supabaseUrl: string;
    supabaseKey: string;
    developerId: string;
    repositoryName: string;
    telemetryEnabled: boolean;
    aiBackendUrl?: string;
    aiModel?: string;
}

export interface AIQueryRequest {
    prompt: string;
    mode: 'ask' | 'generate' | 'refactor';
    developer_id: string;
    repository_name: string;
    issue_id?: string | null;
    model?: string;
    file_path?: string | null;
    language?: string | null;
    selected_text?: string;
    surrounding_code?: string;
    selection?: {
        start_line: number;
        start_character: number;
        end_line: number;
        end_character: number;
    } | null;
}

export interface AIEditInstruction {
    kind?: 'replace_selection' | 'insert_at_cursor' | 'replace_full_document' | 'create_file';
    file_path?: string;
    content?: string;
}

export interface AIQueryResponse {
    id?: string;
    response?: string;
    answer?: string;
    output?: string;
    message?: string;
    model?: string;
    input_tokens?: number;
    output_tokens?: number;
    usage?: {
        input_tokens?: number;
        output_tokens?: number;
        total_tokens?: number;
    };
    edit?: AIEditInstruction | null;
    edits?: AIEditInstruction[];
}
