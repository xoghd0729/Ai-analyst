// 표시용 텍스트에서 이모지·국기를 제거한다. (백엔드 원문/로직은 그대로 두고 화면에서만 정리)
export const noEmoji = (t) =>
  String(t ?? '')
    .replace(/[\p{Extended_Pictographic}\p{Regional_Indicator}️‍]+\s?/gu, '')
    .trim()
