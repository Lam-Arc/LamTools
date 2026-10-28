/*
  user:"写一套高质量交互样式 …" — 这个文件只服务演示页：主题切换、滚动索引、进度演示、校验与计数。
  控件本身的行为在 controls.ts，样式在 kit.css。
*/

(() => {
  const $ = <T extends Element>(selector: string, root: ParentNode = document): T | null =>
    root.querySelector<T>(selector);

  const $$ = <T extends Element>(selector: string, root: ParentNode = document): T[] =>
    Array.from(root.querySelectorAll<T>(selector));

  const html = document.documentElement;
  const themeMeta = $<HTMLMetaElement>('meta[name="theme-color"]');

  /* ---------------- Theme ---------------- */

  const applyTheme = (theme: string, persist: boolean): void => {
    const next = theme === 'light' ? 'light' : 'dark';
    html.dataset.theme = next;

    if (themeMeta) {
      themeMeta.content = next === 'light' ? '#fdfbf7' : '#1b1d22';
    }

    if (persist) {
      try {
        localStorage.setItem('ui-kit-theme', next);
      } catch {
        /* local files can block storage; the switch still works for this session */
      }
    }
  };

  const themeControl = $<HTMLElement>('[data-theme-control]');
  const currentTheme = html.dataset.theme === 'light' ? 'light' : 'dark';
  applyTheme(currentTheme, false);

  themeControl?.addEventListener('segmentedchange', (event) => {
    const detail = (event as CustomEvent<{ value?: string }>).detail;
    applyTheme(detail?.value === 'light' ? 'light' : 'dark', true);
  });

  const themeItem = $$<HTMLButtonElement>('.segmented__item', themeControl ?? document).find(
    (item) => item.dataset.value === currentTheme,
  );
  if (themeItem && themeItem.getAttribute('aria-checked') !== 'true') {
    themeItem.click();
  }

  /* ---------------- Scroll index ---------------- */

  const railLinks = $$<HTMLAnchorElement>('.rail a[href^="#"]');
  const sections = railLinks
    .map((link) => document.getElementById(link.hash.slice(1)))
    .filter((section): section is HTMLElement => section !== null);

  let scrollTicking = false;

  const updateCurrentSection = (): void => {
    scrollTicking = false;
    if (!sections.length) return;

    const marker = window.innerHeight * 0.28;
    let current = sections[0];

    for (const section of sections) {
      if (section.getBoundingClientRect().top <= marker) current = section;
    }

    const atBottom =
      window.innerHeight + window.scrollY >=
      document.documentElement.scrollHeight - 2;
    if (atBottom) current = sections[sections.length - 1];

    railLinks.forEach((link) => {
      if (link.hash === `#${current.id}`) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  };

  const requestSectionUpdate = (): void => {
    if (scrollTicking) return;
    scrollTicking = true;
    requestAnimationFrame(updateCurrentSection);
  };

  window.addEventListener('scroll', requestSectionUpdate, { passive: true });
  window.addEventListener('resize', requestSectionUpdate);
  updateCurrentSection();

  /* ---------------- Progress demo ---------------- */

  const progress = $<HTMLElement>('[data-live-progress]');
  const progressValue = $<HTMLElement>('[data-live-progress-value]');
  const runProgress = $<HTMLButtonElement>('[data-run-progress]');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let progressFrame = 0;

  const setProgress = (value: number): void => {
    if (!progress) return;
    const percent = Math.max(0, Math.min(100, Math.round(value)));
    progress.style.setProperty('--value', String(percent));
    progress.setAttribute('aria-valuenow', String(percent));
    progress.setAttribute('aria-valuetext', `${percent}%`);
    if (progressValue) progressValue.textContent = `${percent}%`;
  };

  runProgress?.addEventListener('click', () => {
    if (!progress) return;
    cancelAnimationFrame(progressFrame);
    progress.dataset.running = 'true';

    if (reducedMotion.matches) {
      setProgress(100);
      progress.dataset.running = 'false';
      return;
    }

    const duration = 1800;
    const start = performance.now();
    setProgress(0);

    const tick = (now: number): void => {
      const elapsed = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - elapsed, 3);
      setProgress(eased * 100);

      if (elapsed < 1) {
        progressFrame = requestAnimationFrame(tick);
      } else {
        progress.dataset.running = 'false';
      }
    };

    progressFrame = requestAnimationFrame(tick);
  });

  /* ---------------- Slug validation ---------------- */

  $$<HTMLInputElement>('[data-slug-input]').forEach((input) => {
    const field = input.closest<HTMLElement>('.field');
    const error = field?.querySelector<HTMLElement>('[data-slug-error]') ?? null;
    const hint = field?.querySelector<HTMLElement>('.field__hint') ?? null;

    const validate = (): void => {
      const value = input.value.trim();
      const valid = value.length >= 2 && /^[a-z0-9-]+$/.test(value);

      input.setAttribute('aria-invalid', valid ? 'false' : 'true');
      field?.setAttribute('data-invalid', valid ? 'false' : 'true');
      if (error) error.hidden = valid;
      if (hint) hint.hidden = !valid;
    };

    input.addEventListener('input', validate);
    validate();
  });

  /* ---------------- Character count ---------------- */

  $$<HTMLTextAreaElement>('textarea[data-counter]').forEach((area) => {
    const target = $(`[data-counter-for="${area.id}"]`);
    const max = Number(area.getAttribute('maxlength') ?? 0);

    const update = (): void => {
      if (!(target instanceof HTMLElement)) return;
      target.textContent = max ? `${area.value.length} / ${max}` : String(area.value.length);
      target.dataset.near = max > 0 && area.value.length >= max * 0.9 ? 'true' : 'false';
    };

    area.addEventListener('input', update);
    update();
  });

  /* ---------------- Search shortcut ---------------- */

  const search = $<HTMLInputElement>('[data-search-demo]');

  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;

    const target = event.target as HTMLElement | null;
    if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
    if (target?.isContentEditable) return;
    if (!search) return;

    event.preventDefault();
    search.focus();
    search.select();
  });

  /* ---------------- Select log ---------------- */

  const loggedSelect = $<HTMLElement>('[data-log-select]');
  const selectLog = $<HTMLElement>('[data-select-log]');
  const loggedTrigger = loggedSelect?.querySelector<HTMLElement>('.select__trigger') ?? null;

  if (loggedTrigger && selectLog) {
    selectLog.textContent = loggedTrigger.dataset.value ?? '—';
  }

  loggedSelect?.addEventListener('selectchange', (event) => {
    const detail = (event as CustomEvent<{ value?: string }>).detail;
    if (selectLog) selectLog.textContent = detail?.value ?? '—';
  });

  /* ---------------- Segmented log ---------------- */

  const viewControl = $<HTMLElement>('[data-view-control]');
  const viewOutput = $<HTMLElement>('[data-view-output]');

  viewControl?.addEventListener('segmentedchange', (event) => {
    const detail = (event as CustomEvent<{ value?: string }>).detail;
    if (viewOutput) viewOutput.textContent = detail?.value ?? '—';
  });

  /* ---------------- Save notice ---------------- */

  const saveButton = $<HTMLButtonElement>('[data-save]');
  const saveNotice = $<HTMLElement>('[data-save-notice]');
  let noticeTimer = 0;

  saveButton?.addEventListener('click', () => {
    if (!saveNotice) return;
    window.clearTimeout(noticeTimer);
    saveNotice.dataset.visible = 'true';
    saveNotice.textContent = 'Saved just now';

    noticeTimer = window.setTimeout(() => {
      saveNotice.dataset.visible = 'false';
      saveNotice.textContent = '';
    }, 2600);
  });
})();
