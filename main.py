"""入口。--self-check不会打开摄像头；--ui-smoke执行无摄像头界面检查。"""
from pathlib import Path
import argparse
import json
import os
import sys


def main():
    os.environ.setdefault("MPLBACKEND", "Agg")
    parser = argparse.ArgumentParser(description="坐伴：本地姿态提醒")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--ui-smoke", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    models = root / "models"
    if args.self_check:
        import numpy as np
        from zuoban.vision import Detector
        detector = Detector(models)
        try:
            m, _ = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8), 1.0)
            result = {"model_load": "passed", "cpu": True, "blank_frame": m.values,
                      "note": "模型加载及空画面检查，不代表真实姿态准确率"}
        finally:
            detector.close()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.ui_smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, QLockFile
    from zuoban.ui import Window
    data = args.data_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ZuoBan"
    data.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv[:1])
    # Windows的offscreen平台不会总是枚举系统中文字体，显式注册供GUI测试及显示使用。
    from PySide6.QtGui import QFontDatabase, QFont
    for name in ("msyh.ttc", "msyhbd.ttc"):
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Microsoft YaHei", 10))
    lock = QLockFile(str(data / "app.lock"))
    if not lock.tryLock(100):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, "坐伴", "这个数据目录已有坐伴在运行，请使用已打开的窗口。")
        return 1
    window = Window(models, data)
    window.show()
    if args.ui_smoke:
        def snapshot():
            output = args.output or Path("output/ui-smoke.png")
            output.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(output))
            window.close()
        QTimer.singleShot(700, snapshot)
    return app.exec()


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        import traceback
        trace = traceback.format_exc()
        if "--output" in sys.argv:
            target = Path(sys.argv[sys.argv.index("--output") + 1]).with_suffix(".error.txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(trace, encoding="utf-8")
        if sys.stderr is not None:
            sys.stderr.write(trace)
        if not any(flag in sys.argv for flag in ("--self-check", "--ui-smoke")):
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(None, "坐伴启动失败", trace)
        code = 1
    raise SystemExit(code)
