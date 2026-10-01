"""冷链探头读数判定：摄氏温度不超过该厢线合格上限为合格，否则超温。"""


def judge_temp(temp_c: float, limit_c: float) -> tuple[str, str]:
    if temp_c <= limit_c:
        return "合格", f"探头温度未超过 {limit_c:g}℃ 厢线上限"
    return "超温", f"探头温度超过 {limit_c:g}℃ 厢线合格上限"


def verdict_for_display(verdict: str | None, status: str) -> str:
    if verdict:
        return verdict
    if status == "pending":
        return "待处理"
    if status == "processing":
        return "处理中"
    return "—"
