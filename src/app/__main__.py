"""CLI 入口：``python -m app`` 与 PyInstaller 单文件双兼容。

必须用绝对导入：PyInstaller 把本文件作为顶层脚本打包成 ``__main__`` 模块，
相对导入（``from .cli import main``）在该模式下会 ``ImportError: attempted
relative import with no known parent package``。
"""

from app.cli import main

main()
