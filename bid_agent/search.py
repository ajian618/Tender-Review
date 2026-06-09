from __future__ import annotations

import sqlite3

from bid_agent import db


DEFAULT_REVIEW_QUERIES = [
    "资格 资质 营业执照 安全生产许可证",
    "资质动态核查 合格 建筑市场监管公共服务系统",
    "项目负责人 建造师 安考 B 社保",
    "企业信用 信用等级 信用中国 行贿犯罪",
    "评分 评标 技术 商务 报价 资信",
    "业绩 证书 人员 机械 施工组织",
]


def collect_review_evidence(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    per_query_limit: int = 8,
) -> list[dict[str, object]]:
    seen: set[int] = set()
    evidence: list[dict[str, object]] = []

    category_limits = {
        "tender": 14,
        "proposal": 24,
        "qualification": 24,
        "performance": 12,
        "credit": 12,
        "commercial": 12,
        "other": 8,
    }
    for category, category_limit in category_limits.items():
        for item in db.list_project_chunks(
            conn,
            project_id,
            category=category,
            limit=category_limit,
        ):
            chunk_id = int(item["chunk_id"])
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            item["query"] = f"category_seed:{category}"
            evidence.append(item)

    for query in DEFAULT_REVIEW_QUERIES:
        for item in db.search_chunks(conn, query, project_id=project_id, limit=per_query_limit):
            chunk_id = int(item["chunk_id"])
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            item["query"] = query
            evidence.append(item)
    return evidence
