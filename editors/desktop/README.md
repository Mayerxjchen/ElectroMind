# pagent Desktop

Electron 桌面端初始化骨架，当前目标是先把桌面壳搭起来，再逐步复用 `editors/vscode` 里的协议和聊天 UI。

## 当前包含

- Electron 主进程入口
- `preload` 桥接层
- 一个可运行的渲染层页面
- 工作区目录选择示例
- `esbuild` 构建脚本

## 本地运行

```bash
npm install
npm run start
```

## 下一步建议

1. 抽公共协议到共享目录
2. 迁移聊天渲染层
3. 接入 pagent 子进程与 Wire 事件流
4. 做会话恢复与运行模式切换
