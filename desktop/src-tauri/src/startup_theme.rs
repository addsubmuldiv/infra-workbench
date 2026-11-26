use std::{path::Path, time::Duration};

use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use tauri::window::Color;

const THEME_TOKENS: &str = include_str!("../../../frontend/src/themeTokens.css");
const GLASS_TOKENS: &str = include_str!("../../../frontend/src/vendor/solid-glass.css");

pub struct StartupTheme {
    id: String,
    pub background: Color,
}

impl StartupTheme {
    pub fn load(data: Option<&Path>) -> Self {
        if let Some(id) = data.and_then(saved_theme) {
            if let Some(background) = theme_background(&id) {
                return Self { id, background };
            }
        }
        Self {
            id: "daylight".into(),
            background: theme_background("daylight").unwrap_or(Color(242, 245, 249, 255)),
        }
    }

    pub fn initialization_script(&self) -> String {
        let theme = json!({"id": self.id, "css": format!("{THEME_TOKENS}\n{GLASS_TOKENS}")});
        format!("window.__iwbStartupTheme = {theme};")
    }
}

fn saved_theme(data: &Path) -> Option<String> {
    // The tray may be offline. Read the shared preference without creating or
    // migrating its store, and never wait behind an active database writer.
    let database = Connection::open_with_flags(
        data.join("workbench.db"),
        OpenFlags::SQLITE_OPEN_READ_ONLY,
    ).ok()?;
    database.busy_timeout(Duration::ZERO).ok()?;
    let value: String = database.query_row(
        "SELECT value FROM config WHERE id = 'workspace_ui_state_v1'",
        [],
        |row| row.get(0),
    ).ok()?;
    let state: Value = serde_json::from_str(&value).ok()?;
    let preferences: Value = serde_json::from_str(
        state["values"]["infra-workbench:preferences:v1"].as_str()?,
    ).ok()?;
    Some(preferences["theme"].as_str()?.to_owned())
}

fn theme_background(id: &str) -> Option<Color> {
    let selector = format!("[data-theme=\"{id}\"]");
    let mut background = None;
    let mut native_background = None;
    // Match the exact selectors and opaque tokens also used by the native float.
    for rule in THEME_TOKENS.split('}') {
        let Some((selectors, declarations)) = rule.rsplit_once('{') else { continue };
        let selectors = selectors.lines().last().unwrap_or_default();
        if !selectors.split(',').any(|part| part.trim() == selector) {
            continue;
        }
        for declaration in declarations.split(';') {
            let Some((name, value)) = declaration.split_once(':') else { continue };
            match name.trim() {
                "--bg" => background = hex_color(value.trim()).or(background),
                "--native-bg" => native_background = hex_color(value.trim()).or(native_background),
                _ => (),
            }
        }
    }
    native_background.or(background)
}

fn hex_color(value: &str) -> Option<Color> {
    let hex = value.strip_prefix('#').filter(|hex| hex.len() == 6)?;
    let rgb = u32::from_str_radix(hex, 16).ok()?;
    Some(Color((rgb >> 16) as u8, (rgb >> 8) as u8, rgb as u8, 255))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn saved_theme_is_available_before_the_backend_starts() {
        let directory = std::env::temp_dir().join(format!("iwb-startup-theme-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&directory).unwrap();
        let path = directory.join("workbench.db");
        assert_eq!(StartupTheme::load(Some(&directory)).id, "daylight");
        assert!(!path.exists());

        let database = Connection::open(&path).unwrap();
        database.execute("CREATE TABLE config (id TEXT PRIMARY KEY, value TEXT NOT NULL)", []).unwrap();
        for (id, expected, rgb) in [
            ("midnight", "midnight", Color(17, 27, 40, 255)),
            ("paper", "paper", Color(244, 240, 232, 255)),
            ("glass-dusk", "glass-dusk", Color(33, 25, 37, 255)),
            ("glass-black", "glass-black", Color(0, 0, 0, 255)),
            ("unknown", "daylight", Color(242, 245, 249, 255)),
        ] {
            let preferences = json!({"theme": id, "hostIds": null}).to_string();
            let state = json!({"revision": 1, "values": {"infra-workbench:preferences:v1": preferences}});
            database.execute(
                "INSERT OR REPLACE INTO config VALUES ('workspace_ui_state_v1', ?1)",
                [state.to_string()],
            ).unwrap();
            let startup = StartupTheme::load(Some(&directory));
            assert_eq!(startup.id, expected);
            assert_eq!(startup.background, rgb);
        }
        drop(database);
        std::fs::remove_file(path).unwrap();
        std::fs::remove_dir(directory).unwrap();
    }
}
