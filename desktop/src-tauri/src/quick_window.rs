use std::sync::atomic::{AtomicUsize, Ordering};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
static NEXT: AtomicUsize = AtomicUsize::new(1);

pub fn request(args: &[String]) -> Option<(String,String)> {
    let tool=args.windows(2).find(|a|a[0]=="--quick-tool")?[1].clone();
    let host=args.windows(2).find(|a|a[0]=="--host")?[1].clone();
    if !matches!(tool.as_str(),"terminal"|"files") || host.is_empty() { return None; }
    Some((tool,host))
}

pub fn open(app: &tauri::AppHandle, tool: &str, host: &str) -> tauri::Result<()> {
    open_with_path(app,tool,host,None)
}

fn open_with_path(app: &tauri::AppHandle, tool: &str, host: &str, path: Option<&str>) -> tauri::Result<()> {
    let _window_gate=super::updater::WINDOW_GATE.lock().unwrap();
    if super::updater::installing(app) { return Err(tauri::Error::Io(std::io::Error::new(std::io::ErrorKind::WouldBlock,"更新安装期间不能打开新窗口"))); }
    let mut url=reqwest::Url::parse(infra_workbench_desktop::SERVICE_URL).unwrap();
    url.query_pairs_mut().append_pair("tool",tool).append_pair("host",host);
    if let Some(path)=path { url.query_pairs_mut().append_pair("cwd",path); }
    let label=format!("quick-{}",NEXT.fetch_add(1,Ordering::Relaxed));
    let navigation_app=app.clone();
    let window=WebviewWindowBuilder::new(app,&label,WebviewUrl::External(url))
        .title(if tool=="terminal" {"终端"} else {"文件"})
        .inner_size(if tool=="terminal" {760.0} else {900.0},if tool=="terminal" {480.0} else {560.0})
        .min_inner_size(480.0,320.0).decorations(false).visible(false)
        .background_color(tauri::window::Color(28,42,57,255))
        .initialization_script(super::READY_SCRIPT)
        .disable_drag_drop_handler()
        .on_navigation(move |url|!super::updater::installing(&navigation_app) && infra_workbench_desktop::is_service_url(url))
        .on_new_window(|_,_|tauri::webview::NewWindowResponse::Deny)
                .on_download(|webview, event| {
                    match event {
                        tauri::webview::DownloadEvent::Requested { url, destination } => {
                            if !webview.url().map(|page| infra_workbench_desktop::is_service_url(&page)).unwrap_or(false)
                                || !infra_workbench_desktop::is_download_url(&url) { return false; }
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
        .build()?;
    #[cfg(windows)]
    if let Ok(hwnd)=window.hwnd() {
        #[link(name="dwmapi")]
        extern "system" { fn DwmSetWindowAttribute(hwnd: *mut std::ffi::c_void,attr:u32,value:*const u32,size:u32)->i32; }
        let preference=2u32;
        unsafe { DwmSetWindowAttribute(hwnd.0 as _,33,&preference,4); }
    }
    let _=window.center();
    Ok(())
}

#[tauri::command]
pub fn quick_window_action(window: tauri::WebviewWindow, action: String) -> Result<(),String> {
    if !window.label().starts_with("quick-") || !window.url().map(|u|infra_workbench_desktop::is_service_url(&u)).unwrap_or(false) {
        return Err("不允许的窗口".into());
    }
    let result=match action.as_str() {
        "drag"=>window.start_dragging(),
        "minimize"=>window.minimize(),
        "maximize"=>if window.is_maximized().unwrap_or(false) {window.unmaximize()} else {window.maximize()},
        "close"=>window.close(),
        _=>return Err("无效的窗口操作".into()),
    };
    result.map_err(|e|e.to_string())
}

#[cfg(test)]
mod tests {
    use super::request;
    #[test]
    fn only_known_tools_with_hosts_can_be_opened() {
        let args=|values:&[&str]|values.iter().map(|s|s.to_string()).collect::<Vec<_>>();
        assert_eq!(request(&args(&["app","--quick-tool","terminal","--host","a &/#"])),Some(("terminal".into(),"a &/#".into())));
        assert_eq!(request(&args(&["app","--quick-tool","shell","--host","a"])),None);
        assert_eq!(request(&args(&["app","--quick-tool","files"])),None);
    }
}

#[tauri::command]
pub fn open_quick_tool(window: tauri::WebviewWindow, tool: String, host: String, path: Option<String>) -> Result<(),String> {
    if !window.label().starts_with("quick-") || !window.url().map(|u|infra_workbench_desktop::is_service_url(&u)).unwrap_or(false) {
        return Err("不允许的窗口".into());
    }
    if !matches!(tool.as_str(),"terminal"|"files") || host.is_empty() || host.len()>512 {
        return Err("无效的窗口参数".into());
    }
    if let Some(ref value)=path {
        if !value.starts_with('/') || value.len()>4096 || value.chars().any(|c|c.is_control()) {return Err("无效的目录".into());}
    }
    open_with_path(window.app_handle(),&tool,&host,path.as_deref()).map_err(|e|e.to_string())
}
