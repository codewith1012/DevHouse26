import * as vscode from 'vscode';
import { SignalAggregator } from './signalAggregator';
import { ActivityMonitor } from './activityMonitor';
import { WebhookSender } from './webhookSender';
import { GitListener } from './gitListener';
import { CameraMonitor } from './cameraMonitor';
import { JiraPicker } from './jiraPicker';
import { AIEditInstruction, AIQueryRequest, AIQueryResponse } from './types';

export const logger = vscode.window.createOutputChannel("Developer Intelligence");

export async function activate(context: vscode.ExtensionContext) {
    logger.show(true);
    logger.appendLine('Developer Intelligence Telemetry extension is now active');

    // Initialize core modules
    const aggregator = new SignalAggregator();
    
    const config = vscode.workspace.getConfiguration('devintel');
    const supabaseUrl = config.get<string>('supabaseUrl', 'https://sgszqmuqwjghogtfuhbq.supabase.co');
    const supabaseKey = config.get<string>('supabaseKey', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnc3pxbXVxd2pnaG9ndGZ1aGJxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM5MjE3MDIsImV4cCI6MjA4OTQ5NzcwMn0.kZbXvIIRnMq6gdWrowF9MKOkEgFCHlkuNaf6kT-QaSM');
    
    const webhookSender = new WebhookSender(supabaseUrl, supabaseKey);
    
    const activityMonitor = new ActivityMonitor(aggregator);
    activityMonitor.start();

    const cameraMonitor = new CameraMonitor(context.globalState);

    const jiraPicker = new JiraPicker(context);
    setTimeout(() => {
        jiraPicker.fetchAndPrompt();
    }, 1000); // Small delay to let git warm up

    const selectJiraCommand = vscode.commands.registerCommand('devhouse.selectJiraIssue', () => {
        jiraPicker.showPicker();
    });

    const askAICommand = vscode.commands.registerCommand('devhouse.askAI', async () => {
        await runAIWorkflow('ask', jiraPicker);
    });

    const generateAtCursorCommand = vscode.commands.registerCommand('devhouse.generateAtCursor', async () => {
        await runAIWorkflow('generate', jiraPicker);
    });

    const refactorSelectionCommand = vscode.commands.registerCommand('devhouse.refactorSelection', async () => {
        await runAIWorkflow('refactor', jiraPicker);
    });

    const gitListener = new GitListener(aggregator, activityMonitor, webhookSender, cameraMonitor, jiraPicker);
    await gitListener.initialize();

    // Register a manual test command
    const testCommand = vscode.commands.registerCommand('devintel.sendTestPing', async () => {
        const session = aggregator.getSession();
        vscode.window.showInformationMessage(`DevIntel: Current Session Duration: ${session.editing_duration_minutes}m. Lines added: ${session.lines_added}`);
    });

    const presenceTestCommand = vscode.commands.registerCommand('devintel.runPresenceCheck', async () => {
        cameraMonitor.triggerPresenceCheck();
        vscode.window.showInformationMessage('DevIntel: Presence check triggered. See the "Developer Intelligence" output for details.');
    });

    context.subscriptions.push(
        activityMonitor,
        gitListener,
        cameraMonitor,
        jiraPicker,
        selectJiraCommand,
        askAICommand,
        generateAtCursorCommand,
        refactorSelectionCommand,
        testCommand,
        presenceTestCommand
    );
}

export function deactivate() {
    // Clean up
}

type AIMode = 'ask' | 'generate' | 'refactor';

function getAIConfig() {
    const config = vscode.workspace.getConfiguration('devintel');
    return {
        developerId: config.get<string>('developerId', 'dev_22'),
        repositoryName: config.get<string>('repositoryName', 'payment-service'),
        aiBackendUrl: config.get<string>('aiBackendUrl', 'http://127.0.0.1:8010'),
        aiModel: config.get<string>('aiModel', 'llama3.2:latest'),
    };
}

async function runAIWorkflow(mode: AIMode, jiraPicker: JiraPicker): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('Open a file in the editor before using DevHouse AI.');
        return;
    }

    const promptPlaceholder =
        mode === 'refactor'
            ? 'Describe how you want to refactor the selected code'
            : mode === 'generate'
                ? 'Describe what should be generated at the cursor'
                : 'Ask DevHouse AI anything about the current code';

    const prompt = await vscode.window.showInputBox({
        prompt: 'DevHouse AI request',
        placeHolder: promptPlaceholder,
        ignoreFocusOut: true,
    });

    if (!prompt || !prompt.trim()) {
        return;
    }

    if (mode === 'refactor' && editor.selection.isEmpty) {
        vscode.window.showWarningMessage('Select code first, then run "DevHouse: Refactor Selection".');
        return;
    }

    const requestPayload = buildAIRequestPayload(mode, prompt.trim(), editor, jiraPicker);
    logger.appendLine(`[AI] Sending ${mode} request for ${requestPayload.file_path || 'untitled file'}`);

    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: 'DevHouse AI',
            cancellable: false,
        },
        async () => {
            const response = await sendAIRequest(requestPayload);
            if (!response) {
                return;
            }

            await handleAIResponse(mode, editor, response);
        },
    );
}

function buildAIRequestPayload(mode: AIMode, prompt: string, editor: vscode.TextEditor, jiraPicker: JiraPicker): AIQueryRequest {
    const config = getAIConfig();
    const document = editor.document;
    const selection = editor.selection;
    const selectedText = selection.isEmpty ? '' : document.getText(selection);
    const visibleRange = editor.visibleRanges[0];
    const surroundingCode = visibleRange ? document.getText(visibleRange) : document.getText();

    return {
        prompt,
        mode,
        developer_id: config.developerId,
        repository_name: config.repositoryName,
        issue_id: jiraPicker.getActiveIssueId(),
        model: config.aiModel,
        file_path: document.isUntitled ? null : document.fileName,
        language: document.languageId,
        selected_text: selectedText,
        surrounding_code: surroundingCode.slice(0, 16000),
        selection: {
            start_line: selection.start.line,
            start_character: selection.start.character,
            end_line: selection.end.line,
            end_character: selection.end.character,
        },
    };
}

async function sendAIRequest(payload: AIQueryRequest): Promise<AIQueryResponse | null> {
    const { aiBackendUrl } = getAIConfig();
    const baseUrl = aiBackendUrl.replace(/\/$/, '');

    try {
        const response = await fetch(`${baseUrl}/api/ai/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const errorText = await response.text();
            logger.appendLine(`[AI] Backend error ${response.status}: ${errorText}`);
            vscode.window.showErrorMessage(`DevHouse AI request failed: ${response.status}`);
            return null;
        }

        const data = (await response.json()) as AIQueryResponse;
        return data;
    } catch (error) {
        logger.appendLine(`[AI] Request failed: ${error}`);
        vscode.window.showErrorMessage('DevHouse AI backend is unreachable. Check devintel.aiBackendUrl.');
        return null;
    }
}

async function handleAIResponse(mode: AIMode, editor: vscode.TextEditor, response: AIQueryResponse): Promise<void> {
    const usage = response.usage || {};
    const inputTokens = response.input_tokens ?? usage.input_tokens ?? 0;
    const outputTokens = response.output_tokens ?? usage.output_tokens ?? 0;
    const answer = extractAnswerText(response);
    const edits = normalizeEditInstructions(response, mode, editor, answer);

    if (edits.length) {
        const applied = await applyAIEdits(editor, edits);
        if (applied) {
            logger.appendLine(`[AI] Applied ${edits.length} edit(s). Tokens in/out: ${inputTokens}/${outputTokens}`);
            vscode.window.showInformationMessage(`DevHouse AI applied ${edits.length} edit(s). Tokens: ${inputTokens}/${outputTokens}.`);
            return;
        }
    }

    if (answer) {
        await showAIAnswer(answer, inputTokens, outputTokens, response.model);
        return;
    }

    vscode.window.showWarningMessage('DevHouse AI returned no editable output.');
}

function extractAnswerText(response: AIQueryResponse): string {
    return String(
        response.response
        || response.answer
        || response.output
        || response.message
        || '',
    ).trim();
}

function normalizeEditInstructions(
    response: AIQueryResponse,
    mode: AIMode,
    editor: vscode.TextEditor,
    answer: string,
): AIEditInstruction[] {
    const edits = Array.isArray(response.edits) ? response.edits.filter(Boolean) : [];
    if (response.edit) {
        edits.unshift(response.edit);
    }
    if (edits.length) {
        return edits;
    }

    const extractedCode = extractCodeBlock(answer) || answer;
    if (!extractedCode.trim()) {
        return [];
    }

    if (mode === 'refactor' && !editor.selection.isEmpty) {
        return [{ kind: 'replace_selection', content: extractedCode }];
    }
    if (mode === 'generate') {
        return [{ kind: 'insert_at_cursor', content: extractedCode }];
    }
    return [];
}

function extractCodeBlock(text: string): string {
    const match = text.match(/```(?:[\w+-]+)?\r?\n([\s\S]*?)```/);
    return match ? match[1].trim() : '';
}

async function applyAIEdits(editor: vscode.TextEditor, edits: AIEditInstruction[]): Promise<boolean> {
    const workspaceEdit = new vscode.WorkspaceEdit();
    const document = editor.document;

    for (const edit of edits) {
        const content = String(edit.content || '');
        const kind = edit.kind || 'replace_selection';

        if (kind === 'replace_full_document') {
            const start = new vscode.Position(0, 0);
            const end = document.lineAt(document.lineCount - 1).range.end;
            workspaceEdit.replace(document.uri, new vscode.Range(start, end), content);
            continue;
        }

        if (kind === 'create_file' && edit.file_path) {
            const uri = vscode.Uri.file(edit.file_path);
            workspaceEdit.createFile(uri, { ignoreIfExists: false, overwrite: true });
            workspaceEdit.insert(uri, new vscode.Position(0, 0), content);
            continue;
        }

        if (kind === 'insert_at_cursor') {
            workspaceEdit.insert(document.uri, editor.selection.active, content);
            continue;
        }

        const targetRange = editor.selection.isEmpty
            ? new vscode.Range(editor.selection.active, editor.selection.active)
            : new vscode.Range(editor.selection.start, editor.selection.end);
        workspaceEdit.replace(document.uri, targetRange, content);
    }

    return vscode.workspace.applyEdit(workspaceEdit);
}

async function showAIAnswer(answer: string, inputTokens: number, outputTokens: number, model?: string): Promise<void> {
    const document = await vscode.workspace.openTextDocument({
        content: [
            '# DevHouse AI',
            '',
            `Model: ${model || 'unknown'}`,
            `Input tokens: ${inputTokens}`,
            `Output tokens: ${outputTokens}`,
            '',
            answer,
            '',
        ].join('\n'),
        language: 'markdown',
    });
    await vscode.window.showTextDocument(document, { preview: true });
    logger.appendLine(`[AI] Response opened in editor. Tokens in/out: ${inputTokens}/${outputTokens}`);
}
