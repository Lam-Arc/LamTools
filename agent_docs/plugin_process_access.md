# 插件程序路径解析与环境构造

当前扩展：Windows 原生受管 spawn/run 与句柄已实现，见 [第二阶段运行能力](plugin_phase2_runtime.md#windows-原生受管进程)。本文保留 2n 解析/环境子集的规则，后文未覆盖的运行能力以扩展页为准。

user:“写好清单，逐项打勾完成，不要出错”+(进程能力按可验收子集推进，程序查找不代表启动、授权或完成运行)。

受管桌面 Python 插件在 start/on_load 中取得 `context.processes`，同步调用以下两项基础接口。它们只做宿主本地解析，不创建或执行子进程，不返回进程句柄，也不提供 Shell 执行。

```python
api = context.processes
program = api.resolve_executable("python", env={"PATH": "C:\\Python314"})
child_env = api.environment({"MY_OPTION": "enabled", "REMOVE_THIS": None})
# program 是 pathlib.Path，child_env 是只读 Mapping。
# 后续执行必须使用已完成审批和生命周期验收的路径；本接口不负责启动。
```

## 程序解析

`resolve_executable(command: str | Path, *, env=None) -> Path` 接受绝对程序路径或无目录分隔符的 PATH 名称。拒绝空值、首尾空白、NUL，以及带目录分隔符或盘符的相对路径。绝对路径验证给定文件，不自动追加扩展名；返回规范化绝对路径，允许解析符号链接。

裸名称按构造后的 PATH 顺序搜索，只使用绝对目录；空项、相对项和带引号而非真实绝对路径的项被跳过。不隐式搜索当前工作目录，不扩展环境变量或去掉引号。不提供 PATH 时不回退到宿主默认搜索路径。最多接受 256 个 PATH 项，超出抛错。

Windows 按 PATHEXT 顺序匹配，名称已有允许的扩展名时直接匹配。PATHEXT 缺失时使用 `.COM;.EXE;.BAT;.CMD`，显式无效值会报错；最多 32 个点开头的字母数字扩展名。找到文件不证明它是有效 Windows 可执行映像，也不会为 .cmd/.bat 或文件关联启动解释器。其他桌面平台验证普通文件及执行位。

程序路径可以位于项目外，没有目录隔离或授权含义。查找不锁定文件版本，文件可能在查找后被替换；调用方不能据此跳过执行时验证。访问网络路径等文件系统操作没有独立 I/O 截止时间，数量限制不等于时长保证。

## 环境构造

`environment(overrides: dict[str, str | None] | None = None) -> Mapping[str, str]` 每次复制当前进程环境，过滤名称中含 KEY/PASSWORD/SECRET/TOKEN 的条目及 DSH_/SUNDAY_/LAMTOOLS_ 前缀，均不区分大小写。它是命名启发式：可能过滤普通名称，也可能遗漏其他名称下的敏感值，不是密钥扫描或隔离边界。不会读取插件凭据库。

然后应用显式 overrides：字符串设置值，None 删除变量；显式提供的凭据名称允许通过。名称必须非空、不含等号/NUL，值不得含 NUL，全部需可编码为 UTF-8。最多 256 项显式覆盖，构造后环境按 UTF-8 键值总量计最多 1 MiB。Windows 合并时统一大写，避免 PATH/path 双重定义；其他平台保持大小写。

DSH_SUBPROCESS_CONTROL（含大小写变体）是保留标记，拒绝显式设置或删除，避免假装拥有未分配的控制管道。没有 DSH proxyEnvironmentForChild 的特殊覆盖处理；普通未过滤的代理变量按原环境复制。返回不可变映射，若未来启动接口需要 dict，需显式 `dict(child_env)`；不可变不代表日志脱敏，显式环境值仍可被调用者读取。

resolve_executable 的 env 是相同覆盖规则下的查找环境，不是完整替换环境，不能从已含超过 256 个键的 environment 返回值再直接作为 overrides 传入。需要精确查找时只覆盖 PATH/PATHEXT 即可。调用不会改写 os.environ，两次读取可观察到外部环境变化，不保证跨调用快照。

## 生命周期与错误

两项操作每次检查当前插件启动代；停用、启动失败清理或重启后旧接口失效，抛现有 ServiceError。未受管上下文不能取得接口。同步操作没有后台进程或任务需要清理，没有额外的取消协议。

从公开 SDK 导入 `ProcessAccessError`，按 `.code` 分支：process/invalid-command、invalid-environment、not-found、lookup-failed（均加 process/ 前缀）。消息不回显完整环境或底层异常，找不到程序不返回猜测路径。未提供进程退出码或成功执行标志，因为没有启动任何程序。

## DSH 移植边界

固定上游的 [subprocess 手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/subprocess/subprocess/README.md)与[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/subprocess/subprocess/src/index.ts)为基准。resolveExecutable 和直接调用 scrubbedParentEnv 可人工近似改为上述同步 API；PATH 处理、返回类型、宿主前缀、限额与代理处理有差异。

未实现 spawn、终端、stdin/stdout/stderr/control、输出读取/溢出文件、远程后端、terminate/waitForExit 或受管进程范围退出证明。shell.resolve/execute 也未实现，不能把 DSH 的异步句柄协议换成普通运行函数就声明兼容。现有命令执行器可作为后续复用候选，但不代表已经满足这些完整契约。

迁移报告新增 processMethods，所有方法保持 agent-required；解析和环境构造提供近似建议，执行/终端方法保留待办。[阶段清单](dsh_compatibility_checklist.md)中进程启动与回收继续不勾选。验收见 `core/tests/test_plugin_process_access.py` 与迁移测试。
