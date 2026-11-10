# 二次元生图提示词技能对照

生成时间：2026-11-10。全部在本机 ComfyUI 0.43.1 上真实出图，同一模型、同一参数、同一种子，只有提示词与负面词按各项目自己的规则分别撰写。

本文只记录提示词、参数和产物，不做画面优劣判断。

阅读顺序提示：真正可比的是第七节那一组（A0 到 A4，统一栈按 Good Anima 官方工作流搭起来）。第二节到第五节那四张（cmp-R1 到 cmp-R4）是早期在没有 LoRA、没有自定义采样节点的小模型上跑的，只能看提示词结构，不能用来比画质。第六节是 DSH 插件的 Qwen 基线。

## 一、统一实验条件

| 项 | 值 |
| --- | --- |
| 模型 | `anima-aesthetic-v1.1.safetensors` |
| 文本编码器 | `qwen_3_06b_base.safetensors`，CLIPLoader type=`stable_diffusion` |
| VAE | `qwen_image_vae.safetensors` |
| 采样器 / 调度器 | `er_sde` / `simple` |
| 步数 / CFG | 30 / 4.0 |
| 尺寸 | 832 x 1216 |
| 种子 | 20261110（四行完全相同） |
| 工作流 | UNETLoader + CLIPLoader + VAELoader + CLIPTextEncode 两次 + EmptyLatentImage + KSampler + VAEDecode + SaveImage |
| 生成方式 | 直接 HTTP 提交 ComfyUI `/prompt`，轮询 `/history`，经 `/view` 取图 |

四行之间唯一的变量是提示词结构、质量前缀与负面词。

## 二、总表

| 编号 | 采用的规则 | 提示词结构 | 提示词字数 | 负面词条数 | 耗时 | 产物 |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | 裸标签基线 | 单段逗号标签 | 26 个标签 | 9 | 91 秒（含首次加载） | `artifacts/anima-compare/cmp-R1.png` |
| R2 | ComfyUI Good Anima v2mini | 质量前缀一段 + 空行 + 自然语言一段 | 前缀 9 + 标签 20 + 6 句 | 16 | 22 秒 | `artifacts/anima-compare/cmp-R2.png` |
| R3 | Anima Prompting | 四段，空行分隔：质量/年份/安全、角色数、通用标签、自然语言 | 4 段共 11 句 | 11 | 19 秒 | `artifacts/anima-compare/cmp-R3.png` |
| R4 | Hermes 构图技能 | 单段标签，按 Camera → Expression → Pose 归组 | 25 个标签 | 9 | 21 秒 | `artifacts/anima-compare/cmp-R4.png` |

## 三、逐行详情

### R1 裸标签基线

用途：作为对照组，代表「直接堆 booru 标签」的普通写法。

提示词：

```text
1girl, whale girl, solo, short hair, blue hair, gradient hair, fin hair ornament, white sailor dress, blue skirt, whale tail, sitting, on rock, looking at viewer, smile, ocean, underwater, light rays, depth of field, upper body, from below, cel shading, anime style
```

负面词：

```text
worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia
```

### R2 ComfyUI Good Anima v2mini

规则来源：`ShiroEirin/comfyui-good-anima` 的 `comfyui-animatool`。它要求先出视觉简报再组装三层：`tag_block`（质量、年代、安全、角色、外观、道具）+ `nltags_block`（位置、关系、接触、视线、光源、景深），负面词按风险动态追加。

提示词，第一段是质量前缀，空行后是自然语言：

```text
masterpiece, best quality, score_7, safe, newest, year 2025, 1girl, solo, whale girl, short hair, blue hair, gradient hair, fin hair ornament, white sailor dress, blue skirt, sitting, on rock, looking at viewer, smile, ocean, underwater, light rays

girl sits on a rock at the shallow sea floor. she turns her head and looks at the camera. her hand rests on a whale tail. whales swim far behind her. light rays fall from the water surface. camera looks up at her from below, half body.
```

负面词，按它列的脸、手、脚、多人、透视、持物风险组装：

```text
worst quality, low quality, score_1, score_2, score_3, bad anatomy, bad hands, extra fingers, missing fingers, bad feet, extra limbs, merged characters, duplicate, cropped, out of frame, bad perspective, signature, watermark, jpeg artifacts
```

与官方默认链路的差异：官方默认是 `anima-base-v1.0` 加双美学 LoRA 加 FLSamplerV4/RES4LYF 加 TeaCache 加 RTX VSR。本机没有那两个 LoRA，也没有 FLSamplerV4 与 RES4LYF 节点，所以按它文档写的「裸模型」前缀 `masterpiece, best quality, score_7, safe` 和裸模型采样器 `er_sde` + `simple` 来跑，其余参数与其它行持平。这一行验证的是提示词结构，不代表它官方工作流的完整效果。

### R3 Anima Prompting

规则来源：`Volnovik/anima-prompting` 的 `SKILL.md`。四段固定顺序，段间空行：质量/年份/安全 → 角色数/角色/作品/画师 → 通用标签 → 自然语言。自然语言段按它的「给 0.6B 小脑写」原则：短句、每句一个可见事实、不用含糊代词。

提示词：

```text
masterpiece, best quality, safe, year 2025, newest

1girl

solo, whale girl, short hair, blue hair, gradient hair, fin hair ornament, white sailor dress, blue skirt, sitting, on rock, looking at viewer, smile, ocean, underwater, light rays, upper body, from below, cel shading

A whale girl sits on a rock at the shallow sea floor. She has short blue gradient hair and blue white fin ear ornaments. She wears a white sailor dress with a blue skirt. She turns her head and looks at the viewer. She smiles. One hand rests on a whale tail. Whales swim far behind her. Light rays fall down from the water surface. The camera looks up at her. Cel shading anime style.
```

负面词，用它表格里 Aesthetic 版本的推荐清单。注意它明确说 Aesthetic 版不要用 `score_*`，会推向 slop：

```text
worst quality, low quality, score_1, score_2, score_3, artist name, censored, signature, twins, jpeg artifacts, chromatic aberration
```

### R4 Hermes 构图技能

规则来源：`re-forest/hermes-anime-composition-skills`。它把镜头、表情、姿势拆成三个拥有者技能，由 `anima-prompt-optimizer` 合并，输出标签模式或自然语言模式。它本身是纯文本技能，不含生图后端，也没有可直接运行的脚本。

提示词，按 Camera → Expression → Pose 的顺序归组后合并成一段：

```text
1girl, solo, whale girl, short hair, blue hair, gradient hair, fin hair ornament, white sailor dress, blue skirt, ocean, underwater, light rays, cel shading, from below, upper body, shallow depth of field, looking at viewer, gentle smile, half-closed eyes, sitting, on rock, hand on tail, head turn
```

负面词，该套件没有规定，用基线那份：

```text
worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia
```

与它完整形态的差异：它的 Camera → Expression → Pose 交接、三候选受控选择、锁轴与 receipt 验证这一整套流程没有实现，这里只取了它最终输出的标签形态。

## 四、客观差异

四行共用同一模型、同一种子、同一尺寸与采样参数，因此：

- R1、R4 是纯标签流，提示词没有自然语言成分。
- R2 是「标签段 + 自然语言段」两段式，并带质量前缀与年代标签。
- R3 是四段式，质量段与角色数段各自独立成段，自然语言段最长。
- 负面词长度 R1 与 R4 相同，R2 最长（16 条），R3 采用 Aesthetic 专用清单且不含 `blurry` 与 `sepia`。
- 耗时差异主要来自首次加载模型，R1 91 秒含加载，其余三张 19 到 22 秒。

两个项目在 `score_*` 上直接冲突，这一行数据也体现了这点：

- Good Anima 的裸模型前缀是 `masterpiece, best quality, score_7, safe`，R2 照用。
- Anima Prompting 明确写「Aesthetic 版本不要用 `score_*`，会推向 slop」，R3 不用。
- 本次跑的是 `anima-aesthetic-v1.1`，属于 Aesthetic 分支，所以这两个前缀指导在本行是互斥的。要判定哪个说法成立，需要拿同一个种子再跑一轮只换前缀的对照。

## 五、产物

| 编号 | 文件 |
| --- | --- |
| R1 | `artifacts/anima-compare/cmp-R1.png` |
| R2 | `artifacts/anima-compare/cmp-R2.png` |
| R3 | `artifacts/anima-compare/cmp-R3.png` |
| R4 | `artifacts/anima-compare/cmp-R4.png` |

每张图的完整提示词、负面词与参数同时保存在生成机的 `payloads/R*.json` 与 `payloads/manifest.json` 里，可直接重放。

## 六、补充：DSH 插件那套基线

前面四行用的是本机现成的 Anima 小模型，拿来横向比质量是不对的。这里补上 dsh-qwen-paint 插件的原始基线，工作流直接调用插件自己的 `buildWorkflow`，节点、连线、cfg、步数一字未改。

### 条件

| 项 | 值 |
| --- | --- |
| 主模型 | `qwen_image_2.1_int8_convrot.safetensors`，7,256,783,064 字节 |
| 文本编码器 | `qwen3vl_8b_w4a8.safetensors`，6,312,105,364 字节，CLIPLoader type=`qwen_image` |
| VAE | `qwen_image_2.1_vae_bf16.safetensors`，675,509,688 字节 |
| 校验 | 三个文件 SHA256 全部与 ModelScope 官方文件列表一致 |
| 工作流 | UNETLoader + CLIPLoader + VAELoader + TextEncodeQwenImage21 + QwenImage21Cache + EmptyLatentImage + KSampler + VAEDecode + SaveImage |
| 采样 | euler + simple，25 步，cfg 1.0，denoise 1.0 |
| 编码分辨率 | 1024，固定 |
| 负面词 | 空字符串，插件对 cfg=1 的建议就是不填 |
| 种子 | 20261110 |

### 提示词

按插件的配方写，主体 + 外观细节 + 环境 + 光线 + 风格 + 画质词，中文：

```text
鲸鱼娘。拟人化的鲸鱼少女，深蓝色短发带渐变，发梢像尾鳍，耳侧有蓝白相间的鲸鳍状耳饰，珊瑚色的眼睛，温柔地微笑。白蓝相间的水手服，靛蓝色百褶裙，赤脚。她坐在浅海的礁石上，身后一条鲸尾，远处有鲸群游过。水下漫射的丁达尔光从头顶斜射下来，蓝色体积光。日系动画赛璐璐风格，柔和阴影，高清细节。
```

### 两张结果

| 编号 | 尺寸 | 耗时 | 产物 |
| --- | --- | --- | --- |
| Q1 | 832 x 1216，2:3 | 351 秒，含首次加载 13.5 GB 权重 | `artifacts/anima-compare/qwen-Q1.png` |
| Q2 | 992 x 992，1:1 | 16 秒，模型已在显存 | `artifacts/anima-compare/qwen-Q2.png` |

### 与前面四行的关系

四行 Anima 结果与这两行不是同一基线，不能直接横向比较画质。要评判 Good Anima 与 Anima Prompting 的真实水平，需要按其文档准备 `anima-base-v1.0`、双美学 LoRA 与 FLSamplerV4、RES4LYF 节点后重跑，本机目前缺这些组件。

## 七、统一栈复现（本轮真正可比的一组）

按 Good Anima 仓库自带的 `anima-txt2img-base` 工作流 JSON 逐节点复刻，五个提示词技能在同一套栈上跑，唯一变量是提示词与负面词。

### 安装的组件

| 组件 | 来源 | 状态 |
| --- | --- | --- |
| ANIMA_BOOSTER v1.3.0 | `BlackSnowSkill/ANIMA_BOOSTER` | 已装，提供 AnimaBoosterLoader 与 AnimaTeaCache |
| ComfyUI-BSS_FLSampler v1.3.0 | `BlackSnowSkill/ComfyUI-BSS_FLSampler` | 已装，提供 FLS_SamplerV4 |
| RES4LYF | `ClownsharkBatwing/RES4LYF` | 已装，提供 `beta57` 调度器，补装了 pywavelets、opencv、matplotlib |
| anima-highres-aesthetic-boost | `LyliaEngine/anima-highres-aesthetic-boost`，138 MB | 已下载，装在 models/loras |

### 栈参数

| 项 | 值 |
| --- | --- |
| 模型 | `anima-aesthetic-v1.1.safetensors` |
| LoRA | `anima-highres-aesthetic-boost.safetensors`，强度 1.0 |
| 文本编码器 | `qwen_3_06b_base.safetensors`，type=`stable_diffusion` |
| VAE | `qwen_image_vae.safetensors` |
| 采样 | FLS_SamplerV4，`dpmpp_2m_sde_gpu` + `beta57`，30 步，cfg 4.5，denoise 1.0，fovea 3.0，sharpness 0.5，mask_inertia 0.85 |
| 加速 | AnimaTeaCache，threshold 0.15，adaptive，v1 Legacy Fast |
| 尺寸 / 种子 | 1024 x 1536 / 20261110 |

### 与官方工作流的差异

- 底座用 `anima-aesthetic-v1.1` 代替 `anima-base-v1.0`。后者 12.2 GB，HuggingFace 直连被墙，镜像单连 1.8 MB/s，本轮没有等它。
- 只装了一个 LoRA。官方的第二个 `anima-base-1-masterpiece-v51` 在 HuggingFace 上没有找到可用的 Anima 版本，Civitai 需要登录。
- 没有 `RTXVideoSuperResolution` 2 倍放大。那个节点包要 TensorRT 引擎，没有安装，所以产物是 1024x1536 原生分辨率。
- T8 那一行只用了它自带的 52 套风格预设与 default_negative，没有安装它的节点包，因为节点包的抓取功能依赖 Civitai 与 Gelbooru 的密钥。
- Hermes 那一行只取它的标签模式输出，它的 Camera → Expression → Pose 交接与三候选选择流程没有实现。

### 五行提示词

A0 裸标签基线：

```text
1girl, solo, whale girl, short hair, blue hair, gradient hair, fin hair ornament, white sailor dress, blue skirt, sitting, on rock, looking at viewer, smile, ocean, underwater, light rays, upper body, from below, cel shading
```

A1 Good Anima 三层，质量前缀 + 标签段 + 自然语言段：

```text
masterpiece, best quality, score_7, safe, newest, year 2025, 1girl, solo, whale girl, short hair, blue hair, gradient hair, fin hair ornament, white sailor dress, blue skirt, sitting, on rock, looking at viewer, smile, ocean, underwater, light rays, upper body

girl sits on a rock at the shallow sea floor. she turns her head and looks at the camera. her hand rests on a whale tail. whales swim far behind her. light rays fall from the water surface. camera looks up at her from below, half body.
```

A2 Anima Prompting 四段：

```text
masterpiece, best quality, safe, year 2025, newest

1girl

1girl, solo, whale girl, short hair, blue hair, gradient hair, fin hair ornament, white sailor dress, blue skirt, sitting, on rock, looking at viewer, smile, ocean, underwater, light rays, upper body, from below, cel shading

A whale girl sits on a rock at the shallow sea floor. She has short blue gradient hair and blue white fin ear ornaments. She wears a white sailor dress with a blue skirt. She turns her head and looks at the viewer. She smiles. One hand rests on a whale tail. Whales swim far behind her. Light rays fall down from the water surface. The camera looks up at her. Cel shading anime style.
```

A3 Hermes 构图标签：

```text
1girl, solo, whale girl, short hair, blue hair, gradient hair, fin hair ornament, white sailor dress, blue skirt, sitting, on rock, looking at viewer, smile, ocean, underwater, light rays, shallow depth of field, gentle smile, half-closed eyes, hand on tail, head turn
```

A4 T8 风格预设，用「动漫默认」预设打头：

```text
score_9, score_8_up, score_7_up, masterpiece, best quality, highly detailed, anime style, beautiful face, detailed eyes, vibrant colors, 1girl, solo, whale girl, short hair, blue hair, gradient hair, fin hair ornament, white sailor dress, blue skirt, sitting, on rock, looking at viewer, smile, ocean, underwater, light rays, upper body, from below, cel shading
```

A4 的负面词用它自带的 default_negative，共 446 字符，含 lazyneg、lazyhand、photorealistic、artist name 等 30 余条。

### 结果

| 编号 | 规则来源 | 提示词字数 | 负面词字数 | 耗时 | 产物 |
| --- | --- | --- | --- | --- | --- |
| A0 | 裸标签基线 | 224 | 84 | 104 秒含加载 | `artifacts/anima-compare/anima2-A0.png` |
| A1 | ComfyUI Good Anima v2mini | 497 | 240 | 28 秒 | `artifacts/anima-compare/anima2-A1.png` |
| A2 | Anima Prompting | 669 | 132 | 28 秒 | `artifacts/anima-compare/anima2-A2.png` |
| A3 | Hermes 构图技能 | 268 | 84 | 28 秒 | `artifacts/anima-compare/anima2-A3.png` |
| A4 | T8 风格预设 | 361 | 446 | 28 秒 | `artifacts/anima-compare/anima2-A4.png` |

五行同栈同种子，文件均为 1024x1536，可直接并排查看。

一处组装瑕疵要说明：A2 的第三段里重复带了 `1girl` 计数标签，按 Anima Prompting 的规则它应当只出现在第二段。这一批结果没有重跑，记录在此以免误读。
