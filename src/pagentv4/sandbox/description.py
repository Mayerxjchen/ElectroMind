"""电脑自描述 —— 生成一段 system prompt，告诉 agent 它面前这台电脑长什么样。

写作原则参考 zagent：整段用「你有一台电脑可以使用」的第一人称视角，
不暴露 sandbox / backend / 虚拟路径这类工程词。工具名跟 sandbox/tools.py 一致。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

COMPUTER_DESCRIPTION_TEMPLATE = """你有一台{computer_name}可以使用。
系统：{os_info}
工作目录：{home}
用户目录：{host_root}
{extra}你可以用这几个工具操作它：
- run_command：执行任意 shell 命令
- read_file：读文件内容，可选带行号；大文件用 start_line/end_line 按行范围读
- write_file：写文件（会自动创建父目录）
- str_replace：把文件里的一段文本替换成新文本
- list_dir：查看当前工作目录里的文件
- list_host_files：查看用户目录里的文件（用于定位用户提到的文件）
- copy_from_host：从用户目录把文件复制到工作目录
- copy_to_host：把工作目录里的文件交付给用户；默认放到用户目录下的 `{artifacts_dir}/` 输出目录

工作目录里的文件是持久的，随时可以查看和修改。
文件工具（read_file / write_file / list_dir 等）只能访问工作目录；用户目录工具（list_host_files / copy_from_host）只能访问用户目录。
run_command 默认受 command_policy 约束：workdir 模式下命令里不能出现工作目录之外的路径（系统目录如 /usr、/bin 除外）；open 模式等同完整 shell。动态路径（如 python -c "open(...)"）无法靠静态扫描完全拦住，需要 OS/容器级隔离。"""


UV_ENVIRONMENT_EXTRA = """Python 依赖：
- 电脑上已装 uv。需要额外 Python 包时，在工作目录建一个 venv（如 .venv），别污染系统 Python。
- 推荐流程：uv venv .venv → uv pip install -p .venv/bin/python <包名> → 用 run_command 跑 .venv/bin/python <脚本>。
- 需要时可用 `uv --help` 查用法。
- 长期不再需要的时候，清理掉虚拟环境。

"""


ProbeRunner = Callable[[str], Awaitable[dict]]


async def uv_environment_extra(run_probe: ProbeRunner) -> str:
    result = await run_probe("command -v uv >/dev/null 2>&1 && uv --version")
    if result.get("ok") and result.get("exit_code") == 0:
        return UV_ENVIRONMENT_EXTRA
    return ""


async def build_computer_description(
    *,
    computer_name: str,
    os_info: str,
    home: str,
    host_root: str,
    artifacts_dir: str,
    extra: str,
    run_probe: ProbeRunner,
) -> str:
    uv_extra = await uv_environment_extra(run_probe)
    return COMPUTER_DESCRIPTION_TEMPLATE.format(
        computer_name=computer_name,
        os_info=os_info,
        home=home,
        host_root=host_root,
        artifacts_dir=artifacts_dir,
        extra=extra + uv_extra,
    )
