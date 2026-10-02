'use strict';

const { spawn } = require('node:child_process');

function runPython(pythonPath, tool, argumentsList, input = '', spawnProcess = spawn) {
    if (!['funcloom', 'refactrail'].includes(tool)) {
        throw new Error('Unsupported tool');
    }
    return new Promise((resolve, reject) => {
        const process = spawnProcess(pythonPath, ['-I', '-m', tool, ...argumentsList], {
            shell: false,
            windowsHide: true,
            env: { ...global.process.env, PYTHONNOUSERSITE: '1', PYTHONUTF8: '1' },
        });
        let output = '';
        let errors = '';
        let settled = false;
        const timer = setTimeout(() => finish(new Error('Tool exceeded 60 seconds')), 60000);
        function finish(error, code) {
            if (settled) { return; }
            settled = true;
            clearTimeout(timer);
            if (error) { process.kill(); reject(error); }
            else { resolve({ code, output, errors }); }
        }
        function append(text, stderr) {
            if (stderr) { errors += text; } else { output += text; }
            if (Buffer.byteLength(output + errors, 'utf8') > 8 * 1024 * 1024) {
                finish(new Error('Tool output exceeded 8 MB'));
            }
        }
        process.stdout.setEncoding('utf8');
        process.stderr.setEncoding('utf8');
        process.stdout.on('data', text => append(text, false));
        process.stderr.on('data', text => append(text, true));
        process.on('error', error => finish(error));
        process.on('close', code => finish(null, code));
        process.stdin.on('error', () => {});
        process.stdin.end(input);
    });
}

function ensureTrusted(vscode) {
    if (!vscode.workspace.isTrusted) {
        throw new Error('Trust this workspace before running Python tools.');
    }
}

function checkArguments(tool, filePath, profile) {
    return tool === 'refactrail'
        ? ['check', filePath, '--profile', profile, '--output-format', 'json', '--no-cache']
        : ['check', filePath, '--format', 'json'];
}

module.exports = { runPython, ensureTrusted, checkArguments };
