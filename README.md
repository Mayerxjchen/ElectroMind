# pagent

基于 **OpenAI 兼容 Chat Completions** 的轻量 **async** agent 核心：

- `Session`：对话缓冲 `messages`，用 `session += {...}` 追加消息，`reset()` 清空
- `LLM`：对 `AsyncOpenAI` 的薄封装，只负责单次 `invoke`；历史由 `Session` 组装
- `DeepSeek`：同上，接入 [DeepSeek 官方 OpenAI 兼容 API](https://api-docs.deepseek.com/zh-cn/)（详见下文）
- `Ollama` / `Vllm` / `Sglang`：本地 OpenAI 兼容服务默认地址占位（`/v1`），见下文
- `@tool()` / `FunctionTool`：把 Python 函数变成 function-calling 的 schema
- `Agent`：多轮循环，直到模型不再调用工具或达到 `max_turns`
- **内置工具**（`defaults`）：`clock`（UTC/本地 ISO）、`region`（本机 locale / 时区等线索，非 GPS）；`DEFAULT_TOOLS` 两者皆含，可按需删减

## 安装

```bash
pip install pagent
```

从源码目录：

```bash
cd pagent
uv sync
pip install -e .
```

## 环境变量（API Key）

默认 `LLM` 会读 **`OPENAI_API_KEY`**（与 OpenAI 官方一致）；用 **`DeepSeek()`** 时读 **`DEEPSEEK_API_KEY`**。

在终端里（当前 shell 有效）：

```bash
export OPENAI_API_KEY="sk-..."   # macOS / Linux
# Windows (cmd):  set OPENAI_API_KEY=sk-...
# Windows (PowerShell): $env:OPENAI_API_KEY="sk-..."
```

长期生效可写进 `~/.zshrc` / `~/.bashrc`，或用 [direnv](https://direnv.net)、`.env` + 你自己的加载方式（本库不读 `.env` 文件）。

若既没设置环境变量、调用时也没传 `apikey=`，请求会带着空 key 发出，一般会认证失败——请至少满足其一。

## DeepSeek

以官方文档为准：[**DeepSeek API 文档**](https://api-docs.deepseek.com/zh-cn/)（OpenAI SDK 兼容）。

| 项目 | 值 |
|------|-----|
| OpenAI SDK `base_url` | `https://api.deepseek.com`（与本库 `DeepSeek.BASE_URL` 一致） |
| API Key | 在 [控制台](https://platform.deepseek.com/api_keys) 申请；本地可 `export DEEPSEEK_API_KEY=...` |
| 常用模型（见文档「模型 & 价格」） | `deepseek-v4-flash`、`deepseek-v4-pro` 等 |
| `deepseek-chat` / `deepseek-reasoner` | 官方说明将于 **2026/07/24** 弃用；兼容上分别对应 **`deepseek-v4-flash` 的非思考 / 思考** 用法，建议新代码直接用 v4 模型名 |

示例（默认模型为 `deepseek-v4-flash`，可用第一个参数换掉）：

```python
from pagent import Agent, DeepSeek, Session, tool

agent = Agent(
    llm=DeepSeek(),  # 或 DeepSeek("deepseek-v4-pro")
    session=Session(),
    tools=[...],
)
```

若要用文档里的 **思考模式** 等扩展字段，可通过 `request_kwargs` 传给 `chat.completions.create`（示例见官网「首次调用 API」——如 `reasoning_effort`、`extra_body` / `thinking` 等），例如：

```python
DeepSeek(
    "deepseek-v4-pro",
    request_kwargs={
        "reasoning_effort": "high",
        "extra_body": {"thinking": {"type": "enabled"}},
    },
)
```

具体参数名与是否必填以 [官方文档](https://api-docs.deepseek.com/zh-cn/) 当期说明为准。

### 本地：Ollama、vLLM、SGLang

三者若在本地提供 **OpenAI Chat Completions 兼容 HTTP API**（通常路径带 **`/v1`**），本库的 **`LLM`** 都可以通过 `base_url` + `model_id` 直接使用；我们为常见默认监听地址提供了薄封装：**`Ollama`**、**`Vllm`**、**`Sglang`**。

| 类 | 默认 `base_url` | 备注 |
|----|-----------------|------|
| `Ollama` | `http://127.0.0.1:11434/v1` | 以 [Ollama OpenAI 兼容说明](https://github.com/ollama/ollama/blob/main/docs/openai.md) 为准；`model_id` = 与你本机 `ollama ls` / 拉取的名称一致 |
| `Vllm` | `http://127.0.0.1:8000/v1` | 对应 vLLM 启动 OpenAI API server 的常见端口（以你 `--port` / 文档为准） |
| `Sglang` | `http://127.0.0.1:30000/v1` | 常见于 SGLang router 示例端口，**请按当前启动命令与官方文档校对** |

这些服务多数 **不需要真实 API Key**；`AsyncOpenAI` 往往需要非空字符串，因此未设置环境变量、也未传 `apikey=` 时，我们会填入占位符 **`not-needed`**。你若在服务端配置了鉴权，请设置对应环境变量或传入 `apikey=`：

- `Ollama` → `OLLAMA_API_KEY`（若你使用自定义网关代理）
- `Vllm` → `VLLM_API_KEY`
- `Sglang` → `SGLANG_API_KEY`

示例：

```python
from pagent import Agent, Ollama, Session, tool

agent = Agent(
    llm=Ollama("llama3.2"),
    session=Session(),
    tools=[...],
)
```

另一台机器或换端口：**`base_url`** 可随时覆盖默认值，例如 `Ollama("mistral-small3.3", base_url="http://192.168.1.5:11434/v1")`。

工具调用能否稳定工作取决于 **服务端与具体模型对 function calling 的实现**；遇到问题请先在对应引擎文档里核对是否支持 `/v1/chat/completions` 与 tools 字段。

## 完整示例：工具调用 + 查看用量

下面假设已设置 `OPENAI_API_KEY`，模型名按你账号可用模型修改（示例用 `gpt-4o-mini`）。

将以下内容保存为 `demo.py` 后执行：`python demo.py`。

```python
import asyncio
import os

from pagent import Agent, LLM, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Return a short fake weather line for the city.

    Args:
        city: City name in English or Chinese.
    """
    return f"It's sunny in {city} today."


async def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("请先设置环境变量 OPENAI_API_KEY")

    llm = LLM("gpt-4o-mini")
    session = Session("You are a concise assistant. Use tools when needed.")
    agent = Agent(llm=llm, session=session, tools=[get_weather], max_turns=8)

    result = await agent.run("厦门今天天气怎样？用工具查。")
    print("--- reply ---")
    print(result.content)
    print("--- stats ---")
    print(agent.stats)


if __name__ == "__main__":
    asyncio.run(main())
```

`agent.stats` 上会累计 `turns`、token 用量等；`result` 为最后一轮模型返回（`result.usage` 等为该轮信息，具体以 SDK 为准）。

## 接入自己的供应商（任意 OpenAI 兼容网关）

思路：**同一个 `LLM` 类**，换 `base_url`、`model_id`，以及 key 的来源。

### 方式一：显式传参（推荐，最直观）

把网关文档里的 **Base URL**（通常带 `/v1`）、**模型 id**、**API Key** 填进去即可：

```python
import os

from pagent import LLM

llm = LLM(
    "your-model-id-on-that-host",
    base_url="https://your-gateway.example.com/v1",
    apikey=os.environ["MY_LLM_API_KEY"],
)
```

也可以继续用环境变量存 key，变量名你自己定，只要在代码里 `os.environ["..."]` 或 `os.getenv("...")` 读出来传给 `apikey` 即可。

### 方式二：子类固定「自家」默认地址和 key 环境变量

适合团队内封装：把 `BASE_URL`、`API_KEY_ENV_VAR` 写在子类上，`get_api_key()` 会自动读对应环境变量。

```python
import os

from pagent import LLM


class AcmeChat(LLM):
    """示例：公司统一网关。"""

    API_KEY_ENV_VAR = "ACME_LLM_API_KEY"
    BASE_URL = "https://llm.acme.internal/v1"

    def __init__(self, model_id="acme-default", **kwargs):
        super().__init__(model_id, **kwargs)


# 使用前: export ACME_LLM_API_KEY=...
llm = AcmeChat("acme-default")
```

`kwargs` 仍可传 `base_url` / `apikey` / `request_kwargs`，用于临时覆盖默认（与基类 `LLM.__init__` 行为一致）。

### `request_kwargs`：额外请求参数

若网关要求温度、顶层 `extra_body` 等，可挂在构造函数的第四项：

```python
LLM(
    "some-model",
    base_url="https://.../v1",
    apikey=os.environ["MY_KEY"],
    request_kwargs={"temperature": 0.2},
)
```

这些键会并入每次 `chat.completions.create(...)`（本库固定 `stream=False`）。

## 维护者：GitHub 自动发布到 PyPI

仓库带 [`.github/workflows/publish.yml`](.github/workflows/publish.yml)：每次在 GitHub 上 **Release → Publish a release**（正式发布，不是 draft）时，CI 会 `uv build` 并上传到 PyPI。

**一次性配置（推荐 [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)，无需把 token 写进 GitHub Secrets）：**

1. 在 [PyPI](https://pypi.org/) 上确保已有项目 `pagent`（首次可用手动 `uv publish` 建项目，或在项目设置里按 PyPI 说明添加 pending publisher）。
2. 打开该项目的 **Manage → Settings → Publishing**，添加 **Trusted Publisher**：
   - Provider：**GitHub**
   - Owner / Repository：你的 `用户名/pagent`
   - Workflow name：`publish.yml`
   - **Environment** 留空（与当前 workflow 一致；若你在 PyPI 填了 environment，则须在 GitHub 仓库里建同名 [Environment](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#jobsjob_idenvironment)，并在 workflow 里写 `environment: 名字`）。
3. 发版前把 `pyproject.toml` 里的 **`version`** 改成新版本，合并到默认分支。
4. 在 GitHub 上 **新建 tag**（例如 `v0.1.1`）并 **Create release**；发布完成后等几分钟再查 [pypi.org/project/pagent](https://pypi.org/project/pagent/)。

若暂不想配 OIDC，仍可在本机用 **API token** + `uv publish`。

---

**说明**：只要对方实现的是 **OpenAI Chat Completions** 兼容接口（路径、字段与官方相近），上述方式即可；若对方 API 形状完全不同，需要在网关侧做适配，或自行改写 `LLM.invoke`，那已超出本库的默认假设。
