"""站点钩子的落点：由 ``deeptutor_ext.pth`` 在解释器启动时导入。

这里必须保持极轻——只登记一个「等 DeepTutor 的工具模块加载完再动手」的回调，
绝不在此处导入 DeepTutor 本身。否则每一个用到这个虚拟环境的 Python 进程
（包括 pip、各种小脚本）都要付出加载整个 DeepTutor 的代价。
"""

try:
    from deeptutor_ext.integrate import install

    install()
except Exception:  # 钩子失败不能让解释器起不来
    import logging

    logging.getLogger(__name__).debug("扩展接入登记失败，DeepTutor 将以原样运行", exc_info=True)
