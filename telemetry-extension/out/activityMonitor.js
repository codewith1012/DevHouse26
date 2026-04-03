"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ActivityMonitor = void 0;
const vscode = require("vscode");
class ActivityMonitor {
    aggregator;
    disposables = [];
    openedFiles = new Set();
    modifiedFiles = new Set();
    constructor(aggregator) {
        this.aggregator = aggregator;
    }
    start() {
        this.disposables.push(vscode.workspace.onDidOpenTextDocument(this.onDidOpenDocument.bind(this)), vscode.workspace.onDidChangeTextDocument(this.onDidChangeDocument.bind(this)));
    }
    onDidOpenDocument(document) {
        const fileName = document.fileName;
        if (!this.openedFiles.has(fileName)) {
            this.openedFiles.add(fileName);
            this.aggregator.addFilesOpened(1);
        }
    }
    onDidChangeDocument(event) {
        if (event.contentChanges.length === 0) {
            return;
        }
        let linesAdded = 0;
        let linesDeleted = 0;
        for (const change of event.contentChanges) {
            const newLines = (change.text.match(/\n/g) || []).length;
            const removedLines = change.range.end.line - change.range.start.line;
            if (newLines > 0)
                linesAdded += newLines;
            if (removedLines > 0)
                linesDeleted += removedLines;
            if (newLines === 0 && removedLines === 0 && change.text.length > 0) {
                linesAdded += 1;
            }
            else if (newLines === 0 && removedLines === 0 && change.text.length === 0 && change.rangeLength > 0) {
                linesDeleted += 1;
            }
        }
        const fileName = event.document.fileName;
        if (!this.modifiedFiles.has(fileName)) {
            this.modifiedFiles.add(fileName);
            this.aggregator.addFileModified();
        }
        this.aggregator.addLinesChanged(linesAdded, linesDeleted);
    }
    resetTracker() {
        this.openedFiles.clear();
        this.modifiedFiles.clear();
    }
    dispose() {
        this.disposables.forEach(d => d.dispose());
    }
}
exports.ActivityMonitor = ActivityMonitor;
//# sourceMappingURL=activityMonitor.js.map