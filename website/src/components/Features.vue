<script setup lang="ts">
const capabilities = [
  {
    index: 'A',
    title: '一个工作台，装下完整过程',
    body: '从提问、推理到工具执行与结果交付，所有状态都在同一条任务脉络里。',
  },
  {
    index: 'B',
    title: '长任务也能放心交出去',
    body: '会话与执行状态持续保存。任务可以暂停、恢复，也可以在关键动作前等待确认。',
  },
  {
    index: 'C',
    title: '从通用 Agent 继续扩展',
    body: '模型、工具、技能与工作流共用同一个 Core，让更多 AI 场景落在一致的基础能力上。',
  },
]
</script>

<template>
  <section id="capabilities" class="capabilities-section">
    <div class="site-container capabilities-layout">
      <header class="capabilities-intro">
        <p class="section-label">不只是一块聊天框</p>
        <h2>把 AI 的能力，变成可持续的工作。</h2>
      </header>

      <ol class="capability-list">
        <li v-for="item in capabilities" :key="item.index">
          <span class="capability-index" aria-hidden="true">{{ item.index }}</span>
          <h3>{{ item.title }}</h3>
          <p>{{ item.body }}</p>
        </li>
      </ol>
    </div>
  </section>
</template>
