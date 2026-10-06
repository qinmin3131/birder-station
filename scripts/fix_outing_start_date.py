#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 outings 表中 start_date 被误存为导入日期的历史数据。

背景：`src/web/import_service.py::_create_outing` 历史上把 start_date
硬编码为 `datetime.now()`（导入当天日期），而非从文件夹名解析出的
拍摄日期。2026-09-28 已修正为按文件夹名解析；本脚本用于一次性回填
历史 outings 的 start_date，使其反映真实拍摄日期。

用法：
    python scripts/fix_outing_start_date.py            # 执行修复
    python scripts/fix_outing_start_date.py --dry-run  # 只预览不写入
    python scripts/fix_outing_start_date.py --db-path "自定义路径/birder.db"
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.io.path_parser import PathParser


def parse_args():
    parser = argparse.ArgumentParser(description="回填 outings.start_date 为文件夹名解析出的拍摄日期")
    parser.add_argument("--db-path", default="data/birder.db",
                        help="数据库文件路径 (默认: data/birder.db)")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示将要修改的内容，不实际写入")
    return parser.parse_args()


def main():
    args = parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"错误: 数据库文件不存在 - {db_path}")
        sys.exit(1)

    print(f"连接数据库: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, name, start_date, end_date FROM outings ORDER BY id"
    ).fetchall()
    print(f"共 {len(rows)} 条外拍记录\n")

    to_fix = []
    skipped = 0
    for r in rows:
        parsed_start, parsed_end, _ = PathParser.parse_folder_name(r["name"])
        current = r["start_date"]
        if not parsed_start:
            # 文件夹名不含可解析日期（如 "testdata"、"燕隼"），保留原值
            print(f"  [跳过] id={r['id']} name={r['name']!r} 无法从名称解析日期，保留 start_date={current!r}")
            skipped += 1
            continue
        if parsed_start == current and (not parsed_end or parsed_end == r["end_date"]):
            print(f"  [无需修改] id={r['id']} name={r['name']!r} start_date={current!r}")
            continue
        to_fix.append({
            "id": r["id"],
            "name": r["name"],
            "old_start": current,
            "new_start": parsed_start,
            "old_end": r["end_date"],
            "new_end": parsed_end if parsed_end else r["end_date"],
        })
        print(f"  [待修复] id={r['id']} name={r['name']!r} "
              f"start_date: {current!r} -> {parsed_start!r}"
              + (f", end_date: {r['end_date']!r} -> {parsed_end!r}" if parsed_end and parsed_end != r['end_date'] else ""))

    print(f"\n汇总: {len(to_fix)} 条待修复, {skipped} 条跳过(无日期前缀), {len(rows) - len(to_fix) - skipped} 条无需修改")

    if not to_fix:
        print("没有需要修复的记录")
        conn.close()
        return

    if args.dry_run:
        print("\n[DRY-RUN 模式] 未执行实际修改")
        conn.close()
        return

    print("\n开始写入...")
    for item in to_fix:
        conn.execute(
            "UPDATE outings SET start_date = ?, end_date = ? WHERE id = ?",
            (item["new_start"], item["new_end"], item["id"]),
        )
        print(f"  已更新 id={item['id']}: start_date {item['old_start']!r} -> {item['new_start']!r}"
              + (f", end_date {item['old_end']!r} -> {item['new_end']!r}" if item['new_end'] != item['old_end'] else ""))
    conn.commit()
    conn.close()
    print(f"\n修复完成: 共更新 {len(to_fix)} 条记录")


if __name__ == "__main__":
    main()
