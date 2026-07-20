"""电脑自描述 —— 生成一段 system prompt，告诉 agent 它面前这台电脑长什么样。

写作原则参考 zagent：整段用「你有一台电脑可以使用」的第一人称视角，
不暴露 sandbox / backend / 虚拟路径这类工程词。工具名跟 sandbox/tools.py 一致。

这段叙事随实际启用的工具动态渲染：工具清单由 `sandbox.spec.tools` 白名单决定，
只有启用的工具才会出现在提示词里，与注册给模型的 tool schema 保持一致。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

# 每个工具在提示词里的一句话说明；键与 sandbox/tools.py 的 SANDBOX_TOOL_NAMES 对齐。
# copy_to_host 的说明含 {artifacts_dir} 占位，渲染时再 format。
TOOL_DESCRIPTIONS = {
    "run_command": "run_command：执行任意 shell 命令",
    "read_file": "read_file：读文件内容，可选带行号；大文件用 start_line/end_line 按行范围读",
    "write_file": "write_file：写文件（会自动创建父目录）",
    "str_replace": "str_replace：把文件里的一段文本替换成新文本",
    "list_dir": "list_dir：查看当前工作目录里的文件",
    "list_host_files": "list_host_files：查看用户目录里的文件（用于定位用户提到的文件）",
    "copy_from_host": (
        "copy_from_host：从用户目录把文件或目录复制到工作目录"
        "（目录会先 tar.gz 打包再解压）"
    ),
    "copy_to_host": (
        "copy_to_host：把工作目录里的文件交付给用户；"
        "固定写到用户目录下的 `{artifacts_dir}/` 输出目录"
    ),
}

COMPUTER_DESCRIPTION_TEMPLATE = """你有一台{computer_name}可以使用。
系统：{os_info}
工作目录（文件工具路径）：{home}
用户目录：{host_root}
{extra}你可以用这几个工具操作它：
{tool_lines}

工作目录里的文件是持久的，随时可以查看和修改。{boundary_notes}"""

# 文件工具的访问边界注记；仅当相关工具启用时才拼进提示词。
WORKDIR_BOUNDARY_NOTE = (
    "文件工具（read_file / write_file / list_dir 等）只能访问工作目录；"
    "用户目录工具（list_host_files / copy_from_host）只能访问用户目录。"
)
COMMAND_POLICY_NOTE = (
    "run_command 默认受 command_policy 约束：workdir 模式下命令里不能出现工作目录"
    "之外的路径（系统目录如 /usr、/bin 除外）；open 模式等同完整 shell。"
    '动态路径（如 python -c "open(...)"）无法靠静态扫描完全拦住，需要 OS/容器级隔离。'
)


def render_tool_lines(tool_names: Sequence[str], *, artifacts_dir: str) -> str:
    """按启用的工具渲染 `- 工具名：说明` 列表；未知名忽略。"""
    lines = []
    for name in tool_names:
        text = TOOL_DESCRIPTIONS.get(name)
        if text is None:
            continue
        lines.append("- " + text.format(artifacts_dir=artifacts_dir))
    return "\n".join(lines)


def render_boundary_notes(tool_names: Sequence[str]) -> str:
    """按启用的工具条件拼接边界注记：无关工具没启用就不提对应约束。"""
    names = set(tool_names)
    notes = []
    file_tools = {"read_file", "write_file", "list_dir"}
    host_tools = {"list_host_files", "copy_from_host"}
    if names & file_tools and names & host_tools:
        notes.append(WORKDIR_BOUNDARY_NOTE)
    if "run_command" in names:
        notes.append(COMMAND_POLICY_NOTE)
    if not notes:
        return ""
    return "\n" + "\n".join(notes)


UV_ENVIRONMENT_EXTRA = """Python 依赖：
- 电脑上已装 uv。需要额外 Python 包时，在工作目录建一个 venv（如 .venv），别污染系统 Python。
- 推荐流程：uv venv .venv → uv pip install -p .venv/bin/python <包名> → 用 run_command 跑 .venv/bin/python <脚本>。
- 需要时可用 `uv --help` 查用法。
- 长期不再需要的时候，清理掉虚拟环境。

"""

NODE_ENVIRONMENT_EXTRA = """Node.js 依赖：
- 电脑上已装 node 和 npm。做 Node 项目时在工作目录初始化（如 npm init -y），依赖装到本地 node_modules，别往全局乱装。
- 推荐流程：npm init -y → npm install <包名> → node <脚本> 或 npm run <script>。
- 需要时可用 `node --version`、`npm --help` 确认环境。

"""

BROWSER_ENVIRONMENT_EXTRA = """Headless 浏览器：
- 电脑上已装 Chromium（chromium-browser）。截图、渲染 HTML、导出 PDF 时用它，别指望 GUI。
- 已预装 Noto Sans CJK 中文字体；HTML 里别只写「微软雅黑 / PingFang」等 Windows/macOS 字体，应加 `Noto Sans CJK SC` 或通用 `sans-serif`。
- 容器里必须带：`--headless --disable-gpu --no-sandbox --disable-dev-shm-usage`（$CHROMIUM_FLAGS 已预设）。
- 示例：chromium-browser $CHROMIUM_FLAGS --screenshot=out.png https://example.com
- 本地 HTML：chromium-browser $CHROMIUM_FLAGS --print-to-pdf=out.pdf file:///home/agent/page.html
- Puppeteer/Playwright 可设 PUPPETEER_EXECUTABLE_PATH=$CHROME_BIN 指向系统 Chromium。

"""


ProbeRunner = Callable[[str], Awaitable[dict]]


async def uv_environment_extra(run_probe: ProbeRunner) -> str:
    result = await run_probe("command -v uv >/dev/null 2>&1 && uv --version")
    if result.get("ok") and result.get("exit_code") == 0:
        return UV_ENVIRONMENT_EXTRA
    return ""


async def node_environment_extra(run_probe: ProbeRunner) -> str:
    result = await run_probe("command -v node >/dev/null 2>&1 && node --version")
    if result.get("ok") and result.get("exit_code") == 0:
        return NODE_ENVIRONMENT_EXTRA
    return ""


async def browser_environment_extra(run_probe: ProbeRunner) -> str:
    result = await run_probe(
        "command -v chromium-browser >/dev/null 2>&1 && chromium-browser --version"
    )
    if result.get("ok") and result.get("exit_code") == 0:
        return BROWSER_ENVIRONMENT_EXTRA
    return ""


async def environment_extra(run_probe: ProbeRunner) -> str:
    uv_extra = await uv_environment_extra(run_probe)
    node_extra = await node_environment_extra(run_probe)
    browser_extra = await browser_environment_extra(run_probe)
    return uv_extra + node_extra + browser_extra


async def build_computer_description(
    *,
    computer_name: str,
    os_info: str,
    home: str,
    host_root: str,
    artifacts_dir: str,
    extra: str,
    tool_names: Sequence[str],
    run_probe: ProbeRunner,
) -> str:
    tool_extra = await environment_extra(run_probe)
    return COMPUTER_DESCRIPTION_TEMPLATE.format(
        computer_name=computer_name,
        os_info=os_info,
        home=home,
        host_root=host_root,
        extra=extra + tool_extra,
        tool_lines=render_tool_lines(tool_names, artifacts_dir=artifacts_dir),
        boundary_notes=render_boundary_notes(tool_names),
    )
