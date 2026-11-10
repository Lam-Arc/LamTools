# SVG 图解模式（按本章内容选，不按页选）

一套底色和配色，换图形不换样式。宽度固定 `viewBox="0 0 960 H"`，`width="100%"`，高度按内容给。

配色建议（与页面 CSS 变量一致）：

```
--ink:#1f2329  --muted:#5b6470  --line:#c9d1da  --accent:#2f6feb
--accent-soft:#e8f0ff  --warn:#c2410c  --warn-soft:#fdeee6  --ok:#0f7b52  --ok-soft:#e6f5ee
```

## 1 流程 / 步骤路径（讲操作顺序、处理链路）

要点：从左到右或从上到下，方框 + 箭头，判断点用菱形，终点用深色块。

```html
<svg viewBox="0 0 960 190" width="100%" role="img" aria-label="音频抓取到转写的流程">
  <defs>
    <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#2f6feb"/>
    </marker>
  </defs>
  <rect x="20" y="60" width="200" height="70" rx="10" fill="#e8f0ff" stroke="#2f6feb"/>
  <text x="120" y="90" text-anchor="middle" font-size="15" fill="#1f2329">yt-dlp 抓音频</text>
  <text x="120" y="112" text-anchor="middle" font-size="12" fill="#5b6470">bestaudio -&gt; mp3</text>
  <line x1="220" y1="95" x2="300" y2="95" stroke="#2f6feb" stroke-width="2" marker-end="url(#ar)"/>
  <rect x="310" y="60" width="200" height="70" rx="10" fill="#fff" stroke="#c9d1da"/>
  <text x="410" y="90" text-anchor="middle" font-size="15" fill="#1f2329">ffprobe 校验时长</text>
  <text x="410" y="112" text-anchor="middle" font-size="12" fill="#c2410c">差异 &gt; 5% 就重下</text>
  <line x1="510" y1="95" x2="590" y2="95" stroke="#2f6feb" stroke-width="2" marker-end="url(#ar)"/>
  <rect x="600" y="60" width="200" height="70" rx="10" fill="#fff" stroke="#c9d1da"/>
  <text x="700" y="90" text-anchor="middle" font-size="15" fill="#1f2329">Whisper 转写</text>
  <text x="700" y="112" text-anchor="middle" font-size="12" fill="#5b6470">turbo / small.en</text>
</svg>
```

## 2 概念关系 / 分层（讲体系、上下位、并列）

要点：分层用嵌套矩形，并列用同层卡片，关系用带标签的连线。

```html
<svg viewBox="0 0 960 240" width="100%" role="img" aria-label="时间线、调色、音频三层结构">
  <rect x="20" y="20" width="920" height="60" rx="10" fill="#e8f0ff" stroke="#2f6feb"/>
  <text x="40" y="46" font-size="15" fill="#1f2329">应用层：项目经理的剪辑动作</text>
  <text x="40" y="66" font-size="12" fill="#5b6470">剪切、变速、字幕轨</text>
  <rect x="60" y="100" width="840" height="60" rx="10" fill="#fff" stroke="#c9d1da"/>
  <text x="80" y="126" font-size="15" fill="#1f2329">数据层：片段索引与关键帧</text>
  <text x="80" y="146" font-size="12" fill="#5b6470">in/out 点、轨道顺序</text>
  <rect x="100" y="180" width="760" height="50" rx="10" fill="#f5f7fa" stroke="#c9d1da"/>
  <text x="120" y="209" font-size="14" fill="#1f2329">存储层：媒体文件与缩略图缓存</text>
  <line x1="480" y1="80" x2="480" y2="100" stroke="#c9d1da" stroke-width="2" stroke-dasharray="4 3"/>
  <line x1="480" y1="160" x2="480" y2="180" stroke="#c9d1da" stroke-width="2" stroke-dasharray="4 3"/>
</svg>
```

## 3 时间线（讲发展、版本变化、操作时序）

要点：一条横轴，节点带时间标签，关键转折用加粗点。

```html
<svg viewBox="0 0 960 200" width="100%" role="img" aria-label="项目从建轨到导出的时间线">
  <line x1="60" y1="100" x2="900" y2="100" stroke="#c9d1da" stroke-width="3"/>
  <circle cx="140" cy="100" r="8" fill="#2f6feb"/>
  <text x="140" y="78" text-anchor="middle" font-size="13" fill="#1f2329">00:00 建轨</text>
  <text x="140" y="128" text-anchor="middle" font-size="12" fill="#5b6470">导入素材</text>
  <circle cx="420" cy="100" r="8" fill="#2f6feb"/>
  <text x="420" y="78" text-anchor="middle" font-size="13" fill="#1f2329">04:12 首轮剪辑</text>
  <text x="420" y="128" text-anchor="middle" font-size="12" fill="#5b6470">粗剪定节奏</text>
  <circle cx="700" cy="100" r="11" fill="#c2410c"/>
  <text x="700" y="76" text-anchor="middle" font-size="13" fill="#c2410c">12:40 字幕对时</text>
  <text x="700" y="130" text-anchor="middle" font-size="12" fill="#5b6470">这里最容易翻车</text>
  <circle cx="880" cy="100" r="8" fill="#0f7b52"/>
  <text x="880" y="78" text-anchor="middle" font-size="13" fill="#1f2329">21:05 导出</text>
</svg>
```

## 4 对比矩阵（讲方案取舍）

要点：表头是维度，行是方案，格子写具体差异，别写「好 / 差」这种空词。

```html
<svg viewBox="0 0 960 220" width="100%" role="img" aria-label="两种导出方式的对比矩阵">
  <rect x="20" y="20" width="920" height="180" rx="10" fill="#fff" stroke="#c9d1da"/>
  <line x1="20" y1="60" x2="940" y2="60" stroke="#c9d1da"/>
  <text x="40" y="46" font-size="14" fill="#5b6470">维度</text>
  <text x="380" y="46" font-size="14" fill="#2f6feb">硬件编码</text>
  <text x="700" y="46" font-size="14" fill="#c2410c">软件编码</text>
  <text x="40" y="96" font-size="14" fill="#1f2329">速度</text>
  <text x="380" y="96" font-size="14" fill="#1f2329">快，约 1/4 时长</text>
  <text x="700" y="96" font-size="14" fill="#1f2329">慢，约 2 倍时长</text>
  <line x1="20" y1="115" x2="940" y2="115" stroke="#eef1f5"/>
  <text x="40" y="146" font-size="14" fill="#1f2329">画质</text>
  <text x="380" y="146" font-size="14" fill="#1f2329">同码率下略糊</text>
  <text x="700" y="146" font-size="14" fill="#0f7b52">同码率下更干净</text>
  <line x1="20" y1="165" x2="940" y2="165" stroke="#eef1f5"/>
  <text x="40" y="190" font-size="14" fill="#1f2329">适用</text>
  <text x="380" y="190" font-size="14" fill="#1f2329">日更、草稿</text>
  <text x="700" y="190" font-size="14" fill="#1f2329">成片、交付</text>
</svg>
```

## 5 检查表 / 决策树（讲风险、误区、判断条件）

要点：决策树用菱形判条件，两条出口各写后果；检查表用方框加勾选标记。

```html
<svg viewBox="0 0 960 250" width="100%" role="img" aria-label="音频时长不一致时的判断路径">
  <defs>
    <marker id="aw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#c2410c"/>
    </marker>
  </defs>
  <polygon points="480,20 700,70 480,120 260,70" fill="#e8f0ff" stroke="#2f6feb"/>
  <text x="480" y="74" text-anchor="middle" font-size="14" fill="#1f2329">差异是否超过 5%</text>
  <line x1="480" y1="120" x2="480" y2="170" stroke="#0f7b52" stroke-width="2"/>
  <rect x="330" y="170" width="300" height="60" rx="10" fill="#e6f5ee" stroke="#0f7b52"/>
  <text x="480" y="206" text-anchor="middle" font-size="14" fill="#0f7b52">否：继续转写</text>
  <line x1="700" y1="70" x2="820" y2="70" stroke="#c2410c" stroke-width="2" marker-end="url(#aw)"/>
  <text x="750" y="60" text-anchor="middle" font-size="12" fill="#c2410c">是</text>
  <rect x="700" y="150" width="230" height="90" rx="10" fill="#fdeee6" stroke="#c2410c"/>
  <text x="815" y="182" text-anchor="middle" font-size="13" fill="#1f2329">重下音频</text>
  <text x="815" y="205" text-anchor="middle" font-size="13" fill="#1f2329">仍不一致则标异常</text>
  <text x="815" y="228" text-anchor="middle" font-size="12" fill="#5b6470">时间戳以 ffprobe 为准</text>
</svg>
```

## 6 数据简图（讲规模、比例、耗时）

要点：条形长度对应真实数值，必须标数值和单位，必须有比较基准。

```html
<svg viewBox="0 0 960 210" width="100%" role="img" aria-label="各阶段耗时占比">
  <text x="20" y="30" font-size="14" fill="#1f2329">62 分钟视频各阶段耗时</text>
  <rect x="180" y="50" width="380" height="26" rx="4" fill="#2f6feb"/>
  <text x="170" y="69" text-anchor="end" font-size="13" fill="#5b6470">下载音频</text>
  <text x="572" y="69" font-size="13" fill="#1f2329">1.8 分钟</text>
  <rect x="180" y="90" width="620" height="26" rx="4" fill="#0f7b52"/>
  <text x="170" y="109" text-anchor="end" font-size="13" fill="#5b6470">转写</text>
  <text x="812" y="109" font-size="13" fill="#1f2329">11 分钟</text>
  <rect x="180" y="130" width="300" height="26" rx="4" fill="#c2410c"/>
  <text x="170" y="149" text-anchor="end" font-size="13" fill="#5b6470">抽帧与截图</text>
  <text x="492" y="149" font-size="13" fill="#1f2329">5 分钟</text>
  <text x="180" y="186" font-size="12" fill="#5b6470">基准：最终报告的 62 分钟视频，CPU 转写</text>
</svg>
```

## 7 因果链路（讲连锁反应、为什么翻车）

要点：每个环节写「原因」，箭头写「导致」，最后落到可观察的结果。

```html
<svg viewBox="0 0 960 210" width="100%" role="img" aria-label="时间戳错位的因果链">
  <defs>
    <marker id="ac" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#c2410c"/>
    </marker>
  </defs>
  <rect x="20" y="70" width="190" height="70" rx="10" fill="#fdeee6" stroke="#c2410c"/>
  <text x="115" y="100" text-anchor="middle" font-size="14" fill="#1f2329">抓了多 P 视频</text>
  <text x="115" y="122" text-anchor="middle" font-size="12" fill="#5b6470">只下了第 1 个 P</text>
  <line x1="210" y1="105" x2="300" y2="105" stroke="#c2410c" stroke-width="2" marker-end="url(#ac)"/>
  <text x="255" y="96" text-anchor="middle" font-size="12" fill="#c2410c">导致</text>
  <rect x="310" y="70" width="200" height="70" rx="10" fill="#fff" stroke="#c9d1da"/>
  <text x="410" y="100" text-anchor="middle" font-size="14" fill="#1f2329">时长比对不符</text>
  <text x="410" y="122" text-anchor="middle" font-size="12" fill="#5b6470">差 5% 以上</text>
  <line x1="510" y1="105" x2="600" y2="105" stroke="#c2410c" stroke-width="2" marker-end="url(#ac)"/>
  <text x="555" y="96" text-anchor="middle" font-size="12" fill="#c2410c">导致</text>
  <rect x="610" y="70" width="330" height="70" rx="10" fill="#fff" stroke="#c9d1da"/>
  <text x="775" y="100" text-anchor="middle" font-size="14" fill="#1f2329">报告里的回跳时间戳全部偏移</text>
  <text x="775" y="122" text-anchor="middle" font-size="12" fill="#5b6470">结论点不到对应画面</text>
</svg>
```

## 自检

每张图画完对一遍：

- 把 SVG 里的文字单独读出来，是不是这一章的关键词，而不是「步骤一、步骤二」。
- 有没有箭头、连线、坐标轴这类关系表达，拿掉箭头这张图还讲得通吗，讲得通说明是装饰图。
- 和上一章的图对比，除了标题不同以外是否完全一样，一样就重画。
- 文字有没有压线、出框，字号是否 >= 11px。
