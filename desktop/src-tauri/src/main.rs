#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use infra_workbench_desktop::{is_download_url, is_service_url, valid_health, DesktopSession, SERVICE_URL};
use std::{path::PathBuf, process::{Command, Stdio}, sync::atomic::{AtomicBool, Ordering}, time::{Duration, Instant}};
use tauri::{Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
mod window_fade;
mod quick_window;
use window_fade::restore_window;

#[derive(Default)]
struct Connecting(AtomicBool);

fn bootstrap_url(url: &reqwest::Url) -> bool {
    matches!(url.scheme(), "tauri" | "http" | "https")
        && matches!(url.host_str(), Some("tauri.localhost" | "localhost"))
        && url.port().is_none()
        && (url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost"))
}

fn status(window: &WebviewWindow, message: &str) {
    let text = serde_json::to_string(message).unwrap();
    let _ = window.eval(format!("document.getElementById('status').textContent={text}"));
}

fn probe(client: &reqwest::blocking::Client) -> Result<bool, String> {
    match client.get(format!("{SERVICE_URL}api/health")).send() {
        Ok(response) => {
            if !response.status().is_success() {
                return Err("8765 端口上的服务无法通过工作台检查。未停止任何进程。".into());
            }
            let value = response.json::<serde_json::Value>().map_err(|_| "8765 端口被其他程序占用。未停止任何进程。")?;
            if valid_health(&value) { Ok(true) } else { Err("8765 端口被其他程序占用。未停止任何进程。".into()) }
        }
        Err(error) if error.is_connect() => Ok(false),
        Err(_) => Err("本地后台响应超时，请检查系统托盘或菜单栏。未重复启动后台。".into()),
    }
}

fn start_runtime() -> Result<(), String> {
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
    command.spawn().map_err(|e| format!("无法启动后台：{e}"))?;
    Ok(())
}

fn connect(window: WebviewWindow) {
    let handle = window.app_handle().clone();
    if handle.state::<Connecting>().0.swap(true, Ordering::SeqCst) { return; }
    std::thread::spawn(move || {
        let result = (|| -> Result<(), String> {
            let client = reqwest::blocking::Client::builder().no_proxy()
                .redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(2))
                .build().map_err(|e| e.to_string())?;
            if !probe(&client)? {
                status(&window, "正在启动本地后台…");
                start_runtime()?;
                let deadline = Instant::now() + Duration::from_secs(45);
                loop {
                    if probe(&client)? { break; }
                    if Instant::now() >= deadline { return Err("后台未能在 45 秒内就绪，请查看数据目录中的 desktop.log 或 macos-desktop.log。".into()); }
                    std::thread::sleep(Duration::from_millis(300));
                }
            }
            window.navigate(SERVICE_URL.parse().unwrap()).map_err(|e| e.to_string())?;
            Ok(())
        })();
        if let Err(error) = result {
            status(&window, &error);
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

const READY_SCRIPT: &str = r#"
(() => {
  if (location.origin !== 'http://127.0.0.1:8765') return;
  let pending=false;
  const observer=new MutationObserver(ready);
  function ready() {
    const root=document.getElementById('root');
    if (pending || !root || !(root.querySelector('.shell') || (location.search.includes('tool=') ? root.querySelector('.terminal-dock,.file-browser,[role=alert]') : root.querySelector('button')))) return;
    pending=true;
    // Hidden WebViews can suspend animation frames; do not wait on requestAnimationFrame.
    setTimeout(() => {
      const invoke=window.__TAURI_INTERNALS__?.invoke;
      if (!invoke) { pending=false;setTimeout(ready,50);return; }
      invoke('desktop_ready').then(()=>observer.disconnect()).catch(()=>{pending=false;setTimeout(ready,100)});
    },100);
  }
  observer.observe(document,{childList:true,subtree:true});
  ready();
})();
"#;

fn main() {
    tauri::Builder::default()
        .manage(Connecting::default())
        .manage(DesktopSession::default())
        .plugin(tauri_plugin_single_instance::init(|app, args, _| {
            if args.iter().any(|arg|arg=="--quit-desktop") { app.exit(0);return; }
            if let Some((tool,host))=quick_window::request(&args) { let _=quick_window::open(app,&tool,&host);return; }
            if let Some(window) = app.get_webview_window("main") {
                if app.state::<DesktopSession>().request_show() {
                    restore_window(&window,true);
                }
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::default()
            .with_filter(|label|label=="main")
            .with_state_flags(tauri_plugin_window_state::StateFlags::SIZE | tauri_plugin_window_state::StateFlags::POSITION | tauri_plugin_window_state::StateFlags::MAXIMIZED).build())
        .invoke_handler(tauri::generate_handler![close_desktop, desktop_ready, quick_window::quick_window_action, quick_window::open_quick_tool])
        .setup(|app| {
            if std::env::args().any(|arg|arg=="--quit-desktop") { app.handle().exit(0);return Ok(()); }
            if let Some((tool,host))=quick_window::request(&std::env::args().collect::<Vec<_>>()) { quick_window::open(app.handle(),&tool,&host)?;return Ok(()); }
            #[cfg(target_os = "macos")]
            app.set_menu(tauri::menu::Menu::default(app.handle())?)?;
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Infra Workbench").inner_size(1440.0, 900.0).min_inner_size(480.0, 360.0)
                .visible(false)
                .background_color(tauri::window::Color(242,245,249,255))
                .initialization_script(READY_SCRIPT)
                .disable_drag_drop_handler() // Keep HTML file/folder upload handlers in the shared UI.
                .on_navigation(|url| {
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
        })
        .build(tauri::generate_context!())
        .expect("无法运行 Infra Workbench 桌面入口")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { code: None, api, .. } = event {
                api.prevent_exit();
                if let Some(window) = app.get_webview_window("main") {
                    app.state::<DesktopSession>().hide();
                    let _ = window.hide();
                }
            }
        });
}
