"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.CameraMonitor = void 0;
const vscode = require("vscode");
const extension_1 = require("./extension");
const cp = require("child_process");
const path = require("path");
const fs = require("fs");
class CameraMonitor {
    state;
    checks = [];
    sessionStart;
    intervalId;
    scriptPath;
    constructor(state) {
        this.state = state;
        this.scriptPath = this.resolveScriptPath();
        // Restore state
        this.checks = this.state.get('devintel.presence.checks', []);
        this.sessionStart = this.state.get('devintel.presence.sessionStart', Date.now());
        if (this.sessionStart === 0 || this.checks.length === 0) {
            this.sessionStart = Date.now();
            this.saveState();
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
                this.checkPresence();
            }, 45000);
            extension_1.logger.appendLine(`[PRESENCE] Camera monitor started. Script: ${this.scriptPath}`);
            // Initial check immediately
            this.checkPresence();
        }
    }
    stop() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = undefined;
        }
    }
    checkPresence() {
        if (!fs.existsSync(this.scriptPath)) {
            extension_1.logger.appendLine(`[PRESENCE] Face detection script not found: ${this.scriptPath}`);
            this.recordCheck(0);
            return;
        }
        extension_1.logger.appendLine(`[PRESENCE] Running face check with script: ${this.scriptPath}`);
        this.runPythonScript([...this.getPythonCommandCandidates()], this.scriptPath);
    }
    resolveScriptPath() {
        const candidates = [
            path.join(__dirname, '..', 'src', 'detect_face.py'),
            path.join(__dirname, 'detect_face.py')
        ];
        for (const candidate of candidates) {
            if (fs.existsSync(candidate)) {
                return candidate;
            }
        }
        return candidates[0];
    }
    getPythonCommandCandidates() {
        const config = vscode.workspace.getConfiguration('devintel');
        const configured = (config.get('pythonCommand', '') || '').trim();
        const isWindows = process.platform === 'win32';
        const candidates = [configured, isWindows ? 'python' : 'python3', 'python', 'py'].filter(Boolean);
        return [...new Set(candidates)];
    }
    runPythonScript(commands, scriptPath) {
        const command = commands.shift();
        if (!command) {
            extension_1.logger.appendLine('[PRESENCE] No working Python interpreter was found. Recording absence.');
            this.recordCheck(0);
            return;
        }
        cp.execFile(command, [scriptPath], { windowsHide: true }, (error, stdout, stderr) => {
            if (error) {
                extension_1.logger.appendLine(`[PRESENCE] Python command failed (${command}): ${error.message}`);
                if (stderr.trim()) {
                    extension_1.logger.appendLine(`[PRESENCE] stderr (${command}): ${stderr.trim()}`);
                }
                this.runPythonScript(commands, scriptPath);
                return;
            }
            const result = stdout.trim();
            if (stderr.trim()) {
                extension_1.logger.appendLine(`[PRESENCE] stderr (${command}): ${stderr.trim()}`);
            }
            extension_1.logger.appendLine(`[PRESENCE] Raw detector output (${command}): ${result || '<empty>'}`);
            if (result === '1') {
                this.recordCheck(1);
            }
            else if (result === '0') {
                this.recordCheck(0);
            }
            else {
                extension_1.logger.appendLine(`[PRESENCE] Unexpected detector output. Recording absence.`);
                this.recordCheck(0);
            }
        });
    }
    recordCheck(value) {
        this.checks.push(value);
        this.saveState();
        extension_1.logger.appendLine(`[PRESENCE] Face detected: ${value === 1}. Total checks: ${this.checks.length}`);
    }
    saveState() {
        this.state.update('devintel.presence.checks', this.checks);
        this.state.update('devintel.presence.sessionStart', this.sessionStart);
    }
    getPresenceData() {
        const total = this.checks.length;
        const present = this.checks.reduce((a, b) => a + b, 0);
        const pct = total === 0 ? 0 : (present / total) * 100;
        const durationSecs = Math.floor((Date.now() - this.sessionStart) / 1000);
        return {
            attendance_pct: Number(pct.toFixed(2)),
            total_checks: total,
            present_checks: present,
            session_duration_seconds: durationSecs,
            session_start: new Date(this.sessionStart).toISOString()
        };
    }
    triggerPresenceCheck() {
        this.checkPresence();
    }
    resetSession() {
        this.checks = [];
        this.sessionStart = Date.now();
        this.saveState();
        extension_1.logger.appendLine(`[PRESENCE] Session reset.`);
    }
    dispose() {
        this.stop();
    }
}
exports.CameraMonitor = CameraMonitor;
//# sourceMappingURL=cameraMonitor.js.map