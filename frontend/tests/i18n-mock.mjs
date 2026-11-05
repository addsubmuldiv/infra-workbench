import * as defaults from '../src/internalDefaults.ts';
import * as policy from '../src/internalPolicy.ts';
import * as locale from '../src/i18n.ts';
import * as assistant from '../src/assistantLocale.ts';
import * as tools from '../src/toolI18n.ts';
import * as main from '../src/mainI18n.ts';
import * as labels from '../src/localizedLabels.ts';
export function i18nMock(name){
 if(name.replace(/\.ts$/,'')==='./internalDefaults')return defaults;
 if(name.replace(/\.ts$/,'')==='./internalPolicy')return policy;
 const key=name.replace(/\.ts$/,'');
 if(key==='./mainI18n')return main;
 if(key==='./i18n')return {...locale,useLocale:()=>locale.getLocale()};
 if(key==='./assistantLocale')return assistant;
 if(key==='./toolI18n')return tools;
 if(key==='./localizedLabels')return labels;
}
