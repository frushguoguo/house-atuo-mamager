from __future__ import annotations

import random
from datetime import datetime, timedelta


def build_synthetic_listings(source: str, city: str, districts: list[str], limit: int) -> list[dict]:
    if not districts:
        districts = ["unknown"]

    communities = [
        "金桥花苑",
        "绿地云湾",
        "春申名都",
        "静安豪景",
        "中远两湾城",
        "花木苑",
        "世纪公园城",
    ]
    layouts = ["1室1厅", "2室1厅", "2室2厅", "3室2厅", "4室2厅"]
    tags_pool = ["满五唯一", "近地铁", "随时看房", "南北通透", "业主急售", "精装修"]

    rows: list[dict] = []
    today = datetime.now()
    rand = random.Random(f"{source}-{city}-{','.join(districts)}-{limit}")

    for i in range(limit):
        district = districts[i % len(districts)]
        community = communities[rand.randrange(len(communities))]
        area = round(rand.uniform(48, 165), 1)
        total = round(rand.uniform(180, 1250), 1)
        listing_id = f"{source}-{district}-{i+1:04d}"
        listed_at = (today - timedelta(days=rand.randrange(180))).date().isoformat()
        tags = rand.sample(tags_pool, k=rand.randint(1, 3))
        title = f"{district}{community}{layouts[rand.randrange(len(layouts))]}优选房源"
        rows.append(
            {
                "listing_id": listing_id,
                "source": source,
                "city": city,
                "district": district,
                "community": community,
                "title": title,
                "layout": layouts[rand.randrange(len(layouts))],
                "area_sqm": area,
                "total_price_wan": total,
                "listed_at": listed_at,
                "url": f"https://{source}.example.com/listing/{listing_id}",
                "tags": tags,
            }
        )
    return rows

