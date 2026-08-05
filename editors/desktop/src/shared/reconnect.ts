/** 指数退避重连调度（D3）—— wire 子进程崩溃/退出后的自动重连。
 *
 * 纯逻辑模块（不依赖 Electron），便于 node --test 直接验证。
 * 契约：
 * - ``schedule()``：记录一次失败并按退避序列安排重连；达到上限返回 false
 *   （调用方决定是否停止并等待手动重试）。
 * - ``onConnected()``：连接成功（收到首个有效事件）→ 重置计数与定时器。
 * - ``cancel()``：主动停止（app 退出 / 手动断开）。
 * - 退避序列：1s, 2s, 4s, 8s, 16s, 30s（封顶），最大 5 次自动尝试。
 * - 不无限循环：上限后停止，避免 wire 反复崩溃时空转。
 */

export const RECONNECT_BASE_DELAY_MS = 1000;
export const RECONNECT_MAX_DELAY_MS = 30_000;
export const RECONNECT_MAX_ATTEMPTS = 5;

export interface ReconnectScheduler {
  /** 安排一次重连；返回是否安排了（false = 已达上限或已取消）。 */
  schedule(): boolean;
  /** 连接成功 → 重置退避计数与定时器。 */
  onConnected(): void;
  /** 主动取消（app 退出 / 手动断开）。 */
  cancel(): void;
  /** 当前尝试次数（测试与诊断用）。 */
  attempts: number;
  /** 是否有挂起的重连定时器。 */
  pending(): boolean;
}

export function createReconnectScheduler(options?: {
  onReconnect: () => void;
  baseDelayMs?: number;
  maxDelayMs?: number;
  maxAttempts?: number;
  now?: () => number;
}): ReconnectScheduler {
  const onReconnect = options?.onReconnect ?? (() => {});
  const baseDelay = options?.baseDelayMs ?? RECONNECT_BASE_DELAY_MS;
  const maxDelay = options?.maxDelayMs ?? RECONNECT_MAX_DELAY_MS;
  const maxAttempts = options?.maxAttempts ?? RECONNECT_MAX_ATTEMPTS;

  let attempts = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function clearTimer(): void {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }

  return {
    get attempts() {
      return attempts;
    },
    pending() {
      return timer !== null;
    },
    schedule(): boolean {
      if (attempts >= maxAttempts) {
        return false;
      }
      attempts += 1;
      const delay = Math.min(baseDelay * 2 ** (attempts - 1), maxDelay);
      clearTimer();
      timer = setTimeout(() => {
        timer = null;
        onReconnect();
      }, delay);
      return true;
    },
    onConnected(): void {
      attempts = 0;
      clearTimer();
    },
    cancel(): void {
      attempts = 0;
      clearTimer();
    },
  };
}
