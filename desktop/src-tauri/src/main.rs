// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    #[cfg(target_os = "linux")]
    {
        unsafe {
            // Fix WebKitGTK DMA-BUF / GBM buffer allocation failures on NVIDIA proprietary drivers
            if std::env::var("WEBKIT_DISABLE_DMABUF_RENDERER").is_err() {
                std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
            }
            // Force XWayland backend on Linux for flawless transparent window compositing
            if std::env::var("GDK_BACKEND").is_err() {
                std::env::set_var("GDK_BACKEND", "x11");
            }
        }
    }

    desktop_lib::run()
}
