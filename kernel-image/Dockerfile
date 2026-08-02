# 学生代码的执行环境。
#
# 底子是官方的科学计算镜像（pandas、scikit-learn、matplotlib、seaborn 都在），
# 在它之上补三类东西：
#
#   * 深度学习那一套（torch 的 CPU 版、transformers、datasets、evaluate）——
#     Hugging Face 的课程从第一章就开始 `from transformers import pipeline`，
#     没有它们，页面上的代码格全都跑不起来；
#   * 拉模型要用的小工具（huggingface_hub 自带，加 sentencepiece 做分词）；
#   * 三套语言工具链：Go、Node、Rust。课程里的代码格靠它们跑。
#
# 装 CPU 版 torch 是有意的：这台机器没有显卡，GPU 版会多带一两 GB 用不上的库。
#
# ── 为什么 Go 和 Node 是从 vendor/ 拷进来而不是构建时下载 ──
#
# 这台机器通过 Tailscale 的出口访问 dl.google.com、nodejs.org 这些站点。
# 宿主上 curl 得到，但**容器网络到不了那条链路**——容器把域名解析到
# 198.19.x 的 Tailscale 地址，却没有到那个网段的路由，表现是 SSL 连接失败。
# 所以先在宿主上下载好放进 vendor/，构建时只做拷贝。
#
# 下载（换版本时重跑一次）：
#   cd ~/DeepTutor-ext/kernel-image/vendor
#   curl -fsSLO https://dl.google.com/go/go1.25.5.linux-amd64.tar.gz
#   curl -fsSL -o node.tar.xz https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-x64.tar.xz
#
# Rust 走系统源（apt 能通），版本是 1.75。比当前 stable 老一些，
# 但课程用到的语言特性它全都有；换成 rustup 需要构建时联网，这台机器上做不到。
#
# 构建：cd ~/DeepTutor-ext && make kernel-build

FROM quay.io/jupyter/scipy-notebook:latest

USER root

# ── Go ──────────────────────────────────────────────────────────────
#
# 这一段之前不在构建脚本里，Go 只存在于已经跑起来的那个镜像里——
# 谁重建一次镜像，Go 课就全废了。补回来。
COPY vendor/go.tar.gz /tmp/go.tar.gz
RUN set -eux; \
    tar -C /usr/local -xzf /tmp/go.tar.gz; \
    rm /tmp/go.tar.gz; \
    /usr/local/go/bin/go version

# ── Node ────────────────────────────────────────────────────────────
#
# 选 22 的 LTS 线：--experimental-strip-types 在 22.6 之后可用，
# TypeScript 的格子不必先编译再跑。
COPY vendor/node.tar.xz /tmp/node.tar.xz
RUN set -eux; \
    tar -C /usr/local --strip-components=1 -xJf /tmp/node.tar.xz; \
    rm /tmp/node.tar.xz; \
    node --version; npm --version

# ── Rust ────────────────────────────────────────────────────────────
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends rustc cargo; \
    apt-get clean; rm -rf /var/lib/apt/lists/*; \
    rustc --version; cargo --version

# 工具链进 PATH，各自的缓存目录放到工作目录下——那是宿主挂进来的可写目录，
# 容器重建不用重来一遍。
ENV PATH=/usr/local/go/bin:${PATH} \
    GOPATH=/home/jovyan/work/.gopath \
    GOCACHE=/home/jovyan/work/.gocache \
    GOFLAGS=-mod=mod

USER ${NB_UID}

# torch 的 CPU 版走官方专用源，避免把 CUDA 依赖一并拖下来。
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

RUN pip install --no-cache-dir \
        transformers \
        datasets \
        evaluate \
        accelerate \
        sentencepiece \
        huggingface_hub

# 模型缓存放到工作目录下（那是宿主挂进来的可写目录），重建容器不用重新下载。
# 具体路径由启动脚本用环境变量传进来，这里只给一个容器内的兜底值。
ENV HF_HOME=/home/jovyan/work/.hf-cache \
    TRANSFORMERS_VERBOSITY=error
