import {i18nMock} from './i18n-mock.mjs';
import * as toolTranslations from '../src/toolI18n.ts';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(fs.readFileSync(new URL('../src/terminalTemplates.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const exports={};new Function('require','exports',code)(name=>name==='./toolI18n.ts'?toolTranslations:i18nMock(name),exports);
const {renderTemplate,variables}=exports;
test('template parameters are single literal shell arguments and missing or multiline values cannot be inserted',()=>{
 assert.deepEqual(variables('echo {{name}} {{name}} {{port}}'),['name','port']);
 assert.equal(renderTemplate('echo {{name}}',{}).command,'');
 assert.equal(renderTemplate('echo {{name}}',{name:'a\nb'}).command,'');
 assert.equal(renderTemplate('python {{script}} --port={{port}}',{script:"a'中文 ; $(touch nope).py",port:'29500'}).command,"python 'a'\\''中文 ; $(touch nope).py' --port='29500'");
});
