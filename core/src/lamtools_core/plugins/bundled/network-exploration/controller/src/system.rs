// user:“实现这个插件，也正好实验我们的新插件架构”+(网络修改先留快照，验证失败回滚；检测到外部修改则保留现场，不能覆盖用户设置)。
use crate::{
    powershell,
    state::{Controller, Reply},
};
use serde_json::{json, Value};
const PREFIX: &str = r#"$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new();$a=$env:SUNDAY_NETWORK_ARGS|ConvertFrom-Json;"#;

fn notify_proxy() -> Result<(), String> {
    #[cfg(windows)]
    {
        use windows_sys::Win32::Networking::WinInet::{
            InternetSetOptionW, INTERNET_OPTION_REFRESH, INTERNET_OPTION_SETTINGS_CHANGED,
        };
        // SAFETY: the documented process-wide refresh options accept null handles and no buffer.
        let changed = unsafe {
            InternetSetOptionW(
                std::ptr::null(),
                INTERNET_OPTION_SETTINGS_CHANGED,
                std::ptr::null(),
                0,
            )
        };
        let refreshed = unsafe {
            InternetSetOptionW(
                std::ptr::null(),
                INTERNET_OPTION_REFRESH,
                std::ptr::null(),
                0,
            )
        };
        if changed == 0 || refreshed == 0 {
            return Err("代理设置已写入，但 Windows 刷新失败，将尝试恢复原设置".into());
        }
    }
    Ok(())
}

fn validate(p: &Value) -> Result<(), String> {
    match p["kind"].as_str() {
        Some("proxy") => {
            if let Some(server) = p.get("server") {
                let server = server.as_str().ok_or("系统代理地址必须是字符串")?;
                server
                    .strip_prefix("127.0.0.1:")
                    .and_then(|value| value.parse::<u16>().ok())
                    .filter(|port| *port > 0)
                    .ok_or("系统代理仅允许指向此插件的本机回环端口")?;
            }
        }
        Some("dns") => {
            if !matches!(p["interface_index"].as_u64(), Some(1..=4294967295)) {
                return Err("请选择有效的网络接口".into());
            }
            let rows = p["servers"].as_array().ok_or("DNS 必须为 IP 地址列表")?;
            if rows.is_empty()
                || rows.len() > 4
                || rows.iter().any(|v| {
                    v.as_str()
                        .and_then(|s| s.parse::<std::net::IpAddr>().ok())
                        .is_none()
                })
            {
                return Err("请输入 1–4 个有效的 DNS IP 地址".into());
            }
        }
        Some("firewall") => {
            let path = p["program"].as_str().ok_or("缺少应用绝对路径")?;
            if !std::path::Path::new(path).is_absolute()
                || !path.to_lowercase().ends_with(".exe")
                || path.contains(['*', '?'])
            {
                return Err("请选择应用的 .exe 绝对路径".into());
            }
            if p.get("name").is_some()
                && !p["name"]
                    .as_str()
                    .unwrap_or("")
                    .starts_with("Sunday-Network-")
            {
                return Err("只能修改插件自己创建的防火墙规则".into());
            }
        }
        Some("qos") => {
            let path = p["program"].as_str().ok_or("缺少应用路径")?;
            if !std::path::Path::new(path).is_absolute() || path.contains(['*', '?']) {
                return Err("请选择应用绝对路径".into());
            }
            if !matches!(p["bits_per_second"].as_u64(), Some(8000..=100000000000)) {
                return Err("应用限速必须为 8 Kbit/s–100 Gbit/s".into());
            }
        }
        _ => return Err("此系统操作尚不支持；未修改任何配置".into()),
    }
    Ok(())
}
pub async fn inspect(p: Value) -> Reply {
    validate(&p)?;
    let script = match p["kind"].as_str().unwrap() {
        "proxy" => {
            r#"$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings';$r=Get-ItemProperty $key;@{enabled=$r.ProxyEnable;server=$r.ProxyServer;bypass=$r.ProxyOverride}|ConvertTo-Json -Compress"#
        }
        "dns" => {
            r#"$guid=([guid](Get-NetAdapter -InterfaceIndex $a.interface_index -IncludeHidden).InterfaceGuid).ToString('B');$m4=(Get-ItemProperty -LiteralPath ('HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\'+$guid) -Name NameServer -ErrorAction SilentlyContinue).NameServer;$m6=(Get-ItemProperty -LiteralPath ('HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters\Interfaces\'+$guid) -Name NameServer -ErrorAction SilentlyContinue).NameServer;@{adapter_guid=$guid;rows=@(Get-DnsClientServerAddress -InterfaceIndex $a.interface_index|Sort-Object AddressFamily|ForEach-Object {@{family=[int]$_.AddressFamily;servers=@($_.ServerAddresses);manual=if([int]$_.AddressFamily -eq 2){[bool]$m4}else{[bool]$m6}}})}|ConvertTo-Json -Depth 5 -Compress"#
        }
        "firewall" => {
            r#"$r=Get-NetFirewallRule -Name $a.name -ErrorAction SilentlyContinue;if($r){$f=$r|Get-NetFirewallApplicationFilter;@{exists=$true;program=$f.Program;action=[string]$r.Action;enabled=[string]$r.Enabled;direction=[string]$r.Direction;profile=[string]$r.Profile;edge=[string]$r.EdgeTraversalPolicy;ports=($r|Get-NetFirewallPortFilter|Select-Object Protocol,LocalPort,RemotePort,IcmpType,DynamicTarget);addresses=($r|Get-NetFirewallAddressFilter|Select-Object LocalAddress,RemoteAddress);services=($r|Get-NetFirewallServiceFilter|Select-Object Service);interfaces=($r|Get-NetFirewallInterfaceFilter|Select-Object InterfaceAlias);interface_types=($r|Get-NetFirewallInterfaceTypeFilter|Select-Object InterfaceType);security=($r|Get-NetFirewallSecurityFilter|Select-Object Authentication,Encryption,LocalUser,RemoteUser,RemoteMachine,OverrideBlockRules)}|ConvertTo-Json -Depth 6 -Compress}else{@{exists=$false}|ConvertTo-Json -Compress}"#
        }
        "qos" => {
            r#"$r=Get-NetQosPolicy -Name $a.name -PolicyStore ActiveStore -ErrorAction SilentlyContinue;if($r){@{exists=$true;program=$r.AppPathNameMatchCondition;bits_per_second=[uint64]$r.ThrottleRateAction;conditions=($r|Select-Object DSCPAction,IPDstPortEndMatchCondition,IPDstPortStartMatchCondition,IPDstPrefixMatchCondition,IPPortMatchCondition,IPProtocolMatchCondition,IPSrcPortEndMatchCondition,IPSrcPortStartMatchCondition,IPSrcPrefixMatchCondition,JobObjectMatchCondition,MinBandwidthWeightAction,NetDirectPortMatchCondition,NetworkProfile,Owner,Precedence,PriorityValue8021Action,TemplateMatchCondition,URIMatchCondition,URIRecursiveMatchCondition,UserMatchCondition)}|ConvertTo-Json -Depth 5 -Compress}else{@{exists=$false}|ConvertTo-Json -Compress}"#
        }
        _ => unreachable!(),
    };
    powershell(&format!("{PREFIX}{script}"), p).await
}
async fn apply(p: Value) -> Reply {
    validate(&p)?;
    let script = match p["kind"].as_str().unwrap() {
        "proxy" => {
            r#"$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings';$server=if($a.server){[string]$a.server}else{'127.0.0.1:17890'};Set-ItemProperty $key ProxyServer $server;Set-ItemProperty $key ProxyOverride '<local>';Set-ItemProperty $key ProxyEnable 1;@{ok=$true}|ConvertTo-Json -Compress"#
        }
        "dns" => {
            r#"foreach($family in @('InterNetwork','InterNetworkV6')){$servers=@($a.servers|Where-Object {([Net.IPAddress]::Parse($_)).AddressFamily.ToString() -eq $family});if($servers.Count){Get-DnsClientServerAddress -InterfaceIndex $a.interface_index -AddressFamily $(if($family -eq 'InterNetwork'){'IPv4'}else{'IPv6'})|Set-DnsClientServerAddress -ServerAddresses $servers}};Clear-DnsClientCache;@{ok=$true}|ConvertTo-Json -Compress"#
        }
        "firewall" => {
            r#"New-NetFirewallRule -Name $a.name -DisplayName $a.name -Direction Outbound -Program $a.program -Action Block -Enabled True|Out-Null;@{ok=$true}|ConvertTo-Json -Compress"#
        }
        "qos" => {
            r#"New-NetQosPolicy -Name $a.name -AppPathNameMatchCondition $a.program -ThrottleRateActionBitsPerSecond $a.bits_per_second -PolicyStore ActiveStore|Out-Null;@{ok=$true}|ConvertTo-Json -Compress"#
        }
        _ => unreachable!(),
    };
    let proxy = p["kind"] == "proxy";
    let result = powershell(&format!("{PREFIX}{script}"), p).await?;
    if proxy {
        notify_proxy()?;
    }
    Ok(result)
}
async fn restore(p: Value, before: Value) -> Reply {
    validate(&p)?;
    let args = json!({"request":p,"before":before});
    let base = format!("{PREFIX}$b=$a.before;$a=$a.request;");
    let script = match p["kind"].as_str().unwrap() {
        "proxy" => {
            // user:“fl clash 一关之后，我整个电脑的网就跟爆了一样”+(恢复时先检查旧的本机代理端口是否还活着，死了就关闭系统代理而不是把死端口写回去)。
            r#"$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings';$dead=$false;if($b.enabled -eq 1 -and [string]$b.server -match '^(127\.0\.0\.1|localhost):(\d+)$'){$hostName=[string]$Matches[1];$port=[int]$Matches[2];$client=New-Object Net.Sockets.TcpClient;try{$dead=-not $client.ConnectAsync($hostName,$port).Wait(300)}catch{$dead=$true};$client.Dispose()};if($dead){Set-ItemProperty $key ProxyEnable 0}else{foreach($pair in @(@('enabled','ProxyEnable'),@('server','ProxyServer'),@('bypass','ProxyOverride'))){$v=$b.($pair[0]);if($null -eq $v){Remove-ItemProperty -Path $key -Name $pair[1] -ErrorAction SilentlyContinue}else{Set-ItemProperty -Path $key -Name $pair[1] -Value $v}}};@{ok=$true}|ConvertTo-Json -Compress"#
        }
        "dns" => {
            r#"foreach($row in $b.rows){$obj=Get-DnsClientServerAddress -InterfaceIndex $a.interface_index -AddressFamily $(if($row.family -eq 2){'IPv4'}else{'IPv6'});if($row.manual){$obj|Set-DnsClientServerAddress -ServerAddresses @($row.servers)}else{$obj|Set-DnsClientServerAddress -ResetServerAddresses}};Clear-DnsClientCache;@{ok=$true}|ConvertTo-Json -Compress"#
        }
        "firewall" => {
            r#"Remove-NetFirewallRule -Name $a.name;@{ok=$true}|ConvertTo-Json -Compress"#
        }
        "qos" => {
            r#"Remove-NetQosPolicy -Name $a.name -PolicyStore ActiveStore -Confirm:$false;@{ok=$true}|ConvertTo-Json -Compress"#
        }
        _ => unreachable!(),
    };
    let result = powershell(&format!("{base}{script}"), args).await?;
    if p["kind"] == "proxy" {
        notify_proxy()?;
    }
    Ok(result)
}
pub fn owns(current: &Value, expected: &Value) -> bool {
    current == expected
}
fn expected_state(p: &Value, before: &Value) -> Reply {
    match p["kind"].as_str() {
        Some("proxy") => Ok(json!({
            "enabled":1,
            "server":p["server"].as_str().unwrap_or("127.0.0.1:17890"),
            "bypass":"<local>"
        })),
        Some("firewall") => Ok(
            json!({"exists":true,"program":p["program"],"action":"Block","enabled":"True","direction":"Outbound"}),
        ),
        Some("qos") => {
            Ok(json!({"exists":true,"program":p["program"],"bits_per_second":p["bits_per_second"]}))
        }
        Some("dns") => {
            let mut expected = before.clone();
            for row in expected["rows"].as_array_mut().ok_or("DNS 快照损坏")? {
                let family = row["family"].as_u64().ok_or("DNS 地址族缺失")?;
                let servers: Vec<_> = p["servers"]
                    .as_array()
                    .ok_or("缺少 DNS 地址")?
                    .iter()
                    .filter(|s| {
                        s.as_str()
                            .and_then(|s| s.parse::<std::net::IpAddr>().ok())
                            .map(|ip| ip.is_ipv4() == (family == 2))
                            .unwrap_or(false)
                    })
                    .cloned()
                    .collect();
                if !servers.is_empty() {
                    row["servers"] = json!(servers);
                    row["manual"] = json!(true);
                }
            }
            Ok(expected)
        }
        _ => Err("系统操作尚不支持".into()),
    }
}
fn restored_matches(current: &Value, before: &Value) -> bool {
    if current["adapter_guid"] != before["adapter_guid"] {
        return false;
    }
    if let (Some(current), Some(before)) = (current["rows"].as_array(), before["rows"].as_array()) {
        return current.len() == before.len()
            && current.iter().zip(before).all(|(a, b)| {
                a["family"] == b["family"]
                    && a["manual"] == b["manual"]
                    && (b["manual"] == false || a["servers"] == b["servers"])
            });
    }
    current == before
}
fn matches_expected(current: &Value, expected: &Value) -> bool {
    expected
        .as_object()
        .map(|fields| {
            fields
                .iter()
                .all(|(key, value)| current.get(key) == Some(value))
        })
        .unwrap_or(current == expected)
}
fn encode_snapshot(value: &Value) -> Reply {
    Ok(json!({"protected":crate::credentials::protect(&value.to_string())?}))
}
fn decode_snapshot(value: &Value) -> Reply {
    if let Some(cipher) = value["protected"].as_str() {
        serde_json::from_str(&crate::credentials::unprotect(cipher)?)
            .map_err(|_| "恢复快照损坏".into())
    } else {
        Ok(value.clone())
    }
}
impl Controller {
    // user:“修”+(系统代理只指向插件已启动的服务；本机加速不再依赖 Mihomo)。
    fn validate_proxy_target(&self, p: &Value) -> Result<(), String> {
        let port = p["server"]
            .as_str()
            .unwrap_or("127.0.0.1:17890")
            .strip_prefix("127.0.0.1:")
            .and_then(|value| value.parse::<u16>().ok())
            .ok_or("系统代理地址无效")?;
        if (port == 17890 && self.engines.proxy.is_some())
            || (port > 0
                && port == self.accelerator.port
                && self.accelerator.status()["running"] == true)
        {
            Ok(())
        } else {
            Err("请先启动对应的本机加速或代理服务".into())
        }
    }
    pub async fn apply_system(&mut self, mut p: Value) -> Reply {
        validate(&p)?;
        if matches!(p["kind"].as_str(), Some("firewall" | "qos"))
            && !std::path::Path::new(p["program"].as_str().unwrap_or("")).is_file()
        {
            return Err("应用文件不存在，请选择实际的程序文件".into());
        }
        if p["kind"] == "proxy" {
            self.validate_proxy_target(&p)?;
        }
        if self.saved.transactions.iter().any(|t| {
            t["status"] == "applied"
                && t["request"]["kind"] == p["kind"]
                && t["request"]["interface_index"] == p["interface_index"]
                && t["request"]["program"] == p["program"]
        }) {
            return Err("同一配置已有生效事务，请先恢复原配置".into());
        }
        let id = uuid::Uuid::new_v4().to_string();
        if p["kind"] == "firewall" || p["kind"] == "qos" {
            p["name"] = json!(format!("Sunday-Network-{id}"));
        }
        let before = inspect(p.clone()).await?;
        let expected = expected_state(&p, &before)?;
        if self.saved.transactions.len() >= 200 {
            return Err("恢复记录已达 200 条，请先归档记录".into());
        }
        self.saved.transactions.push(json!({"id":id,"request":p,"before":encode_snapshot(&before)?,"after":encode_snapshot(&expected)?,"status":"prepared","time":chrono::Utc::now().to_rfc3339()}));
        let index = self.saved.transactions.len() - 1;
        self.persist()?;
        let result = apply(p.clone()).await;
        if result.is_err() {
            // Re-read ownership after a partial failure; never blindly overwrite
            // a user or another program's intervening change.
            let _ = self.restore_index(index).await;
            return result;
        }
        let after = match inspect(p.clone()).await {
            Ok(value) => value,
            Err(error) => {
                let _ = self.restore_index(index).await;
                return Err(error);
            }
        };
        if !matches_expected(&after, &expected) {
            self.saved.transactions[index]["status"] = json!("recovery_required");
            self.persist()?;
            return Err("系统返回的配置与预期不一致，已保留快照，请核对后恢复".into());
        }
        self.saved.transactions[index]["after"] = encode_snapshot(&after)?;
        self.saved.transactions[index]["status"] = json!("applied");
        if let Err(error) = self.persist() {
            let _ = self.restore_index(index).await;
            return Err(error);
        }
        self.event("system", "网络配置已更改，已保存恢复快照");
        self.persist()?;
        Ok(json!({"transaction":{"id":id,"kind":p["kind"],"status":"applied"}}))
    }
    async fn restore_index(&mut self, index: usize) -> Reply {
        let row = self.saved.transactions[index].clone();
        let before = decode_snapshot(&row["before"])?;
        let current = inspect(row["request"].clone()).await?;
        if restored_matches(&current, &before) {
            self.saved.transactions[index]["status"] = json!("restored");
            self.persist()?;
            return Ok(json!({"restored":true}));
        }
        if let Some(after) = row.get("after") {
            if !owns(&current, &decode_snapshot(after)?) {
                self.saved.transactions[index]["status"] = json!("external_change");
                self.persist()?;
                return Err(
                    "检测到其他软件或用户已修改此配置；保留当前设置，请手动核对快照".into(),
                );
            }
        } else if current == before {
            self.saved.transactions[index]["status"] = json!("restored");
            self.persist()?;
            return Ok(json!({"restored":true}));
        } else {
            self.saved.transactions[index]["status"] = json!("recovery_required");
            self.persist()?;
            return Err("上次修改中断，无法确认配置所有权，请手动核对快照".into());
        }
        restore(row["request"].clone(), before.clone()).await?;
        let verified = inspect(row["request"].clone()).await?;
        if !restored_matches(&verified, &before) {
            return Err("恢复后的配置与快照不一致，请手动核对".into());
        }
        self.saved.transactions[index]["status"] = json!("restored");
        self.event("recovery", "已恢复插件修改前的配置");
        self.persist()?;
        Ok(json!({"restored":true,"id":row["id"]}))
    }
    pub async fn restore_system(&mut self, p: Value) -> Reply {
        let id = p["id"].as_str().ok_or("缺少事务 ID")?;
        let index = self
            .saved
            .transactions
            .iter()
            .position(|row| {
                row["id"] == id
                    && matches!(
                        row["status"].as_str(),
                        Some("applied" | "prepared" | "recovery_required")
                    )
            })
            .ok_or("没有可恢复的事务")?;
        self.restore_index(index).await
    }
    // user:“修”+(关闭加速只恢复指向自身端口的事务，不影响独立运行的代理)。
    pub async fn rollback_accelerator(&mut self) -> Result<(), String> {
        let server = format!("127.0.0.1:{}", self.accelerator.port);
        for index in (0..self.saved.transactions.len()).rev() {
            let row = &self.saved.transactions[index];
            if row["request"]["kind"] == "proxy"
                && row["request"]["server"] == server
                && matches!(
                    row["status"].as_str(),
                    Some("applied" | "prepared" | "recovery_required")
                )
            {
                self.restore_index(index).await?;
            }
        }
        Ok(())
    }
    pub async fn rollback_kind(&mut self, kind: &str) -> Result<(), String> {
        for i in (0..self.saved.transactions.len()).rev() {
            if self.saved.transactions[i]["request"]["kind"] == kind
                && self.saved.transactions[i]["status"] == "applied"
            {
                self.restore_index(i).await?;
            }
        }
        Ok(())
    }
    pub async fn restore_all(&mut self) -> Result<(), String> {
        let mut errors = Vec::new();
        for i in (0..self.saved.transactions.len()).rev() {
            if matches!(
                self.saved.transactions[i]["status"].as_str(),
                Some("applied" | "prepared" | "recovery_required")
            ) {
                if let Err(error) = self.restore_index(i).await {
                    errors.push(error);
                }
            }
        }
        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors.join("；"))
        }
    }
    pub async fn recover(&mut self) -> Result<(), String> {
        let _ = self.engines.stop_proxy().await;
        if let Err(error) = self.restore_all().await {
            self.event("recovery", &error);
            self.persist()?;
        }
        Ok(())
    }
    pub fn save_automations(&mut self, p: Value) -> Reply {
        if p["revision"].as_u64() != Some(self.saved.revision) {
            return Err("自动化规则已更新，请刷新".into());
        }
        let rows = p["automations"]
            .as_array()
            .ok_or("automations 必须为数组")?;
        if rows.len() > 30 {
            return Err("自动化最多 30 条".into());
        }
        for row in rows {
            crate::observe::validate_host(row["target"].as_str().ok_or("自动化缺少检测目标")?)?;
            if !matches!(row["interval_minutes"].as_u64(), Some(1..=1440)) {
                return Err("诊断间隔应为 1–1440 分钟".into());
            }
            if row["action"] != "diagnose" {
                return Err("自动执行仅支持只读诊断；系统修改必须手动审批".into());
            }
        }
        let old = self.saved.automations.clone();
        self.saved.automations = rows.clone();
        self.saved.revision += 1;
        if let Err(error) = self.persist() {
            self.saved.automations = old;
            self.saved.revision -= 1;
            return Err(error);
        }
        Ok(json!({"revision":self.saved.revision}))
    }
    pub async fn run_automation(&mut self, p: Value) -> Reply {
        let index = p["index"].as_u64().ok_or("缺少自动化序号")? as usize;
        let row = self
            .saved
            .automations
            .get(index)
            .ok_or("自动化不存在")?
            .clone();
        if p["dry_run"].as_bool().unwrap_or(true) {
            return Ok(
                json!({"dry_run":true,"would_execute":{"action":"diagnose","target":row["target"]},"changes_system":false}),
            );
        }
        self.diagnose(json!({"target":row["target"]})).await
    }
    pub async fn automation_tick(&mut self) {
        let now = chrono::Utc::now().timestamp();
        let due: Vec<_> = self
            .saved
            .automations
            .iter()
            .enumerate()
            .filter(|(_, r)| {
                r["enabled"] == true
                    && now - r["last_run"].as_i64().unwrap_or(0)
                        >= r["interval_minutes"].as_i64().unwrap_or(60) * 60
            })
            .map(|(i, r)| (i, r["target"].clone()))
            .collect();
        for (index, target) in due {
            self.saved.automations[index]["last_run"] = json!(now);
            let result = self.diagnose(json!({"target":target})).await;
            if result.is_err() {
                self.event("automation", "定时诊断失败；不会自动修改网络配置");
            }
            let _ = self.persist();
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn proxy_server_accepts_loopback_ports_only() {
        // user:“本机加速层 你学习一下呗…它该抄就抄”+(本机加速器用临时端口，系统代理仍然只允许回环地址)。
        assert!(validate(&json!({"kind":"proxy","server":"127.0.0.1:17890"})).is_ok());
        assert!(validate(&json!({"kind":"proxy","server":"127.0.0.1:49152"})).is_ok());
        assert!(validate(&json!({"kind":"proxy","server":"10.0.0.1:8080"})).is_err());
        assert!(validate(&json!({"kind":"proxy","server":"127.0.0.1:0"})).is_err());
    }
    #[test]
    fn firewall_filter_change_invalidates_ownership() {
        let original = json!({"exists":true,"program":"app.exe","ports":{"RemotePort":"Any"}});
        let changed = json!({"exists":true,"program":"app.exe","ports":{"RemotePort":"443"}});
        assert!(!owns(&changed, &original));
    }
    #[test]
    fn reused_interface_index_does_not_restore_another_adapter() {
        let before =
            json!({"adapter_guid":"old","rows":[{"family":2,"manual":false,"servers":[]}]});
        let current =
            json!({"adapter_guid":"new","rows":[{"family":2,"manual":false,"servers":[]}]});
        assert!(!restored_matches(&current, &before));
    }
    #[test]
    fn refuses_unsupported_system_changes() {
        assert!(validate(&json!({"kind":"certificate"})).is_err());
        assert!(
            validate(&json!({"kind":"dns","interface_index":2,"servers":["1.1.1.1;whoami"]}))
                .is_err()
        );
    }
    #[test]
    fn external_changes_must_not_be_overwritten() {
        assert!(!owns(&json!({"server":"other"}), &json!({"server":"ours"})));
    }
    #[test]
    fn dns_snapshot_keeps_automatic_mode_and_unmodified_ipv6() {
        let before = json!({"rows":[{"family":2,"servers":["192.168.1.1"],"manual":false},{"family":23,"servers":["::1"],"manual":true}]});
        let after = expected_state(&json!({"kind":"dns","servers":["1.1.1.1"]}), &before).unwrap();
        assert_eq!(after["rows"][0]["manual"], true);
        assert_eq!(after["rows"][1], before["rows"][1]);
        assert_eq!(before["rows"][0]["manual"], false);
    }
    #[test]
    fn dhcp_restore_allows_a_new_lease_without_pinning_old_dns() {
        assert!(restored_matches(
            &json!({"rows":[{"family":2,"servers":["192.168.2.1"],"manual":false}]}),
            &json!({"rows":[{"family":2,"servers":["192.168.1.1"],"manual":false}]})
        ));
    }
    // user:“修”+(本机加速无需订阅；仅允许指向确实由插件启动的监听端口)。
    #[tokio::test]
    async fn regression_proxy_target_accepts_local_accelerator_without_mihomo() {
        let dir = std::env::temp_dir().join(format!("network-target-{}", uuid::Uuid::new_v4()));
        let mut controller = Controller::new(dir.clone()).unwrap();
        assert!(controller
            .validate_proxy_target(&json!({"server":"127.0.0.1:17890"}))
            .is_err());
        controller.accelerator.start(None).await.unwrap();
        let port = controller.accelerator.port;
        assert!(controller
            .validate_proxy_target(&json!({"server":format!("127.0.0.1:{port}")}))
            .is_ok());
        assert!(controller
            .validate_proxy_target(&json!({"server":"127.0.0.1:1"}))
            .is_err());
        controller.accelerator.stop();
        assert!(controller
            .validate_proxy_target(&json!({"server":format!("127.0.0.1:{port}")}))
            .is_err());
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[tokio::test]
    async fn regression_failed_recovery_keeps_listener_and_unrelated_proxy_is_untouched() {
        // user:“修”+(快照损坏时也不能停止仍被系统代理使用的服务；测试不读取或改写系统设置)。
        let dir = std::env::temp_dir().join(format!("network-stop-{}", uuid::Uuid::new_v4()));
        let mut controller = Controller::new(dir.clone()).unwrap();
        controller.accelerator.start(None).await.unwrap();
        let port = controller.accelerator.port;
        controller.saved.transactions.push(json!({"request":{"kind":"proxy","server":format!("127.0.0.1:{port}")},"status":"applied","before":{"protected":"invalid"}}));
        assert!(controller
            .call("accelerator.stop", json!({}))
            .await
            .is_err());
        assert_eq!(controller.accelerator.port, port);
        assert!(tokio::net::TcpStream::connect(("127.0.0.1", port))
            .await
            .is_ok());
        controller.saved.transactions[0]["request"]["server"] = json!("127.0.0.1:1");
        controller
            .call("accelerator.stop", json!({}))
            .await
            .unwrap();
        assert_eq!(controller.saved.transactions[0]["status"], "applied");
        assert_eq!(controller.accelerator.port, 0);
        std::fs::remove_dir_all(dir).unwrap();
    }
}
