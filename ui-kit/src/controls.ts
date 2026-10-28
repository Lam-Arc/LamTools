/*
  user:"写一套高质量交互样式 … ts 或 css … 不用看已有代码"
  需求：行为层只做必要的事——同步滑块填充与读数、可键盘操作的下拉框、会滑动的分段选择、切换按钮。
  样式与状态全部留在 CSS；脚本不负责“画”任何控件。
*/

(() => {
  type SelectOption = {
    el: HTMLElement;
    value: string;
    label: string;
    disabled: boolean;
  };

  const $ = <T extends Element>(selector: string, root: ParentNode = document): T | null =>
    root.querySelector<T>(selector);

  const $$ = <T extends Element>(selector: string, root: ParentNode = document): T[] =>
    Array.from(root.querySelectorAll<T>(selector));

  let optionUid = 0;
  let openSelect: SelectMenu | null = null;

  /* ---------------- Range ---------------- */

  const bindRanges = (root: ParentNode): void => {
    $$<HTMLInputElement>('input[type="range"].slider__input', root).forEach((input) => {
      if (input.dataset.kitRange === '1') return;
      input.dataset.kitRange = '1';

      const wrap = input.closest<HTMLElement>('.slider');
      const output = wrap?.querySelector<HTMLElement>('[data-range-output]') ?? null;
      const decimals = Number.parseInt(wrap?.dataset.decimals ?? '0', 10);
      const suffix = wrap?.dataset.suffix ?? '';

      const update = (): void => {
        const min = Number(input.min || 0);
        const max = Number(input.max || 100);
        const value = Number(input.value);
        const progress = max === min ? 0 : ((value - min) / (max - min)) * 100;
        const text = `${value.toFixed(Number.isFinite(decimals) ? decimals : 0)}${suffix}`;

        wrap?.style.setProperty('--fill', `${progress}%`);
        if (output) output.textContent = text;
        input.setAttribute('aria-valuetext', text);
      };

      input.addEventListener('input', update);
      input.addEventListener('change', update);
      update();
    });
  };

  /* ---------------- Toggle buttons ---------------- */

  const bindToggles = (root: ParentNode): void => {
    $$<HTMLButtonElement>('[data-toggle]', root).forEach((button) => {
      if (button.dataset.kitToggle === '1') return;
      button.dataset.kitToggle = '1';

      button.addEventListener('click', () => {
        const pressed = button.getAttribute('aria-pressed') !== 'true';
        button.setAttribute('aria-pressed', pressed ? 'true' : 'false');
        button.dispatchEvent(
          new CustomEvent('togglechange', { detail: { pressed }, bubbles: true }),
        );
      });
    });
  };

  /* ---------------- Indeterminate checkboxes ---------------- */

  const bindIndeterminate = (root: ParentNode): void => {
    $$<HTMLInputElement>('input[data-indeterminate]', root).forEach((input) => {
      if (input.dataset.kitIndeterminate === '1') return;
      input.dataset.kitIndeterminate = '1';
      input.indeterminate = true;
    });
  };

  /* ---------------- Select ---------------- */

  class SelectMenu {
    private readonly options: SelectOption[];
    private readonly valueEl: HTMLElement | null;
    private isOpen = false;
    private activeIndex = -1;
    private typeahead = '';
    private typeaheadTimer = 0;

    constructor(
      private readonly root: HTMLElement,
      private readonly trigger: HTMLButtonElement,
      private readonly popup: HTMLElement,
    ) {
      this.valueEl = $<HTMLElement>('[data-select-value]', root);

      this.options = $$<HTMLElement>('[role="option"]', popup).map((el) => {
        if (!el.id) el.id = `kit-option-${++optionUid}`;
        const labelEl = el.querySelector<HTMLElement>('.select__option-label');
        return {
          el,
          value: el.dataset.value ?? el.id,
          label: (labelEl?.textContent ?? el.textContent ?? '').trim(),
          disabled: el.getAttribute('aria-disabled') === 'true',
        };
      });

      const selected = this.options.find(
        (option) => option.el.getAttribute('aria-selected') === 'true',
      );
      if (selected) {
        this.trigger.dataset.value = selected.value;
        this.trigger.dataset.placeholder = 'false';
      }

      this.trigger.addEventListener('click', () => {
        if (this.isOpen) this.close(true);
        else this.open();
      });

      this.trigger.addEventListener('keydown', (event) => {
        if (this.isOpen) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          this.open(event.key === 'ArrowUp' ? -1 : 1);
        }
      });

      this.popup.addEventListener('keydown', this.onKeydown);
      this.popup.addEventListener('pointermove', this.onPointerMove);
      this.popup.addEventListener('click', this.onClick);
    }

    private open(direction: 1 | -1 = 1): void {
      if (this.isOpen) return;
      if (openSelect && openSelect !== this) openSelect.close(false);
      openSelect = this;
      this.isOpen = true;

      this.popup.hidden = false;
      this.popup.style.maxHeight = '';
      this.trigger.setAttribute('aria-expanded', 'true');

      const selectedIndex = this.options.findIndex(
        (option) =>
          option.el.getAttribute('aria-selected') === 'true' && !option.disabled,
      );
      const fallback = direction === -1 ? this.lastEnabled() : this.firstEnabled();
      const start = selectedIndex >= 0 ? selectedIndex : fallback;
      if (start >= 0) this.setActive(start, false);

      this.place();
      this.popup.focus({ preventScroll: true });
      if (start >= 0) this.setActive(start, true);

      document.addEventListener('pointerdown', this.onDocumentPointer, true);
      window.addEventListener('resize', this.onResize, { passive: true });
    }

    private close(returnFocus: boolean): void {
      if (!this.isOpen) return;
      this.isOpen = false;
      this.popup.hidden = true;
      this.popup.removeAttribute('aria-activedescendant');
      this.trigger.setAttribute('aria-expanded', 'false');
      delete this.root.dataset.side;
      document.removeEventListener('pointerdown', this.onDocumentPointer, true);
      window.removeEventListener('resize', this.onResize);
      if (openSelect === this) openSelect = null;
      if (returnFocus) this.trigger.focus({ preventScroll: true });
    }

    private place(): void {
      const rect = this.trigger.getBoundingClientRect();
      const desired = Math.min(this.popup.scrollHeight, 236);
      const below = window.innerHeight - rect.bottom - 12;
      const above = rect.top - 12;
      const side = desired > below && above > below ? 'top' : 'bottom';
      const available = side === 'top' ? above : below;

      this.root.dataset.side = side;
      if (desired > available) {
        this.popup.style.maxHeight = `${Math.min(desired, Math.max(64, available))}px`;
      }
    }

    private setActive(index: number, scroll = true): void {
      const option = this.options[index];
      if (!option) return;

      this.activeIndex = index;
      this.options.forEach((item, itemIndex) => {
        if (itemIndex === index) item.el.dataset.active = 'true';
        else delete item.el.dataset.active;
      });
      this.popup.setAttribute('aria-activedescendant', option.el.id);
      if (scroll) option.el.scrollIntoView({ block: 'nearest' });
    }

    private firstEnabled(): number {
      return this.options.findIndex((option) => !option.disabled);
    }

    private lastEnabled(): number {
      for (let index = this.options.length - 1; index >= 0; index -= 1) {
        if (!this.options[index].disabled) return index;
      }
      return -1;
    }

    private move(delta: number): void {
      const count = this.options.length;
      if (!count) return;

      let index = this.activeIndex;
      for (let step = 0; step < count; step += 1) {
        index = (index + delta + count) % count;
        if (!this.options[index].disabled) {
          this.setActive(index);
          return;
        }
      }
    }

    private edge(last: boolean): void {
      const index = last ? this.lastEnabled() : this.firstEnabled();
      if (index >= 0) this.setActive(index);
    }

    private findByPrefix(prefix: string): number {
      const count = this.options.length;
      const from = this.activeIndex >= 0 ? this.activeIndex : -1;

      for (let step = 1; step <= count; step += 1) {
        const index = (from + step + count) % count;
        const option = this.options[index];
        if (!option.disabled && option.label.toLowerCase().startsWith(prefix)) return index;
      }
      return -1;
    }

    private select(index: number): void {
      const option = this.options[index];
      if (!option || option.disabled) return;

      this.options.forEach((item, itemIndex) => {
        item.el.setAttribute('aria-selected', itemIndex === index ? 'true' : 'false');
      });
      if (this.valueEl) this.valueEl.textContent = option.label;
      this.trigger.dataset.placeholder = 'false';
      this.trigger.dataset.value = option.value;

      this.close(true);
      this.root.dispatchEvent(
        new CustomEvent('selectchange', {
          detail: { value: option.value, label: option.label, index },
          bubbles: true,
        }),
      );
    }

    private onKeydown = (event: KeyboardEvent): void => {
      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault();
          this.move(1);
          return;
        case 'ArrowUp':
          event.preventDefault();
          this.move(-1);
          return;
        case 'Home':
          event.preventDefault();
          this.edge(false);
          return;
        case 'End':
          event.preventDefault();
          this.edge(true);
          return;
        case 'Enter':
        case ' ':
          event.preventDefault();
          this.select(this.activeIndex);
          return;
        case 'Escape':
          event.preventDefault();
          this.close(true);
          return;
        case 'Tab':
          this.close(true);
          return;
        default:
          break;
      }

      if (
        event.key.length === 1 &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey
      ) {
        this.typeahead += event.key.toLowerCase();
        window.clearTimeout(this.typeaheadTimer);
        this.typeaheadTimer = window.setTimeout(() => {
          this.typeahead = '';
        }, 500);

        const match = this.findByPrefix(this.typeahead);
        if (match >= 0) this.setActive(match);
      }
    };

    private onPointerMove = (event: PointerEvent): void => {
      const target = (event.target as HTMLElement | null)?.closest<HTMLElement>(
        '[role="option"]',
      );
      if (!target) return;

      const index = this.options.findIndex(
        (option) => option.el === target && !option.disabled,
      );
      if (index >= 0 && index !== this.activeIndex) this.setActive(index, false);
    };

    private onClick = (event: MouseEvent): void => {
      const target = (event.target as HTMLElement | null)?.closest<HTMLElement>(
        '[role="option"]',
      );
      if (!target) return;

      const index = this.options.findIndex((option) => option.el === target);
      if (index >= 0) this.select(index);
    };

    private onDocumentPointer = (event: PointerEvent): void => {
      if (!this.root.contains(event.target as Node)) this.close(false);
    };

    private onResize = (): void => {
      if (this.isOpen) this.place();
    };
  }

  const setupSelect = (root: HTMLElement): void => {
    if (root.dataset.kitSelect === '1') return;

    const trigger = $<HTMLButtonElement>('.select__trigger', root);
    const popup = $<HTMLElement>('.select__popup', root);
    if (!trigger || !popup) return;

    root.dataset.kitSelect = '1';
    new SelectMenu(root, trigger, popup);
  };

  /* ---------------- Segmented control ---------------- */

  class Segmented {
    private readonly items: HTMLButtonElement[];
    private readonly indicator: HTMLElement | null;
    private observer: ResizeObserver | null = null;

    constructor(private readonly root: HTMLElement) {
      this.items = $$<HTMLButtonElement>('[role="radio"]', root);
      this.indicator = $<HTMLElement>('.segmented__indicator', root);

      this.items.forEach((item, index) => {
        if (!item.hasAttribute('aria-checked')) {
          item.setAttribute('aria-checked', index === 0 ? 'true' : 'false');
        }
        item.tabIndex = item.getAttribute('aria-checked') === 'true' ? 0 : -1;

        item.addEventListener('click', () => this.select(index, false));
        item.addEventListener('keydown', (event) => this.onKeydown(event, index));
      });

      this.layout();
      requestAnimationFrame(() => {
        this.layout();
        this.root.dataset.ready = 'true';
      });

      if ('ResizeObserver' in window) {
        this.observer = new ResizeObserver(() => this.layout());
        this.observer.observe(root);
      }

      document.fonts.ready.then(() => this.layout());
    }

    private layout(): void {
      if (!this.indicator) return;

      const checked = this.items.find(
        (item) => item.getAttribute('aria-checked') === 'true',
      );
      if (!checked) return;

      const rootRect = this.root.getBoundingClientRect();
      const itemRect = checked.getBoundingClientRect();
      if (!itemRect.width) return;

      const left = itemRect.left - rootRect.left - this.root.clientLeft;
      this.indicator.style.width = `${itemRect.width}px`;
      this.indicator.style.transform = `translateX(${left}px)`;
    }

    private select(index: number, focus: boolean): void {
      const item = this.items[index];
      if (!item) return;

      if (item.getAttribute('aria-checked') === 'true') {
        if (focus) item.focus();
        return;
      }

      this.items.forEach((candidate, candidateIndex) => {
        const checked = candidateIndex === index;
        candidate.setAttribute('aria-checked', checked ? 'true' : 'false');
        candidate.tabIndex = checked ? 0 : -1;
      });

      this.layout();
      if (focus) item.focus();

      this.root.dispatchEvent(
        new CustomEvent('segmentedchange', {
          detail: { value: item.dataset.value ?? String(index), index },
          bubbles: true,
        }),
      );
    }

    private onKeydown(event: KeyboardEvent, index: number): void {
      const last = this.items.length - 1;
      let next = index;

      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
        next = index === last ? 0 : index + 1;
      } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
        next = index === 0 ? last : index - 1;
      } else if (event.key === 'Home') {
        next = 0;
      } else if (event.key === 'End') {
        next = last;
      } else {
        return;
      }

      event.preventDefault();
      this.select(next, true);
    }
  }

  const setupSegmented = (root: HTMLElement): void => {
    if (root.dataset.kitSegmented === '1') return;
    root.dataset.kitSegmented = '1';
    new Segmented(root);
  };

  /* ---------------- Init ---------------- */

  const init = (root: ParentNode = document): void => {
    bindRanges(root);
    bindToggles(root);
    bindIndeterminate(root);
    $$<HTMLElement>('.select[data-select]', root).forEach(setupSelect);
    $$<HTMLElement>('.segmented[data-segmented]', root).forEach(setupSegmented);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init());
  } else {
    init();
  }

  (window as unknown as { Controls?: { init: (root?: ParentNode) => void } }).Controls = {
    init,
  };
})();
