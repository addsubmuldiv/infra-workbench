import {toolText} from '../../shared/toolI18n.ts';

export type SSHLogin = {id: string; user: string | null};
export type SSHLoginSettings = {
  accounts: SSHLogin[];
  default_account_id: string;
  interactive_account_id: string | null;
};
export type SSHLoginHost = {
  id: string;
  target: string;
  user?: string | null;
  ssh_logins?: SSHLoginSettings;
  ssh_account_id?: string;
};

export function pinSSHLogin<T extends SSHLoginHost>(host: T, accountId?: string): T {
  const settings = host.ssh_logins;
  const id = accountId ?? host.ssh_account_id ?? settings?.interactive_account_id ?? settings?.default_account_id;
  if (!id || id === host.ssh_account_id) return host;
  const account = settings?.accounts.find(item => item.id === id);
  return {...host, ssh_account_id: id, user: account?.user ?? null};
}

export function sshWindowLabel(host: SSHLoginHost) {
  return host.ssh_account_id && host.user ? host.user + '@' + host.target : host.target;
}

export function sshAccountUrl(url: string, accountId?: string) {
  if (!accountId) return url;
  return url + (url.includes('?') ? '&' : '?') + 'ssh_account_id=' + encodeURIComponent(accountId);
}

export function sshAccountFetch(accountId?: string): typeof fetch {
  return (input, init) => fetch(typeof input === 'string' ? sshAccountUrl(input, accountId) : input, init);
}

export async function sshLoginRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {'X-IWB': '1', 'Content-Type': 'application/json'},
    cache: 'no-store',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? toolText(data.detail) : String(response.status));
  return data as T;
}
