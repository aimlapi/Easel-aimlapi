import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/components/SettingsPanel.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('SettingsPanel.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declarations = new Map();

function collect(node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
    declarations.set(node.name.text, node);
  }
  ts.forEachChild(node, collect);
}

collect(parsed);

function compile(expression) {
  return ts.transpileModule(expression, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
}

function value(name) {
  const node = declarations.get(name);
  assert.ok(node, `${name} is declared`);
  return runInNewContext(compile(`(${node.initializer.getText(parsed)});`));
}

function addAimlapi(rows) {
  const node = declarations.get('addAimlapi');
  assert.ok(node, 'addAimlapi is declared');
  let next;
  const callback = runInNewContext(compile(`(${node.initializer.getText(parsed)});`), {
    AIMLAPI_BASE_URL: value('AIMLAPI_BASE_URL'),
    AIMLAPI_DEFAULT_MODEL: value('AIMLAPI_DEFAULT_MODEL'),
    setChatRows: (update) => { next = JSON.parse(JSON.stringify(update(rows))); },
  });
  callback();
  return next;
}

test('AI/ML API preset row targets the fixed OpenAI-compatible endpoint', () => {
  const rows = addAimlapi([{ slot: 'openai', role: '主' }]);
  assert.equal(rows.length, 2);
  const preset = rows[1];
  assert.equal(preset.slot, 'aimlapi');
  assert.equal(preset.name, 'AI/ML API');
  assert.equal(preset.baseUrl, 'https://api.aimlapi.com/v1');
  assert.equal(preset.model, 'openai/gpt-4.1-mini');
  assert.equal(preset.role, '备', 'adding the preset must not take over the primary route');
  assert.equal(rows[0].role, '主');
});

test('AI/ML API preset is added only once', () => {
  const rows = addAimlapi([{ slot: 'aimlapi', role: '备' }]);
  assert.equal(rows.length, 1);
});

test('AI/ML API preset base URL is not editable in the panel', () => {
  assert.match(source, /aimlapi:\s*\{\s*model:\s*true,\s*base:\s*false\s*\}/);
});
