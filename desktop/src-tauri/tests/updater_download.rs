#![cfg(test)]

//! Exercises the real updater HTTP/signature path with a throwaway signing key.
//! No installer APIs, desktop dialogs, runtime shutdown, or production network is used.
use std::{
    io::{Read, Write},
    net::TcpListener,
    sync::{Arc, atomic::{AtomicBool, Ordering}},
    thread::{self, JoinHandle},
    time::Duration,
};
use tauri_plugin_updater::UpdaterExt;
use base64::{Engine, engine::general_purpose::STANDARD};

const PAYLOAD: &[u8] = include_bytes!("fixtures/updater/payload.bin");
const SIGNATURE: &str = include_str!("fixtures/updater/payload.bin.sig");
const PUBLIC_KEY: &str = include_str!("fixtures/updater/public.pub");

struct Server { origin: String, stop: Arc<AtomicBool>, worker: Option<JoinHandle<()>> }
impl Server {
    fn new(version: &str, signature: &str, payload: Vec<u8>) -> Self {
        let listener=TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let origin=format!("http://{}",listener.local_addr().unwrap());
        let feed=serde_json::to_vec(&serde_json::json!({
            "version": version,
            "notes": "Ephemeral signed update fixture",
            "platforms": { "test-target": {"url":format!("{origin}/package"),"signature":signature.trim()} }
        })).unwrap();
        let stop=Arc::new(AtomicBool::new(false)); let signal=stop.clone();
        let worker=thread::spawn(move || {
            while !signal.load(Ordering::SeqCst) {
                let (mut stream,_)=match listener.accept() {
                    Ok(value)=>value,
                    Err(error) if error.kind()==std::io::ErrorKind::WouldBlock=>{thread::sleep(Duration::from_millis(5));continue;},
                    Err(error)=>panic!("mock HTTP accept: {error}"),
                };
                // Windows may inherit the listener's nonblocking mode. The
                // fixture reads a complete HTTP request with a bounded timeout.
                stream.set_nonblocking(false).unwrap();
                stream.set_read_timeout(Some(Duration::from_secs(3))).unwrap();
                let mut request=Vec::new(); let mut chunk=[0u8;1024];
                while !request.windows(4).any(|w|w==b"\r\n\r\n") && request.len()<8192 {
                    let count=stream.read(&mut chunk).unwrap(); if count==0 {break;} request.extend_from_slice(&chunk[..count]);
                }
                let first_line=String::from_utf8_lossy(&request);
                let (status,body)=if first_line.starts_with("GET /feed ") {("200 OK",feed.as_slice())}
                    else if first_line.starts_with("GET /package ") {("200 OK",payload.as_slice())}
                    else {("404 Not Found",b"not found".as_slice())};
                let header=format!("HTTP/1.1 {status}\r\nContent-Length: {}\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n",body.len());
                stream.write_all(header.as_bytes()).unwrap(); stream.write_all(body).unwrap();
            }
        });
        Self { origin,stop,worker:Some(worker) }
    }
}
impl Drop for Server {
    fn drop(&mut self) { self.stop.store(true,Ordering::SeqCst); self.worker.take().unwrap().join().unwrap(); }
}
fn app() -> tauri::App<tauri::test::MockRuntime> {
    let mut context=tauri::test::mock_context(tauri::test::noop_assets());
    context.package_info_mut().version="0.1.1".parse().unwrap();
    context.config_mut().plugins.0.insert("updater".into(),serde_json::json!({
        "pubkey": PUBLIC_KEY.trim(),
        "requireSignedVersion": true,
        // This override lives only in this test context, never in application config.
        "dangerousInsecureTransportProtocol": true
    }));
    tauri::test::mock_builder().plugin(tauri_plugin_updater::Builder::new().build()).build(context).unwrap()
}
fn check_and_download(version: &str, signature: &str, payload: Vec<u8>) -> Result<Vec<u8>,tauri_plugin_updater::Error> {
    let server=Server::new(version,signature,payload);
    let app=app();
    let updater=app.updater_builder().target("test-target").no_proxy().timeout(Duration::from_secs(5))
        .endpoints(vec![format!("{}/feed",server.origin).parse().unwrap()]).unwrap().build().unwrap();
    tauri::async_runtime::block_on(async {
        let update=updater.check().await?.expect("newer release must be detected");
        assert_eq!(update.version,version);
        let mut received=0; let mut completed=false;
        let bytes=update.download(|chunk,total| { received+=chunk; assert_eq!(total,Some(payload_len())); },||completed=true).await?;
        assert_eq!(received,bytes.len()); assert!(completed);
        Ok(bytes)
    })
}
fn payload_len() -> u64 { PAYLOAD.len() as u64 }

#[test]
fn signed_download_accepts_newer_release_and_rejects_tampering() {
    assert_eq!(check_and_download("0.1.2",SIGNATURE,PAYLOAD.to_vec()).unwrap(),PAYLOAD);
    let mut tampered=PAYLOAD.to_vec(); tampered[0]^=1;
    assert!(check_and_download("0.1.2",SIGNATURE,tampered).is_err(),"modified payload must fail signature verification");
    // Keep valid minisign/base64 framing and the original key ID, but corrupt
    // one byte of the actual Ed25519 signature (the first ten bytes are metadata).
    let decoded=String::from_utf8(STANDARD.decode(SIGNATURE.trim()).unwrap()).unwrap();
    let mut lines=decoded.lines().map(str::to_owned).collect::<Vec<_>>();
    let mut signature_bytes=STANDARD.decode(&lines[1]).unwrap(); signature_bytes[10]^=1;
    lines[1]=STANDARD.encode(signature_bytes);
    let bad_signature=STANDARD.encode(lines.join("\n"));
    assert!(check_and_download("0.1.2",&bad_signature,PAYLOAD.to_vec()).is_err(),"well-formed but invalid signature must be rejected");
    let mismatch=check_and_download("0.1.3",SIGNATURE,PAYLOAD.to_vec()).unwrap_err();
    assert!(matches!(mismatch,tauri_plugin_updater::Error::SignedVersionMismatch { .. }),"must reject a feed version that differs from its signed artifact: {mismatch}");
}

#[test]
fn production_update_transport_remains_https_and_signed() {
    let config:serde_json::Value=serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
    let updater=&config["plugins"]["updater"];
    assert_eq!(updater["endpoints"],serde_json::json!(["https://github.com/addsubmuldiv/infra-workbench/releases/latest/download/latest.json"]));
    assert_eq!(updater["requireSignedVersion"],true);
    assert_ne!(updater["dangerousInsecureTransportProtocol"],true);
}
