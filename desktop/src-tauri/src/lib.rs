use tauri::{Emitter, Manager};
use tauri_plugin_global_shortcut::ShortcutState;
use tauri_plugin_notification::NotificationExt;

#[tauri::command]
fn exit_app(app_handle: tauri::AppHandle) {
    app_handle.exit(0);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![exit_app])
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_shortcut("Alt+G")
                .expect("Failed to parse Alt+G shortcut")
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        if let Some(window) = app.get_webview_window("main") {
                            if let Ok(is_visible) = window.is_visible() {
                                if is_visible {
                                    let _ = window.hide();
                                } else {
                                    let _ = window.show();
                                    let _ = window.unminimize();
                                    let _ = window.set_focus();
                                    let _ = window.emit("focus-input", ());
                                }
                            }
                        }
                    }
                })
                .build(),
        )
        .setup(|app| {
            // Emit desktop toast on startup confirming Wayfinder is active
            let _ = app
                .notification()
                .builder()
                .title("Wayfinder Active (Alt+G)")
                .body("HUD ready in background. Set game to Borderless Windowed for overlay display.")
                .show();

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

