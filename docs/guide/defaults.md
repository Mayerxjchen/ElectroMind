# Built-in tools

Language: [简体中文](/zh/guide/defaults) | [日本語](/ja/guide/defaults) | [四川话](/sc/guide/defaults) | English

Optional tools in `pagent.defaults`: `clock`, `region`, `readfile`, `web_search`, `bash`.

```python
from pagent import Agent, LLM, Session, DEFAULT_TOOLS, bash, clock, readfile, region, web_search

agent = Agent(
    llm=LLM("gpt-4o-mini"),
    session=Session("You are helpful."),
    tools=[*DEFAULT_TOOLS],  # clock + region
    max_turns=8,
)
```

`DEFAULT_TOOLS` is `[clock, region]`. Add `web_search` yourself (needs extra install).

## clock {#clock}

Current time as ISO 8601.

```python
tools=[clock]
# utc=True (default) or utc=False for local time
```

## region {#region}

OS locale and timezone hint (no GPS).

```python
tools=[region]
```

## readfile {#readfile}

Read a UTF-8 text file under process `cwd` (absolute or relative path; `~` expanded). Up to **500 code points** per call (`max_chars`). Use **`offset`** to read the next window when the header says `continues at offset N`.

```python
tools=[readfile]
# readfile("src/pagent/defaults.py", max_chars=500, offset=0)
# readfile("src/pagent/defaults.py", max_chars=500, offset=500)
```

## bash {#bash}

Run a **whitelisted** command in process `cwd` (no shell). Currently only **`ls`** is allowed; path arguments must resolve under the workspace (same rules as `readfile`).

```python
tools=[bash]
# bash("ls")
# bash("ls -la src")
```

## web_search {#web-search}

Web search via DuckDuckGo.

```bash
pip install 'pagent[search]'
```

```python
tools=[web_search]
```

## See also

- [Tools](./tools) (write your own `@tool`)
