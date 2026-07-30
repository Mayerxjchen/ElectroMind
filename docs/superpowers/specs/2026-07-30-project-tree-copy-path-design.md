# Project Tree Copy Path Design

**Date:** 2026-07-30  
**Status:** Approved for implementation planning

## Goal

Allow users to copy either the absolute path or the project-relative path of
any file or directory shown in the Electron Desktop project's right sidebar.

## Interaction

Right-clicking a project-tree row opens a compact context menu with:

1. `复制绝对路径`
2. `复制项目相对路径`

The menu applies to both files and directories. Normal left-click behavior
(expanding and collapsing directories) remains unchanged.

After a successful copy, the existing toast system reports the copied value:

```text
已复制绝对路径：/Users/name/project/src/app/config.py
```

or:

```text
已复制相对路径：src/app/config.py
```

The context menu closes after a selection, an outside click, Escape, window
blur, or when the project tree is rerendered.

## Path Semantics

Each rendered project node carries its canonical project-relative path from the
tree data. Paths are never reconstructed from visible labels.

- Absolute path: resolve the node's relative path beneath the active
  `RuntimeState.projectPath`.
- Relative path: use the node's normalized project-relative path.
- Project root: relative form is `.`, absolute form is `projectPath`.

Path joining must be platform-aware and must not allow a node path to escape
the active project root. Project-tree data is already produced from that root;
the renderer still treats malformed absolute or parent-escaping node paths as
invalid and does not copy them.

## Clipboard Boundary

The renderer uses `navigator.clipboard.writeText`, which is already used by the
Desktop onboarding and settings UI. No new IPC method or filesystem write is
required.

Clipboard failures display an error toast and leave the menu available for a
retry.

## Rendering

Only project-tree rows receive the context-menu behavior. Sandbox-tree and
artifact rows are unchanged in this phase.

The menu is rendered once at shell level and positioned at the pointer within
the viewport. It uses the existing light/dark theme variables and remains
usable in the narrow right sidebar. Menu actions include accessible roles and
keyboard focus.

## Tests and Verification

Automated tests or extracted pure helpers cover:

- relative path normalization;
- absolute path construction below the project root;
- rejection of absolute and `..` escaping node paths;
- project-root path handling;
- file and directory rows exposing the same menu actions.

Desktop verification requires:

- `npm run check`;
- `npm run compile`;
- manual right-click checks for a file and directory;
- both clipboard values matching the selected node;
- success and failure toasts;
- menu dismissal by outside click and Escape;
- unchanged left-click expand/collapse behavior.

## Non-goals

- opening files or directories from the context menu;
- renaming, deleting, moving, or revealing nodes in Finder;
- adding context menus to the sandbox tree or artifacts;
- a global keyboard shortcut for copying paths.
