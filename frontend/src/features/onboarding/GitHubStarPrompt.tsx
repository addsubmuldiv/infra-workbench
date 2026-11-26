import React, {useEffect, useState, useSyncExternalStore} from 'react';
import {Star, X} from 'lucide-react';
import {t, useLocale} from '../../shared/i18n';
import {UI_GITHUB_STAR_HISTORY_POLL_MS, UI_GITHUB_STAR_IDLE_MS} from '../../internalDefaults';
import {withRequestTimeout} from '../../shared/requests';
import {workspaceStorage} from '../../workspace/workspaceState';
import './githubStarPrompt.css';

const dismissalKey = 'workspace:github-star-prompt-dismissed:v1';
const subscribe = (listener: () => void) => workspaceStorage.subscribe(dismissalKey, listener);
const isDismissed = () => workspaceStorage.getItem(dismissalKey) === 'true';
const dismiss = () => workspaceStorage.setItem(dismissalKey, 'true');
const activityEvents = ['pointerdown', 'keydown', 'wheel', 'focus', 'blur'] as const;
const isForeground = () => document.visibilityState === 'visible' && document.hasFocus();

export function GitHubStarPrompt() {
  useLocale();
  const dismissed = useSyncExternalStore(subscribe, isDismissed);
  const [hasHistory, setHasHistory] = useState(false);
  const [idle, setIdle] = useState(false);

  useEffect(() => {
    if (dismissed || hasHistory) return;
    const controller = new AbortController();
    const params = new URLSearchParams({timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'});
    let pending = false;
    const check = async () => {
      if (pending || document.visibilityState !== 'visible') return;
      pending = true;
      try {
        const result = await withRequestTimeout(8000, async signal => {
          const response = await fetch(`/api/resource-history/availability?${params}`, {
            headers: {'X-IWB': '1'}, cache: 'no-store', signal,
          });
          return response.ok ? await response.json() : null;
        }, controller.signal);
        if (!controller.signal.aborted && result?.has_two_days === true) setHasHistory(true);
      } catch {
        // An unavailable history check leaves the prompt hidden until the next check.
      } finally {
        pending = false;
      }
    };
    void check();
    const timer = window.setInterval(check, UI_GITHUB_STAR_HISTORY_POLL_MS);
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', check);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener('focus', check);
      document.removeEventListener('visibilitychange', check);
    };
  }, [dismissed, hasHistory]);

  useEffect(() => {
    if (dismissed || !hasHistory || idle) return;
    let timer: number | undefined;
    const restart = () => {
      window.clearTimeout(timer);
      if (isForeground()) {
        timer = window.setTimeout(() => {
          if (isForeground()) setIdle(true);
        }, UI_GITHUB_STAR_IDLE_MS);
      }
    };
    for (const event of activityEvents) window.addEventListener(event, restart, {capture: true, passive: true});
    document.addEventListener('visibilitychange', restart);
    restart();
    return () => {
      window.clearTimeout(timer);
      for (const event of activityEvents) window.removeEventListener(event, restart, true);
      document.removeEventListener('visibilitychange', restart);
    };
  }, [dismissed, hasHistory, idle]);

  if (dismissed || !hasHistory || !idle) return null;

  return <aside className="github-star-prompt" aria-labelledby="github-star-prompt-title">
    <h2 id="github-star-prompt-title"><Star size={16} aria-hidden="true"/>{t('喜欢 Infra Workbench 吗？', 'Enjoying Infra Workbench?')}</h2>
    <p>{t('欢迎在 GitHub 上给项目加颗星。', 'Give the project a star on GitHub.')}</p>
    <button type="button" className="icon-button github-star-close" aria-label={t('关闭 GitHub 加星提示', 'Close GitHub star prompt')} onClick={dismiss}><X size={15}/></button>
    <div className="github-star-actions">
      <button type="button" className="text-button" onClick={dismiss}>{t('忽略', 'Dismiss')}</button>
      <a className="primary" href="https://github.com/addsubmuldiv/infra-workbench" target="_blank" rel="noopener noreferrer" onClick={dismiss}>{t('在 GitHub 上加星', 'Star on GitHub')}</a>
    </div>
  </aside>;
}
