# DeepTutor 源码版 + 本地扩展的生命周期与升级流程
#
# 用法：cd ~/DeepTutor-ext && make <目标>
#   make install            首次安装扩展包与站点钩子
#   make start | stop | restart | status | health
#   make verify             接入自检（升级后必跑）
#   make upgrade VERSION=v1.5.8   升级到指定版本并重新集成
#   make patches            把本地源码改动导出成补丁文件备查
#
# 目录分工：
#   ~/DeepTutor-src   DeepTutor 官方源码，一个 git 工作树，跟随上游
#   ~/DeepTutor-ext   我们自己的东西，独立目录，升级时完全不受影响
#
# 端口选择说明：这台机器上 9181/9182/9183 归 pip 安装的那套 DeepTutor，
# 9184 是实验用的 Jupyter 容器，9185 被 novnc 的 websockify 占着，
# 所以源码版用 9187（前端）与 9188（后端）。改端口要同时改
# ~/DeepTutor-src/data/user/settings/system.json。

SRC        := $(HOME)/DeepTutor-src
EXT        := $(HOME)/DeepTutor-ext
PY         := $(SRC)/.venv/bin/python
PIP        := $(SRC)/.venv/bin/pip
DEEPTUTOR  := $(SRC)/.venv/bin/deeptutor
FRONT_PORT := 9187
BACK_PORT  := 9188
LAN_IP     := 192.168.213.24
LOG_DIR    := $(EXT)/logs
LOG        := $(LOG_DIR)/deeptutor.log
PIDFILE    := $(LOG_DIR)/deeptutor.pid

# 本地源码改动放在 local 分支上；upstream-base 这个本地标签记录它基于哪个上游版本，
# 升级时靠这两者做变基。没有本地改动时它们都不存在，升级退化成简单的切换标签。
LOCAL_BRANCH := local
BASE_TAG     := upstream-base

.PHONY: help install start stop restart status health logs verify upgrade patches wait-port \
        kernel-start kernel-stop kernel-status kernel-logs kernel-build

help:
	@echo "make install | start | stop | restart | status | health | verify"
	@echo "make upgrade VERSION=v1.5.8    升级 DeepTutor 并重新集成扩展"
	@echo "make patches                   导出本地源码改动"
	@echo "make kernel-start | kernel-stop | kernel-status | kernel-logs   学生代码的执行容器"
	@echo ""
	@echo "应用地址： http://$(LAN_IP):$(FRONT_PORT)/"
	@echo "后端接口： http://$(LAN_IP):$(BACK_PORT)/docs"

# ── 安装 ────────────────────────────────────────────────────────────────

install:
	@$(PIP) install -q -e $(EXT)
	@$(PY) $(EXT)/bin/install-sitehook.py
	@echo "扩展已安装。执行 make verify 确认接入是否生效。"

# ── 生命周期 ────────────────────────────────────────────────────────────

start:
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
	  echo "服务已在运行，进程号 $$(cat $(PIDFILE))。要重启请执行 make restart。"; \
	  exit 0; \
	fi
	@mkdir -p $(LOG_DIR)
	@cd $(SRC) && setsid nohup $(DEEPTUTOR) start --home $(SRC) >> $(LOG) 2>&1 < /dev/null & \
	  echo $$! > $(PIDFILE)
	@$(MAKE) --no-print-directory wait-port
	@echo "已启动： http://$(LAN_IP):$(FRONT_PORT)/"

# 等后端端口进入监听状态。用后端而不是前端做判据，是因为前端在源码模式下跑的是
# Next.js 开发服务器，首次编译要一两分钟，而后端起来就说明扩展已经加载完毕。
wait-port:
	@for i in $$(seq 1 180); do \
	  if ss -tln | grep -q ":$(BACK_PORT) "; then exit 0; fi; \
	  if [ -f $(PIDFILE) ] && ! kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
	    echo "启动进程已退出，最后 20 行日志："; tail -20 $(LOG); exit 1; \
	  fi; \
	  sleep 1; \
	done; \
	echo "等待 180 秒后端口 $(BACK_PORT) 仍未监听，最后 20 行日志："; tail -20 $(LOG); exit 1

stop:
	@if [ -f $(PIDFILE) ]; then \
	  kill -TERM -- -$$(cat $(PIDFILE)) 2>/dev/null || kill -TERM $$(cat $(PIDFILE)) 2>/dev/null || true; \
	  rm -f $(PIDFILE); \
	fi
	@sleep 2
	@if ss -tln | grep -qE ":($(FRONT_PORT)|$(BACK_PORT)) "; then \
	  echo "仍有进程占用端口，按端口清理"; \
	  fuser -k $(FRONT_PORT)/tcp $(BACK_PORT)/tcp 2>/dev/null || true; \
	  sleep 2; \
	fi
	@if ss -tln | grep -qE ":($(FRONT_PORT)|$(BACK_PORT)) "; then \
	  echo "端口仍未释放，请手工检查：ss -tlnp | grep -E '$(FRONT_PORT)|$(BACK_PORT)'"; exit 1; \
	fi
	@echo "已停止，端口 $(FRONT_PORT) 与 $(BACK_PORT) 均已释放。"

restart: stop start

status:
	@echo "== 版本 =="
	@cd $(SRC) && printf "  DeepTutor 源码 %s（%s）\n" "$$(git describe --tags --always 2>/dev/null)" "$$(git rev-parse --abbrev-ref HEAD)"
	@$(PY) -c "import deeptutor_ext; print('  扩展包', deeptutor_ext.__version__)" 2>/dev/null || echo "  扩展包 未安装"
	@echo "== 进程 =="
	@pgrep -af "deeptutor start --home $(SRC)|next dev|uvicorn" || echo "  （没有运行中的进程）"
	@echo "== 端口 =="
	@ss -tlnp 2>/dev/null | grep -E ":($(FRONT_PORT)|$(BACK_PORT)) " || echo "  （$(FRONT_PORT) 与 $(BACK_PORT) 均未监听）"

health:
	@echo -n "前端 http://$(LAN_IP):$(FRONT_PORT)/      -> "; \
	  curl -s -o /dev/null -w "HTTP %{http_code}\n" -m 15 http://127.0.0.1:$(FRONT_PORT)/ || echo "请求失败"
	@echo -n "后端 http://$(LAN_IP):$(BACK_PORT)/docs   -> "; \
	  curl -s -o /dev/null -w "HTTP %{http_code}\n" -m 15 http://127.0.0.1:$(BACK_PORT)/docs || echo "请求失败"

logs:
	@tail -f $(LOG)

# ── 学生代码的执行容器 ──────────────────────────────────────────────────

# 构建执行环境的镜像：科学计算库之外还带 transformers 那一套，
# 因为 Hugging Face 的课程从第一章就要用。要下载一两 GB，第一次构建慢。
kernel-build:
	@docker build -t deeptutor-kernel:local $(EXT)/kernel-image
	@echo "镜像已构建。执行 make kernel-stop && make kernel-start 换过去。"

kernel-start:
	@$(EXT)/bin/kernel-container.sh start

kernel-stop:
	@$(EXT)/bin/kernel-container.sh stop

kernel-status:
	@$(EXT)/bin/kernel-container.sh status

kernel-logs:
	@$(EXT)/bin/kernel-container.sh logs

# ── 接入自检 ────────────────────────────────────────────────────────────

verify:
	@$(PY) $(EXT)/bin/verify-integration.py

# ── 升级 ────────────────────────────────────────────────────────────────
#
# 升级要做的事按顺序是：停服务 → 取上游新版本 → 把本地源码改动变基到新版本 →
# 重装后端依赖与前端依赖 → 重新安装扩展 → 自检 → 起服务。
# 只有第三步可能需要人工介入（变基冲突），其余都是机械动作。

upgrade:
	@test -n "$(VERSION)" || { echo "用法：make upgrade VERSION=v1.5.8"; exit 1; }
	@echo "==> 停止服务"
	@$(MAKE) --no-print-directory stop || true
	@echo "==> 取上游 $(VERSION)"
	@cd $(SRC) && { git rev-parse --is-shallow-repository | grep -q true && git fetch --unshallow --tags || git fetch --tags; }
	@cd $(SRC) && git rev-parse -q --verify "$(VERSION)^{commit}" >/dev/null \
	  || { echo "上游没有 $(VERSION) 这个标签，先确认版本号。"; exit 1; }
	@echo "==> 处理本地源码改动"
	@cd $(SRC) && if git rev-parse -q --verify $(LOCAL_BRANCH) >/dev/null; then \
	    if ! git rev-parse -q --verify $(BASE_TAG) >/dev/null; then \
	      echo "有 $(LOCAL_BRANCH) 分支却没有 $(BASE_TAG) 标签，无法判断变基起点，请人工处理。"; exit 1; \
	    fi; \
	    git checkout $(LOCAL_BRANCH) >/dev/null 2>&1; \
	    if git rebase --onto $(VERSION) $(BASE_TAG) $(LOCAL_BRANCH); then \
	      git tag -f $(BASE_TAG) $(VERSION) >/dev/null; \
	      echo "本地改动已变基到 $(VERSION)"; \
	    else \
	      echo "变基有冲突，已停在冲突处。解决后执行 git rebase --continue，"; \
	      echo "再手工执行 git tag -f $(BASE_TAG) $(VERSION)，然后重跑本目标剩余步骤。"; exit 1; \
	    fi; \
	  else \
	    git checkout $(VERSION) >/dev/null 2>&1 && echo "没有本地源码改动，直接切到 $(VERSION)"; \
	  fi
	@echo "==> 重装后端依赖"
	@cd $(SRC) && $(PIP) install -q -e .
	@echo "==> 重装前端依赖"
	@cd $(SRC)/web && npm ci --legacy-peer-deps --silent
	@echo "==> 重新安装扩展"
	@$(MAKE) --no-print-directory install
	@echo "==> 接入自检"
	@$(MAKE) --no-print-directory verify
	@echo "==> 启动"
	@$(MAKE) --no-print-directory start
	@echo "升级完成。"

# ── 本地源码改动的备份 ──────────────────────────────────────────────────
#
# 变基之后 local 分支的提交哈希会变，导出一份补丁文件便于审阅、比对和异地重放。

patches:
	@cd $(SRC) && git rev-parse -q --verify $(LOCAL_BRANCH) >/dev/null \
	  || { echo "还没有 $(LOCAL_BRANCH) 分支，说明目前所有改动都在扩展包里，无需导出。"; exit 0; }
	@mkdir -p $(EXT)/patches
	@rm -f $(EXT)/patches/*.patch
	@cd $(SRC) && git format-patch -o $(EXT)/patches $(BASE_TAG)..$(LOCAL_BRANCH) >/dev/null
	@ls -1 $(EXT)/patches/*.patch 2>/dev/null | sed 's|.*/|  |' || echo "  （没有需要导出的提交）"
