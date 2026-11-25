import {i18nMock} from './i18n-mock.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as sshLogins from '../src/sshLogins.ts';

function harness(t, {fail = false} = {}) {
  const values = [], effects = [], deps = [], calls = [];
  let slot = 0, tree, closed = 0, updated = 0, saved = true;
  const react = {
    createElement: (type, props, ...children) => ({type, props: {...props, children}}),
    useState: initial => {
      const i = slot++;
      if (!(i in values)) values[i] = typeof initial === 'function' ? initial() : initial;
      return [values[i], value => {values[i] = typeof value === 'function' ? value(values[i]) : value}];
    },
    useEffect: (fn, next) => {
      const i = slot++;
      if (!deps[i] || next.some((value, j) => value !== deps[i][j])) {effects.push(fn); deps[i] = next}
    },
  };
  const fetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({url, ...options});
    if (fail && options.method === 'POST') return {ok: false, json: async () => ({detail: '验证失败'})};
    if (options.method === 'DELETE') saved = false;
    return {ok: true, json: async () => ({
      accounts: [{id: 'original', user: 'root', can_remember: true, password_saved: saved},
        {id: 'personal', user: 'alice', can_remember: true, password_saved: false}],
      default_account_id: 'original', interactive_account_id: null,
    })};
  };
  t.after(() => {globalThis.fetch = fetch});
  const source = fs.readFileSync(new URL('../src/SSHAccountsDialog.tsx', import.meta.url), 'utf8');
  const js = ts.transpileModule(source, {
    compilerOptions: {module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true},
  }).outputText;
  const exports = {};
  new Function('require', 'exports', js)(name => i18nMock(name) ?? (name === 'react' ? react : name === './sshLogins' ? sshLogins : {}), exports);
  const host = {id: 'example', target: 'example'};
  const render = () => {
    slot = 0;
    tree = exports.SSHAccountsDialog({host, close: () => closed++, updated: async () => updated++});
    for (const effect of effects.splice(0)) effect();
  };
  const nodes = node => !node || typeof node !== 'object' ? []
    : [node, ...(node.props?.children ?? []).flat(Infinity).flatMap(child => nodes(child))];
  const find = predicate => nodes(tree).find(predicate);
  const settle = () => new Promise(resolve => setImmediate(resolve));
  return {
    render, find, calls, get closed() {return closed}, get updated() {return updated},
    async ready() {render(); await settle(); render()},
    click(label) {find(node => node.type === 'button' && node.props.children.includes(label)).props.onClick(); render()},
    change(type, value) {find(node => node.type === type).props.onChange({target: {value}}); render()},
    async submit() {find(node => node.type === 'form').props.onSubmit({preventDefault(){}}); await settle(); render()},
    settle,
  };
}

test('password update validates the selected account and clears the input', async t => {
  const h = harness(t);
  await h.ready();
  h.click('改密码');
  h.change('input', 'example-password');
  await h.submit();
  const post = h.calls.find(call => call.method === 'POST');
  assert.equal(post.url, '/api/hosts/example/ssh-password?ssh_account_id=original');
  assert.equal(JSON.parse(post.body).password, 'example-password');
  assert.equal(post.headers['X-IWB'], '1');
  assert.equal(h.find(node => node.type === 'input'), undefined);
  assert.equal(h.updated, 1);
});

test('failed verification keeps the password form open for correction', async t => {
  const h = harness(t, {fail: true});
  await h.ready();
  h.click('改密码');
  h.change('input', 'example-wrong-password');
  await h.submit();
  assert.equal(h.find(node => node.type === 'input').props.value, 'example-wrong-password');
  assert.ok(h.find(node => node.props?.role === 'alert'));
});

test('forgetting a password affects only the selected login and refreshes the list', async t => {
  const h = harness(t);
  await h.ready();
  h.click('清除密码');
  await h.submit();
  const deletion = h.calls.find(call => call.method === 'DELETE');
  assert.equal(deletion.url, '/api/hosts/example/ssh-password?ssh_account_id=original');
  assert.equal(h.updated, 1);
});

test('machine and window account preferences apply only after Save', async t => {
  const h = harness(t);
  await h.ready();
  h.change('select', 'personal');
  assert.equal(h.calls.length, 1);
  h.click('保存');
  await h.settle();
  const save = h.calls.find(call => call.method === 'PUT');
  assert.deepEqual(JSON.parse(save.body), {default_account_id: 'personal', interactive_account_id: null});
  assert.equal(h.closed, 1);
});
