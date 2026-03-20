"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.GitListener = void 0;
const vscode = require("vscode");
const path = require("path");
const fs = require("fs");
const os = require("os");
const extension_1 = require("./extension");
class GitListener {
    aggregator;
    activityMonitor;
    webhookSender;
    cameraMonitor;
    jiraPicker;
    disposables = [];
    lastCommitIds = new Map();
    config;
    constructor(aggregator, activityMonitor, webhookSender, cameraMonitor, jiraPicker) {
        this.aggregator = aggregator;
        this.activityMonitor = activityMonitor;
        this.webhookSender = webhookSender;
        this.cameraMonitor = cameraMonitor;
        this.jiraPicker = jiraPicker;
        this.updateConfig();
        vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration('devintel')) {
                this.updateConfig();
            }
        });
        extension_1.logger.appendLine("[INIT] GitListener created");
    }
    updateConfig() {
        const config = vscode.workspace.getConfiguration('devintel');
        let developerId = config.get('developerId', 'dev_22');
        // If it's the default placeholder, use the OS username instead
        if (developerId === 'dev_22') {
            developerId = os.userInfo().username || 'unknown_dev';
        }
        this.config = {
            supabaseUrl: config.get('supabaseUrl', 'https://sgszqmuqwjghogtfuhbq.supabase.co'),
            supabaseKey: config.get('supabaseKey', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnc3pxbXVxd2pnaG9ndGZ1aGJxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM5MjE3MDIsImV4cCI6MjA4OTQ5NzcwMn0.kZbXvIIRnMq6gdWrowF9MKOkEgFCHlkuNaf6kT-QaSM'),
            developerId: developerId,
            repositoryName: config.get('repositoryName', 'payment-service'),
            telemetryEnabled: config.get('telemetryEnabled', true)
        };
        this.webhookSender.updateConfig(this.config.supabaseUrl, this.config.supabaseKey);
    }
    async initialize() {
        const gitExtension = vscode.extensions.getExtension('vscode.git');
        if (!gitExtension) {
            extension_1.logger.appendLine("[ERROR] VS Code Git extension not found.");
            return;
        }
        const gitAPI = gitExtension.isActive ? gitExtension.exports.getAPI(1) : await gitExtension.activate().then(() => gitExtension.exports.getAPI(1));
        if (!gitAPI) {
            extension_1.logger.appendLine("[ERROR] Could not get Git API.");
            return;
        }
        const setupRepo = async (repo) => {
            const repoPath = repo.rootUri.fsPath;
            extension_1.logger.appendLine(`[INIT] Monitoring repository: ${repoPath}`);
            if (repo?.state?.HEAD?.commit) {
                this.lastCommitIds.set(repo.rootUri.toString(), repo.state.HEAD.commit);
            }
            // Sync any existing events that haven't been sent yet
            await this.syncExistingEvents(repoPath);
            // 1. Listen to internal VS Code Git state changes
            this.disposables.push(repo.state.onDidChange(() => {
                const repoName = path.basename(repo.rootUri.fsPath);
                extension_1.logger.appendLine(`[EVENT] Git state changed for ${repoName}`);
                this.checkForNewCommit(repo);
            }));
            // 2. Add a FileSystemWatcher for external commits (e.g. Git Bash)
            const gitHeadPattern = new vscode.RelativePattern(repo.rootUri, '.git/HEAD');
            const watcher = vscode.workspace.createFileSystemWatcher(gitHeadPattern);
            watcher.onDidChange(() => {
                extension_1.logger.appendLine(`[EVENT] External Git activity detected (HEAD changed)`);
                setTimeout(() => this.checkForNewCommit(repo), 1000);
            });
            this.disposables.push(watcher);
        };
        if (gitAPI.repositories.length > 0) {
            for (const repo of gitAPI.repositories) {
                await setupRepo(repo);
            }
        }
        else {
            this.disposables.push(gitAPI.onDidOpenRepository(async (repo) => {
                await setupRepo(repo);
            }));
        }
    }
    async syncExistingEvents(repoPath) {
        const eventsDir = path.join(repoPath, '.devpulse', 'events');
        const syncedDir = path.join(eventsDir, 'synced');
        if (!fs.existsSync(eventsDir))
            return;
        if (!fs.existsSync(syncedDir)) {
            fs.mkdirSync(syncedDir, { recursive: true });
        }
        try {
            const files = fs.readdirSync(eventsDir);
            const pendingFiles = files.filter(f => f.endsWith('.json'));
            if (pendingFiles.length === 0)
                return;
            extension_1.logger.appendLine(`[SYNC] Found ${pendingFiles.length} pending events. Attempting sync...`);
            for (const file of pendingFiles) {
                const filePath = path.join(eventsDir, file);
                try {
                    const content = fs.readFileSync(filePath, 'utf8');
                    const event = JSON.parse(content);
                    // Attempt to send to Supabase
                    const success = await this.webhookSender.sendToSupabase(event);
                    if (success) {
                        // Move to synced folder
                        const destPath = path.join(syncedDir, file);
                        fs.renameSync(filePath, destPath);
                        extension_1.logger.appendLine(`[SYNC] Successfully synced and moved ${file}`);
                    }
                }
                catch (err) {
                    extension_1.logger.appendLine(`[SYNC] Failed to sync ${file}: ${err}`);
                }
            }
        }
        catch (err) {
            extension_1.logger.appendLine(`[ERROR] Failed to scan events directory: ${err}`);
        }
    }
    async checkForNewCommit(repo) {
        if (!this.config.telemetryEnabled) {
            return;
        }
        const head = repo.state.HEAD;
        if (!head || !head.commit) {
            return;
        }
        const currentCommitId = head.commit;
        const repoUri = repo.rootUri.toString();
        const previousCommitId = this.lastCommitIds.get(repoUri);
        if (previousCommitId !== currentCommitId) {
            extension_1.logger.appendLine(`[DETECTED] New commit! ${previousCommitId?.substring(0, 7)} -> ${currentCommitId.substring(0, 7)}`);
            this.lastCommitIds.set(repoUri, currentCommitId);
            try {
                const repoPath = repo.rootUri.fsPath;
                extension_1.logger.appendLine(`[PROCESS] Extracting detailed metrics for commit ${currentCommitId.substring(0, 7)}...`);
                const stats = await this.getCommitStats(currentCommitId, repoPath);
                // FILTER: Only send if there are actual changes
                if (stats.files.length === 0 && stats.additions === 0 && stats.deletions === 0) {
                    extension_1.logger.appendLine(`[SKIP] Commit ${currentCommitId.substring(0, 7)} has no changes. Skipping sync.`);
                    return;
                }
                const supabaseEvent = this.buildSupaBaseEvent(stats, head.name || 'main');
                // Process locally: Save to JSON file
                const filePath = await this.saveEventLocally(supabaseEvent, repoPath);
                extension_1.logger.appendLine(`[DEBUG] Final Payload Object to WebhookSender: ${JSON.stringify(supabaseEvent)}`);
                // Send to Supabase
                const success = await this.webhookSender.sendToSupabase(supabaseEvent);
                if (success && filePath) {
                    this.moveToSynced(filePath);
                }
                // Reset for the next session
                this.aggregator.resetSession();
                this.activityMonitor.resetTracker();
                this.cameraMonitor.resetSession();
            }
            catch (error) {
                extension_1.logger.appendLine(`[ERROR] Failed to process new commit: ${error}`);
            }
        }
    }
    async getCommitStats(commitId, repoPath) {
        const { exec } = await Promise.resolve().then(() => require('child_process'));
        const { promisify } = await Promise.resolve().then(() => require('util'));
        const execAsync = promisify(exec);
        try {
            // 1. Basic commit info
            const { stdout: commitInfo } = await execAsync(`git show -s --format="%an|%ae|%aI|%P|%s|%B" ${commitId}`, { cwd: repoPath });
            const [author, authorEmail, timestamp, parents, subject, body] = commitInfo.trim().split('|');
            const parent_commit_id = parents.trim().split(' ')[0] || null;
            const fullMessage = body || subject;
            // 2. Additions/Deletions
            const { stdout: statOut } = await execAsync(`git show --shortstat --format="" ${commitId}`, { cwd: repoPath });
            let additions = 0, deletions = 0;
            const match = statOut.match(/(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?/);
            if (match) {
                additions = parseInt(match[2] || '0');
                deletions = parseInt(match[3] || '0');
            }
            // 3. Repository owner (try from remote)
            let repositoryOwner = null;
            try {
                const { stdout: remoteUrl } = await execAsync(`git remote get-url origin`, { cwd: repoPath });
                const gitMatch = remoteUrl.match(/github\.com[:/]([^/]+)/);
                if (gitMatch)
                    repositoryOwner = gitMatch[1];
            }
            catch (e) { /* ignore */ }
            // 4. File-level details
            const { stdout: fileStatusOut } = await execAsync(`git diff-tree --no-commit-id --name-status -r ${commitId}`, { cwd: repoPath });
            const files = [];
            const fileLines = fileStatusOut.trim().split('\n').filter(l => l.length > 0);
            for (const line of fileLines) {
                const [status, filePath] = line.split(/\s+/);
                const ext = path.extname(filePath).replace('.', '') || '';
                // Get patch for this specific file
                const { stdout: patch } = await execAsync(`git show --format="" ${commitId} -- "${filePath}"`, { cwd: repoPath });
                // Get additions/deletions for this file
                const { stdout: fileStats } = await execAsync(`git diff ${parent_commit_id || '4b825dc642cb6eb9a060e54bf8d69288fbee4904'} ${commitId} --numstat -- "${filePath}"`, { cwd: repoPath });
                const [fileAdd = '0', fileDel = '0'] = fileStats.trim().split(/\s+/);
                files.push({
                    file_path: filePath,
                    file_extension: ext,
                    change_type: this.mapGitStatus(status),
                    additions: parseInt(fileAdd),
                    deletions: parseInt(fileDel),
                    language: this.detectLanguage(ext),
                    patch: patch.substring(0, 5000), // Cap per-file patch
                    module: filePath.split('/')[0] || '',
                    directory: path.dirname(filePath),
                    commit_id: commitId
                });
            }
            return {
                commitId, author, authorEmail, timestamp, parent_commit_id,
                message: fullMessage, additions, deletions, repositoryOwner,
                files, isMergeCommit: parents.trim().split(' ').length > 1
            };
        }
        catch (err) {
            extension_1.logger.appendLine(`[ERROR] Git CLI failed: ${err}`);
            throw err;
        }
    }
    mapGitStatus(status) {
        const map = { 'A': 'added', 'M': 'modified', 'D': 'deleted', 'R': 'renamed', 'C': 'copied' };
        return map[status[0]] || 'modified';
    }
    detectLanguage(ext) {
        const map = { 'ts': 'typescript', 'js': 'javascript', 'py': 'python', 'go': 'go', 'rs': 'rust', 'c': 'c', 'cpp': 'cpp', 'java': 'java' };
        return map[ext.toLowerCase()] || 'text';
    }
    buildSupaBaseEvent(stats, branchName) {
        const session = this.aggregator.getSession();
        const issueMatch = stats.message.match(/#(\d+)/) || stats.message.match(/([A-Z]{2,}-\d+)/);
        const linkedIssue = issueMatch ? issueMatch[0] : null;
        const presence = this.cameraMonitor.getPresenceData();
        const filteredFiles = stats.files.filter((f) => !f.file_path.startsWith('.devpulse/'));
        const diff_patch = filteredFiles.map((f) => f.patch).join('\n\n');
        const modules_touched = Array.from(new Set(filteredFiles.map((f) => f.module || f.directory).filter(Boolean)));
        const calcAdditions = filteredFiles.reduce((acc, f) => acc + (f.additions || 0), 0);
        const calcDeletions = filteredFiles.reduce((acc, f) => acc + (f.deletions || 0), 0);
        return {
            event_type: "commit_event",
            schema_version: "1.1", // Bumped version
            developer_id: this.config.developerId,
            commit_id: stats.commitId,
            author: stats.author,
            author_email: stats.authorEmail,
            message: stats.message,
            repository_owner: stats.repositoryOwner,
            repository_name: this.config.repositoryName,
            timestamp: stats.timestamp,
            branch: branchName,
            additions: calcAdditions,
            deletions: calcDeletions,
            commit_type: "general",
            parent_commit_id: stats.parent_commit_id,
            commit_category: "general",
            commit_message_length: stats.message.length,
            total_changes: calcAdditions + calcDeletions,
            commit_size: calcAdditions + calcDeletions,
            is_merge_commit: stats.isMergeCommit,
            linked_issue: linkedIssue,
            issue_id: this.jiraPicker.getActiveIssueId(),
            pull_request_number: null, // Hard to detect locally
            pr_title: null,
            pr_labels: [],
            files: stats.files, // Raw unfiltered for audit column
            files_changed_count: filteredFiles.length,
            net_loc: calcAdditions - calcDeletions,
            diff_patch: diff_patch,
            files_json: { files: filteredFiles },
            modules_touched: modules_touched,
            attendance_pct: presence.attendance_pct,
            presence_total_checks: presence.total_checks,
            presence_present_count: presence.present_checks,
            session_duration_secs: presence.session_duration_seconds,
            session_start: presence.session_start,
            // Legacy/Signal fields
            active_minutes: session.editing_duration_minutes,
            idle_minutes: 0,
            focus_ratio: 1.0,
            debug_session_count: 0
        };
    }
    async saveEventLocally(event, repoPath) {
        try {
            const devPulseDir = path.join(repoPath, '.devpulse', 'events');
            if (!fs.existsSync(devPulseDir)) {
                fs.mkdirSync(devPulseDir, { recursive: true });
            }
            const fileName = `${event.commit_id}.json`;
            const filePath = path.join(devPulseDir, fileName);
            fs.writeFileSync(filePath, JSON.stringify(event, null, 2));
            extension_1.logger.appendLine(`[LOCAL] Saved commit data to: ${filePath}`);
            return filePath;
        }
        catch (err) {
            extension_1.logger.appendLine(`[ERROR] Failed to save local JSON: ${err}`);
            return undefined;
        }
    }
    moveToSynced(filePath) {
        try {
            const dir = path.dirname(filePath);
            const fileName = path.basename(filePath);
            const syncedDir = path.join(dir, 'synced');
            if (!fs.existsSync(syncedDir)) {
                fs.mkdirSync(syncedDir, { recursive: true });
            }
            const destPath = path.join(syncedDir, fileName);
            fs.renameSync(filePath, destPath);
            extension_1.logger.appendLine(`[SYNC] Moved to synced folder: ${fileName}`);
        }
        catch (err) {
            extension_1.logger.appendLine(`[ERROR] Failed to move file to synced: ${err}`);
        }
    }
    dispose() {
        this.disposables.forEach(d => d.dispose());
    }
}
exports.GitListener = GitListener;
//# sourceMappingURL=gitListener.js.map