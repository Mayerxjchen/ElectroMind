"""顶层命令分派包：每个子命令一个模块，统一 ``run(argv) -> int``（进程退出码）。

- interactive: 交互模式（默认入口 / 携带初始 prompt / -c / -r）
- print_mode:  非交互 -p 模式
- session / config / skills / doctor / app / service: 顶层子命令
"""
