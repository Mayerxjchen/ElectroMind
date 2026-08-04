/** FileApi unsupported-operation semantics test.
 *
 *  When an optional desktop file operation is absent, FileApi must
 *  produce an explicit observable failure — either a thrown Error with
 *  a stable code (renameFile, deleteFile) or a result object with an
 *  error/reason field (importFiles, copyFileBetween, previewFile).
 *
 *  Compiles the pure TypeScript module via esbuild and imports it into
 *  the Node test runner so assertions test actual executable logic, not
 *  regex matches against source text.
 */

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const esbuild = require("esbuild");

// ---------------------------------------------------------------------------
// Compile helper
// ---------------------------------------------------------------------------

const MODULE_PATH = join(
  import.meta.dirname,
  "..",
  "src",
  "renderer",
  "store",
  "FileApi.ts",
);

let _module = null;

async function getModule() {
  if (_module) return _module;

  const tmpDir = mkdtempSync(join(tmpdir(), "fileapi-test-"));
  const outFile = join(tmpDir, "fileapi.mjs");

  try {
    await esbuild.build({
      entryPoints: [MODULE_PATH],
      bundle: true,
      outfile: outFile,
      platform: "node",
      format: "esm",
      target: "node20",
      logLevel: "silent",
      absWorkingDir: join(import.meta.dirname, ".."),
      // FileApi accesses `window.desktop.*` — rewrite to globalThis so
      // the mock set on globalThis.window is reachable from ESM scope.
      define: { window: "globalThis.window" },
    });
  } catch (err) {
    rmSync(tmpDir, { recursive: true, force: true });
    throw err;
  }

  try {
    _module = await import(outFile);
  } finally {
    // Clean up temp dir — the module is now loaded in the registry.
    rmSync(tmpDir, { recursive: true, force: true });
  }

  return _module;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeRef(overrides = {}) {
  return {
    id: "test-1",
    source: "project",
    path: "/tmp/test.txt",
    name: "test.txt",
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
    ...overrides,
  };
}

/** Install an empty window.desktop — no optional methods are present. */
function mockEmptyDesktop() {
  globalThis.window = { desktop: {} };
}

// ---------------------------------------------------------------------------
// UnsupportedOperationError structure
// ---------------------------------------------------------------------------

test("UnsupportedOperationError has stable code and meaningful message", async () => {
  const { UnsupportedOperationError } = await getModule();

  const err = new UnsupportedOperationError("renameFile");

  assert.ok(err instanceof Error, "must be an Error instance");
  assert.ok(
    err instanceof UnsupportedOperationError,
    "must be an UnsupportedOperationError instance",
  );
  assert.strictEqual(err.name, "UnsupportedOperationError");
  assert.strictEqual(err.code, "UNSUPPORTED_OPERATION");
  assert.match(err.message, /renameFile/);
  assert.match(err.message, /not yet supported/);
});

// ---------------------------------------------------------------------------
// renameFile — must throw when capability is absent
// ---------------------------------------------------------------------------

test("renameFile throws UnsupportedOperationError when desktop.renameFile is absent", async () => {
  const { renameFile, UnsupportedOperationError } = await getModule();

  mockEmptyDesktop();
  const ref = makeRef();

  await assert.rejects(
    () => renameFile(ref, "new-name.txt"),
    (err) => {
      assert.ok(err instanceof UnsupportedOperationError);
      assert.strictEqual(err.code, "UNSUPPORTED_OPERATION");
      assert.match(err.message, /renameFile/);
      return true;
    },
    "renameFile must throw UnsupportedOperationError when capability is absent",
  );
});

test("renameFile throws (not returns original ref) when unsupported", async () => {
  const { renameFile } = await getModule();

  mockEmptyDesktop();
  const ref = makeRef();

  // Must NOT silently return the original ref.
  let threw = false;
  try {
    const result = await renameFile(ref, "new-name.txt");
    // If we get here, the function returned — which is wrong.
    threw = false;
  } catch (err) {
    threw = true;
    // The result must NOT equal the original ref (since it threw).
    assert.notDeepStrictEqual(err, ref, "error object must not be the original ref");
  }

  assert.ok(threw, "renameFile must throw, not return silently");
});

// ---------------------------------------------------------------------------
// deleteFile — must throw when capability is absent
// ---------------------------------------------------------------------------

test("deleteFile throws UnsupportedOperationError when desktop.deleteFile is absent", async () => {
  const { deleteFile, UnsupportedOperationError } = await getModule();

  mockEmptyDesktop();
  const ref = makeRef();

  await assert.rejects(
    () => deleteFile(ref),
    (err) => {
      assert.ok(err instanceof UnsupportedOperationError);
      assert.strictEqual(err.code, "UNSUPPORTED_OPERATION");
      assert.match(err.message, /deleteFile/);
      return true;
    },
    "deleteFile must throw UnsupportedOperationError when capability is absent",
  );
});

test("deleteFile throws (not silent no-op) when unsupported", async () => {
  const { deleteFile } = await getModule();

  mockEmptyDesktop();
  const ref = makeRef();

  let threw = false;
  try {
    await deleteFile(ref);
    // If we get here, it resolved silently — wrong.
  } catch (_err) {
    threw = true;
  }

  assert.ok(threw, "deleteFile must throw, not silently resolve");
});

// ---------------------------------------------------------------------------
// Already-working operations — explicit error result, not throw
// ---------------------------------------------------------------------------

test("importFiles returns explicit error result when capability absent", async () => {
  const { importFiles } = await getModule();

  mockEmptyDesktop();
  const target = makeRef({ path: "/dst" });

  const results = await importFiles(target, ["/tmp/a.txt", "/tmp/b.txt"]);

  assert.strictEqual(results.length, 2);
  for (const r of results) {
    assert.strictEqual(r.ok, false, "each import result must be ok: false");
    assert.ok(typeof r.error === "string" && r.error.length > 0, "error message must exist");
  }
});

test("copyFileBetween returns explicit error result when capability absent", async () => {
  const { copyFileBetween } = await getModule();

  mockEmptyDesktop();
  const src = makeRef({ id: "src-1" });
  const dst = makeRef({ id: "dst-1", path: "/tmp/dst.txt" });

  const result = await copyFileBetween(src, dst);

  assert.strictEqual(result.ok, false);
  assert.ok(typeof result.error === "string" && result.error.length > 0);
});

test("previewFile returns explicit reason when capability absent", async () => {
  const { previewFile } = await getModule();

  mockEmptyDesktop();
  const ref = makeRef({ size: 1024 });

  const result = await previewFile(ref);

  assert.strictEqual(result.kind, "binary");
  assert.ok(typeof result.reason === "string" && result.reason.length > 0);
  // Must retain the original file metadata.
  assert.strictEqual(result.name, ref.name);
  assert.strictEqual(result.path, ref.path);
});
