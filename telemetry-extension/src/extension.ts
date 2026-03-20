import * as vscode from 'vscode';
import { SignalAggregator } from './signalAggregator';
import { ActivityMonitor } from './activityMonitor';
import { WebhookSender } from './webhookSender';
import { GitListener } from './gitListener';
import { CameraMonitor } from './cameraMonitor';

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

    const gitListener = new GitListener(aggregator, activityMonitor, webhookSender, cameraMonitor);
    await gitListener.initialize();

    // Register a manual test command
    const testCommand = vscode.commands.registerCommand('devintel.sendTestPing', async () => {
        const session = aggregator.getSession();
        vscode.window.showInformationMessage(`DevIntel: Current Session Duration: ${session.editing_duration_minutes}m. Lines added: ${session.lines_added}`);
    });

    context.subscriptions.push(
        activityMonitor,
        gitListener,
        cameraMonitor,
        testCommand
    );
}

export function deactivate() {
    // Clean up
}
