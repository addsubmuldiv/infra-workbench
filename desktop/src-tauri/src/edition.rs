use serde::Serialize;
use tauri::WebviewWindow;
#[cfg(windows)]
use tauri::Manager;

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Edition {
    Installed,
    Development,
}

#[derive(Serialize)]
pub(crate) struct EditionStatus {
    current: Edition,
    switch_supported: bool,
    switch_available: bool,
}

#[tauri::command]
pub(crate) async fn desktop_edition_status(window: WebviewWindow) -> Result<EditionStatus, String> {
    super::updater::guard(&window)?;
    let current = if super::runtime_source_root().is_some() {
        Edition::Development
    } else {
        Edition::Installed
    };
    #[cfg(windows)]
    let switch_available = windows::target(current).is_some();
    #[cfg(not(windows))]
    let switch_available = false;
    Ok(EditionStatus { current, switch_supported: cfg!(windows), switch_available })
}

#[tauri::command]
pub(crate) async fn desktop_switch_edition(window: WebviewWindow) -> Result<(), String> {
    super::updater::guard(&window)?;
    #[cfg(windows)]
    {
        use super::updater;
        let app = window.app_handle().clone();
        updater::begin_switch(&app)?;
        let worker = app.clone();
        let result = tauri::async_runtime::spawn_blocking(move || windows::switch(&worker))
            .await
            .map_err(|error| error.to_string())
            .and_then(|result| result);
        if result.is_ok() {
            app.exit(0);
        } else {
            updater::cancel_switch(&app);
        }
        result
    }
    #[cfg(not(windows))]
    Err("desktop_switch_unsupported".into())
}

#[cfg(windows)]
pub(crate) use windows::{run_handoff, remember_checkout};

#[cfg(windows)]
mod windows {
    use super::Edition;
    use crate::{runtime_source_root, updater};
    use std::{
        ffi::OsStr,
        io::{Read, Write},
        os::windows::process::CommandExt,
        path::{Path, PathBuf},
        process::{Command, Stdio},
    };
    use winreg::{enums::{HKEY_CURRENT_USER, KEY_READ, KEY_WOW64_32KEY, KEY_WOW64_64KEY}, RegKey};
    use windows_sys::Win32::Foundation::{CloseHandle, ERROR_INVALID_PARAMETER, WAIT_OBJECT_0};

    const SOURCE_KEY: &str = r"Software\InfraWorkbench\Development";
    const UNINSTALL_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Infra Workbench";
    const DESKTOP_EXE: &str = "infra-workbench-desktop.exe";
    const HANDOFF: &str = "--iwb-edition-handoff";

    pub(crate) struct Launch {
        executable: PathBuf,
        source: Option<PathBuf>,
    }

    impl Launch {
        fn command(&self) -> Command {
            let mut command = Command::new(&self.executable);
            command.arg("--show-desktop").env_remove("IWB_DATA")
                .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())
                .creation_flags(0x08000000);
            if let Some(root) = &self.source {
                command.env("IWB_SOURCE_ROOT", root).current_dir(root);
            } else {
                command.env_remove("IWB_SOURCE_ROOT");
                if let Some(directory) = self.executable.parent() {
                    command.current_dir(directory);
                }
            }
            command
        }
    }

    fn valid_checkout(root: &Path) -> bool {
        root.is_absolute() && root.join(".venv/Scripts/pythonw.exe").is_file()
            && root.join("backend/desktop_runtime.py").is_file()
            && root.join("frontend/dist/index.html").is_file()
    }

    pub(crate) fn remember_checkout() {
        let Some(root) = runtime_source_root().and_then(|root| root.canonicalize().ok()) else { return; };
        if valid_checkout(&root) {
            let user = RegKey::predef(HKEY_CURRENT_USER);
            if let Err(error) = user.create_subkey(SOURCE_KEY)
                .and_then(|(key, _)| key.set_value("Checkout", &root.as_os_str().to_os_string())) {
                crate::startup_trace(&format!("Could not record development checkout: {error}"));
            }
        }
    }

    fn built_desktop(root: &Path) -> Option<PathBuf> {
        if !valid_checkout(root) { return None; }
        let builds = root.join("desktop/src-tauri/target");
        [builds.join("release").join(DESKTOP_EXE), builds.join("debug").join(DESKTOP_EXE)]
            .into_iter()
            .filter_map(|path| {
                let metadata = path.metadata().ok()?;
                metadata.is_file().then_some((metadata.modified().ok()?, path))
            })
            .max_by_key(|(time, _)| *time)
            .map(|(_, path)| path)
    }

    fn registered_install(directory: &str) -> Option<PathBuf> {
        let directory = Path::new(directory.trim().trim_matches('"'));
        if !directory.is_absolute() || !directory.join("iwb-runtime.exe").is_file() {
            return None;
        }
        let binary = directory.join(DESKTOP_EXE);
        binary.is_file().then_some(binary)
    }

    pub(crate) fn target(current: Edition) -> Option<Launch> {
        let user = RegKey::predef(HKEY_CURRENT_USER);
        match current {
            Edition::Installed => {
                let root: std::ffi::OsString = user.open_subkey(SOURCE_KEY).ok()?.get_value("Checkout").ok()?;
                let root = PathBuf::from(root);
                Some(Launch { executable: built_desktop(&root)?, source: Some(root) })
            }
            Edition::Development => {
                let executable = [KEY_READ, KEY_READ | KEY_WOW64_64KEY, KEY_READ | KEY_WOW64_32KEY]
                    .into_iter()
                    .find_map(|flags| {
                        let key = user.open_subkey_with_flags(UNINSTALL_KEY, flags).ok()?;
                        let directory: String = key.get_value("InstallLocation").ok()?;
                        registered_install(&directory)
                    })?;
                Some(Launch { executable, source: None })
            }
        }
    }

    pub(crate) fn switch(app: &tauri::AppHandle) -> Result<(), String> {
        let current = current_edition();
        target(current).ok_or("desktop_switch_target_missing")?;
        updater::safe_views(app, true)?;

        // The helper waits for the shell to release Tauri's single-instance lock.
        // EOF cancels the handoff if the backend refuses to shut down.
        let executable = std::env::current_exe().map_err(|_| "desktop_switch_launch_failed")?;
        let mut handoff = Command::new(executable)
            .args([HANDOFF, &std::process::id().to_string()])
            .stdin(Stdio::piped()).stdout(Stdio::null()).stderr(Stdio::null())
            .creation_flags(0x08000000)
            .spawn().map_err(|_| "desktop_switch_launch_failed")?;
        let mut signal = handoff.stdin.take().ok_or("desktop_switch_launch_failed")?;
        updater::stop_owned_runtime(None)?;
        if signal.write_all(b"1").is_err() {
            let _ = updater::recover_runtime();
            return Err("desktop_switch_launch_failed".into());
        }
        Ok(())
    }

    fn current_edition() -> Edition {
        if runtime_source_root().is_some() { Edition::Development } else { Edition::Installed }
    }

    fn wait_for_parent(pid: u32) -> bool {
        #[link(name = "kernel32")]
        extern "system" {
            fn OpenProcess(access: u32, inherit: i32, pid: u32) -> windows_sys::Win32::Foundation::HANDLE;
            fn WaitForSingleObject(process: windows_sys::Win32::Foundation::HANDLE, millis: u32) -> u32;
        }
        const SYNCHRONIZE: u32 = 0x00100000;
        let process = unsafe { OpenProcess(SYNCHRONIZE, 0, pid) };
        if process.is_null() {
            return std::io::Error::last_os_error().raw_os_error() == Some(ERROR_INVALID_PARAMETER as i32);
        }
        let exited = unsafe { WaitForSingleObject(process, 30_000) == WAIT_OBJECT_0 };
        unsafe { CloseHandle(process); }
        exited
    }

    pub(crate) fn run_handoff() -> bool {
        let mut args = std::env::args_os().skip(1);
        if args.next().as_deref() != Some(OsStr::new(HANDOFF)) { return false; }
        let Some(parent) = args.next().and_then(|pid| pid.to_str()?.parse::<u32>().ok()) else { return true; };
        let mut signal = [0u8];
        if std::io::stdin().read_exact(&mut signal).is_err() || signal != *b"1"
            || !wait_for_parent(parent) { return true; }

        if let Some(launch) = target(current_edition()) {
            if updater::port_closed() && launch.command().spawn().is_ok() { return true; }
        }
        crate::startup_trace("Desktop edition handoff failed; reopening the original edition");
        if let Ok(executable) = std::env::current_exe() {
            let _ = Command::new(executable).arg("--show-desktop").creation_flags(0x08000000).spawn();
        }
        true
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn installer_detection_requires_both_programs_in_absolute_directory() {
            let directory = std::env::temp_dir().join(format!("iwb-edition-{}", uuid::Uuid::new_v4()));
            std::fs::create_dir(&directory).unwrap();
            assert!(registered_install(".").is_none());
            std::fs::write(directory.join(DESKTOP_EXE), []).unwrap();
            let quoted = format!("\"{}\"", directory.display());
            assert!(registered_install(&quoted).is_none());
            std::fs::write(directory.join("iwb-runtime.exe"), []).unwrap();
            assert_eq!(registered_install(&quoted), Some(directory.join(DESKTOP_EXE)));
            std::fs::remove_dir_all(directory).unwrap();
        }
    }
}
