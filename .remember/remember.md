# Handoff

## State
- LamWriter 启动器已整合到源码目录 `members/writer/`
- `setup.bat` 和 `start.bat` 已创建并测试通过
- 虚拟环境 `venv/` 和数据目录 `data/` 都在项目内
- 所有批处理文件使用 UTF-8 编码（chcp 65001）避免中文乱码

## Next
- 测试 `setup.bat` 和 `start.bat` 在干净环境下的可用性
- 修复删除会话/项目的 bug
- 联网搜索功能待修复

## Context
- 用户不是专业开发者，说人话，别拽术语，听不懂会生气
- 危险操作先问，别自己删东西
- **编码规范**：所有 .bat 脚本必须使用 UTF-8（chcp 65001），不支持则用英文输出
