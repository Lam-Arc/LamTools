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
    // user:“气泡下方不要用行，用小图标可以吗”+(附件以图标引用渲染，文件名在可访问名称与 tooltip 里)
    const attachmentButton = wrapper.get('.reference-items .reference-item');
    expect(attachmentButton.attributes('aria-label')).toContain('note.md');
    expect(attachmentButton.attributes('title')).toContain('note.md');
    expect(wrapper.get('.reference-items').classes()).toContain('reference-items--icons');
  });

  it('keeps upload order while stacking consecutive small files between media cards', () => {
    // user:“比如说，我上传了一个附件图片，再上传了4个附件，再上传了一个视频，
    // 再上传了一个附件，再上传了一个视频”+(媒体各占一列；连续小附件每 3 个叠一列，
    // 第 4 个另起一列但仍夹在原来的图片和视频之间)。
    const doc = (id: string): CoreAttachment => ({
      id, filename: `${id}.txt`, label: `${id}.txt`, mime_type: 'text/plain', size: 10,
      preview_type: 'text', status: 'uploaded',
    })
    const media = (id: string, kind: 'image' | 'video'): CoreAttachment => ({
      id, filename: `${id}.${kind === 'image' ? 'png' : 'mp4'}`, label: `${id}.${kind === 'image' ? 'png' : 'mp4'}`,
      mime_type: kind === 'image' ? 'image/png' : 'video/mp4', size: 10,
      preview_type: kind, status: 'uploaded',
    })
    const wrapper = mountAttachmentTray({
      props: {
        attachments: [
          media('img', 'image'),
          doc('a'), doc('b'), doc('c'), doc('d'),
          media('vid1', 'video'),
          doc('e'),
          media('vid2', 'video'),
        ],
      },
    })
    const columns = wrapper.findAll('.attachment-column')
    expect(columns.map(column => column.classes().find(name => name.startsWith('attachment-column--')))).toEqual([
      'attachment-column--media',
      'attachment-column--stack',
      'attachment-column--stack',
      'attachment-column--media',
      'attachment-column--stack',
      'attachment-column--media',
    ])
    expect(columns.map(column => column.findAll('.attachment-entry').length)).toEqual([1, 3, 1, 1, 1, 1])
    // 第 4 个附件没有被排到视频后面。
    expect(columns[2]!.text()).toContain('d.txt')
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

    // user:“图片和视频附件以大缩略显示”+(媒体条目直接铺大缩略图，不再显示文字胶囊)。
    expect(wrapper.find('.attachment-entry--media').exists()).toBe(true);
    expect(wrapper.find('.attachment-pill').exists()).toBe(false);
    expect(wrapper.find('.attachment-preview--media').exists()).toBe(true);
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.find('img.attachment-media').exists()).toBe(true));
    expect(wrapper.get('img.attachment-media').attributes('src')).toMatch(/^data:image\/png;base64,/);
  });
});
