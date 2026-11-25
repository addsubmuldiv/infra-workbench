import React, {useEffect, useState} from 'react';
import {KeyRound, Plus} from 'lucide-react';
import {t, useLocale} from './i18n';
import {ModalDialog} from './ModalDialog';
import {sshAccountUrl, sshLoginRequest, type SSHLogin, type SSHLoginSettings} from './sshLogins';
import './sshAccounts.css';

type Account = SSHLogin & {password_saved: boolean | null; can_remember: boolean; error?: string | null};
type Settings = Omit<SSHLoginSettings, 'accounts'> & {accounts: Account[]};
type Edit = {kind: 'add'} | {kind: 'password' | 'remove' | 'forget'; account: Account};

function label(account: SSHLogin) {
  return account.user ?? t('使用 SSH 配置账号', 'Use SSH config user');
}

export function SSHAccountsDialog({host, close, updated}: {
  host: {id: string; target: string};
  close: () => void;
  updated: () => Promise<void>;
}) {
  useLocale();
  const [settings, setSettings] = useState<Settings>();
  const [machine, setMachine] = useState('');
  const [interactive, setInteractive] = useState('');
  const [edit, setEdit] = useState<Edit>();
  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const base = '/api/hosts/' + encodeURIComponent(host.id);
  const endpoint = base + '/ssh-accounts';

  useEffect(() => {
    let active = true;
    sshLoginRequest<Settings>(endpoint).then(value => {
      if (!active) return;
      setSettings(value);
      setMachine(value.default_account_id);
      setInteractive(value.interactive_account_id ?? '');
    }).catch(err => {if (active) setError(String(err.message ?? err))});
    return () => {active = false};
  }, [endpoint]);

  function startEdit(next?: Edit) {
    setEdit(next);
    setUser('');
    setPassword('');
    setError('');
  }

  async function act(operation: () => Promise<void>) {
    if (pending) return;
    setPending(true);
    setError('');
    try { await operation() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setPending(false) }
  }

  function savePreferences() {
    void act(async () => {
      await sshLoginRequest(endpoint + '/preferences', 'PUT', {
        default_account_id: machine,
        interactive_account_id: interactive || null,
      });
      await updated();
      close();
    });
  }

  function saveAccount(event: React.FormEvent) {
    event.preventDefault();
    if (!edit || !settings) return;
    void act(async () => {
      if (edit.kind === 'add') {
        await sshLoginRequest(endpoint, 'POST', {user: user.trim(), password});
      } else if (edit.kind === 'remove') {
        await sshLoginRequest(endpoint + '/' + encodeURIComponent(edit.account.id), 'DELETE');
      } else {
        const path = sshAccountUrl(base + '/ssh-password', edit.account.id);
        if (edit.kind === 'password') await sshLoginRequest(path, 'POST', {password});
        else await sshLoginRequest(path, 'DELETE');
      }
      startEdit();
      const saved = await sshLoginRequest<Settings>(endpoint);
      setSettings(saved);
      if (!saved.accounts.some(account => account.id === machine)) setMachine(saved.default_account_id);
      if (interactive && !saved.accounts.some(account => account.id === interactive)) {
        setInteractive(saved.interactive_account_id ?? '');
      }
      await updated();
    });
  }

  const listed = settings?.accounts ?? [];
  const chosenDefault = listed.find(account => account.id === machine);
  const missingInteractive = interactive && !listed.some(account => account.id === interactive);
  const add = edit?.kind === 'add';
  const changePassword = edit?.kind === 'password';
  const writePassword = add || changePassword;
  const canRemember = listed.some(account => account.can_remember);
  const explanation = edit?.kind === 'remove'
    ? t('移除此账号及保存的 SSH 密码？', 'Remove this account and its saved SSH password?')
    : t('删除此账号保存的 SSH 密码？', 'Delete the saved SSH password for this account?');

  return <ModalDialog className="modal ssh-accounts-modal" labelledBy="ssh-accounts-title"
    onDismiss={() => {if (!pending) close()}}>
    <div className="modal-header">
      <h2 id="ssh-accounts-title">{host.target} · {t('SSH 账号', 'SSH accounts')}</h2>
      <div className="ssh-account-actions">
        <button type="button" className="secondary" onClick={close} disabled={pending}>{t('取消', 'Cancel')}</button>
        <button type="button" className="primary" onClick={savePreferences} disabled={pending || !settings || !!edit}>{t('保存', 'Save')}</button>
      </div>
    </div>
    {!settings && !error && <p role="status">{t('正在读取 SSH 账号…', 'Loading SSH accounts…')}</p>}
    {settings && <>
      <div className="ssh-account-preferences">
        <label className="form-label">
          {t('机器默认账号', 'Machine default account')}
          <select data-dialog-focus value={machine} onChange={event => setMachine(event.target.value)} disabled={pending}>
            {listed.map(account => <option key={account.id} value={account.id}>{label(account)}</option>)}
          </select>
          <small>{t('用于助手、资源采集和新建隧道', 'Used for the assistant, monitoring, and new tunnels')}</small>
        </label>
        <label className="form-label">
          {t('终端与文件', 'Terminal and files')}
          <select value={interactive} onChange={event => setInteractive(event.target.value)} disabled={pending}>
            {missingInteractive && <option value={interactive} disabled>{t('账号已删除，请重新选择', 'Account removed. Choose another account.')}</option>}
            <option value="">{t('跟随机器默认账号', 'Use machine default')}{chosenDefault ? ' (' + label(chosenDefault) + ')' : ''}</option>
            {listed.map(account => <option key={account.id} value={account.id}>{label(account)}</option>)}
          </select>
          <small>{t('用于新开的终端和文件窗口', 'Used for new terminal and file windows')}</small>
        </label>
      </div>
      <div className="ssh-account-list-heading">
        <strong>{t('已保存账号', 'Saved accounts')}</strong>
        <button type="button" className="secondary compact" disabled={pending || !canRemember} onClick={() => startEdit({kind: 'add'})}>
          <Plus size={15}/>{t('添加账号', 'Add account')}
        </button>
      </div>
      <ul className="ssh-account-list">
        {listed.map(account => <li key={account.id}>
          <div>
            <strong>{label(account)}</strong>
            <small>{account.password_saved === true ? t('密码已保存', 'Password saved') : account.password_saved === false
              ? t('未保存密码', 'No saved password') : t('未能读取密码状态', 'Password status unavailable')}</small>
          </div>
          <div className="ssh-account-actions">
            <button type="button" className="secondary compact" disabled={pending || !account.can_remember} onClick={() => startEdit({kind: 'password', account})}>
              <KeyRound size={14}/>{account.password_saved ? t('改密码', 'Change saved password') : t('保存密码', 'Save password')}
            </button>
            {account.password_saved && <button type="button" className="secondary compact" disabled={pending} onClick={() => startEdit({kind: 'forget', account})}>
              {t('清除密码', 'Forget password')}
            </button>}
            {account.id !== settings.default_account_id && <button type="button" className="secondary compact" disabled={pending} onClick={() => startEdit({kind: 'remove', account})}>
              {t('移除账号', 'Remove account')}
            </button>}
          </div>
        </li>)}
      </ul>
      {!canRemember && <p className="subtle">{t('此系统暂不支持保存 SSH 密码。', 'Saving SSH passwords is unavailable on this system.')}</p>}
    </>}
    {edit && <form className="ssh-account-editor" onSubmit={saveAccount}>
      <strong>{add ? t('添加账号', 'Add account') : label(edit.account)}</strong>
      {add && <label className="form-label">{t('用户名', 'Username')}
        <input value={user} onChange={event => setUser(event.target.value)} required maxLength={100} autoComplete="off" disabled={pending}/>
      </label>}
      {writePassword ? <label className="form-label">{t('SSH 登录密码', 'SSH login password')}
        <input type="password" value={password} onChange={event => setPassword(event.target.value)} required maxLength={2048} autoComplete="off" disabled={pending}/>
      </label> : <p>{explanation}</p>}
      <div className="modal-footer">
        <button type="button" className="secondary" disabled={pending} onClick={() => startEdit()}>{t('返回', 'Back')}</button>
        <button type="submit" className="primary" disabled={pending}>{writePassword ? t('验证并保存', 'Verify and save') : t('确认删除', 'Confirm removal')}</button>
      </div>
    </form>}
    {error && <p className="connection-error" role="alert">{error}</p>}
  </ModalDialog>;
}
