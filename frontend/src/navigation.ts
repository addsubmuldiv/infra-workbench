export type Page='overview'|'connections'|'watch'|'precision'|'reservations'|'settings';
const pages:Page[]=['overview','connections','watch','precision','reservations','settings'];
export function pageFromHash(hash:string):Page{
  const page=hash.replace(/^#/,'') as Page;
  return pages.includes(page)?page:'overview';
}
export function hostSelectionPage(current:Page,direct=false):Page{
  return direct||current!=='connections'?'overview':'connections';
}
