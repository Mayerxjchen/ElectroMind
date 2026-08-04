import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync(new URL("../src/renderer/style.css", import.meta.url), "utf8");

test("local execution warning occupies a compact explicit grid row", () => {
    assert.match(
        css,
        /\.execution-risk-bar\s*\{[^}]*grid-area:\s*risk/s,
        "execution risk bar must use the risk grid area",
    );
    assert.match(
        css,
        /\.desktop-workbench\s*\{[^}]*grid-area:\s*workbench/s,
        "desktop workbench must use the workbench grid area",
    );
    assert.match(
        css,
        /\.desktop-shell\.macos\s*\{[^}]*grid-template-rows:\s*40px\s+auto\s+minmax\(0,\s*1fr\)/s,
        "macOS shell must reserve only an auto-sized row for the warning",
    );
});
