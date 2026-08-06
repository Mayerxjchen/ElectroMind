/** 危险操作二次确认 —— 经事件桥走 vanilla confirm 模态。
 *
 *  main.ts 监听 electromind:confirm-request，完成后回发
 *  electromind:confirm-resolved{requestId, ok}。
 */

let confirmSeq = 0;

export function requestConfirm(opts: {
  title: string;
  message: string;
  confirmText: string;
  cancelText?: string;
}): Promise<boolean> {
  const requestId = `confirm-${++confirmSeq}`;
  return new Promise<boolean>((resolve) => {
    const onResolved = (e: Event) => {
      const d = (e as CustomEvent).detail as {
        requestId?: string;
        ok?: boolean;
      };
      if (d.requestId !== requestId) return;
      window.removeEventListener("electromind:confirm-resolved", onResolved);
      resolve(Boolean(d.ok));
    };
    window.addEventListener("electromind:confirm-resolved", onResolved);
    window.dispatchEvent(
      new CustomEvent("electromind:confirm-request", {
        detail: {
          requestId,
          title: opts.title,
          message: opts.message,
          confirmText: opts.confirmText,
          cancelText: opts.cancelText,
        },
      }),
    );
  });
}
