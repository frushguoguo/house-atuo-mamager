from __future__ import annotations

from typing import Any


def generate_copy_variants(listing: dict[str, Any], style: str = "专业可信", n: int = 3) -> list[str]:
    district = listing["district"]
    community = listing["community"]
    layout = listing["layout"]
    area = listing["area_sqm"]
    total = listing["total_price_wan"]
    unit = listing.get("unit_price_yuan", 0)
    tags = "、".join(listing.get("tags", [])) or "交通便利"

    base = [
        f"{district}{community} {layout}，约{area}平，总价{total}万，标签：{tags}。",
        f"核心卖点：户型方正、采光稳定，当前约{unit}元/平，适合首次置业与改善。",
        f"{style}推荐：该房源位于{district}核心板块，生活配套成熟，带看效率高。",
        f"看房建议：重点关注楼层采光与近30天同小区成交节奏，可快速判断议价空间。",
    ]
    variants = []
    for i in range(n):
        prefix = f"版本{i + 1}"
        variants.append(f"{prefix} | {base[i % len(base)]}")
    return variants


def generate_batch_copy(clean_rows: list[dict[str, Any]], style: str, top_n: int) -> list[dict[str, Any]]:
    selected = clean_rows[:top_n]
    payload = []
    for row in selected:
        payload.append(
            {
                "listing_id": row["listing_id"],
                "title": row["title"],
                "variants": generate_copy_variants(row, style=style, n=3),
            }
        )
    return payload

