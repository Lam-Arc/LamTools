# 目录选择控制器的项目内浏览

user:“第二阶段结束后 就继续开展第三阶段”+(复用原已存在的项目内目录浏览，明确没有原生选择对话框)。

固定上游 [directory-picker.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/directory-picker.ts) 和[控制器手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/README.zh.md)已核对。上游根据实际native/browse capability提供pick、list和createDirectory；当前原宿主只提供browse。

`context.directory_picker_controller.capability()`返回browse；`await ...list(path=None, limit=100)`和`await ...create_directory(path, name)`调用原`context.directory_picker`，限定启动代固定项目根、本地固定磁盘和原路径检查。默认目录是当前项目而非上游home；原list先对所有条目计限、再只返回目录，可能出现截断且目录不足limit。根外、网络盘及已观察链接不开放；原路径校验不是抗恶意并发的原子文件系统边界。`await ...pick()`明确抛出`directory-picker/unavailable`，没有原生选择器或前端。

原同步browse在线程执行，取消包括重复取消后等待原操作完成再传播取消；创建可能已发生，调用方不能将取消当作回滚。绑定在结果/错误发布前复核；创建后绑定变化和无法确认的创建失败标记`may_have_changed=True`，已有目录的明确冲突除外。原错误投影为unreadable/exists/create-failed，非完整DSH RemoteError/details。线程正处于系统调用时不可强制抢占。

插件可明确声明token POST和http.remote，将自有处理器映射到本近似；未自动开放路由，也未实现Peer角色授权或DSH codec。13项新增验收使用临时目录和临时测试令牌，覆盖真实列举/创建、根外拒绝、错误、不可用native、重复取消及创建后变更、真实HTTP及迁移提示。DSH完整目录控制器、客户端和根外选择仍未完成。
