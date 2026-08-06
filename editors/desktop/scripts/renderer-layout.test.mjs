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

// P0「单一 Shell 布局所有者」：Composer 进入主列正常文档流，删除浮层定位；
// OverlayLayer 提供浮层宿主。这些规则是布局稳定性的硬约束 —— 回归即失败。

test("composer dock is in normal document flow, never a floating overlay", () => {
    const block = css.match(/\.composer-dock\s*\{([^}]*)\}/s)?.[1] ?? "";
    assert.match(block, /position:\s*static/, "composer dock must be position:static");
    assert.doesNotMatch(
        block,
        /position:\s*(fixed|absolute)/,
        "composer dock must not use fixed/absolute positioning",
    );
    // 浮层定位的配套 hack（为浮层预留底部空隙）也必须消失
    assert.doesNotMatch(
        css,
        /\.pane-center>\.chat-log\s*\{[^}]*padding:[^}]*120px/s,
        "chat-log must not reserve 120px bottom padding for a floating composer",
    );
});

test("overlay layer hosts fixed overlays without participating in the shell grid", () => {
    const block = css.match(/\.desktop-overlay-layer\s*\{([^}]*)\}/s)?.[1] ?? "";
    assert.match(block, /position:\s*absolute/, "overlay layer covers the viewport");
    assert.match(block, /pointer-events:\s*none/, "empty overlay layer must not block clicks");
    assert.match(
        css,
        /\.desktop-overlay-layer>\.desktop-modal[^{]*\{[^}]*pointer-events:\s*auto/s,
        "modals inside the overlay layer must receive clicks",
    );
});
