//! Run the real embedded bootstrap and CSP without starting/stopping any backend.
//! cargo run --release --example startup_validation -- <receipt.json>
use std::path::PathBuf;
use tauri::{WebviewUrl, WebviewWindowBuilder};

fn main() {
    let receipt = PathBuf::from(std::env::args().nth(1).expect("receipt path required"));
    let auto_close = std::env::args().any(|arg| arg == "--auto-close");
    let mut context = tauri::generate_context!();
    context.config_mut().identifier = "com.infra-workbench.startup-validation".into();
    tauri::Builder::default()
        .setup(move |app| {
            let handle = app.handle().clone();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Infra Workbench · 启动页回归验证")
                .inner_size(1100.0, 720.0)
                .visible(true)
                .initialization_script(concat!(
                    "window.__startupViolations=[];document.addEventListener('securitypolicyviolation',e=>window.__startupViolations.push({directive:e.effectiveDirective,blocked:e.blockedURI}));\n",
                    include_str!("../../bootstrap/startup.js")
                ))
                .on_navigation(move |url| {
                    // Capture inside the native navigation callback, without
                    // weakening the production CSP to permit extra IPC/network.
                    if url.host_str() == Some("startup-validation.invalid") {
                        if let Some((_, result)) = url.query_pairs().find(|(key, _)| key == "result") {
                            std::fs::write(&receipt, result.as_bytes()).expect("write receipt");
                            if auto_close {
                                let ok = serde_json::from_str::<serde_json::Value>(&result).ok()
                                    .and_then(|value| value.get("ok").and_then(|v| v.as_bool())).unwrap_or(false);
                                handle.exit(if ok { 0 } else { 1 });
                            }
                        }
                        return false;
                    }
                    true
                })
                .on_page_load(|window, payload| {
                    if payload.event() != tauri::webview::PageLoadEvent::Finished { return; }
                    let _ = window.eval(r#"setTimeout(()=>{
                      const root=document.getElementById('iwb-startup'),panel=document.getElementById('iwb-startup-panel'),svg=root?.querySelector('svg');
                      const box=panel?.getBoundingClientRect(),icon=svg?.getBoundingClientRect();
                      const css=root?getComputedStyle(root):null;
                      const result={origin:location.origin,csp:document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.content,
                        root:css?{position:css.position,display:css.display}:null,
                        panel:box?{x:box.x,y:box.y,width:box.width,height:box.height}:null,
                        icon:icon?{width:icon.width,height:icon.height}:null,
                        viewport:{width:innerWidth,height:innerHeight},violations:window.__startupViolations};
                      result.ok=!!(css?.position==='fixed'&&box?.width<=460&&icon?.width===48&&icon?.height===48&&box.x>=0&&box.y>=0&&box.right<=innerWidth&&box.bottom<=innerHeight&&!result.violations.length);
                      location.href='http://startup-validation.invalid/?result='+encodeURIComponent(JSON.stringify(result));
                    },750)"#);
                })
                .build()?;
            Ok(())
        })
        .run(context)
        .expect("startup validation window failed");
}
