# 交互层对外 API

交互层就是原来叫“标注层”的那块全屏透明窗口。任何本机程序都可以通过 Core 的 HTTP 接口在屏幕上画标记、清标记，或者请用户圈一块区域。

## 连接

- 地址：`http://127.0.0.1:<Core 端口>`，默认端口见 Core 启动日志。桌面壳自己用的端口不固定时，从 `get_api_base` 或启动日志里读。
- 只接受环回地址访问；开了 LAN 模式要带 `Authorization: Bearer <token>`。
- 所有坐标都是**虚拟桌面的物理像素**，左上角原点，多屏时副屏可能是负坐标。

## 读状态

```bash
curl http://127.0.0.1:5172/api/core/overlay/state
```

返回：

```json
{
  "version": 12,
  "server_time": 1794223188.4,
  "marks": [
    {
      "id": "mk-ae0fa3da",
      "kind": "arrow",
      "points": [[1052, 41], [1509, 127]],
      "color": "#ff5c8a",
      "width": 4,
      "text": "",
      "ttl": 30,
      "window": null,
      "window_missing": false,
      "label": "",
      "created_at": 1794223158.4,
      "expires_at": 1794223188.4,
      "source": "external"
    }
  ],
  "capture_requested": false
}
```

`capture_requested` 为 true 表示有人（别的程序或 Agent 工具）正在请用户圈一块区域，交互层取走之后会变回 false。

## 画标记

`POST /api/core/overlay/control`，`action` 为 `show`：

```bash
curl -X POST http://127.0.0.1:5172/api/core/overlay/control \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "show",
    "marks": [
      {"kind": "arrow", "points": [[900, 500], [1200, 620]], "color": "#ff5c8a", "width": 4},
      {"kind": "rect", "points": [[1200, 300], [1600, 520]], "color": "#7aa8ff"},
      {"kind": "text", "points": [[900, 460]], "text": "点这里", "ttl": 20},
      {"kind": "danmaku", "points": [[0, 200]], "text": "这条只在上方三成飘过", "ttl": 6},
      {"kind": "sticker", "points": [[1280, 720]], "text": "🎉", "ttl": 3},
      {"kind": "svg", "points": [[400, 700], [900, 1000]],
       "shapes": [{"type": "circle", "cx": 250, "cy": 150, "r": 120, "fill": "none"}]}
    ]
  }'
```

支持的类型：`arrow`、`rect`、`ellipse`、`pen`、`text`、`svg`、`danmaku`、`sticker`。

公共字段：

| 字段 | 说明 |
| --- | --- |
| `points` | 物理像素点。箭头/矩形/椭圆/svg 给两个点，涂鸦给一串点，文字/弹幕/表情包给一个点 |
| `color` | 描边与文字颜色，默认 `#ff5c8a` |
| `width` | 线宽，默认 3 |
| `text` | 文字内容；弹幕和表情包的文字也放这里 |
| `ttl` | 存活秒数。静态标记默认 30，表情包默认 3，上限 24 小时。弹幕不给 ttl 时按句子长度自动给足跨屏时间（4 到 60 秒），长句给更久 |
| `motion` | `{type, duration, fade, easing, from}`，type 可选 `fade/pop/float/drift/danmaku`，from 可选 `right/left/center/top/bottom` |
| `draw` | 只有 svg 用：`{mode: "stroke"\|"reveal"\|"none", duration}`，默认描边逐段画 |
| `image` | 表情包或弹幕的图片：`{asset, width, height}`，asset 由 `desktop_overlay` 工具从工作区复制生成 |
| `window_id` | 绑定到某个窗口，窗口移动时标记跟着走 |

单次最多 40 个，屏幕上最多同时 400 个;sVG 图形最多 200 个，只接受白名单里的图形和属性。

`danmaku` 的轨道固定在屏幕上方 30%，锚点 `y` 换算成页面坐标后对齐成行，行距等于字号乘 1.6 再加 8 像素，所以同一批弹幕不会叠字；文字按中文字宽估算，字越多越慢，倍速只整体缩放不改变这个相对关系。

弹幕的位移时长永远不超过它的寿命：给的 ttl 短于跨屏时间时按寿命反推速度，宁可快一点也不半路消失。

## 续画 SVG

```bash
curl -X POST http://127.0.0.1:5172/api/core/overlay/control \
  -H 'Content-Type: application/json' \
  -d '{"action":"append","id":"mk-ae0fa3da","shapes":[{"type":"path","d":"M 10 220 C 90 140, 220 300, 380 200"}]}'
```

新图形从到达那刻开始画，标记的过期时间顺延到 `now + ttl`。

## 弹幕的表现规则

| 项目 | 行为 |
| --- | --- |
| 轨道 | 只在屏幕上方 30% 的带子里，按锚点对齐成行 |
| 速度 | 基准 240 像素每秒，文字超过 5 个字号宽后逐步降速，最多降 55% |
| 位移 | CSS 动画跑在合成层，页面每帧不改样式，长句也不会一顿一顿 |
| 寿命 | 默认按长度估出跨屏时间，动画一定在寿命内走完 |
| 倍速、字体、字号 | 托盘菜单进交互层设置，改完立刻生效，不用重开窗口 |

## 清除

```bash
# 清空全部
curl -X POST http://127.0.0.1:5172/api/core/overlay/control \
  -H 'Content-Type: application/json' -d '{"action":"clear","all":true}'

# 按 id 清
curl -X POST http://127.0.0.1:5172/api/core/overlay/control \
  -H 'Content-Type: application/json' -d '{"action":"clear","ids":["mk-ae0fa3da"]}'
```

## 请用户圈一块区域

```bash
curl -X POST http://127.0.0.1:5172/api/core/overlay/control \
  -H 'Content-Type: application/json' -d '{"action":"capture"}'
```

交互层会在下一轮轮询（约 400 毫秒）进入框选态，用户拖完直接进 Ping 的截图编辑器。请求只生效一次，页面取走后 `capture_requested` 变回 false；要取消没被取走的请求用 `{"action":"capture_ack"}`。请求有 30 秒有效期：交互层没开的时候不会挂很久之后突然弹出来。

参数类型是严格的：`all` 必须是布尔值，`ids` 必须是数组，传字符串会被拒绝而不是猜你的意思。

前提是桌面端在跑并且交互层已经打开（托盘菜单或 `desktop_overlay` 工具都行）。纯后端进程没有窗口，这个动作不会产生任何可见效果。

## 读表情包图片

`GET /api/core/overlay/assets/<asset>`，只接受服务端生成的随机文件名，不允许路径片段。
