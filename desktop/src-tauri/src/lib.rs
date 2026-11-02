use reqwest::Url;
use serde_json::Value;

use std::sync::atomic::{AtomicBool,Ordering};

pub struct DesktopSession { ready:AtomicBool, requested:AtomicBool }
impl Default for DesktopSession {
    fn default()->Self { Self {ready:AtomicBool::new(false),requested:AtomicBool::new(true)} }
}
impl DesktopSession {
    pub fn request_show(&self)->bool { self.requested.store(true,Ordering::SeqCst);self.ready.load(Ordering::SeqCst) }
    pub fn hide(&self) { self.requested.store(false,Ordering::SeqCst); }
    pub fn mark_ready(&self)->bool { self.ready.store(true,Ordering::SeqCst);self.requested.load(Ordering::SeqCst) }
}

pub fn fade_duration_ms(visible:bool,animations_enabled:bool)->Option<u64> {
    if !visible && animations_enabled {Some(300)} else {None}
}
pub fn fade_alpha(elapsed:u64,duration:u64)->u8 {
    if duration==0 {return 255;}
    let progress=(elapsed as f64/duration as f64).clamp(0.0,1.0);
    (255.0*(progress*progress*(3.0-2.0*progress))).round() as u8
}

pub const SERVICE_URL: &str = "http://127.0.0.1:8765/";

pub fn is_service_url(url: &Url) -> bool {
    url.scheme() == "http" && url.host_str() == Some("127.0.0.1")
        && url.port() == Some(8765) && url.username().is_empty() && url.password().is_none()
}

pub fn valid_health(value: &Value) -> bool {
    value.get("name").and_then(Value::as_str) == Some("infra-workbench")
}

pub fn is_download_url(url: &Url) -> bool {
    is_service_url(url) || (url.scheme() == "blob"
        && Url::parse(url.path()).map(|origin| is_service_url(&origin)).unwrap_or(false))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_exact_loopback_origin_can_live_inside_the_window() {
        for value in [SERVICE_URL, "http://127.0.0.1:8765/#overview", "http://127.0.0.1:8765/api/files"] {
            assert!(is_service_url(&Url::parse(value).unwrap()), "{value}");
        }
        for value in ["http://127.0.0.1:8766/", "https://127.0.0.1:8765/", "http://localhost:8765/", "http://127.0.0.1.evil.test:8765/", "file:///tmp/test.html", "http://user@127.0.0.1:8765/"] {
            assert!(!is_service_url(&Url::parse(value).unwrap()), "{value}");
        }
    }

    #[test]
    fn unrelated_or_malformed_health_is_rejected() {
        assert!(valid_health(&serde_json::json!({"name":"infra-workbench","version":"0.1.0"})));
        for value in [serde_json::json!({"name":"other"}), serde_json::json!({}), serde_json::json!(null)] {
            assert!(!valid_health(&value));
        }
    }

    #[test]
    fn downloads_accept_only_service_responses_and_its_blob_urls() {
        assert!(is_download_url(&Url::parse("http://127.0.0.1:8765/api/files/download").unwrap()));
        assert!(is_download_url(&Url::parse("blob:http://127.0.0.1:8765/1234").unwrap()));
        for value in ["blob:https://evil.test/123", "blob:null/123", "https://evil.test/test.zip", "file:///tmp/test"] {
            assert!(!is_download_url(&Url::parse(value).unwrap()), "{value}");
        }
    }
}

#[cfg(test)]
mod session_tests {
    use super::DesktopSession;
    #[test]
    fn cold_window_waits_for_ready_but_reopening_reuses_ready_view() {
        let state=DesktopSession::default();
        assert!(!state.request_show());
        assert!(state.mark_ready());
        state.hide();
        assert!(state.request_show());
    }
    #[test]
    fn closing_while_loading_does_not_reopen_unexpectedly() {
        let state=DesktopSession::default();
        state.hide();
        assert!(!state.mark_ready());
        assert!(state.request_show());
    }
}

#[cfg(test)]
mod fade_tests {
    use super::{fade_duration_ms,fade_alpha};
    #[test]
    fn fade_only_when_hidden_and_system_animations_enabled() {
        assert_eq!(fade_duration_ms(false,true),Some(300));
        assert_eq!(fade_duration_ms(true,true),None);
        assert_eq!(fade_duration_ms(false,false),None);
    }
    #[test]
    fn fade_finishes_opaque_and_progresses_monotonically() {
        assert_eq!(fade_alpha(0,150),0);
        assert_eq!(fade_alpha(150,150),255);
        let values:Vec<_>=(0..=150).map(|time|fade_alpha(time,150)).collect();
        assert!(values.windows(2).all(|pair|pair[0]<=pair[1]));
    }
}
