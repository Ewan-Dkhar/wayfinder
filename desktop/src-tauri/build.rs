use std::env;
use std::fs;
use std::path::{Path, PathBuf};

const STUB_SIGNATURE: &str = "# WAYFINDER_DEV_STUB";

fn is_dev_stub(path: &Path) -> bool {
    if let Ok(metadata) = fs::metadata(path) {
        // Real compiled PyInstaller sidecars are > 50MB; dev stubs are tiny (< 5MB)
        if metadata.len() < 5 * 1024 * 1024 {
            if let Ok(bytes) = fs::read(path) {
                let sig = STUB_SIGNATURE.as_bytes();
                return bytes.windows(sig.len()).any(|w| w == sig);
            }
        }
    }
    false
}

fn create_dev_stub(path: &Path, target: &str) {
    let rustc = env::var("RUSTC").unwrap_or_else(|_| "rustc".to_string());
    let temp_src = path.with_extension("stub_temp.rs");
    let stub_source = format!(
        "fn main() {{\n    println!(\"[Wayfinder Dev Stub] Sidecar placeholder active for {target}. Expecting external daemon on 127.0.0.1:8765: {STUB_SIGNATURE}\");\n}}\n"
    );

    let mut compiled = false;
    if fs::write(&temp_src, &stub_source).is_ok() {
        let output = std::process::Command::new(&rustc)
            .arg("--target")
            .arg(target)
            .arg("--crate-name")
            .arg("dev_stub")
            .arg("-O")
            .arg("-o")
            .arg(path)
            .arg(&temp_src)
            .output();

        let _ = fs::remove_file(&temp_src);
        if let Ok(out) = output {
            if out.status.success() {
                compiled = true;
            }
        }
    }

    if !compiled {
        // Fallback script/text stub
        let stub_content = if target.contains("windows") {
            format!(
                "@echo off\r\nrem {STUB_SIGNATURE}\r\nrem Auto-generated development placeholder for {target}\r\necho [Wayfinder Dev Stub] Sidecar placeholder active. Expecting external daemon on 127.0.0.1:8765\r\nexit /b 0\r\n"
            )
        } else {
            format!(
                "#!/bin/sh\n{STUB_SIGNATURE}\n# Auto-generated development placeholder for {target}\n# In development, run the daemon via: uv run uvicorn core.server:app --port 8765\necho \"[Wayfinder Dev Stub] Sidecar placeholder active. Expecting external daemon on 127.0.0.1:8765\"\nexit 0\n"
            )
        };
        let _ = fs::write(path, stub_content);

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o755));
        }
    }
}

fn main() {
    let target = env::var("TARGET").unwrap_or_default();
    let profile = env::var("PROFILE").unwrap_or_default();
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap_or_default());

    let binary_name = if target.contains("windows") {
        format!("wayfinder-daemon-{target}.exe")
    } else {
        format!("wayfinder-daemon-{target}")
    };

    let binaries_dir = manifest_dir.join("binaries");
    let binary_path = binaries_dir.join(&binary_name);

    println!("cargo:rustc-check-cfg=cfg(wayfinder_dev_stub)");
    println!("cargo:rerun-if-changed={}", binary_path.display());

    if !binary_path.exists() {
        if profile == "debug" {
            let _ = fs::create_dir_all(&binaries_dir);
            create_dev_stub(&binary_path, &target);
            println!("cargo:warning=Created development sidecar stub at: {}", binary_path.display());
            println!("cargo:warning=In development mode, run the Python daemon via: uv run uvicorn core.server:app --port 8765");
        } else {
            panic!(
                "\n\n❌ [Wayfinder] Production build failed: Missing compiled sidecar binary at:\n   {}\n\n👉 Please compile the standalone sidecar before bundling:\n   uv run python scripts/build_sidecar.py\n\n",
                binary_path.display()
            );
        }
    } else if profile == "release" && is_dev_stub(&binary_path) {
        panic!(
            "\n\n❌ [Wayfinder] Production build cannot package the development stub binary!\n👉 Please compile the real standalone daemon before bundling:\n   uv run python scripts/build_sidecar.py\n\n"
        );
    }

    if is_dev_stub(&binary_path) {
        println!("cargo:rustc-cfg=wayfinder_dev_stub");
    }

    tauri_build::build()
}

