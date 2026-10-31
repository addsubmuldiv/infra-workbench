export const HOST_CATEGORIES=['全部','GPU','NPU'] as const;
export type HostCategory=typeof HOST_CATEGORIES[number];
type HostEntry={target:string;snapshot:{devices:{kind:string}[]}};

export function filterHosts<T extends HostEntry>(hosts:T[],category:HostCategory,search=''):T[]{
  const query=search.trim().toLowerCase();
  return hosts.filter(host=>host.target.toLowerCase().includes(query)&&
    (category==='全部'||host.snapshot.devices.some(device=>device.kind===category)));
}
