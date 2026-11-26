export type Page='overview'|'precision'|'reservations'|'history'|'settings'|'assistant';
const pages:Page[]=['overview','precision','reservations','history','settings','assistant'];
export function pageFromHash(hash:string):Page{
  const page=hash.replace(/^#/,'').split('?')[0] as Page;
  return pages.includes(page)?page:'overview';
}
export type HostLocation={hostId:string;devices:string[]};
export function hostLocationFromHash(hash:string):HostLocation|null{
  if(!hash.startsWith('#overview?'))return null;
  const query=new URLSearchParams(hash.slice(hash.indexOf('?')+1)),hostId=query.get('host');
  if(!hostId||hostId.length>253)return null;
  return {hostId,devices:[...new Set(query.getAll('device').filter(id=>id.length>0&&id.length<=253))].slice(0,64)};
}
export function notificationLocation(value?:string):string{
  if(value?.startsWith('#reservations?')){
    const query=new URLSearchParams(value.slice(value.indexOf('?')+1)),id=query.get('group');
    if(id&&/^[a-zA-Z0-9_-]{1,128}$/.test(id)&&[...query.keys()].every(key=>key==='group'))return '#reservations?group='+encodeURIComponent(id);
  }
  return value&&hostLocationFromHash(value)?value:'#reservations';
}
