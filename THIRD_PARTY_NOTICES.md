# 第三方来源与授权记录

坐伴的原创工作是校准、姿态状态判断、提醒策略、桌面集成、记录与测试。人体/人脸基础模型来自Google，不宣称自研。

| 组件 | 上游 | 授权说明 |
|---|---|---|
| MediaPipe | https://github.com/google-ai-edge/mediapipe | Apache-2.0；发布包保留安装分发中的许可证 |
| OpenCV | https://github.com/opencv/opencv | Apache-2.0；Python二进制依赖另见其第三方许可证 |
| NumPy | https://github.com/numpy/numpy | BSD-3-Clause及二进制依赖许可证 |
| PySide6 / Qt | https://doc.qt.io/qtforpython-6/licenses.html | 使用开源发行版，按LGPL/GPL及模块适用条款保留通知；采用目录分发，不静态链接 |
| PyInstaller | https://pyinstaller.org/en/stable/license.html | GPL带发行例外，保留对应通知 |
| psutil | https://github.com/giampaolo/psutil | BSD-3-Clause |

模型官方说明：
- https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker
- https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker

固定版本模型下载链接与SHA-256记录在 `models/manifest.json`。
模型分发条款应以模型卡及官方上游实际许可为准，不能仅凭网页内容许可认定所有权重使用条件。正式发布前需完成模型卡授权核对与第三方通知检查。
工程提供 `tools/collect_licenses.py` 收集已安装分发包的许可证文本与来源元数据，随发布包提供。
