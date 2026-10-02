'use strict';

// End-to-end editor workflows for FuncLoom, run inside a VS Code
// extension host. Dialogs are answered by stubbing vscode.window, so the
// run needs no clicks. Results go to host-workflows.json in the workspace.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
const manifest = require('../package.json');

const TOOL = manifest.name;

function stubWindow(stubs) {
    const originals = {};
    for (const [name, value] of Object.entries(stubs)) {
        originals[name] = vscode.window[name];
        vscode.window[name] = value;
    }
    return () => Object.assign(vscode.window, originals);
}

async function runCommand(command, stubs = {}) {
    const errors = [];
    const restore = stubWindow({
        ...stubs,
        showErrorMessage: async message => { errors.push(message); },
    });
    try {
        await vscode.commands.executeCommand(`${TOOL}.${command}`);
    } finally {
        restore();
    }
    return errors;
}

async function openFile(filePath) {
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
    return vscode.window.showTextDocument(document);
}

function activeText() {
    return vscode.window.activeTextEditor?.document.getText() ?? '';
}

async function closeAll() {
    await vscode.commands.executeCommand('workbench.action.closeAllEditors');
}

function notebookJson(cells) {
    return JSON.stringify({
        nbformat: 4, nbformat_minor: 5,
        metadata: { kernelspec: { language: 'python', name: 'python3', display_name: 'Python 3' },
            language_info: { name: 'python' } },
        cells: cells.map(source => ({ cell_type: 'code', metadata: {}, execution_count: null,
            outputs: [], source })),
    });
}

async function run() {
    const root = vscode.workspace.workspaceFolders[0].uri.fsPath;
    const results = {};
    const step = async (name, action) => {
        try {
            results[name] = (await action()) || 'passed';
        } catch (error) {
            results[name] = `FAILED: ${error.message}`;
            fs.writeFileSync(path.join(root, 'host-workflows.json'), JSON.stringify(results, null, 2));
            throw error;
        }
    };
    const extension = vscode.extensions.getExtension(`samtherocket.${TOOL}`);
    await step('activation and command registration', async () => {
        await extension.activate();
        const commands = await vscode.commands.getCommands(true);
        for (const command of manifest.contributes.commands) {
            assert.ok(commands.includes(command.command), command.command);
        }
    });
    const config = vscode.workspace.getConfiguration(TOOL);
    await config.update('pythonPath', process.env.PYTHON_REVIEW_PATH, vscode.ConfigurationTarget.Workspace);

    const fixture = path.join(root, 'fixture.py');
    const fixtureText = 'def log_reading(reading_int: int):\n    print(reading_int)\n';
    fs.writeFileSync(fixture, fixtureText);
    await step('check populates Problems without editing', async () => {
        await openFile(fixture);
        assert.deepEqual(await runCommand('check'), []);
        const found = vscode.languages.getDiagnostics(vscode.Uri.file(fixture))
            .filter(item => item.source === TOOL);
        assert.ok(found.length > 0, 'expected FuncLoom findings in Problems');
        assert.equal(fs.readFileSync(fixture, 'utf8'), fixtureText);
        return `passed (${found.length} problem(s), e.g. ${found[0].code})`;
    });

    const tax = path.join(root, 'snippet_tax.py');
    await step('snippet from a selection, no context', async () => {
        const editor = await openFile(tax);
        const last = editor.document.lineCount - 1;
        editor.selection = new vscode.Selection(0, 0, last, 0);
        const errors = await runCommand('snippet', { showQuickPick: async () => 'No context' });
        assert.deepEqual(errors, []);
        const report = JSON.parse(activeText());
        assert.ok(JSON.stringify(report).includes('def '), 'draft function expected');
        return 'passed (JSON draft shown)';
    });
    await step('snippet with an optional context TOML', async () => {
        await openFile(tax);
        const errors = await runCommand('snippet', {
            showQuickPick: async () => 'Use context TOML',
            showOpenDialog: async () => [vscode.Uri.file(path.join(root, 'snippet_tax.toml'))],
        });
        assert.deepEqual(errors, []);
        assert.ok(activeText().includes('calculate_invoice_totals_tuple'),
            'the context function name must be used');
    });
    await step('snippet cancelled at the context choice', async () => {
        const editor = await openFile(tax);
        const errors = await runCommand('snippet', { showQuickPick: async () => undefined });
        assert.deepEqual(errors, []);
        assert.equal(vscode.window.activeTextEditor.document.uri.fsPath, editor.document.uri.fsPath);
    });

    const notebookPath = path.join(root, 'orders.ipynb');
    fs.writeFileSync(notebookPath, notebookJson([
        'prices = [120, 80, 45]\n',
        '# Totals\ntotal = sum(prices) * 1.1\nprint(round(total, 2))\n',
    ]));
    await step('snippet from a notebook cell', async () => {
        await closeAll();
        const notebook = await vscode.workspace.openNotebookDocument(vscode.Uri.file(notebookPath));
        const editor = await vscode.window.showNotebookDocument(notebook);
        editor.selections = [new vscode.NotebookRange(1, 2)];
        await vscode.commands.executeCommand('notebook.cell.edit');
        assert.equal(vscode.window.activeTextEditor?.document.uri.scheme, 'vscode-notebook-cell');
        const errors = await runCommand('snippet', { showQuickPick: async () => 'No context' });
        assert.deepEqual(errors, []);
        assert.ok(activeText().includes('total'), 'cell code must be drafted');
    });
    await step('modularize a notebook into a chosen new folder', async () => {
        await closeAll();
        await vscode.window.showNotebookDocument(
            await vscode.workspace.openNotebookDocument(vscode.Uri.file(notebookPath)));
        const destination = path.join(root, 'orders_package');
        const errors = await runCommand('modularize', {
            showSaveDialog: async () => vscode.Uri.file(destination),
        });
        assert.deepEqual(errors, []);
        assert.ok(fs.existsSync(path.join(destination, 'main.py')), 'main.py expected');
        return `passed (${fs.readdirSync(destination).length} entries written)`;
    });
    await step('existing output folder is refused with a message', async () => {
        await closeAll();
        await vscode.window.showNotebookDocument(
            await vscode.workspace.openNotebookDocument(vscode.Uri.file(notebookPath)));
        const errors = await runCommand('modularize', {
            showSaveDialog: async () => vscode.Uri.file(path.join(root, 'orders_package')),
        });
        assert.equal(errors.length, 1, 'one error message expected');
        return `passed ("${errors[0].split('\n')[0].slice(0, 90)}")`;
    });
    await step('refine to a chosen new file, original untouched', async () => {
        await closeAll();
        await openFile(fixture);
        const destination = path.join(root, 'fixture.refined.py');
        const errors = await runCommand('refine', { showSaveDialog: async () => vscode.Uri.file(destination) });
        assert.deepEqual(errors, []);
        assert.ok(fs.existsSync(destination));
        assert.equal(fs.readFileSync(fixture, 'utf8'), fixtureText);
    });
    await step('cancelled save dialog writes nothing', async () => {
        await openFile(fixture);
        const before = fs.readdirSync(root).length;
        const errors = await runCommand('refine', { showSaveDialog: async () => undefined });
        assert.deepEqual(errors, []);
        assert.equal(fs.readdirSync(root).length, before);
    });
    await step('unsaved changes are refused with a message', async () => {
        const editor = await openFile(fixture);
        await editor.edit(builder => builder.insert(new vscode.Position(0, 0), '# edit\n'));
        const errors = await runCommand('check');
        assert.deepEqual(errors, ['Save the file before running this command.']);
        await vscode.commands.executeCommand('workbench.action.files.revert');
    });
    await step('wrong interpreter gives an install message', async () => {
        await openFile(fixture);
        await config.update('pythonPath', process.execPath, vscode.ConfigurationTarget.Workspace);
        const errors = await runCommand('check');
        await config.update('pythonPath', process.env.PYTHON_REVIEW_PATH, vscode.ConfigurationTarget.Workspace);
        assert.equal(errors.length, 1);
        assert.ok(errors[0].startsWith(`Install ${TOOL} ${manifest.toolVersion}`), errors[0]);
    });
    await step('no open file gives a clear message', async () => {
        await closeAll();
        assert.deepEqual(await runCommand('check'), ['Open a Python file or notebook first.']);
    });
    fs.writeFileSync(path.join(root, 'host-workflows.json'), JSON.stringify(results, null, 2));
}

module.exports = { run };
