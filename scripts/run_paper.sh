#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Keep Matplotlib's font cache writable and run-local on restricted systems.
export MPLCONFIGDIR="${MPLCONFIGDIR:-$ROOT/.mplconfig}"
mkdir -p "$MPLCONFIGDIR"

usage() {
  cat <<'EOF'
用法:
  ./scripts/run_paper.sh [选项] [额外 run_all.py 参数]

说明:
  - 默认使用 real 模式运行完整实验。
  - 默认自动续跑（--resume），同一个 RUN_ID 再次执行会复用已完成阶段。
  - 若存在 .env.local，会在启动前自动加载。
  - 入口脚本会在失败后做有限次自动重试，并沿用同一个 RUN_ID 继续。

常用示例:
  ./scripts/run_paper.sh --run-id paper_v24_real_01
  ./scripts/run_paper.sh --mode demo --run-id paper_v24_demo_01
  ./scripts/run_paper.sh --run-id paper_v24_real_01 --clean-run

选项:
  --run-id ID           指定运行 ID；未提供时自动生成
  --mode MODE           real 或 demo，默认 real
  --clean-run           运行前删除同名 run 目录后重跑
  --force               强制重算阶段（仍沿用同一 RUN_ID）
  --retry N             失败后自动重试 N 次，默认 2
  --retry-wait SEC      首次重试前等待秒数，默认 20；后续按尝试次数递增
  --check               启动前执行环境和 ClickHouse 检查
  --resume              显式声明续跑（默认已开启）
  --no-resume           关闭默认续跑
  -h, --help            显示帮助
EOF
}

log() {
  printf '[run_paper] %s\n' "$*" >&2
}

require_non_negative_int() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    log "参数错误: ${name} 需要是非负整数，实际收到 '${value}'"
    exit 2
  fi
}

RUN_ID="${RUN_ID:-}"
MODE="real"
RESUME=1
CLEAN_RUN=0
FORCE=0
RETRY_COUNT="${RUN_PAPER_RETRY:-4}"
RETRY_WAIT="${RUN_PAPER_RETRY_WAIT:-20}"
DO_CHECK=0
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id)
      [[ $# -ge 2 ]] || { log "参数错误: --run-id 需要一个值"; exit 2; }
      RUN_ID="$2"
      shift 2
      ;;
    --run-id=*)
      RUN_ID="${1#*=}"
      shift
      ;;
    --mode)
      [[ $# -ge 2 ]] || { log "参数错误: --mode 需要一个值"; exit 2; }
      MODE="$2"
      shift 2
      ;;
    --mode=*)
      MODE="${1#*=}"
      shift
      ;;
    --clean-run)
      CLEAN_RUN=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --resume)
      RESUME=1
      shift
      ;;
    --no-resume)
      RESUME=0
      shift
      ;;
    --retry)
      [[ $# -ge 2 ]] || { log "参数错误: --retry 需要一个值"; exit 2; }
      RETRY_COUNT="$2"
      shift 2
      ;;
    --retry=*)
      RETRY_COUNT="${1#*=}"
      shift
      ;;
    --retry-wait)
      [[ $# -ge 2 ]] || { log "参数错误: --retry-wait 需要一个值"; exit 2; }
      RETRY_WAIT="$2"
      shift 2
      ;;
    --retry-wait=*)
      RETRY_WAIT="${1#*=}"
      shift
      ;;
    --check)
      DO_CHECK=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      EXTRA_ARGS+=("$@")
      break
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

case "$MODE" in
  real|demo) ;;
  *)
    log "参数错误: --mode 仅支持 real 或 demo，实际收到 '${MODE}'"
    exit 2
    ;;
esac

require_non_negative_int "--retry" "$RETRY_COUNT"
require_non_negative_int "--retry-wait" "$RETRY_WAIT"

if [[ -z "$RUN_ID" ]]; then
  RUN_ID="paper_v24_${MODE}_$(date +%Y%m%d_%H%M%S)"
fi

if [[ -f .env.local ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env.local
  set +a
  log "已自动加载 .env.local"
else
  log "未检测到 .env.local，继续使用当前环境变量"
fi

# Refuse a real run when the ClickHouse readonly profile has no positive
# max_memory_usage. The server must provide this bound because readonly users
# cannot change it per query.
if [[ "$MODE" == "real" ]]; then
  export UR_CH_REQUIRE_MEMORY_GUARD="${UR_CH_REQUIRE_MEMORY_GUARD:-1}"
fi

if (( DO_CHECK )); then
  log "开始执行环境检查"
  python3 scripts/check_environment.py
  # Fail fast on the external dependency before local evidence validation.
  # This keeps database interaction at the front of the v2.4/v2.5 workflow and
  # makes a connectivity failure distinguishable from submission-readiness gaps.
  log "开始执行 ClickHouse 连通性检查"
  bash ./check_ch.sh
  log "开始执行冻结监督、天气和不可变证据检查"
  python3 scripts/verify_evidence_archive.py --root .
  python3 scripts/validate_supervision_registry.py
fi

CMD=(python3 run_all.py --mode "$MODE" --run-id "$RUN_ID" --stage all)
if (( RESUME )); then
  CMD+=(--resume)
fi
if (( CLEAN_RUN )); then
  CMD+=(--clean-run)
fi
if (( FORCE )); then
  CMD+=(--force)
fi
if ((${#EXTRA_ARGS[@]} > 0)); then
  CMD+=("${EXTRA_ARGS[@]}")
fi

OUT_BASE="$ROOT/runs/$RUN_ID"
if [[ "$MODE" == "demo" ]]; then
  OUT_BASE="$ROOT/demo_runs/$RUN_ID"
fi

MAX_ATTEMPTS=$((RETRY_COUNT + 1))
log "实验目录: $ROOT"
log "运行模式: $MODE"
log "运行 ID: $RUN_ID"
if (( RESUME )); then
  log "已开启自动续跑；同一 RUN_ID 将跳过已完成阶段"
else
  log "已关闭自动续跑；若同名 run 已存在，可能需要手动处理"
fi
if (( CLEAN_RUN )); then
  log "已请求 clean run：若存在同名 run 目录，将先删除再重跑"
fi
if (( FORCE )); then
  log "已开启 force：会强制重算目标阶段"
fi
log "最大尝试次数: ${MAX_ATTEMPTS}（失败后最多自动重试 ${RETRY_COUNT} 次）"

attempt=1
while true; do
  log "开始第 ${attempt}/${MAX_ATTEMPTS} 次执行"
  if "${CMD[@]}"; then
    log "实验计算完成，开始生成核心结果校验清单与防覆盖归档"
    python3 scripts/archive_run.py --run-dir "$OUT_BASE" --bundle-dir "$ROOT/run_archives"
    log "实验运行与结果封存完成。输出目录: $OUT_BASE"
    log "核心结果归档: $ROOT/run_archives/${RUN_ID}_core_results.zip"
    exit 0
  else
    exit_code=$?
  fi
  if (( attempt >= MAX_ATTEMPTS )); then
    log "实验运行失败，已达到最大尝试次数。最后退出码: ${exit_code}"
    exit "$exit_code"
  fi
  sleep_s=$((RETRY_WAIT * attempt))
  log "第 ${attempt} 次执行失败（退出码 ${exit_code}），${sleep_s}s 后将使用同一 RUN_ID 自动续跑"
  sleep "$sleep_s"
  attempt=$((attempt + 1))
done
