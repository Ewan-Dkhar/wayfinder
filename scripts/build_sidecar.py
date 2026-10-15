#!/usr/bin/env python3
"""Builds the standalone wayfinder-daemon binary and stages it as a Tauri sidecar.

Steps:
1. Detects host Rust target triple via `rustc -vV` (e.g. x86_64-unknown-linux-gnu).
2. Runs PyInstaller against `wayfinder-daemon.spec`.
3. Copies frozen executable to `desktop/src-tauri/binaries/wayfinder-daemon-<TARGET_TRIPLE>`.
4. Performs an automated live smoke test against the compiled binary on port 8769.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TAURI_BINARIES_DIR = PROJECT_ROOT / "desktop" / "src-tauri" / "binaries"
DIST_DIR = PROJECT_ROOT / "dist"


def get_rust_target_triple() -> str:
    """Queries rustc for the host platform's target triple."""
    try:
        output = subprocess.check_output(["rustc", "-vV"], text=True)
        for line in output.splitlines():
            if line.startswith("host:"):
                return line.split(":", 1)[1].strip()
    except Exception as err:
        print(f"⚠️  Could not determine target triple from rustc ({err}). Falling back to x86_64-unknown-linux-gnu.")
    return "x86_64-unknown-linux-gnu"


def build_pyinstaller() -> Path:
    """Runs PyInstaller using wayfinder-daemon.spec."""
    print("\n📦 [1/4] Running PyInstaller to freeze Python micro-daemon...")
    spec_file = PROJECT_ROOT / "wayfinder-daemon.spec"
    if not spec_file.exists():
        raise FileNotFoundError(f"Spec file missing: {spec_file}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_file),
    ]

    subprocess.check_call(cmd, cwd=PROJECT_ROOT)

    binary_name = "wayfinder-daemon.exe" if sys.platform == "win32" else "wayfinder-daemon"
    compiled_binary = DIST_DIR / binary_name
    if not compiled_binary.exists():
        raise FileNotFoundError(f"Expected compiled binary not found at: {compiled_binary}")

    size_mb = compiled_binary.stat().st_size / (1024 * 1024)
    print(f"✅ [2/4] PyInstaller binary compiled successfully: {compiled_binary} ({size_mb:.1f} MB)")
    return compiled_binary


def stage_tauri_sidecar(compiled_binary: Path) -> Path:
    """Copies the compiled binary with target triple to desktop/src-tauri/binaries/."""
    print("\n🚚 [3/4] Staging sidecar binary for Tauri v2...")
    TAURI_BINARIES_DIR.mkdir(parents=True, exist_ok=True)

    triple = get_rust_target_triple()
    ext = ".exe" if sys.platform == "win32" else ""
    staged_name = f"wayfinder-daemon-{triple}{ext}"
    destination = TAURI_BINARIES_DIR / staged_name

    shutil.copy2(compiled_binary, destination)
    if sys.platform != "win32":
        destination.chmod(0o755)

    print(f"✅ Staged sidecar binary: {destination}")
    return destination


def smoke_test_binary(binary_path: Path) -> None:
    """Starts the compiled binary on a temporary port and verifies /health endpoint."""
    print("\n🔍 [4/4] Performing live smoke test on compiled sidecar binary...")
    import httpx

    test_port = 8769
    env = os.environ.copy()
    env["WAYFINDER_PORT"] = str(test_port)

    proc = subprocess.Popen(
        [str(binary_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        health_ok = False
        start_time = time.time()
        while time.time() - start_time < 12.0:
            if proc.poll() is not None:
                _, err = proc.communicate()
                raise RuntimeError(f"Binary exited prematurely with code {proc.returncode}:\n{err}")
            try:
                with httpx.Client(timeout=1.0) as client:
                    res = client.get(f"http://127.0.0.1:{test_port}/health")
                    if res.status_code == 200:
                        data = res.json()
                        print(f"   • Daemon status:    {data.get('status')}")
                        print(f"   • Database OK:      {data.get('db_ok')}")
                        print(f"   • Indexed chunks:   {data.get('indexed_chunks')}")
                        print(f"   • Active model:     {data.get('model')}")
                        health_ok = True
                        break
            except Exception:
                time.sleep(0.3)

        if not health_ok:
            raise TimeoutError("Compiled binary did not respond on /health within 12 seconds.")

        print("🎉 [SUCCESS] Compiled binary passed all health probes!")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    print("=" * 60)
    print("  Wayfinder Standalone Sidecar Packaging Pipeline")
    print("=" * 60)

    try:
        binary = build_pyinstaller()
        staged = stage_tauri_sidecar(binary)
        smoke_test_binary(staged)
        print("\n🚀 Ready for production build: `cd desktop && npm run tauri build`\n")
    except Exception as err:
        print(f"\n❌ Packaging failed: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
