#!/bin/sh
set -eu
PATCH_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TASK_BUILD_ROOT=${HWP_RENDERER_BUILD_ROOT:-"$HOME/.cache/hwp-make-renderer-rebuild"}
mkdir -p "$TASK_BUILD_ROOT"
cd "$TASK_BUILD_ROOT"
if [ -e rhwp-python ] || [ -e rhwp-core-patched ]; then
    printf '%s\n' 'Use a fresh HWP_RENDERER_BUILD_ROOT; existing source trees are preserved.' >&2
    exit 1
fi
git clone --no-checkout https://github.com/DanMeon/rhwp-python rhwp-python
git -C rhwp-python checkout --detach c42f46aee3959c7caa33db771c0addc1a8302e61
git clone --no-checkout https://github.com/edwardkim/rhwp rhwp-core-patched
git -C rhwp-core-patched checkout --detach ce45231c0c88efd5397d8fae9cd7d73de915095d
git -C rhwp-core-patched apply --check "$PATCH_DIR/rhwp-core.patch"
git -C rhwp-core-patched apply "$PATCH_DIR/rhwp-core.patch"
git -C rhwp-python apply --check "$PATCH_DIR/rhwp-python.patch"
git -C rhwp-python apply "$PATCH_DIR/rhwp-python.patch"
cp "$PATCH_DIR/Cargo.lock" rhwp-python/Cargo.lock
python3 -m venv venv
venv/bin/python -m pip install maturin==1.15.0 cargo-xwin==0.23.1
export PATH="$TASK_BUILD_ROOT/venv/bin:$PATH"
export RUSTUP_TOOLCHAIN=1.98.1
rustup toolchain install 1.98.1 --profile minimal
rustup target add x86_64-pc-windows-msvc
export PYO3_NO_PYTHON=1 PYO3_CROSS=1 PYO3_CROSS_PYTHON_VERSION=3.10
export XWIN_CACHE_DIR="$TASK_BUILD_ROOT/xwin"
export CARGO_TARGET_DIR="$TASK_BUILD_ROOT/target"
cd rhwp-python
# cargo-xwin's SDK can expose only lowercase advapi32.lib on a case-sensitive
# host. A failed link preserves all build artifacts; alias that exact file and
# retry once. Other errors retain their original nonzero exit status.
if ! maturin build --locked --target x86_64-pc-windows-msvc --release -j 4 --out ../wheels; then
    SDK_LIB="$XWIN_CACHE_DIR/xwin/sdk/lib/um/x86_64"
    if [ -f "$SDK_LIB/advapi32.lib" ] && [ ! -e "$SDK_LIB/Advapi32.lib" ]; then
        ln -s advapi32.lib "$SDK_LIB/Advapi32.lib"
        maturin build --locked --target x86_64-pc-windows-msvc --release -j 4 --out ../wheels
    else
        exit 1
    fi
fi
