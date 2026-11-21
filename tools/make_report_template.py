"""報告用スプレッドシートの雛形（xlsx）を作る。Googleドライブにアップすると自動でスプレッドシートに変換される。"""
import sys
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

NAVY, GOLD, LIGHT = "0B3D91", "F5A623", "EEF2F9"
head_font = Font(bold=True, color="FFFFFF")
head_fill = PatternFill("solid", fgColor=NAVY)

SHEETS = {
    "ダッシュボード": None,
    "日次推移": ["日付", "Xフォロワー", "X増減", "IGフォロワー", "IG増減", "合計フォロワー", "X投稿数", "Xインプレッション",
                 "Xいいね", "Xリポスト", "Xブックマーク", "X返信", "IG投稿数", "IGリーチ", "IG再生数", "IGいいね",
                 "IG保存", "IGシェア", "IGコメント", "メモ"],
    "投稿別": ["投稿日時", "SNS", "形式", "テーマ", "狙い", "内容（冒頭）", "インプ/リーチ", "再生数", "いいね",
               "保存/ブックマーク", "シェア/リポスト", "コメント/返信", "エンゲージ率", "スコア", "使用素材", "URL"],
    "週次サマリー": ["週", "期間", "Xフォロワー増", "IGフォロワー増", "合計フォロワー", "Xインプ合計", "IGリーチ合計",
                   "いいね合計", "保存合計", "シェア合計", "一番伸びた投稿", "伸びた理由（AI分析）", "来週試すこと"],
    "テーマ別": ["集計期間", "テーマ", "SNS", "投稿数", "平均インプ/リーチ", "平均いいね", "平均保存", "平均エンゲージ率", "平均スコア"],
}
WIDTH = {"内容（冒頭）": 46, "一番伸びた投稿": 40, "伸びた理由（AI分析）": 50, "来週試すこと": 50, "URL": 36, "使用素材": 28, "メモ": 30}

wb = Workbook()
wb.remove(wb.active)
for name, cols in SHEETS.items():
    ws = wb.create_sheet(name)
    if cols is None:
        continue
    for i, c in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=i, value=c)
        cell.font, cell.fill = head_font, head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = WIDTH.get(c, 14)
    ws.freeze_panes = "B2"
    ws.row_dimensions[1].height = 32

ws = wb["ダッシュボード"]
ws.column_dimensions["A"].width = 28
for col in "BCDE":
    ws.column_dimensions[col].width = 18
ws["A1"] = "SNS運用レポート（X / Instagram）"
ws["A1"].font = Font(bold=True, size=18, color=NAVY)
ws["A2"] = "毎日23時台に自動更新されます。週次の分析は毎週月曜に追加されます。"
ws["A2"].font = Font(color="666666")
rows = [
    ("", "X", "Instagram", "合計", ""),
    ("フォロワー（最新）", "-", "-", "-", ""),
    ("フォロワー増減（直近7日）", "-", "-", "-", ""),
    ("フォロワー増減（直近30日）", "-", "-", "-", ""),
    ("インプ/リーチ（直近7日）", "-", "-", "-", ""),
    ("いいね（直近7日）", "-", "-", "-", ""),
    ("保存・ブックマーク（直近7日）", "-", "-", "-", ""),
    ("エンゲージ率（直近7日）", "-", "-", "-", ""),
    ("最終更新", "-", "", "", ""),
]
for r, row in enumerate(rows, start=4):
    for c, v in enumerate(row, start=1):
        cell = ws.cell(row=r, column=c, value=v)
        if r == 4 and v:
            cell.font, cell.fill = head_font, head_fill
            cell.alignment = Alignment(horizontal="center")
        elif c == 1 and v:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor=LIGHT)
ws["A14"] = "今週のハイライト（AI分析）"
ws["A14"].font = Font(bold=True, size=13, color=NAVY)
ws["A15"] = "データがたまると自動で書き込まれます。"
ws["A15"].alignment = Alignment(wrap_text=True, vertical="top")
ws.merge_cells("A15:E22")

wb.save(sys.argv[1])
print("saved", sys.argv[1])
