import * as vscode from 'vscode';
import { SignalAggregator } from './signalAggregator';

export class ActivityMonitor {
    private aggregator: SignalAggregator;
    private disposables: vscode.Disposable[] = [];
    private openedFiles: Set<string> = new Set();
    private modifiedFiles: Set<string> = new Set();

    constructor(aggregator: SignalAggregator) {
        this.aggregator = aggregator;
    }

    public start(): void {
        this.disposables.push(
            vscode.workspace.onDidOpenTextDocument(this.onDidOpenDocument.bind(this)),
            vscode.workspace.onDidChangeTextDocument(this.onDidChangeDocument.bind(this))
        );
    }

    private onDidOpenDocument(document: vscode.TextDocument): void {
        const fileName = document.fileName;
        if (!this.openedFiles.has(fileName)) {
            this.openedFiles.add(fileName);
            this.aggregator.addFilesOpened(1);
        }
    }

    private onDidChangeDocument(event: vscode.TextDocumentChangeEvent): void {
        if (event.contentChanges.length === 0) {
            return;
        }

        let linesAdded = 0;
        let linesDeleted = 0;

        for (const change of event.contentChanges) {
            const newLines = (change.text.match(/\n/g) || []).length;
            const removedLines = change.range.end.line - change.range.start.line;
            
            if (newLines > 0) linesAdded += newLines;
            if (removedLines > 0) linesDeleted += removedLines;
            
            if (newLines === 0 && removedLines === 0 && change.text.length > 0) {
                linesAdded += 1;
            } else if (newLines === 0 && removedLines === 0 && change.text.length === 0 && change.rangeLength > 0) {
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

    public resetTracker(): void {
        this.openedFiles.clear();
        this.modifiedFiles.clear();
    }

    public dispose(): void {
        this.disposables.forEach(d => d.dispose());
    }
}
