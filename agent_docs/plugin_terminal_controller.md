# 会话执行目录受管终端管道

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(按真实会话目录启动原受管进程，明确非PTY与生命周期差异)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[terminal-controller源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/terminal-controller/src/index.ts)和[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/terminal-controller/README.zh.md)已核对。上游终端是Session拥有的真实PTY，支持shell profile、retain/attach、resize、屏幕恢复与双向输入，Session和控制器释放会回收进程。

`await context.terminal_controller.environment(session_id)`复用原working_directory可见性、项目和执行目录，返回session_id/cwd/cwd_exists/pty=false；当前实现会检查目录存在状态，上游environment不检查文件系统。仅此元数据方法经明确插件token POST/http.remote真实HTTP验收，隐藏会话及其他项目被拒绝。

`await context.terminal_controller.open(session_id, argv, timeout=..., env=None, max_output_bytes=65536)`先取得同一可见会话的原执行目录，目录不存在拒绝，再调用原`context.terminals.open`及Windows Job受管进程，返回原PluginTerminal对象，支持send/read/wait/close；stdin/stdout/stderr为管道，`pty=False`。真实Windows Python进程验收了当前目录、交互输入/输出和close等待实际回收。原插件启动代停用会回收进程；没有独立会话终端ID、Session销毁驱动回收、PTY尺寸、shell探测/配置、retain/attach、多窗口控制权、屏幕重放、双向Remote或自动HTTP创建。不能把PluginTerminal对象当作JSON或DSH WebTerminal。

会话准入等待期间可取消；根/宿主/启动代失效不启动进程。若真实进程启动后而结果交付前绑定失效，控制器先close/join原进程再传播错误；Windows原进程启动取消/资源管理仍由OwnedProcess负责。不强制终止不合作的系统调用或把管道当PTY。只有显式插件原处理器可映射环境查询，用户命令能力与原受管进程的权限相同，不自动开放命令路由。

10项新增验收覆盖可见会话实际执行目录、隐藏/跨项目拒绝、真实进程交互和回收、四种准入失效/取消、启动后宿主撤回实际回收、真实HTTP环境及迁移交接。完整terminalController仍未完成。

原受管进程启动后、交付PluginTerminal前再次经过原会话准入并对比执行目录；会话隐藏/删除、目录变化或最终准入被取消时先关闭并等待该进程，再传播错误/取消。新增4项验收使用真实临时Windows Python进程，覆盖会话隐藏、目录变化、正常返回及最终准入期间重复取消等待真实回收。交付后会话销毁仍不会自动回收该终端；检查并非跨进程原子权限锁。
