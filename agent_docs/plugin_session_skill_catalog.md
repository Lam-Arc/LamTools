# 会话技能目录近似接口

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(从真实可见会话执行目录和已安装原技能注册表取得用户可调用元数据)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[skill-catalog.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/skill-catalog.ts)以会话投影/原目录及预设作用域选择注册表，只返回user-invocable技能；冷会话不激活Agent，live目录可能ensure。

`await context.session_skill_catalog.list(session_id, limit=100)`先绑定应用原操作目录上的`command_skill_registry_factory`和`command_skill_state_store_factory`，任一缺失或返回无效提供方为session-skill/unavailable，不返回假空列表。原working_directory负责可见会话/项目/执行目录，其他项目拒绝；基于原SkillRegistry.available(执行目录)及SkillStateStore.snapshot过滤user_invocable=false或已停用项。原排序/磁盘技能优先级与运行时技能由原注册表决定，不新建注册表或账本。

结果为`{skills:[{name,description,model_invocable,path?}],truncated}`，limit整数1–500；内存技能无path。仅返回元数据，不提供正文。原SkillRegistry发现磁盘技能时可能同步读取技能文件及其正文；扫描开始后无法异步抢占，结果仅按limit截断，原注册表本身并无新的扫描限额。初次准入及发现后的会话复核等待可取消，取消释放作用域租约；目录宿主、项目根、操作目录、注册表工厂、状态工厂或启动代变化时拒绝旧结果。检查不是原子目录快照。

实际HTTP须插件原operations处理器显式调用并声明token POST与http.remote；真实SkillRegistry/SkillStateStore、会话SQLite及HTTP已验收，隐藏会话拒绝、不得返回技能正文。此近似无DSH standing preset scope、per-Agent替换注册表、live目录ensure/Agent恢复、whenToUse投影及生成codec；不能据此声称完整sessionSkillCatalog完成。

13项新增验收覆盖真实运行/磁盘技能、启用与用户调用策略、无提供方明确报错、结果限额、隐藏/跨项目会话、原宿主/目录/两工厂/启动代失效及取消、实际HTTP和迁移交接。SkillRegistry/SkillStateStore为测试中真实提供方实例；本批没有将未安装提供方标为已安装。

发现完成后重新核对原会话可见性、执行目录和原启用账本；目录改变或启用账本变化时拒绝旧结果，调用方可重试。新增6项验收覆盖真实注册表发现期间会话隐藏、最终读取中目录切换/取消、启用状态变化及真实HTTP隐藏拒绝；这些读取不是原子权限或文件系统锁。原注册表有共享可变缓存，本次未将其移到线程，故同步发现期间仍不能异步抢占。
