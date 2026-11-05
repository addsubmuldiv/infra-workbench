#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use infra_workbench_desktop::{is_download_url, is_service_url, valid_health, DesktopSession, SERVICE_URL};
use std::{path::PathBuf, process::{Command, Stdio}, sync::atomic::{AtomicBool, Ordering}, time::{Duration, Instant}};
use tauri::{Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
mod window_fade;
mod lifecycle;
mod quick_window;
mod updater;
use window_fade::restore_window;

#[derive(Default)]
struct Connecting(AtomicBool);

fn bootstrap_url(url: &reqwest::Url) -> bool {
    matches!(url.scheme(), "tauri" | "http" | "https")
        && matches!(url.host_str(), Some("tauri.localhost" | "localhost"))
        && url.port().is_none()
        && (url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost"))
}

fn status(window: &WebviewWindow, stage: &str, percent: u8, error: Option<&str>) {
    let stage = serde_json::to_string(stage).unwrap();
    let error = serde_json::to_string(error.unwrap_or("")).unwrap();
    let _ = window.eval(format!("window.__iwbStartup?.update({stage},{percent},{error})"));
}

fn probe_instance(client: &reqwest::blocking::Client) -> Result<Option<String>, String> {
    match client.get(format!("{SERVICE_URL}api/health")).send() {
        Ok(response) => {
            if !response.status().is_success() {
                return Err("8765 端口上的服务无法通过工作台检查。未停止任何进程。".into());
            }
            let value = response.json::<serde_json::Value>().map_err(|_| "8765 端口被其他程序占用。未停止任何进程。")?;
            if valid_health(&value) { Ok(Some(value.get("instance").and_then(|v|v.as_str()).unwrap_or("legacy").to_owned())) } else { Err("8765 端口被其他程序占用。未停止任何进程。".into()) }
        }
        Err(error) if error.is_connect() => Ok(None),
        Err(_) => Err("本地后台响应超时，请检查系统托盘或菜单栏。未重复启动后台。".into()),
    }
}

fn probe(client:&reqwest::blocking::Client)->Result<bool,String>{probe_instance(client).map(|value|value.is_some())}

fn watch_service(app:tauri::AppHandle){
    std::thread::spawn(move || {
        let Ok(client)=reqwest::blocking::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(2)).build() else {return;};
        let mut watch=lifecycle::ServiceWatch::default();
        #[cfg(windows)]
        let quit=lifecycle::QuitSignal::new();
        loop {
            if updater::installing(&app){std::thread::sleep(Duration::from_secs(2));continue;}
            #[cfg(windows)]
            if quit.as_ref().map(|signal|signal.requested()).unwrap_or(false){app.exit(0);break;}
            // A busy HTTP server is not a dead backend. Only confirmed loss of
            // its listener or a different instance ends this desktop session.
            let stopped=match probe_instance(&client){Ok(identity)=>watch.observe_identity(identity),Err(_)=>false};
            if stopped {app.exit(0);break;}
            std::thread::sleep(Duration::from_secs(2));
        }
    });
}

fn start_runtime() -> Result<std::process::Child, String> {
    let mut command;
    let data;
    if cfg!(debug_assertions) {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap().to_path_buf();
        let python = root.join(if cfg!(windows) {".venv/Scripts/pythonw.exe"} else {".venv/bin/python"});
        if !python.is_file() { return Err("找不到项目 Python 环境，请先运行原有安装入口。".into()); }
        command = Command::new(python);
        command.args(["-m", "backend.desktop_runtime"]).current_dir(&root);
        data = std::env::var_os("IWB_DATA").map(PathBuf::from).unwrap_or_else(|| root.join("data"));
    } else {
        let executable = std::env::current_exe().map_err(|e| e.to_string())?;
        let runtime = executable.parent().unwrap().join(if cfg!(windows) {"iwb-runtime.exe"} else {"iwb-runtime"});
        if !runtime.is_file() { return Err("安装包缺少 Python 后台，请重新安装完整桌面版。".into()); }
        command = Command::new(runtime);
        data = std::env::var_os("IWB_DATA").map(PathBuf::from)
            .or_else(|| dirs::data_local_dir().map(|base| base.join("InfraWorkbench")))
            .ok_or("无法确定当前用户的数据目录")?;
    }
    std::fs::create_dir_all(&data).map_err(|e| format!("无法创建数据目录：{e}"))?;
    command.arg("--no-browser").env("IWB_DATA", &data)
        .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW; leave monitoring independent of the GUI.
    }
    // Dropping Child intentionally leaves the tray/menu-bar process alive.
    command.spawn().map_err(|e| format!("无法启动后台：{e}"))
}

fn connect(window: WebviewWindow) {
    let handle = window.app_handle().clone();
    if handle.state::<Connecting>().0.swap(true, Ordering::SeqCst) { return; }
    std::thread::spawn(move || {
        let result = (|| -> Result<(), String> {
            let client = reqwest::blocking::Client::builder().no_proxy()
                .redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(2))
                .build().map_err(|e| e.to_string())?;
            let deadline=Instant::now()+Duration::from_secs(60);
            let mut child:Option<std::process::Child>=None;
            let mut last_error=String::from("后台未能在 60 秒内就绪，请查看 desktop.log");
            loop {
                match probe(&client) {
                    Ok(true)=>break,
                    Ok(false)=>{
                        let finished=if let Some(process)=child.as_mut(){process.try_wait().map_err(|e|e.to_string())?}else{None};
                        if let Some(result)=finished {if !result.success(){return Err("后台启动失败，请查看 desktop.log".into());}}
                        if child.is_none()||finished.is_some(){status(&window,"backend",20,None);child=Some(start_runtime()?);}
                    },
                    Err(error)=>{last_error=error;status(&window,"waiting",20,None);}
                }
                if Instant::now()>=deadline {return Err(last_error);}
                std::thread::sleep(Duration::from_millis(300));
            }
            status(&window,"health",70,None);
            window.navigate(SERVICE_URL.parse().unwrap()).map_err(|e| e.to_string())?;
            Ok(())
        })();
        if let Err(error) = result {
            status(&window, "error",20,Some(&error));
            if handle.state::<DesktopSession>().mark_ready() { restore_window(&window,false); }
        }
        handle.state::<Connecting>().0.store(false, Ordering::SeqCst);
    });
}

#[tauri::command]
fn close_desktop(window: WebviewWindow) -> Result<(), String> {
    let url = window.url().map_err(|e| e.to_string())?;
    if !is_service_url(&url) && !bootstrap_url(&url) { return Err("不允许的页面".into()); }
    window.state::<DesktopSession>().hide();
    window.hide().map_err(|error|error.to_string())
}

#[tauri::command]
fn desktop_ready(window: WebviewWindow) -> Result<(), String> {
    if !window.url().map(|url|is_service_url(&url)).unwrap_or(false) { return Err("不允许的页面".into()); }
    if window.label().starts_with("quick-") { restore_window(&window,false);return Ok(()); }
    if window.state::<DesktopSession>().mark_ready() {
        restore_window(&window,false);
    }
    Ok(())
}

const READY_SCRIPT: &str = concat!(include_str!("../../bootstrap/startup.js"), r#"
(() => {
  if (location.origin !== 'http://127.0.0.1:8765') return;
  let pending=false;
  const observer=new MutationObserver(ready);
  function ready() {
    const root=document.getElementById('root');
    if (pending || !root || !(root.querySelector('.shell') || (location.search.includes('tool=') ? root.querySelector('.terminal-dock,.file-browser,.standalone-assistant,[role=alert]') : root.querySelector('button')))) return;
    pending=true;
    // Hidden WebViews can suspend animation frames; do not wait on requestAnimationFrame.
    setTimeout(() => {
      const invoke=window.__TAURI_INTERNALS__?.invoke;
      if (!invoke) { pending=false;setTimeout(ready,50);return; }
      invoke('desktop_ready').then(()=>{window.__iwbStartup?.update('frontend',100);window.__iwbStartup?.finish();observer.disconnect()}).catch(()=>{pending=false;setTimeout(ready,100)});
    },100);
  }
  observer.observe(document,{childList:true,subtree:true});
  ready();
})();
"#);

// Serialize window creation with updater installation, just like quick windows.
fn show_main_window(app: &tauri::AppHandle, focus: bool) -> tauri::Result<()> {
    let _window_gate = updater::WINDOW_GATE.lock().unwrap();
    if updater::installing(app) { return Ok(()); }
    if let Some(window) = app.get_webview_window("main") {
        if app.state::<DesktopSession>().request_show() {
            restore_window(&window, focus);
        }
        return Ok(());
    }
    let navigation_app=app.clone();
    let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Infra Workbench").inner_size(1440.0, 900.0).min_inner_size(480.0, 360.0)
        .visible(true)
        .background_color(tauri::window::Color(242,245,249,255))
        .initialization_script(READY_SCRIPT)
        .disable_drag_drop_handler() // Keep HTML file/folder upload handlers in the shared UI.
        .on_navigation(move |url| {
            if updater::installing(&navigation_app) { return false; }
            if is_service_url(url) || bootstrap_url(url) { return true; }
            if matches!(url.scheme(), "http" | "https") { let _ = open::that(url.as_str()); }
            false
        })
        .on_new_window(|url, _| {
            if matches!(url.scheme(), "http" | "https") { let _ = open::that(url.as_str()); }
            tauri::webview::NewWindowResponse::Deny
        })
        .on_download(|webview, event| {
            match event {
                tauri::webview::DownloadEvent::Requested { url, destination } => {
                    if !webview.url().map(|page| is_service_url(&page)).unwrap_or(false)
                        || !is_download_url(&url) { return false; }
                    let name = destination.file_name().and_then(|name| name.to_str()).unwrap_or("download");
                    let mut dialog = rfd::FileDialog::new().set_title("保存下载文件").set_file_name(name);
                    if let Some(directory) = dirs::download_dir() { dialog = dialog.set_directory(directory); }
                    if let Some(path) = dialog.save_file() { *destination = path; } else { return false; }
                }
                tauri::webview::DownloadEvent::Finished { success: false, .. } => {
                    rfd::MessageDialog::new().set_title("下载未完成")
                        .set_description("文件未能保存，请检查保存位置或重新下载。")
                        .set_level(rfd::MessageLevel::Error).show();
                }
                _ => (),
            }
            true
        })
        .on_page_load(|window, payload| {
            if payload.event() == tauri::webview::PageLoadEvent::Finished && bootstrap_url(payload.url()) {
                connect(window);
            }
        })
        .build()?;
    let close_window = window.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            // Hiding does not unload the WebView, discard editors or close SSH tabs.
            close_window.state::<DesktopSession>().hide();
            let _ = close_window.hide();
        }
    });
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .manage(updater::UpdaterState::default())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Connecting::default())
        .manage(DesktopSession::default())
        .plugin(tauri_plugin_single_instance::init(|app, args, _| {
            if updater::installing(app) { return; }
            if args.iter().any(|arg|arg=="--quit-desktop") { app.exit(0);return; }
            if let Some((tool,host))=quick_window::request(&args) { let _=quick_window::open(app,&tool,&host);return; }
            if let Err(error) = show_main_window(app, true) {
                eprintln!("无法打开工作台窗口：{error}");
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::default()
            .with_filter(|label|label=="main")
            .with_state_flags(tauri_plugin_window_state::StateFlags::SIZE | tauri_plugin_window_state::StateFlags::POSITION | tauri_plugin_window_state::StateFlags::MAXIMIZED).build())
        .invoke_handler(tauri::generate_handler![updater::desktop_update_status, updater::desktop_update_check, updater::desktop_update_download, updater::desktop_update_install, updater::desktop_update_safety_response, close_desktop, desktop_ready, quick_window::quick_window_action, quick_window::open_quick_tool])
        .setup(|app| {
            if std::env::args().any(|arg|arg=="--quit-desktop") { app.handle().exit(0);return Ok(()); }
            watch_service(app.handle().clone());
            #[cfg(target_os = "macos")]
            app.set_menu(tauri::menu::Menu::default(app.handle())?)?;
            if let Some((tool,host))=quick_window::request(&std::env::args().collect::<Vec<_>>()) { quick_window::open(app.handle(),&tool,&host)?;return Ok(()); }
            show_main_window(app.handle(), false)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("无法运行 Infra Workbench 桌面入口")
        .run(|app, event| {
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = &event {
                if let Err(error) = show_main_window(app, false) {
                    eprintln!("无法打开工作台窗口：{error}");
                }
            }
            if let tauri::RunEvent::ExitRequested { code: None, api, .. } = event {
                api.prevent_exit();
                if let Some(window) = app.get_webview_window("main") {
                    app.state::<DesktopSession>().hide();
                    let _ = window.hide();
                }
            }
        });
}
