/** Virtual scrolling list for long message threads.
 *
 * Only renders items visible in the viewport + a small buffer above
 * and below.  Item heights are estimated and refined on first render
 * via ResizeObserver.
 *
 * Usage::
 *
 *   const list = new VirtualList(container, {
 *     itemCount: 500,
 *     renderItem: (i, el) => { el.textContent = messages[i]; },
 *     estimateHeight: () => 80,
 *   });
 *   list.setCount(newCount);
 */

interface VirtualListOptions {
  /** Total number of items. */
  itemCount: number;
  /** Populate *el* with the content for item at index *i*. */
  renderItem: (index: number, el: HTMLElement) => void;
  /** Estimated item height in px (used before measurement). */
  estimateHeight: (index: number) => number;
  /** Overscan count (items rendered beyond viewport). Default 3. */
  overscan?: number;
}

export class VirtualList {
  private container: HTMLElement;
  private inner: HTMLElement;
  private options: VirtualListOptions;
  private heights = new Map<number, number>();
  private itemElements = new Map<number, HTMLElement>();
  private itemPool: HTMLElement[] = [];
  private visibleRange: [number, number] = [0, 0];
  private resizeObserver: ResizeObserver | null = null;

  constructor(container: HTMLElement, options: VirtualListOptions) {
    this.container = container;
    this.options = { overscan: 3, ...options };

    // Create inner spacer
    this.inner = document.createElement("div");
    this.inner.className = "virtual-list-inner";
    this.inner.style.position = "relative";
    this.container.appendChild(this.inner);

    // Listen for scroll
    this.container.addEventListener("scroll", () => this.renderVisible(), {
      passive: true,
    });

    this.recomputeTotalHeight();
    this.renderVisible();
  }

  /** Update item count (e.g., when new messages arrive). */
  setCount(count: number): void {
    this.options.itemCount = count;
    this.recomputeTotalHeight();
    this.renderVisible();
  }

  /** Re-render after external changes. */
  refresh(): void {
    this.heights.clear();
    this.recomputeTotalHeight();
    this.renderVisible();
  }

  /** Scroll to the bottom (latest message). */
  scrollToBottom(): void {
    this.container.scrollTop = this.container.scrollHeight;
  }

  destroy(): void {
    this.resizeObserver?.disconnect();
    this.inner.innerHTML = "";
    this.itemElements.clear();
    this.itemPool = [];
  }

  // ── Internals ──────────────────────────────────────────────────────

  private recomputeTotalHeight(): void {
    let h = 0;
    for (let i = 0; i < this.options.itemCount; i++) {
      h += this.heights.get(i) ?? this.options.estimateHeight(i);
    }
    this.inner.style.height = `${h}px`;
  }

  private getOffset(index: number): number {
    let offset = 0;
    for (let i = 0; i < index; i++) {
      offset += this.heights.get(i) ?? this.options.estimateHeight(i);
    }
    return offset;
  }

  private renderVisible(): void {
    const { scrollTop, clientHeight } = this.container;
    const overscan = this.options.overscan ?? 3;

    // Find first visible item (binary search by accumulated offsets)
    let start = 0;
    let offset = 0;
    for (let i = 0; i < this.options.itemCount; i++) {
      const h = this.heights.get(i) ?? this.options.estimateHeight(i);
      if (offset + h > scrollTop) {
        start = i;
        break;
      }
      offset += h;
    }

    // Find last visible item
    let end = start;
    let y = offset;
    while (end < this.options.itemCount && y < scrollTop + clientHeight) {
      y += this.heights.get(end) ?? this.options.estimateHeight(end);
      end++;
    }

    // Apply overscan
    start = Math.max(0, start - overscan);
    end = Math.min(this.options.itemCount, end + overscan);

    // Skip if range unchanged
    if (start === this.visibleRange[0] && end === this.visibleRange[1]) return;
    this.visibleRange = [start, end];

    // Recycle items outside range
    for (const [idx, el] of this.itemElements) {
      if (idx < start || idx >= end) {
        this.recycle(el);
        this.itemElements.delete(idx);
      }
    }

    // Render items in range
    let currentOffset = this.getOffset(start);
    for (let i = start; i < end; i++) {
      if (this.itemElements.has(i)) continue;
      const el = this.acquire();
      this.options.renderItem(i, el);
      const h = this.heights.get(i) ?? this.options.estimateHeight(i);
      el.style.position = "absolute";
      el.style.top = `${currentOffset}px`;
      el.style.left = "0";
      el.style.right = "0";
      this.inner.appendChild(el);
      this.itemElements.set(i, el);
      currentOffset += h;
    }
  }

  private acquire(): HTMLElement {
    if (this.itemPool.length > 0) {
      return this.itemPool.pop()!;
    }
    const el = document.createElement("div");
    el.className = "virtual-list-item";
    // Observe height changes
    if (!this.resizeObserver) {
      this.resizeObserver = new ResizeObserver((entries) => {
        let changed = false;
        for (const entry of entries) {
          const el = entry.target as HTMLElement;
          const idx = Number(el.dataset.virtualIndex);
          if (isNaN(idx)) continue;
          const newH = entry.contentRect.height;
          const oldH = this.heights.get(idx);
          if (oldH !== newH) {
            this.heights.set(idx, newH);
            changed = true;
          }
        }
        if (changed) {
          this.recomputeTotalHeight();
          this.renderVisible();
        }
      });
    }
    this.resizeObserver.observe(el);
    return el;
  }

  private recycle(el: HTMLElement): void {
    this.resizeObserver?.unobserve(el);
    el.remove();
    this.itemPool.push(el);
  }
}
