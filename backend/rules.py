"""冷链探头读数判定：摄氏温度不超过领单时抄录的厢线上限为合格，否则超温。"""

DEFAULT_LIMIT_C = 8.0


def judge_temp(temp_c: float, limit_c: float = DEFAULT_LIMIT_C) -> tuple[str, str]:
    if temp_c <= limit_c:
        return "合格", f"探头温度 {temp_c:g}℃ 未超过该厢线上限 {limit_c:g}℃"
    return "超温", f"探头温度 {temp_c:g}℃ 超过该厢线上限 {limit_c:g}℃"


def verdict_for_display(verdict: str | None, status: str) -> str:
    if verdict:
        return verdict
    if status == "pending":
        return "待处理"
    if status == "processing":
        return "处理中"
    return "—"
