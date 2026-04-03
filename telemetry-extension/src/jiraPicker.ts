import * as vscode from 'vscode';
import { logger } from './extension';

export interface JiraIssue {
    issue_id: string;
    title: string;
    description: string;
    status: string;
}

export class JiraPicker {
    private activeIssueId: string | null = null;
    private statusBarItem: vscode.StatusBarItem;
    private issues: JiraIssue[] = [];
    private context: vscode.ExtensionContext;

    constructor(context: vscode.ExtensionContext) {
        this.context = context;
        this.statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
        this.statusBarItem.command = 'devhouse.selectJiraIssue';
        
        // Restore from persistence
        this.activeIssueId = this.context.globalState.get<string | null>('devintel.activeIssueId', null);
        
        this.updateStatusBar();
    }

    public async fetchAndPrompt() {
        await this.fetchIssues();
        
        // Only prompt if nothing is selected or if we want to refresh
        if (!this.activeIssueId) {
            await this.showPicker();
        }
    }

    private async fetchIssues() {
        const config = vscode.workspace.getConfiguration('devintel');
        const supabaseUrl = config.get<string>('supabaseUrl', '');
        const supabaseKey = config.get<string>('supabaseKey', '');
        
        if (!supabaseUrl || !supabaseKey) return;
        
        const url = `${supabaseUrl.replace(/\/$/, '')}/rest/v1/req_code_mapping?select=issue_id,title,description,status`;
        try {
            const response = await fetch(url, {
                headers: {
                    'apikey': supabaseKey,
                    'Authorization': `Bearer ${supabaseKey}`
                }
            });
            if (response.ok) {
                this.issues = (await response.json()) as JiraIssue[];
            } else {
                logger.appendLine(`[JIRA] Failed to fetch issues: ${response.statusText}`);
            }
        } catch (err) {
            logger.appendLine(`[JIRA] Error fetching issues: ${err}`);
        }
    }

    public async showPicker() {
        if (this.issues.length === 0) {
            await this.fetchIssues();
        }

        const items: vscode.QuickPickItem[] = [
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
            } as any);
        }

        const selected = await vscode.window.showQuickPick(items, {
            placeHolder: 'Select an active Jira Issue for telemetry',
            matchOnDescription: true,
            matchOnDetail: true
        });

        if (selected) {
            if (selected.label.includes('Skip for now')) {
                this.activeIssueId = null;
            } else {
                this.activeIssueId = (selected as any).issue_id;
            }
            this.updateStatusBar();
            this.context.globalState.update('devintel.activeIssueId', this.activeIssueId);
            logger.appendLine(`[JIRA] Selected issue: ${this.activeIssueId || 'None'}`);
        }
    }

    private updateStatusBar() {
        if (this.activeIssueId) {
            this.statusBarItem.text = `$(issue-opened) ${this.activeIssueId}`;
            this.statusBarItem.show();
        } else {
            this.statusBarItem.text = `$(issues) No Issue Selected`;
            this.statusBarItem.show();
        }
    }

    public getActiveIssueId(): string | null {
        return this.activeIssueId;
    }

    public dispose() {
        this.statusBarItem.dispose();
    }
}
