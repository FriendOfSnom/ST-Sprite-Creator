#!/usr/bin/env python3
"""
Build script for ST Sprite Creator standalone executable.

This script:
1. Ensures rembg models are pre-downloaded (so they're bundled in the exe)
2. Runs PyInstaller with the spec file
3. Reports the output location

Usage:
    python build_exe.py

Requirements:
    pip install pyinstaller

Output:
    dist/ST Sprite Creator/ST Sprite Creator.exe
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def check_pyinstaller():
    """Check if PyInstaller is installed."""
    try:
        import PyInstaller
        print(f"[OK] PyInstaller version: {PyInstaller.__version__}")
        return True
    except ImportError:
        print("[ERROR] PyInstaller not installed!")
        print("       Run: pip install pyinstaller")
        return False


def pre_download_rembg_models():
    """
    Pre-download rembg models so they're available for bundling.

    rembg downloads models on first use to ~/.u2net/
    We trigger a download here so the models exist before packaging.
    """
    print("\n[INFO] Pre-downloading rembg models (this may take a while on first run)...")

    try:
        from rembg import remove
        from PIL import Image
        import io

        # Create a tiny test image
        test_img = Image.new('RGBA', (10, 10), (255, 0, 0, 255))

        # Run rembg once to trigger model download
        # This downloads the u2net model (~176MB) to ~/.u2net/
        output_img = remove(test_img)

        print("[OK] rembg models ready")

        # Check where models are stored
        home = Path.home()
        u2net_dir = home / ".u2net"
        if u2net_dir.exists():
            models = list(u2net_dir.glob("*.onnx"))
            for model in models:
                size_mb = model.stat().st_size / (1024 * 1024)
                print(f"     Found model: {model.name} ({size_mb:.1f} MB)")

        return True

    except Exception as e:
        print(f"[WARNING] Could not pre-download rembg models: {e}")
        print("          Users may need to download models on first use.")
        return False


def clean_build_dirs():
    """Clean previous build artifacts."""
    print("\n[INFO] Cleaning previous build artifacts...")

    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        dir_path = Path(dir_name)
        if dir_path.exists():
            print(f"       Removing {dir_name}/")
            shutil.rmtree(dir_path)

    print("[OK] Clean complete")


def run_pyinstaller():
    """Run PyInstaller with the spec file."""
    print("\n[INFO] Running PyInstaller...")
    print("       This may take several minutes...\n")

    spec_file = Path(__file__).parent / "sprite_creator.spec"

    if not spec_file.exists():
        print(f"[ERROR] Spec file not found: {spec_file}")
        return False

    cmd = [sys.executable, "-m", "PyInstaller", str(spec_file), "--noconfirm"]

    try:
        result = subprocess.run(cmd, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] PyInstaller failed with code {e.returncode}")
        return False
    except FileNotFoundError:
        print("[ERROR] PyInstaller command not found. Is it installed?")
        return False


def report_output():
    """Report the build output location and size."""
    output_dir = Path("dist") / "ST Sprite Creator"

    if not output_dir.exists():
        print("\n[ERROR] Output directory not found!")
        return

    print("\n" + "=" * 60)
    print("BUILD COMPLETE!")
    print("=" * 60)

    # Find the exe
    exe_name = "ST Sprite Creator.exe"
    exe_path = output_dir / exe_name

    if exe_path.exists():
        exe_size = exe_path.stat().st_size / (1024 * 1024)
        print(f"\nExecutable: {exe_path}")
        print(f"Size: {exe_size:.1f} MB")

    # Calculate total folder size
    total_size = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file())
    total_size_mb = total_size / (1024 * 1024)

    print(f"\nTotal folder size: {total_size_mb:.1f} MB")
    print(f"Location: {output_dir.absolute()}")

    print("\n" + "-" * 60)
    print("DISTRIBUTION:")
    print(f"  1. Zip the '{output_dir}' folder")
    print("  2. Users extract and run 'ST Sprite Creator.exe'")
    print("-" * 60)


def main():
    """Main build process."""
    print("=" * 60)
    print("ST Sprite Creator - Build Script")
    print("=" * 60)

    # Step 1: Check PyInstaller
    if not check_pyinstaller():
        sys.exit(1)

    # Step 2: Pre-download rembg models
    pre_download_rembg_models()

    # Step 3: Clean previous builds
    clean_build_dirs()

    # Step 4: Run PyInstaller
    if not run_pyinstaller():
        print("\n[ERROR] Build failed!")
        sys.exit(1)

    # Step 5: Report output
    report_output()

    print("\n[SUCCESS] Build completed successfully!")


if __name__ == "__main__":
    main()
