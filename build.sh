#!/usr/bin/env bash

# Build the complete Sub2API application from the repository root.
# The frontend must be built first because the backend embeds its dist/ files.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="${SCRIPT_DIR}/frontend"
BACKEND_DIR="${SCRIPT_DIR}/backend"
OUTPUT="${OUTPUT:-${BACKEND_DIR}/bin/sub2api}"
if [[ "${OUTPUT}" != /* ]]; then
    OUTPUT="${SCRIPT_DIR}/${OUTPUT}"
fi

die() {
    printf '错误: %s\n' "$1" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "未找到命令 $1，请先安装对应工具。"
}

require_command go
require_command node

PNPM_VERSION='9.15.9'
PNPM_PATH_PREFIX=''
if command -v pnpm >/dev/null 2>&1 && [[ "$(pnpm --version)" == "${PNPM_VERSION}" ]]; then
    PNPM_CMD=(pnpm)
elif command -v corepack >/dev/null 2>&1; then
    # The lockfile uses pnpm v9 settings. Newer pnpm versions ignore the
    # package.json overrides block and reject this lockfile in frozen mode.
    PNPM_CMD=(corepack "pnpm@${PNPM_VERSION}")
    # Package scripts invoke `pnpm` by name. Put a small shim first in PATH so
    # those nested calls use the same pinned version as the top-level command.
    PNPM_SHIM_DIR="$(mktemp -d)"
    trap 'rm -rf "${PNPM_SHIM_DIR}"' EXIT
    cat > "${PNPM_SHIM_DIR}/pnpm" <<EOF
#!/usr/bin/env bash
exec corepack pnpm@${PNPM_VERSION} "\$@"
EOF
    chmod +x "${PNPM_SHIM_DIR}/pnpm"
    PNPM_PATH_PREFIX="${PNPM_SHIM_DIR}:"
else
    die "需要 pnpm 9 或 corepack；请安装 pnpm ${PNPM_VERSION}。"
fi

run_pnpm() {
    if [[ -n "${NPM_CONFIG_REGISTRY:-}" && "${PNPM_CMD[0]}" == corepack ]]; then
        PATH="${PNPM_PATH_PREFIX}${PATH}" COREPACK_NPM_REGISTRY="${NPM_CONFIG_REGISTRY}" "${PNPM_CMD[@]}" "$@"
    else
        PATH="${PNPM_PATH_PREFIX}${PATH}" "${PNPM_CMD[@]}" "$@"
    fi
}

if [[ ! -f "${FRONTEND_DIR}/pnpm-lock.yaml" ]]; then
    die "缺少 frontend/pnpm-lock.yaml，无法执行可复现的前端安装。"
fi

if [[ ! -f "${BACKEND_DIR}/go.mod" ]]; then
    die "缺少 backend/go.mod，当前目录不是有效的 Sub2API 源码目录。"
fi

printf '==> 安装前端依赖（pnpm --frozen-lockfile）\n'
# CI=true makes pnpm's module-directory cleanup non-interactive, so the script
# also works when stdout/stdin are redirected or it is run by an automation job.
export CI="${CI:-true}"
CI="${CI:-true}" run_pnpm --dir "${FRONTEND_DIR}" install --frozen-lockfile

printf '==> 编译前端\n'
run_pnpm --dir "${FRONTEND_DIR}" run build

VERSION="${VERSION:-$("${BACKEND_DIR}/scripts/resolve-version.sh")}"
COMMIT="${COMMIT:-$(git -C "${SCRIPT_DIR}" rev-parse --short HEAD 2>/dev/null || printf 'unknown')}"
DATE="${DATE:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
BUILD_TYPE="${BUILD_TYPE:-source}"

mkdir -p "$(dirname "${OUTPUT}")"

printf '==> 编译后端（嵌入前端）\n'
(
    cd "${BACKEND_DIR}"
    CGO_ENABLED=0 go build \
        -tags embed \
        -ldflags="-s -w -X main.Version=${VERSION} -X main.Commit=${COMMIT} -X main.Date=${DATE} -X main.BuildType=${BUILD_TYPE}" \
        -trimpath \
        -o "${OUTPUT}" \
        ./cmd/server
)

printf '编译完成: %s\n' "${OUTPUT}"
