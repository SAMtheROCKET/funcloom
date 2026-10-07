'use strict';

const path = require('node:path');
const { runPython, ensureTrusted, checkArguments } = require('./runner');
const { resolvePythonPath, ensureTool } = require('./setup');
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
        const pythonPath = await resolvePythonPath(vscode, uri, config.get('pythonPath', ''));
        await ensureTool(vscode, {
            pythonPath, tool, displayName: manifest.displayName,
            version: manifest.toolVersion, runPython,
        });
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
            if (command === 'extract') {
                args = await extractArguments(vscode, editor, uri);
                if (!args) { return; }
            } else if (command === 'check') {
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
        if (command === 'extract') {
            if (result.code !== 0) {
                throw new Error(result.output.split(/\r?\n/).find(line => line.startsWith('Not applied'))
                    || 'Nothing was written; see the FuncLoom output for the reasons.');
            }
            await vscode.window.showTextDocument(vscode.Uri.file(args.at(-1)));
        } else if (command === 'check') {
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

// Selected physical lines (1-based); a selection ending at column 0 of a
// later line does not include that line.
function selectedLines(selection) {
    const start = selection.start.line + 1;
    let end = selection.end.line + 1;
    if (end > start && selection.end.character === 0) { end -= 1; }
    return { start, end };
}

// Ask for the function name and a new output file; null when cancelled.
async function extractArguments(vscode, editor, uri) {
    if (!editor || editor.selection.isEmpty) {
        throw new Error('Select the lines to extract first.');
    }
    const { start, end } = selectedLines(editor.selection);
    const name = await vscode.window.showInputBox({
        title: `Function name for lines ${start}-${end}`,
        validateInput: text => /^[A-Za-z_][A-Za-z0-9_]*$/.test(text) ? null : 'Use a Python identifier.',
    });
    if (!name) { return null; }
    const outputUri = await vscode.window.showSaveDialog({
        title: 'Choose a new file for the rewritten module',
        defaultUri: vscode.Uri.file(uri.fsPath.replace(/\.py$/, '') + '.extracted.py'),
    });
    if (!outputUri) { return null; }
    return ['plan', uri.fsPath, '--start-line', String(start), '--end-line', String(end),
        '--name', name, '--apply-to', outputUri.fsPath];
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

module.exports = { activate, describeRefusal, selectedLines };
