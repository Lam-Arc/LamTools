# 修复计划

## A1 + A2: 注入 Persona + 执行纪律 + 工具 Schema
- [ ] `core_kernel_adapter.py`: 添加 imports（persona、prompt_assembler）
- [ ] `core_kernel_adapter.py`: WriterKit.__init__ 添加 work_root 参数
- [ ] `core_kernel_adapter.py`: WriterKit.build_model_request 注入系统提示 + 工具定义
- [ ] `core_kernel_adapter.py`: run_core_kernel 传 work_root 给 WriterKit

## A3: 注册 git_status / git_diff
- [ ] `core_kernel_adapter.py`: ReadWriteToolExecutor 添加 git_status/git_diff 方法
- [ ] `core_kernel_adapter.py`: ReadWriteToolExecutor.as_dict 注册 git 工具

## A4: 真实验证
- [ ] `core_kernel_adapter.py`: WriterKit.verify 检查文件存在性 + stub检测

## A5: writeback 状态跟踪
- [ ] `core_kernel_adapter.py`: WriterKit.writeback 记录 recent_tools/statuses/failures

## A6: drift 检测
- [ ] `core_kernel_adapter.py`: WriterKit.decide_next 添加 drift 检测逻辑

## 自审
- [ ] 自审所有修改

## 真实任务测试
- [ ] 启动 backend 跑 writer run 真实任务
