'use strict';

const path = require('node:path');
const { runPython, ensureTrusted, checkArguments } = require('./runner');
const manifest = require('./package.json');

function activate(context) {
    const vscode = require('vscode');
    const tool = manifest.name;
    const output = vscode.window.createOutputChannel(manifest.displayName);
    const diagnostics = vscode.languages.createDiagnosticCollection(tool);
    context.subscriptions.push(output, diagnostics);

    async function execute(command) {
        ensureTrusted(vscode);
        const editor = vscode.window.activeTextEditor;
        const notebook = vscode.window.activeNotebookEditor;
        const uri = notebook?.notebook.uri || editor?.document.uri;
        if (!uri) { throw new Error('Open a Python file or notebook first.'); }
        const config = vscode.workspace.getConfiguration(tool, uri);
        let pythonPath = config.get('pythonPath', 'python');
        if (!path.isAbsolute(pythonPath) && /[\\/]/.test(pythonPath)) {
            const workspace = vscode.workspace.getWorkspaceFolder(uri);
            if (!workspace) { throw new Error('Use an absolute Python executable path.'); }
            pythonPath = path.resolve(workspace.uri.fsPath, pythonPath);
        }
        const runtime = await runPython(pythonPath, tool, ['--version']);
        if (runtime.code !== 0 || !runtime.output.includes(manifest.toolVersion)) {
            throw new Error(`Install ${tool} ${manifest.toolVersion} in the configured interpreter. ${runtime.errors}`);
        }
        let args;
        let input = '';
        if (command === 'snippet') {
            if (!editor || !['python', 'python3'].includes(editor.document.languageId)) {
                throw new Error('Select Python text or open a Python notebook cell.');
            }
            input = editor.selection.isEmpty ? editor.document.getText()
                : editor.document.getText(editor.selection);
            args = ['snippet', '-', '--format', 'json'];
            const choice = await vscode.window.showQuickPick(
                ['No context', 'Use context TOML'], { title: 'FuncLoom context' });
            if (!choice) { return; }
            if (choice === 'Use context TOML') {
                const selected = await vscode.window.showOpenDialog({
                    canSelectMany: false, filters: { 'Context TOML': ['toml'] },
                });
                if (!selected) { return; }
                args.push('--context', selected[0].fsPath);
            } else { args.push('--no-context'); }
        } else {
            if (uri.scheme !== 'file') { throw new Error('This command requires a local saved file.'); }
            if (editor?.document.isDirty || notebook?.notebook.isDirty) {
                throw new Error('Save the file before running this command.');
            }
            if (command !== 'modularize' && path.extname(uri.fsPath) !== '.py') {
                throw new Error('Use a saved .py file; notebooks support function drafts and modularization.');
            }
            if (command === 'check') {
                args = checkArguments(tool, uri.fsPath, config.get('profile', 'strict'));
            } else if (command === 'preview' || command === 'fix') {
                args = ['fix', uri.fsPath, '--profile', config.get('profile', 'strict')];
                if (command === 'preview') { args.push('--diff'); }
            } else {
                const outputUri = await vscode.window.showSaveDialog({
                    title: 'Choose a new output file or folder name',
                    defaultUri: vscode.Uri.file(uri.fsPath + (command === 'refine' ? '.refined.py' : '.modular')),
                });
                if (!outputUri) { return; }
                args = [command, uri.fsPath, '--output', outputUri.fsPath, '--format', 'json'];
            }
        }
        const result = await runPython(pythonPath, tool, args, input);
        output.clear();
        output.appendLine(result.output);
        if (result.errors) { output.appendLine(result.errors); }
        output.show(true);
        if (result.code === null || result.code > 1) {
            throw new Error(result.errors || result.output || 'The tool failed.');
        }
        if (command === 'check') {
            const report = JSON.parse(result.output);
            const findings = Array.isArray(report) ? report : [
                ...(report.diagnostics || []),
                ...(report.modules || []).flatMap(module => module.diagnostics || []),
            ];
            diagnostics.set(uri, findings.map(finding => {
                const line = Math.max(0, finding.line - 1);
                const column = Math.max(0, finding.column - 1);
                const diagnostic = new vscode.Diagnostic(
                    new vscode.Range(line, column, line, column + 1), finding.message,
                    finding.severity === 'error' ? vscode.DiagnosticSeverity.Error : vscode.DiagnosticSeverity.Warning);
                diagnostic.code = finding.code;
                diagnostic.source = tool;
                return diagnostic;
            }));
        } else if (command !== 'fix') {
            const document = await vscode.workspace.openTextDocument({
                content: result.output, language: command === 'preview' ? 'diff' : 'json',
            });
            await vscode.window.showTextDocument(document, { preview: true });
            const refusal = describeRefusal(command, result.output);
            if (refusal) { throw new Error(refusal); }
        }
    }

    for (const contribution of manifest.contributes.commands) {
        const command = contribution.command.split('.').at(-1);
        context.subscriptions.push(vscode.commands.registerCommand(contribution.command,
            () => execute(command).catch(error => vscode.window.showErrorMessage(error.message))));
    }
}

// A modularize or refine report that wrote nothing must not look like a
// success: name the first diagnostics so the user sees why.
function describeRefusal(command, outputText) {
    if (!['modularize', 'refine'].includes(command)) { return null; }
    let report;
    try { report = JSON.parse(outputText); } catch { return null; }
    if (!report || !report.status || ['written', 'unchanged'].includes(report.status)) {
        return null;
    }
    const reasons = (report.diagnostics || []).slice(0, 3)
        .map(item => `${item.code}: ${item.message}`).join('; ');
    return `Nothing was written (${report.status}). ${reasons || 'See the report for details.'}`;
}

module.exports = { activate, describeRefusal };
