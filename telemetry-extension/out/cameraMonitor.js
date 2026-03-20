"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.CameraMonitor = void 0;
const vscode = require("vscode");
const extension_1 = require("./extension");
const cp = require("child_process");
const path = require("path");
class CameraMonitor {
    state;
    checks = [];
    sessionStart;
    intervalId;
    constructor(state) {
        this.state = state;
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
        // When running compiled out/cameraMonitor.js, __dirname is .../out
        // The script is stored in .../src/detect_face.py
        const scriptPath = path.join(__dirname, '..', 'src', 'detect_face.py');
        cp.exec(`py "${scriptPath}"`, (error, stdout, stderr) => {
            if (error) {
                extension_1.logger.appendLine(`[PRESENCE] Python execution error: ${error.message}`);
                this.recordCheck(0);
                return;
            }
            const result = stdout.trim();
            if (result === '1') {
                this.recordCheck(1);
            }
            else {
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