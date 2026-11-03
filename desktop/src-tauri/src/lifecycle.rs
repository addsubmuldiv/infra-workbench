#[derive(Default)]
pub struct ServiceWatch { ready:bool, failures:u8, identity:Option<String> }
impl ServiceWatch {
    pub fn observe_identity(&mut self,identity:Option<String>)->bool {
        if let Some(value)=identity {
            if self.identity.as_ref().map(|old|old!=&value).unwrap_or(false){return true;}
            self.identity=Some(value);self.observe(true)
        }else{self.observe(false)}
    }
    // Startup and one-off delays must not look like a deliberate backend exit.
    pub fn observe(&mut self,healthy:bool)->bool {
        if healthy {self.ready=true;self.failures=0;return false;}
        if self.ready {self.failures=self.failures.saturating_add(1);}
        self.ready && self.failures>=3
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn transient_startup_and_health_failures_do_not_close_windows(){
        let mut watch=ServiceWatch::default();
        for _ in 0..10 {assert!(!watch.observe(false));}
        assert!(!watch.observe(true));assert!(!watch.observe(false));assert!(!watch.observe(false));
        assert!(!watch.observe(true));assert!(!watch.observe(false));
    }
    #[test]
    fn stopped_backend_closes_all_native_windows_after_a_bounded_grace_period(){
        let mut watch=ServiceWatch::default();watch.observe(true);
        assert!(!watch.observe(false));assert!(!watch.observe(false));assert!(watch.observe(false));
    }
    #[test]
    fn backend_replacement_cannot_leave_windows_attached_to_an_old_session(){
        let mut watch=ServiceWatch::default();
        assert!(!watch.observe_identity(Some("first".into())));
        assert!(!watch.observe_identity(Some("first".into())));
        assert!(watch.observe_identity(Some("second".into())));
    }
}

#[cfg(windows)]
pub struct QuitSignal(*mut std::ffi::c_void);
#[cfg(windows)]
#[link(name="kernel32")]
extern "system" {
    fn CreateEventW(attributes:*mut std::ffi::c_void,manual:i32,initial:i32,name:*const u16)->*mut std::ffi::c_void;
    fn WaitForSingleObject(handle:*mut std::ffi::c_void,timeout:u32)->u32;
    fn CloseHandle(handle:*mut std::ffi::c_void)->i32;
}
#[cfg(windows)]
impl QuitSignal {
    pub fn new()->Option<Self>{
        Self::named("Local\\InfraWorkbenchDesktopQuit")
    }
    fn named(value:&str)->Option<Self>{
        let name:Vec<u16>=value.encode_utf16().chain(std::iter::once(0)).collect();
        let handle=unsafe{CreateEventW(std::ptr::null_mut(),1,0,name.as_ptr())};
        if handle.is_null(){None}else{Some(Self(handle))}
    }
    pub fn requested(&self)->bool{unsafe{WaitForSingleObject(self.0,0)==0}}
}
#[cfg(windows)]
impl Drop for QuitSignal {fn drop(&mut self){unsafe{CloseHandle(self.0);}}}

#[cfg(all(test,windows))]
mod signal_tests {
    use super::*;
    #[link(name="kernel32")]
    extern "system" {fn SetEvent(handle:*mut std::ffi::c_void)->i32;}
    #[test]
    fn windows_quit_signal_reaches_the_existing_instance(){
        let name=format!("Local\\InfraWorkbenchLifecycleTest-{}",std::process::id());
        let resident=QuitSignal::named(&name).unwrap();
        let sender=QuitSignal::named(&name).unwrap();
        assert!(!resident.requested());
        assert_ne!(unsafe{SetEvent(sender.0)},0);
        assert!(resident.requested());
    }
}
