"""Generate the demo workspace's business data: two months of raw operations exports.

Why this exists
---------------
The office take's story is "the agent reads real material and reports on it".
Numbers invented inside a single run cannot be compared month over month, so the
raw exports are generated once, deterministically, and staged into the demo
workspace ahead of the takes.  The intended findings are baked into the data so
the resulting report has something true to say:

* overall September revenue is up ~12% versus August, pulled by 私域社群 and the
  中秋 gift season on 礼盒套装;
* 信息流投放 spend grows much faster than the revenue it brings, so its ROI
  drops from ~3.1 to ~2.8;
* 车载香氛 refund rate rises from 3.2% to 5.1% (a quality-batch story).

Usage
-----
    py -3.14 scripts/demo-video/fixtures/make-business-data.py
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from random import Random

OUT = Path(__file__).resolve().parent / "business-review"

CHANNELS = ["自然流量", "信息流投放", "私域社群", "老客复购"]

# base daily orders per channel, and per-category price / margin
CATEGORIES = {
    "香薰蜡烛": {"price": 168, "margin": {8: 0.55, 9: 0.54}},
    "家居香氛": {"price": 219, "margin": {8: 0.52, 9: 0.52}},
    "车载香氛": {"price": 128, "margin": {8: 0.48, 9: 0.47}},
    "礼盒套装": {"price": 366, "margin": {8: 0.58, 9: 0.59}},
    "配件耗材": {"price": 69, "margin": {8: 0.42, 9: 0.42}},
}

BASE_ORDERS = {
    "自然流量": {"香薰蜡烛": 18, "家居香氛": 12, "车载香氛": 20, "礼盒套装": 4, "配件耗材": 14},
    "信息流投放": {"香薰蜡烛": 12, "家居香氛": 8, "车载香氛": 16, "礼盒套装": 3, "配件耗材": 6},
    "私域社群": {"香薰蜡烛": 6, "家居香氛": 5, "车载香氛": 4, "礼盒套装": 5, "配件耗材": 7},
    "老客复购": {"香薰蜡烛": 5, "家居香氛": 4, "车载香氛": 6, "礼盒套装": 2, "配件耗材": 9},
}

# month-over-month demand growth per channel (September vs August)
SEP_CHANNEL_GROWTH = {"自然流量": 1.10, "信息流投放": 1.08, "私域社群": 1.22, "老客复购": 1.15}

# ad spend as a share of that channel's revenue
AD_SPEND_RATIO = {"自然流量": {8: 0.0, 9: 0.0}, "信息流投放": {8: 0.32, 9: 0.38},
                  "私域社群": {8: 0.06, 9: 0.06}, "老客复购": {8: 0.04, 9: 0.04}}

# refund rate per category per month; 车载香氛's September jump is the batch story
REFUND_RATE = {
    8: {"香薰蜡烛": 0.028, "家居香氛": 0.024, "车载香氛": 0.032, "礼盒套装": 0.018, "配件耗材": 0.021},
    9: {"香薰蜡烛": 0.027, "家居香氛": 0.025, "车载香氛": 0.051, "礼盒套装": 0.017, "配件耗材": 0.022},
}

PROMOS = [
    # (start, end, channel multipliers)
    (date(2026, 8, 18), date(2026, 8, 24), {"信息流投放": 1.6, "私域社群": 1.3}),
    (date(2026, 9, 15), date(2026, 9, 21), {"信息流投放": 1.5, "私域社群": 1.5, "老客复购": 1.2}),
]

MID_AUTUMN = (date(2026, 9, 19), date(2026, 9, 25))  # 中秋礼赠档, 礼盒 driven
POST_HOLIDAY = (date(2026, 9, 26), date(2026, 9, 30))  # 节后回落


def month_days(month: int) -> list[date]:
    ndays = 31 if month == 8 else 30
    return [date(2026, month, day) for day in range(1, ndays + 1)]


def day_multiplier(day: date, channel: str, category: str, month: int) -> float:
    m = 1.0
    if day.weekday() >= 5:  # Sat / Sun
        m *= 1.35
    elif day.weekday() == 4:  # Fri
        m *= 1.15
    for start, end, channels in PROMOS:
        if start <= day <= end and channel in channels:
            m *= channels[channel]
    if month == 9:
        m *= SEP_CHANNEL_GROWTH[channel]
        if category == "礼盒套装":
            if MID_AUTUMN[0] <= day <= MID_AUTUMN[1]:
                m *= 2.8
            elif POST_HOLIDAY[0] <= day <= POST_HOLIDAY[1]:
                m *= 0.5
    return m


def write_month(rng: Random, month: int) -> None:
    path = OUT / f"2026-0{month}-经营明细.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["日期", "渠道", "品类", "订单数", "收入", "退款金额", "广告花费", "毛利"])
        for day in month_days(month):
            for channel in CHANNELS:
                for cat, info in CATEGORIES.items():
                    base = BASE_ORDERS[channel][cat]
                    orders = round(base * day_multiplier(day, channel, cat, month)
                                   * rng.uniform(0.92, 1.08))
                    if orders <= 0:
                        continue
                    revenue = orders * info["price"] * rng.uniform(0.94, 1.06)
                    refund = revenue * REFUND_RATE[month][cat]
                    ad = revenue * AD_SPEND_RATIO[channel][month]
                    gross = (revenue - refund) * info["margin"][month]
                    w.writerow([day.isoformat(), channel, cat, orders,
                                round(revenue, 2), round(refund, 2),
                                round(ad), round(gross, 2)])


CALDOC = """# 经营数据口径说明

本目录是渠道/品类经营明细的原始导出，按「日期 × 渠道 × 品类」一行记录。

## 字段口径

| 字段 | 口径 |
|------|------|
| 订单数 | 当日该渠道、该品类的支付订单数 |
| 收入 | 下单金额合计（未扣退款） |
| 退款金额 | 当月发生的退款，按原渠道计入 |
| 净收入 | 收入 − 退款金额 |
| 广告花费 | 该渠道当日的投放消耗（自然流量为 0） |
| 毛利 | 已扣商品成本后的毛利额（不含广告费） |
| 毛利率 | 毛利 ÷ 净收入 |
| 客单价 | 收入 ÷ 订单数 |

## 档期备注

- 08-18 ~ 08-24：夏末清仓（信息流投放、私域社群加投）
- 09-15 ~ 09-21：秋日上新（信息流投放、私域社群加投，老客复购联动）
- 09-19 ~ 09-25：中秋礼赠档（礼盒套装为主力）
- 中秋节为 2026-09-25，节后礼盒需求回落属正常节奏
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = Random(20260930)
    for month in (8, 9):
        write_month(rng, month)
    (OUT / "口径说明.md").write_text(CALDOC, encoding="utf-8")

    # print the aggregates the report is expected to find, as a sanity check
    def load(month: int) -> list[dict]:
        with (OUT / f"2026-0{month}-经营明细.csv").open(encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    aug, sep = load(8), load(9)
    def agg(rows):
        rev = sum(float(r["收入"]) for r in rows)
        refund = sum(float(r["退款金额"]) for r in rows)
        gross = sum(float(r["毛利"]) for r in rows)
        orders = sum(int(r["订单数"]) for r in rows)
        return rev, refund, gross, orders

    for name, rows in (("8月", aug), ("9月", sep)):
        rev, refund, gross, orders = agg(rows)
        print(f"{name}: 收入 {rev:,.0f}  净收入 {rev - refund:,.0f}  订单 {orders:,}"
              f"  客单价 {rev / orders:.1f}  毛利率 {gross / (rev - refund):.3f}"
              f"  退款率 {refund / rev:.3f}")
    a = agg(aug); s = agg(sep)
    print(f"收入环比 {(s[0] / a[0] - 1) * 100:+.1f}%   客单价环比 {(s[3] and (s[0]/s[3]) / (a[0]/a[3]) - 1) * 100:+.1f}%")
    for ch in CHANNELS:
        ra = [r for r in aug if r["渠道"] == ch]
        rs = [r for r in sep if r["渠道"] == ch]
        rev_a = sum(float(r["收入"]) for r in ra)
        rev_s = sum(float(r["收入"]) for r in rs)
        ad_a = sum(float(r["广告花费"]) for r in ra)
        ad_s = sum(float(r["广告花费"]) for r in rs)
        roi_a = rev_a / ad_a if ad_a else 0
        roi_s = rev_s / ad_s if ad_s else 0
        print(f"  {ch}: 收入 {rev_a:,.0f} -> {rev_s:,.0f} ({(rev_s / rev_a - 1) * 100:+.1f}%)"
              + (f"  花费 {ad_a:,.0f} -> {ad_s:,.0f}  ROI {roi_a:.2f} -> {roi_s:.2f}" if ad_a else ""))
    for cat in CATEGORIES:
        ra = sum(float(r["退款金额"]) for r in aug if r["品类"] == cat)
        va = sum(float(r["收入"]) for r in aug if r["品类"] == cat)
        rs = sum(float(r["退款金额"]) for r in sep if r["品类"] == cat)
        vs = sum(float(r["收入"]) for r in sep if r["品类"] == cat)
        print(f"  退款率 {cat}: {ra / va:.3f} -> {rs / vs:.3f}")


if __name__ == "__main__":
    main()
