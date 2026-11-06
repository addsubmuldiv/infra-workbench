use std::{collections::HashMap, path::PathBuf, sync::Mutex, time::{Duration, Instant, SystemTime, UNIX_EPOCH}};
use serde::{Deserialize, Serialize};
use tauri::{Manager, WebviewWindow};
use tauri_plugin_updater::{Update, UpdaterExt};

// Serializes native window construction with the transition into installation.
pub static WINDOW_GATE: Mutex<()> = Mutex::new(());

const ENDPOINT: &str = "https://github.com/addsubmuldiv/infra-workbench/releases/latest/download/latest.json";
#[derive(Clone, Serialize)]
pub struct Status {
    supported: bool, current_version: String, phase: String, available_version: Option<String>,
    notes: Option<String>, downloaded_bytes: u64, total_bytes: Option<u64>, last_checked: Option<u64>, error: Option<String>,
}
struct Inner { status: Status, update: Option<Update>, bytes: Option<Vec<u8>>, safety: HashMap<String, Option<bool>> }
pub struct UpdaterState(Mutex<Inner>);
impl Default for UpdaterState {
    fn default() -> Self { Self(Mutex::new(Inner { status: Status { supported: cfg!(windows) && !cfg!(debug_assertions), current_version: env!("CARGO_PKG_VERSION").into(), phase: "idle".into(), available_version: None, notes: None, downloaded_bytes: 0, total_bytes: None, last_checked: None, error: None }, update: None, bytes: None, safety: HashMap::new() })) }
}
pub fn installing(app: &tauri::AppHandle) -> bool { app.state::<UpdaterState>().0.lock().unwrap().status.phase == "installing" }
fn allowed(label: &str, url: &reqwest::Url) -> bool {
    label == "main" && infra_workbench_desktop::is_service_url(url) && !url.query_pairs().any(|(k,v)| k == "tool" || (k == "demo" && v == "1"))
}
fn guard(window: &WebviewWindow) -> Result<(),String> {
    if allowed(window.label(), &window.url().map_err(|e|e.to_string())?) { Ok(()) } else { Err("仅主工作台可更新桌面应用".into()) }
}
fn snapshot(app: &tauri::AppHandle) -> Status { app.state::<UpdaterState>().0.lock().unwrap().status.clone() }
fn fail(app: &tauri::AppHandle, message: String) -> Status {
    let state=app.state::<UpdaterState>(); let mut inner=state.0.lock().unwrap(); inner.status.phase=if inner.update.is_some() && inner.bytes.is_some() {"downloaded"} else {"error"}.into(); inner.status.error=Some(message); inner.status.clone()
}
fn begin_inner(inner: &mut Inner, phase: &str) -> Result<(),String> {
    if !inner.status.supported { return Err("此运行方式不支持自动安装更新，请使用正式安装版".into()); }
    if matches!(inner.status.phase.as_str(), "checking"|"downloading"|"installing") { return Err("更新操作正在进行".into()); }
    match phase {
        "checking" => {
            // A failed fresh check must never retain an older candidate or verified bytes.
            inner.update=None; inner.bytes=None; inner.status.available_version=None; inner.status.notes=None;
            inner.status.downloaded_bytes=0; inner.status.total_bytes=None;
        },
        "downloading" => {
            if inner.update.is_none() { return Err("请先检查可用更新".into()); }
            inner.bytes=None; inner.status.downloaded_bytes=0; inner.status.total_bytes=None;
        },
        "installing" => if inner.update.is_none() || inner.bytes.is_none() { return Err("请先下载并验证更新".into()); },
        _ => return Err("无效的更新操作".into()),
    }
    inner.status.phase=phase.into(); inner.status.error=None; Ok(())
}
fn begin(app: &tauri::AppHandle, phase: &str) -> Result<(),String> {
    begin_inner(&mut app.state::<UpdaterState>().0.lock().unwrap(),phase)
}
#[tauri::command]
pub fn desktop_update_status(window: WebviewWindow) -> Result<Status,String> { guard(&window)?; Ok(snapshot(window.app_handle())) }
#[tauri::command]
pub async fn desktop_update_check(window: WebviewWindow) -> Result<Status,String> {
    guard(&window)?; let app=window.app_handle().clone(); begin(&app,"checking")?;
    let result=async {
        let updater=app.updater_builder().endpoints(vec![ENDPOINT.parse().unwrap()]).map_err(|e|e.to_string())?
            .timeout(Duration::from_secs(90)).on_before_exit(||{}).restart_after_install(true).version_comparator(|current,remote|remote.version>current).build().map_err(|e|e.to_string())?;
        updater.check().await.map_err(|e|e.to_string())
    }.await;
    match result {
        Err(error)=>Ok(fail(&app,format!("检查更新失败：{error}"))),
        Ok(update)=>{ let state=app.state::<UpdaterState>(); let mut inner=state.0.lock().unwrap();
            inner.status.last_checked=Some(SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis() as u64);
            inner.status.available_version=update.as_ref().map(|u|u.version.clone()); inner.status.notes=update.as_ref().and_then(|u|u.body.clone());
            inner.status.phase=if update.is_some(){"available"}else{"idle"}.into(); inner.status.downloaded_bytes=0; inner.status.total_bytes=None;
            inner.bytes=None; inner.update=update; Ok(inner.status.clone()) }
    }
}
#[tauri::command]
pub async fn desktop_update_download(window: WebviewWindow) -> Result<Status,String> {
    guard(&window)?; let app=window.app_handle().clone();
    let update={ let state=app.state::<UpdaterState>(); let mut inner=state.0.lock().unwrap();
        begin_inner(&mut inner,"downloading")?; inner.update.clone().unwrap() };
    let progress=app.clone();
    match update.download(move |chunk,total| { let state=progress.state::<UpdaterState>(); let mut inner=state.0.lock().unwrap(); inner.status.downloaded_bytes+=chunk as u64; inner.status.total_bytes=total; }, ||{}).await {
        Err(error)=>Ok(fail(&app,format!("下载或签名验证失败：{error}"))),
        Ok(bytes)=>{ let state=app.state::<UpdaterState>(); let mut inner=state.0.lock().unwrap(); inner.bytes=Some(bytes); inner.status.phase="downloaded".into(); Ok(inner.status.clone()) }
    }
}
#[tauri::command]
pub fn desktop_update_safety_response(window: WebviewWindow, nonce: String, safe: bool) -> Result<(),String> {
    if !window.url().map(|u|infra_workbench_desktop::is_service_url(&u)).unwrap_or(false) { return Err("不允许的页面".into()); }
    let state=window.state::<UpdaterState>(); let mut inner=state.0.lock().unwrap();
    let key=format!("{}:{nonce}",window.label());
    if let Some(reply)=inner.safety.get_mut(&key) { *reply=Some(safe); Ok(()) } else { Err("更新确认已过期".into()) }
}
fn release_views(app: &tauri::AppHandle) {
    for window in app.webview_windows().values() { let _=window.eval("window.__IWB_DESKTOP_UPDATE_SAFETY__?.(false)"); }
    app.state::<UpdaterState>().0.lock().unwrap().safety.clear();
}
fn safe_views(app: &tauri::AppHandle) -> Result<(),String> {
    let nonce=uuid::Uuid::new_v4().to_string(); let windows=app.webview_windows();
    { let state=app.state::<UpdaterState>(); let mut inner=state.0.lock().unwrap(); inner.safety.clear();
        for label in windows.keys() { inner.safety.insert(format!("{label}:{nonce}"),None); }
    }
    for window in windows.values() {
        let script=format!(r#"(async()=>{{let safe=false;try{{let hook=window.__IWB_DESKTOP_UPDATE_SAFETY__;let result=hook?await hook(true):null;safe=result?.safe===true;}}catch{{}}await window.__TAURI_INTERNALS__.invoke('desktop_update_safety_response',{{nonce:{},safe}});}})()"#,serde_json::to_string(&nonce).unwrap());
        window.eval(script).map_err(|e|e.to_string())?;
    }
    let deadline=Instant::now()+Duration::from_secs(8);
    loop {
        { let state=app.state::<UpdaterState>(); let inner=state.0.lock().unwrap();
            if inner.safety.values().any(|v|*v==Some(false)) { return Err("请先保存所有窗口的文件、关闭活动终端并等待工作区写入完成".into()); }
            if inner.safety.values().all(|v|*v==Some(true)) { return Ok(()); }
        }
        if Instant::now()>=deadline { return Err("部分窗口未确认安全状态，已取消安装。请关闭这些窗口后重试".into()); }
        std::thread::sleep(Duration::from_millis(50));
    }
}
#[derive(Deserialize, PartialEq)]
struct Receipt { token: String, instance: String, pid: u32, executable: PathBuf }
fn data_dir() -> Result<PathBuf,String> {
    std::env::var_os("IWB_DATA").map(PathBuf::from).or_else(||dirs::data_local_dir().map(|p|p.join("InfraWorkbench"))).ok_or("找不到用户数据目录".into())
}
#[cfg(windows)]
struct OwnedProcess(*mut std::ffi::c_void);
// Windows process handles have no thread affinity; ownership still closes exactly once.
#[cfg(windows)] unsafe impl Send for OwnedProcess {}
#[cfg(windows)]
impl OwnedProcess {
    fn open(pid: u32, expected: &std::path::Path) -> Result<Self,String> {
        #[link(name="kernel32")] extern "system" { fn OpenProcess(access:u32,inherit:i32,pid:u32)->*mut std::ffi::c_void; fn QueryFullProcessImageNameW(process:*mut std::ffi::c_void,flags:u32,name:*mut u16,size:*mut u32)->i32; }
        const PROCESS_TERMINATE: u32 = 0x0001;
        let handle=unsafe{OpenProcess(0x00100000|0x1000|PROCESS_TERMINATE,0,pid)};
        if handle.is_null() { return Err("无法核实后台进程身份，未停止任何进程".into()); }
        let process=Self(handle); let mut name=vec![0u16;32768]; let mut size=name.len() as u32;
        if unsafe{QueryFullProcessImageNameW(handle,0,name.as_mut_ptr(),&mut size)}==0 { return Err("无法核实后台程序路径".into()); }
        let actual=PathBuf::from(String::from_utf16_lossy(&name[..size as usize]));
        if actual.canonicalize().ok()!=expected.canonicalize().ok() || expected.canonicalize().is_err() { return Err("后台程序与当前安装目录不匹配，请手动停止后台后更新".into()); }
        Ok(process)
    }
    fn exited(&self)->bool { #[link(name="kernel32")] extern "system" { fn WaitForSingleObject(handle:*mut std::ffi::c_void,time:u32)->u32; } unsafe{WaitForSingleObject(self.0,0)==0} }
    fn terminate(&self) -> Result<(), String> {
        #[link(name = "kernel32")]
        extern "system" {
            fn TerminateProcess(process: *mut std::ffi::c_void, code: u32) -> i32;
        }
        if self.exited() || unsafe { TerminateProcess(self.0, 1) } != 0 || self.exited() {
            return Ok(());
        }
        Err(format!("无法强制退出后台：{}", std::io::Error::last_os_error()))
    }
}
#[cfg(windows)] impl Drop for OwnedProcess { fn drop(&mut self) { #[link(name="kernel32")] extern "system" { fn CloseHandle(handle:*mut std::ffi::c_void)->i32; } unsafe{CloseHandle(self.0);}; } }
fn port_closed() -> bool {
    std::net::TcpStream::connect_timeout(&"127.0.0.1:8765".parse().unwrap(),Duration::from_millis(200)).is_err()
}
fn recover_runtime() -> Result<(),String> {
    let client=reqwest::blocking::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(2)).build().map_err(|e|e.to_string())?;
    if !port_closed() { return Err("服务端口已被使用，未重复启动后台".into()); }
    super::start_runtime()?;
    let deadline=Instant::now()+Duration::from_secs(45);
    loop {
        if super::probe(&client)? { return Ok(()); }
        if Instant::now()>=deadline { return Err("后台未在 45 秒内恢复，请重新打开应用并检查 desktop.log".into()); }
        std::thread::sleep(Duration::from_millis(300));
    }
}
#[cfg(windows)]
fn confirm_force_stop(reason: &str, english: bool) -> bool {
    let (title, warning) = if english {
        ("Force quit and install?", "Forcing the local service to quit may interrupt terminal sessions, transfers, and writes in progress. Select Yes to force quit and continue installing.")
    } else {
        ("强制退出并安装？", "强制退出本机后台可能中断终端、文件传输和正在写入的数据。选择「是」将强制退出并继续安装。")
    };
    rfd::MessageDialog::new()
        .set_level(rfd::MessageLevel::Warning)
        .set_title(title)
        .set_description(format!("{reason}\n\n{warning}"))
        .set_buttons(rfd::MessageButtons::YesNo)
        .show() == rfd::MessageDialogResult::Yes
}

#[cfg(windows)]
fn force_stop_runtime(process: &OwnedProcess, path: &std::path::Path, receipt: &Receipt) -> Result<(), String> {
    if !process.exited() {
        let current = std::fs::read(path).ok().and_then(|bytes| serde_json::from_slice::<Receipt>(&bytes).ok());
        if current.as_ref() != Some(receipt) && !process.exited() {
            return Err("update_shutdown_identity".into());
        }
        process.terminate()?;
    }
    let deadline = Instant::now() + Duration::from_secs(10);
    while Instant::now() < deadline {
        if process.exited() && port_closed() {
            // A killed runtime cannot remove its receipt. The next runtime replaces it.
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Err("update_force_timeout".into())
}
fn stop_owned_runtime(english: bool) -> Result<(),String> {
    let path=data_dir()?.join("desktop-update-control.json");
    let receipt:Receipt=serde_json::from_slice(&std::fs::read(&path).map_err(|_|"后台不是本安装版管理的服务，请手动停止并使用安装包更新")?).map_err(|_|"后台更新凭据无效".to_string())?;
    let expected=std::env::current_exe().map_err(|e|e.to_string())?.parent().ok_or("无法确定安装目录")?.join(if cfg!(windows){"iwb-runtime.exe"}else{"iwb-runtime"});
    if expected.canonicalize().is_err() || expected.canonicalize().ok()!=receipt.executable.canonicalize().ok() || receipt.token.len()<32 || receipt.instance.is_empty() {return Err("后台不属于当前安装目录，未停止任何进程".into());}
    #[cfg(windows)] let process=OwnedProcess::open(receipt.pid,&expected)?;
    #[cfg(not(windows))] return Err("当前平台暂不支持安全停止后台，请使用安装包更新".into());
    #[cfg(windows)] {
        let client=reqwest::blocking::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(5)).build().map_err(|e|e.to_string())?;
        let shutdown = client
            .post(format!("{}api/desktop/update-shutdown", infra_workbench_desktop::SERVICE_URL))
            .bearer_auth(&receipt.token)
            .header("X-IWB", "1")
            .json(&serde_json::json!({"instance": receipt.instance, "executable": receipt.executable}));
        let retry_deadline = Instant::now() + Duration::from_secs(5);
        loop {
            let response = shutdown.try_clone().ok_or("无法重试后台退出请求")?
                .send().map_err(|e| e.to_string())?;
            let status = response.status();
            if status.is_success() {
                break;
            }
            if status != reqwest::StatusCode::CONFLICT {
                return Err(format!("update_shutdown_failed (HTTP {status})"));
            }
            let detail = response.json::<serde_json::Value>().unwrap_or_default();
            let reason = match detail.get("detail").and_then(|value| value.as_str()) {
                Some("Wait for active operations before updating") => "update_shutdown_busy",
                Some("Close active terminals before updating") => "update_shutdown_terminals",
                Some("Wait for file transfers before updating") => "update_shutdown_transfers",
                Some("Desktop runtime identity mismatch") => "update_shutdown_identity",
                _ => "update_shutdown_failed",
            };
            if reason != "update_shutdown_busy" || Instant::now() >= retry_deadline {
                let explanation = match (reason, english) {
                    ("update_shutdown_busy", true) => "The background service still has operations in progress.",
                    ("update_shutdown_busy", false) => "后台仍有操作正在进行。",
                    ("update_shutdown_terminals", true) => "The background service still has active terminals.",
                    ("update_shutdown_terminals", false) => "后台仍有活动终端。",
                    ("update_shutdown_transfers", true) => "The background service still has file transfers in progress.",
                    ("update_shutdown_transfers", false) => "后台仍有文件正在传输。",
                    _ => return Err(reason.into()),
                };
                if confirm_force_stop(explanation, english) {
                    return force_stop_runtime(&process, &path, &receipt);
                }
                return Err(reason.into());
            }
            std::thread::sleep(Duration::from_millis(250));
        }
        let deadline=Instant::now()+Duration::from_secs(60);
        loop {
            let closed=port_closed();
            if !path.exists() && process.exited() && closed {return Ok(());}
            if Instant::now()>=deadline {
                if process.exited() && closed {
                    return match recover_runtime() {
                        Ok(())=>Err("后台已退出，但更新凭据未正常清理；已取消安装并恢复后台".into()),
                        Err(error)=>Err(format!("已取消安装；后台恢复失败：{error}")),
                    };
                }
                let explanation = if english {
                    "The background service did not exit within 60 seconds."
                } else {
                    "后台在 60 秒内未退出。"
                };
                let mut force_error = None;
                if !process.exited() && confirm_force_stop(explanation, english) {
                    match force_stop_runtime(&process, &path, &receipt) {
                        Ok(()) => return Ok(()),
                        Err(error) => force_error = Some(error),
                    }
                }
                // A successful shutdown request cannot be cancelled after the tray has
                // started draining. Keep its exact process handle, never look up/kill a PID.
                let instance=receipt.instance.clone();
                std::thread::spawn(move || {
                    let deadline=Instant::now()+Duration::from_secs(180);
                    while Instant::now()<deadline {
                        if process.exited() {
                            let same_owner=std::fs::read(&path).ok().and_then(|b|serde_json::from_slice::<Receipt>(&b).ok()).map(|r|r.instance==instance).unwrap_or(!path.exists());
                            if same_owner && port_closed() { let _=recover_runtime(); }
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(500));
                    }
                });
                return Err(force_error.unwrap_or_else(|| "后台在 60 秒内未完全退出，已取消安装。若原后台随后退出，会在三分钟内尝试恢复，请稍后重新打开应用".into()));
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    }
}
#[tauri::command]
pub async fn desktop_update_install(window: WebviewWindow, english: Option<bool>) -> Result<Status,String> {
    guard(&window)?; let app=window.app_handle().clone();
    let (update,bytes)={ let _window_gate=WINDOW_GATE.lock().unwrap();
        let state=app.state::<UpdaterState>(); let mut inner=state.0.lock().unwrap();
        begin_inner(&mut inner,"installing")?; (inner.update.clone().unwrap(),inner.bytes.clone().unwrap()) };
    let worker=app.clone();
    let result=tauri::async_runtime::spawn_blocking(move || -> Result<(),String> {
        let confirmed=rfd::MessageDialog::new().set_title("安装桌面更新").set_description(format!("即将安装桌面版本 {}。更新将关闭所有工作台窗口并重启应用。请先保存文件、关闭终端并等待写入完成。是否继续？",update.version)).set_buttons(rfd::MessageButtons::YesNo).show();
        if confirmed!=rfd::MessageDialogResult::Yes {return Err("已取消安装".into());}
        safe_views(&worker)?;
        stop_owned_runtime(english.unwrap_or(false))?;
        if let Err(error)=update.install(bytes) {
            return match recover_runtime() {
                Ok(())=>Err(format!("安装失败，后台已恢复：{error}")),
                Err(recovery)=>Err(format!("安装失败：{error}；后台恢复失败：{recovery}")),
            };
        }
        Ok(())
    }).await.map_err(|e|e.to_string());
    match result { Ok(Ok(()))=>Ok(snapshot(&app)), other=>{release_views(&app); Ok(fail(&app,match other {Ok(Err(e))|Err(e)=>e,_=>unreachable!()}))} }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn fresh_check_discards_previous_download_even_when_it_later_fails() {
        let state=UpdaterState::default(); let mut inner=state.0.lock().unwrap();
        inner.status.supported=true; inner.bytes=Some(vec![1,2]); inner.status.available_version=Some("99.0.0".into()); inner.status.phase="error".into();
        begin_inner(&mut inner,"checking").unwrap();
        assert!(inner.bytes.is_none()); assert!(inner.update.is_none()); assert!(inner.status.available_version.is_none());
        inner.status.phase="error".into(); assert!(begin_inner(&mut inner,"installing").is_err());
    }
    #[test] fn active_operations_cannot_be_replaced_and_missing_data_cannot_install() {
        let state=UpdaterState::default(); let mut inner=state.0.lock().unwrap(); inner.status.supported=true;
        for phase in ["checking","downloading","installing"] {
            inner.status.phase=phase.into(); assert!(begin_inner(&mut inner,"checking").is_err()); assert!(begin_inner(&mut inner,"installing").is_err());
        }
        inner.status.phase="idle".into(); assert!(begin_inner(&mut inner,"installing").is_err()); assert!(begin_inner(&mut inner,"downloading").is_err());
    }
    #[test] fn update_requires_main_real_service() {
        for (label,url) in [("main","http://127.0.0.1:8765/"),("main","http://127.0.0.1:8765/?demo=0")] {assert!(allowed(label,&url.parse().unwrap()));}
        for (label,url) in [("quick-1","http://127.0.0.1:8765/"),("main","http://127.0.0.1:8765/?demo=1"),("main","http://127.0.0.1:8765/?tool=terminal"),("main","https://evil.test/")] {assert!(!allowed(label,&url.parse().unwrap()));}
    }
}
