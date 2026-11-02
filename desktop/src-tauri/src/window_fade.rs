//! Short compositor-opacity transition; no resize, reload or permanent animation loop.
use tauri::WebviewWindow;

pub fn restore_window(window:&WebviewWindow,animate:bool) {
    let target=window.clone();
    let _=window.run_on_main_thread(move || {
        if target.is_visible().unwrap_or(false) {
            if target.is_minimized().unwrap_or(false) {let _=target.unminimize();}
            let _=target.set_focus();
            return;
        }
        #[cfg(target_os="windows")]
        if animate && native::fade_in(&target) { return; }
        #[cfg(not(target_os="windows"))]
        let _=animate;
        let _=target.show();
        let _=target.set_focus();
    });
}

#[cfg(target_os="windows")]
mod native {
    use super::*;
    use std::{ffi::c_void,time::{Duration,Instant}};
    use infra_workbench_desktop::{fade_alpha,fade_duration_ms};
    #[link(name="user32")]
    extern "system" {
        fn SystemParametersInfoW(action:u32,param:u32,value:*mut c_void,flags:u32)->i32;
        fn GetWindowLongPtrW(hwnd:*mut c_void,index:i32)->isize;
        fn SetWindowLongPtrW(hwnd:*mut c_void,index:i32,value:isize)->isize;
        fn SetLayeredWindowAttributes(hwnd:*mut c_void,key:u32,alpha:u8,flags:u32)->i32;
    }
    #[link(name="dwmapi")]
    extern "system" {
        fn DwmSetWindowAttribute(hwnd:*mut c_void,attribute:u32,value:*const u32,size:u32)->i32;
        fn DwmFlush()->i32;
    }
    struct Cloak(*mut c_void);
    impl Drop for Cloak {
        fn drop(&mut self) {
            let disabled=0u32;
            unsafe {DwmSetWindowAttribute(self.0,13,&disabled,4);}
        }
    }
    pub fn fade_in(window:&WebviewWindow)->bool {
        let mut enabled=0i32;
        // Read the Windows Accessibility > Animation effects preference; never change it.
        let available=unsafe { SystemParametersInfoW(0x1042,0,&mut enabled as *mut _ as *mut c_void,0)!=0 };
        let Some(duration)=fade_duration_ms(false,available && enabled!=0) else {return false;};
        let Ok(handle)=window.hwnd() else {return false;};
        let hwnd=handle.0;
        // Keep the compositor from presenting the opaque frame while Tao
        // rebuilds the native styles. Release only after opacity zero is committed.
        let enabled=1u32;
        if unsafe {DwmSetWindowAttribute(hwnd,13,&enabled,4)}<0 {
            return false;
        }
        let cloak=Cloak(hwnd);
        // Tao rebuilds GWL_EXSTYLE when showing a window. Apply opacity after
        // show/focus, before returning to the event loop, so it is not discarded.
        if window.show().is_err() {return false;}
        let _=window.set_focus();
        let style=unsafe {GetWindowLongPtrW(hwnd,-20)};
        unsafe {SetWindowLongPtrW(hwnd,-20,style|0x80000);}
        if unsafe {SetLayeredWindowAttributes(hwnd,0,0,2)}==0 {return false;}
        unsafe {DwmFlush();}
        drop(cloak);
        let target=window.clone();
        std::thread::spawn(move || {
            let started=Instant::now();
            loop {
                let elapsed=started.elapsed().as_millis() as u64;
                let alpha=fade_alpha(elapsed,duration);
                let frame=target.clone();
                if target.run_on_main_thread(move || {
                    if let Ok(handle)=frame.hwnd() {
                        unsafe {SetLayeredWindowAttributes(handle.0,0,alpha,2);}
                    }
                }).is_err() {break;}
                if elapsed>=duration {break;}
                // Leave the UI thread free to paint the WebView between frames.
                std::thread::sleep(Duration::from_millis(10));
            }
        });
        true
    }
}
