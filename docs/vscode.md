# VS Code Extension

Language: [中文](/zh/vscode) | English

The pagent VS Code extension adds a chat panel to VS Code. After installing the
extension, you can talk to pagent from the sidebar and let it read files, run
commands, call tools, and resume previous conversations in the current workspace.

## Install

Download the VS Code extension package from
[pagent GitHub Releases](https://github.com/SyncLionPaw/pagent/releases):

Download the file ending in `.vsix`.

Install it in VS Code:

1. Open the **Extensions** panel.
2. Click the `...` menu in the upper-right corner of the Extensions panel.
3. Select **Install from VSIX...**.
4. Pick the `.vsix` file you downloaded.
5. Reload the VS Code window after installation. The pagent icon appears in the
   activity bar.

You can also open the command palette and run:

```text
Extensions: Install from VSIX...
```

The extension also needs the `pagent` command on your machine. Install the CLI
first:

```bash
uv tool install pagent
```

If VS Code cannot find `pagent`, set `pagent.command` to the absolute path of
the executable.

## First Run

Click the pagent icon in the activity bar and open **Chat**.

If no API key has been configured yet, the extension asks for:

- API key
- model name, default: `deepseek-v4-flash`
- base URL, optional

After saving the config, the extension writes `pagent.toml` and you can start
chatting.

## Files Created by the Extension

The extension uses a pagent home directory for config, conversation history, and
local skills.

If the current workspace already has `.pagent/`, the extension uses:

```text
<workspace>/.pagent/
```

If the workspace does not have `.pagent/`, the extension uses:

```text
~/.pagent/
```

If you want a project to have its own config and conversation history, create
`.pagent/` in the project root:

```bash
mkdir .pagent
```

After that, the extension uses the project-local `.pagent/`.

Common files:

```text
.pagent/
├── pagent.toml          # Config: model, API key, sandbox, permissions
├── threads/             # Conversation history
│   └── thread-.../
│       ├── metainfo.json
│       └── messages.jsonl
└── skills/              # Optional local skills
```

What these files mean:

| Path | Contents |
| --- | --- |
| `pagent.toml` | Model, API key, base URL, runtime mode, SSH, approval mode |
| `threads/` | Conversation history; each thread is a resumable conversation |
| `metainfo.json` | Thread title, created time, updated time, message count |
| `messages.jsonl` | Messages in that thread |
| `skills/` | Optional local skills |

Empty threads with no messages are cleaned up when the backend exits normally.

If `.pagent/` is inside a project that you commit to Git, avoid committing a
`pagent.toml` that contains an API key.

## Config File

The extension writes `pagent.toml` after the first API key setup. You can also
edit it manually:

```toml
[provider]
api_key = "sk-..."
model = "deepseek-v4-flash"
# base_url = "https://..."

[sandbox]
backend = "local" # local | docker | podman | ssh
command_policy = "workdir"

[ssh]
config_path = "~/.ssh/config"
host = "my-remote"
workdir = "~/pagent"

[permission]
mode = "prompt" # prompt | auto
```

You can also provide the API key with an environment variable:

```bash
export DEEPSEEK_API_KEY=sk-...
```

## Use the Chat

Open Chat, type in the composer, and press Enter to send. Use Shift+Enter for a
new line.

The extension streams the answer as it arrives. Reasoning appears in a
collapsible `thinking` panel. Tool calls appear as tool cards, which can be
expanded for details.

## Title Bar Buttons

The Chat title bar has three buttons:

| Button | Meaning |
| --- | --- |
| Open in editor | Open a wider chat panel in the editor area |
| Resume session | Pick a previous conversation and continue it |
| New session | Start a new empty conversation |

## Composer Buttons

The composer footer has:

| Button | Meaning |
| --- | --- |
| `/` | Open the slash command menu |
| Runtime mode | Choose where tools run |
| Stamp | Toggle YOLO mode |
| Send | Send the current message |

YOLO mode automatically approves dangerous tool calls such as running commands.
Use it only when you trust the current workspace and request.

## Runtime Modes

The runtime mode controls where pagent tools run.

| Mode | Meaning |
| --- | --- |
| Local | Run tools on the current machine |
| Docker | Run tools in a Docker container |
| Podman | Run tools in a Podman container |
| SSH | Run tools on a remote machine |

Docker and Podman appear only when the corresponding CLI exists in the VS Code
host environment.

SSH mode reads `~/.ssh/config` and shows explicit `Host` aliases. Wildcard
entries such as `Host *` are hidden.

## Slash Commands

Click `/`, or type `/` in the composer, to open the command menu.

Current commands:

| Command | Meaning |
| --- | --- |
| `/help` | Show available commands |
| `/skills` | Show loaded skills |
| `/history` | Show conversation information |
| `/pwd` | Show the active pagent home / workspace context |
| `/ls` | List files in the current context |

Slash commands do not start a model turn and do not enter conversation history.

## Tool Approval

By default, dangerous tools pause for approval. The tool card shows approve and
deny buttons.

If YOLO mode is enabled, approvals are skipped. You can also set:

```toml
[permission]
mode = "auto"
```

## Troubleshooting

**The pagent icon does not appear.**

Make sure the `.vsix` installation succeeded, then reload the VS Code window.

**VS Code cannot find `pagent`.**

Run `uv tool install pagent`. If it still cannot be found, set
`pagent.command` in VS Code settings.

**Docker or Podman does not appear in the menu.**

The corresponding CLI is missing from the VS Code host environment, or it is not
available in PATH.

**SSH hosts do not appear.**

Check `pagent.sshConfigPath` and make sure it contains explicit `Host xxx`
entries.

**Where is conversation history stored?**

Under `threads/` in the active pagent home. In project mode this is usually
`<workspace>/.pagent/threads/`; otherwise it is `~/.pagent/threads/`.
