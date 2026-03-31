"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.JiraPicker = void 0;
const vscode = require("vscode");
const extension_1 = require("./extension");
class JiraPicker {
    activeIssueId = null;
    statusBarItem;
    issues = [];
    context;
    constructor(context) {
        this.context = context;
        this.statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
        this.statusBarItem.command = 'devhouse.selectJiraIssue';
        // Restore from persistence
        this.activeIssueId = this.context.globalState.get('devintel.activeIssueId', null);
        this.updateStatusBar();
    }
    async fetchAndPrompt() {
        await this.fetchIssues();
        // Only prompt if nothing is selected or if we want to refresh
        if (!this.activeIssueId) {
            await this.showPicker();
        }
    }
    async fetchIssues() {
        const config = vscode.workspace.getConfiguration('devintel');
        const supabaseUrl = config.get('supabaseUrl', '');
        const supabaseKey = config.get('supabaseKey', '');
        if (!supabaseUrl || !supabaseKey)
            return;
        const url = `${supabaseUrl.replace(/\/$/, '')}/rest/v1/req_code_mapping?select=issue_id,title,description,status`;
        try {
            const response = await fetch(url, {
                headers: {
                    'apikey': supabaseKey,
                    'Authorization': `Bearer ${supabaseKey}`
                }
            });
            if (response.ok) {
                this.issues = (await response.json());
            }
            else {
                extension_1.logger.appendLine(`[JIRA] Failed to fetch issues: ${response.statusText}`);
            }
        }
        catch (err) {
            extension_1.logger.appendLine(`[JIRA] Error fetching issues: ${err}`);
        }
    }
    async showPicker() {
        if (this.issues.length === 0) {
            await this.fetchIssues();
        }
        const items = [
            {
                label: '$(close) Skip for now',
                description: 'Do not link commits to an issue'
            }
        ];
        for (const issue of this.issues) {
            items.push({
                label: `$(issue-opened) ${issue.issue_id} — ${issue.title}`,
                description: issue.status,
                detail: issue.description,
                issue_id: issue.issue_id
            });
        }
        const selected = await vscode.window.showQuickPick(items, {
            placeHolder: 'Select an active Jira Issue for telemetry',
            matchOnDescription: true,
            matchOnDetail: true
        });
        if (selected) {
            if (selected.label.includes('Skip for now')) {
                this.activeIssueId = null;
            }
            else {
                this.activeIssueId = selected.issue_id;
            }
            this.updateStatusBar();
            this.context.globalState.update('devintel.activeIssueId', this.activeIssueId);
            extension_1.logger.appendLine(`[JIRA] Selected issue: ${this.activeIssueId || 'None'}`);
        }
    }
    updateStatusBar() {
        if (this.activeIssueId) {
            this.statusBarItem.text = `$(issue-opened) ${this.activeIssueId}`;
            this.statusBarItem.show();
        }
        else {
            this.statusBarItem.text = `$(issues) No Issue Selected`;
            this.statusBarItem.show();
        }
    }
    getActiveIssueId() {
        return this.activeIssueId;
    }
    dispose() {
        this.statusBarItem.dispose();
    }
}
exports.JiraPicker = JiraPicker;
//# sourceMappingURL=jiraPicker.js.map