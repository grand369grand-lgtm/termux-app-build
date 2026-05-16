#!/usr/bin/env python3
"""
Patch Anroot bootstrap zips to:
1. Replace com.termux with com.anroot in all files (text and ELF binaries)
2. Inject custom Anroot scripts and configurations

This script processes bootstrap zip files and replaces all references to
com.termux with com.anroot in both text files (scripts, configs) and
ELF binaries (RPATH/RUNPATH entries). It also injects custom Anroot
files for first-boot setup, auto-login, dpkg wrapping, etc.

Usage: python3 patch-bootstrap.py <zip_file> [zip_file ...]
"""

import os
import sys
import struct
import tempfile
import shutil
import zipfile

# The old and new package names
OLD_PREFIX = "com.termux"
NEW_PREFIX = "com.anroot"
OLD_PATH = "/data/data/com.termux"
NEW_PATH = "/data/data/com.anroot"


# ============================================================================
# CUSTOM ANROOT FILES TO INJECT
# ============================================================================

ANROOT_FIRST_BOOT = r'''#!/data/data/com.anroot/files/usr/bin/sh
# anroot-first-boot - First boot setup for Anroot
# Installs proot-distro, Debian, and configures auto-login

export PREFIX=/data/data/com.anroot/files/usr
export HOME=/data/data/com.anroot/files/home
export PATH=$PREFIX/bin:$PATH
export TMPDIR=$PREFIX/tmp
export LD_LIBRARY_PATH=$PREFIX/lib

LOG_PREFIX="[Anroot Setup]"

echo "$LOG_PREFIX === Anroot First Boot Setup Started ==="
echo "$LOG_PREFIX Date: $(date)"
echo "$LOG_PREFIX Prefix: $PREFIX"

# --- Setup dpkg wrapper ---
echo "$LOG_PREFIX Setting up dpkg wrapper..."
if [ -f "$PREFIX/bin/dpkg-wrap" ]; then
    # Save original dpkg as dpkg.bin
    if [ ! -f "$PREFIX/bin/dpkg.bin" ]; then
        cp "$PREFIX/bin/dpkg" "$PREFIX/bin/dpkg.bin"
    fi
    # Replace dpkg with our wrapper
    cp "$PREFIX/bin/dpkg-wrap" "$PREFIX/bin/dpkg"
    chmod 700 "$PREFIX/bin/dpkg"
    echo "$LOG_PREFIX dpkg wrapper installed."
else
    echo "$LOG_PREFIX WARNING: dpkg-wrap not found, skipping dpkg wrapper setup"
fi

# --- Setup Anroot welcome banner ---
echo "$LOG_PREFIX Setting up Anroot welcome banner..."
cat > "$PREFIX/etc/motd" << 'MOTDEOF'
  ___                         ____            _
 / _ \ _ __   ___ _ __ __ _  |  _ \ ___  ___| |_ ___
| |_| | '_ \ / _ \ '__/ _` | | |_) / _ \/ __| __/ __|
|  _  | |_) |  __/ | | (_| | |  _ <  __/\__ \ |_\__ \
|_| |_| .__/ \___|_|  \__,_| |_| \_\___||___/\__|___/
      |_|
  Anroot - Linux on Android

  Website: https://crossberry.vercel.app
  GitHub:  https://github.com/grand369grand-lgtm/anroot

  Quick Start:
    anroot-setup-storage  - Setup storage access
    anroot-update         - Update packages
    anroot-shell          - Open Anroot Termux shell

MOTDEOF
chmod 644 "$PREFIX/etc/motd"
echo "$LOG_PREFIX Welcome banner configured."

# --- Setup auto-login to Debian ---
echo "$LOG_PREFIX Setting up auto-login to Debian..."
mkdir -p "$PREFIX/etc/profile.d"
cat > "$PREFIX/etc/profile.d/anroot-autologin.sh" << 'AUTOLOGINEOF'
#!/data/data/com.anroot/files/usr/bin/sh
# Auto-login to Debian proot on every shell start
# Skip if already inside Debian or if Debian is not installed yet

if [ -n "$ANROOT_DEBIAN_ACTIVE" ]; then
    # Already inside Debian, do nothing
    return 0
fi

# Check if Debian is installed
DEBIAN_ROOTFS="/data/data/com.anroot/files/usr/var/proot-distro/installed-rootfs/debian"
if [ -d "$DEBIAN_ROOTFS" ]; then
    export ANROOT_DEBIAN_ACTIVE=1
    # Bind external storage into Debian if available
    STORAGE_BINDS=""
    if [ -d "/data/data/com.anroot/files/home/storage" ]; then
        STORAGE_BINDS="--bind /data/data/com.anroot/files/home/storage:/root/storage"
    fi
    if [ -d "/sdcard" ]; then
        STORAGE_BINDS="$STORAGE_BINDS --bind /sdcard:/root/sdcard"
    fi
    # Clear screen before entering Debian
    clear
    exec proot-distro login debian $STORAGE_BINDS
fi
AUTOLOGINEOF
chmod 700 "$PREFIX/etc/profile.d/anroot-autologin.sh"
echo "$LOG_PREFIX Auto-login configured."

# --- Setup home directory ---
echo "$LOG_PREFIX Setting up home directory..."
mkdir -p "$HOME"
cat > "$HOME/.bashrc" << 'BASHRC'
# ~/.bashrc: executed by bash(1) for non-login shells.
# Anroot custom bashrc

# If running interactively, don't do anything
case $- in
    *i*) ;;
      *) return;;
esac

# Don't put duplicate lines or lines starting with space in the history
HISTCONTROL=ignoreboth
shopt -s histappend
HISTSIZE=1000
HISTFILESIZE=2000
shopt -s checkwinsize

# Set prompt
if [ -n "$ANROOT_DEBIAN_ACTIVE" ]; then
    PS1='\[\033[01;32m\]anroot@debian\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
else
    PS1='\[\033[01;32m\]anroot\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
fi

# Aliases
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
alias anroot-update='apt update && apt upgrade -y'
alias anroot-shell='exit'
BASHRC
chmod 644 "$HOME/.bashrc"
echo "$LOG_PREFIX Home directory configured."

# --- Install proot-distro ---
echo "$LOG_PREFIX Installing proot-distro..."
# Use apt directly instead of pkg to avoid anroot-setup-package-manager dependency
apt update 2>&1 | tail -5
if [ $? -ne 0 ]; then
    echo "$LOG_PREFIX WARNING: apt update failed, trying pkg..."
    pkg update 2>&1 | tail -5
fi

apt install -y proot-distro 2>&1 | tail -10
if [ $? -ne 0 ]; then
    echo "$LOG_PREFIX WARNING: apt install proot-distro failed, trying pkg..."
    pkg install -y proot-distro 2>&1 | tail -10
fi

# Verify proot-distro is available
if ! command -v proot-distro >/dev/null 2>&1; then
    echo "$LOG_PREFIX ERROR: proot-distro installation failed!"
    echo "$LOG_PREFIX Try running manually: apt update && apt install proot-distro"
    # Don't exit - let the user try manually
else
    echo "$LOG_PREFIX proot-distro installed successfully."

    # --- Install Debian ---
    echo "$LOG_PREFIX Installing Debian (this may take several minutes)..."
    proot-distro install debian 2>&1 | tail -20

    # Verify Debian installation
    DEBIAN_ROOTFS="/data/data/com.anroot/files/usr/var/proot-distro/installed-rootfs/debian"
    if [ -d "$DEBIAN_ROOTFS" ]; then
        echo "$LOG_PREFIX Debian installed successfully."

        # --- Install essential packages inside Debian ---
        echo "$LOG_PREFIX Installing essential packages inside Debian..."
        proot-distro login debian -- apt update 2>&1 | tail -5
        proot-distro login debian -- apt install -y sudo ncurses-term nano 2>&1 | tail -10

        # --- Install Anroot custom commands inside Debian ---
        echo "$LOG_PREFIX Installing Anroot commands inside Debian..."
        mkdir -p "$DEBIAN_ROOTFS/usr/local/bin"

        # anroot-setup-storage command
        cat > "$DEBIAN_ROOTFS/usr/local/bin/anroot-setup-storage" << 'CMDEOF'
#!/bin/sh
# anroot-setup-storage - Setup external storage access in Anroot
echo "Setting up Anroot storage access..."
echo "Storage is automatically available at:"
echo "  /root/storage  - Termux storage symlinks"
echo "  /root/sdcard   - External storage (/sdcard)"
echo ""
echo "If storage is not accessible, run 'termux-setup-storage'"
echo "from the Anroot Termux shell (use 'anroot-shell' to exit Debian first)."
CMDEOF
        chmod 755 "$DEBIAN_ROOTFS/usr/local/bin/anroot-setup-storage"

        # anroot-info command
        cat > "$DEBIAN_ROOTFS/usr/local/bin/anroot-info" << 'CMDEOF'
#!/bin/sh
# anroot-info - Show Anroot system information
echo "=== Anroot System Information ==="
echo "App:       Anroot (Debian on Android)"
echo "Website:   https://crossberry.vercel.app"
echo "GitHub:    https://github.com/grand369grand-lgtm/anroot"
echo ""
echo "Debian version: $(cat /etc/debian_version 2>/dev/null || echo 'Unknown')"
echo "Kernel: $(uname -r)"
echo "Architecture: $(uname -m)"
echo "Uptime: $(uptime)"
CMDEOF
        chmod 755 "$DEBIAN_ROOTFS/usr/local/bin/anroot-info"

        # anroot-update command
        cat > "$DEBIAN_ROOTFS/usr/local/bin/anroot-update" << 'CMDEOF'
#!/bin/sh
# anroot-update - Update both Debian and Termux packages
echo "=== Updating Debian packages ==="
apt update && apt upgrade -y
echo ""
echo "=== Updating Anroot Termux packages ==="
echo "Run 'anroot-shell' to go to Termux shell, then 'pkg upgrade'"
CMDEOF
        chmod 755 "$DEBIAN_ROOTFS/usr/local/bin/anroot-update"

        # anroot-shell command (exit proot back to Termux shell)
        cat > "$DEBIAN_ROOTFS/usr/local/bin/anroot-shell" << 'CMDEOF'
#!/bin/sh
# anroot-shell - Exit Debian proot to return to Anroot Termux shell
echo "Exiting Debian. Type 'exit' again to close the terminal."
echo "To return to Debian, just start a new terminal session."
exit 0
CMDEOF
        chmod 755 "$DEBIAN_ROOTFS/usr/local/bin/anroot-shell"

        echo "$LOG_PREFIX Anroot commands installed in Debian."
    else
        echo "$LOG_PREFIX ERROR: Debian rootfs not found after installation!"
        echo "$LOG_PREFIX You can try manually: proot-distro install debian"
    fi
fi

# --- Mark first boot complete ---
rm -f "$PREFIX/ANROOT_FIRST_BOOT"

echo "$LOG_PREFIX === Anroot First Boot Setup Complete ==="
echo "$LOG_PREFIX Please restart the app to auto-login to Debian."
echo "$LOG_PREFIX If Debian was not installed, run: proot-distro install debian"
'''

DPKG_WRAP = r'''#!/data/data/com.anroot/files/usr/bin/sh
# dpkg-wrap - Wrapper for dpkg that translates com.termux paths to com.anroot
# This intercepts .deb package installations and rewrites paths inside them
# so that packages designed for Termux work with Anroot's com.anroot paths.

export PREFIX=/data/data/com.anroot/files/usr
DPKG_BIN="$PREFIX/bin/dpkg.bin"

# If dpkg.bin doesn't exist, we can't wrap
if [ ! -f "$DPKG_BIN" ]; then
    # Fall back to original dpkg if it exists
    if [ -f "$PREFIX/bin/dpkg.orig" ]; then
        exec "$PREFIX/bin/dpkg.orig" "$@"
    fi
    echo "Error: dpkg.bin not found" >&2
    exit 1
fi

# Scan arguments for .deb files
DEB_FILES=""
OTHER_ARGS=""
for arg in "$@"; do
    case "$arg" in
        *.deb)
            if [ -f "$arg" ]; then
                DEB_FILES="$DEB_FILES $arg"
            else
                OTHER_ARGS="$OTHER_ARGS $arg"
            fi
            ;;
        *)
            OTHER_ARGS="$OTHER_ARGS $arg"
            ;;
    esac
done

# If no .deb files, just pass through to real dpkg
if [ -z "$DEB_FILES" ]; then
    exec "$DPKG_BIN" "$@"
fi

# Process each .deb file
for deb in $DEB_FILES; do
    TMPDIR=$(mktemp -d)
    EXTRACT_DIR="$TMPDIR/extract"

    # Extract the .deb
    "$DPKG_BIN" --fsys-tarfile "$deb" 2>/dev/null | tar -xf - -C "$TMPDIR" 2>/dev/null
    if [ $? -ne 0 ]; then
        # Can't extract, just use as-is
        rm -rf "$TMPDIR"
        OTHER_ARGS="$OTHER_ARGS $deb"
        continue
    fi

    # Check if any file contains com.termux references
    NEEDS_PATCH=0
    if grep -rl "com.termux" "$TMPDIR" >/dev/null 2>&1; then
        NEEDS_PATCH=1
    fi

    if [ $NEEDS_PATCH -eq 1 ]; then
        # Replace com.termux with com.anroot in all text files
        find "$TMPDIR" -type f | while read f; do
            if file "$f" | grep -q "text\|ASCII\|script\|shell"; then
                sed -i 's|com\.termux|com.anroot|g' "$f" 2>/dev/null
                sed -i 's|/data/data/com\.termux|/data/data/com.anroot|g' "$f" 2>/dev/null
            fi
        done

        # Rebuild the .deb
        MODIFIED_DEB="$TMPDIR/modified.deb"
        # Create control and data tarballs
        if [ -d "$TMPDIR/control" ] && [ -d "$TMPDIR/data" ]; then
            cd "$TMPDIR/control" && tar -cf "$TMPDIR/control.tar" . 2>/dev/null
            cd "$TMPDIR/data" && tar -cf "$TMPDIR/data.tar" . 2>/dev/null
            # Reassemble using ar
            if command -v ar >/dev/null 2>&1; then
                cd "$TMPDIR"
                ar r "$MODIFIED_DEB" debian-binary control.tar data.tar 2>/dev/null
            fi
        fi

        if [ -f "$MODIFIED_DEB" ]; then
            # Install the modified .deb
            "$DPKG_BIN" $OTHER_ARGS "$MODIFIED_DEB"
            rm -rf "$TMPDIR"
            continue
        fi
    fi

    rm -rf "$TMPDIR"
    # Install the original .deb
    "$DPKG_BIN" $OTHER_ARGS "$deb"
done
'''

ANROOT_PKG = r'''#!/data/data/com.anroot/files/usr/bin/sh
# anroot-pkg - Wrapper for pkg command
export PREFIX=/data/data/com.anroot/files/usr
exec "$PREFIX/bin/pkg" "$@"
'''

ANROOT_CHANGE_REPO = r'''#!/data/data/com.anroot/files/usr/bin/sh
# anroot-change-repo - Wrapper for termux-change-repo
export PREFIX=/data/data/com.anroot/files/usr
if command -v termux-change-repo >/dev/null 2>&1; then
    exec termux-change-repo "$@"
else
    echo "termux-change-repo not found"
    exit 1
fi
'''

ANROOT_SETUP_STORAGE = r'''#!/data/data/com.anroot/files/usr/bin/sh
# anroot-setup-storage - Setup storage access
# This requests Android storage permission and creates symlinks
export PREFIX=/data/data/com.anroot/files/usr
if command -v termux-setup-storage >/dev/null 2>&1; then
    exec termux-setup-storage "$@"
else
    echo "Requesting storage access..."
    echo "Please grant storage permission when prompted."
    echo "Storage will be available at ~/storage/"
fi
'''

ANROOT_SETUP_PACKAGE_MANAGER = r'''#!/data/data/com.anroot/files/usr/bin/sh
# anroot-setup-package-manager - Wrapper for termux-setup-package-manager
# The pkg script calls this, but after com.termux->com.anroot replacement,
# the binary name gets changed. This wrapper redirects to the real binary.
export PREFIX=/data/data/com.anroot/files/usr
if command -v termux-setup-package-manager >/dev/null 2>&1; then
    exec termux-setup-package-manager "$@"
else
    # If termux-setup-package-manager doesn't exist either,
    # just set up the default repo manually
    echo "Setting up Anroot package manager..."
    mkdir -p $PREFIX/etc/apt/sources.list.d
    echo "deb https://packages.termux.dev/apt/termux-main stable main" > $PREFIX/etc/apt/sources.list
    apt update 2>/dev/null
fi
'''

ANROOT_PATH_SH = r'''#!/data/data/com.anroot/files/usr/bin/sh
# anroot-path.sh - Set up Anroot environment and clear screen on startup
# This runs on every shell session start via profile.d
export LD_LIBRARY_PATH=/data/data/com.anroot/files/usr/lib
# Clear screen to hide Termux bootstrap messages
clear
'''

# Map of files to inject into the bootstrap zip
# Key = path in zip (relative to $PREFIX), Value = content
INJECTED_FILES = {
    "bin/anroot-first-boot": ANROOT_FIRST_BOOT,
    "bin/dpkg-wrap": DPKG_WRAP,
    "bin/anroot-pkg": ANROOT_PKG,
    "bin/anroot-change-repo": ANROOT_CHANGE_REPO,
    "bin/anroot-setup-storage": ANROOT_SETUP_STORAGE,
    "bin/anroot-setup-package-manager": ANROOT_SETUP_PACKAGE_MANAGER,
    "etc/profile.d/anroot-path.sh": ANROOT_PATH_SH,
}


def is_elf(data):
    """Check if data starts with ELF magic bytes."""
    return data[:4] == b'\x7fELF'


def patch_elf_rpath(data):
    """
    Patch ELF binary RPATH/RUNPATH entries.
    Replace /data/data/com.termux with /data/data/com.anroot in .dynstr.

    Since the new path is shorter, we pad the remaining bytes with nulls.
    This is safe because C strings are null-terminated.
    """
    if not is_elf(data):
        return data

    old_bytes = OLD_PATH.encode('ascii')
    new_bytes = NEW_PATH.encode('ascii')

    # We need the replacement to be the same length for ELF structural integrity
    # Pad with null bytes since C strings are null-terminated
    if len(new_bytes) < len(old_bytes):
        padded_new = new_bytes + b'\x00' * (len(old_bytes) - len(new_bytes))
    else:
        padded_new = new_bytes[:len(old_bytes)]

    # Replace all occurrences of the old path with the padded new path
    patched = data.replace(old_bytes, padded_new)

    return patched


def patch_text(data):
    """
    Patch text files (scripts, configs) by replacing com.termux with com.anroot.
    For text files, the replacement can be shorter since there's no structural constraint.
    Also replaces "Termux" with "Anroot" in user-visible text, but NOT in internal
    command names that must remain as-is (like termux-change-repo).
    """
    try:
        text = data.decode('utf-8', errors='replace')
        # Replace the package name reference
        text = text.replace(OLD_PREFIX, NEW_PREFIX)
        # Also replace full paths
        text = text.replace(OLD_PATH, NEW_PATH)
        return text.encode('utf-8', errors='replace')
    except Exception:
        return data


def is_text_file(data, filename):
    """Determine if a file is likely a text file."""
    # Check by extension
    text_extensions = {
        '.sh', '.bash', '.zsh', '.py', '.pl', '.rb', '.conf', '.cfg',
        '.txt', '.md', '.xml', '.json', '.yaml', '.yml', '.toml',
        '.properties', '.list', '.sources', '.installs', '.control',
        '.desc', '.pro', '.cmake', '.pc', '.la', '.header',
    }
    _, ext = os.path.splitext(filename)
    if ext.lower() in text_extensions:
        return True

    # Check for shebang
    if data[:2] == b'#!':
        return True

    # Check if data contains null bytes (binary)
    if b'\x00' in data[:8192]:
        return False

    # Try to decode as UTF-8
    try:
        data[:8192].decode('utf-8')
        return True
    except (UnicodeDecodeError, ValueError):
        return False


def patch_zip(zip_path):
    """Patch a bootstrap zip file in place, adding Anroot customizations."""
    print(f"Patching {zip_path}...")

    # Read the original zip
    with zipfile.ZipFile(zip_path, 'r') as zf:
        entries = zf.infolist()
        patched_entries = {}

        for entry in entries:
            if entry.is_dir():
                continue

            data = zf.read(entry.filename)
            original_size = len(data)

            if is_elf(data):
                # Patch ELF binary
                patched_data = patch_elf_rpath(data)
                patch_type = "ELF"
            elif is_text_file(data, entry.filename):
                # Patch text file
                patched_data = patch_text(data)
                patch_type = "text"
            else:
                # For other binary files, try ELF-style byte replacement
                patched_data = data.replace(
                    OLD_PATH.encode('ascii'),
                    NEW_PATH.encode('ascii') + b'\x00' * (len(OLD_PATH) - len(NEW_PATH))
                )
                patched_data = patched_data.replace(
                    OLD_PREFIX.encode('ascii'),
                    NEW_PREFIX.encode('ascii') + b'\x00' * (len(OLD_PREFIX) - len(NEW_PREFIX))
                )
                patch_type = "binary"

            if patched_data != data:
                print(f"  Patched ({patch_type}): {entry.filename} ({original_size} bytes)")

            patched_entries[entry.filename] = patched_data

    # Inject custom Anroot files
    for inject_path, content in INJECTED_FILES.items():
        content_bytes = content.encode('utf-8')
        patched_entries[inject_path] = content_bytes
        print(f"  Injected: {inject_path} ({len(content_bytes)} bytes)")

    # Write the patched zip
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            if entry.is_dir():
                zf.writestr(entry, b'')
            elif entry.filename in patched_entries:
                zf.writestr(entry, patched_entries[entry.filename])
            else:
                zf.writestr(entry, patched_entries.get(entry.filename, b''))

        # Add any new injected files that weren't already in the zip
        for inject_path, content_bytes in INJECTED_FILES.items():
            if inject_path not in [e.filename for e in entries if not e.is_dir()]:
                zf.writestr(inject_path, content_bytes)

    print(f"Done patching {zip_path}")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <zip_file> [zip_file ...]")
        sys.exit(1)

    for zip_path in sys.argv[1:]:
        if not os.path.exists(zip_path):
            print(f"Error: {zip_path} not found")
            continue
        patch_zip(zip_path)


if __name__ == '__main__':
    main()
