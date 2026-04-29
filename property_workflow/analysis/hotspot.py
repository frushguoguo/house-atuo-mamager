from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any


def _price_bucket(total_price_wan: float) -> str:
    if total_price_wan < 300:
        return "<300万"
    if total_price_wan < 500:
        return "300-500万"
    if total_price_wan < 800:
        return "500-800万"
    return "800万+"


def build_hotspot_report(clean_rows: list[dict[str, Any]]) -> dict[str, Any]:
    district_prices: dict[str, list[float]] = defaultdict(list)
    district_unit_prices: dict[str, list[int]] = defaultdict(list)
    community_counter: Counter[str] = Counter()
    bucket_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()

    for row in clean_rows:
        district = str(row.get("district", "未知区域"))
        total = float(row.get("total_price_wan", 0))
        unit = int(row.get("unit_price_yuan", 0))
        source = str(row.get("source", "unknown"))
        community = str(row.get("community", "未知小区"))

        district_prices[district].append(total)
        district_unit_prices[district].append(unit)
        community_counter[community] += 1
        bucket_counter[_price_bucket(total)] += 1
        source_counter[source] += 1

    district_rank = []
    for district, totals in district_prices.items():
        district_rank.append(
            {
                "district": district,
                "listing_count": len(totals),
                "avg_total_price_wan": round(mean(totals), 2),
                "avg_unit_price_yuan": int(mean(district_unit_prices[district])),
            }
        )
    district_rank.sort(key=lambda x: (x["listing_count"], x["avg_unit_price_yuan"]), reverse=True)

    top_communities = [
        {"community": name, "listing_count": count}
        for name, count in community_counter.most_common(10)
    ]

    return {
        "summary": {
            "total_listings": len(clean_rows),
            "district_count": len(district_rank),
            "source_distribution": dict(source_counter),
        },
        "district_hotspots": district_rank,
        "price_bucket_distribution": dict(bucket_counter),
        "top_communities": top_communities,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = []
    summary = report["summary"]
    lines.append("# 房源热点分析报告")
    lines.append("")
    lines.append(f"- 样本总量: {summary['total_listings']}")
    lines.append(f"- 覆盖区域数: {summary['district_count']}")
    lines.append(f"- 数据源分布: {summary['source_distribution']}")
    lines.append("")
    lines.append("## 区域热度排行")
    for item in report["district_hotspots"]:
        lines.append(
            f"- {item['district']}: {item['listing_count']}套, "
            f"均价{item['avg_total_price_wan']}万, 单价{item['avg_unit_price_yuan']}元/平"
        )
    lines.append("")
    lines.append("## 价格区间分布")
    for bucket, count in report["price_bucket_distribution"].items():
        lines.append(f"- {bucket}: {count}套")
    lines.append("")
    lines.append("## 热门小区 Top10")
    for item in report["top_communities"]:
        lines.append(f"- {item['community']}: {item['listing_count']}套")
    lines.append("")
    return "\n".join(lines)

