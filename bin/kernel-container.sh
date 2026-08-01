#!/usr/bin/env bash
# 学生代码的执行容器：一个装了科学计算库的 Jupyter 服务，宿主只通过 HTTP 驱动它。
#
# 为什么要单独一个容器：学生在教学场景里本来就要写代码，等于给了任意代码执行能力。
# 容器把它关在一个看不到宿主文件系统的地方，只留两个显式挂载——课程目录只读、
# 工作目录可写——再加上内存、CPU、进程数三道限额。
#
# 用法：
#   bin/kernel-container.sh start | stop | status | logs
#
# 访问口令每次启动重新生成，写进 .kernel-token（仅本人可读），不打印、不入日志。

set -euo pipefail

NAME="deeptutor-kernel"
IMAGE="quay.io/jupyter/scipy-notebook:latest"
PORT="9189"
EXT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOKEN_FILE="${EXT_DIR}/.kernel-token"
SRC_HOME="${DEEPTUTOR_SRC_HOME:-${HOME}/DeepTutor-src}"

# 两个挂载都用「容器内路径与宿主路径完全相同」的形式。这样内核里算出来的文件路径
# 拿到宿主上直接可用，不必来回换算——DeepTutor 自己的沙箱边车也是这个约定。
WORKSPACE_DIR="${SRC_HOME}/data/user/workspace"
COURSES_DIR="${SRC_HOME}/data/user/courses"

usage() {
  echo "用法：$(basename "$0") {start|stop|status|logs}"
  exit 1
}

port_in_use_by_other() {
  ss -tln 2>/dev/null | grep -q ":${PORT} " && ! docker ps --filter "name=^${NAME}$" --format '{{.Names}}' | grep -q .
}

cmd_start() {
  if docker ps --filter "name=^${NAME}$" --format '{{.Names}}' | grep -q .; then
    echo "内核容器已在运行。"
    return 0
  fi
  if port_in_use_by_other; then
    echo "端口 ${PORT} 已被别的进程占用，先处理掉再启动：ss -tlnp | grep ${PORT}" >&2
    exit 1
  fi

  mkdir -p "${WORKSPACE_DIR}" "${COURSES_DIR}"
  docker rm -f "${NAME}" >/dev/null 2>&1 || true

  local token
  token="$(openssl rand -hex 24)"
  umask 077
  printf '%s' "${token}" > "${TOKEN_FILE}"

  docker run -d --name "${NAME}" \
    --restart unless-stopped \
    -p "127.0.0.1:${PORT}:8888" \
    -v "${WORKSPACE_DIR}:${WORKSPACE_DIR}" \
    -v "${COURSES_DIR}:${COURSES_DIR}:ro" \
    --memory 4g --cpus 2 --pids-limit 256 \
    --user 1000:100 \
    "${IMAGE}" \
    start-notebook.py \
      --IdentityProvider.token="${token}" \
      --ServerApp.ip=0.0.0.0 \
      --ServerApp.root_dir=/ \
      --ServerApp.allow_origin='*' >/dev/null

  # 等服务真的能应答再返回，否则第一次执行会撞上连接被拒。
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null -m 2 "http://127.0.0.1:${PORT}/api/status"; then
      echo "内核容器已就绪：http://127.0.0.1:${PORT}（只绑本机回环）"
      echo "  课程目录（只读）：${COURSES_DIR}"
      echo "  工作目录（可写）：${WORKSPACE_DIR}"
      return 0
    fi
    sleep 1
  done
  echo "容器起来了但 60 秒内没有应答，看日志：docker logs ${NAME}" >&2
  exit 1
}

cmd_stop() {
  docker rm -f "${NAME}" >/dev/null 2>&1 && echo "内核容器已停止并移除。" || echo "内核容器本来就没在运行。"
  rm -f "${TOKEN_FILE}"
}

cmd_status() {
  if docker ps --filter "name=^${NAME}$" --format '{{.Names}}\t{{.Status}}' | grep -q .; then
    docker ps --filter "name=^${NAME}$" --format '  容器 {{.Names}} · {{.Status}}'
    echo -n "  服务应答： "
    curl -s -o /dev/null -w "HTTP %{http_code}\n" -m 5 "http://127.0.0.1:${PORT}/api/status" || echo "无应答"
    echo -n "  活跃内核数： "
    if [ -r "${TOKEN_FILE}" ]; then
      curl -s -m 5 -H "Authorization: token $(cat "${TOKEN_FILE}")" \
        "http://127.0.0.1:${PORT}/api/kernels" \
        | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))' 2>/dev/null || echo "查询失败"
    else
      echo "口令文件不存在"
    fi
  else
    echo "  内核容器未运行。"
  fi
}

cmd_logs() {
  docker logs -f "${NAME}"
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  *) usage ;;
esac
