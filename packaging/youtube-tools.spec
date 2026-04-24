# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — macOS (arm64) + Windows (x86_64) bundles.

Run from project root:
    pyinstaller packaging/youtube-tools.spec
"""
import platform
import sys
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).parent
IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
IS_APPLE_SILICON = IS_MACOS and platform.machine() == "arm64"


# ---------------------------------------------------------------- data files
# Ship the three scripts alongside the frozen app so paths.py can find them.
datas = [
    (str(PROJECT_ROOT / "parse.py"), "."),
    (str(PROJECT_ROOT / "download.py"), "."),
    (str(PROJECT_ROOT / "transcribe.py"), "."),
]


# ------------------------------------------------------------ bundled ffmpeg
# Optional: drop static ffmpeg + ffprobe into packaging/bin/<os>/ and they'll
# be bundled. If the directory is missing we build without them (user is
# expected to have ffmpeg on PATH).
if IS_MACOS:
    bin_dir = PROJECT_ROOT / "packaging" / "bin" / "macos-arm64"
elif IS_WINDOWS:
    bin_dir = PROJECT_ROOT / "packaging" / "bin" / "windows-x86_64"
else:
    bin_dir = None

binaries = []
if bin_dir and bin_dir.is_dir():
    for entry in bin_dir.iterdir():
        if entry.is_file():
            binaries.append((str(entry), "bin"))


# -------------------------------------------------------- hidden imports
hiddenimports = [
    "yt_dlp",
    "faster_whisper",
    "platformdirs",
]
# Only try to pack mlx on Apple Silicon; it doesn't exist elsewhere.
if IS_APPLE_SILICON:
    hiddenimports += ["mlx", "mlx_whisper"]


# ----------------------------------------------------------------- analysis
block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Icon resolution — optional. Drop files at packaging/icon.icns / icon.ico.
icon_icns = PROJECT_ROOT / "packaging" / "icon.icns"
icon_ico = PROJECT_ROOT / "packaging" / "icon.ico"
icon_path = None
if IS_MACOS and icon_icns.exists():
    icon_path = str(icon_icns)
elif IS_WINDOWS and icon_ico.exists():
    icon_path = str(icon_ico)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="youtube-tools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="youtube-tools",
)


# ------------------------------------------------------------------- macOS .app
if IS_MACOS:
    app = BUNDLE(
        coll,
        name="youtube-tools.app",
        icon=icon_path,
        bundle_identifier="com.youtube-tools.app",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
