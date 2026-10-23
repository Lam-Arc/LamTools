# Sunday 0.3.21 发布验收记录

- 发布提交：`f8ac4a27243185dce09c9ffb89665578b69ad509`；标签：`v0.3.21`。
- GitHub：https://github.com/Lam-Arc/LamTools/releases/tag/v0.3.21
- 构建：https://github.com/Lam-Arc/LamTools/actions/runs/39907803416
- Windows 构建耗时：13 分 17 秒；安装、升级、卸载、保留数据和自动重启检查成功。
- 正式 Windows 安装包：`Sunday_0.3.21_x64-setup.exe`，73555367 字节。
- SHA-256：`94ca39361693495125b77e32f52fe5752ef393272ef33101f99d0b1e732a3e9f`。
- 本地构建仅用于初验；公开渠道使用 GitHub CI 安装包。

## 本地验收

- 安装位置：`E:\setuptest\0.3.21`；文件版本 0.3.21。
- 首次启动主进程 42408、后端 35420，均来自隔离安装目录。
- 已通过项目读取和真实设置接口供应商添加、读取、删除。测试使用占位密钥和本地无效地址，没有调用外部模型。
- 开发版曾被另外启动，导致单实例互斥；关闭该开发进程后完成真实安装版验收。
- 原始证据：`data/core-agent/release-0.3.21-local-install.txt`、`release-0.3.21-api-acceptance.json`。

## 公共更新与官网

- 更新检测已返回 site / 0.3.21 / up_to_date。
- 公开更新验收：见 `data/core-agent/release-0.3.21-public-update.log`，已通过：73555367 字节和 SHA-256 一致，静默安装退出 0，自动重启主进程 23688，后台端口 49175 健康。
- 官网预览从当前源码构建；入口添加发布版本和提交的注释标记，方便核对线上实际版本。
- 移动端 0.1.48 保持不变。

## 服务器审计

资源：阿里云 cn-hangzhou / `i-bp10t7y63rvbncmjstpm` / 47.114.43.99。
所有命令使用 Cloud Assistant，KeepCommand=true；以下逐项记录。传输只使用任务专用 SSH 公钥。

| 操作 | UTC 证据时间 | 结果 | RequestId / CommandId / InvokeId |
| --- | --- | --- | --- |
| Sunday-0.3.21-authorize-transfer | 2026-10-23T05:50:50+00:00 | Success / 0 | 01A1674F-D3D4-524E-92F5-56E1D203DA41 / c-hz070voon3weww0 / t-hz070voon46ei9s |

```text
authorized key lines: 2
```

| Sunday-0.3.21-linux-channel-inspection | 2026-10-23T06:01:24+00:00 | Success / 0 | 01A16759-7E4A-5981-AD69-3B8695928383 / c-hz070vpmjorr400 / t-hz070vpmjowqwow |

```text
Fri Oct 23 06:01:21 AM UTC 2026
Sunday_0.3.20_amd64.AppImage
Sunday_0.3.20_amd64.deb
drwxr-xr-x 2 root root 4096 Oct 15 09:54 /var/backups/ainarit
lrwxrwxrwx 1 root root   61 Oct 15 09:53 /var/www/lamtools/site -> /var/www/lamtools/site-releases/0.3.20-mobile-0.1.48-20261015
{
  "version": "0.1.48",
  "download_url": "https://47.114.43.99.nip.io/downloads/Sunday-mobile-latest.apk",
  "release_url": "https://47.114.43.99.nip.io/#download",
  "release_notes": "Sunday Mobile 0.1.48",
  "sha256": "fc18f4c0676822d52884b490a2beb196ea3fb978dc4640e4e8acfc8904f5684a",
  "size": 60826900
}
```

| Sunday-0.3.21-publish-site-and-preview | 2026-10-23T06:12:50+00:00 | Success / 0 | 01A16763-E653-523C-9455-0177706D7F0E / c-hz070vqn1rrr56o / t-hz070vqn1rwqxvk |

```text
Fri Oct 23 06:12:43 AM UTC 2026
published channel: desktop 0.3.21, mobile 0.1.48, Linux 0.3.21
backups: /var/backups/ainarit/sunday-before-20261023T061247Z.tar.gz /var/backups/ainarit/ainarit-preview-before-20261023T061247Z.tar.gz
page stamped for desktop 0.3.21 / mobile 0.1.48 / Linux 0.3.21: sunday.html
active
active
live: https://ainarit.com/sunday.html reads 0.3.21 / 0.1.48; /preview/ serves /preview/assets/preview-4RRA2anN.js
published channel: desktop 0.3.21, mobile 0.1.48, Linux 0.3.21
public site already in step
HTTP/2 200 
accept-ranges: bytes
alt-svc: h3=":443"; ma=2592000
content-type: application/octet-stream
etag: "dmbzpze7iv8617sjon"
last-modified: Fri, 23 Oct 2026 06:06:10 GMT
server: Caddy
vary: Accept-Encoding
active
active
```

| Sunday-0.3.21-publish-Windows-channel | 2026-10-23T06:06:12+00:00 | Success / 0 | 01A1675D-E2D2-5CFB-819D-F75A1185D908 / c-hz070vq1yfcgohs / t-hz070vq1yfhgh6o |

```text
Fri Oct 23 06:06:09 AM UTC 2026
94ca39361693495125b77e32f52fe5752ef393272ef33101f99d0b1e732a3e9f  /var/www/lamtools/Sunday_0.3.21_x64-setup.exe
94ca39361693495125b77e32f52fe5752ef393272ef33101f99d0b1e732a3e9f  /var/www/lamtools/Sunday-latest-x64-setup.exe
{
  "version": "0.3.21",
  "download_url": "https://ainarit.com/downloads/Sunday_0.3.21_x64-setup.exe",
  "release_url": "https://ainarit.com/sunday.html",
  "release_notes": "Sunday 0.3.21",
  "published_at": "2026-10-23T06:05:31Z",
  "sha256": "94ca39361693495125b77e32f52fe5752ef393272ef33101f99d0b1e732a3e9f",
  "size": 73555367,
  "linux_version": "0.3.20"
}
active
active
```

| Sunday-0.3.21-remove-temporary-transfer-key | 2026-10-23T06:10:50+00:00 | Success / 0 | 01A16762-20E3-5425-8402-A4D25ECB6660 / c-hz070vqgu8qv2tc / t-hz070vqgu93ckjk |

```text
Fri Oct 23 06:10:47 AM UTC 2026
before key count: 2
after key count: 1
```

| Sunday-0.3.21-stage-inspection | 2026-10-23T05:59:05+00:00 | Success / 0 | 01A16757-5ECC-588C-A121-CDEC2D0878BE / c-hz070vpf3snrv9c / t-hz070vpf3t09czk |

```text
Fri Oct 23 05:59:02 AM UTC 2026
/var/www/lamtools/site-releases/0.3.20-mobile-0.1.48-20261015
-rw-r--r-- 1 root root 4.7M Oct 23 13:58 /tmp/release-0.3.21-site.tar.gz
-rw-r--r-- 1 root root 6.2K Oct 23 13:58 /tmp/sync-public-site.sh
1bacd30c1944c2a0c4ae456a5d060d988fd3b6a90abe7f9fba19257a4efe782b  /tmp/release-0.3.21-site.tar.gz
{
  "version": "0.3.20",
  "download_url": "https://ainarit.com/downloads/Sunday_0.3.20_x64-setup.exe",
  "release_url": "https://ainarit.com/sunday.html",
  "release_notes": "Sunday 0.3.20",
  "published_at": "2026-10-14T18:52:57Z",
  "sha256": "4e9ea304de7d52446569052c68ee54b33fc7efe5e0c2f93ce12ab1e9882804fe",
  "size": 58836915
}
active
active
```

| Sunday-0.3.21-stage-release-marker | 2026-10-23T06:00:02+00:00 | Success / 0 | 01A16758-416F-5F1D-871B-1B4FCE1D5289 / c-hz070vpi7bzkcn4 / t-hz070vpi7c9jy0w |

```text
88e75e119b361fc29f4696f604218933299c174823dbc6950b60f8f8e664d02d  /tmp/release-0.3.21-site-stamped.tar.gz
/var/www/lamtools/site-releases/0.3.21-mobile-0.1.48-20261023/assets/preview-4RRA2anN.js
staged site verified; public symlink unchanged: /var/www/lamtools/site-releases/0.3.20-mobile-0.1.48-20261015
```

| Sunday-0.3.21-stage-site | 2026-10-23T05:59:20+00:00 | Failed / 1 | 01A16757-A108-59AD-B6AE-A14E12B654DE / c-hz070vpg0bhoe0w / t-hz070vpg0bu5vr4 |

完整请求和执行输出：`data/core-agent/release-0.3.21-cloud-audit.jsonl`。
最初只读检查：01A1674C-7339-5FE3-9225-58FEAEB2208A / c-hz070vocsqhv5ds / t-hz070vocsqmuy2o（目录假设错误，退出 2，无修改）；随后检查：01A1674D-18B0-5DB0-B13C-0B6FB2AE0568 / c-hz070vof28olc00 / t-hz070vof28tl4ow（成功）。

## 备份与回退

- Windows 旧更新配置和 latest 安装包：`/var/backups/ainarit/release-0.3.21/`。
- 旧官网目标：`/var/www/lamtools/site-releases/0.3.20-mobile-0.1.48-20261015`；旧目录保留。
- 回退 Windows：从备份恢复 desktop-update.json 和 Sunday-latest-x64-setup.exe；保留新版本文件不会影响旧频道。
- 回退官网：把 site 链接切回上面的旧目标，并从同步脚本输出列出的 tar 备份恢复 sunday.html 与预览目录。
- 临时 SSH 授权备份：`/root/.ssh/authorized_keys.before-sunday-0.3.21`；清理必须仅移除任务公钥，保留其他授权。
- 预览初次暂存因入口版本检测失败而退出；后续给发布产物加入准确版本标记重新暂存。失败发生在未公开的目录内，未影响服务。

## 范围

- 本次代码修复验收：26 项新增或加强的控制边界测试通过；未跑全量测试。
- 完整 Rust 独立控制服务尚未迁移，不宣称整个控制架构迁移完成。
- website/src/components/Download.vue 默认版本仍是 0.3.20；本次通过构建参数发布 0.3.21。

## 最终验收

- Windows 与 Linux 云端构建全部成功；正式发布包含 Windows、AppImage、deb 三项文件。
- 官网同步和只读复查全部成功，Linux 链接 HTTP 检查成功，移动端保持 0.1.48。
- 同步备份：/var/backups/ainarit/sunday-before-20261023T061247Z.tar.gz 和 ainarit-preview-before-20261023T061247Z.tar.gz。
- 临时上传公钥已从服务器精确删除，授权数量从 2 恢复 1；保留其余授权。
- 开发版恢复：主进程 10028，后台端口 53094；恢复后健康检查成功。
- 云端发布过程中 Caddy 和 relay 服务持续正常。
- 完整构建起止时间见 data/core-agent/release-0.3.21-ci-result.json；Windows 作业 13 分 17 秒。
