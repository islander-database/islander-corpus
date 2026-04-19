#!/usr/bin/env python3
"""
sync_metadata.py — 從 text/ 下所有 .md 檔的 front-matter 自動產生中央 metadata。

設計理念：
- 每個 .md 檔的 YAML front-matter 是 single source of truth
- 中央 metadata/islander_metadata.yaml 和 .csv 都是從檔案聚合而成
- 修改語料 metadata 時，編輯檔案 front-matter，再重跑此腳本

用法：
    python3 scripts/sync_metadata.py
"""
import csv
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEXT_DIR = ROOT / "text"
META_DIR = ROOT / "metadata"
YAML_OUT = META_DIR / "islander_metadata.yaml"
CSV_OUT = META_DIR / "islander_metadata.csv"

# 特殊處理：已撤下但保留 metadata 紀錄的檔案
WITHDRAWN_ENTRIES = [
    {
        "id": "00002",
        "title": "白腹秧雞之死",
        "author": "胡語居士",
        "date": "2024-09-25",
        "created": "2025-05-17",
        "tags": ["生命教育", "鳥類觀察", "校園隨筆", "情感書寫", "文化筆記"],
        "license": "CC-BY-NC-SA-4.0",
        "filepath": "text/文化筆記/00002_白腹秧雞之死.md",
        "status": "withdrawn",
        "notes": "暫時撤下，作者投稿他處中",
    },
]

# 特殊處理：授權狀態待確認
AUTHORIZATION_OVERRIDES = {
    "賴武忠": "pending_family_consent",
}


def parse_front_matter(content: str) -> tuple[dict, str]:
    """從 .md 內容抽出 YAML front-matter 和正文。回傳 (front_matter dict, body str)。"""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        print(f"⚠️ YAML parse 失敗：{e}", file=sys.stderr)
        return {}, content
    return fm, parts[2].lstrip("\n")


def extract_id_from_filename(filename: str) -> str | None:
    """從 {id}_{title}.md 抽出 id。支援 00001 或 s0001 格式。"""
    m = re.match(r"^(\d{5}|[a-z]\d{4})_", filename)
    return m.group(1) if m else None


def build_entry(file_path: Path) -> dict | None:
    """從單一 .md 檔產生 metadata 紀錄。"""
    rel_path = file_path.relative_to(ROOT)
    file_id = extract_id_from_filename(file_path.name)
    if file_id is None:
        print(f"⚠️ 跳過（檔名不符規則）：{rel_path}", file=sys.stderr)
        return None

    content = file_path.read_text(encoding="utf-8")
    fm, _body = parse_front_matter(content)

    if not fm:
        print(f"⚠️ 跳過（無 front-matter）：{rel_path}", file=sys.stderr)
        return None

    entry = {
        "id": file_id,
        "title": fm.get("title", file_path.stem.split("_", 1)[1] if "_" in file_path.stem else file_path.stem),
        "author": fm.get("author", "胡語居士"),
        "date": fm.get("date"),
        "created": fm.get("created"),
        "tags": fm.get("tags", []),
        "license": fm.get("license", "CC-BY-NC-SA-4.0"),
        "filepath": str(rel_path).replace("\\", "/"),
    }
    # 選用欄位
    if "source" in fm:
        entry["source"] = fm["source"]
    if "notes" in fm:
        entry["notes"] = fm["notes"]

    # 套用授權狀態 override
    if entry["author"] in AUTHORIZATION_OVERRIDES:
        entry["authorization_status"] = AUTHORIZATION_OVERRIDES[entry["author"]]

    return entry


def normalize_for_yaml(entries: list[dict]) -> str:
    """產生符合 SKILL.md 規範的 YAML 字串：id 加雙引號、tags 陣列加雙引號。"""
    lines = []
    for e in entries:
        lines.append(f'- id: "{e["id"]}"')
        lines.append(f'  title: {e["title"]}')
        lines.append(f'  author: {e["author"]}')
        if e.get("date"):
            lines.append(f'  date: {e["date"]}')
        if e.get("created"):
            lines.append(f'  created: {e["created"]}')
        # tags
        tags = e.get("tags") or []
        tags_str = ", ".join(f'"{t}"' for t in tags)
        lines.append(f'  tags: [{tags_str}]')
        lines.append(f'  license: {e["license"]}')
        lines.append(f'  filepath: {e["filepath"]}')
        if e.get("source"):
            lines.append(f'  source: {e["source"]}')
        if e.get("notes"):
            lines.append(f'  notes: {e["notes"]}')
        if e.get("authorization_status"):
            lines.append(f'  authorization_status: {e["authorization_status"]}')
        if e.get("status"):
            lines.append(f'  status: {e["status"]}')
    return "\n".join(lines) + "\n"


def write_csv(entries: list[dict], path: Path):
    """寫入 CSV 索引。tags 用 | 分隔，便於匯入試算表。"""
    fieldnames = [
        "id", "title", "author", "date", "created", "tags",
        "license", "filepath", "source", "notes",
        "authorization_status", "status",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for e in entries:
            row = dict(e)
            row["tags"] = "|".join(e.get("tags") or [])
            w.writerow(row)


def main():
    files = sorted(TEXT_DIR.rglob("*.md"))
    entries = []
    for fp in files:
        e = build_entry(fp)
        if e:
            entries.append(e)

    # 加入已撤下檔案的紀錄
    entries.extend(WITHDRAWN_ENTRIES)

    # 排序：純數字 id 優先，s 系列在後
    def sort_key(e):
        eid = e["id"]
        if eid.isdigit():
            return (0, int(eid))
        return (1, eid)
    entries.sort(key=sort_key)

    # 檢查 id 重複
    seen = {}
    for e in entries:
        if e["id"] in seen:
            print(f"❌ ID 重複：{e['id']}", file=sys.stderr)
            print(f"   {seen[e['id']]['filepath']}", file=sys.stderr)
            print(f"   {e['filepath']}", file=sys.stderr)
        seen[e["id"]] = e

    yaml_str = normalize_for_yaml(entries)
    YAML_OUT.write_text(yaml_str, encoding="utf-8")
    write_csv(entries, CSV_OUT)

    # 統計
    by_author = {}
    for e in entries:
        by_author[e["author"]] = by_author.get(e["author"], 0) + 1
    print(f"✅ 產出 {len(entries)} 筆 metadata")
    print(f"   YAML → {YAML_OUT.relative_to(ROOT)}")
    print(f"   CSV  → {CSV_OUT.relative_to(ROOT)}")
    print(f"\n作者分布：")
    for author, n in sorted(by_author.items(), key=lambda x: -x[1]):
        print(f"   {author:<12} {n}")


if __name__ == "__main__":
    main()
