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
    const gitListener = new gitListener_1.GitListener(aggregator, activityMonitor, webhookSender, cameraMonitor);
    await gitListener.initialize();
    // Register a manual test command
    const testCommand = vscode.commands.registerCommand('devintel.sendTestPing', async () => {
        const session = aggregator.getSession();
        vscode.window.showInformationMessage(`DevIntel: Current Session Duration: ${session.editing_duration_minutes}m. Lines added: ${session.lines_added}`);
    });
    context.subscriptions.push(activityMonitor, gitListener, cameraMonitor, testCommand);
}
function deactivate() {
    // Clean up
}
//# sourceMappingURL=extension.js.map