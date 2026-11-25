import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import ts from 'typescript';
import {i18nMock} from './i18n-mock.mjs';

const source = fs.readFileSync(new URL('../src/GitHubStarPrompt.tsx', import.meta.url), 'utf8');
const {outputText} = ts.transpileModule(source, {
  compilerOptions: {module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true},
});

function makePrompt(saved = new Map(), {hasHistory = true, idle = true} = {}) {
  const exports = {};
  const storage = {
    getItem: key => saved.get(key) ?? null,
    setItem: (key, value) => saved.set(key, value),
  };
  let field = 0;
  const modules = {
    react: {
      ...React,
      useEffect: () => {},
      useState: () => [[hasHistory, idle][field++], () => {}],
      useSyncExternalStore: (_subscribe, read) => read(),
    },
    './workspaceState': {workspaceStorage: storage},
  };
  new Function('require', 'exports', outputText)(name => modules[name] ?? i18nMock(name) ?? {}, exports);
  return exports.GitHubStarPrompt;
}

function elements(element) {
  if (!React.isValidElement(element)) return [];
  return [element, ...React.Children.toArray(element.props.children).flatMap(elements)];
}

test('the GitHub prompt needs both two days of history and foreground inactivity', () => {
  assert.equal(makePrompt(new Map(), {hasHistory: false})(), null);
  assert.equal(makePrompt(new Map(), {idle: false})(), null);
  assert.ok(makePrompt()());
});

test('opening, closing, or ignoring the GitHub prompt remembers the choice across windows', () => {
  for (const action of ['关闭 GitHub 加星提示', '忽略', '在 GitHub 上加星']) {
    const saved = new Map();
    const render = makePrompt(saved);
    const button = elements(render()).find(({props}) => props['aria-label'] === action || props.children === action);
    assert.ok(button, action);
    assert.equal(saved.size, 0);
    if (button.type === 'a') {
      assert.equal(button.props.href, 'https://github.com/addsubmuldiv/infra-workbench');
      assert.equal(button.props.target, '_blank');
    }
    button.props.onClick();
    assert.equal(makePrompt(saved)(), null);
  }
});
