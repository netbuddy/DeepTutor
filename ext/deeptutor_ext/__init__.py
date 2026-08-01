"""DeepTutor 扩展包：在不改动 DeepTutor 源码的前提下追加功能。

装进 DeepTutor 所用的同一个虚拟环境后，站点钩子（deeptutor_ext.pth）会在解释器
启动时调用 :func:`deeptutor_ext.integrate.install`，把扩展工具挂进宿主的工具清单。
"""

__version__ = "0.1.0"
