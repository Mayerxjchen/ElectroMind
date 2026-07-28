# ElectroMind Web UI 图标优化设计

## 目标

基于用户提供的像素风 ElectroMind 猫咪 Logo，制作适合 Web UI 的透明背景图标，同时保留一份透明背景的完整品牌 Logo。小尺寸界面使用猫咪主体，完整字标用于后续欢迎页、README 或 About 页面。

## 输入与视觉不变量

编辑目标为用户提供的 ElectroMind 猫咪图片。处理时必须保留：

- 白色与深灰双色猫咪；
- 蓝色眼睛、蓝色项圈和闪电吊牌；
- 深蓝色像素描边与原有像素画风；
- 完整 Logo 中的 `ElectroMind` 字样、大小写和深蓝/亮蓝配色。

不得新增阴影、渐变背景、描边光晕、水印或其他图形元素。

## 输出资产

### Web UI 图标

- 文件：`editors/desktop/assets/logo-icon.png`
- 内容：仅保留猫咪主体，不包含 `ElectroMind` 字样。
- 画布：正方形透明 PNG。
- 构图：猫咪居中，主体完整，四周保留约 10% 透明安全边距。
- 用途：由现有构建脚本复制到 `dist/logo-icon.png`，供 Web UI favicon 使用。

生成时先保存为新的候选文件，完成视觉与透明度验证后再替换现有 `logo-icon.png`。不修改现有 `app-icon.png`、`.icns`、`.ico` 和 `icon.iconset`，避免把 Web UI favicon 优化扩大为桌面安装包图标重制。

### 完整透明 Logo

- 文件：`editors/desktop/assets/electromind-logo.png`
- 内容：保留猫咪主体与 `ElectroMind` 字样。
- 画布：紧凑横向透明 PNG，四周保留适量透明边距。
- 用途：作为欢迎页、README 或 About 页的品牌资产；本次不新增 UI 引用。

## 处理流程

1. 使用 imagegen 编辑输入图片，将主体放到可干净移除的纯色键控背景上。
2. 使用 imagegen 技能提供的本地脚本将键控色转换为 alpha 通道。
3. 检查猫咪白色区域未被误删、深蓝像素描边完整、边缘无键控色残留。
4. 为方形图标裁切猫咪主体并保留安全边距。
5. 将验证通过的方形资产写入现有 Web UI 图标路径。
6. 运行 Desktop 构建，确认图标被复制到 `dist/` 且 HTML 引用仍有效。

## 验收标准

- 两个最终 PNG 均包含有效 alpha 通道。
- 四角完全透明，白色背景不再可见。
- 猫咪主体没有被裁断，白色毛发区域保持不透明。
- 方形图标在 16、32、64 和 128 像素预览下仍能辨认。
- 完整 Logo 的文字准确，无缺字、变形或颜色漂移。
- `npm run compile` 成功，`dist/logo-icon.png` 与源 Web UI 图标一致。

## 非目标

- 不重新设计猫咪、字标或品牌配色。
- 不修改 Desktop 主进程图标、安装包图标或 VS Code 扩展图标。
- 不改动 Web UI 布局和业务代码。
