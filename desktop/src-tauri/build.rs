use std::env;
use std::fs;
use std::path::{Path, PathBuf};

const STUB_SIGNATURE: &str = "# WAYFINDER_DEV_STUB";

fn is_dev_stub(path: &Path) -> bool {
    if let Ok(metadata) = fs::metadata(path) {
        if metadata.len() < 1024 {
            if let Ok(content) = fs::read_to_string(path) {
                return content.contains(STUB_SIGNATURE);
            }
        }
    }
    false
}

fn create_dev_stub(path: &Path, target: &str) {
    let stub_content = format!(
        "#!/bin/sh\n{}\n# Auto-generated development placeholder for {}\n# In development, run the daemon via: uv run uvicorn core.server:app --port 8765\necho \"[Wayfinder Dev Stub] Sidecar placeholder active. Expecting external daemon on 127.0.0.1:8765\"\nexit 0\n",
        STUB_SIGNATURE, target
    );
    let _ = fs::write(path, stub_content);

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o755));
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

    tauri_build::build()
}

