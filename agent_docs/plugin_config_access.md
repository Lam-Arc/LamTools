# 插件配置快照与条件保存 v1

<!-- user:“宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(插件配置复用原文件和管理入口，修订检查与保存/生效边界明确，不冒充 DSH 即时配置)。 -->

Sunday 桌面进程内 Python 插件通过 `context.config` 读取自己的文件配置、做已有基础校验，并按修订号保存完整配置对象。它复用原 config_store 和管理操作；不增加另一份配置状态、数据库或执行器。

## 使用

```python
class Runtime:
    def start(self, context):
        self.config = context.config

    def save_count(self, count):
        before = self.config.read()
        candidate = dict(before.values)
        candidate["count"] = count
        checked = self.config.validate(candidate)
        if not checked.valid:
            return checked
        return self.config.replace(candidate, expected_revision=before.revision)

def create_plugin(context):
    return Runtime()
```

在受管 start/on_load 中获取门面。宿主把该代实际加载的 PluginManifest 与 owner 绑定，不接受调用方传入其他插件名称或路径。停用、重启和启动失败后旧门面拒绝访问，新代重新获取门面。成功写入的文件不因后续启动失败自动回滚。

## 方法

| 方法 | 结果 |
| --- | --- |
| `read()` | ConfigSnapshot：values/schema/revision/exists/path/validation |
| `validate(values)` | ConfigValidation：valid/problems/level；不写文件 |
| `replace(values, *, expected_revision)` | ConfigSaveResult：snapshot/saved/applied/requires_reload |

结果外层不可变，values/schema 是分离的可变副本，修改副本不会直接改文件。read 不注入 schema 默认值，也不合并 profile 或环境覆盖；缺失文件返回 values={}、exists=false，仍有可用于首次保存的 revision。已有语义不合基本 schema 的对象可以读取，validation 会报告问题，允许调用方构造修正值。

配置和 schema 文档必须为不超过 1 MiB 的 UTF-8 JSONC 对象，支持 BOM、注释与尾逗号，不破坏字符串中的 `https://`。值必须为有限的标准 JSON，不接受非字符串对象键、元组或自定义对象。损坏文档、非对象、非有限数字及声明但无法读取的 schema 明确拒绝，不当作空值或无 schema。

### 基础校验的准确范围

validation.level 始终是 basic：沿用已有 validator，检查必填键、已声明的顶层基本 type 与 enum。它不是完整 JSON Schema 或 DSH Config 验证器；嵌套约束、数值范围、正则、组合类型、引用、格式及其他约束不在当前保证内。valid=true 仅表示这些基础检查通过。

没有 schema 时接受符合 JSON 对象契约的值，不自动套用插件构造函数中的默认值。不得把 basic 结果当作运行时一定能接纳的完整配置验证。

## 修订、文件与并发

第三方插件继续使用 `<plugin>/data/config.jsonc`；该目录已有稳定数据链接时沿用其实际位置。内置插件继续使用 `<data_dir>/plugins/<name>.jsonc`，不写只读 bundled 代码目录。配置身份属于插件，不随 for_work_root 自动变成按工作区分层设置。

revision 是内容摘要，覆盖实际路径、插件名/版本、原始配置字节与 schema 字节，能发现外部文件和 schema 编辑，也区分缺失文件与已保存空对象。注释变化也会改变修订。它不是单调计数：原始内容完全恢复后，摘要可以重复。

SDK replace 强制 expected_revision。检查当前文件、校验候选值和写入在合作文件锁内完成，过期值返回 config/conflict。多个合作进程使用相同旧修订保存不同值时，不会一起成功。写入先 flush/fsync 临时文件，再原子替换；锁等待约 2 秒失败后返回 config/busy，由调用方决定是否重试。

管理 `plugin.system.config.get/update` 共用相同路径、快照与保存函数。get 增加 revision、validation_level 和 validation_problems；update 接受 expected_revision，并返回新修订及保存/应用状态。旧调用方省略修订号时保留最后写入覆盖行为，**不能据此说所有界面已经具备过期保护**。现有内置插件直接写入 helper 也参与相同文件锁，但没有修订号的写入仍可能覆盖更早结果。

锁只协调合作写入方，不与任意外部编辑器或代码/schema 替换共同组成完整事务。JSONC 在保存时规范为 JSON，会丢失注释和原格式；不会保留 YAML 表达式或只修改局部文本。

## 保存与应用

ConfigSaveResult.saved=true 只表示文件保存成功；applied=false、requires_reload=true 表示宿主没有执行或确认运行时应用。按操作重新读取配置的插件可以在下一次读取时使用新值；持有旧值的插件需自行重新读取或由宿主显式重载。这里不自动重启插件、不发变更事件，不回滚后续加载失败的已保存文件。

操作同步完成，没有异步回调或 HMR/profile 锁事务。保存后若遇到读取错误，应重新读取文件核对状态，不能仅凭错误假定磁盘一定未改变。坏 JSON 或 schema 的显式文件修复不属于本 API；接口不提供 force 覆盖损坏文档。

## 错误与剩余差异

ConfigError.code 包括 config/conflict、invalid-revision、invalid-values、corrupt、schema、busy、io 和 unavailable。已停止门面另沿用 scope-closed。配置快照是当前插件的原始值，**不是秘密字段脱敏后的 UI 安全投影**；凭据应继续使用 context.credentials，调用方不能把整个快照直接发布给模型或公开界面。

上游固定为 `f3803c96974ad4a94195fb97e5c637e9c2a3afe3` 的[Settings 手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/settings/settings/README.zh.md)和[Config Editor 手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/boot/config-editor/README.zh.md)。

| DSH 能力 | Sunday 当前边界 |
| --- | --- |
| configEditor.edit | 仅可人工改为快照 + 完整对象条件保存，不是等价 edit/apply |
| profile/home/命令行 overlay | 未实现相同层级或覆盖拒绝规则 |
| Config 完整验证与 volatile 引用 | 未实现；当前只基础文件校验 |
| 路径编辑、字段 reset、保留客户端未见字段 | 未实现；replace 是完整替换，调用方负责保留其他字段 |
| secret 角色、存在性标记与表单投影 | 未实现；快照包含原始配置 |
| configure({auto:false}, fiber) | 未提供同等动态表单策略接口 |
| 应用失败恢复文档/patch、与 HMR 串行 | 未实现；保存和重载分开 |
| 注释保留与变更订阅 | 未实现；保存规范化，调用方显式重新读取 |

现有前端尚未接入修订号提交，本批不修改与并行样式任务相关的前端文件；该接线留待统一处理。迁移报告新增 configMethods，对 edit 只给出 candidateContract，全部为 agent-required，不生成假热重载或 Settings 同名空实现。

验收：`core/tests/test_plugin_config_access.py`。覆盖缺失与 JSONC 读取、值副本、内容/schema 修订、基础校验、坏文档、内置路径、旧写入方、保存失败、停用代际、启动失败后持久状态、独立进程竞争和锁占用，以及真实桌面 SDK/管理入口互通。
