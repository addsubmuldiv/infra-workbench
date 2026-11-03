use std::sync::atomic::{AtomicUsize, Ordering};
use std::{collections::HashMap,sync::{LazyLock,Mutex}};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
static NEXT: AtomicUsize = AtomicUsize::new(1);
// Per-window, memory-only handoff. Never send terminal text through navigation
// URLs or persist it as workspace state. The receiver can drain only its own key.
static CONTEXTS: LazyLock<Mutex<HashMap<String,Vec<serde_json::Value>>>>=LazyLock::new(||Mutex::new(HashMap::new()));

fn check_context(items:&[serde_json::Value])->Result<(),String>{
    if items.len()>3 {return Err("终端附件数量超出限制".into());}
    for item in items {
        for (field,limit) in [("host_id",512),("label",512),("terminal_id",256),("captured_at",100),("content",12000)] {
            let value=item.get(field).and_then(|v|v.as_str()).ok_or("无效的终端附件")?;
            if value.chars().count()>limit {return Err("终端附件超出限制".into());}
        }
        if !matches!(item.get("source").and_then(|v|v.as_str()),Some("screen"|"selection")) || !item.get("truncated").map(|v|v.is_boolean()).unwrap_or(false) {return Err("无效的终端附件".into());}
        for field in ["cwd","session_id"] {
            if let Some(value)=item.get(field) {if !value.is_null() && !value.as_str().map(|v|v.chars().count()<=4096).unwrap_or(false) {return Err("无效的终端附件".into());}}
        }
        if serde_json::to_vec(item).map_err(|e|e.to_string())?.len()>100_000 {return Err("终端附件超出限制".into());}
    }
    Ok(())
}

#[derive(Clone,Copy,Debug,PartialEq)]
struct Frame { x:i32,y:i32,width:i32,height:i32 }

fn companion_frames(source:Frame,area:Frame,scale:f64)->Result<(Frame,Frame),String>{
    let gap=(12.0*scale).round() as i32;
    let margin=(8.0*scale).round() as i32;
    let min_source=(480.0*scale).round() as i32;
    let width=((440.0*scale).round() as i32).min(area.width-min_source-gap-2*margin);
    if width<(320.0*scale).round() as i32 {return Err("屏幕宽度不足以并排显示，请调整系统缩放或将终端移到更宽的显示器".into());}
    let mut source=source;
    source.width=source.width.min(area.width-2*margin);
    source.height=source.height.min(area.height-2*margin);
    source.x=source.x.clamp(area.x+margin,area.x+area.width-source.width-margin);
    source.y=source.y.clamp(area.y+margin,area.y+area.height-source.height-margin);
    let height=source.height.max((520.0*scale).round() as i32).min(area.height-2*margin);
    let y=source.y.clamp(area.y+margin,area.y+area.height-height-margin);
    let x=if source.x+source.width+gap+width<=area.x+area.width-margin {
        source.x+source.width+gap
    }else if source.x-gap-width>=area.x+margin {
        source.x-gap-width
    }else {
        source.x=area.x+margin;
        source.width=area.width-width-gap-2*margin;
        source.x+source.width+gap
    };
    Ok((source,Frame{x,y,width,height}))
}

pub fn request(args: &[String]) -> Option<(String,String)> {
    let tool=args.windows(2).find(|a|a[0]=="--quick-tool")?[1].clone();
    let host=args.windows(2).find(|a|a[0]=="--host")?[1].clone();
    if !matches!(tool.as_str(),"terminal"|"files") || host.is_empty() { return None; }
    Some((tool,host))
}

pub fn open(app: &tauri::AppHandle, tool: &str, host: &str) -> tauri::Result<()> {
    open_with_path(app,tool,host,None,None,None)
}

fn open_with_path(app: &tauri::AppHandle, tool: &str, host: &str, path: Option<&str>, companion: Option<&tauri::WebviewWindow>, channel: Option<&str>) -> tauri::Result<()> {
    let _window_gate=super::updater::WINDOW_GATE.lock().unwrap();
    if super::updater::installing(app) { return Err(tauri::Error::Io(std::io::Error::new(std::io::ErrorKind::WouldBlock,"更新安装期间不能打开新窗口"))); }
    let mut url=reqwest::Url::parse(infra_workbench_desktop::SERVICE_URL).unwrap();
    url.query_pairs_mut().append_pair("tool",tool).append_pair("host",host);
    if let Some(path)=path { url.query_pairs_mut().append_pair("cwd",path); }
    if let Some(channel)=channel {url.query_pairs_mut().append_pair("channel",channel);}
    let label=companion.map(|source|format!("quick-assistant-{}",source.label())).unwrap_or_else(||format!("quick-{}",NEXT.fetch_add(1,Ordering::Relaxed)));
    if let (Some(source),Some(existing))=(companion,app.get_webview_window(&label)) {
        place_companion(source,&existing).map_err(|message|tauri::Error::Io(std::io::Error::other(message)))?;
        if existing.url()?.query_pairs().find(|(key,_)|key=="channel").map(|(_,value)|value.into_owned())!=channel.map(str::to_owned) {existing.navigate(url)?;}
        existing.unminimize()?;existing.show()?;existing.set_focus()?;return Ok(());
    }
    let navigation_app=app.clone();
    let window=WebviewWindowBuilder::new(app,&label,WebviewUrl::External(url))
        .title(if tool=="assistant" {"AI 助手"} else if tool=="terminal" {"终端"} else {"文件"})
        .inner_size(if tool=="terminal" {760.0} else {900.0},if tool=="terminal" {480.0} else {560.0})
        .min_inner_size(if companion.is_some() {320.0} else {480.0},320.0).decorations(false).visible(false)
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
    let context_label=label.clone();
    window.on_window_event(move |event|{if matches!(event,tauri::WindowEvent::Destroyed){if let Ok(mut contexts)=CONTEXTS.lock(){contexts.remove(&context_label);}}});
    #[cfg(windows)]
    if let Ok(hwnd)=window.hwnd() {
        #[link(name="dwmapi")]
        extern "system" { fn DwmSetWindowAttribute(hwnd: *mut std::ffi::c_void,attr:u32,value:*const u32,size:u32)->i32; }
        let preference=2u32;
        unsafe { DwmSetWindowAttribute(hwnd.0 as _,33,&preference,4); }
    }
    if let Some(source)=companion {
        if let Err(message)=place_companion(source,&window) {let _=window.close();return Err(tauri::Error::Io(std::io::Error::other(message)));}
    }else {let _=window.center();}
    Ok(())
}

#[tauri::command]
pub fn quick_window_action(window: tauri::WebviewWindow, action: String) -> Result<serde_json::Value,String> {
    if !window.label().starts_with("quick-") || !window.url().map(|u|infra_workbench_desktop::is_service_url(&u)).unwrap_or(false) {
        return Err("不允许的窗口".into());
    }
    if action=="take-terminal-context" {
        if !window.label().starts_with("quick-assistant-") {return Err("只允许助手窗口接收终端附件".into());}
        let items=CONTEXTS.lock().map_err(|_|"无法读取终端附件")?.remove(window.label()).unwrap_or_default();
        return Ok(serde_json::Value::Array(items));
    }
    let result=match action.as_str() {
        "drag"=>window.start_dragging(),
        "minimize"=>window.minimize(),
        "maximize"=>if window.is_maximized().unwrap_or(false) {window.unmaximize()} else {window.maximize()},
        "close"=>window.close(),
        _=>return Err("无效的窗口操作".into()),
    };
    result.map(|_|serde_json::Value::Null).map_err(|e|e.to_string())
}

#[cfg(test)]
mod tests {
    use super::{request,companion_frames,check_context,Frame};
    #[test]
    fn native_handoff_rejects_invalid_or_oversized_terminal_attachments(){
        let valid=serde_json::json!({"host_id":"node","label":"node","terminal_id":"tab","captured_at":"now","content":"test","source":"screen","truncated":false});
        assert!(check_context(&[valid.clone()]).is_ok());
        assert!(check_context(&vec![valid.clone();4]).is_err());
        let mut huge=valid.clone();huge["content"]=serde_json::json!("字".repeat(12001));assert!(check_context(&[huge]).is_err());
        let mut malformed=valid;malformed["label"]=serde_json::json!({"text":"not a string"});assert!(check_context(&[malformed]).is_err());
    }
    #[test]
    fn companion_is_adjacent_without_covering_the_terminal(){
        let area=Frame{x:0,y:0,width:1920,height:1040};
        let source=Frame{x:100,y:100,width:1000,height:650};
        let (terminal,assistant)=companion_frames(source,area,1.0).unwrap();
        assert_eq!(terminal,source);assert!(assistant.x>=terminal.x+terminal.width);
        let (terminal,assistant)=companion_frames(Frame{x:0,y:0,width:1920,height:1040},area,1.0).unwrap();
        assert!(terminal.x+terminal.width<assistant.x);assert!(assistant.x+assistant.width<=1920);
    }
    #[test]
    fn companion_handles_left_side_negative_monitors_and_display_scaling(){
        let area=Frame{x:-2560,y:0,width:2560,height:1440};
        let source=Frame{x:-1000,y:100,width:900,height:900};
        let (terminal,assistant)=companion_frames(source,area,1.5).unwrap();
        assert!(assistant.x+assistant.width<terminal.x);
        assert!(assistant.x>=area.x);assert!(assistant.y+assistant.height<=area.height);
        assert!(companion_frames(source,Frame{x:0,y:0,width:600,height:900},1.0).is_err());
    }
    #[test]
    fn only_known_tools_with_hosts_can_be_opened() {
        let args=|values:&[&str]|values.iter().map(|s|s.to_string()).collect::<Vec<_>>();
        assert_eq!(request(&args(&["app","--quick-tool","terminal","--host","a &/#"])),Some(("terminal".into(),"a &/#".into())));
        assert_eq!(request(&args(&["app","--quick-tool","shell","--host","a"])),None);
        assert_eq!(request(&args(&["app","--quick-tool","files"])),None);
    }
}

#[tauri::command]
pub fn open_quick_tool(window: tauri::WebviewWindow, tool: String, host: String, path: Option<String>, channel: Option<String>, attachments:Option<Vec<serde_json::Value>>) -> Result<(),String> {
    if !window.label().starts_with("quick-") || !window.url().map(|u|infra_workbench_desktop::is_service_url(&u)).unwrap_or(false) {
        return Err("不允许的窗口".into());
    }
    if !matches!(tool.as_str(),"terminal"|"files"|"assistant") || host.is_empty() || host.len()>512 {
        return Err("无效的窗口参数".into());
    }
    if let Some(ref value)=path {
        if !value.starts_with('/') || value.len()>4096 || value.chars().any(|c|c.is_control()) {return Err("无效的目录".into());}
    }
    if tool=="assistant" {
        let items=attachments.unwrap_or_default();check_context(&items)?;
        let source=window.url().map_err(|e|e.to_string())?;
        if !source.query_pairs().any(|(key,value)|key=="tool"&&value=="terminal") {return Err("只允许从独立终端打开助手".into());}
        let value=channel.as_deref().ok_or("缺少窗口传递通道")?;
        if !(16..=80).contains(&value.len()) || !value.bytes().all(|byte|byte.is_ascii_alphanumeric()||byte==b'-') {return Err("无效的窗口传递通道".into());}
        open_with_path(window.app_handle(),&tool,&host,None,Some(&window),Some(value)).map_err(|e|e.to_string())?;
        let mut contexts=CONTEXTS.lock().map_err(|_|"无法传递终端附件")?;
        let queue=contexts.entry(format!("quick-assistant-{}",window.label())).or_default();
        queue.extend(items);if queue.len()>3 {queue.drain(..queue.len()-3);}
        return Ok(());
    }
    open_with_path(window.app_handle(),&tool,&host,path.as_deref(),None,None).map_err(|e|e.to_string())
}

fn place_companion(source:&tauri::WebviewWindow,assistant:&tauri::WebviewWindow)->Result<(),String>{
    let monitor=source.current_monitor().map_err(|e|e.to_string())?.ok_or("无法确定终端所在显示器")?;
    let position=source.outer_position().map_err(|e|e.to_string())?;
    let size=source.outer_size().map_err(|e|e.to_string())?;
    let area=monitor.work_area();
    let original=Frame{x:position.x,y:position.y,width:size.width as i32,height:size.height as i32};
    let (terminal,companion)=companion_frames(original,Frame{x:area.position.x,y:area.position.y,width:area.size.width as i32,height:area.size.height as i32},monitor.scale_factor())?;
    if source.is_maximized().unwrap_or(false) {source.unmaximize().map_err(|e|e.to_string())?;}
    if terminal!=original || source.outer_size().map_err(|e|e.to_string())?!=size {
        source.set_size(tauri::PhysicalSize::new(terminal.width as u32,terminal.height as u32)).map_err(|e|e.to_string())?;
        source.set_position(tauri::PhysicalPosition::new(terminal.x,terminal.y)).map_err(|e|e.to_string())?;
    }
    assistant.set_size(tauri::PhysicalSize::new(companion.width as u32,companion.height as u32)).map_err(|e|e.to_string())?;
    assistant.set_position(tauri::PhysicalPosition::new(companion.x,companion.y)).map_err(|e|e.to_string())?;
    Ok(())
}
