import * as vscode from 'vscode';
import { logger } from './extension';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

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
    private readonly scriptPath: string;

    constructor(state: vscode.Memento) {
        this.state = state;
        this.scriptPath = this.resolveScriptPath();
        
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

            logger.appendLine(`[PRESENCE] Camera monitor started. Script: ${this.scriptPath}`);
            
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
        if (!fs.existsSync(this.scriptPath)) {
            logger.appendLine(`[PRESENCE] Face detection script not found: ${this.scriptPath}`);
            this.recordCheck(0);
            return;
        }

        logger.appendLine(`[PRESENCE] Running face check with script: ${this.scriptPath}`);
        this.runPythonScript([...this.getPythonCommandCandidates()], this.scriptPath);
    }

    private resolveScriptPath(): string {
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

    private getPythonCommandCandidates(): string[] {
        const config = vscode.workspace.getConfiguration('devintel');
        const configured = (config.get<string>('pythonCommand', '') || '').trim();
        const isWindows = process.platform === 'win32';
        const candidates = [configured, isWindows ? 'python' : 'python3', 'python', 'py'].filter(Boolean);
        return [...new Set(candidates)];
    }

    private runPythonScript(commands: string[], scriptPath: string): void {
        const command = commands.shift();
        if (!command) {
            logger.appendLine('[PRESENCE] No working Python interpreter was found. Recording absence.');
            this.recordCheck(0);
            return;
        }

        cp.execFile(command, [scriptPath], { windowsHide: true }, (error, stdout, stderr) => {
            if (error) {
                logger.appendLine(`[PRESENCE] Python command failed (${command}): ${error.message}`);
                if (stderr.trim()) {
                    logger.appendLine(`[PRESENCE] stderr (${command}): ${stderr.trim()}`);
                }
                this.runPythonScript(commands, scriptPath);
                return;
            }

            const result = stdout.trim();
            if (stderr.trim()) {
                logger.appendLine(`[PRESENCE] stderr (${command}): ${stderr.trim()}`);
            }
            logger.appendLine(`[PRESENCE] Raw detector output (${command}): ${result || '<empty>'}`);

            if (result === '1') {
                this.recordCheck(1);
            } else if (result === '0') {
                this.recordCheck(0);
            } else {
                logger.appendLine(`[PRESENCE] Unexpected detector output. Recording absence.`);
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

    public triggerPresenceCheck() {
        this.checkPresence();
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
