#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
APP_DIR="${REPO_ROOT}/apps/insta_batch_export"
BUNDLE_NAME="${BUNDLE_NAME:-insta360-batch-export-offline-linux-x86_64}"
OUTPUT_ROOT="${1:-${REPO_ROOT}/dist}"
BUNDLE_DIR="${OUTPUT_ROOT}/${BUNDLE_NAME}"
BUNDLE_TARBALL="${OUTPUT_ROOT}/${BUNDLE_NAME}.tar.gz"
PYTHON_BIN="${PYTHON:-python3}"

DEFAULT_MEDIA_SDK_ROOT="${REPO_ROOT}/media-sdk-root/usr"
DEFAULT_MODELS_DIR="${REPO_ROOT}/libMediaSDK-dev-3.1.1.0-20250922_191110-amd64/models"
MEDIA_SDK_ROOT="${MEDIA_SDK_ROOT:-${DEFAULT_MEDIA_SDK_ROOT}}"
MODELS_DIR="${INSTA_MEDIA_MODELS_DIR:-${DEFAULT_MODELS_DIR}}"
SDK_LIB_DIR="${MEDIA_SDK_LIB_DIR:-${MEDIA_SDK_ROOT}/lib}"
SDK_LIB="${INSTA_MEDIASDK_LIB:-${SDK_LIB_DIR}/libMediaSDK.so}"
export MEDIA_SDK_ROOT
export INSTA_MEDIA_MODELS_DIR="${MODELS_DIR}"

PYI_WORK_ROOT="${REPO_ROOT}/build/offline_bundle_pyinstaller"
PYI_DIST_ROOT="${REPO_ROOT}/build/offline_bundle_dist"
PYI_SPEC_ROOT="${REPO_ROOT}/build/offline_bundle_spec"
EXPORTER_BUILD_DIR="${REPO_ROOT}/build/offline_bundle_exporter"
EXPORTER_PATH="${EXPORTER_BUILD_DIR}/insta_media_exporter"
PYI_APP_NAME="insta360-batch-export-gui"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_file() {
  local path="$1"
  local label="$2"
  [[ -f "${path}" ]] || die "missing ${label}: ${path}"
}

require_dir() {
  local path="$1"
  local label="$2"
  [[ -d "${path}" ]] || die "missing ${label}: ${path}"
}

require_dir "${SDK_LIB_DIR}" "MediaSDK library directory"
require_file "${SDK_LIB}" "libMediaSDK.so"
require_dir "${MODELS_DIR}" "MediaSDK models directory"

"${PYTHON_BIN}" -m PyInstaller --version >/dev/null 2>&1 || die \
  "PyInstaller is required. Install it with: ${PYTHON_BIN} -m pip install pyinstaller"

printf 'Building portable C++ exporter...\n'
mkdir -p "${EXPORTER_BUILD_DIR}"
g++ "${APP_DIR}/cpp_exporter/insta_media_exporter.cc" \
  -std=c++11 -O2 -Wall -Wextra \
  -I"${MEDIA_SDK_ROOT}/include" \
  -L"${SDK_LIB_DIR}" \
  -Wl,--disable-new-dtags \
  -Wl,-rpath,'$ORIGIN/../sdk/lib' \
  -Wl,-rpath-link,"${SDK_LIB_DIR}" \
  -Wl,--no-as-needed -lMediaSDK -lMNN_Cuda_Main -Wl,--as-needed \
  -lpthread \
  -o "${EXPORTER_PATH}"
require_file "${EXPORTER_PATH}" "compiled exporter"

printf 'Building PyInstaller GUI...\n'
rm -rf "${PYI_WORK_ROOT}" "${PYI_DIST_ROOT}" "${PYI_SPEC_ROOT}"
mkdir -p "${PYI_WORK_ROOT}" "${PYI_DIST_ROOT}" "${PYI_SPEC_ROOT}"
"${PYTHON_BIN}" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "${PYI_APP_NAME}" \
  --paths "${APP_DIR}" \
  --distpath "${PYI_DIST_ROOT}" \
  --workpath "${PYI_WORK_ROOT}" \
  --specpath "${PYI_SPEC_ROOT}" \
  "${APP_DIR}/gui_app.py"

printf 'Assembling bundle: %s\n' "${BUNDLE_DIR}"
rm -rf "${BUNDLE_DIR}"
mkdir -p \
  "${BUNDLE_DIR}/app" \
  "${BUNDLE_DIR}/bin" \
  "${BUNDLE_DIR}/sdk/lib" \
  "${BUNDLE_DIR}/sdk/models"

cp -a "${PYI_DIST_ROOT}/${PYI_APP_NAME}" "${BUNDLE_DIR}/app/"
install -m 755 "${EXPORTER_PATH}" "${BUNDLE_DIR}/bin/insta_media_exporter"
cp -a "${SCRIPT_DIR}/README_OFFLINE.md" "${BUNDLE_DIR}/README_OFFLINE.md"

printf 'Copying MediaSDK runtime libraries...\n'
while IFS= read -r lib_path; do
  lib_name="$(basename "${lib_path}")"
  if [[ "${lib_name}" == "libcuda.so.1" ]]; then
    printf '  skipping bundled CUDA driver shim: %s\n' "${lib_name}"
    continue
  fi
  cp -a "${lib_path}" "${BUNDLE_DIR}/sdk/lib/"
done < <(find "${SDK_LIB_DIR}" -maxdepth 1 \( -type f -o -type l \) -name '*.so*' | sort)

require_file "${BUNDLE_DIR}/sdk/lib/libMediaSDK.so" "bundled libMediaSDK.so"
if [[ -e "${BUNDLE_DIR}/sdk/lib/libcuda.so.1" ]]; then
  die "bundle unexpectedly contains sdk/lib/libcuda.so.1"
fi

printf 'Copying MediaSDK models...\n'
cp -a "${MODELS_DIR}/." "${BUNDLE_DIR}/sdk/models/"

cat >"${BUNDLE_DIR}/run_gui.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export INSTA_EXPORTER_PATH="${BUNDLE_ROOT}/bin/insta_media_exporter"
export INSTA_MEDIASDK_LIB="${BUNDLE_ROOT}/sdk/lib/libMediaSDK.so"
export MEDIA_SDK_LIB_DIR="${BUNDLE_ROOT}/sdk/lib"
export INSTA_MEDIA_MODELS_DIR="${BUNDLE_ROOT}/sdk/models"
export LD_LIBRARY_PATH="${BUNDLE_ROOT}/sdk/lib:${LD_LIBRARY_PATH:-}"

exec "${BUNDLE_ROOT}/app/insta360-batch-export-gui/insta360-batch-export-gui" "$@"
EOF
chmod 755 "${BUNDLE_DIR}/run_gui.sh"

cat >"${BUNDLE_DIR}/bundle_manifest.txt" <<EOF
bundle_name=${BUNDLE_NAME}
created_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
media_sdk_root=${MEDIA_SDK_ROOT}
media_sdk_lib=${SDK_LIB}
models_dir=${MODELS_DIR}
bundled_cuda_driver_lib=false
EOF

printf '\nOffline bundle ready:\n  %s\n' "${BUNDLE_DIR}"
printf 'Creating archive: %s\n' "${BUNDLE_TARBALL}"
tar -C "${OUTPUT_ROOT}" -czf "${BUNDLE_TARBALL}" "${BUNDLE_NAME}"
printf 'Archive ready:\n  %s\n' "${BUNDLE_TARBALL}"
printf 'Run it with:\n  %s/run_gui.sh\n' "${BUNDLE_DIR}"
