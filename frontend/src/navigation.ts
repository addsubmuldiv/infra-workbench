export type Page='overview'|'connections'|'watch'|'precision';
const pages:Page[]=['overview','connections','watch','precision'];
export function pageFromHash(hash:string):Page{
  const page=hash.replace(/^#/,'') as Page;
  return pages.includes(page)?page:'overview';
}
export function hostSelectionPage(current:Page,direct=false):Page{
  return direct||current!=='connections'?'overview':'connections';
}
