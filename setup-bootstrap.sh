#!/bin/bash
# setup-bootstrap.sh - Download, patch, and inject libanroot-path-translate.so into bootstrap zips
set -e

CPP_DIR="/home/z/my-project/termux-app/app/src/main/cpp"
SCRIPT_DIR="/home/z/my-project/termux-app"
PYTHON_SCRIPT="$SCRIPT_DIR/patch-bootstrap.py"

# Bootstrap version info from build.gradle
BOOTSTRAP_VERSION="2026.02.12-r1%2Bapt.android-7"
BASE_URL="https://github.com/termux/termux-packages/releases/download/bootstrap-${BOOTSTRAP_VERSION}"

# Architecture mappings: zip arch -> lib arch
declare -A ARCH_MAP=(
    ["aarch64"]="aarch64"
    ["arm"]="arm"
    ["i686"]="x86"
    ["x86_64"]="x86_64"
)

cd "$CPP_DIR"

for arch in aarch64 arm i686 x86_64; do
    ZIPFILE="bootstrap-${arch}.zip"

    # Download if not already present
    if [ ! -f "$ZIPFILE" ]; then
        echo "Downloading $ZIPFILE..."
        wget -q "${BASE_URL}/${ZIPFILE}" -O "$ZIPFILE"
        echo "Downloaded $ZIPFILE"
    else
        echo "$ZIPFILE already exists"
    fi
done

# Patch all zips with com.termux -> com.anroot
echo ""
echo "=== Patching bootstrap zips ==="
python3 "$PYTHON_SCRIPT" bootstrap-aarch64.zip bootstrap-arm.zip bootstrap-i686.zip bootstrap-x86_64.zip

# Inject libanroot-path-translate.so into each bootstrap zip
echo ""
echo "=== Injecting libanroot-path-translate.so into bootstrap zips ==="

for arch in aarch64 arm i686 x86_64; do
    ZIPFILE="bootstrap-${arch}.zip"
    LIB_ARCH="${ARCH_MAP[$arch]}"
    LIBFILE="libanroot-path-translate-${LIB_ARCH}.so"
    TARGET_PATH="lib/libanroot-path-translate.so"

    if [ ! -f "$LIBFILE" ]; then
        echo "ERROR: $LIBFILE not found"
        exit 1
    fi

    # Create a temporary directory to modify the zip
    TMPDIR=$(mktemp -d)
    cp "$ZIPFILE" "$TMPDIR/original.zip"

    # Extract, add our library, and repack
    cd "$TMPDIR"
    mkdir -p extract
    cd extract
    unzip -q "$TMPDIR/original.zip"

    # Copy our library into the lib/ directory
    cp "$CPP_DIR/$LIBFILE" "$TARGET_PATH"
    chmod 755 "$TARGET_PATH"

    # Repack the zip
    zip -q -r "$TMPDIR/new.zip" .

    # Replace the original
    cp "$TMPDIR/new.zip" "$CPP_DIR/$ZIPFILE"

    # Cleanup
    rm -rf "$TMPDIR"

    echo "Injected $LIBFILE into $ZIPFILE as $TARGET_PATH"
    cd "$CPP_DIR"
done

echo ""
echo "=== Bootstrap setup complete ==="
ls -la bootstrap-*.zip
