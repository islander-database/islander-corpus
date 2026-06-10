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

# 例外紀錄（撤下語料、授權狀態註記）改存 metadata/overrides.yaml，
# 由人工維護，新增例外時編輯該檔即可，不需修改本程式。
OVERRIDES_FILE = META_DIR / "overrides.yaml"

# 必填欄位：front-matter 缺任一項即中止，不寫出索引
REQUIRED_FIELDS = ["title", "author", "date", "created"]


def load_overrides() -> dict:
    """讀取 metadata/overrides.yaml。檔案不存在時回傳空結構。"""
    if not OVERRIDES_FILE.exists():
        return {"withdrawn": [], "authorization_overrides": {}}
    data = yaml.safe_load(OVERRIDES_FILE.read_text(encoding="utf-8")) or {}
    return {
        "withdrawn": data.get("withdrawn") or [],
        "authorization_overrides": data.get("authorization_overrides") or {},
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


def build_entry(file_path: Path, auth_overrides: dict, errors: list[str]) -> dict | None:
    """從單一 .md 檔產生 metadata 紀錄。缺必填欄位時記入 errors。"""
    rel_path = file_path.relative_to(ROOT)
    file_id = extract_id_from_filename(file_path.name)
    if file_id is None:
        errors.append(f"檔名不符規則：{rel_path}")
        return None

    content = file_path.read_text(encoding="utf-8")
    fm, _body = parse_front_matter(content)

    if not fm:
        errors.append(f"無 front-matter：{rel_path}")
        return None

    # 必填欄位檢查：像表單的必填欄，缺了就不給過
    missing = [f for f in REQUIRED_FIELDS if fm.get(f) in (None, "")]
    if not fm.get("tags"):
        print(f"⚠️ tags 為空：{rel_path}", file=sys.stderr)
    if missing:
        errors.append(f"缺必填欄位 {missing}：{rel_path}")
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
    if entry["author"] in auth_overrides:
        entry["authorization_status"] = auth_overrides[entry["author"]]

    return entry


def find_cross_repo_clashes(ids: set[str]) -> list[str]:
    """檢查姊妹庫（限制收錄分庫）的編號是否與本庫重疊。

    兩庫共用主線流水號，撞號會破壞引用唯一性。
    找不到姊妹庫目錄時跳過（例如單獨 clone 本庫的協作者）。
    """
    sibling_text = ROOT.parent / "islander-private-corpus" / "text"
    if not sibling_text.is_dir():
        return []
    other = set()
    for p in sibling_text.rglob("*.md"):
        fid = extract_id_from_filename(p.name)
        if fid:
            other.add(fid)
    return sorted(ids & other)


def normalize_for_yaml(entries: list[dict]) -> str:
    """產生符合 SKILL.md 規範的 YAML 字串：id 加雙引號、tags 陣列加雙引號。

    title/author/source/notes 為自由文字欄位，一律加雙引號並跳脫，
    避免 `[摘要]`、`: ` 等開頭/內容產生非法 YAML。
    """
    def q(value) -> str:
        """雙引號包裹並跳脫反斜線與雙引號。"""
        s = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'

    lines = []
    for e in entries:
        lines.append(f'- id: "{e["id"]}"')
        lines.append(f'  title: {q(e["title"])}')
        lines.append(f'  author: {q(e["author"])}')
        if e.get("date"):
            lines.append(f'  date: {e["date"]}')
        if e.get("created"):
            lines.append(f'  created: {e["created"]}')
        # tags
        tags = e.get("tags") or []
        tags_str = ", ".join(q(t) for t in tags)
        lines.append(f'  tags: [{tags_str}]')
        lines.append(f'  license: {e["license"]}')
        lines.append(f'  filepath: {e["filepath"]}')
        if e.get("source"):
            lines.append(f'  source: {q(e["source"])}')
        if e.get("notes"):
            lines.append(f'  notes: {q(e["notes"])}')
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
    overrides = load_overrides()
    files = sorted(TEXT_DIR.rglob("*.md"))
    entries = []
    errors: list[str] = []
    for fp in files:
        try:
            e = build_entry(fp, overrides["authorization_overrides"], errors)
        except OSError as err:
            errors.append(f"無法讀取：{fp.relative_to(ROOT)} → {err}")
            continue
        if e:
            entries.append(e)

    if errors:
        for msg in errors:
            print(f"❌ {msg}", file=sys.stderr)
        print(f"❌ 共 {len(errors)} 個檔案有問題，已中止，未寫出索引。請修正後重跑。", file=sys.stderr)
        sys.exit(1)

    # 加入已撤下檔案的紀錄（來自 metadata/overrides.yaml）
    entries.extend(overrides["withdrawn"])

    # 排序：純數字 id 優先，s 系列在後
    def sort_key(e):
        eid = e["id"]
        if eid.isdigit():
            return (0, int(eid))
        return (1, eid)
    entries.sort(key=sort_key)

    # 檢查 id 重複：發現重複即中止，不寫出索引
    seen = {}
    has_dup = False
    for e in entries:
        if e["id"] in seen:
            has_dup = True
            print(f"❌ ID 重複：{e['id']}", file=sys.stderr)
            print(f"   {seen[e['id']]['filepath']}", file=sys.stderr)
            print(f"   {e['filepath']}", file=sys.stderr)
        seen[e["id"]] = e
    if has_dup:
        print("❌ 偵測到重複 id，已中止，未寫出索引。請先改號再重跑。", file=sys.stderr)
        sys.exit(1)

    # 跨庫撞號檢查
    clashes = find_cross_repo_clashes(set(seen.keys()))
    if clashes:
        print(f"❌ 與限制收錄分庫撞號：{clashes}", file=sys.stderr)
        print("❌ 兩庫共用主線流水號，請改號後重跑。已中止，未寫出索引。", file=sys.stderr)
        sys.exit(1)

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
