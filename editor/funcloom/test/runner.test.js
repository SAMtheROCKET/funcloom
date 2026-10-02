'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { runPython, ensureTrusted, checkArguments } = require('../runner');

test('untrusted workspaces cannot run Python', () => {
    assert.throws(() => ensureTrusted({ workspace: { isTrusted: false } }), /Trust/);
    ensureTrusted({ workspace: { isTrusted: true } });
});

test('arguments preserve paths containing spaces and shell characters', () => {
    const source = 'C:\\example space\\$(bad);file.py';
    assert.deepEqual(checkArguments('funcloom', source),
        ['check', source, '--format', 'json']);
    assert.deepEqual(checkArguments('refactrail', source, 'strict'),
        ['check', source, '--profile', 'strict', '--output-format', 'json', '--no-cache']);
});

test('runner uses isolated Python, argument arrays and no shell', async () => {
    let actual;
    const result = await runPython('C:\\python path\\python.exe', 'funcloom',
        ['snippet', '-'], 'amount = 1', (executable, args, options) => {
            actual = { executable, args, options };
            const process = new EventEmitter();
            process.stdout = new EventEmitter(); process.stdout.setEncoding = () => {};
            process.stderr = new EventEmitter(); process.stderr.setEncoding = () => {};
            process.stdin = new EventEmitter();
            process.stdin.end = input => {
                assert.equal(input, 'amount = 1');
                queueMicrotask(() => {
                    process.stdout.emit('data', '{"status":"candidate_for_review"}');
                    process.emit('close', 0);
                });
            };
            process.kill = () => {};
            return process;
        });
    assert.equal(actual.options.shell, false);
    assert.equal(actual.options.windowsHide, true);
    assert.deepEqual(actual.args, ['-I', '-m', 'funcloom', 'snippet', '-']);
    assert.equal(result.code, 0);
    assert.equal(JSON.parse(result.output).status, 'candidate_for_review');
});

test('unknown module names are refused', () => {
    assert.throws(() => runPython('python', 'untrusted', []), /Unsupported/);
});

test('a report that wrote nothing is described, a written one is not', () => {
    const { describeRefusal } = require('../extension');
    const refused = JSON.stringify({ status: 'refused', diagnostics: [
        { code: 'MOD006', message: 'Output folder is not empty: out' }] });
    assert.equal(describeRefusal('modularize', refused),
        'Nothing was written (refused). MOD006: Output folder is not empty: out');
    assert.equal(describeRefusal('refine', JSON.stringify({ status: 'written' })), null);
    assert.equal(describeRefusal('snippet', refused), null);
    assert.equal(describeRefusal('modularize', 'not json'), null);
});
