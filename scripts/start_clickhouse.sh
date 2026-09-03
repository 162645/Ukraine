#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -f .env.local ]]; then set -a; source .env.local; set +a; fi

CONFIG_FILE="config/experiment_v2.local.yaml"
[[ -f "$CONFIG_FILE" ]] || CONFIG_FILE="config/experiment_v2.yaml"
CONFIG_HOST="$(awk '/^  host:[[:space:]]*/ {print $2; exit}' "$CONFIG_FILE")"
DB_HOST="${UR_CH_HOST:-$CONFIG_HOST}"
HTTP_PORT="${UR_CH_HTTP_PORT:-8123}"
NATIVE_PORT="${UR_CH_NATIVE_PORT:-9000}"
CONFIG_SSH_HOST="$(awk '/^  ssh_host:[[:space:]]*/ {print $2; exit}' "$CONFIG_FILE")"
CONFIG_SSH_USER="$(awk '/^  ssh_user:[[:space:]]*/ {print $2; exit}' "$CONFIG_FILE")"
CONFIG_SSH_PASSWORD="$(awk '/^  ssh_password:[[:space:]]*/ {sub(/^  ssh_password:[[:space:]]*/, ""); print; exit}' "$CONFIG_FILE")"
CONFIG_START_CMD="$(awk '/^  service_start_command:[[:space:]]*/ {sub(/^  service_start_command:[[:space:]]*/, ""); print; exit}' "$CONFIG_FILE")"
CONFIG_RESTART_CMD="$(awk '/^  service_restart_command:[[:space:]]*/ {sub(/^  service_restart_command:[[:space:]]*/, ""); print; exit}' "$CONFIG_FILE")"
SSH_HOST="${UR_CH_SSH_HOST:-${CONFIG_SSH_HOST:-$DB_HOST}}"
SSH_USER="${UR_CH_SSH_USER:-$CONFIG_SSH_USER}"
SSH_PASSWORD="${UR_CH_SSH_PASSWORD:-$CONFIG_SSH_PASSWORD}"
WAIT_SECONDS="${UR_CH_START_WAIT_SECONDS:-30}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "用法: ./scripts/start_clickhouse.sh [--restart|--diagnose]"
  echo "默认读取 config/experiment_v2.local.yaml 中的 SSH 配置。"
  exit 0
fi
RESTART=0
DIAGNOSE=0
if [[ "${1:-}" == "--restart" ]]; then RESTART=1; fi
if [[ "${1:-}" == "--diagnose" ]]; then DIAGNOSE=1; fi

port_open() { nc -z -G 2 "$DB_HOST" "$1" >/dev/null 2>&1; }
echo "ClickHouse: ${DB_HOST} (HTTP ${HTTP_PORT}, native ${NATIVE_PORT})"
if [[ "$RESTART" -eq 0 && "$DIAGNOSE" -eq 0 ]] && port_open "$HTTP_PORT" && port_open "$NATIVE_PORT"; then
  echo "端口已可用，执行连接检查。"
  ./check_ch.sh
  exit 0
fi

if [[ -z "$SSH_USER" ]]; then
  echo "端口不可用，且未配置 UR_CH_SSH_USER。" >&2
  echo "请在 .env.local 添加：UR_CH_SSH_USER=服务器SSH用户" >&2
  exit 2
fi

if [[ "$DIAGNOSE" -eq 1 ]]; then
  ACTION="diagnose"
elif [[ "$RESTART" -eq 1 ]]; then
  ACTION="restart"
else
  ACTION="start"
fi
# Always print the remote service state, listeners, and recent errors before
# taking the requested action. The body is sent over stdin, avoiding nested
# shell quoting and making the sudo password flow deterministic.
REMOTE_BODY="$(cat <<'REMOTE_EOF'
set -u
ACTION="$1"
echo '--- systemctl before ---'
systemctl list-unit-files --type=service 2>/dev/null | grep -i clickhouse || true
systemctl status clickhouse-server --no-pager 2>/dev/null || true
echo '--- listeners before ---'
ss -lntp | grep -E ':(8123|9000)\\b' || true
echo '--- recent journal ---'
journalctl -u clickhouse-server -n 40 --no-pager 2>/dev/null || true
journalctl -u clickhouse -n 40 --no-pager 2>/dev/null || true
echo '--- installed binaries/config ---'
command -v clickhouse-server || true
find /etc /usr /opt -maxdepth 4 -type f -name 'config.xml' -path '*clickhouse*' 2>/dev/null | head -20 || true
pgrep -af 'clickhouse-server|clickhouse' || true
echo '--- requested action ---'
if [[ "$ACTION" != "diagnose" ]]; then
  UNIT=""
  for candidate in clickhouse-server clickhouse clickhouse-server.service clickhouse.service; do
    if systemctl list-unit-files "${candidate}" 2>/dev/null | grep -q "${candidate}"; then UNIT="${candidate}"; break; fi
  done
  if [[ -n "$UNIT" ]]; then
    if [[ "$ACTION" == "restart" ]]; then systemctl restart "$UNIT"; else systemctl start "$UNIT"; fi
  elif [[ -x /etc/init.d/clickhouse-server ]]; then
    if [[ "$ACTION" == "restart" ]]; then /etc/init.d/clickhouse-server restart; else /etc/init.d/clickhouse-server start; fi
  elif command -v service >/dev/null 2>&1 && service clickhouse-server status >/dev/null 2>&1; then
    if [[ "$ACTION" == "restart" ]]; then service clickhouse-server restart; else service clickhouse-server start; fi
  elif pgrep -f 'clickhouse-server' >/dev/null 2>&1; then
    echo "ClickHouse process already exists; no systemd unit found."
  elif command -v clickhouse-server >/dev/null 2>&1; then
    CFG="/etc/clickhouse-server/config.xml"
    [[ -f "$CFG" ]] || CFG=""
    if [[ -n "$CFG" ]]; then nohup clickhouse-server --config-file="$CFG" >/tmp/clickhouse-server.start.log 2>&1 &
    else nohup clickhouse-server >/tmp/clickhouse-server.start.log 2>&1 & fi
  else
    echo "ClickHouse executable and systemd unit were not found." >&2
    exit 3
  fi
fi
echo '--- systemctl after ---'
systemctl status clickhouse-server --no-pager 2>/dev/null || true
systemctl status clickhouse --no-pager 2>/dev/null || true
echo '--- listeners after ---'
ss -lntp | grep -E ':(8123|9000)\\b' || true
echo '--- process after ---'
pgrep -af 'clickhouse-server|clickhouse' || true
EOF
REMOTE_EOF
)"
REMOTE_B64="$(printf '%s\n' "$REMOTE_BODY" | base64 | tr -d '\n')"
echo "通过 SSH 执行: ${SSH_USER}@${SSH_HOST} ${ACTION}"
if [[ -n "$SSH_PASSWORD" ]] && command -v expect >/dev/null 2>&1; then
  # Force password authentication for the SSH hop, then feed the same local
  # server password to sudo and stream the remote script on stdin.
  export UR_LOCAL_SSH_PASSWORD="$SSH_PASSWORD"
  export UR_LOCAL_SSH_USER="$SSH_USER"
  export UR_LOCAL_SSH_HOST="$SSH_HOST"
  export UR_LOCAL_REMOTE_B64="$REMOTE_B64"
  export UR_LOCAL_REMOTE_ACTION="$ACTION"
  expect -c '
set timeout 30
set user $env(UR_LOCAL_SSH_USER)
set host $env(UR_LOCAL_SSH_HOST)
set password $env(UR_LOCAL_SSH_PASSWORD)
set body_b64 $env(UR_LOCAL_REMOTE_B64)
set action $env(UR_LOCAL_REMOTE_ACTION)
spawn ssh -o ConnectTimeout=10 -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=accept-new "$user@$host" "sudo -S -p {} bash -s -- $action"
expect {
  -re "Are you sure you want to continue connecting" { send "yes\r"; exp_continue }
  -re "(?i)password:" { send -- "$password\r"; after 500; send -- "$password\r"; send "echo $body_b64 | base64 -d\r"; send "\004" }
}
expect {
  eof
}
catch wait result
if {[lindex $result 3] != 0} { exit [lindex $result 3] }
'
else
  echo "未找到 expect，无法自动输入 SSH/sudo 密码。" >&2
  exit 2
fi

for ((i=0; i<WAIT_SECONDS; i+=2)); do
  if port_open "$HTTP_PORT" && port_open "$NATIVE_PORT"; then
    echo "ClickHouse 已恢复，执行连接检查。"
    ./check_ch.sh
    exit 0
  fi
  sleep 2
done
echo "服务命令已执行，但端口在 ${WAIT_SECONDS}s 内仍不可用。" >&2
exit 1
