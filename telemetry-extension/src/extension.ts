import * as vscode from 'vscode';
import { SignalAggregator } from './signalAggregator';
import { ActivityMonitor } from './activityMonitor';
import { WebhookSender } from './webhookSender';
import { GitListener } from './gitListener';
import { CameraMonitor } from './cameraMonitor';
import { JiraPicker } from './jiraPicker';

export const logger = vscode.window.createOutputChannel("Developer Intelligence");

export async function activate(context: vscode.ExtensionContext) {
    logger.show(true);
    logger.appendLine('Developer Intelligence Telemetry extension is now active');

    // Initialize core modules
    const aggregator = new SignalAggregator();
    
    const config = vscode.workspace.getConfiguration('devintel');
    const supabaseUrl = config.get<string>('supabaseUrl', 'https://sgszqmuqwjghogtfuhbq.supabase.co');
    const supabaseKey = config.get<string>('supabaseKey', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnc3pxbXVxd2pnaG9ndGZ1aGJxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM5MjE3MDIsImV4cCI6MjA4OTQ5NzcwMn0.kZbXvIIRnMq6gdWrowF9MKOkEgFCHlkuNaf6kT-QaSM');
    const estimateEngineUrl = config.get<string>('estimateEngineUrl', 'http://127.0.0.1:8000');
    
    const webhookSender = new WebhookSender(supabaseUrl, supabaseKey, estimateEngineUrl);
    
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
        testCommand,
        presenceTestCommand
    );
}

export function deactivate() {
    // Clean up
}
