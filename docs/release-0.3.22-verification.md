# Sunday 0.3.22 发布验收记录

- 最终发布提交：`1e6ad19793470685abf9cec932946ffce6615fb8`；标签：`v0.3.22`。
- 正式构建：https://github.com/Lam-Arc/LamTools/actions/runs/39921045564
- 发布页：https://github.com/Lam-Arc/LamTools/releases/tag/v0.3.22
- 初次构建 39920018659 在发现快照重复进入历史后主动取消，取消完成且确认不存在 Release 后，按发布故障恢复指南撤回未发布标签并重新创建。最终标签指向修正提交。没有覆盖已公开的安装包。

## 代码与文档验收

- 新增相关检查：21 项后端、8 项前端通过；没有运行全量测试。
- 包含自动和手动完整流程、同任务再次压缩、取消、数据库重开、事务回滚、旧数据库空尾部、子代理结果晚到、系统前缀和快照不会重复进入历史。
- 原始记录持续追加；SQLite 在同一事务提交摘要、系统基线和完整快照。
- 保留真实 usage 优先与一拍延迟；本地估算统一乘 2.5，卡片显示最新后端占用。
- Wiki 更新 compaction.md、resource-usage.md；结构、目录和本地链接验证通过（77 个词条）。既有 Wiki 草稿保持在工作区，没有把整个无关草稿库打进代码发布提交。
- 样式参考：实际读取 Wikipedia Cache (computing) 和 Factorio Wiki Steel chest；Terraria 参考页无法访问，使用 Factorio 同类条目替代。

## 安装与更新验收

- 最终本地安装目录：`E:\setuptest\0.3.22`；最终安装验收主进程 13292、后端 20532，均来自该目录。
- 项目读取、设置供应商添加/读取/删除通过。使用占位密钥和本地无效地址，没有调用真实模型。
- 本地构建和 CI 构建独立；官网发布使用 CI 安装包，确保 GitHub 与官网下载一致。
- 安装包 SHA-256：`2c01a3bc56531fbd908eede47007bc6d7075493775eceba5ee105d87b86cc62c`；字节数：73556550。
- 构建日志：`data/core-agent/release-0.3.22-build-final.log`。
- 安装/API 证据：`release-0.3.22-local-install-final.txt`、`release-0.3.22-api-acceptance.json`。

### release-0.3.22-public-update.log

```text
Update-channel acceptance against https://ainarit.com
Scratch install: E:\setuptest\update-0.3.22
1. read the published manifest
  ok: manifest names a version (0.3.22)
  ok: manifest points at an https download (https://ainarit.com/downloads/Sunday_0.3.22_x64-setup.exe)
  ok: manifest carries a sha256
  ok: manifest carries a size (73556550 bytes)
2. download the installer and verify it like the app does
  downloaded 73556550 bytes, sha256 2c01a3bc56531fbd908eede47007bc6d7075493775eceba5ee105d87b86cc62c
  ok: downloaded size matches the manifest
  ok: downloaded bytes match the manifest digest
3. install it the way the in-app update does (silent + auto restart)
  ok: the installer exited 0 (got 0)
  ok: the installed application is in place
4. the setup must have started the application again
  ok: the application was started again by the setup (pid 47764)
  ok: the restarted application reports a healthy backend (port 61482)
Update-channel acceptance passed for 0.3.22
```

### release-0.3.22-update-check.json

```text
{
  "current_version": "0.3.22",
  "latest_version": "0.3.22",
  "source": "site",
  "notes_source": "site",
  "status": "up_to_date"
}
```

### release-0.3.22-dev-restored.json

```text
{
  "verified_utc": "2026-10-23T08:15:25.8467936Z",
  "port": "62042",
  "app_path": "E:\\LamTools\\core\\desktop\\src-tauri\\target\\debug\\lamcore.exe",
  "app_pid": 26476,
  "status": "ok"
}
```

## 服务器操作审计

服务器：cn-hangzhou / i-bp10t7y63rvbncmjstpm / 47.114.43.99。使用 default / codexlam，CLI 已通过 Get-Command 验证。
逐项操作和结果如下；时间均为 UTC，来自云端命令输出或本地回执完成时间。每个 Cloud Assistant 命令 KeepCommand=true。

| 操作 | 类型 | 完成 UTC | 结果 | RequestId / CommandId / InvokeId |
| --- | --- | --- | --- | --- |
| Sunday-0.3.22-publication-preflight | 只读检查 | 2026-10-23T07:46:53+00:00 | Success / 0 | 01A167BA-0F3F-582C-A9D2-023841867F3E / c-hz070vz1a2r8hkw / t-hz070vz1a33pzb4 |

```text
Fri Oct 23 07:46:50 AM UTC 2026
{
  "version": "0.3.21",
  "download_url": "https://ainarit.com/downloads/Sunday_0.3.21_x64-setup.exe",
  "release_url": "https://ainarit.com/sunday.html",
  "release_notes": "Sunday 0.3.21",
  "published_at": "2026-10-23T06:05:31Z",
  "sha256": "94ca39361693495125b77e32f52fe5752ef393272ef33101f99d0b1e732a3e9f",
  "size": 73555367,
  "linux_version": "0.3.21"
}
/var/www/lamtools/site-releases/0.3.21-mobile-0.1.48-20261023
active
active
Filesystem      Size  Used Avail Use% Mounted on
/dev/vda3        40G   15G   23G  39% /
authorized key count: 1
```

| Sunday-0.3.22-authorize-temporary-transfer | 修改 | 2026-10-23T07:47:41+00:00 | Success / 0 | 01A167BA-CE15-5D65-88F9-6C6C73A506DA / c-hz070vz3vvph4hs / t-hz070vz3vvrz0u8 |

```text
Fri Oct 23 07:47:38 AM UTC 2026
authorized key count after append: 2
```

| Sunday-0.3.22-stage-site | 修改 | 2026-10-23T07:48:17+00:00 | Success / 0 | 01A167BB-5A79-50F6-88EC-E351E057A06F / c-hz070vz5t61kvls / t-hz070vz5t66koao |

```text
Fri Oct 23 07:48:14 AM UTC 2026
afff86c64aaf8c133f2744cfccf09ecd5611757c963a6cb2f8ff374e1d07fb07  /tmp/release-0.3.22-site.tar.gz
/var/www/lamtools/site-releases/0.3.22-mobile-0.1.48-20261022/assets/preview-BaHfxV8Y.js
/var/www/lamtools/site-releases/0.3.21-mobile-0.1.48-20261023
```

| Sunday-0.3.22-preserve-Linux-downloads-during-release | 修改 | 2026-10-23T07:52:00+00:00 | Success / 0 | 01A167BE-C108-523A-A8E6-5702976EA7CF / c-hz070vzhqnokcg0 / t-hz070vzhqnyjxts |

```text
Fri Oct 23 07:51:57 AM UTC 2026
https://github.com/Lam-Arc/LamTools/releases/download/v0.3.21/Sunday_0.3.21_amd64.AppImage
https://github.com/Lam-Arc/LamTools/releases/download/v0.3.21/Sunday_0.3.21_amd64.deb
active
active
```

| Sunday-0.3.22-publish-Windows-channel | 修改 | 2026-10-23T08:11:41+00:00 | Failed / 1 | 01A167D0-C407-578A-A89D-42C66FAE18A8 / c-hz070w18xa1ff9c / t-hz070w18xabf0n4 |

```text
Fri Oct 23 08:11:38 AM UTC 2026
Traceback (most recent call last):
  File "<stdin>", line 6, in <module>
AttributeError: module 'hashlib' has no attribute 'file_digest'
```

| Sunday-0.3.22-publish-Windows-channel-retry | 修改 | 2026-10-23T08:12:05+00:00 | Success / 0 | 01A167D1-23BC-5B41-A5B0-70676E636890 / c-hz070w1a8a35p8g / t-hz070w1a8a85hxc |

```text
Fri Oct 23 08:12:02 AM UTC 2026
2c01a3bc56531fbd908eede47007bc6d7075493775eceba5ee105d87b86cc62c  /var/www/lamtools/Sunday_0.3.22_x64-setup.exe
2c01a3bc56531fbd908eede47007bc6d7075493775eceba5ee105d87b86cc62c  /var/www/lamtools/Sunday-latest-x64-setup.exe
{
  "version": "0.3.22",
  "download_url": "https://ainarit.com/downloads/Sunday_0.3.22_x64-setup.exe",
  "release_url": "https://ainarit.com/sunday.html",
  "release_notes": "Sunday 0.3.22\n\n- 统一自动压缩和手动 `/compact` 的上下文测量、保存与恢复流程。\n- 优先使用真实 usage；缺失时用 2.5 倍本地估算，允许一次请求的延迟。\n- 同一次任务内再次达到阈值仍可压缩，无需补发用户消息。\n- 保留原始历史，压缩后的新工作继续逐步保存；数据库恢复和取消更可靠。\n- 系统提示与运行时状态一起计入预算，状态快照不重复进入历史。\n- 右侧卡片显示后端最新占用，不再复用旧模型和旧片段的读数。\n\n验证：21 项新增后端检查和 8 项新增前端检查通过；未运行全量测试。安装、升级与自动更新另经发布验收。",
  "published_at": "2026-10-23T08:10:49Z",
  "sha256": "2c01a3bc56531fbd908eede47007bc6d7075493775eceba5ee105d87b86cc62c",
  "size": 73556550,
  "linux_version": "0.3.21"
}
active
active
```

| Sunday-0.3.22-remove-temporary-transfer-key | 修改 | 2026-10-23T08:13:06+00:00 | Success / 0 | 01A167D2-1789-5F01-8D3E-700D9A327DC5 / c-hz070w1dkie7s3k / t-hz070w1dkij7ksg |

```text
Fri Oct 23 08:13:05 AM UTC 2026
before key count: 2
after key count: 1
```


### 每项修改的范围

1. 临时上传授权：备份 /root/.ssh/authorized_keys，追加本任务公钥；传输结束后精确移除此公钥，保留其他授权。
2. 上传暂存：通过专用 SSH 公钥传输站点归档、同步脚本、CI 安装包和清单到 /tmp；Cloud Assistant 检查并部署。
3. 未公开站点暂存：新建 /var/www/lamtools/site-releases/0.3.22-mobile-0.1.48-20261022，旧站点目录不变。UI 内容与初始 6f9d01dd 提交一致；最终补丁只修改后端及验收，没有改动该 UI 构建。
4. 保持旧 Linux 下载：在新 Windows Release 生成前，把 ainarit.com 的旧 Linux 链接固定到 v0.3.21，避免 latest 临时指向不含旧包的新 Release。
5. Windows 频道：备份旧清单和 latest 安装包，发布 Sunday_0.3.22_x64-setup.exe，原子替换 latest 硬链接及 desktop-update.json；移动端不变。
6. 官网同步：Linux 文件可下载后，更新清单 Linux 版本、固定 Linux 下载链接到 v0.3.22、切换 site 符号链接、运行同步脚本更新 sunday.html 与预览；脚本保存页面与预览 tar 备份。
7. 清理临时上传公钥：从授权文件移除本任务精确公钥行，验证不再存在；不替换其他人的授权。

### 验证与回退

- 原始回执和完整操作命令：`data/core-agent/release-0.3.22-cloud-audit.jsonl`。
- Windows 备份：/var/backups/ainarit/release-0.3.22/desktop-update.json、Sunday-latest-x64-setup.exe。
- 原页面备份：同目录 sunday-before-pin.html 与 sunday-before-final.html；最终页面和预览 tar 的精确文件名见上方同步输出。
- 旧 site 目标：/var/www/lamtools/site-releases/0.3.21-mobile-0.1.48-20261023。
- 回退：恢复备份清单和 latest 安装包，site 链接切回旧目录，再从页面/预览备份恢复对应文件。新版本文件可保留，不影响旧频道。
- 临时授权备份：/root/.ssh/authorized_keys.before-sunday-0.3.22。若需重新传输，应重新授权任务公钥，不覆盖整个 authorized_keys。
- 服务检查：Caddy 与 relay 必须保持 active；公开下载 HTTP、尺寸与 SHA-256、站点同步和自动重启均在回执中记录。
- 官网源码 Download.vue 默认版本仍为 0.3.20，本次通过构建参数发布 0.3.22。
