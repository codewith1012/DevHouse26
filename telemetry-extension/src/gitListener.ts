import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { SignalAggregator } from './signalAggregator';
import { ActivityMonitor } from './activityMonitor';
import { WebhookSender } from './webhookSender';
import { CameraMonitor } from './cameraMonitor';
import { JiraPicker } from './jiraPicker';
import { SupaBaseEvent, ExtensionConfig } from './types';
import { logger } from './extension';

export class GitListener {
    private aggregator: SignalAggregator;
    private activityMonitor: ActivityMonitor;
    private webhookSender: WebhookSender;
    private cameraMonitor: CameraMonitor;
    private jiraPicker: JiraPicker;
    private disposables: vscode.Disposable[] = [];
    private lastCommitIds: Map<string, string> = new Map();
    private config!: ExtensionConfig;

    constructor(
        aggregator: SignalAggregator, 
        activityMonitor: ActivityMonitor,
        webhookSender: WebhookSender,
        cameraMonitor: CameraMonitor,
        jiraPicker: JiraPicker
    ) {
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
        
        logger.appendLine("[INIT] GitListener created");
    }

    private updateConfig(): void {
        const config = vscode.workspace.getConfiguration('devintel');
        let developerId = config.get<string>('developerId', 'dev_22');
        
        // If it's the default placeholder, use the OS username instead
        if (developerId === 'dev_22') {
            developerId = os.userInfo().username || 'unknown_dev';
        }

        this.config = {
            supabaseUrl: config.get<string>('supabaseUrl', 'https://sgszqmuqwjghogtfuhbq.supabase.co'),
            supabaseKey: config.get<string>('supabaseKey', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnc3pxbXVxd2pnaG9ndGZ1aGJxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM5MjE3MDIsImV4cCI6MjA4OTQ5NzcwMn0.kZbXvIIRnMq6gdWrowF9MKOkEgFCHlkuNaf6kT-QaSM'),
            developerId: developerId,
            repositoryName: config.get<string>('repositoryName', 'payment-service'),
            telemetryEnabled: config.get<boolean>('telemetryEnabled', true)
        };
        this.webhookSender.updateConfig(this.config.supabaseUrl, this.config.supabaseKey);
    }

    public async initialize(): Promise<void> {
        const gitExtension = vscode.extensions.getExtension('vscode.git');
        if (!gitExtension) {
            logger.appendLine("[ERROR] VS Code Git extension not found.");
            return;
        }

        const gitAPI = gitExtension.isActive ? gitExtension.exports.getAPI(1) : await gitExtension.activate().then(() => gitExtension.exports.getAPI(1));

        if (!gitAPI) {
            logger.appendLine("[ERROR] Could not get Git API.");
            return;
        }

        const setupRepo = async (repo: any) => {
            const repoPath = repo.rootUri.fsPath;
            logger.appendLine(`[INIT] Monitoring repository: ${repoPath}`);
            
            if (repo?.state?.HEAD?.commit) {
                this.lastCommitIds.set(repo.rootUri.toString(), repo.state.HEAD.commit);
            }

            // Initial setup and backfill (Asynchronous)
            this.ensureDotDevPulseFolders(repoPath);
            this.backfillHistoricalCommits(repoPath, repo).catch(err => {
                logger.appendLine(`[BACKFILL] [ERROR] Backfill failed: ${err}`);
            });

            // 1. Listen to internal VS Code Git state changes
            this.disposables.push(
                repo.state.onDidChange(() => {
                    const repoName = path.basename(repo.rootUri.fsPath);
                    logger.appendLine(`[EVENT] Git state changed for ${repoName}`);
                    this.checkForNewCommit(repo);
                })
            );

            // 2. Add a FileSystemWatcher for external commits (e.g. Git Bash)
            const gitHeadPattern = new vscode.RelativePattern(repo.rootUri, '.git/HEAD');
            const watcher = vscode.workspace.createFileSystemWatcher(gitHeadPattern);
            
            watcher.onDidChange(() => {
                logger.appendLine(`[EVENT] External Git activity detected (HEAD changed)`);
                setTimeout(() => this.checkForNewCommit(repo), 1000);
            });
            
            this.disposables.push(watcher);
        };

        if (gitAPI.repositories.length > 0) {
            for (const repo of gitAPI.repositories) {
                await setupRepo(repo);
            }
        } else {
            this.disposables.push(
                gitAPI.onDidOpenRepository(async (repo: any) => {
                    await setupRepo(repo);
                })
            );
        }
    }

    private ensureDotDevPulseFolders(repoPath: string) {
        const { eventsDir, syncedDir } = this.getEventStoragePaths(repoPath);
        const devPulseDir = path.dirname(eventsDir);

        if (!fs.existsSync(devPulseDir)) {
            fs.mkdirSync(devPulseDir, { recursive: true });
        }
        if (!fs.existsSync(eventsDir)) {
            fs.mkdirSync(eventsDir, { recursive: true });
        }
        if (!fs.existsSync(syncedDir)) {
            fs.mkdirSync(syncedDir, { recursive: true });
        }

        // Create .devpulse/.gitignore if it doesn't exist
        const devpulseGitignore = path.join(devPulseDir, '.gitignore');
        if (!fs.existsSync(devpulseGitignore)) {
            fs.writeFileSync(devpulseGitignore, '*\n', 'utf8');
            logger.appendLine(`[INIT] Created ${devpulseGitignore} with '*'`);
        }

        // Add .devpulse/ to root .gitignore
        const rootGitignore = path.join(repoPath, '.gitignore');
        try {
            if (fs.existsSync(rootGitignore)) {
                const content = fs.readFileSync(rootGitignore, 'utf8');
                const lines = content.split(/\r?\n/);
                if (!lines.some(line => line.trim() === '.devpulse' || line.trim() === '.devpulse/')) {
                    fs.appendFileSync(rootGitignore, '\n.devpulse/\n');
                    logger.appendLine(`[INIT] Added .devpulse/ to root ${rootGitignore}`);
                }
            } else {
                fs.writeFileSync(rootGitignore, '.devpulse/\n', 'utf8');
                logger.appendLine(`[INIT] Created root ${rootGitignore} with .devpulse/`);
            }
        } catch (err) {
            logger.appendLine(`[ERROR] Failed to update root .gitignore: ${err}`);
        }
    }

    private async backfillHistoricalCommits(repoPath: string, repo: any) {
        logger.appendLine(`[BACKFILL] Starting scan for historical commits in ${repoPath}`);
        
        const { exec } = await import('child_process');
        const { promisify } = await import('util');
        const execAsync = promisify(exec);

        try {
            // Get last 50 commit hashes from HEAD
            const { stdout: logOut } = await execAsync(`git log -n 50 --format=%H`, { cwd: repoPath });
            const allHashes = logOut.trim().split('\n').filter(h => h.length > 0);
            
            const { syncedDir } = this.getEventStoragePaths(repoPath);
            const unsyncedHashes = allHashes.filter(h => !fs.existsSync(path.join(syncedDir, `${h}.json`)));

            if (unsyncedHashes.length === 0) {
                logger.appendLine(`[BACKFILL] All recent commits are already synced.`);
                return;
            }

            logger.appendLine(`[BACKFILL] Found ${unsyncedHashes.length} unsynced historical commits.`);

            let syncedCount = 0;
            // Process in reverse (oldest unsynced first)
            for (const hash of unsyncedHashes.reverse()) {
                try {
                    const stats = await this.getCommitStats(hash, repoPath);
                    if (stats.files.length === 0 && stats.additions === 0 && stats.deletions === 0) {
                        logger.appendLine(`[BACKFILL] [SKIP] Commit ${hash.substring(0, 7)} has no changes.`);
                        continue;
                    }

                    const event = this.buildSupaBaseEvent(stats, repo.state.HEAD?.name || 'main', repoPath);
                    const filePath = await this.saveEventLocally(event, repoPath);

                    if (filePath) {
                        const success = await this.webhookSender.sendToSupabase(event);
                        if (success) {
                            this.moveToSynced(filePath);
                            syncedCount++;
                            logger.appendLine(`[BACKFILL] Sent commit ${hash.substring(0, 7)}`);
                        }
                    }
                } catch (err) {
                    logger.appendLine(`[BACKFILL] [ERROR] Failed to process commit ${hash.substring(0, 7)}: ${err}`);
                }
            }

            logger.appendLine(`[BACKFILL] Complete. ${syncedCount}/${unsyncedHashes.length} commits synced.`);
            
            // Finally, sync any events that might still be in eventsDir but weren't part of the log scan
            await this.syncExistingEvents(repoPath);
            
        } catch (err) {
            logger.appendLine(`[BACKFILL] [ERROR] Historical scan failed: ${err}`);
        }
    }

    private async syncExistingEvents(repoPath: string) {
        const { eventsDir, syncedDir } = this.getEventStoragePaths(repoPath);
        
        if (!fs.existsSync(eventsDir)) return;
        if (!fs.existsSync(syncedDir)) {
            fs.mkdirSync(syncedDir, { recursive: true });
        }

        try {
            const files = fs.readdirSync(eventsDir);
            const pendingFiles = files.filter(f => f.endsWith('.json'));

            if (pendingFiles.length === 0) return;

            logger.appendLine(`[SYNC] Found ${pendingFiles.length} pending events. Attempting sync...`);

            for (const file of pendingFiles) {
                const filePath = path.join(eventsDir, file);
                try {
                    const content = fs.readFileSync(filePath, 'utf8');
                    const event = JSON.parse(content) as SupaBaseEvent;
                    
                    // Attempt to send to Supabase
                    const success = await this.webhookSender.sendToSupabase(event);
                    
                    if (success) {
                        const moved = this.moveToSynced(filePath);
                        if (moved) {
                            logger.appendLine(`[SYNC] Successfully synced and moved ${file}`);
                        }
                    }
                } catch (err) {
                    logger.appendLine(`[SYNC] Failed to sync ${file}: ${err}`);
                }
            }

            await this.reconcileSupabaseWithLocalMirror(repoPath);
        } catch (err) {
            logger.appendLine(`[ERROR] Failed to scan events directory: ${err}`);
        }
    }

    private async checkForNewCommit(repo: any): Promise<void> {
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
            logger.appendLine(`[DETECTED] New commit! ${previousCommitId?.substring(0,7)} -> ${currentCommitId.substring(0,7)}`);
            this.lastCommitIds.set(repoUri, currentCommitId);

            try {
                const repoPath = repo.rootUri.fsPath;
                logger.appendLine(`[PROCESS] Extracting detailed metrics for commit ${currentCommitId.substring(0,7)}...`);
                
                const stats = await this.getCommitStats(currentCommitId, repoPath);
                
                // FILTER: Only send if there are actual changes
                if (stats.files.length === 0 && stats.additions === 0 && stats.deletions === 0) {
                    logger.appendLine(`[SKIP] Commit ${currentCommitId.substring(0,7)} has no changes. Skipping sync.`);
                    return;
                }

                const supabaseEvent = this.buildSupaBaseEvent(stats, head.name || 'main', repoPath);
                
                // Process locally: Save to JSON file
                const filePath = await this.saveEventLocally(supabaseEvent, repoPath);

                logger.appendLine(`[DEBUG] Final Payload Object to WebhookSender: ${JSON.stringify(supabaseEvent)}`);

                // Send to Supabase
                const success = await this.webhookSender.sendToSupabase(supabaseEvent);
                
                if (success && filePath) {
                    this.moveToSynced(filePath);
                    await this.reconcileSupabaseWithLocalMirror(repoPath);
                }
                
                // Reset for the next session
                this.aggregator.resetSession();
                this.activityMonitor.resetTracker();
                this.cameraMonitor.resetSession();

            } catch (error) {
                logger.appendLine(`[ERROR] Failed to process new commit: ${error}`);
            }
        }
    }

    private async getCommitStats(commitId: string, repoPath: string) {
        const { exec } = await import('child_process');
        const { promisify } = await import('util');
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
            let repositoryOwner: string | null = null;
            try {
                const { stdout: remoteUrl } = await execAsync(`git remote get-url origin`, { cwd: repoPath });
                const gitMatch = remoteUrl.match(/github\.com[:/]([^/]+)/);
                if (gitMatch) repositoryOwner = gitMatch[1];
            } catch (e) { /* ignore */ }

            // 4. File-level details
            const { stdout: fileStatusOut } = await execAsync(`git diff-tree --no-commit-id --name-status -r ${commitId}`, { cwd: repoPath });
            const files: any[] = [];
            
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
        } catch (err) {
            logger.appendLine(`[ERROR] Git CLI failed: ${err}`);
            throw err;
        }
    }

    private mapGitStatus(status: string): string {
        const map: Record<string, string> = { 'A': 'added', 'M': 'modified', 'D': 'deleted', 'R': 'renamed', 'C': 'copied' };
        return map[status[0]] || 'modified';
    }

    private detectLanguage(ext: string): string {
        const map: Record<string, string> = { 'ts': 'typescript', 'js': 'javascript', 'py': 'python', 'go': 'go', 'rs': 'rust', 'c': 'c', 'cpp': 'cpp', 'java': 'java' };
        return map[ext.toLowerCase()] || 'text';
    }

    private buildSupaBaseEvent(stats: any, branchName: string, repoPath: string): SupaBaseEvent {
        const session = this.aggregator.getSession();
        
        const issueMatch = stats.message.match(/#(\d+)/) || stats.message.match(/([A-Z]{2,}-\d+)/);
        const linkedIssue = issueMatch ? issueMatch[0] : null;

        const presence = this.cameraMonitor.getPresenceData();
        
        const filteredFiles = stats.files.filter((f: any) => !f.file_path.startsWith('.devpulse/'));
        const diff_patch = filteredFiles.map((f: any) => f.patch).join('\n\n');
        const modules_touched = Array.from(new Set(filteredFiles.map((f: any) => f.module || f.directory).filter(Boolean))) as string[];
        
        const calcAdditions = filteredFiles.reduce((acc: number, f: any) => acc + (f.additions || 0), 0);
        const calcDeletions = filteredFiles.reduce((acc: number, f: any) => acc + (f.deletions || 0), 0);

        const repositoryName = path.basename(repoPath) || this.config.repositoryName;

        return {
            event_type: "commit_event",
            schema_version: "1.1", // Bumped version
            developer_id: this.config.developerId,
            commit_id: stats.commitId,
            author: stats.author,
            author_email: stats.authorEmail,
            message: stats.message,
            repository_owner: stats.repositoryOwner,
            repository_name: repositoryName,
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

    private async saveEventLocally(event: SupaBaseEvent, repoPath: string): Promise<string | undefined> {
        try {
            const devPulseDir = path.join(repoPath, '.devpulse', 'events');
            if (!fs.existsSync(devPulseDir)) {
                fs.mkdirSync(devPulseDir, { recursive: true });
            }
            
            const fileName = `${event.commit_id}.json`;
            const filePath = path.join(devPulseDir, fileName);
            fs.writeFileSync(filePath, JSON.stringify(event, null, 2));

            // Ensure directory exists for synced as well
            const syncedDir = path.join(repoPath, '.devpulse', 'synced');
            if (!fs.existsSync(syncedDir)) {
                fs.mkdirSync(syncedDir, { recursive: true });
            }
            
            logger.appendLine(`[LOCAL] Saved commit data to: ${filePath}`);
            return filePath;
        } catch (err) {
            logger.appendLine(`[ERROR] Failed to save local JSON: ${err}`);
            return undefined;
        }
    }

    private moveToSynced(filePath: string): boolean {
        try {
            const fileName = path.basename(filePath);
            const repoPath = path.dirname(path.dirname(path.dirname(filePath))); // .devpulse/events/file -> repoPath
            const { syncedDir } = this.getEventStoragePaths(repoPath);
            
            if (!fs.existsSync(syncedDir)) {
                fs.mkdirSync(syncedDir, { recursive: true });
            }
            
            const destPath = path.join(syncedDir, fileName);
            if (fs.existsSync(destPath)) {
                fs.unlinkSync(destPath);
            }

            fs.copyFileSync(filePath, destPath);
            fs.unlinkSync(filePath);
            // logger.appendLine(`[SYNC] Moved to synced folder: ${fileName}`);
            return true;
        } catch (err) {
            logger.appendLine(`[ERROR] Failed to move file to synced: ${err}`);
            return false;
        }
    }

    private getEventStoragePaths(repoPath: string): { eventsDir: string; syncedDir: string } {
        const eventsDir = path.join(repoPath, '.devpulse', 'events');
        const syncedDir = path.join(repoPath, '.devpulse', 'synced');
        return { eventsDir, syncedDir };
    }

    private loadEventFileMap(directory: string): Map<string, SupaBaseEvent> {
        const events = new Map<string, SupaBaseEvent>();
        if (!fs.existsSync(directory)) {
            return events;
        }

        for (const file of fs.readdirSync(directory)) {
            const filePath = path.join(directory, file);
            if (!file.endsWith('.json')) {
                continue;
            }
            if (!fs.statSync(filePath).isFile()) {
                continue;
            }

            try {
                const event = JSON.parse(fs.readFileSync(filePath, 'utf8')) as SupaBaseEvent;
                if (event.commit_id) {
                    events.set(event.commit_id, event);
                }
            } catch (error) {
                logger.appendLine(`[SYNC] Failed to read local event ${filePath}: ${error}`);
            }
        }

        return events;
    }

    private collectLocalEventMirror(repoPath: string): Map<string, SupaBaseEvent> {
        const { eventsDir, syncedDir } = this.getEventStoragePaths(repoPath);
        const pendingEvents = this.loadEventFileMap(eventsDir);
        const syncedEvents = this.loadEventFileMap(syncedDir);

        for (const [commitId, event] of syncedEvents.entries()) {
            if (!pendingEvents.has(commitId)) {
                pendingEvents.set(commitId, event);
            }
        }

        return pendingEvents;
    }

    private async reconcileSupabaseWithLocalMirror(repoPath: string): Promise<void> {
        const localEvents = this.collectLocalEventMirror(repoPath);
        const expectedCommitIds = new Set(localEvents.keys());

        logger.appendLine(`[SYNC] Reconciling Supabase with local mirror. Local events: ${expectedCommitIds.size}`);

        for (const event of localEvents.values()) {
            const success = await this.webhookSender.sendToSupabase(event);
            if (!success) {
                logger.appendLine(`[SYNC] Failed to mirror local event ${event.commit_id} to Supabase.`);
            }
        }

        const repositoryName = path.basename(repoPath) || this.config.repositoryName;
        const remoteCommitIds = await this.webhookSender.fetchRemoteCommitIds(this.config.developerId, repositoryName);
        for (const commitId of remoteCommitIds) {
            if (!expectedCommitIds.has(commitId)) {
                const deleted = await this.webhookSender.deleteEventByIdentity(commitId, this.config.developerId, this.config.repositoryName);
                if (deleted) {
                    logger.appendLine(`[SYNC] Removed remote event with no local JSON mirror: ${commitId}`);
                }
            }
        }
    }

    public dispose(): void {
        this.disposables.forEach(d => d.dispose());
    }
}
