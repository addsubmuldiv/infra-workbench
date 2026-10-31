use reqwest::Url;
use serde_json::Value;

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
