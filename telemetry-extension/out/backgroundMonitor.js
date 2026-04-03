"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.BackgroundMonitor = void 0;
const vscode = require("vscode");
const extension_1 = require("./extension");
const cp = require("child_process");
const os = require("os");
const APP_WHITELIST = {
    'chrome.exe': 'Google Chrome',
    'chrome': 'Google Chrome',
    'firefox.exe': 'Mozilla Firefox',
    'firefox': 'Mozilla Firefox',
    'msedge.exe': 'Microsoft Edge',
    'msedge': 'Microsoft Edge',
    'code.exe': 'Visual Studio Code',
    'code': 'Visual Studio Code',
    'slack.exe': 'Slack',
    'slack': 'Slack',
    'teams.exe': 'Microsoft Teams',
    'teams': 'Microsoft Teams',
    'discord.exe': 'Discord',
    'discord': 'Discord',
    'spotify.exe': 'Spotify',
    'spotify': 'Spotify',
    'zoom.exe': 'Zoom',
    'zoom.us': 'Zoom',
    'postman.exe': 'Postman',
    'postman': 'Postman',
    'figma.exe': 'Figma',
    'figma': 'Figma',
    'notion.exe': 'Notion',
    'notion': 'Notion',
    'obs64.exe': 'OBS Studio',
    'obs': 'OBS Studio'
};
class BackgroundMonitor {
    state;
    trackedApps = new Map();
    intervalId;
    constructor(state) {
        this.state = state;
        // Restore state
        const savedApps = this.state.get('devintel.backgroundApps', {});
        for (const [key, value] of Object.entries(savedApps)) {
            this.trackedApps.set(key, value);
        }
        this.start();
        vscode.workspace.onDidChangeConfiguration(e => {
            if (e.affectsConfiguration('devintel.telemetryEnabled')) {
                this.start();
            }
        });
    }
    start() {
        const config = vscode.workspace.getConfiguration('devintel');
        const enabled = config.get('telemetryEnabled', true);
        if (!enabled) {
            this.stop();
            return;
        }
        if (!this.intervalId) {
            this.intervalId = setInterval(() => {
                this.checkApps();
            }, 60000);
            // Initial check immediately
            this.checkApps();
        }
    }
    stop() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = undefined;
        }
    }
    checkApps() {
        const isWindows = os.platform() === 'win32';
        const cmd = isWindows ? 'tasklist /FO CSV /NH' : 'ps aux';
        cp.exec(cmd, { maxBuffer: 1024 * 1024 * 5 }, (error, stdout, stderr) => {
            if (error) {
                extension_1.logger.appendLine(`[BACKGROUND APP] Execution error: ${error.message}`);
                return;
            }
            const now = Date.now();
            const lines = stdout.split('\n');
            const seenInThisCheck = new Set();
            for (const line of lines) {
                let textToMatch = '';
                if (isWindows) {
                    const match = line.match(/^"([^"]+)"/);
                    if (match) {
                        textToMatch = match[1].toLowerCase();
                    }
                }
                else {
                    const parts = line.trim().split(/\s+/);
                    if (parts.length > 10) {
                        textToMatch = parts.slice(10).join(' ').toLowerCase();
                    }
                }
                if (!textToMatch)
                    continue;
                let matchedAppName;
                let matchedProcessName;
                for (const [key, appName] of Object.entries(APP_WHITELIST)) {
                    if ((isWindows && textToMatch === key) || (!isWindows && textToMatch.includes(key))) {
                        matchedAppName = appName;
                        matchedProcessName = key;
                        break;
                    }
                }
                if (matchedAppName && matchedProcessName && !seenInThisCheck.has(matchedProcessName)) {
                    seenInThisCheck.add(matchedProcessName);
                    const existing = this.trackedApps.get(matchedProcessName);
                    if (existing) {
                        existing.last_seen = now;
                    }
                    else {
                        this.trackedApps.set(matchedProcessName, {
                            app_name: matchedAppName,
                            process_name: matchedProcessName,
                            first_seen: now,
                            last_seen: now
                        });
                    }
                }
            }
            this.saveState();
            extension_1.logger.appendLine(`[BACKGROUND APP] Monitored ${this.trackedApps.size} whitelisted apps in this cycle.`);
        });
    }
    saveState() {
        const objToSave = {};
        for (const [key, value] of this.trackedApps.entries()) {
            objToSave[key] = value;
        }
        this.state.update('devintel.backgroundApps', objToSave);
    }
    getTrackedApps() {
        const result = [];
        for (const app of this.trackedApps.values()) {
            const durationSecs = Math.floor((app.last_seen - app.first_seen) / 1000);
            result.push({
                app_name: app.app_name,
                process_name: app.process_name,
                first_seen: new Date(app.first_seen).toISOString(),
                last_seen: new Date(app.last_seen).toISOString(),
                duration_seconds: durationSecs
            });
        }
        return result;
    }
    resetSession() {
        this.trackedApps.clear();
        this.saveState();
        extension_1.logger.appendLine(`[BACKGROUND APP] Session reset.`);
    }
    dispose() {
        this.stop();
    }
}
exports.BackgroundMonitor = BackgroundMonitor;
//# sourceMappingURL=backgroundMonitor.js.map