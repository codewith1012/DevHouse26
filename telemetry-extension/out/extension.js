"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.logger = void 0;
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = require("vscode");
const signalAggregator_1 = require("./signalAggregator");
const activityMonitor_1 = require("./activityMonitor");
const webhookSender_1 = require("./webhookSender");
const gitListener_1 = require("./gitListener");
const cameraMonitor_1 = require("./cameraMonitor");
const jiraPicker_1 = require("./jiraPicker");
exports.logger = vscode.window.createOutputChannel("Developer Intelligence");
async function activate(context) {
    exports.logger.show(true);
    exports.logger.appendLine('Developer Intelligence Telemetry extension is now active');
    // Initialize core modules
    const aggregator = new signalAggregator_1.SignalAggregator();
    const config = vscode.workspace.getConfiguration('devintel');
    const supabaseUrl = config.get('supabaseUrl', 'https://sgszqmuqwjghogtfuhbq.supabase.co');
    const supabaseKey = config.get('supabaseKey', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnc3pxbXVxd2pnaG9ndGZ1aGJxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM5MjE3MDIsImV4cCI6MjA4OTQ5NzcwMn0.kZbXvIIRnMq6gdWrowF9MKOkEgFCHlkuNaf6kT-QaSM');
    const webhookSender = new webhookSender_1.WebhookSender(supabaseUrl, supabaseKey);
    const activityMonitor = new activityMonitor_1.ActivityMonitor(aggregator);
    activityMonitor.start();
    const cameraMonitor = new cameraMonitor_1.CameraMonitor(context.globalState);
    const jiraPicker = new jiraPicker_1.JiraPicker(context);
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
    const gitListener = new gitListener_1.GitListener(aggregator, activityMonitor, webhookSender, cameraMonitor, jiraPicker);
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
    context.subscriptions.push(activityMonitor, gitListener, cameraMonitor, jiraPicker, selectJiraCommand, askAICommand, generateAtCursorCommand, refactorSelectionCommand, testCommand, presenceTestCommand);
}
function deactivate() {
    // Clean up
}
function getAIConfig() {
    const config = vscode.workspace.getConfiguration('devintel');
    return {
        developerId: config.get('developerId', 'dev_22'),
        repositoryName: config.get('repositoryName', 'payment-service'),
        aiBackendUrl: config.get('aiBackendUrl', 'http://127.0.0.1:8010'),
        aiModel: config.get('aiModel', 'llama3.2:latest'),
    };
}
async function runAIWorkflow(mode, jiraPicker) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('Open a file in the editor before using DevHouse AI.');
        return;
    }
    const promptPlaceholder = mode === 'refactor'
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
    exports.logger.appendLine(`[AI] Sending ${mode} request for ${requestPayload.file_path || 'untitled file'}`);
    await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: 'DevHouse AI',
        cancellable: false,
    }, async () => {
        const response = await sendAIRequest(requestPayload);
        if (!response) {
            return;
        }
        await handleAIResponse(mode, editor, response);
    });
}
function buildAIRequestPayload(mode, prompt, editor, jiraPicker) {
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
async function sendAIRequest(payload) {
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
            exports.logger.appendLine(`[AI] Backend error ${response.status}: ${errorText}`);
            vscode.window.showErrorMessage(`DevHouse AI request failed: ${response.status}`);
            return null;
        }
        const data = (await response.json());
        return data;
    }
    catch (error) {
        exports.logger.appendLine(`[AI] Request failed: ${error}`);
        vscode.window.showErrorMessage('DevHouse AI backend is unreachable. Check devintel.aiBackendUrl.');
        return null;
    }
}
async function handleAIResponse(mode, editor, response) {
    const usage = response.usage || {};
    const inputTokens = response.input_tokens ?? usage.input_tokens ?? 0;
    const outputTokens = response.output_tokens ?? usage.output_tokens ?? 0;
    const answer = extractAnswerText(response);
    const edits = normalizeEditInstructions(response, mode, editor, answer);
    if (edits.length) {
        const applied = await applyAIEdits(editor, edits);
        if (applied) {
            exports.logger.appendLine(`[AI] Applied ${edits.length} edit(s). Tokens in/out: ${inputTokens}/${outputTokens}`);
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
function extractAnswerText(response) {
    return String(response.response
        || response.answer
        || response.output
        || response.message
        || '').trim();
}
function normalizeEditInstructions(response, mode, editor, answer) {
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
function extractCodeBlock(text) {
    const match = text.match(/```(?:[\w+-]+)?\r?\n([\s\S]*?)```/);
    return match ? match[1].trim() : '';
}
async function applyAIEdits(editor, edits) {
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
async function showAIAnswer(answer, inputTokens, outputTokens, model) {
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
    exports.logger.appendLine(`[AI] Response opened in editor. Tokens in/out: ${inputTokens}/${outputTokens}`);
}
//# sourceMappingURL=extension.js.map