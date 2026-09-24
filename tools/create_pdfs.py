"""从工程文档生成阶段PDF；不生成虚构试验结果。"""
from pathlib import Path
import html
import json
import os
import re
import xml.etree.ElementTree as ET

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf"


def init():
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    pdfmetrics.registerFont(TTFont("CJK", str(font), subfontIndex=0))
    OUTPUT.mkdir(parents=True, exist_ok=True)


def style(size=10.5, leading=17, after=8):
    return ParagraphStyle(f"s{size}", fontName="CJK", fontSize=size, leading=leading,
                          textColor=colors.HexColor("#203447"), spaceAfter=after,
                          wordWrap="CJK", alignment=TA_LEFT)


def para(text, size=10.5):
    return Paragraph(html.escape(text), style(size, size * 1.65))


def markdown(path):
    blocks = []
    for raw in path.read_text(encoding="utf-8").split("\n\n"):
        text = raw.strip()
        if not text:
            continue
        if text.startswith("# "):
            continue
        if text.startswith("## "):
            blocks.append(Paragraph(html.escape(text[3:]), ParagraphStyle("heading", parent=style(14, 23, 10), keepWithNext=True)))
        elif text.startswith("|"):
            for line in text.splitlines():
                if not re.match(r"^[|\s:\-]+$", line):
                    blocks.append(para(line.replace("|", "  ")))
        else:
            blocks.append(para(text.replace("\n", " ").replace("`", "")))
    return blocks


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("CJK", 8)
    canvas.setFillColor(colors.HexColor("#6b7c8a"))
    canvas.drawString(45, 27, "坐伴 · 开发阶段材料 · 真人效果待验证")
    canvas.drawRightString(A4[0] - 45, 27, str(doc.page))
    canvas.restoreState()


def build(name, title, blocks):
    doc = SimpleDocTemplate(str(OUTPUT / name), pagesize=A4, leftMargin=45, rightMargin=45,
                           topMargin=43, bottomMargin=48, title=title, author="")
    doc.build([para(title, 22), Spacer(1, 12), *blocks], onFirstPage=footer, onLaterPages=footer)


def main():
    init()
    build("坐伴-技术说明.pdf", "坐伴技术说明", [
        para("本材料描述已实现的Windows桌面原型、核心算法、接口和限制，供开发复核与比赛方案撰写使用。真实识别性能、用户效果和第二台电脑兼容性仍需按实验流程验证。"),
        *markdown(ROOT / "docs" / "算法与架构.md")])
    junit = ET.parse(ROOT / "output" / "pytest.xml").getroot()
    suites = list(junit.iter("testsuite"))
    tests = sum(int(s.attrib.get("tests", 0)) for s in suites)
    failures = sum(int(s.attrib.get("failures", 0)) + int(s.attrib.get("errors", 0)) for s in suites)
    benchmark = json.loads((ROOT / "output" / "benchmark.json").read_text(encoding="utf-8"))
    check = json.loads((ROOT / "output" / "model-check.json").read_text(encoding="utf-8"))
    checks = [
        para("本报告只记载本轮已执行的工程验证，不将自动化测试或空画面性能替代真人动作识别试验。"),
        para("已执行检查", 15),
        para(f"自动化测试：{tests}项，失败或错误{failures}项。覆盖连续计时、恢复、暂停、冷却、独立有效性、过期结果、校准、角度数学约定、统计并集、存储和界面生命周期。"),
        para(f"模型检查：{check['model_load']}。两模型在CPU上加载成功，空画面不输出有效姿态。"),
        para("界面检查：离屏启动不访问摄像头，检查中文字体、监测页面、三个标签页与会话结束流程。"),
        para("Windows打包检查：运行发布目录中的ZuoBan.exe，模型CPU加载与离屏界面启动均返回0并产生新结果。已修复绘图库遗漏与ICU动态库冲突；该检查仅代表本机，不替代第二台电脑验收。"),
        para("空画面CPU基准", 15),
        para(f"输入：黑色640×480图像，共{benchmark['frames']}帧；没有真人，因此不包含完整人脸/人体关键点成功跟踪的典型工作负载。"),
        para(f"CPU标识：{benchmark['cpu']}；逻辑处理器：{benchmark['logical_processors']}。"),
        para(f"离线推理速度：{benchmark['inference_fps']:.1f}帧/秒；推理耗时中位数：{benchmark['latency_ms_p50']:.2f}毫秒；P95：{benchmark['latency_ms_p95']:.2f}毫秒；进程峰值RSS：{benchmark['peak_rss_mb']:.1f}MB。"),
        para("以上速度不含相机和界面开销，也不是软件运行时的目标采样频率。软件默认每秒约10组；真实有效覆盖率、检出率、误提醒次数尚无结论。"),
        para("未完成验证与下一步", 15),
        para("待真人核对低头/抬头符号，分别验证三项动作、组合动作与干扰；待5—8名参与者试用、独立测试、60分钟实机运行及第二台电脑离线验收。打包自检的详细结果见output中的独立记录。"),
        para("完整流程见docs/真人验证与实验记录.md。未完成项不能在参赛材料中写成通过；当前阈值均为工程起点。"),
    ]
    build("坐伴-阶段测试报告.pdf", "坐伴阶段测试报告", checks)
    print("Created 2 PDFs")


if __name__ == "__main__":
    main()
