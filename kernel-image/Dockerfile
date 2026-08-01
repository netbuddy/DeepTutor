# 学生代码的执行环境。
#
# 底子是官方的科学计算镜像（pandas、scikit-learn、matplotlib、seaborn 都在），
# 在它之上补两类东西：
#
#   * 深度学习那一套（torch 的 CPU 版、transformers、datasets、evaluate）——
#     Hugging Face 的课程从第一章就开始 `from transformers import pipeline`，
#     没有它们，页面上的代码格全都跑不起来；
#   * 拉模型要用的小工具（huggingface_hub 自带，加 sentencepiece 做分词）。
#
# 装 CPU 版 torch 是有意的：这台机器没有显卡，GPU 版会多带一两 GB 用不上的库。
#
# 构建：cd ~/DeepTutor-ext && make kernel-build

FROM quay.io/jupyter/scipy-notebook:latest

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
