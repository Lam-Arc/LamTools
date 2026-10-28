use crate::engines::Engines;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::VecDeque,
    path::PathBuf,
    time::{Duration, Instant},
};
use sysinfo::Networks;
pub type Reply = Result<Value, String>;

// user:“实现这个插件，也正好实验我们的新插件架构”+(设置采用版本检查和原子持久化，三个入口不能互相覆盖)。
#[derive(Serialize, Deserialize, Default)]
pub struct Saved {
    pub revision: u64,
    pub settings: Value,
    #[serde(default)]
    pub rules: Vec<Value>,
    #[serde(default)]
    pub reports: Vec<Value>,
    #[serde(default)]
    pub transactions: Vec<Value>,
    #[serde(default)]
    pub downloads: Vec<Value>,
    #[serde(default)]
    pub automations: Vec<Value>,
    #[serde(default)]
    pub events: VecDeque<Value>,
}
pub struct Controller {
    pub data: PathBuf,
    pub saved: Saved,
    pub engines: Engines,
    pub accelerator: crate::accelerator::Accelerator,
    pub networks: Networks,
    pub history: VecDeque<Value>,
    pub last_sample: Instant,
    pub last_total: (u64, u64),
    pub last_automation: Instant,
    pub proxy_expected: bool,
}
impl Controller {
    pub fn new(data: PathBuf) -> Result<Self, String> {
        std::fs::create_dir_all(&data).map_err(|e| e.to_string())?;
        let path = data.join("state.json");
        let saved = if path.exists() {
            serde_json::from_slice(&std::fs::read(path).map_err(|e| e.to_string())?)
                .map_err(|_| "插件状态损坏；保留原文件并从备份恢复")?
        } else {
            Saved {
                settings: json!({"sample_seconds": 5,"mode":"local"}),
                ..Default::default()
            }
        };
        let mut networks = Networks::new_with_refreshed_list();
        networks.refresh(true);
        let total = networks.values().fold((0, 0), |(r, t), n| {
            (r + n.total_received(), t + n.total_transmitted())
        });
        Ok(Self {
            engines: Engines::new(data.clone())?,
            accelerator: crate::accelerator::Accelerator::new(),
            data,
            saved,
            networks,
            history: VecDeque::new(),
            last_sample: Instant::now(),
            last_total: total,
            last_automation: Instant::now(),
            proxy_expected: false,
        })
    }
    pub fn persist(&self) -> Result<(), String> {
        let destination = self.data.join("state.json");
        let temporary = self.data.join("state.next.json");
        let bytes = serde_json::to_vec_pretty(&self.saved).map_err(|e| e.to_string())?;
        use std::io::Write;
        let mut file = std::fs::File::create(&temporary).map_err(|e| e.to_string())?;
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|e| e.to_string())?;
        if destination.exists() {
            std::fs::copy(&destination, self.data.join("state.backup.json"))
                .map_err(|e| e.to_string())?;
        }
        std::fs::rename(temporary, destination).map_err(|e| e.to_string())
    }
    pub fn event(&mut self, kind: &str, message: &str) {
        self.saved.events.push_back(
            json!({"time":chrono::Utc::now().to_rfc3339(),"kind":kind,"message":message}),
        );
        while self.saved.events.len() > 200 {
            self.saved.events.pop_front();
        }
    }
    pub async fn call(&mut self, method: &str, p: Value) -> Reply {
        match method {
            "status" => self.status().await,
            "settings.update" => self.update_settings(p),
            "connections" => crate::observe::connections(p).await,
            "interfaces" => crate::observe::interfaces().await,
            "dns.query" => crate::observe::dns_query(p).await,
            "lan" => crate::observe::lan().await,
            "diagnose" => self.diagnose(p).await,
            "rules.save" => self.save_rules(p),
            "rules.test" => crate::observe::match_rule(&self.saved.rules, p),
            "proxy.start" => {
                let result = self.engines.start_proxy(p).await;
                if result.is_ok() {
                    self.proxy_expected = true;
                    // user:“修”+(线路启停同步到已运行的本机加速器)。
                    self.accelerator.set_fallback(Some(17890));
                }
                result
            }
            "proxy.stop" => {
                self.rollback_kind("proxy").await?;
                self.proxy_expected = false;
                self.accelerator.set_fallback(None);
                self.engines.stop_proxy().await
            }
            "proxy.inspect" => self.engines.proxy_inspect().await,
            "proxy.select" => self.engines.proxy_select(p).await,
            "proxy.delay" => self.engines.proxy_delay(p).await,
            "proxy.optimize" => self.engines.proxy_optimize(p).await,
            "proxy.mode" => self.engines.proxy_mode(p).await,
            "proxy.config" => self.engines.proxy_config(p).await,
            // user:“本机加速层 你学习一下呗…它该抄就抄”+(本地 CONNECT 加速，代理内核只作为非命中域名的兜底)。
            "accelerator.start" => {
                let fallback = self.proxy_expected.then_some(17890);
                let result = self.accelerator.start(fallback).await?;
                self.reroute_auto_downloads(Some(self.accelerator.port)).await?;
                Ok(result)
            }
            "accelerator.stop" => {
                // user:“修”+(后台同样先恢复系统代理；恢复失败不关闭监听，避免断网)。
                self.rollback_accelerator().await?;
                self.reroute_auto_downloads(None).await?;
                self.accelerator.stop();
                Ok(json!({"running":false,"port":0}))
            }
            "transfer.add" => self.add_download(p).await,
            "transfer.list" => self.download_snapshot().await,
            "transfer.action" => self.transfer_action(p).await,
            "transfer.recover" => self.recover_downloads().await,
            "transfer.verify" => self.verify_download(p).await,
            "system.apply" => self.apply_system(p).await,
            "system.restore" => self.restore_system(p).await,
            "system.inspect" => crate::system::inspect(p).await,
            "automation.save" => self.save_automations(p),
            "automation.run" => self.run_automation(p).await,
            "export" => Ok(
                json!({"reports":self.saved.reports,"events":self.saved.events,"rules":self.saved.rules}),
            ),
            "shutdown" => Ok(json!({"stopped":true})),
            _ => Err("未知网络操作".into()),
        }
    }
    pub async fn status(&mut self) -> Reply {
        self.check_proxy_exit().await;
        let proxy = self.engines.proxy_status().await;
        // user:“修”+(所有面板直接消费统一下载快照，避免首页速度和数量停留在旧值)。
        let downloads = self.download_snapshot().await?["tasks"].clone();
        let transactions:Vec<_>=self.saved.transactions.iter().map(|row|json!({"id":row["id"],"time":row["time"],"status":row["status"],"request":row["request"]})).collect();
        Ok(
            json!({"controller_pid":std::process::id(),"revision":self.saved.revision,"settings":self.saved.settings,
            "proxy":proxy,"engines":self.engines.available(),"traffic_source":"system_interfaces",
            "accelerator":self.accelerator.status(),
            "traffic":self.history.back(),"history":self.history,"rules":self.saved.rules,"reports":self.saved.reports,
            "transactions":transactions,"events":self.saved.events,"downloads":downloads,
            "automations":self.saved.automations}),
        )
    }
    fn update_settings(&mut self, p: Value) -> Reply {
        if p["revision"].as_u64() != Some(self.saved.revision) {
            return Err("设置已在其他面板更新，请刷新后重试".into());
        }
        let value = p["settings"].as_object().ok_or("settings 必须是对象")?;
        if let Some(seconds) = value.get("sample_seconds") {
            if !matches!(seconds.as_u64(), Some(2..=60)) {
                return Err("采样间隔应为 2–60 秒".into());
            }
        }
        if let Some(mode) = value.get("mode") {
            if !matches!(mode.as_str(), Some("local" | "hybrid" | "control")) {
                return Err("无效的运行模式".into());
            }
        }
        let old = self.saved.settings.clone();
        let revision = self.saved.revision;
        for key in value.keys() {
            if !matches!(key.as_str(), "sample_seconds" | "mode") {
                return Err(format!("未知设置 {key}"));
            }
        }
        for (key, value) in value {
            self.saved.settings[key] = value.clone();
        }
        self.saved.revision += 1;
        if let Err(error) = self.persist() {
            self.saved.settings = old;
            self.saved.revision = revision;
            return Err(error);
        }
        Ok(json!({"revision":self.saved.revision,"settings":self.saved.settings}))
    }
    fn save_rules(&mut self, p: Value) -> Reply {
        if p["revision"].as_u64() != Some(self.saved.revision) {
            return Err("规则已更新，请刷新".into());
        }
        let rules = p["rules"].as_array().ok_or("rules 必须是数组")?;
        if rules.len() > 500 {
            return Err("规则最多 500 条".into());
        }
        let mut seen = std::collections::HashSet::new();
        for rule in rules {
            let domain = rule["domain"].as_str().ok_or("规则缺少域名")?;
            crate::observe::validate_host(domain)?;
            if !seen.insert(domain.to_lowercase()) {
                return Err(format!("域名规则冲突：{domain}"));
            }
            if !matches!(
                rule["outbound"].as_str(),
                Some("DIRECT" | "PROXY" | "REJECT")
            ) {
                return Err("出口必须为 DIRECT、PROXY 或 REJECT".into());
            }
        }
        let previous = self.saved.rules.clone();
        self.saved.rules = rules.clone();
        self.saved.revision += 1;
        if let Err(e) = self.persist() {
            self.saved.rules = previous;
            self.saved.revision -= 1;
            return Err(e);
        }
        Ok(json!({"revision":self.saved.revision,"rules":self.saved.rules}))
    }
    pub async fn tick(&mut self) {
        self.check_proxy_exit().await;
        if self.last_sample.elapsed()
            >= Duration::from_secs(self.saved.settings["sample_seconds"].as_u64().unwrap_or(5))
        {
            self.networks.refresh(true);
            let total = self.networks.values().fold((0, 0), |(r, t), n| {
                (r + n.total_received(), t + n.total_transmitted())
            });
            let seconds = self.last_sample.elapsed().as_secs_f64();
            let interfaces:Vec<_>=self.networks.iter().map(|(name,n)|json!({"name":name,"received":n.total_received(),"sent":n.total_transmitted()})).collect();
            self.history.push_back(json!({"time":chrono::Utc::now().to_rfc3339(),"download":(total.0.saturating_sub(self.last_total.0) as f64/seconds) as u64,
                "upload":(total.1.saturating_sub(self.last_total.1) as f64/seconds) as u64,"received":total.0,"sent":total.1,"interfaces":interfaces}));
            while self.history.len() > 120 {
                self.history.pop_front();
            }
            self.last_total = total;
            self.last_sample = Instant::now();
            if self.engines.aria.is_some() {
                if self.download_snapshot().await.is_err() {
                    self.event("transfer", "下载内核不可用；已保留任务记录，可恢复任务");
                }
            }
        }
        if self.last_automation.elapsed() >= Duration::from_secs(60) {
            self.last_automation = Instant::now();
            self.automation_tick().await;
        }
    }
    pub async fn shutdown(&mut self) {
        if let Err(error) = self.restore_all().await {
            self.event("recovery", &error);
        }
        self.accelerator.stop();
        self.engines.shutdown().await;
        let _ = self.persist();
    }
    async fn check_proxy_exit(&mut self) {
        if !self.proxy_expected {
            return;
        }
        let alive = self
            .engines
            .proxy
            .as_mut()
            .map(|p| matches!(p.try_wait(), Ok(None)))
            .unwrap_or(false);
        if !alive {
            self.proxy_expected = false;
            self.accelerator.set_fallback(None);
            if let Err(error) = self.rollback_kind("proxy").await {
                self.event("recovery", &error);
            }
            let _ = self.engines.stop_proxy().await;
            self.event(
                "proxy",
                "代理内核已退出；已检查系统代理恢复，基础诊断与下载服务仍可使用",
            );
            let _ = self.persist();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn controller() -> Controller {
        Controller::new(
            std::env::temp_dir().join(format!("sunday-network-test-{}", uuid::Uuid::new_v4())),
        )
        .unwrap()
    }
    #[test]
    fn settings_reject_stale_revision_and_survive_restart() {
        let mut c = controller();
        c.update_settings(json!({"revision":0,"settings":{"sample_seconds":3}}))
            .unwrap();
        assert!(c
            .update_settings(json!({"revision":0,"settings":{"sample_seconds":8}}))
            .is_err());
        let other = Controller::new(c.data.clone()).unwrap();
        assert_eq!(other.saved.settings["sample_seconds"], 3);
        std::fs::remove_dir_all(c.data).unwrap();
    }
    #[test]
    fn conflicting_rules_are_not_committed() {
        let mut c = controller();
        assert!(c.save_rules(json!({"revision":0,"rules":[{"domain":"example.com","outbound":"DIRECT"},{"domain":"EXAMPLE.com","outbound":"PROXY"}]})).is_err());
        assert_eq!(c.saved.revision, 0);
        std::fs::remove_dir_all(c.data).unwrap();
    }
}
