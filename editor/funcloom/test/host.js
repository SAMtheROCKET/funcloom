'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
const manifest = require('../package.json');

async function run() {
    const tool = manifest.name;
    const extension = vscode.extensions.getExtension(`samtherocket.${tool}`);
    assert.ok(extension, 'Extension must be discoverable');
    await extension.activate();
    const commands = await vscode.commands.getCommands(true);
    for (const command of manifest.contributes.commands) {
        assert.ok(commands.includes(command.command), command.command);
    }
    const root = vscode.workspace.workspaceFolders[0].uri.fsPath;
    await vscode.workspace.getConfiguration(tool).update('pythonPath',
        process.env.PYTHON_REVIEW_PATH, vscode.ConfigurationTarget.Workspace);
    const fixture = path.join(root, 'fixture.py');
    const original = 'def log_reading(reading_int: int):\n    print(reading_int)\n';
    fs.writeFileSync(fixture, original);
    const uri = vscode.Uri.file(fixture);
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(uri));
    await vscode.commands.executeCommand(`${tool}.check`);
    assert.ok(vscode.languages.getDiagnostics(uri).some(item => item.source === tool),
        'Checking must populate Problems');
    assert.equal(fs.readFileSync(fixture, 'utf8'), original);
    if (tool === 'refactrail') {
        await vscode.commands.executeCommand('refactrail.preview');
        assert.equal(fs.readFileSync(fixture, 'utf8'), original);
        assert.equal(vscode.window.activeTextEditor.document.languageId, 'diff');
        await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(uri));
        await vscode.commands.executeCommand('refactrail.fix');
        assert.ok(fs.readFileSync(fixture, 'utf8').includes('-> None:'));
    }
    fs.writeFileSync(path.join(root, 'host-result.json'), JSON.stringify({
        tool, version: manifest.version, activation: 'passed', check: 'passed',
        previewAndFix: tool === 'refactrail' ? 'passed' : 'not exercised',
    }, null, 2));
}

module.exports = { run };
