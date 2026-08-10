#!/usr/bin/env bash
#
# 把 local 分支上的前端改动发布到 GitHub 的发布分支。
#
# 两条分支各有各的用途，不要合并：
#   local                          只放前端改动，基于 upstream-base 标签，
#                                  make upgrade 靠这两者把改动变基到新版上游。
#   发布分支（默认 feat/course-and-notebook）
#                                  内容是 local 的前端改动，外加 ext/ 子树、
#                                  两门自编课程与全部文档。
# 把发布分支合回 local，会让 make upgrade 的变基去重放那些无关提交，必然出事。
#
# 发布的做法：以发布分支的最新提交为基础，只把 web 目录覆盖成 local 的样子。
# 这是按内容比对，已经发布过的改动自然算出空差异，不会重复提交，也不会碰到
# 发布分支上 web 目录以外的任何东西。
#
# 本脚本只把提交备好，不推送——这台机器外网时通时断，也没存 GitHub 凭据。
# 推送命令会在最后打印出来，在有凭据的机器上执行。

set -euo pipefail

SRC="${SRC:-$HOME/DeepTutor-src}"
LOCAL_BRANCH="${LOCAL_BRANCH:-local}"
FORK_REMOTE="${FORK_REMOTE:-fork}"
FORK_URL="${FORK_URL:-https://github.com/netbuddy/DeepTutor.git}"
FORK_BRANCH="${FORK_BRANCH:-feat/course-and-notebook}"
PUB_BRANCH="${PUB_BRANCH:-publish}"
PUB_TREE="${PUB_TREE:-/tmp/deeptutor-publish}"
LAN_IP="${LAN_IP:-192.168.213.24}"
MSG="${MSG:-前端改动同步到发布分支}"

cd "$SRC"

git rev-parse -q --verify "$LOCAL_BRANCH" >/dev/null || {
  echo "没有 $LOCAL_BRANCH 分支，说明前端没有本地改动，无需发布。"
  exit 0
}

git remote get-url "$FORK_REMOTE" >/dev/null 2>&1 || {
  echo "没有名为 $FORK_REMOTE 的远端，先执行："
  echo "  cd $SRC && git remote add $FORK_REMOTE $FORK_URL"
  exit 1
}

drop_worktree() {
  git -C "$SRC" worktree remove --force "$PUB_TREE" >/dev/null 2>&1 || true
  git -C "$SRC" worktree prune
}

echo "==> 取回发布分支（这台机器外网时通时断，最多试 5 次）"
fetched=0
for i in 1 2 3 4 5; do
  if git fetch -q "$FORK_REMOTE" "$FORK_BRANCH" 2>/dev/null; then
    fetched=1
    break
  fi
  echo "    第 $i 次没通，5 秒后重试"
  sleep 5
done
if [ "$fetched" != 1 ]; then
  echo "五次都没取回来，等网络好些再跑。"
  exit 1
fi

echo "==> 比对前端目录"
if git diff --quiet "$FORK_REMOTE/$FORK_BRANCH" "$LOCAL_BRANCH" -- web/; then
  echo "前端目录与发布分支已经一致，没有要发布的内容。"
  exit 0
fi

echo "==> 另开一份工作副本，不动 $SRC 里正在被服务读取的那份"
drop_worktree
git worktree add -q "$PUB_TREE" -B "$PUB_BRANCH" "$FORK_REMOTE/$FORK_BRANCH"
trap drop_worktree EXIT

echo "==> 把前端目录覆盖成 $LOCAL_BRANCH 的样子"
git -C "$PUB_TREE" diff HEAD "$LOCAL_BRANCH" -- web/ > "$PUB_TREE/.publish.patch"
git -C "$PUB_TREE" apply --index "$PUB_TREE/.publish.patch"
rm -f "$PUB_TREE/.publish.patch"

echo "==> 本次要发布的改动"
git -C "$PUB_TREE" diff --cached --stat

git -C "$PUB_TREE" commit -q -m "$MSG"

echo "==> 发布前核验"
missing=$(git log --oneline "$PUB_BRANCH..$FORK_REMOTE/$FORK_BRANCH" | wc -l)
if [ "$missing" != 0 ]; then
  echo "核验不过：发布分支上有 $missing 个提交没被包含，推上去会丢内容，已停下。"
  exit 1
fi
echo "    发布分支的全部提交都已包含，是快进推送"

drift=$(git diff --stat "$PUB_BRANCH" "$LOCAL_BRANCH" -- web/ | wc -l)
if [ "$drift" != 0 ]; then
  echo "核验不过：前端目录与 $LOCAL_BRANCH 仍有差异，已停下。"
  exit 1
fi
echo "    前端目录与 $LOCAL_BRANCH 完全一致"

cat <<EOF

提交已备好，在 $PUB_BRANCH 分支上。这台机器没存 GitHub 凭据，
推送请在装了 gh 并已登录的机器上执行下面四条：

  rm -rf /tmp/dt-push && git init --bare -q /tmp/dt-push && cd /tmp/dt-push
  git fetch --update-shallow yun@$LAN_IP:DeepTutor-src $PUB_BRANCH:refs/heads/topush
  git -c credential.helper='!gh auth git-credential' push $FORK_URL topush:$FORK_BRANCH
  cd / && rm -rf /tmp/dt-push

（$SRC 是浅克隆，取回必须带 --update-shallow，否则会被拒。）
EOF
