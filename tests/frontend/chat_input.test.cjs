'use strict';

// Zero-dependency regression for the "failed ask clears input" bug.
// Run from project root: node --test tests/frontend/chat_input.test.cjs

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const appSource = fs.readFileSync(
    path.resolve(__dirname, '../../frontend/js/app.js'),
    'utf8'
);

function createHarness({ response, rejection, question = '请解释 AVL 树旋转' }) {
    const calls = {
        questions: [],
        errors: [],
        history: [],
        scopes: [],
        answers: [],
        autoResize: 0
    };
    const sandbox = {
        document: {
            // app.js registers the DOMContentLoaded callback at load time.
            // Keep it dormant: exercise real methods on a lightweight fake instance.
            addEventListener: () => {}
        },
        window: {},
        console,
        performance: { now: () => 1000 },
        apiClient: {
            async ask(q) {
                calls.questions.push(q);
                if (rejection) throw rejection;
                return response;
            }
        }
    };

    vm.runInNewContext(
        appSource + '\n;globalThis.ChatAppUnderTest = ChatApp;',
        sandbox,
        { filename: 'frontend/js/app.js' }
    );

    const app = Object.create(sandbox.ChatAppUnderTest.prototype);
    const input = {
        value: question,
        disabled: false,
        focus: () => {}
    };
    app.elements = {
        questionInput: input,
        submitBtn: { disabled: false },
        answerSection: { classList: { contains: () => false } },
        questionDisplayContent: { textContent: '' }
    };
    app.isLoading = false;
    app.currentAnswer = null;
    app.currentSources = null;
    app.currentLatency = null;
    app.currentMode = '';
    app.currentOutOfScope = false;
    app.hideAllSections = () => {};
    app.showLoading = () => {};
    app.hideLoading = () => {};
    app.hideError = () => {};
    app.showError = (code, message) => calls.errors.push({ code, message });
    app.showRequestError = (err) => calls.errors.push(err);
    app.showAnswer = (answer) => calls.answers.push(answer);
    app.showScopeNotice = (value) => calls.scopes.push(value);
    app.showSources = () => {};
    app.addHistory = (entry) => calls.history.push(entry);
    app.autoResizeTextarea = () => { calls.autoResize += 1; };
    app.updateConnectionStatus = () => {};
    return { app, input, calls };
}

test('successful answer clears input and adds history', async () => {
    const { app, input, calls } = createHarness({
        response: {
            success: true,
            data: {
                answer: 'AVL 通过旋转调整树高',
                sources: [],
                mode: 'qa',
                out_of_scope: false,
                latency_ms: { retrieval: 10, rerank: 2, generation: 30, total: 42 }
            }
        }
    });
    await app.handleSubmit();
    assert.equal(input.value, '');
    assert.equal(calls.autoResize, 1);
    assert.equal(calls.history.length, 1);
    assert.equal(calls.answers.length, 1);
    assert.equal(input.disabled, false);
});

test('business error (HTTP 200, success=false) keeps the question for retry', async () => {
    const question = '这段代码为什么出错？';
    const { app, input, calls } = createHarness({
        question,
        response: {
            success: false,
            data: null,
            error: { code: 'RAG_ERROR', message: '模型调用失败' }
        }
    });
    await app.handleSubmit();
    assert.equal(input.value, question);
    assert.equal(calls.errors.length, 1);
    assert.equal(calls.errors[0].code, 'RAG_ERROR');
    assert.equal(calls.history.length, 0);
    assert.equal(calls.autoResize, 0);
    assert.equal(input.disabled, false);
});

test('network failure keeps the question for retry', async () => {
    const question = '请给我解释快速排序';
    const { app, input, calls } = createHarness({
        question,
        rejection: Object.assign(new Error('connection reset'), { code: 'NETWORK_ERROR' })
    });
    await app.handleSubmit();
    assert.equal(input.value, question);
    assert.equal(calls.errors.length, 1);
    assert.equal(calls.history.length, 0);
    assert.equal(input.disabled, false);
});

test('successful out-of-scope reply still clears input', async () => {
    const { app, input, calls } = createHarness({
        response: {
            success: true,
            data: {
                answer: '当前知识库暂无足够资料',
                sources: [],
                mode: 'qa',
                out_of_scope: true,
                latency_ms: { total: 100 }
            }
        }
    });
    await app.handleSubmit();
    assert.equal(input.value, '');
    assert.equal(calls.history.length, 1);
    assert.equal(calls.history[0].outOfScope, true);
    assert.equal(calls.scopes[0], true);
});
