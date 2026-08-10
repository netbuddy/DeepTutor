#!/usr/bin/env bash
#
# 把扩展仓库（~/DeepTutor-ext）同步到 GitHub 发布分支的 ext/ 子目录。
#
# 【在哪台机器上跑】不是 192.168.213.24，而是你自己那台装了 gh 并已登录、
# 能稳定访问 GitHub 的机器。.24 上 github.com 被解析到透明代理的虚拟地址，
# 时通时断，而且没存任何 GitHub 凭据。本脚本住在扩展仓库里，但不在那里执行。
# 下面这条写法每次都取服务器上的最新版来跑，不必自己保存副本：
#
#   bash <(ssh yun@192.168.213.24 'cat ~/DeepTutor-ext/bin/sync-to-github.sh')
#
# 【为什么必须用 git subtree，不许复制文件】
# ext/ 是用 git subtree 并进发布分支的，subtree 靠历史里的记录点判断「上次
# 同步到哪儿了」。用复制文件的方式改 ext/ 下的内容，这个记录点不会前进，
# 下次真正跑 subtree pull 时它会拿一个过时的基准来比较，把对方的纯新增判成
# 冲突。2026-08-09 就因此撞过一次冲突，靠人工比对树哈希才敢确认没丢东西。
# 所以 ext/ 的同步只走这一条路。
#
# 【与前端发布的分工】
#   ext/ 下的内容      → 本脚本（在工作站上跑）
#   web/ 下的前端改动  → .24 上的 make publish，再按它打印的命令推送
# 两者都往同一条发布分支上追加提交，各跑各的，互不干扰。

set -euo pipefail

EXT_SSH="${EXT_SSH:-yun@192.168.213.24:DeepTutor-ext}"
FORK_URL="${FORK_URL:-https://github.com/netbuddy/DeepTutor.git}"
FORK_BRANCH="${FORK_BRANCH:-feat/course-and-notebook}"
EXT_BRANCH="${EXT_BRANCH:-master}"
WORK_DIR="${WORK_DIR:-$HOME/.cache/deeptutor-fork}"
# 不传 MSG 时，提交信息取扩展仓库最新提交的标题，这样发布分支的历史上能一眼
# 看出这次同步带来了什么；只写「同步扩展仓库」等于什么都没说。
MSG="${MSG:-}"
GIT_CRED="${GIT_CRED:-!gh auth git-credential}"

git_fork() { git -C "$WORK_DIR" "$@"; }

echo "==> 准备发布分支的工作副本：$WORK_DIR"
if [ ! -d "$WORK_DIR/.git" ]; then
  mkdir -p "$(dirname "$WORK_DIR")"
  git clone -q --branch "$FORK_BRANCH" "$FORK_URL" "$WORK_DIR"
else
  git_fork remote set-url origin "$FORK_URL"
fi

git_fork fetch -q origin "$FORK_BRANCH"
if [ -n "$(git_fork status --porcelain)" ]; then
  echo "工作副本里有未提交的改动，先处理干净再跑（$WORK_DIR）："
  git_fork status --short
  exit 1
fi
git_fork checkout -q -B "$FORK_BRANCH" "origin/$FORK_BRANCH"
before=$(git_fork rev-parse HEAD)
echo "    发布分支当前顶端：$(git_fork log --oneline -1)"

echo "==> 取回扩展仓库并比对"
git_fork fetch -q "$EXT_SSH" "$EXT_BRANCH"
ext_tree=$(git_fork rev-parse FETCH_HEAD^{tree})
cur_tree=$(git_fork rev-parse "HEAD:ext")
if [ "$ext_tree" = "$cur_tree" ]; then
  echo "    ext 子目录已经与扩展仓库一致，无需同步。"
  exit 0
fi
echo "    有差异，逐文件如下："
git_fork diff --stat "$cur_tree" "$ext_tree" | sed 's/^/      /'

if [ -z "$MSG" ]; then
  MSG="同步扩展仓库：$(git_fork log -1 --format=%s FETCH_HEAD)"
fi
echo "==> 用 git subtree 合并，提交信息为「$MSG」"
if ! git_fork subtree pull --prefix=ext "$EXT_SSH" "$EXT_BRANCH" -m "$MSG"; then
  echo ""
  echo "子树合并没能自动完成，已停在冲突处，没有产生提交。"
  echo "先看 $WORK_DIR 里的冲突，确认哪一侧是对的再手工解决；"
  echo "不确定就执行 git -C $WORK_DIR merge --abort 全部退回。"
  exit 1
fi

echo "==> 推送前核验"
new_ext=$(git_fork rev-parse "HEAD:ext")
if [ "$new_ext" != "$ext_tree" ]; then
  echo "核验不过：合并后的 ext 子目录与扩展仓库对不上，已停下不推送。"
  echo "  合并结果：$new_ext"
  echo "  扩展仓库：$ext_tree"
  exit 1
fi
echo "    ext 子目录与扩展仓库逐字节一致"

outside=$(git_fork diff --name-only "origin/$FORK_BRANCH" HEAD -- . ':(exclude)ext/' | wc -l)
if [ "$outside" != 0 ]; then
  echo "核验不过：ext 以外还有 $outside 个文件被改动，本脚本只该动 ext，已停下。"
  git_fork diff --name-only "origin/$FORK_BRANCH" HEAD -- . ':(exclude)ext/' | sed 's/^/      /'
  exit 1
fi
echo "    ext 以外一个文件都没动"

if ! git_fork merge-base --is-ancestor "origin/$FORK_BRANCH" HEAD; then
  echo "核验不过：不是快进推送，推上去会丢掉远端已有的提交，已停下。"
  exit 1
fi
echo "    发布分支的全部提交都已包含，是快进推送"

echo "==> 推送"
git_fork -c "credential.helper=$GIT_CRED" push origin "HEAD:$FORK_BRANCH"

echo ""
echo "同步完成：$(git_fork rev-parse --short "$before") → $(git_fork rev-parse --short HEAD)"
echo "工作副本留在 $WORK_DIR，下次再跑会直接复用，不必重新克隆。"
