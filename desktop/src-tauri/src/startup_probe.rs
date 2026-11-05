//! Separate an absent TCP listener from an unresponsive HTTP service.
use std::net::SocketAddr;
#[cfg(any(not(windows), test))]
use std::{io::ErrorKind, net::TcpStream, time::Duration};

#[cfg(any(not(windows), test))]
fn listener_present(connection: std::io::Result<TcpStream>) -> Result<bool, String> {
    match connection {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == ErrorKind::ConnectionRefused => Ok(false),
        Err(error) => Err(format!("无法连接本地后台端口：{error}。未停止任何进程。")),
    }
}

pub fn probe_with<F>(address: SocketAddr, health: F) -> Result<Option<String>, String>
where F: FnOnce() -> Result<Option<String>, String> {
    #[cfg(windows)]
    let listening = crate::windows_listener::listening(address)?;
    #[cfg(not(windows))]
    let listening = listener_present(TcpStream::connect_timeout(&address, Duration::from_millis(150)))?;
    if !listening {
        return Ok(None);
    }
    health()
}

pub fn probe_instance(client: &reqwest::blocking::Client, address: SocketAddr) -> Result<Option<String>, String> {
    probe_with(address, || {
        let response = client.get(format!("http://{address}/api/health")).send()
            .map_err(|_| "本地后台响应超时：已检测到端口监听，但健康检查未完成。未重复启动后台。".to_string())?;
        if !response.status().is_success() {
            return Err("本地端口上的服务无法通过工作台检查。未停止任何进程。".into());
        }
        let value = response.json::<serde_json::Value>()
            .map_err(|_| "本地端口被其他程序占用或返回了无效响应。未停止任何进程。".to_string())?;
        if !crate::valid_health(&value) {
            return Err("本地端口被其他程序占用。未停止任何进程。".into());
        }
        Ok(Some(value.get("instance").and_then(|v| v.as_str()).unwrap_or("legacy").to_owned()))
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    #[test]
    fn tcp_timeout_is_unknown_instead_of_evidence_of_service_loss() {
        assert!(listener_present(Err(ErrorKind::TimedOut.into())).is_err());
        assert_eq!(listener_present(Err(ErrorKind::ConnectionRefused.into())), Ok(false));
    }

    #[test]
    fn no_listener_starts_backend_even_if_http_would_report_a_generic_timeout() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        drop(listener);
        let mut called = false;
        let result = probe_with(address, || {
            called = true;
            Err("HTTP timeout without a connect classification".into())
        });
        assert_eq!(result, Ok(None));
        assert!(!called, "No HTTP request should precede launching an absent backend");
    }

    #[test]
    fn confirmed_listener_http_timeout_never_means_start_another_backend() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let result = probe_with(listener.local_addr().unwrap(), || Err("HTTP timeout".into()));
        assert_eq!(result, Err("HTTP timeout".into()));
    }

    #[test]
    fn healthy_listener_returns_its_instance() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        assert_eq!(probe_with(listener.local_addr().unwrap(), || Ok(Some("instance".into()))), Ok(Some("instance".into())));
    }

    #[test]
    fn real_http_timeout_preserves_the_confirmed_listener() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let worker = std::thread::spawn(move || {
            #[cfg(not(windows))]
            drop(listener.accept().unwrap());
            let connection = listener.accept().unwrap();
            std::thread::sleep(Duration::from_millis(300));
            drop(connection);
        });
        let client = reqwest::blocking::Client::builder().no_proxy().timeout(Duration::from_millis(100)).build().unwrap();
        assert!(probe_instance(&client, address).unwrap_err().contains("已检测到端口监听"));
        worker.join().unwrap();
    }

    #[test]
    fn real_http_health_returns_instance_after_tcp_preflight() {
        use std::io::{Read, Write};
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let worker = std::thread::spawn(move || {
            #[cfg(not(windows))]
            drop(listener.accept().unwrap());
            let (mut stream, _) = listener.accept().unwrap();
            stream.set_read_timeout(Some(Duration::from_secs(3))).unwrap();
            let mut request = [0; 2048];
            stream.read(&mut request).unwrap();
            let body = r#"{"name":"infra-workbench","instance":"native-fixture"}"#;
            write!(stream, "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", body.len(), body).unwrap();
        });
        let client = reqwest::blocking::Client::builder().no_proxy().timeout(Duration::from_secs(3)).build().unwrap();
        assert_eq!(probe_instance(&client, address), Ok(Some("native-fixture".into())));
        worker.join().unwrap();
    }
}
