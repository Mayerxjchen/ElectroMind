// 宿主入口 —— 第 3 课：视图输入通过消息桥回传宿主。
//
// 这一层跑在 Node 环境（VS Code 的扩展宿主进程），能自由使用 vscode API。
// 后续课程会在 activate() 里逐步注册子进程桥、事件流渲染、命令等。

import * as vscode from "vscode";

import { ChatViewProvider } from "./host/panel";

async function openChatView(): Promise<void> {
  await vscode.commands.executeCommand("workbench.action.focusAuxiliaryBar");
  await vscode.commands.executeCommand("pagent.chat.focus");
}

/**
 * 插件激活入口。
 *
 * VS Code 在满足 package.json 的 activationEvents 时调用一次 activate。
 * 因为我们贡献了命令和视图，VS Code 会在命令被调用或视图被展开时自动激活本插件。
 *
 * @param context 扩展上下文。所有一次性注册（命令、视图、监听器、通道）都要 push 进
 *   context.subscriptions，VS Code 会在插件停用时统一 dispose，避免泄漏。
 */
export function activate(context: vscode.ExtensionContext): void {
  // createOutputChannel 在“输出”面板建一个名为 pagent 的通道，宿主日志打到这里。
  const output = vscode.window.createOutputChannel("pagent");

  // registerCommand 把命令 id（对应 package.json 的 contributes.commands）
  // 绑定到一个回调。返回的 Disposable 交给 subscriptions 托管。
  const hello = vscode.commands.registerCommand("pagent.hello", () => {
    // showInformationMessage 在右下角弹一条通知，用来确认插件确实激活并跑通。
    void vscode.window.showInformationMessage("pagent 插件已激活 —— 第 3 课");
  });

  // registerWebviewViewProvider 把视图 id 绑定到我们的 provider；VS Code 在用户
  // 展开该视图时回调 provider 填充内容。
  const chatProvider = new ChatViewProvider(context.extensionUri, output);
  const chatView = vscode.window.registerWebviewViewProvider(
    ChatViewProvider.viewId,
    chatProvider,
  );

  // 视图标题栏按钮（package.json 的 menus.view/title 贡献）：新会话 / 恢复会话。
  // 按钮显示在原生「PAGENT: CHAT」标题栏右侧，回调转交给 provider 处理。
  const reset = vscode.commands.registerCommand("pagent.chat.reset", () => {
    chatProvider.resetSession();
  });
  const resume = vscode.commands.registerCommand("pagent.chat.resume", () => {
    void chatProvider.resumeSession();
  });
  // 「在编辑器区打开」：侧栏无法设默认宽度或强制放右侧，用编辑器区 WebviewPanel
  // 开一个更宽、可由用户拖到右侧的聊天面板，与侧栏共用同一子进程。
  const openInEditor = vscode.commands.registerCommand(
    "pagent.chat.openInEditor",
    () => {
      chatProvider.openInEditor();
    },
  );
  const open = vscode.commands.registerCommand("pagent.chat.open", () => {
    void openChatView();
  });
  const setup = vscode.commands.registerCommand("pagent.setup", () => {
    void chatProvider.runSetup();
  });

  context.subscriptions.push(
    output,
    hello,
    chatView,
    reset,
    resume,
    openInEditor,
    open,
    setup,
    // chatProvider.dispose() 确保子进程和定时器在插件停用时被回收；
    // 不放入 subscriptions 则依赖 webview onDidDispose 触发，关窗口时可能不执行。
    new vscode.Disposable(() => chatProvider.dispose()),
  );
}

/**
 * 插件停用钩子。所有注册都交给了 subscriptions，VS Code 统一 dispose。
 */
export function deactivate(): void { }
