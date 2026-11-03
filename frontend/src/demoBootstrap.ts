import {createDemoRuntime,installDemoNetwork} from './demoRuntime';
declare const __IWB_DEMO__:boolean;
export const demoOnlyBuild=typeof __IWB_DEMO__!=='undefined'&&__IWB_DEMO__;
export const isDemo=demoOnlyBuild||new URLSearchParams(location.search).get('demo')==='1';
export const demoRuntime=isDemo?createDemoRuntime():null;
if(demoRuntime){document.documentElement.classList.add('demo-mode');installDemoNetwork(window,demoRuntime);}
