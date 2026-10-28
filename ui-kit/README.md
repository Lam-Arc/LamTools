# Sunday Controls

一套可复用的黑白交互控件样式。信号不再是红色或橙色，而是 Sunday 主题里的 **control 反转对**：

- 暗色：象牙白控件 + 石墨字
- 浅色：石墨控件 + 象牙字

任何填充块上的文字、勾、滑块拇指都使用它的反色；不会出现白底白字或黑底黑字。语义红只留给任务失败/危险确认，不作为滑杆、进度条、分段或开关的强调色。

## 文件

| 文件 | 作用 |
|---|---|
| `src/tokens.css` | 明暗两套颜色、交互几何、圆角、动效 token |
| `src/kit.css` | 按钮、输入框、下拉框、滑块、进度条、开关、勾选、分段、滚动条 |
| `src/controls.ts` | 滑块读数、下拉框、分段选择、切换按钮、半选复选框 |
| `src/demo.css` + `index.html` | 可交互样张（不是接入依赖） |
| `dist/controls.js` | `controls.ts` 的编译产物 |

## 直接使用

```html
<link rel="stylesheet" href="src/tokens.css">
<link rel="stylesheet" href="src/kit.css">
<script src="dist/controls.js" defer></script>
```

首次渲染自动初始化。异步插入的节点再调用一次：

```js
Controls.init(rootElement)
```

主题由根元素切换：

```html
<html data-theme="dark">  <!-- 象牙控件 + 石墨字 -->
<html data-theme="light"> <!-- 石墨控件 + 象牙字 -->
```

## 关键规则

1. **信号是反色，不是色相。** 主按钮、选中分段、开关开启、勾选、滑块填充、进度填充都使用 `--control` 底色和 `--control-ink` 文字。
2. **白/象牙底必须配石墨字；石墨底必须配象牙字。** 不给填充块留同色文字。
3. **层级只靠 1px 线、三档表面色和间距。** 这一层不使用投影或拟物光影。
4. **焦点。** 独立样张使用 2px 反色环；接入 Sunday 时沿用现有 `--blue` 键盘焦点环（见设计规范）。
5. **动效克制。** 90 / 150 / 220ms；`prefers-reduced-motion` 下关闭位移和滑动。
6. **红色不是控件强调色。** 危险/失败仍可使用语义红，但滑块、进度、分段、开关不借它做装饰。

## 组件速查

### 按钮

```html
<button class="btn btn--primary">Deploy</button>
<button class="btn">Duplicate</button>
<button class="btn btn--ghost">Skip</button>
<button class="btn btn--danger">Delete</button>
<button class="btn btn--sm">Small</button>
<button class="btn btn--lg">Large</button>
```

- `data-toggle` + `aria-pressed`：可按压开关按钮
- `data-loading="true"` + `.btn__spinner`：加载态
- `--danger` 在独立层是黑白描边，不引入红色

### 输入框

```html
<div class="field">
  <label class="field__label" for="name">Workspace name</label>
  <input class="input" id="name" placeholder="e.g. Atlas">
  <p class="field__hint">Visible to everyone.</p>
  <p class="field__error">Use lowercase letters only.</p>
</div>
```

- `.input-group` + `.input-group__addon`：前缀/后缀
- `aria-invalid="true"`：2px 反色边框 + 错误文字
- `.input--area`：多行输入

### 滑块

```html
<div class="slider" data-suffix="%" data-decimals="0" style="--fill: 48%">
  <div class="slider__head">
    <label class="slider__label" for="density">Grid density</label>
    <output class="slider__value" data-range-output for="density">48%</output>
  </div>
  <div class="slider__track">
    <span class="slider__fill" aria-hidden="true"></span>
    <input class="slider__input" id="density" type="range" min="0" max="100" value="48">
  </div>
</div>
```

`data-suffix` / `data-decimals` 控制读数格式；脚本同时写入 `aria-valuetext`。

### 进度条

```html
<div class="progress" role="progressbar" aria-valuenow="62" aria-valuemin="0" aria-valuemax="100" style="--value: 62">
  <div class="progress__bar"></div>
</div>
```

- `--buffer` + `.progress--buffer`：缓冲层
- `data-indeterminate="true"`：不确定进度
- `.progress--thin`：细进度

### 下拉框

```html
<div class="select" data-select>
  <button class="select__trigger" type="button" aria-haspopup="listbox" aria-expanded="false">
    <span class="select__value" data-select-value>Staging</span>
    <span class="select__chevron" aria-hidden="true"></span>
  </button>
  <div class="select__popup" role="listbox" tabindex="-1" hidden>
    <div class="select__option" role="option" aria-selected="true" data-value="staging">
      <span class="select__check" aria-hidden="true"></span>
      <span class="select__option-label">Staging</span>
      <span class="select__meta">current</span>
    </div>
  </div>
</div>
```

支持方向键、Home/End、Enter/Space、Esc、Tab、首字母跳转，视口不足时自动向上翻转。选择后派发 `selectchange`：

```js
el.addEventListener('selectchange', (event) => console.log(event.detail.value))
```

### 开关与勾选

```html
<label class="switch">
  <input class="switch__input" type="checkbox" role="switch" checked>
  <span class="switch__track" aria-hidden="true"><span class="switch__thumb"></span></span>
  <span class="switch__text"><span class="switch__title">Stream output</span></span>
</label>

<label class="check">
  <input class="check__input" type="checkbox" checked>
  <span class="check__box" aria-hidden="true"></span>
  <span class="check__label">Remember this device</span>
</label>
```

### 分段

```html
<div class="segmented" data-segmented role="radiogroup" aria-label="View">
  <span class="segmented__indicator" aria-hidden="true"></span>
  <button class="segmented__item" type="button" role="radio" aria-checked="true" data-value="list">List</button>
  <button class="segmented__item" type="button" role="radio" aria-checked="false" tabindex="-1" data-value="grid">Grid</button>
</div>
```

一个 Tab 停靠点；方向键、Home/End 移动选中和指示块。变化时派发 `segmentedchange`。

### 滚动条

给任意滚动容器加 `.scroll`：

```html
<div class="scroll" style="height: 180px; overflow: auto">…</div>
```

4px 拇指嵌在 12px 轨道里；颜色跟随当前主题的 ink。

## 接入 Sunday

生产层在 `core/ui`，不是把独立样张的通用类直接搬进应用：

- `core/ui/src/styles/variables.css`：新增 `--interaction-*` 几何 token
- `core/ui/src/styles/sunday-controls.css`：开关、分段、滑块、进度、按钮按压反馈
- `core/ui/src/components/SundaySwitch.vue`
- `core/ui/src/components/SundaySegmented.vue`
- `core/ui/src/components/SundayRange.vue`

当前使用位置：

- `CoreGeneralEditor.vue`：三个布尔偏好使用 `SundaySwitch`
- `ThemeEditor.vue`：界面密度使用 `SundaySegmented`，内容宽度使用 `SundayRange`
- `ThemeAreaEditor.vue`：渐变角度/透明度使用 `SundayRange`
- `CoreUpdateCard.vue`：更新进度使用 `.sunday-progress`

接入规则：

- 继续用现有 `UiSelect`、输入框和按钮体系；不要导入样张里的 `.btn` / `.input` / `.select`。
- 填充状态使用 `--settings-control-solid` / `--settings-control-text`（设置页）或 `--theme-control-solid` / `--theme-control-text`（其他区域）。
- 键盘焦点沿用现有 `--blue` 环；滑块把环画在拇指上。
- 设计规范已更新为 `lam-design-spec` v0.2.0，包含这套配方和反色文字规则。

## 构建与预览

TypeScript：

```bash
cd ui-kit
node ../core/desktop/node_modules/typescript/bin/tsc src/controls.ts src/demo.ts \
  --outDir dist --target ES2020 --lib DOM,DOM.Iterable,ES2020 --strict --skipLibCheck
```

样张：

```bash
cd ui-kit
python -m http.server 8931
```

打开 `http://127.0.0.1:8931/`。样张是纯静态文件，`dist/controls.js` 是唯一构建产物。
