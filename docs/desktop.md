# Desktop app

Language: [中文](/zh/desktop) | English

**pagent Desktop** is a desktop workbench for talking to an AI agent: session history on the left, chat in the center, sandbox files and generated artifacts on the right.

This page is for **end users** — download, API key, first task, everyday controls. To hack on the app itself, see the [developer README](https://github.com/SyncLionPaw/pagent/blob/main/editors/desktop/README.md).

## Install

### 1. Install the backend (required)

Desktop needs the `pagent` command on your machine (same as the VS Code extension):

```bash
uv tool install pagent
```

If the app later says it cannot start the backend, make sure `pagent` is on your `PATH`, or reinstall with the command above.

### 2. Download the app

Get the desktop build from [pagent GitHub Releases](https://github.com/SyncLionPaw/pagent/releases):

- **macOS (Apple Silicon)** — `pagent-Desktop-<version>-arm64.zip`, or `pagent Desktop.app` inside the release assets.

Unzip and move **pagent Desktop** into **Applications**.

### macOS says the app is “damaged”?

Downloads from GitHub get a **quarantine** flag. Unsigned apps often show *“pagent Desktop is damaged and can’t be opened”* — the build is usually fine.

**Fix (recommended)** — run in Terminal:

```bash
xattr -cr "/Applications/pagent Desktop.app"
```

Then open the app normally. The zip also includes **`打开说明.txt`** (Chinese open instructions).

**Right-click → Open** works for some Gatekeeper prompts but not always for the “damaged” message; prefer `xattr` above.

**Windows / Linux** builds are not published yet. Use the [VS Code extension](./vscode) or the `pagent` CLI.

## Before your first message: API key

**On first launch**, if pagent or an API key is missing, a blocking **Setup** wizard opens (environment → API key → sandbox) — the main UI stays locked until those are ready. Reopen the wizard anytime from the user menu → **Setup**. The **environment health check** in Settings is separate: status lights and disk usage, not a wizard.

It checks:

- `uv` / `pagent` on PATH (one-click install or copy commands)
- API key (writes `~/.pagent/pagent.toml`)
- Optional: `docker` / `podman` and the `pagent:latest` image (for container sandbox only)

Choose **Set up later** to skip; you still need a key before chatting.

Without the wizard, configure a key manually:

**Environment variable:**

```bash
export DEEPSEEK_API_KEY=sk-...
```

**Config file (recommended):** create `~/.pagent/pagent.toml`:

```toml
[provider]
api_key = "sk-..."
model = "deepseek-v4-flash"
```

More providers: [Providers & API keys](./guide/providers).

If the key is missing, you will see an error after you send a message. Open **Settings** (gear) for an **environment health check** (status lights + disk usage for `~/.pagent` and the sandbox image) and a read-only overview of `pagent.toml` — edit the file in a text editor to change values.

## First launch

1. Open **pagent Desktop**.
2. The app starts the backend automatically and tries to **resume your latest conversation** for the current project.
3. To start fresh, click **New task** in the sidebar.

### Create a task

In the **New task** dialog:

| Field | What to pick |
| --- | --- |
| **Sandbox** | **local** — runs on your Mac, no Docker needed (default) |
| **Project folder** | The folder on disk you want the agent to work with |

Click **Create session**, type in the box at the bottom, press **Enter** to send (**Shift+Enter** for a new line).

## Main window

```text
┌─────────────┬──────────────────────┬─────────────┐
│  Sessions   │       Chat           │  Files &    │
│             │                      │  artifacts  │
└─────────────┴──────────────────────┴─────────────┘
```

- **Left** — past chats; click one to continue.
- **Center** — messages, tool steps, composer.
- **Right** — sandbox tree, project files, outputs (HTML, PDF, etc.), log.

Drag the edges to resize. Press **⌘K** (or the **?** button) for shortcuts.

## Composer

| Control | What it does |
| --- | --- |
| **Send / Stop** | Send; while the agent is running, becomes **Stop** to cancel |
| **Lightning (YOLO)** | Auto-approve tool calls — use only when you trust the task |
| **Ring** | Rough context usage vs model limit |
| **@** | Insert a file from your project or sandbox into the message |

## Settings & help

| Where | What |
| --- | --- |
| **Gear** | Environment health check (status lights + disk usage) + view `pagent.toml` |
| **Book icon** | Open this documentation site in the browser |
| **User menu → Scan docs** | QR code for the docs on your phone |

To change model or advanced sandbox options, edit `pagent.toml` in a text editor.

## Where files go

```text
~/.pagent/
├── pagent.toml       # your API key and model
├── threads/          # conversation history
└── skills/           # optional local skills

<your project>/
└── artifacts/        # files the agent generated (HTML, etc.)
```

Do not share or commit `pagent.toml` if it contains a real API key.

## Something wrong?

| Problem | Try |
| --- | --- |
| “Bridge” or backend won’t start | Run `uv tool install pagent`; check the log panel on the right |
| Error after sending | Add API key to `pagent.toml` or `DEEPSEEK_API_KEY` |
| “Damaged, can’t be opened” | Run `xattr -cr "/Applications/pagent Desktop.app"` (see above) |
| Settings says no config file | Create `~/.pagent/pagent.toml` as above |
| Tool stuck on “running” | Tap **Stop**, or send again; recent versions fix stale tool cards on reload |

## Also useful

- [VS Code extension](./vscode) — same agent inside VS Code, with guided first-run setup
- [Install CLI](./guide/install) — if `uv` is not installed yet
