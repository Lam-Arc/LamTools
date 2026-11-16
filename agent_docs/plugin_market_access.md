# 插件市场只读目录

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(复用原市场真实目录、缓存和安装状态，不伪造配置型上游市场)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[plugin-market源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/boot/plugin-market/src/index.ts)和[中文手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/boot/plugin-market/README.zh.md)已核对。上游默认不配置索引，支持配置多个索引、搜索分页、兼容性及详情；安装委托pluginManager。

固定上游Remote方法为`listIndexes()`、`setIndexes(urls)`、`search(url, query)`、`readEntryDetail(url, name, version, language, options)`；内部`entry(url, name)`不是Remote。`setIndexes`会写入profile设置并发出变更事件；`search`返回索引声明、`fetchedAt`、默认版本、逐版本兼容性/安装参数和分页；`readEntryDetail`按版本来源访问npm文件CDN或Git仓库，另有认证连接上的详情图片路由。Sunday没有原索引设置、DSH索引/版本模型或详情读取器，故当前只把查询映射到固定官方目录，没有映射设置写入或任意URL详情读取。不能把调用方URL直接交给HTTP/Git；未来接入必须建立明确来源/出站策略、大小与期限限制、凭据隔离、取消和清理验收。

`await context.plugin_market.list()`只调用原`plugin.market.list`，复用Sunday固定官方GitHub发布目录校验、安装状态和缓存；不提供安装/更新，不接收用户指定URL。返回原`plugins/source/error`，原目录当前固定QQ robot和刷B站两个候选，是否可安装取决于实际有效发布目录。网络及缓存均不可用时原provider返回source=unavailable、各项installable=false和错误；这不是已安装或可用服务的假成功。若原操作未安装，明确host/unavailable。

读取绑定插件启动代和原操作目录，返回前复核；请求取消（包括重复取消）后等待原查询及其工作线程真正退出，再释放租约，可能仍发生原只读缓存更新。原网络请求沿用distribution每次请求超时和回退策略，没有承诺整个查询的严格总时限。插件可以在自身operations处理器明确调用，再声明token POST/http.remote；脚本不自动创建路由或配置上游索引。

8项新增验收使用受控GitHub响应/临时目录，实际执行原目录校验、缓存、主机安装状态与HTTP映射；覆盖无provider、网络不可用不能冒充可安装、启动代/原目录撤回和重复取消等待真实线程。测试没有安装插件，也没有验证实际互联网服务健康。DSH自定义索引、search分页、逐版本兼容/详情、安装及Peer/codec仍未完成。


## 原固定目录搜索

`context.plugin_market.search(text="", offset=0, limit=50, category=None)`调用同一原目录，在id、标题、分类、描述及能力上按NFKC规范化并忽略大小写做完整子串匹配，按原目录顺序分页；offset为非负安全整数，limit为1–100，文本最多200字符。返回items、total、next_offset和原source/error，原安装状态不被改写。每次分页各自读取原目录，跨页期间目录或安装状态可变化，没有固定快照；不支持上游分词、模糊排名、标签过滤、配置多索引或详情。

15项新增验收覆盖真实原目录与分页、无效参数、不可用状态、真实HTTP、撤回/重复取消等待原工作线程和迁移提示。网络由受控响应替代，未安装插件，不能据此声称真实互联网可用或整个pluginMarket完成。

## 原固定目录精确条目

`await context.plugin_market.entry(name)`按大小写精确匹配原目录id，返回`item`（未找到为null）及原`source/error`。它沿用list的启动代检查和取消结算，不安装插件；上游`entry(url, name)`不是Remote方法且支持已配置索引，此处没有索引参数、版本兼容投影或详细介绍。8项新增验收覆盖真实原目录、缺失和参数拒绝、明确HTTP、缓存及不可用状态；网络响应受控。

另3项新增验收直接验证entry在重复取消、启动代撤回和原操作目录替换时等待原读取线程结束，不发布旧条目。

## 原固定索引来源

`await context.plugin_market.list_indexes()`仅在原`plugin.market.list`由plugin-system挂载且当前作用域有效时，返回原市场固定`CATALOG_URL`；缺提供方或归属不符明确拒绝。此查询不访问网络，不表示目录健康或包可安装；原市场实际先尝试同一GitHub发布的API资产，失败再回退此URL。5项新增验收覆盖原提供方、无提供方/错误归属、作用域与目录替换、显式Remote和迁移，不安装插件。上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/boot/plugin-market/src/index.ts)允许多个配置来源及缓存标题/错误，此处只报告固定来源，不提供配置、缓存元数据或Peer协议。

市场`list/search/entry`调用原操作前后也检查`plugin-system`归属；不同所有者不能冒充原市场，读取期间归属撤回不会发布旧结果。5项新增验收覆盖三种入口、在途替换及真实Remote，所有网络数据受控。归属和原注册身份检查不是跨线程原子锁。

原操作目录为每次注册分配不透明身份；市场读取在异步派发开始前及完成后核对身份，因此同所有者重新注册也不会被当作原操作。4项新增验收包含受控原市场、派发前替换不执行新处理器、等待中替换、正常读取及真实Remote。身份检查不提供跨线程原子锁。

可选`category`在分页前以NFKC和大小写折叠精确匹配原目录的分类显示名称，与文本条件同时生效；未匹配返回空页并保留原来源、错误及安装状态。11项新增验收覆盖真实原目录、分类/文本/分页、无效参数先拒绝、离线状态、重复取消、认证HTTP及迁移，网络响应受控且未安装插件。固定上游按索引声明的分类ID过滤，本目录只有显示名称，不支持上游分类ID、标签、模糊排序或稳定索引快照。

## 固定首次结果的分页

`search_snapshot(text="", category=None, offset=0, limit=50, snapshot=None)`首次通过原市场操作读取并过滤完整实际目录，返回不透明`snapshot`及分页；后续以相同文本和分类传回令牌继续读取首次结果，不重新访问网络。每个插件启动代最多16份、每份最多100条、120秒过期，过期/淘汰/查询不匹配明确拒绝，启动代结束清空。原市场操作撤回、替换或归属变化也拒绝旧快照；取消首次读取等待原线程清理。返回数据使用副本，来源及错误取首次实际结果。

目录快照只固定首次过滤得到的目录行、顺序、来源和错误；每页另通过原`plugin.system.list`刷新安装版本及更新状态，不重新读取市场目录。安装状态只是展示信息，不是安装授权；实际安装仍须原宿主检查。上游`fetchedAt`会保留索引文档快照并逐页重新计算安装状态，本接口复用了逐页刷新语义，但没有多索引、详情和其余协议。新增验收覆盖目录不重读而安装状态刷新、原插件清单提供方缺失/归属或绑定替换时拒绝发布；共4项。

首次分页在安装状态读取、结果组装和市场提供方复核成功后才发布快照；失败或取消不会因容量挤掉尚未过期的旧快照。读取旧页等待安装状态期间，若原快照已过期或被其他成功请求淘汰，则拒绝发布旧页；市场提供方替换也拒绝结果。此检查并非跨线程原子锁。新增验收覆盖错误、取消、淘汰、过期、提供方替换、真实认证Remote错误及迁移交接。
