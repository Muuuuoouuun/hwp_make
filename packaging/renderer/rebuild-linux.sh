#!/bin/sh
# Native Linux build of the same core patches used by the Windows wheel.
set -eu

PATCH_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TASK_BUILD_ROOT=${HWP_RENDERER_BUILD_ROOT:-"$HOME/.cache/hwp-make-renderer-linux"}
TASK_PYTHON=${HWP_RENDERER_PYTHON:-python3}
TASK_JOBS=${HWP_RENDERER_BUILD_JOBS:-2}

case "$(uname -s):$(uname -m)" in
    Linux:x86_64) ;;
    *) echo "This build is verified only on Linux x86_64." >&2; exit 1 ;;
esac
for renderer_tool in git cc c++ pkg-config rustup; do
    if ! command -v "$renderer_tool" >/dev/null 2>&1; then
        echo "Missing build tool: $renderer_tool (see packaging/renderer/README.md)." >&2
        exit 1
    fi
done
if [ -n "${HWP_RENDERER_SYSROOT:-}" ]; then
    export PKG_CONFIG_SYSROOT_DIR="$HWP_RENDERER_SYSROOT"
    export PKG_CONFIG_PATH="$HWP_RENDERER_SYSROOT/usr/lib/x86_64-linux-gnu/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
    export LIBRARY_PATH="$HWP_RENDERER_SYSROOT/usr/lib/x86_64-linux-gnu${LIBRARY_PATH:+:$LIBRARY_PATH}"
fi
pkg-config --exists fontconfig freetype2
mkdir -p "$TASK_BUILD_ROOT"
TASK_BUILD_ROOT=$(CDPATH= cd -- "$TASK_BUILD_ROOT" && pwd)
cd "$TASK_BUILD_ROOT"
if [ -e rhwp-python ] || [ -e rhwp-core-patched ]; then
    echo "Choose a fresh HWP_RENDERER_BUILD_ROOT; existing sources are preserved." >&2
    exit 1
fi

checkout_source() {
    git init --quiet "$1"
    git -C "$1" remote add origin "$2"
    git -C "$1" fetch --depth 1 origin "$3"
    git -C "$1" checkout --detach FETCH_HEAD
}
checkout_source rhwp-python https://github.com/DanMeon/rhwp-python c42f46aee3959c7caa33db771c0addc1a8302e61
checkout_source rhwp-core-patched https://github.com/edwardkim/rhwp ce45231c0c88efd5397d8fae9cd7d73de915095d
git -C rhwp-core-patched apply --check "$PATCH_DIR/rhwp-core.patch"
git -C rhwp-core-patched apply "$PATCH_DIR/rhwp-core.patch"
git -C rhwp-core-patched apply --check "$PATCH_DIR/rhwp-core-font-cache.patch"
git -C rhwp-core-patched apply "$PATCH_DIR/rhwp-core-font-cache.patch"
git -C rhwp-python apply --check "$PATCH_DIR/rhwp-python.patch"
git -C rhwp-python apply "$PATCH_DIR/rhwp-python.patch"
cp "$PATCH_DIR/Cargo.lock" rhwp-python/Cargo.lock
git -C rhwp-python apply --check "$PATCH_DIR/rhwp-python-font-cache.patch"
git -C rhwp-python apply "$PATCH_DIR/rhwp-python-font-cache.patch"
# The binding metadata retains the original submodule's license path.
mkdir -p rhwp-python/external/rhwp
cp rhwp-core-patched/LICENSE rhwp-python/external/rhwp/LICENSE

"$TASK_PYTHON" -m venv build-venv
build-venv/bin/python -m pip install maturin==1.15.0 patchelf==0.17.2.4
export PATH="$TASK_BUILD_ROOT/build-venv/bin:$PATH"
export RUSTUP_TOOLCHAIN=1.98.1
rustup toolchain install 1.98.1 --profile minimal
export CARGO_TARGET_DIR="$TASK_BUILD_ROOT/target"
cd rhwp-python
maturin build --locked --release -j "$TASK_JOBS" --out ../wheels
echo "Built wheels: $TASK_BUILD_ROOT/wheels (not installed automatically)."
