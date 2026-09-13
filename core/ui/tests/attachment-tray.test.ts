import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import AttachmentTray from '../src/components/AttachmentTray.vue';
import ChatThread from '../src/components/ChatThread.vue';
import type { CoreAttachment, CoreMessage } from '../src/types';
import { createFakeTransport } from './fake-transport'

const uploaded: CoreAttachment = {
  id: 'att-1',
  filename: 'note.md',
  label: 'note.md',
  mime_type: 'text/markdown',
  size: 120,
  preview_type: 'text',
  status: 'uploaded',
};

const testTransport = createFakeTransport()

function mountAttachmentTray(options: any = {}) {
  return mount(AttachmentTray, {
    ...options,
    props: { transport: testTransport, ...(options.props ?? {}) },
  })
}

function mountChatThread(options: any = {}) {
  return mount(ChatThread, {
    ...options,
    props: { transport: testTransport, ...(options.props ?? {}) },
  })
}

describe('AttachmentTray', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('renders uploaded and failed attachments with stable actions', async () => {
    const wrapper = mountAttachmentTray({
      props: {
        attachments: [
          uploaded,
          {
            ...uploaded,
            id: 'att-2',
            filename: 'bad.png',
            label: 'bad.png',
            mime_type: 'image/png',
            preview_type: 'image',
            status: 'failed',
            error: '上传失败',
          },
        ],
      },
    });

    expect(wrapper.text()).toContain('note.md');
    expect(wrapper.text()).toContain('bad.png');
    expect(wrapper.text()).toContain('上传失败');
    expect(wrapper.text()).toContain('MD');
    expect(wrapper.text()).not.toContain('本机打开');

    await wrapper.get('[data-attachment-preview="att-1"]').trigger('click');
    await wrapper.get('[data-attachment-remove="att-1"]').trigger('click');
    await wrapper.get('[data-attachment-retry="att-2"]').trigger('click');

    expect(wrapper.emitted('preview')?.[0]).toEqual(['att-1']);
    expect(wrapper.emitted('remove')?.[0]).toEqual(['att-1']);
    expect(wrapper.emitted('retry')?.[0]).toEqual(['att-2']);
  });

  it('renders user-message attachment parts in ChatThread', () => {
    const messages: CoreMessage[] = [{
      id: 'm-1',
      role: 'user',
      content: '看附件',
      timestamp: '',
      parts: [{
        id: 'm-1:att-1',
        partType: 'attachment',
        status: 'completed',
        content: '',
        label: 'note.md',
        metadata: { attachment: uploaded },
      }],
    }];

    const wrapper = mountChatThread({ props: { messages } });

    expect(wrapper.text()).toContain('看附件');
    expect(wrapper.text()).toContain('note.md');
    expect(wrapper.get('.message-attachment-deck').classes()).toContain('message-attachment-deck--right');
  });

  it('renders image attachments as thumbnail-only cards', async () => {
    const transport = createFakeTransport({
      status: 200,
      headers: { 'content-type': 'image/png' },
      body: Uint8Array.from([137, 80, 78, 71]),
    })
    const wrapper = mountAttachmentTray({
      props: {
        transport,
        attachments: [{
          ...uploaded,
          id: 'image-1',
          filename: 'preview.png',
          label: 'preview.png',
          mime_type: 'image/png',
          preview_type: 'image',
        }],
      },
    });

    expect(wrapper.find('.attachment-card--image').exists()).toBe(true);
    expect(wrapper.find('.attachment-copy').exists()).toBe(false);
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.find('.attachment-thumbnail').exists()).toBe(true));
    expect(wrapper.get('.attachment-thumbnail').attributes('src')).toMatch(/^data:image\/png;base64,/);
  });
});
