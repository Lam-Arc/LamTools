# 成果文件引用地址恢复

用户提供的错误引用：`E:/LamTools/MyProject/krea_ref01_00001_.png`。

已从磁盘确认真实文件：`E:/LamTools/MyProject/.lam/artifacts/images/krea_ref01_00001_.png`。

修复覆盖三个问题：报告中的路径遗漏成果目录；Windows 盘符链接在 HTML 净化前没有转换为文件引用；没有真实资料库编号的图片被错误地按编号读取。

## 解析规则

- 优先使用准确且存在的原文件。
- 路径不存在时，仅在当前项目的 `.lam/artifacts`、`.lam/artifact`、`artifacts`、`artifact` 中查找同名文件。
- 唯一匹配才恢复；多个同名文件返回明确的冲突提示，不任意选择。
- 缺失路径指向项目外时不搜索其他项目；不沿符号链接跳出项目。
- 扫描对目录与文件总量设有上限，达到上限后要求使用完整路径。
- 显示链接、图片读取、成果预览、默认应用打开、分屏打开及复制路径共用核实后的地址。
- 提示模型复制工具返回且验证存在的路径，不能按文件名自行省略目录。

读取、恢复、打开接口继续使用已有的后台访问检查。恢复过程不移动、复制或修改用户文件；不改写原聊天消息。

## 验证

仅运行本轮新增测试：

```powershell
cd E:\LamTools\core
python -m pytest tests/test_artifact_reference_resolution.py -q

cd E:\LamTools\core\ui
npx vitest run tests/artifact-reference-resolution.test.ts
npx vue-tsc --noEmit --pretty false
```
