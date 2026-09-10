# 公开参考与来源说明

核查日期：2026-09-10。

## 本包的来源边界

本包按用户确认的 LamTools 桌面办公需求重新编写，交付的是指令、设计默认值和验收方案。
没有直接打包上游 SKILL.md、脚本、字体、图标、模板、模型或第三方依赖。
公开链接用于格式核对、工作流参考和后续实现选型，不表示相应项目已安装、已接入或已在 LamTools 测试。
本包不替第三方代码或资产授予许可证；未来引入具体实现时应逐项核对对应版本、许可证、依赖及分发条件。
不保留 Star 排名快照，避免将社区热度误认为功能质量或实测评分。

## 已核查的原始资料

| 来源 | 链接 | 使用范围 |
|---|---|---|
| Agent Skills Specification | https://agentskills.io/specification | 核对目录、SKILL.md 和 YAML frontmatter 格式 |
| MiniMax Skills | https://github.com/MiniMax-AI/skills | 办公文档、工作簿、PDF 与演示稿能力选型参考 |
| MiniMax pptx-generator | https://raw.githubusercontent.com/MiniMax-AI/skills/main/skills/pptx-generator/SKILL.md | 演示稿生成/编辑流程参考，不复制脚本与模板 |
| AntV chart-visualization-skills | https://github.com/antvis/chart-visualization-skills | 数据图表选择与生成工作流参考 |
| AntV chart-visualization 原文件 | https://raw.githubusercontent.com/antvis/chart-visualization-skills/master/skills/chart-visualization/SKILL.md | 核对其包含外部 HTTP 生成接口；本包改为优先本地渲染 |
| AntV Infographic | https://github.com/antvis/Infographic | 结构图与信息图实现选型参考 |
| AntV infographic-creator | https://raw.githubusercontent.com/antvis/Infographic/main/skills/infographic-creator/SKILL.md | 结构、模板、主题分离的工作流参考 |
| Google Workspace CLI | https://github.com/googleworkspace/cli | 邮件及办公服务连接器选型参考；本包不绑定 Gmail |
| daymade deep-research | https://raw.githubusercontent.com/daymade/claude-code-skills/main/deep-research/SKILL.md | 调研规划、证据整理及审查思路参考 |

会议与归档 Skill 直接根据已确认需求和通用安全工作流程编写，不依赖未核实的特定上游 Skill。
某个公开项目在未来改版，不应自动改变本包运行行为；实际接入依赖应固定版本并重新验收。
