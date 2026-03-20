import * as vscode from 'vscode';
import { logger } from './extension';
import * as cp from 'child_process';
import * as path from 'path';

export interface PresenceData {
    attendance_pct: number;
    total_checks: number;
    present_checks: number;
    session_duration_seconds: number;
    session_start: string;
}

export class CameraMonitor {
    private state: vscode.Memento;
    private checks: number[] = [];
    private sessionStart: number;
    private intervalId?: NodeJS.Timeout;

    constructor(state: vscode.Memento) {
        this.state = state;
        
        // Restore state
        this.checks = this.state.get<number[]>('devintel.presence.checks', []);
        this.sessionStart = this.state.get<number>('devintel.presence.sessionStart', Date.now());
        
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

    private start() {
        const config = vscode.workspace.getConfiguration('devintel');
        const enabled = config.get<boolean>('telemetryEnabled', true);
        
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

    private stop() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = undefined;
        }
    }

    private checkPresence() {
        // When running compiled out/cameraMonitor.js, __dirname is .../out
        // The script is stored in .../src/detect_face.py
        const scriptPath = path.join(__dirname, '..', 'src', 'detect_face.py');
        
        cp.exec(`py "${scriptPath}"`, (error, stdout, stderr) => {
            if (error) {
                logger.appendLine(`[PRESENCE] Python execution error: ${error.message}`);
                this.recordCheck(0);
                return;
            }
            
            const result = stdout.trim();
            if (result === '1') {
                this.recordCheck(1);
            } else {
                this.recordCheck(0);
            }
        });
    }

    private recordCheck(value: number) {
        this.checks.push(value);
        this.saveState();
        logger.appendLine(`[PRESENCE] Face detected: ${value === 1}. Total checks: ${this.checks.length}`);
    }

    private saveState() {
        this.state.update('devintel.presence.checks', this.checks);
        this.state.update('devintel.presence.sessionStart', this.sessionStart);
    }

    public getPresenceData(): PresenceData {
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

    public resetSession() {
        this.checks = [];
        this.sessionStart = Date.now();
        this.saveState();
        logger.appendLine(`[PRESENCE] Session reset.`);
    }

    public dispose() {
        this.stop();
    }
}
