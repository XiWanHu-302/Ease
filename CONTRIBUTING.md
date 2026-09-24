# 贡献与开发指南

感谢关注坐伴。当前项目处于原型验证阶段，优先改进三项姿态检测的可靠性、CPU运行性能和Windows使用体验。

## 开发环境

按 [README](README.md) 配置Python 3.11虚拟环境、锁定依赖和模型。在项目根目录运行命令；调试时直接运行源码，修改后重新启动，无需反复构建exe。

核心代码分为四部分：

| 模块 | 职责 |
|---|---|
| `zuoban/core.py` | 个人校准、参数、三项独立状态机和统计 |
| `zuoban/vision.py` | 图像采集、CPU推理、关键点与角度计算 |
| `zuoban/ui.py` | 监测、报告、设置以及用户操作流程 |
| `zuoban/storage.py` | SQLite存储和CSV导出 |

## 提交修改

- 提交前说明要解决的问题、复现方式和预期行为。较大的功能变更建议先通过Issue讨论范围。
- 保持每次修改聚焦，避免同时重构无关模块。同步更新受影响的说明和参数文档。
- 保持摄像头采集和模型推理独立于界面线程，结果队列只保存最新数据。
- 使用单调时间计算持续时长；保留三项独立有效性、提醒冷却与统计去重。
- 不将摄像头画面、个人会话数据库、密钥、虚拟环境、下载的模型权重或生成产物纳入提交。
- 算法效果需有真实验证依据；合成测试和空画面速度不能作为真人准确率或体验结论。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

状态机和统计修改优先运行 `tests/test_core.py`，角度计算修改运行 `tests/test_geometry.py`，重放和界面修改分别检查对应测试。界面调整还应检查中文显示、缩放和生命周期；纯文档修改检查格式与链接即可。

在Pull Request中说明修改内容、验证命令及结果，并注明未覆盖的场景。真实使用素材需经参与者同意，反馈时移除个人信息。

## 构建Windows运行包

准备发布版本时执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/build.ps1
.\.venv\Scripts\python.exe tools/check_release.py
.\.venv\Scripts\python.exe tools/package_release.py
```

正式配置是 `packaging/zuoban.spec`。运行包必须包含 `ZuoBan.exe` 及同目录的 `_internal`，不能只复制exe。发布前还需检查真实摄像头操作与其他Windows电脑的兼容性。

模型库导入时依赖matplotlib，不能直接排除。当前打包配置还排除了曾导致Qt启动失败的误收集ICU库；调整依赖或构建配置后需要重新验证这些场景。
