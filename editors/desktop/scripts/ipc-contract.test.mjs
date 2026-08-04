/** IPC contract test: every channel exposed by preload must have a
 *  registered handler in main.  Phantom channels (registered in preload
 *  but absent in main) are a runtime error in Electron and are forbidden.
 *
 *  Optional operations that are not yet implemented are typed as optional
 *  in the DesktopApi contract and are NOT exposed in preload at all.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const preload = readFileSync(
  new URL("../src/preload/index.ts", import.meta.url),
  "utf8",
);
const main = readFileSync(
  new URL("../src/main/index.ts", import.meta.url),
  "utf8",
);

// ---------------------------------------------------------------------------
// Extract registered channels from main process
// ---------------------------------------------------------------------------

function extractMainChannels(source) {
  const channels = new Set();
  const re = /ipcMain\.handle\(\s*"([^"]+)"/g;
  let match;
  while ((match = re.exec(source)) !== null) {
    channels.add(match[1]);
  }
  // Also catch ipcMain.on for push channels
  return channels;
}

// ---------------------------------------------------------------------------
// Extract invoked channels from preload
// ---------------------------------------------------------------------------

function extractPreloadChannels(source) {
  const channels = new Set();
  // ipcRenderer.invoke("desktop:xxx", ...)
  const invokeRe = /ipcRenderer\.invoke\(\s*"([^"]+)"/g;
  let match;
  while ((match = invokeRe.exec(source)) !== null) {
    channels.add(match[1]);
  }
  // ipcRenderer.on("desktop:xxx", ...) for push channels
  const onRe = /ipcRenderer\.on\(\s*"([^"]+)"/g;
  while ((match = onRe.exec(source)) !== null) {
    channels.add(match[1]);
  }
  return channels;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("every preload-invoked channel has a main handler", () => {
  const mainChannels = extractMainChannels(main);
  const preloadChannels = extractPreloadChannels(preload);

  assert.ok(mainChannels.size > 0, "main must register at least one handler");
  assert.ok(preloadChannels.size > 0, "preload must invoke at least one channel");

  const missing = [...preloadChannels].filter((ch) => !mainChannels.has(ch));

  assert.deepStrictEqual(
    missing,
    [],
    `Every IPC channel invoked by preload must have a corresponding ` +
    `ipcMain.handle() or ipcMain.on() registration in main. ` +
    `Missing channels: ${missing.join(", ") || "none"}`,
  );
});

test("no known phantom channels remain in preload", () => {
  const preloadChannels = extractPreloadChannels(preload);

  const PHANTOM = [
    "desktop:import-files",
    "desktop:copy-file-between",
    "desktop:rename-file",
    "desktop:delete-file",
    "desktop:show-file-context-menu",
  ];

  for (const ch of PHANTOM) {
    assert.ok(
      !preloadChannels.has(ch),
      `Phantom channel "${ch}" must NOT appear in preload`,
    );
  }
});

test("four implemented file operations are present in both preload and main", () => {
  const mainChannels = extractMainChannels(main);
  const preloadChannels = extractPreloadChannels(preload);

  const IMPLEMENTED = [
    "desktop:get-file-metadata",
    "desktop:copy-file-path",
    "desktop:export-file",
    "desktop:reveal-in-finder",
  ];

  for (const ch of IMPLEMENTED) {
    assert.ok(
      mainChannels.has(ch),
      `Main must register handler for "${ch}"`,
    );
    assert.ok(
      preloadChannels.has(ch),
      `Preload must expose "${ch}"`,
    );
  }
});

test("DesktopApi optional methods are not exposed in preload", () => {
  const preloadChannels = extractPreloadChannels(preload);

  // These are optional (?.) methods in the DesktopApi type.  Preload
  // must NOT provide them — if it does, an ipcRenderer.invoke lands
  // on an unregistered channel and Electron throws at runtime.
  const OPTIONAL_BUT_UNEXPOSED = [
    "desktop:import-files",
    "desktop:copy-file-between",
    "desktop:rename-file",
    "desktop:delete-file",
    "desktop:show-file-context-menu",
  ];

  for (const ch of OPTIONAL_BUT_UNEXPOSED) {
    assert.ok(
      !preloadChannels.has(ch),
      `Optional (unimplemented) channel "${ch}" must not be exposed in preload`,
    );
  }
});
