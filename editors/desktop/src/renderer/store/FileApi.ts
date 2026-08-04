/** Renderer-side file operations API.
 *
 * Every file operation goes through this module — the renderer never
 * touches Node ``fs`` directly.  Each method delegates to the Electron
 * main process via ``window.desktop.*``, which in turn routes to the
 * correct file backend (Local / Sandbox / SSH).
 *
 * File capabilities (copy, export, rename, …) are determined by the
 * backend and reflected in ``FileRef.capabilities``.  The UI renders
 * actions based on capability flags, not by guessing from paths.
 */

import type {
  FilePreview,
  FileRef,
  FileTransferResult,
  PathFormat,
} from "../../shared/protocol";

// ---------------------------------------------------------------------------
// Unsupported operation error
// ---------------------------------------------------------------------------

/** Thrown when a file operation is requested but not yet implemented
 *  in the active desktop backend.  The ``code`` property is stable and
 *  safe for programmatic matching. */
export class UnsupportedOperationError extends Error {
  readonly code = "UNSUPPORTED_OPERATION";

  constructor(operation: string) {
    super(
      `File operation "${operation}" is not yet supported on this desktop version`,
    );
    this.name = "UnsupportedOperationError";
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let _nextId = 1;
function nextId(): string {
  return `file-${Date.now().toString(36)}-${(_nextId++).toString(36)}`;
}

// ---------------------------------------------------------------------------
// Factory: build a FileRef from minimal info + backend query
// ---------------------------------------------------------------------------

export async function resolveFileRef(
  path: string,
  source: FileRef["source"],
  opts?: {
    executionKind?: FileRef["executionKind"];
    threadId?: string;
  },
): Promise<FileRef> {
  const ref: FileRef = {
    id: nextId(),
    source,
    executionKind: opts?.executionKind,
    threadId: opts?.threadId,
    path,
    name: path.split("/").pop() ?? path,
    kind: "file",
    capabilities: {
      preview: false,
      attach: false,
      copyPath: false,
      exportToLocal: false,
      copyToProject: false,
      copyToExecution: false,
      reveal: false,
      rename: false,
      delete: false,
    },
  };
  // Let the backend fill in metadata + capabilities
  return (await window.desktop.getFileMetadata(ref)).ref;
}

// ---------------------------------------------------------------------------
// Path copy
// ---------------------------------------------------------------------------

export async function copyPath(
  ref: FileRef,
  format: PathFormat = "absolute",
): Promise<void> {
  await window.desktop.copyFilePath(ref, format);
}

// ---------------------------------------------------------------------------
// Export (execution → local filesystem)
// ---------------------------------------------------------------------------

export async function exportFile(
  ref: FileRef,
  suggestedName?: string,
): Promise<FileTransferResult> {
  return window.desktop.exportFile(ref, suggestedName);
}

// ---------------------------------------------------------------------------
// Import (local → execution)
// ---------------------------------------------------------------------------

/** Placeholder FileRef used for unsupported-operation results. */
function emptyRef(source: FileRef["source"] = "project"): FileRef {
  return {
    id: "",
    source,
    path: "",
    name: "",
    kind: "file",
    capabilities: {
      preview: false,
      attach: false,
      copyPath: false,
      exportToLocal: false,
      copyToProject: false,
      copyToExecution: false,
      reveal: false,
      rename: false,
      delete: false,
    },
  };
}

export async function importFiles(
  target: FileRef,
  localPaths: string[],
): Promise<FileTransferResult[]> {
  if (!window.desktop.importFiles) {
    return localPaths.map((p) => ({
      ok: false,
      source: { ...emptyRef("project"), path: p, name: p.split("/").pop() ?? p },
      target,
      size: 0,
      error: "File import is not yet supported on this desktop version",
    }));
  }
  return window.desktop.importFiles(target, localPaths);
}

// ---------------------------------------------------------------------------
// Cross-environment copy
// ---------------------------------------------------------------------------

export async function copyFileBetween(
  source: FileRef,
  target: FileRef,
): Promise<FileTransferResult> {
  if (!window.desktop.copyFileBetween) {
    return {
      ok: false,
      source,
      target,
      size: 0,
      error: "Cross-environment file copy is not yet supported on this desktop version",
    };
  }
  return window.desktop.copyFileBetween(source, target);
}

// ---------------------------------------------------------------------------
// Rename / delete
// ---------------------------------------------------------------------------

export async function renameFile(
  ref: FileRef,
  newName: string,
): Promise<FileRef> {
  if (!window.desktop.renameFile) {
    throw new UnsupportedOperationError("renameFile");
  }
  return window.desktop.renameFile(ref, newName);
}

export async function deleteFile(ref: FileRef): Promise<void> {
  if (!window.desktop.deleteFile) {
    throw new UnsupportedOperationError("deleteFile");
  }
  await window.desktop.deleteFile(ref);
}

// ---------------------------------------------------------------------------
// Preview
// ---------------------------------------------------------------------------

export async function previewFile(ref: FileRef): Promise<FilePreview> {
  if (!window.desktop.previewFile) {
    return {
      name: ref.name,
      path: ref.path,
      size: ref.size ?? 0,
      kind: "binary",
      reason: "File preview is not yet supported on this desktop version",
    };
  }
  return window.desktop.previewFile(ref);
}

// ---------------------------------------------------------------------------
// Reveal in OS file manager
// ---------------------------------------------------------------------------

export async function revealInFinder(ref: FileRef): Promise<void> {
  await window.desktop.revealInFinder(ref);
}

// ---------------------------------------------------------------------------
// Context menu
// ---------------------------------------------------------------------------

export interface ContextMenuAction {
  label: string;
  icon?: string;
  enabled: boolean;
  action: () => void;
}

export interface ContextMenuSeparator {
  type: "separator";
}

export type ContextMenuItem = ContextMenuAction | ContextMenuSeparator;

export function buildContextMenu(
  ref: FileRef,
  callbacks: {
    onPreview?: () => void;
    onAttach?: () => void;
    onCopyPath?: (format: PathFormat) => void;
    onExport?: () => void;
    onCopyToProject?: () => void;
    onCopyToExecution?: () => void;
    onReveal?: () => void;
    onRename?: () => void;
    onDelete?: () => void;
  },
): ContextMenuItem[] {
  const { capabilities: cap } = ref;

  return [
    {
      label: "打开预览",
      icon: "eye",
      enabled: cap.preview,
      action: callbacks.onPreview ?? (() => {}),
    },
    { type: "separator" as const },
    {
      label: "附加到对话",
      icon: "plus",
      enabled: cap.attach,
      action: callbacks.onAttach ?? (() => {}),
    },
    { type: "separator" as const },
    {
      label: "复制文件名",
      enabled: cap.copyPath,
      action: () => callbacks.onCopyPath?.("name"),
    },
    {
      label: "复制相对路径",
      enabled: cap.copyPath,
      action: () => callbacks.onCopyPath?.("relative"),
    },
    {
      label: "复制绝对路径",
      enabled: cap.copyPath,
      action: () => callbacks.onCopyPath?.("absolute"),
    },
    {
      label: "复制 Agent URI",
      enabled: cap.copyPath,
      action: () => callbacks.onCopyPath?.("uri"),
    },
    { type: "separator" as const },
    {
      label: "导出到本机…",
      icon: "download",
      enabled: cap.exportToLocal,
      action: callbacks.onExport ?? (() => {}),
    },
    {
      label: "复制到项目…",
      enabled: cap.copyToProject,
      action: callbacks.onCopyToProject ?? (() => {}),
    },
    {
      label: "复制到执行环境…",
      enabled: cap.copyToExecution,
      action: callbacks.onCopyToExecution ?? (() => {}),
    },
    { type: "separator" as const },
    {
      label: "在 Finder 中显示",
      icon: "folder",
      enabled: cap.reveal,
      action: callbacks.onReveal ?? (() => {}),
    },
    {
      label: "重命名",
      enabled: cap.rename,
      action: callbacks.onRename ?? (() => {}),
    },
    {
      label: "删除",
      icon: "trash",
      enabled: cap.delete,
      action: callbacks.onDelete ?? (() => {}),
    },
  ].filter((item): item is ContextMenuAction => {
    if (!("label" in item)) return false;
    const action = item as ContextMenuAction;
    return action.enabled;
  });
}
