#!/usr/bin/env python3
"""
Patch Anroot bootstrap zips to:
1. Replace com.termux with com.anroot in all files (text and ELF binaries)
2. Inject custom Anroot scripts and configurations
3. Replace dpkg with dpkg-wrap that rewrites com.termux paths in .deb packages
4. Inject a minimal 'file' command stub needed by the original dpkg script

Usage: python3 patch-bootstrap.py <zip_file> [zip_file ...]
"""

import os
import sys
import zipfile

OLD_PREFIX = "com.termux"
NEW_PREFIX = "com.anroot"
OLD_PATH = "/data/data/com.termux"
NEW_PATH = "/data/data/com.anroot"


# ============================================================================
# Minimal 'file' command stub - dpkg's wrapper script uses 'file -b'
# ============================================================================
FILE_STUB = r'''#!/data/data/com.anroot/files/usr/bin/sh
# Minimal file(1) command replacement for Anroot
# The dpkg wrapper script uses "file -b" to check package format.
# If the real 'file' command is installed later, it overrides this stub.

BRIEF=0
FILES=""

while [ $# -gt 0 ]; do
    case "$1" in
        -b|--brief) BRIEF=1 ;;
        -h|--help)
            echo "Usage: file [options] <file>"
            echo "Minimal file command replacement for Anroot"
            exit 0
            ;;
        -*) ;;
        *) FILES="$FILES $1" ;;
    esac
    shift
done

for f in $FILES; do
    if [ ! -e "$f" ]; then
        [ $BRIEF -eq 0 ] && echo "$f: cannot open"
        continue
    fi
    case "$f" in
        *.deb)
            if [ $BRIEF -eq 1 ]; then echo "Debian binary package (format 2.0)"
            else echo "$f: Debian binary package (format 2.0)"; fi
            ;;
        *.tar|*.tar.gz|*.tgz|*.tar.xz|*.tar.bz2|*.tar.zst)
            if [ $BRIEF -eq 1 ]; then echo "POSIX tar archive"
            else echo "$f: POSIX tar archive"; fi
            ;;
        *.zip|*.jar|*.apk)
            if [ $BRIEF -eq 1 ]; then echo "Zip archive data"
            else echo "$f: Zip archive data"; fi
            ;;
        *.so|*.so.*)
            if [ $BRIEF -eq 1 ]; then echo "ELF shared object"
            else echo "$f: ELF shared object"; fi
            ;;
        *)
            if [ -r "$f" ]; then
                MAGIC=$(dd if="$f" bs=4 count=1 2>/dev/null | od -A n -t x1 | tr -d ' ')
                case "$MAGIC" in
                    7f454c46)
                        if [ $BRIEF -eq 1 ]; then echo "ELF"
                        else echo "$f: ELF"; fi
                        ;;
                    504b0304)
                        if [ $BRIEF -eq 1 ]; then echo "Zip archive data"
                        else echo "$f: Zip archive data"; fi
                        ;;
                    1f8b*)
                        if [ $BRIEF -eq 1 ]; then echo "gzip compressed data"
                        else echo "$f: gzip compressed data"; fi
                        ;;
                    2321*)
                        if [ $BRIEF -eq 1 ]; then echo "POSIX shell script text executable"
                        else echo "$f: POSIX shell script text executable"; fi
                        ;;
                    *)
                        if [ $BRIEF -eq 1 ]; then echo "data"
                        else echo "$f: data"; fi
                        ;;
                esac
            else
                if [ $BRIEF -eq 1 ]; then echo "data"
                else echo "$f: data"; fi
            fi
            ;;
    esac
done
'''


# ============================================================================
# dpkg-wrap v3 - Replaces bin/dpkg in bootstrap
# Rewrites com.termux→com.anroot paths in .deb packages before installing
# Calls the original dpkg (saved as dpkg.real) for actual operations
# ============================================================================
DPKG_WRAP = r'''#!/data/data/com.anroot/files/usr/bin/sh
# dpkg-wrap v3 - Rewrite com.termux->com.anroot paths in .deb packages
# This replaces the original dpkg binary (saved as dpkg.real)
# It intercepts .deb file installations and rewrites paths before
# passing them to the real dpkg for installation.

export PREFIX=/data/data/com.anroot/files/usr
DPKG_REAL="$PREFIX/bin/dpkg.real"

if [ ! -x "$DPKG_REAL" ]; then
    for alt in "$PREFIX/bin/dpkg.bin" "$PREFIX/bin/dpkg.orig"; do
        if [ -x "$alt" ]; then
            DPKG_REAL="$alt"
            break
        fi
    done
    if [ ! -x "$DPKG_REAL" ]; then
        echo "dpkg: error: cannot find real dpkg binary (tried dpkg.real, dpkg.bin, dpkg.orig)" >&2
        exit 1
    fi
fi

# Separate .deb files from other arguments
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

# No .deb files -> pass through to real dpkg unchanged
if [ -z "$DEB_FILES" ]; then
    exec "$DPKG_REAL" "$@"
fi

# Process each .deb file
RESULT=0
for deb in $DEB_FILES; do
    # Quick check: does this .deb contain com.termux paths?
    NEEDS_REWRITE=0
    if dpkg-deb --fsys-tarfile "$deb" 2>/dev/null | tar -tf - 2>/dev/null | grep -q "com\.termux"; then
        NEEDS_REWRITE=1
    fi

    if [ $NEEDS_REWRITE -eq 0 ]; then
        "$DPKG_REAL" $OTHER_ARGS "$deb"
        RESULT=$?
        continue
    fi

    # Need to rewrite paths in the .deb
    WRAP_TMP=$(mktemp -d "$PREFIX/tmp/dpkg-wrap.XXXXXX")
    if [ -z "$WRAP_TMP" ] || [ ! -d "$WRAP_TMP" ]; then
        "$DPKG_REAL" $OTHER_ARGS "$deb"
        RESULT=$?
        continue
    fi

    EXTRACT="$WRAP_TMP/extract"
    mkdir -p "$EXTRACT"

    if ! dpkg-deb -R "$deb" "$EXTRACT" 2>/dev/null; then
        rm -rf "$WRAP_TMP"
        "$DPKG_REAL" $OTHER_ARGS "$deb"
        RESULT=$?
        continue
    fi

    # Step 1: Rename com.termux directories -> com.anroot
    if [ -d "$EXTRACT/data/data/com.termux" ]; then
        mkdir -p "$EXTRACT/data/data/com.anroot"
        for item in "$EXTRACT/data/data/com.termux"/*; do
            [ -e "$item" ] && mv -f "$item" "$EXTRACT/data/data/com.anroot/" 2>/dev/null
        done
        rm -rf "$EXTRACT/data/data/com.termux"
    fi

    # Step 2: Rewrite paths in DEBIAN control files
    if [ -d "$EXTRACT/DEBIAN" ]; then
        for ctrl_file in "$EXTRACT/DEBIAN"/*; do
            if [ -f "$ctrl_file" ]; then
                sed -i 's|com\.termux|com.anroot|g;s|/data/data/com\.termux|/data/data/com.anroot|g' "$ctrl_file" 2>/dev/null
            fi
        done
    fi

    # Step 3: Rewrite paths in text files
    find "$EXTRACT" -path "$EXTRACT/DEBIAN" -prune -o -type f \( \
        -name "*.sh" -o -name "*.list" -o -name "*.md5sums" -o \
        -name "*.conffiles" -o -name "*.config" -o -name "*.templates" -o \
        -name "*.postinst" -o -name "*.preinst" -o -name "*.postrm" -o \
        -name "*.prerm" -o -name "*.pc" -o -name "*.la" -o -name "*.h" -o \
        -name "*.cmake" -o -name "*.py" -o -name "*.pl" -o -name "*.rb" -o \
        -name "*.conf" -o -name "*.cfg" -o -name "*.txt" -o \
        -name "*.properties" -o -name "*.xml" -o -name "*.json" \
    \) -print 2>/dev/null | while read f; do
        sed -i 's|com\.termux|com.anroot|g;s|/data/data/com\.termux|/data/data/com.anroot|g' "$f" 2>/dev/null
    done

    # Step 4: Fix symlinks
    find "$EXTRACT" -type l 2>/dev/null | while read link; do
        target=$(readlink "$link" 2>/dev/null)
        if echo "$target" | grep -q "com\.termux"; then
            new_target=$(echo "$target" | sed 's|com\.termux|com.anroot|g')
            rm -f "$link" 2>/dev/null
            ln -sf "$new_target" "$link" 2>/dev/null
        fi
    done

    # Step 5: Rebuild the .deb
    NEW_DEB="$WRAP_TMP/modified.deb"
    if dpkg-deb -b "$EXTRACT" "$NEW_DEB" 2>/dev/null; then
        "$DPKG_REAL" $OTHER_ARGS "$NEW_DEB"
        RESULT=$?
    else
        "$DPKG_REAL" $OTHER_ARGS "$deb"
        RESULT=$?
    fi

    rm -rf "$WRAP_TMP"
done

exit $RESULT
'''


# ============================================================================
# First-boot setup script v5
# ============================================================================
ANROOT_FIRST_BOOT = r'''#!/data/data/com.anroot/files/usr/bin/sh
# anroot-first-boot v5 - First boot setup for Anroot
# dpkg-wrap is already installed as bin/dpkg (original saved as bin/dpkg.real)

export PREFIX=/data/data/com.anroot/files/usr
export HOME=/data/data/com.anroot/files/home
export PATH=$PREFIX/bin:$PATH
export TMPDIR=$PREFIX/tmp
export LD_LIBRARY_PATH=$PREFIX/lib

LOG="[Anroot Setup]"
echo "$LOG === Anroot First Boot Setup Started ==="
echo "$LOG Date: $(date)"
echo "$LOG Prefix: $PREFIX"

# --- Step 1: Verify dpkg wrapper ---
echo "$LOG Verifying dpkg wrapper..."
if [ -f "$PREFIX/bin/dpkg.real" ] && [ -f "$PREFIX/bin/dpkg" ]; then
    echo "$LOG dpkg wrapper is in place."
else
    echo "$LOG WARNING: dpkg wrapper not properly set up, fixing..."
    if [ -f "$PREFIX/bin/dpkg" ] && [ ! -f "$PREFIX/bin/dpkg.real" ]; then
        cp "$PREFIX/bin/dpkg" "$PREFIX/bin/dpkg.real"
        chmod 700 "$PREFIX/bin/dpkg.real"
    fi
    if [ -f "$PREFIX/bin/dpkg-wrap" ] && [ -f "$PREFIX/bin/dpkg.real" ]; then
        cp "$PREFIX/bin/dpkg-wrap" "$PREFIX/bin/dpkg"
        chmod 700 "$PREFIX/bin/dpkg"
    fi
fi

# --- Step 2: Welcome banner ---
echo "$LOG Setting up welcome banner..."
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
MOTDEOF
chmod 644 "$PREFIX/etc/motd"

# --- Step 3: Auto-login to Debian ---
echo "$LOG Setting up auto-login to Debian..."
mkdir -p "$PREFIX/etc/profile.d"
cat > "$PREFIX/etc/profile.d/anroot-autologin.sh" << 'AUTOEOF'
#!/data/data/com.anroot/files/usr/bin/sh
# Auto-login to Debian proot - enforced on every shell start

# Skip if already inside Debian
if [ -n "$ANROOT_DEBIAN_ACTIVE" ]; then
    return 0
fi

# Skip if running non-interactive
if [ -n "$ANROOT_SKIP_AUTOLOGIN" ]; then
    return 0
fi

# Wait for first-boot to complete
if [ -f "$PREFIX/ANROOT_FIRST_BOOT" ]; then
    echo ""
    echo "=== Anroot First-Time Setup ==="
    echo "Setup is running in the background..."
    echo "Please wait (max 10 minutes)..."
    echo ""
    WAITED=0
    while [ -f "$PREFIX/ANROOT_FIRST_BOOT" ] && [ $WAITED -lt 600 ]; do
        sleep 5
        WAITED=$((WAITED + 5))
        echo -n "."
    done
    echo ""
fi

# Check if Debian is installed
DEBIAN_ROOTFS="$PREFIX/var/proot-distro/installed-rootfs/debian"
if [ -d "$DEBIAN_ROOTFS" ]; then
    export ANROOT_DEBIAN_ACTIVE=1

    # Build bind mounts for storage
    STORAGE_BINDS=""
    if [ -d "/sdcard" ]; then
        STORAGE_BINDS="$STORAGE_BINDS --bind /sdcard:/root/sdcard"
    fi
    if [ -d "$HOME/storage" ]; then
        STORAGE_BINDS="$STORAGE_BINDS --bind $HOME/storage:/root/storage"
    fi
    if [ -d "/storage" ]; then
        STORAGE_BINDS="$STORAGE_BINDS --bind /storage:/storage"
    fi

    # Enter Debian (exec replaces current shell process)
    clear
    exec proot-distro login debian $STORAGE_BINDS
else
    echo ""
    echo "=== Welcome to Anroot ==="
    echo "Debian is not installed yet."
    echo "Run 'anroot-first-boot' to set up Debian."
    echo ""
fi
AUTOEOF
chmod 700 "$PREFIX/etc/profile.d/anroot-autologin.sh"

# --- Step 4: First-boot marker ---
touch "$PREFIX/ANROOT_FIRST_BOOT"

# --- Step 5: Setup storage ---
echo "$LOG Setting up storage access..."
USER_ID="${TERMUX_APP__USER_ID:-0}"
if [ ! -d "/sdcard" ]; then
    am broadcast --user "$USER_ID" -a "com.anroot.app.request_storage_permissions" > /dev/null 2>&1 || true
    sleep 2
fi

if [ ! -d "$HOME/storage" ]; then
    mkdir -p "$HOME/storage" 2>/dev/null
    if [ -d "/sdcard" ]; then
        ln -sf /sdcard "$HOME/storage/shared" 2>/dev/null
        ln -sf /sdcard/Download "$HOME/storage/downloads" 2>/dev/null
        ln -sf /sdcard/DCIM "$HOME/storage/dcim" 2>/dev/null
        ln -sf /sdcard/Pictures "$HOME/storage/pictures" 2>/dev/null
        ln -sf /sdcard/Music "$HOME/storage/music" 2>/dev/null
        ln -sf /sdcard/Movies "$HOME/storage/movies" 2>/dev/null
        ln -sf /sdcard/Documents "$HOME/storage/documents" 2>/dev/null
        echo "$LOG Storage symlinks created."
    fi
fi

# --- Step 6: Install proot-distro ---
echo "$LOG Installing proot-distro..."
apt update 2>&1 | tail -3
apt install -y proot-distro 2>&1 | tail -5

if ! command -v proot-distro >/dev/null 2>&1; then
    echo "$LOG ERROR: proot-distro installation failed!"
    rm -f "$PREFIX/ANROOT_FIRST_BOOT"
    exit 1
fi
echo "$LOG proot-distro installed."

# --- Step 7: Install Debian ---
echo "$LOG Installing Debian (this takes several minutes)..."
proot-distro install debian 2>&1 | tail -10

DEBIAN_ROOTFS="$PREFIX/var/proot-distro/installed-rootfs/debian"
if [ ! -d "$DEBIAN_ROOTFS" ]; then
    echo "$LOG ERROR: Debian rootfs not found!"
    rm -f "$PREFIX/ANROOT_FIRST_BOOT"
    exit 1
fi
echo "$LOG Debian installed."

# --- Step 8: Setup Debian rootfs ---
echo "$LOG Setting up Debian rootfs..."
mkdir -p "$DEBIAN_ROOTFS/root/sdcard" "$DEBIAN_ROOTFS/root/storage"
mkdir -p "$DEBIAN_ROOTFS/storage" "$DEBIAN_ROOTFS/sdcard"
mkdir -p "$DEBIAN_ROOTFS/mnt" "$DEBIAN_ROOTFS/tmp"

proot-distro login debian -- apt update 2>&1 | tail -3
proot-distro login debian -- apt install -y sudo ncurses-term nano curl wget procps 2>&1 | tail -5

# --- Step 9: Anroot commands inside Debian ---
echo "$LOG Installing Anroot commands in Debian..."
mkdir -p "$DEBIAN_ROOTFS/usr/local/bin"

cat > "$DEBIAN_ROOTFS/usr/local/bin/anroot-setup-storage" << 'CMDEOF'
#!/bin/sh
echo "=== Anroot Storage Setup ==="
echo "Storage locations:"
echo "  /root/storage  - Anroot storage symlinks"
echo "  /root/sdcard   - External storage (/sdcard)"
echo "  /sdcard        - External storage mount point"
echo "  /storage       - Android storage directories"
CMDEOF
chmod 755 "$DEBIAN_ROOTFS/usr/local/bin/anroot-setup-storage"

cat > "$DEBIAN_ROOTFS/usr/local/bin/anroot-info" << 'CMDEOF'
#!/bin/sh
echo "=== Anroot System Information ==="
echo "App:       Anroot (Debian on Android)"
echo "Website:   https://crossberry.vercel.app"
echo "GitHub:    https://github.com/grand369grand-lgtm/anroot"
echo "Debian:    $(cat /etc/debian_version 2>/dev/null || echo 'Unknown')"
echo "Kernel:    $(uname -r)"
echo "Arch:      $(uname -m)"
CMDEOF
chmod 755 "$DEBIAN_ROOTFS/usr/local/bin/anroot-info"

cat > "$DEBIAN_ROOTFS/usr/local/bin/anroot-update" << 'CMDEOF'
#!/bin/sh
echo "=== Updating Debian packages ==="
apt update && apt upgrade -y
CMDEOF
chmod 755 "$DEBIAN_ROOTFS/usr/local/bin/anroot-update"

cat > "$DEBIAN_ROOTFS/usr/local/bin/anroot-install" << 'CMDEOF'
#!/bin/sh
if [ $# -eq 0 ]; then
    echo "Usage: anroot-install <package...>"
    echo "Example: anroot-install build-essential python3"
    exit 1
fi
echo "=== Installing packages in Debian ==="
apt update && apt install -y "$@"
CMDEOF
chmod 755 "$DEBIAN_ROOTFS/usr/local/bin/anroot-install"

# --- Step 10: Debian .bashrc ---
cat > "$DEBIAN_ROOTFS/root/.bashrc" << 'BASHRC'
# ~/.bashrc: Anroot Debian shell
case $- in *i*) ;; *) return;; esac
HISTCONTROL=ignoreboth
shopt -s histappend
HISTSIZE=1000
HISTFILESIZE=2000
shopt -s checkwinsize
PS1='\[\033[01;32m\]root@anroot\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]# '
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
alias update='apt update && apt upgrade -y'
if [ -z "$ANROOT_WELCOMED" ]; then
    export ANROOT_WELCOMED=1
    echo ""
    echo "  Welcome to Anroot Debian!"
    echo "  Type 'anroot-info' for system information."
    echo "  Type 'anroot-update' to update packages."
    echo "  Type 'anroot-install <pkg>' to install packages."
    echo ""
fi
BASHRC
chmod 644 "$DEBIAN_ROOTFS/root/.bashrc"

# --- Step 11: Debian .profile ---
cat > "$DEBIAN_ROOTFS/root/.profile" << 'PROFILE'
# ~/.profile: Anroot Debian login shell
if [ -n "$BASH_VERSION" ]; then
    if [ -f "$HOME/.bashrc" ]; then
        . "$HOME/.bashrc"
    fi
fi
if [ -d "$HOME/bin" ] ; then
    PATH="$HOME/bin:$PATH"
fi
if [ -d "$HOME/.local/bin" ] ; then
    PATH="$HOME/.local/bin:$PATH"
fi
PROFILE
chmod 644 "$DEBIAN_ROOTFS/root/.profile"

# --- Done ---
rm -f "$PREFIX/ANROOT_FIRST_BOOT"
echo "$LOG === Anroot First Boot Setup Complete! ==="
echo "$LOG Restart the app to auto-login to Debian."
'''


# ============================================================================
# Other injected scripts
# ============================================================================
ANROOT_PKG = r'''#!/data/data/com.anroot/files/usr/bin/sh
export PREFIX=/data/data/com.anroot/files/usr
exec "$PREFIX/bin/pkg" "$@"
'''

ANROOT_CHANGE_REPO = r'''#!/data/data/com.anroot/files/usr/bin/sh
export PREFIX=/data/data/com.anroot/files/usr
if command -v termux-change-repo >/dev/null 2>&1; then
    exec termux-change-repo "$@"
else
    echo "termux-change-repo not found"
    exit 1
fi
'''

ANROOT_SETUP_STORAGE = r'''#!/data/data/com.anroot/files/usr/bin/sh
export PREFIX=/data/data/com.anroot/files/usr
export HOME=/data/data/com.anroot/files/home

# Method 1: Try termux-setup-storage if available
if command -v termux-setup-storage >/dev/null 2>&1; then
    termux-setup-storage "$@"
    if [ -d "$HOME/storage" ]; then
        echo "Storage setup complete at ~/storage/"
        exit 0
    fi
fi

# Method 2: Send broadcast with correct action and user ID
USER_ID="${TERMUX_APP__USER_ID:-0}"
am broadcast --user "$USER_ID" -a "com.anroot.app.request_storage_permissions" > /dev/null 2>&1
sleep 2

# Method 3: Manually create storage symlinks
if [ ! -d "$HOME/storage" ]; then
    mkdir -p "$HOME/storage" 2>/dev/null
fi

if [ -d "/sdcard" ]; then
    ln -sf /sdcard "$HOME/storage/shared" 2>/dev/null
    ln -sf /sdcard/Download "$HOME/storage/downloads" 2>/dev/null
    ln -sf /sdcard/DCIM "$HOME/storage/dcim" 2>/dev/null
    ln -sf /sdcard/Pictures "$HOME/storage/pictures" 2>/dev/null
    ln -sf /sdcard/Music "$HOME/storage/music" 2>/dev/null
    ln -sf /sdcard/Movies "$HOME/storage/movies" 2>/dev/null
    ln -sf /sdcard/Documents "$HOME/storage/documents" 2>/dev/null
    ln -sf /sdcard/Podcasts "$HOME/storage/podcasts" 2>/dev/null
    echo "Storage setup complete at ~/storage/"
else
    echo "Storage access not available."
    echo "Grant storage permission in Android Settings > Apps > Anroot > Permissions."
fi
'''

ANROOT_SETUP_PACKAGE_MANAGER = r'''#!/data/data/com.anroot/files/usr/bin/sh
export PREFIX=/data/data/com.anroot/files/usr
if command -v termux-setup-package-manager >/dev/null 2>&1; then
    exec termux-setup-package-manager "$@"
else
    mkdir -p $PREFIX/etc/apt/sources.list.d
    echo "deb https://packages.termux.dev/apt/termux-main stable main" > $PREFIX/etc/apt/sources.list
    apt update 2>/dev/null
fi
'''

ANROOT_PATH_SH = r'''#!/data/data/com.anroot/files/usr/bin/sh
export LD_LIBRARY_PATH=/data/data/com.anroot/files/usr/lib
clear
'''

# Files to inject into the bootstrap zip
INJECTED_FILES = {
    "bin/anroot-first-boot": ANROOT_FIRST_BOOT,
    "bin/dpkg-wrap": DPKG_WRAP,
    "bin/file": FILE_STUB,
    "bin/anroot-pkg": ANROOT_PKG,
    "bin/anroot-change-repo": ANROOT_CHANGE_REPO,
    "bin/anroot-setup-storage": ANROOT_SETUP_STORAGE,
    "bin/anroot-setup-package-manager": ANROOT_SETUP_PACKAGE_MANAGER,
    "etc/profile.d/anroot-path.sh": ANROOT_PATH_SH,
}


def is_elf(data):
    return data[:4] == b'\x7fELF'


def patch_elf_rpath(data):
    if not is_elf(data):
        return data
    old_bytes = OLD_PATH.encode('ascii')
    new_bytes = NEW_PATH.encode('ascii')
    if len(new_bytes) < len(old_bytes):
        padded_new = new_bytes + b'\x00' * (len(old_bytes) - len(new_bytes))
    else:
        padded_new = new_bytes[:len(old_bytes)]
    return data.replace(old_bytes, padded_new)


def patch_text(data):
    try:
        text = data.decode('utf-8', errors='replace')
        text = text.replace(OLD_PREFIX, NEW_PREFIX)
        text = text.replace(OLD_PATH, NEW_PATH)
        return text.encode('utf-8', errors='replace')
    except Exception:
        return data


def is_text_file(data, filename):
    text_extensions = {
        '.sh', '.bash', '.zsh', '.py', '.pl', '.rb', '.conf', '.cfg',
        '.txt', '.md', '.xml', '.json', '.yaml', '.yml', '.toml',
        '.properties', '.list', '.sources', '.installs', '.control',
        '.desc', '.pro', '.cmake', '.pc', '.la', '.header',
    }
    _, ext = os.path.splitext(filename)
    if ext.lower() in text_extensions:
        return True
    if data[:2] == b'#!':
        return True
    if b'\x00' in data[:8192]:
        return False
    try:
        data[:8192].decode('utf-8')
        return True
    except (UnicodeDecodeError, ValueError):
        return False


def patch_zip(zip_path):
    print(f"Patching {zip_path}...")
    with zipfile.ZipFile(zip_path, 'r') as zf:
        entries = zf.infolist()
        patched_entries = {}
        for entry in entries:
            if entry.is_dir():
                continue
            data = zf.read(entry.filename)

            # Special: save original dpkg as dpkg.real, replace with our wrapper
            if entry.filename == "bin/dpkg":
                print(f"  Saving original bin/dpkg as bin/dpkg.real")
                if is_elf(data):
                    patched_dpkg_real = patch_elf_rpath(data)
                elif is_text_file(data, entry.filename):
                    patched_dpkg_real = patch_text(data)
                else:
                    patched_dpkg_real = data.replace(
                        OLD_PATH.encode('ascii'),
                        NEW_PATH.encode('ascii') + b'\x00' * (len(OLD_PATH) - len(NEW_PATH))
                    )
                    patched_dpkg_real = patched_dpkg_real.replace(
                        OLD_PREFIX.encode('ascii'),
                        NEW_PREFIX.encode('ascii') + b'\x00' * (len(OLD_PREFIX) - len(NEW_PREFIX))
                    )
                patched_entries["bin/dpkg.real"] = patched_dpkg_real
                patched_entries["bin/dpkg"] = DPKG_WRAP.encode('utf-8')
                print(f"  Replaced bin/dpkg with dpkg-wrap v3")
                continue

            # Special: replace original file command with our stub
            if entry.filename == "bin/file":
                print(f"  Replacing original bin/file with our stub")
                patched_entries["bin/file"] = FILE_STUB.encode('utf-8')
                continue

            if is_elf(data):
                patched_data = patch_elf_rpath(data)
                patch_type = "ELF"
            elif is_text_file(data, entry.filename):
                patched_data = patch_text(data)
                patch_type = "text"
            else:
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
                print(f"  Patched ({patch_type}): {entry.filename} ({len(data)} bytes)")
            patched_entries[entry.filename] = patched_data

    # Inject custom files
    for inject_path, content in INJECTED_FILES.items():
        if inject_path in ("bin/dpkg.real", "bin/dpkg", "bin/file"):
            continue  # Already handled above
        content_bytes = content.encode('utf-8')
        patched_entries[inject_path] = content_bytes
        print(f"  Injected: {inject_path} ({len(content_bytes)} bytes)")

    # Write patched zip
    existing_files = set(e.filename for e in entries if not e.is_dir())
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            if entry.is_dir():
                zf.writestr(entry, b'')
            elif entry.filename in patched_entries:
                zf.writestr(entry, patched_entries[entry.filename])
            else:
                zf.writestr(entry, b'')
        # Add new injected files not in the original zip
        for inject_path, content_bytes in INJECTED_FILES.items():
            if inject_path not in existing_files and inject_path not in patched_entries:
                zf.writestr(inject_path, content_bytes)
                print(f"  Injected (new): {inject_path} ({len(content_bytes)} bytes)")
        # Add bin/dpkg.real if not in original
        if "bin/dpkg.real" not in existing_files and "bin/dpkg.real" in patched_entries:
            zf.writestr("bin/dpkg.real", patched_entries["bin/dpkg.real"])
            print(f"  Injected (new): bin/dpkg.real ({len(patched_entries['bin/dpkg.real'])} bytes)")
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
