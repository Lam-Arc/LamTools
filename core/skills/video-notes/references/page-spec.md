# 单页报告规格（离线、单文件）

骨架用 `assets/page-template.html`，把 `{{...}}` 换成真内容。这一页是最终交付物：CSS 内联、SVG 内联、截图走相对路径，整个目录拷到别的机器仍然能打开。

## 结构顺序

```
页头   标题 / UP 主 / 时长 / 标签 / 简介（折叠）/ 封面缩略图 / 音频播放器 / 源地址
目录   章节列表，每项带起止时间戳
章节 × n
        1 正文   问题 / 陷阱 / 步骤 / 结论 + 关键引用 + 视觉锚点
        2 图解   内联 SVG，图注前缀「图解」
        3 截图   真实帧（界面演示类视频），图注前缀「视频时间戳 12:34」
页尾   元数据校验记录、生成说明、切片索引
```

顺序不要变。图解讲关系，截图给实证，读者从上往下看是「说清楚 → 画出来 → 看一眼真东西」。

## 组件类名

| 类名 | 用途 |
|---|---|
| `.wrap` | 内容宽度容器，最大 1080px |
| `.hero` | 页头区块 |
| `.meta-grid` | 标题、UP、时长、标签的网格 |
| `.desc` | 简介折叠区（`<details>`） |
| `.toc` | 目录 |
| `section.chapter` | 一章，带 `data-start` / `data-end` 秒数 |
| `.stamp` | 时间戳，链接放在这里 |
| `.block.ask / .trap / .steps / .conclusion` | 四要素块，各带小标题 |
| `.quote` | 关键引用，带时间戳 |
| `.anchor` | 视觉锚点描述 |
| `figure.fig` | 图解或截图容器，内含 `<figcaption>` |
| `.fig-note` | 图注里的来源前缀，「图解」或「视频时间戳」 |
| `.check` | 校验记录表 |

## 时间戳回跳

在线视频：

```html
<a class="stamp" href="https://www.bilibili.com/video/BV1xxxxxxxxx?p=2&amp;t=754" target="_blank" rel="noopener">12:34</a>
```

`t=` 用整数秒。分 P 必须带 `p=`，否则跳到第 1 个 P。

本地文件（离线可跳）：链接指向本地音频，页面内联脚本把点击变成 seek，不弹新窗口。

```html
<a class="stamp" href="audio/BV1xxxx.mp3#t=754" data-seek="754">12:34</a>
```

```html
<audio id="player" controls preload="metadata" src="audio/BV1xxxx.mp3"></audio>
<script>
document.querySelectorAll('a.stamp[data-seek]').forEach(a => {
  a.addEventListener('click', ev => {
    if (!a.getAttribute('href').startsWith('audio/')) return;   // 在线视频链接照常新窗口打开
    ev.preventDefault();
    const p = document.getElementById('player');
    p.currentTime = parseFloat(a.dataset.seek);
    p.play();
    p.scrollIntoView({block: 'center', behavior: 'smooth'});
  });
});
</script>
```

脚本只写这一小段，别的交互一律不加。报告是拿来读的，不是拿来玩的。

## 章节正文的写法

- 用短句，一句一个意思，不用逗号堆长句。
- 步骤写成 `<ol>`，每步一个动作，动词开头。
- 陷阱只在视频里真的提过时写，没提就不写，不要凭常识补。
- 结论要能独立成立，脱离上下文也读得懂。
- 关键引用是 UP 原话，加引号，紧跟时间戳。
- 视觉锚点写画面上有什么，例如「右下角参数面板里的采样率下拉框」，让读者知道截图说的是哪一块。

## 交付前页面自检

```bash
python scripts/page_shot.py --html report.html --out-dir shots --name page
```

机器查：横向溢出、图片没加载、图片尺寸为 0、SVG 文字节点少于 2 个、SVG 图形元素少于 3 个、SVG 没有箭头或虚线、章节块高度异常、可疑空白带。

然后必须用 `read_file` 看 `shots/page.png`，确认每张 SVG 和每张截图都完整显示、没有重叠、没有大片空白。这一步是硬要求，`qa.json` 通过不等于页面能看。
