use std::sync::Mutex;
use tauri::{Emitter, Manager};
use tauri_plugin_global_shortcut::ShortcutState;
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Thread-safe holder for the child daemon process handle.
pub struct DaemonProcess(pub Mutex<Option<CommandChild>>);

fn kill_daemon(app_handle: &tauri::AppHandle) {
    if let Some(state) = app_handle.try_state::<DaemonProcess>() {
        if let Ok(mut lock) = state.0.lock() {
            if let Some(child) = lock.take() {
                eprintln!("[Wayfinder] Terminating wayfinder-daemon child process...");
                let _ = child.kill();
            }
        }
    }
}

#[tauri::command]
fn exit_app(app_handle: tauri::AppHandle) {
    kill_daemon(&app_handle);
    app_handle.exit(0);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_shell::init())
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
            // Attempt to spawn the bundled Python sidecar daemon
            match app.shell().sidecar("wayfinder-daemon") {
                Ok(command) => {
                    match command.spawn() {
                        Ok((_rx, child)) => {
                            eprintln!("[Wayfinder] Embedded wayfinder-daemon spawned successfully.");
                            app.manage(DaemonProcess(Mutex::new(Some(child))));
                        }
                        Err(err) => {
                            eprintln!("[Wayfinder] Could not spawn wayfinder-daemon sidecar ({err}). Expecting external daemon.");
                            app.manage(DaemonProcess(Mutex::new(None)));
                        }
                    }
                }
                Err(err) => {
                    eprintln!("[Wayfinder] Sidecar not configured or not found ({err}). Expecting external daemon.");
                    app.manage(DaemonProcess(Mutex::new(None)));
                }
            }

            // Emit desktop toast on startup confirming Wayfinder is active
            let _ = app
                .notification()
                .builder()
                .title("Wayfinder Active (Alt+G)")
                .body("HUD ready in background. Set game to Borderless Windowed for overlay display.")
                .show();

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                kill_daemon(app_handle);
            }
        });
}
