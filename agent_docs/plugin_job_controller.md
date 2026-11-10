# 当前插件的会话作业控制

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(在原插件作业和真实会话准入上提供受限控制，不冒充全局作业注册表)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[job-controller源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/job-controller/src/index.ts)和[中文手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/job-controller/README.zh.md)已核对。上游list是会话可见名册流，follow是单一绝对字节偏移的非消耗流，human kill保留通知及原因。

`await context.job_controller.list(session_id)`先经原working_directory验证可见会话及当前项目，返回当前插件本项目视图中的作业快照：会话标签相同或标签为None的作业。`read(session_id, job_id, stdout_after=0, stderr_after=0)`对同一范围按原两路独立字节偏移读取有界尾部，重复读取不消耗；`kill(session_id, job_id)`调用原插件作业stop/join并等待实际回调结束。其他插件视图、其他会话标签及未知作业均不可通过本控制器读取或停止；原作业session_id只是插件提供的字符串标签，不是DSH注册表的不可变Session所有权。None标签的当前插件作业可由当前项目任何可见会话访问。

返回原JobView/JobOutput数据类，可由显式http.remote映射经原JSON投影；输出bytes须选resultEncoding=multipart。实际原作业→插件处理器→HTTP快照和原始二进制附件、隐藏会话拒绝、重复读取不消耗均已验收。原缓冲最多各64KiB，偏移丢失标志保留。取消等待会话准入不执行作业操作；kill已派发后，重复取消调用者仍等待原回调真正退出，调用者收到取消不代表停止未发生。项目根/宿主/启动代撤回后拒绝旧结果。

此接口没有DSH跨插件全局作业注册表、无主作业的全局归属、事件驱动list/follow协议、单一混合字节游标、人工停止原因/通知语义或Peer资源lookup。kill会等待回调完成，区别于上游requested回执；无法强制退出不合作的插件回调。10项新增验收覆盖插件/会话隔离、无标签作业、非消耗读取、实际kill与重复取消收尾、四种准入期间失效/取消、真实HTTP/原字节与迁移交接。完整jobController仍待实现。


## 消费驱动的作业输出跟随

固定上游[job observe.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/job-controller/src/observe.ts)及[types.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/job-controller/src/types.ts)以opened/output/status和单一绝对偏移实现事件驱动、非消耗观察。

`context.job_controller.follow(session_id, job_id, stdout_after=0, stderr_after=0, interval=0.1)`返回异步迭代器：先opened携带原JobView，后续output以标准base64携带stdout/stderr原字节、各自绝对offset及lost标记；原作业完成且输出排空后发送status及原JobView并结束。interval须为0.01–2秒的有限数值。每次poll复用原非消耗read、原可见会话及插件作业标签检查；截断/重连使用两路原始字节偏移，非上游单一混合偏移。慢消费者没有后台生产队列，消费期间原有界尾部仍可能截断并显示lost；无新长期线程/观察任务。

插件自身原处理器可返回OperationResult(name, stream)并明确声明resultEncoding=ndjson；HTTP响应中base64是流帧的明确近似编码，不是DSH原生二进制帧/codec。取消等待或HTTP断连关闭观察器，不停止原作业；插件停用仍由原作业所有者回收。事件名/字段、poll、双路游标和裁剪与DSH事件驱动follow不同，没有自动全局名册流或human kill通知。

12项新增验收覆盖真实作业opened/output/status、二进制与非消耗读取、五种无效间隔、其他会话拒绝、取消不停止作业、环形缓冲丢失/续读、标签变更后拒绝、真实NDJSON完整流与断连回收、迁移交接。


## 当前插件名册变化流

`context.job_controller.watch_list(session_id, interval=0.1)`消费驱动轮询，先发送完整当前可见快照，后续仅在快照变化时发送；每次轮询重新检查原会话和项目。间隔为0.01–2秒，期间多次变化可能合并，无法保证观察每个中间状态。快照中的可变结果与内部比较副本隔离。取消或HTTP断连停止观察，不停止原作业。显式NDJSON映射已验证；这是当前插件视图的轮询近似，非上游事件驱动的跨插件全局名册。11项新增验收覆盖增删、完成、隔离、撤回、取消、快照修改、无效间隔、实际HTTP断连和迁移提示。
