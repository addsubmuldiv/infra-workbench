import {useSyncExternalStore} from 'react';
import {t,useLocale} from './i18n';
import {workspaceStorage} from './workspaceState';
import {IMAGES_KEY,readImagesEnabled} from './terminalImages';
const subscribe=(fn:()=>void)=>workspaceStorage.subscribe(IMAGES_KEY,fn);
const snapshot=()=>readImagesEnabled(workspaceStorage);
export default function TerminalImageSettings(){
 useLocale();const enabled=useSyncExternalStore(subscribe,snapshot,snapshot);
 return <label title={t('显示 SIXEL / iTerm 内嵌 PNG、JPEG、GIF；每张最多 200 万像素，每个终端缓存 16 MB。Ctrl/⌘ 单击独占一行的压缩包路径可填入解压命令，需按 Enter 执行。','Show SIXEL / iTerm inline PNG, JPEG, GIF; 2M pixels per image, 16 MB cache per terminal. Ctrl/⌘ click a standalone archive path to fill an extraction command; press Enter to run.')}><input type="checkbox" checked={enabled} onChange={e=>workspaceStorage.setItem(IMAGES_KEY,String(e.target.checked))}/>{t('终端图片','Terminal images')}</label>;
}
