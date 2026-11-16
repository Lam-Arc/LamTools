# 会话执行目录受管终端管道

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(按真实会话目录启动原受管进程，明确非PTY与生命周期差异)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[terminal-controller源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/terminal-controller/src/index.ts)和[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/terminal-controller/README.zh.md)已核对。上游终端是Session拥有的真实PTY，支持shell profile、retain/attach、resize、屏幕恢复与双向输入，Session和控制器释放会回收进程。

`await context.terminal_controller.environment(session_id)`复用原working_directory可见性、项目和执行目录，返回session_id/cwd/cwd_exists/pty=false；当前实现会检查目录存在状态，上游environment不检查文件系统。该元数据方法经明确插件token POST/http.remote真实HTTP验收，隐藏会话及其他项目被拒绝。

`await context.terminal_controller.open(session_id, argv, timeout=..., env=None, max_output_bytes=65536)`先取得同一可见会话的原执行目录，目录不存在拒绝，再调用原`context.terminals.open`及Windows Job受管进程，返回原PluginTerminal对象，支持send/read/wait/close；stdin/stdout/stderr为管道，`pty=False`。真实Windows Python进程验收了当前目录、交互输入/输出和close等待实际回收。原插件启动代停用会回收进程；该原对象没有持久会话终端ID、DSH即时Session销毁事件、PTY尺寸、shell探测/配置、retain/attach、多窗口控制权、屏幕重放、双向Remote或自动HTTP创建。不能把PluginTerminal对象当作JSON或DSH WebTerminal。

会话准入等待期间可取消；根/宿主/启动代失效不启动进程。若真实进程启动后而结果交付前绑定失效，控制器先close/join原进程再传播错误；Windows原进程启动取消/资源管理仍由OwnedProcess负责。不强制终止不合作的系统调用或把管道当PTY。只有显式插件原处理器可映射环境查询，用户命令能力与原受管进程的权限相同，不自动开放命令路由。

10项新增验收覆盖可见会话实际执行目录、隐藏/跨项目拒绝、真实进程交互和回收、四种准入失效/取消、启动后宿主撤回实际回收、真实HTTP环境及迁移交接。完整terminalController仍未完成。

原受管进程启动后、交付PluginTerminal前再次经过原会话准入并对比执行目录；会话隐藏/删除、目录变化或最终准入被取消时先关闭并等待该进程，再传播错误/取消。新增4项验收使用真实临时Windows Python进程，覆盖会话隐藏、目录变化、正常返回及最终准入期间重复取消等待真实回收。交付后的轮询回收行为以本页后续章节为准；检查并非跨进程原子权限锁。

## 交付后的会话寿命

每个存活的原受管终端以约0.2秒间隔复用原可见会话/当前项目准入；会话删除、隐藏、迁移或原宿主失效时关闭并等待原进程回收。自然退出后移除监视任务；插件启动代清理等待监视和原进程结束，同一启动代只注册一份监视清理器。原会话执行目录变化不重新定位已启动进程。读取阻塞时停用等待原检查退出；轮询受调度与读取耗时影响，不是即时删除事件或原子权限锁，失效到检测期间句柄仍可能可用。7项新增验收使用真实临时Windows进程覆盖删除、隐藏、迁移、自然退出、启动代清理、在途读取和目录变化。PTY、DSH终端身份/retain/attach/resize及双向协议仍未完成。

## 显式远程受管管道

`create_pipe(session_id, argv, timeout=..., env=None, max_output_bytes=65536)`调用原受管进程并返回当前插件启动代内的随机ID，`pty=false`；最多保留32个句柄，输出尾部每路最多262144字节。`send_pipe(session_id, id, data, timeout=5)`接收标准base64，解码最多16 KiB，返回实际写入字节数；`read_pipe`以独立stdout/stderr字节游标返回base64尾部、丢失和完成状态；`close_pipe`关闭并等待原进程回收，重复取消不截断清理。输入后会话失效或句柄变化时报告`terminal/write-uncertain`及`may_have_changed=True`，取消不保证输入未送达。

句柄限定当前插件代和原可见当前项目会话；失效轮询与启动代释放沿上节回收，失效会话仍可用相同会话ID关闭自己已持有的句柄。已退出句柄保留输出直到显式关闭或启动代结束，限额满时拒绝；插件必须显式声明token Remote方法，不自动开放命令。10项新增验收使用真实临时Windows进程及实际Remote覆盖交互、作用域、无效输入/限额、发送后失效、重复取消和清理。固定上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/terminal-controller/src/index.ts)提供真实PTY、调用方ID、retain/双向attach/resize及幂等close；本接口为轮询管道，关闭重试近似见下文，不实现完整PTY或Peer权限。

## 受管管道输出流

`follow_pipe(session_id, id, stdout_after=0, stderr_after=0, interval=0.1)`按消费节奏轮询原受管管道，先发`opened`，再发包含base64双路字节、独立游标和丢失标记的`output`，完成后发`end`。interval限0.01–2秒，每次读取前重新核对原会话/项目及句柄；开场之后会再次读取，避免先缓存的数据在会话撤回后发布。观察流关闭、取消或显式NDJSON断连不停止进程，句柄可继续读取或显式关闭；启动代及会话失效回收规则不变。14项新增验收使用真实临时Windows进程覆盖正常结束、旧游标丢失、隐藏/关闭/取消、参数、实际NDJSON断连与迁移。此流不是上游PTY、屏幕状态或双向attach；输入仍单独调用`send_pipe`，无DSH wire/Peer语义。

## 当前插件会话管道列表

`list_pipes(session_id)`经原会话和当前项目准入后，只返回当前插件启动代在该会话持有的管道随机ID、`pty=false`与完成状态；已退出句柄保留至显式关闭或启动代清理。读取不返回输出、命令或本机路径，不启动或停止进程；重复取消等待准入清理。5项新增验收使用真实临时Windows进程覆盖不同会话隔离、退出及关闭、隐藏会话、撤回/取消、认证HTTP和迁移。

固定上游`terminal.list`返回宿主为会话保留的真实PTY和完整终端信息，可用于离线会话；本接口只列本插件代的非PTY句柄，要求原会话可见，不支持跨插件、离线会话、上游终端元数据或Peer协议，准入与进程状态读取非原子。

终端环境、管道读取/输入/跟随和启动期间的会话准入被重复取消时，会等待原会话读取的清理结束后再传播取消。若进程已经启动，还须等待真实进程回收，不能把已取消调用交付为成功句柄；不合作的原读取可能延迟结束。新增验收覆盖六种入口、真实认证Remote、正常可见性，以及真实Windows进程启动后的重复取消与回收。

## 当前环境shell候选

`shells(session_id)`先后复核原可见会话和当前项目，使用同一原受管进程提供方对固定Windows `cmd.exe`、`pwsh.exe`、`powershell.exe`执行PATH程序解析，仅列实际解析到的原生文件及建议参数。缺失项跳过，其他解析错误明确传播；空目录返回空列表，默认项为null，`pty=false`。此方法不启动进程，因此找到文件不保证程序能启动或提供PTY；同步路径解析开始后不能异步抢占，重复取消等待在途会话准入清理。

8项新增验收覆盖实际系统shell解析、缺失及原提供方错误、隐藏/撤回、重复取消、认证HTTP和迁移。固定上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/terminal-controller/src/shells.ts)使用执行提供方声明的默认shell、可配置候选及远程环境；本接口不探测默认项、不提供自定义profile或远程执行环境，不能冒充PTY。

## 已拥有管道的关闭重试

`close_pipe`等待原进程真实回收后保留最近128条该插件启动代、会话及随机ID的关闭记录；同一会话重复关闭这些ID成功，不存在、其他会话或已淘汰ID仍拒绝。清理失败保留原句柄供重试，并发调用等待实际进程；重复取消等待回收后传播取消。关闭期间持有启动代租约，停用等待关闭并清空记录。8项新增验收覆盖真实Windows进程、重复/并发、失败后重试、重复取消、启动代停用、容量、认证HTTP及迁移。上游close还封闭调用方指定ID的未来创建、支持未见ID且Session所有权不同，此接口非完整上游幂等协议。
