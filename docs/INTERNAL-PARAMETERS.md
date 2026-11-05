# 内部数字参数盘点

本次仅定位，不修改数值或运行行为。下表为源码模式扫描的候选项，不保证覆盖所有数字；包含部分协议常量、单位换算和动态表达式，后续需逐项判断，不能全部改成配置。排除了依赖、构建产物、测试和演示数据。

## 建议分组

| 类别 | 主要位置及示例 | 后续注意事项 |
|---|---|---|
| SSH | `backend/ssh.py`：默认连接 20 秒、跳板追加 20 秒、保活 60 秒/3 次、采集命令 35 秒 | 保留 SSH 配置覆盖和取消行为 |
| 启动退出 | `backend/desktop.py` 60 秒；`backend/launcher.py` 默认 90 秒；线程等待 | 分清不同阶段的预算 |
| 采样与历史 | `reservations.py` 采样间隔上限 30 秒；`resource_history.py` 7 天/10000 条；`resource_stats.py` 30 天和新鲜度规则 | 保留未知状态与采样时间 |
| 文件与日志 | `file_ops.py` 文本 1 MiB、复制 64 MiB、1000 项；上传下载 512 MiB；文件夹 10000 项；日志 64 MiB/10000 条 | 优先核对本地与远端 probe 重复限制 |
| 导入与技能 | `server_import.py` 2 MiB/100 行；`skill_service.py` 大小和数量限制；`mcp_skills.py` schema | 同步校验、schema 和界面提示 |
| 助手与模型 | `agent_context.py` 默认上下文 32000；助手模块缓存、调用预算、输出限制 | 区分模型能力、内部默认与用户设置 |
| 界面浮窗 | `floating_layout.py` 尺寸与缩放；前端轮询、提示时长、防抖 | 尺寸与时间分开管理，保留共享偏好 |
| 桌面更新与探测 | `desktop/src-tauri/src/updater.rs` 请求 90 秒、退出等待 45 秒、恢复观察 180 秒；`startup_probe.rs` TCP 探测 150 毫秒 | 保留各阶段安全语义，不能统一缩短 |
| 通知凭据 | `notifications.py` 有效期 120 秒；`macos_credentials.py` 凭据长度上限 | 先确认安全边界用途 |

## 定位明细

行号以盘点时源码为准，单位需结合调用上下文确认。协议版本、单位换算、图形坐标通常留在所属模块。

| 位置 | 当前表达式 |
|---|---|
| `backend/agent_chat.py:251` | `await control['connection'].request('turn/steer',{'threadId':control['thread_id'],'expectedTurnId':control['turn_id'],'input':[{'type':'text','text':text}]},timeout=15)` |
| `backend/agent_context.py:7` | `FALLBACK_CONTEXT = 32000` |
| `backend/agent_query.py:11` | `GIB=1024**3` |
| `backend/agent_read_probe.py:28` | `code=child.wait(timeout=1)` |
| `backend/agent_service.py:46` | `cfg=await asyncio.wait_for(self.ssh.effective(host),timeout=5)` |
| `backend/agent_tools.py:50` | `REFRESH=field('boolean','是否请求更新采样，默认 false；合并同机采集，最多等待 25 秒，保留逐机失败信息。',False)` |
| `backend/app.py:56` | `ROOT = Path(__file__).resolve().parents[1]` |
| `backend/atomic_probe.py:151` | `code=child.wait(timeout=1)` |
| `backend/clusters.py:386` | `rows = self.db.execute('SELECT payload FROM cluster_batches ORDER BY rowid DESC LIMIT 100').fetchall()` |
| `backend/codex_agent.py:173` | `self.binary=binary;self.pending={};self.events=asyncio.Queue(maxsize=2048)` |
| `backend/codex_agent.py:202` | `async def request(self,method,params,timeout=45):` |
| `backend/codex_agent.py:320` | `inventory=await connection.request('mcpServerStatus/list',{'threadId':thread_id},timeout=45)` |
| `backend/codex_agent.py:363` | `await asyncio.wait_for(connection.request('turn/interrupt',{'threadId':chat['codex_thread_id'],'turnId':chat['turns'][-1]['codex_turn_id']},timeout=3),4)` |
| `backend/command_probe.py:13` | `OUTPUT_LIMIT = 1024 * 1024` |
| `backend/command_probe.py:113` | `child.wait(timeout=2)` |
| `backend/command_probe.py:123` | `child.wait(timeout=2)` |
| `backend/core.py:7` | `MIB = 1024 ** 2` |
| `backend/desktop.py:17` | `ROOT = Path(__file__).resolve().parents[1]` |
| `backend/desktop.py:23` | `URL = 'http://127.0.0.1:8765/'` |
| `backend/desktop.py:25` | `BACKEND_STARTUP_TIMEOUT = 60` |
| `backend/desktop.py:66` | `with OPENER.open(Request(URL+'api/'+path), timeout=3) as response:` |
| `backend/desktop.py:75` | `with OPENER.open(request, timeout=3) as response:` |
| `backend/desktop.py:276` | `self.thread.join(timeout=20)` |
| `backend/desktop.py:492` | `stop.set();worker.join(timeout=4)` |
| `backend/desktop_macos.py:21` | `ROOT = Path(__file__).resolve().parents[1]` |
| `backend/desktop_macos.py:224` | `self.runner(args, check=True, timeout=8, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)` |
| `backend/desktop_macos.py:407` | `self.worker.join(timeout=4)` |
| `backend/desktop_runtime.py:78` | `with opener.open(origin+path, timeout=3) as response:` |
| `backend/desktop_runtime.py:97` | `result['feature_checks'] += asyncio.run(asyncio.wait_for(check_ssh(Path(directory)), timeout=15))` |
| `backend/desktop_runtime.py:98` | `result['feature_checks'] += asyncio.run(asyncio.wait_for(check_agent(), timeout=15))` |
| `backend/desktop_runtime.py:126` | `asyncio.run(asyncio.wait_for(check_native_pty(), timeout=10))` |
| `backend/desktop_runtime.py:129` | `thread.join(timeout=10)` |
| `backend/desktop_runtime.py:137` | `thread.join(timeout=10)` |
| `backend/file_ops.py:12` | `TEXT_LIMIT = 1024*1024` |
| `backend/file_ops.py:13` | `COPY_LIMIT = 64*1024*1024` |
| `backend/file_ops.py:14` | `ENTRY_LIMIT = 1000` |
| `backend/file_ops.py:37` | `raw = stream.read(TEXT_LIMIT+1)` |
| `backend/file_ops.py:179` | `if budget[0]>COPY_LIMIT: raise ValueError('复制内容超过 64 MiB，已取消复制')` |
| `backend/file_transfers.py:16` | `MAX_UPLOAD=512*1024*1024` |
| `backend/file_upload_probe.py:8` | `MAX_UPLOAD=512*1024*1024` |
| `backend/files_search.py:77` | `code=process.wait(timeout=2)` |
| `backend/floating_drawing.py:5` | `@lru_cache(maxsize=256)` |
| `backend/floating_drawing.py:15` | `@lru_cache(maxsize=64)` |
| `backend/floating_layout.py:3` | `MIN_SIZE = (220, 190)` |
| `backend/floating_layout.py:4` | `DEFAULT_SIZE = (315, 260)` |
| `backend/floating_layout.py:5` | `DRAW_SCALE = .65` |
| `backend/floating_layout.py:6` | `MAX_SIZE = (520, 480)` |
| `backend/floating_layout.py:16` | `return max(MIN_SIZE[0], min(MAX_SIZE[0], int(width))), max(MIN_SIZE[1], min(MAX_SIZE[1], int(height)))` |
| `backend/floating_monitor.py:14` | `ROOT = Path(__file__).resolve().parents[1]` |
| `backend/floating_monitor.py:16` | `URL = 'http://127.0.0.1:8765/'` |
| `backend/floating_monitor.py:154` | `self.thread.join(timeout=2)` |
| `backend/floating_monitor.py:209` | `app.worker.join(timeout=4)` |
| `backend/floating_monitor.py:263` | `self.inbox = queue.Queue(maxsize=1)` |
| `backend/floating_monitor.py:465` | `with opener.open(URL+'api/state', timeout=3) as response:` |
| `backend/floating_theme.py:7` | `ROOT=Path(__file__).resolve().parents[1]` |
| `backend/floating_theme.py:10` | `@lru_cache(maxsize=1)` |
| `backend/folder_download_probe.py:9` | `MAX_SIZE=512*1024*1024` |
| `backend/folder_download_probe.py:10` | `MAX_ENTRIES=10000` |
| `backend/folder_upload_probe.py:11` | `MAX_UPLOAD=512*1024*1024` |
| `backend/folder_upload_probe.py:12` | `MAX_MANIFEST=1024*1024` |
| `backend/folder_upload_probe.py:13` | `MAX_ENTRIES=10000` |
| `backend/folder_upload_probe.py:56` | `if total>MAX_UPLOAD:raise ValueError('文件夹总大小不能超过 512 MiB')` |
| `backend/folder_upload_probe.py:65` | `if len(file_paths)+len(directories)>MAX_ENTRIES:raise ValueError('文件夹最多支持 10000 项')` |
| `backend/folder_upload_probe.py:67` | `if len(file_paths)+len(directories)>MAX_ENTRIES:raise ValueError('文件夹最多支持 10000 项')` |
| `backend/folder_upload_probe.py:77` | `or type(size) is not int or not 0<=size<=MAX_UPLOAD or not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest)):` |
| `backend/folder_upload_probe.py:90` | `manifest=json.loads(read_line(MAX_MANIFEST+1));files,folders=validate_manifest(manifest)` |
| `backend/launcher.py:14` | `ROOT=Path(__file__).resolve().parents[1]` |
| `backend/launcher.py:15` | `URL='http://127.0.0.1:8765/'` |
| `backend/launcher.py:144` | `def ensure_service(root=ROOT,timeout=90):` |
| `backend/launcher.py:150` | `with opener.open(URL+'api/health',timeout=2) as response:value=json.load(response)` |
| `backend/local_service.py:4` | `def loopback_listening(port=8765,timeout=.1):` |
| `backend/log_download.py:17` | `MAX_DOWNLOAD=512*1024*1024` |
| `backend/log_download.py:42` | `if type(size) is not int or not 0<=size<=MAX_DOWNLOAD: raise ValueError('日志文件大小无效或超过 512 MiB')` |
| `backend/log_reader.py:9` | `MAX_BYTES=64*1024*1024` |
| `backend/log_reader.py:10` | `MAX_RECORDS=10000` |
| `backend/log_reader.py:11` | `MAX_LINE=65536` |
| `backend/log_reader.py:107` | `raw=stream.readline(min(MAX_LINE+1,remaining))` |
| `backend/log_reader.py:110` | `if len(raw)>MAX_LINE: raise ValueError('日志单行过长（超过 64 KiB）')` |
| `backend/macos_credentials.py:6` | `MAX_CREDENTIAL_BYTES = 2560` |
| `backend/mail.py:83` | `kwargs = dict(host=config['host'], port=config['port'], timeout=10)` |
| `backend/mail.py:135` | `last = self.store.db.execute('SELECT status,error,updated FROM mail_outbox ORDER BY updated DESC LIMIT 1').fetchone()` |
| `backend/mail.py:231` | `row = self.store.db.execute("SELECT id,created,payload FROM mail_outbox WHERE status='pending' ORDER BY created LIMIT 1").fetchone()` |
| `backend/mcp_operations.py:17` | `REQUEST_ORIGIN = ContextVar('iwb_mcp_origin', default='http://127.0.0.1:8765')` |
| `backend/mcp_skills.py:54` | `FILES = {'type': 'object', 'minProperties': 1, 'maxProperties': 128,` |
| `backend/mcp_skills.py:56` | `REV = {'type': 'integer', 'minimum': 1}` |
| `backend/mcp_skills.py:57` | `NAME = {'type': 'string', 'pattern': '^[a-z0-9]+(?:-[a-z0-9]+)*$', 'maxLength': 64}` |
| `backend/notifications.py:11` | `MAX_NOTIFICATION_AGE = 120` |
| `backend/remote_probe.py:21` | `done = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=6)` |
| `backend/reservations.py:10` | `MAX_SAMPLE_GAP = 30` |
| `backend/resource_history.py:6` | `RETENTION = 7 * 86400` |
| `backend/resource_history.py:7` | `MAX_EVENTS = 10000` |
| `backend/resource_history.py:109` | `db.execute('DELETE FROM resource_changes WHERE id IN (SELECT id FROM resource_changes ORDER BY id DESC LIMIT -1 OFFSET ?)', (MAX_EVENTS,))` |
| `backend/resource_history.py:126` | `for row in db.execute('SELECT id,created,host_id,alias,kind,payload FROM resource_changes WHERE created>=? AND created<=?'+scope+' ORDER BY id DESC LIMIT 100', (since,now,*scope_args)):` |
| `backend/resource_stats.py:11` | `RETENTION_SECONDS = 30 * 86400` |
| `backend/resource_stats.py:12` | `RULE_VERSION = 1` |
| `backend/resource_stats.py:97` | `previous=db.execute('SELECT id,run_id,fresh_until,devices,status,name,freshness_seconds,COALESCE(last_observed_at,observed_at) FROM resource_observations WHERE host_id=? ORDER BY id DESC LIMIT 1',(host_id,)).fetchone()` |
| `backend/resource_stats.py:116` | `more=db.execute('SELECT 1 FROM resource_observations WHERE fresh_until<? LIMIT 1',(cutoff,)).fetchone() is not None or db.execute('SELECT 1 FROM resource_observation_evidence WHERE observed_at<? LIMIT 1',(cutoff,)).fetchone() is not None` |
| `backend/resource_stats.py:122` | `db=sqlite3.connect(self.database_path,timeout=0.2)` |
| `backend/resource_stats.py:135` | `db=sqlite3.connect(Path(self.database_path).as_uri()+'?mode=ro',uri=True,timeout=1)` |
| `backend/resource_stats.py:151` | `return {host_id for host_id in host_ids if db.execute('SELECT 1 FROM resource_observations WHERE host_id=? LIMIT 1',(host_id,)).fetchone()}` |
| `backend/resource_stats.py:169` | `rows = db.execute('SELECT observed_at,fresh_until,name,status,reason,devices,run_id,id,COALESCE(last_observed_at,observed_at) FROM resource_observations WHERE host_id=? AND observed_at<? AND (observed_at>=? OR id=(SELECT id FROM resource_observations WHERE host_id=? AND observed_at<? ORDER BY observed_at DESC,id DESC LIMI…` |
| `backend/server_import.py:11` | `MAX_FILE=2*1024*1024` |
| `backend/server_import.py:12` | `MAX_ROWS=100` |
| `backend/server_import.py:53` | `if not data or len(data)>MAX_FILE:raise WorkbookError('文件不能为空，且不能超过 2 MiB')` |
| `backend/server_import.py:82` | `if len(rows)>=MAX_ROWS:raise WorkbookError('一次最多导入 100 台服务器，请拆分表格')` |
| `backend/server_import_routes.py:39` | `if len(data)+len(chunk)>MAX_FILE:raise HTTPException(413,'Excel 文件不能超过 2 MiB')` |
| `backend/skill_routes.py:77` | `if len(content)+len(chunk)>UPLOAD_LIMIT:raise HTTPException(413,'导入文件不能超过 2 MiB')` |
| `backend/skill_service.py:19` | `UPLOAD_LIMIT = 2 * 1024 * 1024` |
| `backend/skill_service.py:20` | `TOTAL_LIMIT = 8 * 1024 * 1024` |
| `backend/skill_service.py:21` | `FILE_LIMIT = 1024 * 1024` |
| `backend/skill_service.py:22` | `COUNT_LIMIT = 128` |
| `backend/skill_service.py:23` | `NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')` |
| `backend/skill_service.py:357` | `if len(content)>UPLOAD_LIMIT:raise SkillError('导入文件不能超过 2 MiB')` |
| `backend/skill_service.py:367` | `if len(infos)>COUNT_LIMIT*2:raise SkillError('归档条目过多')` |
| `backend/skill_service.py:379` | `with archive.open(info) as stream:data=stream.read(FILE_LIMIT+1)` |
| `backend/ssh.py:56` | `async def command(self, args, source=None, timeout=15):` |
| `backend/ssh.py:312` | `done = await session.run(command, input=source, timeout=35)` |
| `backend/ssh.py:320` | `return await self.command(self.arguments(host)+[command], source, timeout=35)` |
| `backend/ssh.py:330` | `done = await session.run(command, input=source, timeout=15)` |
| `backend/ssh.py:411` | `done = await conn.run('python3 -', input=install_key_script(public), timeout=15)` |
| `backend/state_changes.py:15` | `async def wait(self, revision, instance, timeout=20):` |
| `backend/store.py:67` | `if self.db.execute('SELECT 1 FROM desktop_outbox WHERE '+condition+' LIMIT 1', limits).fetchone():` |
| `backend/store.py:142` | `'SELECT e.id,e.created,e.host,e.message,d.id,d.url,d.status FROM events e LEFT JOIN desktop_outbox d ON d.event_id=e.id WHERE e.created>=? ORDER BY e.id DESC LIMIT 100',` |
| `backend/sudo.py:10` | `HELPER = '/usr/local/libexec/infra-workbench-process-v1.py'` |
| `backend/sudo.py:11` | `PYTHON = '/usr/bin/python3'` |
| `backend/sudo.py:12` | `PROTOCOL = 'iwb-process-v1'` |
| `backend/terminal_posix.py:130` | `await asyncio.to_thread(self.process.wait,timeout=3)` |
| `backend/terminal_shell.py:141` | `PS0='$(__iwb_before_command)'${PS0-}` |
| `backend/terminal_tmux.py:11` | `def run(*args):return subprocess.run(base+list(args),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=8)` |
| `frontend/src/agentChat.ts:67` | `const timer=setTimeout(finish,delay);signal.addEventListener('abort',finish,{once:true});` |
| `frontend/src/assistantLocale.ts:145` | `"STARTTLS（通常为 587 端口）": "STARTTLS (usually port 587)",` |
| `frontend/src/ChatModelPicker.tsx:32` | `const timer=window.setInterval(()=>void load(),60*60*1000);` |
| `frontend/src/ClusterPanel.tsx:36` | `if(live&&!done)tick=setTimeout(poll,1500);` |
| `frontend/src/ClusterPanel.tsx:38` | `tick=setTimeout(poll,1500);` |
| `frontend/src/ClusterSidebar.tsx:17` | `useEffect(()=>{void load();const tick=setInterval(load,10000);window.addEventListener('clusters-changed',load);return()=>{clearInterval(tick);window.removeEventListener('clusters-changed',load)}},[]);` |
| `frontend/src/DesktopUpdatePanel.tsx:29` | `useEffect(()=>{if(!['checking','downloading','installing'].includes(status.phase))return;const timer=window.setInterval(()=>void updater.run('status'),1000);return()=>clearInterval(timer)},[status.phase]);` |
| `frontend/src/FileBrowser.tsx:73` | `useEffect(()=>{if(!message)return;const timer=setTimeout(()=>setMessage(''),4000);return()=>clearTimeout(timer)},[message]);` |
| `frontend/src/FileBrowser.tsx:74` | `useEffect(()=>{if(transfer?.stage!=='done')return;const timer=setTimeout(()=>setTransfer(null),4000);return()=>clearTimeout(timer)},[transfer?.id,transfer?.stage]);` |
| `frontend/src/FileBrowser.tsx:115` | `const url=URL.createObjectURL(data.blob),link=document.createElement('a');link.href=url;link.download=data.filename;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);` |
| `frontend/src/fileTransfers.ts:14` | `const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve()},ms);` |
| `frontend/src/fileTransfers.ts:24` | `xhr.open('PUT',url);xhr.setRequestHeader('X-IWB','1');xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.responseType='json';xhr.timeout=600000;` |
| `frontend/src/folderUpload.ts:4` | `const MAX_BYTES=512*1024*1024,MAX_ENTRIES=10000;` |
| `frontend/src/folderUpload.ts:16` | `if(bytes>MAX_BYTES)throw new Error(tt("文件夹总大小不能超过 512 MiB"));` |
| `frontend/src/folderUpload.ts:19` | `if(files.size+dirs.size>MAX_ENTRIES)throw new Error(tt("文件夹最多支持 10000 项"));` |
| `frontend/src/folderUpload.ts:26` | `if(files.length>MAX_ENTRIES)throw new Error(tt("文件夹最多支持 10000 项"));` |
| `frontend/src/folderUpload.ts:37` | `if(signal.aborted)throw aborted();if(++entries>MAX_ENTRIES)throw new Error(tt("文件夹最多支持 10000 项"));` |
| `frontend/src/folderUpload.ts:40` | `else{const file=await entry.getFile();if(signal.aborted)throw aborted();bytes+=file.size;if(bytes>MAX_BYTES)throw new Error(tt("文件夹总大小不能超过 512 MiB"));selection.files.push({path,file})}` |
| `frontend/src/folderUpload.ts:51` | `if(body.size>MAX_BYTES)throw new Error(tt("文件夹及清单总大小不能超过 512 MiB"));` |
| `frontend/src/GroupReservations.tsx:20` | `useEffect(()=>{void load();const timer=setInterval(()=>void load(),5000);const hash=()=>setExpanded(new URLSearchParams(location.hash.split('?')[1]??'').get('group'));window.addEventListener('hashchange',hash);return()=>{clearInterval(timer);window.removeEventListener('hashchange',hash)}},[refreshKey]);` |
| `frontend/src/latestUpdate.ts:2` | `export function latestUpdate<T>(render:(value:T)=>void,{schedule=(fn:()=>void)=>setTimeout(fn,100),cancel=clearTimeout}:{schedule?:(fn:()=>void)=>ReturnType<typeof setTimeout>;cancel?:(id:ReturnType<typeof setTimeout>)=>void}={}){` |
| `frontend/src/MailSettingsPage.tsx:21` | `<div className="settings-fieldset"><h3>{ui("发件服务器")}</h3><div className="settings-server"><label className="form-label">{ui("SMTP 服务器")}<input aria-label={ui("SMTP 服务器")} required={form.enabled} placeholder={ui("填写邮箱服务商提供的 SMTP 地址")} value={form.host} disabled={!!loading} onChange={event=>change('host',event.target…` |
| `frontend/src/main.tsx:190` | `useEffect(()=>{load();const timer=setInterval(load,refreshInterval*1000);return()=>clearInterval(timer)},[refreshInterval]);` |
| `frontend/src/main.tsx:205` | `useEffect(()=>{if(!notice)return;const t=setTimeout(()=>setNotice(''),7000);return()=>clearTimeout(t)},[notice]);` |
| `frontend/src/MermaidDiagram.tsx:22` | `const timer=setTimeout(async()=>{` |
| `frontend/src/modelCache.ts:1` | `export const MODEL_CACHE_TTL=14*24*60*60*1000;` |
| `frontend/src/PrecisionCompare.tsx:95` | `setTimeout(()=>URL.revokeObjectURL(url),60000);` |
| `frontend/src/PrecisionCompare.tsx:103` | `const link=document.createElement('a');link.href=url;link.download='training-precision.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);` |
| `frontend/src/QuickWindow.tsx:31` | `const timer=setInterval(()=>void poll(),500);return()=>{alive=false;clearInterval(timer)};` |
| `frontend/src/ServerImport.tsx:50` | `receive(value);setError('');if(importActive(value))timer=setTimeout(poll,1000);` |
| `frontend/src/ServerImport.tsx:54` | `else timer=setTimeout(poll,2500);` |
| `frontend/src/ServicePanel.tsx:12` | `useEffect(()=>{let alive=true;const load=()=>request(host.id).then(data=>{if(alive)setRules(data)}).catch(e=>{if(alive)setError(String(e.message))});void load();const timer=setInterval(load,3000);return()=>{alive=false;clearInterval(timer)}},[host.id]);` |
| `frontend/src/SkillsSettings.tsx:55` | `const download=()=>{if(!detail)return;void act('export',async()=>{const blob=await exportSkill(detail.name,detail.version);const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=detail.name+'.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})};` |
| `frontend/src/SSHTunnelPanel.tsx:45` | `if(active)timer=setTimeout(load,2000);` |
| `frontend/src/SSHTunnelPanel.tsx:47` | `void load();const clock=setInterval(()=>setNow(Date.now()),1000);` |
| `frontend/src/StandaloneAssistant.tsx:26` | `void poll();const timer=setInterval(()=>void poll(),500);` |
| `frontend/src/StandaloneAssistant.tsx:31` | `receiver.ready();const timer=setInterval(()=>receiver.ready(),1000);` |
| `frontend/src/stateChanges.ts:7` | `const timer=setTimeout(finish,ms);signal.addEventListener('abort',finish,{once:true});` |
| `frontend/src/TerminalCommands.tsx:52` | `const timer=setTimeout(()=>{setPending(null);setMessage(tt("尚未确认保存，请检查终端中的错误提示后重试"))},6000);` |
| `frontend/src/TerminalDock.tsx:266` | `try{const text=prepareTerminalInput(input.text);if(!handles.current[tab.id]?.insert(text)){setHint(tt('无法填入命令；多行命令需要终端支持安全粘贴'));input.reply?.('无法填入命令；多行命令需要终端支持安全粘贴');return}setActive(tab.id);setCollapsed(false);if(dock.current)activateFloatingWindow({currentTarget:dock.current,target:dock.current});setTimeout(()=>han…` |
| `frontend/src/TerminalDock.tsx:276` | `useEffect(()=>{if(!hint)return;const timer=setTimeout(()=>setHint(''),12000);return()=>clearTimeout(timer)},[hint]);` |
| `frontend/src/terminalHighlights.ts:41` | `const schedule=()=>{if(!disposed&&timer===undefined)timer=setTimeout(()=>{timer=undefined;refresh()},100)};` |
| `frontend/src/terminalImages.ts:8` | `export function createImageDecodeGuard(store:(image:{close?:()=>void})=>void,timeout=2000){` |
| `frontend/src/terminalImages.ts:17` | `pending.add(finish);timer=setTimeout(finish,timeout);` |
| `frontend/src/TerminalInsert.tsx:32` | `else items=await new Promise<TerminalTarget[]>((resolve,reject)=>{const port=new BroadcastChannel('iwb-terminal-input:'+channel);const timer=setTimeout(()=>{port.close();reject(Error('无法读取配对终端'))},2000);port.onmessage=event=>{if(event.data?.type==='targets'){clearTimeout(timer);port.close();resolve(event.data.items)}…` |
| `frontend/src/TunnelManager.tsx:27` | `useEffect(()=>{mounted.current=true;let timer:ReturnType<typeof setTimeout>;async function poll(){await refresh();if(mounted.current)timer=setTimeout(poll,2000)}void poll();return()=>{mounted.current=false;clearTimeout(timer)}},[]);` |
| `frontend/src/vscode.ts:13` | `const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve()},ms);` |
| `frontend/src/VSCodeButton.tsx:59` | `TUNNEL_TIMEOUT:['等待 SSH 隧道超过 60 秒。隧道仍由后台管理，可以重试或仍然打开 VS Code。','SSH tunnels did not connect within 60 seconds. They remain managed by the backend. Retry or open VS Code anyway.'],` |
| `frontend/src/workspaceState.ts:28` | `const schedule=(delay=250)=>{if(timer)clearTimeout(timer);timer=setTimeout(()=>{timer=undefined;void flush()},delay)};` |
| `frontend/src/workspaceState.ts:53` | `window.setInterval(()=>{void workspaceStorage.refresh()},1500);` |
| `desktop/src-tauri/src/main.rs:166` | `setTimeout(() => {` |
| `desktop/src-tauri/src/main.rs:168` | `if (!invoke) { pending=false;setTimeout(ready,50);return; }` |
| `desktop/src-tauri/src/main.rs:169` | `invoke('desktop_ready').then(()=>{window.__iwbStartup?.update('frontend',100);window.__iwbStartup?.finish();observer.disconnect()}).catch(()=>{pending=false;setTimeout(ready,100)});` |

## Rust 时间参数补充

测试模块未列入以下补充项。

| 位置 | 当前表达式 |
|---|---|
| `desktop/src-tauri/src/main.rs:50` | `let Ok(client)=reqwest::blocking::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(2)).build() else {return;};` |
| `desktop/src-tauri/src/main.rs:55` | `if updater::installing(&app){std::thread::sleep(Duration::from_secs(2));continue;}` |
| `desktop/src-tauri/src/main.rs:62` | `std::thread::sleep(Duration::from_secs(2));` |
| `desktop/src-tauri/src/main.rs:107` | `.redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(2))` |
| `desktop/src-tauri/src/main.rs:109` | `let deadline=Instant::now()+Duration::from_secs(60);` |
| `desktop/src-tauri/src/main.rs:123` | `std::thread::sleep(Duration::from_millis(300));` |
| `desktop/src-tauri/src/startup_probe.rs:20` | `let listening = listener_present(TcpStream::connect_timeout(&address, Duration::from_millis(150)))?;` |
| `desktop/src-tauri/src/updater.rs:59` | `.timeout(Duration::from_secs(90)).on_before_exit(&#124;&#124;{}).restart_after_install(true).version_comparator(&#124;current,remote&#124;remote.version>current).build().map_err(&#124;e&#124;e.to_string())?;` |
| `desktop/src-tauri/src/updater.rs:102` | `let deadline=Instant::now()+Duration::from_secs(8);` |
| `desktop/src-tauri/src/updater.rs:109` | `std::thread::sleep(Duration::from_millis(50));` |
| `desktop/src-tauri/src/updater.rs:137` | `std::net::TcpStream::connect_timeout(&"127.0.0.1:8765".parse().unwrap(),Duration::from_millis(200)).is_err()` |
| `desktop/src-tauri/src/updater.rs:140` | `let client=reqwest::blocking::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(2)).build().map_err(&#124;e&#124;e.to_string())?;` |
| `desktop/src-tauri/src/updater.rs:143` | `let deadline=Instant::now()+Duration::from_secs(45);` |
| `desktop/src-tauri/src/updater.rs:147` | `std::thread::sleep(Duration::from_millis(300));` |
| `desktop/src-tauri/src/updater.rs:158` | `let client=reqwest::blocking::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(5)).build().map_err(&#124;e&#124;e.to_string())?;` |
| `desktop/src-tauri/src/updater.rs:160` | `let deadline=Instant::now()+Duration::from_secs(60);` |
| `desktop/src-tauri/src/updater.rs:175` | `let deadline=Instant::now()+Duration::from_secs(180);` |
| `desktop/src-tauri/src/updater.rs:182` | `std::thread::sleep(Duration::from_millis(500));` |
| `desktop/src-tauri/src/updater.rs:187` | `std::thread::sleep(Duration::from_millis(100));` |
| `desktop/src-tauri/src/window_fade.rs:82` | `std::thread::sleep(Duration::from_millis(10));` |
