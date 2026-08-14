import { afterEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import {
  WORKSPACE_SLOT_NAMES,
  type MemberSlotSet,
  type WorkspaceSlotName,
} from '../src/types';
import {
  getSlotFallback,
  hasSlot,
  validateMemberSlotSet,
} from '../src/helpers/slotValidation';
import WorkspaceShell from '../src/components/WorkspaceShell.vue';
import SessionSidebar from '../src/components/SessionSidebar.vue';
import CoreExecutionControls from '../src/components/CoreExecutionControls.vue';

const defaultViewportWidth = window.innerWidth;

afterEach(() => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: defaultViewportWidth });
  window.dispatchEvent(new Event('resize'));
});

function mountShell(options: Parameters<typeof mount>[1] = {}) {
  return mount(WorkspaceShell, {
    attachTo: options.attachTo,
    props: {
      productName: 'LamTools',
      ...(options.props || {}),
    },
    slots: options.slots,
  });
}

describe('slot declaration validation', () => {
  it('accepts current workspace slot names', () => {
    const slotSet: MemberSlotSet = {
      memberId: 'writer',
      declaredSlots: ['sidebar-body', 'main-content', 'composer-textarea'],
    };

    const result = validateMemberSlotSet(slotSet);

    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('rejects unknown slot names', () => {
    const slotSet: MemberSlotSet = {
      memberId: 'writer',
      declaredSlots: ['sidebar-body', 'invalid-slot' as WorkspaceSlotName],
    };

    const result = validateMemberSlotSet(slotSet);

    expect(result.valid).toBe(false);
    expect(result.errors.some((error) => error.includes('invalid-slot'))).toBe(true);
  });

  it('keeps WORKSPACE_SLOT_NAMES aligned with the validator', () => {
    const result = validateMemberSlotSet({
      memberId: 'all-slots',
      declaredSlots: [...WORKSPACE_SLOT_NAMES],
    });

    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('warns when recommended slots are missing', () => {
    const result = validateMemberSlotSet({
      memberId: 'minimal',
      declaredSlots: ['sidebar-header'],
    });

    expect(result.valid).toBe(true);
    expect(result.warnings).toHaveLength(3);
    expect(result.warnings.some((warning) => warning.includes('sidebar-body'))).toBe(true);
    expect(result.warnings.some((warning) => warning.includes('main-content'))).toBe(true);
    expect(result.warnings.some((warning) => warning.includes('composer-textarea'))).toBe(true);
  });

  it('validates fallback slot keys', () => {
    const fallbacks: Partial<Record<WorkspaceSlotName, string>> = {};
    (fallbacks as Record<string, string>)['not-a-slot'] = 'Fallback';

    const result = validateMemberSlotSet({
      memberId: 'writer',
      declaredSlots: ['sidebar-body'],
      fallbacks,
    });

    expect(result.valid).toBe(false);
    expect(result.errors.some((error) => error.includes('not-a-slot'))).toBe(true);
  });
});

describe('slot helpers', () => {
  const slotSet: MemberSlotSet = {
    memberId: 'writer',
    declaredSlots: ['sidebar-body', 'main-content'],
    fallbacks: {
      'sidebar-body': 'DefaultSidebar',
      'main-content': 'DefaultMain',
    },
  };

  it('returns configured fallbacks', () => {
    expect(getSlotFallback(slotSet, 'sidebar-body')).toBe('DefaultSidebar');
    expect(getSlotFallback(slotSet, 'main-content')).toBe('DefaultMain');
    expect(getSlotFallback(slotSet, 'right-panel')).toBeNull();
  });

  it('checks declared slots', () => {
    expect(hasSlot(slotSet, 'sidebar-body')).toBe(true);
    expect(hasSlot(slotSet, 'main-content')).toBe(true);
    expect(hasSlot(slotSet, 'right-panel')).toBe(false);
  });
});

describe('WorkspaceShell rendering', () => {
  it('renders the current shell frame with required product name', () => {
    const wrapper = mountShell();

    expect(wrapper.find('.workspace-shell').exists()).toBe(true);
    expect(wrapper.find('.drawer-left').exists()).toBe(true);
    expect(wrapper.find('.workspace-main').exists()).toBe(true);
    expect(wrapper.find('.floating-composer').exists()).toBe(true);
    expect(wrapper.find('.drawer-right').exists()).toBe(true);
    expect(wrapper.text()).toContain('LamTools');
  });

  it('can hide the right panel', () => {
    const wrapper = mountShell({
      props: {
        showRightPanel: false,
      },
    });

    expect(wrapper.find('.drawer-right').exists()).toBe(false);
    expect(wrapper.find('.edge-right').exists()).toBe(false);
  });

  it('provides a touch-friendly control that toggles the right panel', async () => {
    const wrapper = mountShell();
    const trigger = wrapper.get('[data-mobile-right-toggle]');

    expect(trigger.element.tagName).toBe('BUTTON');
    expect(trigger.attributes('aria-controls')).toBeDefined();
    expect(trigger.attributes('aria-expanded')).toBe('false');

    await trigger.trigger('click');
    expect(wrapper.get('.drawer-right').classes()).toContain('open');
    expect(trigger.attributes('aria-expanded')).toBe('true');

    await trigger.trigger('click');
    expect(wrapper.get('.drawer-right').classes()).not.toContain('open');
    expect(wrapper.get('.drawer-right').attributes('inert')).toBeDefined();
  });

  it('isolates focus behind the right panel on compact viewports', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
    // setup.ts mocks matchMedia with matches: false; make the narrow-viewport
    // query follow innerWidth so the shell enters compact mode
    window.matchMedia = (query: string): MediaQueryList => ({
      matches: query.includes('max-width') && window.innerWidth <= 640,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    });
    const wrapper = mountShell({ attachTo: document.body });
    const trigger = wrapper.get('[data-mobile-right-toggle]');

    await trigger.trigger('click');
    await nextTick();

    const drawer = wrapper.get('.drawer-right');
    expect(drawer.classes()).toContain('open');
    // The drawer never steals focus; jsdom does not focus buttons on click
    expect(document.activeElement).not.toBe(drawer.element);
    expect(wrapper.get('.drawer-left').attributes('inert')).toBeDefined();
    expect(wrapper.get('.workspace-main').attributes('inert')).toBeDefined();
    expect(wrapper.get('.composer-root').attributes('inert')).toBeDefined();

    (trigger.element as HTMLElement).focus();
    await trigger.trigger('click');
    await nextTick();
    expect(drawer.classes()).not.toContain('open');
    expect(drawer.attributes('inert')).toBeDefined();
    expect(document.activeElement).toBe(trigger.element);

    await trigger.trigger('click');
    await nextTick();
    await wrapper.trigger('keydown', { key: 'Escape' });
    await nextTick();
    expect(drawer.classes()).not.toContain('open');
    expect(document.activeElement).toBe(trigger.element);
    wrapper.unmount();
  });

  it('renders named content slots', () => {
    const wrapper = mountShell({
      slots: {
        'sidebar-body': '<div class="test-sidebar">Projects</div>',
        'main-content': '<main class="test-main">Thread</main>',
        'composer-textarea': '<textarea class="test-composer"></textarea>',
        'right-panel': '<aside class="test-review">Review</aside>',
      },
    });

    expect(wrapper.find('.test-sidebar').text()).toBe('Projects');
    expect(wrapper.find('.test-main').text()).toBe('Thread');
    expect(wrapper.find('.test-composer').exists()).toBe(true);
    expect(wrapper.find('.test-review').text()).toBe('Review');
  });

  it('emits shell actions', async () => {
    const wrapper = mountShell();

    await wrapper.find('.drawer-head .icon-btn').trigger('click');
    await wrapper.find('.settings-entry').trigger('click');
    await wrapper.find('.floating-composer').trigger('submit');

    expect(wrapper.emitted('new-session')).toHaveLength(1);
    expect(wrapper.emitted('settings')).toHaveLength(1);
    expect(wrapper.emitted('composer-submit')).toHaveLength(1);
  });

  it('renders default composer action as stop while running', () => {
    const wrapper = mountShell({
      props: {
        composerActionMode: 'stop',
      },
    });

    const button = wrapper.find('.floating-composer .send');
    expect(button.text()).toBe('stop');
    expect(button.classes()).toContain('send--stop');
    expect(button.attributes('aria-label')).toBe('停止运行');
  });
});

describe('CoreExecutionControls', () => {
  it('emits model, thinking, and shallow changes from the shared composer controls', async () => {
    const wrapper = mount(CoreExecutionControls, {
      props: {
        modelValue: '',
        thinkingMode: 'medium',
        shallowThinkingEnabled: false,
        modelOptions: [
          { value: '', label: 'Default' },
          { value: 'model-1', label: 'Model 1' },
        ],
        thinkingModeOptions: [
          { value: 'medium', label: 'Medium' },
          { value: 'max', label: 'Max' },
        ],
      },
    });

    const triggers = wrapper.findAll('.ui-select-trigger');
    await triggers[0].trigger('click');
    await wrapper.findAll('.ui-select-option')[1].trigger('click');
    await triggers[1].trigger('click');
    await wrapper.findAll('.ui-select-option')[1].trigger('click');
    await triggers[1].trigger('click');
    await wrapper.findAll('.ui-select-option').at(-1)!.trigger('click');

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['model-1']);
    expect(wrapper.emitted('update:thinkingMode')?.[0]).toEqual(['max']);
    expect(wrapper.emitted('update:shallowThinkingEnabled')?.[0]).toEqual([true]);
  });
});

describe('SessionSidebar numbering', () => {
  it('numbers sessions by creation order without changing visible order', () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: [{
          id: 'project-1',
          name: 'Project',
          sessions: [
            { id: 's4', title: 'Session 4', createdAt: '2026-06-22T04:00:00.000Z' },
            { id: 's3', title: 'Session 3', createdAt: '2026-06-22T03:00:00.000Z' },
            { id: 's2', title: 'Session 2', createdAt: '2026-06-22T02:00:00.000Z' },
            { id: 's1', title: 'Session 1', createdAt: '2026-06-22T01:00:00.000Z' },
          ],
        }],
        allowProjectNewSession: false,
        allowRename: false,
      },
    });

    expect(wrapper.findAll('.conversation strong').map((item) => item.text())).toEqual([
      'Session 4',
      'Session 3',
      'Session 2',
      'Session 1',
    ]);
  });

  it('emits delete-session from a single session row without selecting it', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: [{
          id: 'project-1',
          name: 'Project',
          sessions: [
            { id: 's1', title: 'Session 1' },
            { id: 's2', title: 'Session 2' },
          ],
        }],
        allowProjectNewSession: false,
        allowRename: false,
        allowSessionDelete: true,
      },
    });

    await wrapper.find('[data-session-delete="s1"]').trigger('click');

    expect(wrapper.emitted('delete-session')).toEqual([['s1']]);
    expect(wrapper.emitted('select-session')).toBeUndefined();
  });
});
