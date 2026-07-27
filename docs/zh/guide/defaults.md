# 内置工具

语言： [中文](/zh/guide/defaults) | [English](/guide/defaults) | [日本語](/ja/guide/defaults) | [四川话](/sc/guide/defaults)

`pagent.defaults` 提供可选工具：`clock`、`region`、`readfile`、`web_search`、`bash`。

```python
from pagent import Agent, LLM, Session, DEFAULT_TOOLS, bash, clock, readfile, region, web_search

agent = Agent(
    llm=LLM("gpt-4o-mini"),
    session=Session("你是助手。"),
    tools=[*DEFAULT_TOOLS],  # clock + region
    max_turns=24,
)
```

`DEFAULT_TOOLS` 为 `[clock, region]`。`web_search` 需单独加入并安装依赖。

## clock {#clock}

返回当前时间（ISO 8601）。

```python
tools=[clock]
# 默认 utc=True；utc=False 为本地时间
```

## region {#region}

系统语言、时区等（无 GPS）。

```python
tools=[region]
```

## readfile {#readfile}

用**绝对路径**读取当前工作目录下的 UTF-8 文本。相对路径会报错。最多 **500 个 Unicode 码点**（默认 `max_chars=500`）。

```python
tools=[readfile]
```

## bash {#bash}

在进程 `cwd`（工作区）内执行**白名单**命令（不走 shell）。目前仅允许 **`ls`**；路径参数须落在工作区内（规则同 `readfile`）。

```python
tools=[bash]
```

## web_search {#web-search}

DuckDuckGo 网页搜索。

```bash
pip install 'pagent[search]'
```

```python
tools=[web_search]
```

## 相关

- [工具](./tools)（自定义 `@tool`）
