# Study 词典数据（English → 中文）

`en-zh.jsonl` 是随插件打包的词典表，桌面（Python 插件）与移动端（Rust runtime）**共用同一个文件**——
两份运行时都直接读它，不存在两份词表。

## 词条格式

每行一个 JSON 对象，字段固定：

```json
{"word":"emit","phonetic_uk":"/iˈmɪt/","phonetic_us":"/iˈmɪt/",
 "senses":[{"pos":"verb","zh":"散发；发出","en":"to send out gas, heat, light, sound, etc.",
            "example":{"en":"The factory emits a lot of smoke.","zh":"这家工厂排放大量烟雾。"}}],
 "forms":{"3sg":"emits","ing":"emitting","pt":"emitted","pp":"emitted"},
 "source":"generated"}
```

- `senses`：按常用度排序，最多三条；每条含词性、简明中文释义、英文释义、一条例句及其中文翻译。
- `forms` 只用这些键：`pl` `pt` `pp` `ing` `3sg` `comparative` `superlative`。
- `source`：`curated` 表示仓库内手写词条（保留在 `lexicon.py`，构建时并入本文件）；生成的词条不带该字段（运行时视为 bundled）。
- 词形还原（复数、过去式、比较级等）在运行时完成，`emits` / `emitted` / `emitting` 都能落到 `emit`。

## 查询顺序（两端一致）

1. 手写词条（`lexicon.py` 的 `ENTRIES`，桌面优先命中；同一份内容也已并入本文件供移动端使用）。
2. 本文件（生成的词表）。
3. **learned** 层：模型实时给出的词条会写入 `study.db`（kind=`dictionary`，id=`dictionary:<word>`），
   同一个词再次查询直接命中该表，不再调用模型。

## 生成与维护

```powershell
py -3.14 scripts/build-study-dictionary.py --stage list      # 生成/补齐词表 words.txt
py -3.14 scripts/build-study-dictionary.py --stage entries   # 生成词条（可中断、可续跑）
py -3.14 scripts/build-study-dictionary.py --stage prune     # 剔除专有名词等不该收录的词
py -3.14 scripts/build-study-dictionary.py --stage validate  # 校验现有词条
```

- 脚本按批调用**用户自己配置的模型**（`--model` 指定，默认当前使用的模型；思考强度设为 light），
  每条产出都要过 `lexicon.normalize_entry` 校验（词性/中文释义/例句/音标格式/词形键名），不合格的丢弃并在下次续跑时重试。
- 构建是幂等的：已存在的词条跳过，`words.txt` 只增不改，重复执行只会补齐缺口。
- `en-zh.manifest.json` 记录词条数、模型、**累计**用量（多次运行会累加）、生成时间与文件 sha256；
  `words.txt` 是词表来源；`en-zh.rejected.json` 累积记录被排除的词（专有名词等，不会再被重新请求）。
- 词表来源：模型提案 + `wordfreq` 词频校验补齐（构建脚本用，不进产物）。

## 当前规模（2026-09-25 构建）

- 词条 5,769 条（含 108 条手写词条）；词表 5,744 个词。
- 构建用量：365 次调用 / 199,567 prompt + 5,139,061 completion tokens；数据文件 2.85 MB。

## 许可与来源

本表**不含任何第三方词典原文**。词条由用户配置的模型生成，构建脚本只做格式校验与去重；
手写词条（`source: curated`）为本仓库原创的简明释义。因此本文件可以随产品自由分发。
若后续引入外部词库（如 CC BY-SA 的 Wiktionary 派生数据或授权词库），必须在本文件与
`en-zh.manifest.json` 中补记来源与许可，并遵守相应署名/相同方式共享条款。
