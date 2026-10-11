#!/usr/bin/env bash

# Start the locally built Sub2API binary from the repository root.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="${SUB2API_BIN:-${SCRIPT_DIR}/backend/bin/sub2api}"

if [[ "${BINARY}" != /* ]]; then
    BINARY="${SCRIPT_DIR}/${BINARY}"
fi

if [[ ! -f "${BINARY}" ]]; then
    printf '错误: 找不到 Sub2API 可执行文件：%s\n' "${BINARY}" >&2
    printf '请先执行 ./build.sh 编译项目。\n' >&2
    exit 1
fi

if [[ ! -x "${BINARY}" ]]; then
    printf '错误: 文件不可执行：%s\n' "${BINARY}" >&2
    printf '请执行 chmod +x %q 后重试。\n' "${BINARY}" >&2
    exit 1
fi

cd "${SCRIPT_DIR}"
printf '启动 Sub2API：%s\n' "${BINARY}"
exec "${BINARY}" "$@"
