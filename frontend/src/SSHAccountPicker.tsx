import React, {useState} from 'react';
import {t, useLocale} from './i18n';
import {ModalDialog} from './ModalDialog';
import {sshLoginRequest, type SSHLoginHost, type SSHLoginSettings} from './sshLogins';

export function SSHAccountPicker({host, tool, close, open}: {
  host: SSHLoginHost & {ssh_logins: SSHLoginSettings};
  tool: 'terminal' | 'files';
  close: () => void;
  open: (accountId: string, settings?: SSHLoginSettings) => void;
}) {
  useLocale();
  const settings = host.ssh_logins;
  const preferred = settings.interactive_account_id ?? settings.default_account_id;
  const available = settings.accounts.some(account => account.id === preferred);
  const [selected, setSelected] = useState(available ? preferred : '');
  const [remember, setRemember] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const action = tool === 'terminal' ? t('打开终端', 'Open terminal') : t('打开文件', 'Open files');
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || pending) return;
    setError('');
    setPending(true);
    try {
      const saved = remember ? await sshLoginRequest<SSHLoginSettings>(
        '/api/hosts/' + encodeURIComponent(host.id) + '/ssh-accounts/interactive',
        'PUT', {interactive_account_id: selected},
      ) : undefined;
      open(selected, saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }

  return <ModalDialog className="modal sudo-modal" labelledBy="ssh-account-picker-title" onDismiss={() => {if (!pending) close()}}>
    <div className="modal-header"><h2 id="ssh-account-picker-title">{host.target} · {t('选择 SSH 账号', 'Choose SSH account')}</h2></div>
    <form onSubmit={submit}>
      {!available && <p className="subtle">{t('记住的账号已被删除，请重新选择。', 'The remembered account was removed. Choose an account to continue.')}</p>}
      <label className="form-label">{t('登录账号', 'SSH account')}
        <select data-dialog-focus value={selected} disabled={pending} onChange={event => setSelected(event.target.value)}>
          {!available && <option value="" disabled>{t('请选择账号', 'Choose an account')}</option>}
          {settings.accounts.map(account => <option key={account.id} value={account.id}>{account.user ?? t('使用 SSH 配置账号', 'Use SSH config user')}</option>)}
        </select>
      </label>
      <label className="form-check"><input type="checkbox" checked={remember} disabled={pending} onChange={event => setRemember(event.target.checked)}/>
        {t('以后打开这台机器的终端和文件都用此账号', 'Use this account for future terminal and file windows on this machine')}
      </label>
      {error && <p className="connection-error" role="alert">{error}</p>}
      <div className="modal-footer">
        <button type="button" className="secondary" disabled={pending} onClick={close}>{t('取消', 'Cancel')}</button>
        <button type="submit" className="primary" disabled={pending || !selected}>{action}</button>
      </div>
    </form>
  </ModalDialog>;
}
