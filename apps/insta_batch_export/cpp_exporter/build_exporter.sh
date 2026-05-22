#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../.." && pwd)"

if [[ -f "${repo_root}/env.sh" ]]; then
  export INSTA_SDK_ENV_QUIET=1
  source "${repo_root}/env.sh"
  unset INSTA_SDK_ENV_QUIET
fi

if [[ -z "${MEDIA_SDK_ROOT:-}" ]]; then
  cat >&2 <<'EOF'
MEDIA_SDK_ROOT is required.

Set it to the MediaSDK sysroot, for example:
  export MEDIA_SDK_ROOT=/path/to/media-sdk-root/usr

If you use the original local SDK layout, source env.sh before running this
script.
EOF
  exit 2
fi

build_dir="${script_dir}/build"
output="${build_dir}/insta_media_exporter"
mkdir -p "${build_dir}"

g++ "${script_dir}/insta_media_exporter.cc" \
  -std=c++11 -O2 -Wall -Wextra \
  -I"${MEDIA_SDK_ROOT}/include" \
  -L"${MEDIA_SDK_ROOT}/lib" \
  -Wl,--disable-new-dtags \
  -Wl,-rpath,"${MEDIA_SDK_ROOT}/lib" \
  -Wl,-rpath-link,"${MEDIA_SDK_ROOT}/lib" \
  -Wl,--no-as-needed -lMediaSDK -lMNN_Cuda_Main -Wl,--as-needed \
  -lpthread \
  -o "${output}"

printf 'Built exporter: %s\n' "${output}"
