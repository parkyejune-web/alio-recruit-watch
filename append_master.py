# -*- coding: utf-8 -*-
"""
수집분을 마스터 파일에 누적한다 (idx 기준 신규만).

"매일 아침 새로 올라온 것만" 이라는 요구의 실체는 결국 이것 하나다:
  이미 본 공고인지 아닌지를 판정할 안정적인 키가 있는가.
잡알리오는 체크박스 value 에 공고 고유 idx 가 들어 있어서 그것을 키로 쓴다.
(제목·기관명 조합으로 판정하면 재공고·수정공고에서 깨진다)
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MASTER = HERE / "data" / "master.csv"
NEWFILE = HERE / "data" / "신규_최근.csv"


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "alio_공고.csv")
    rows = list(csv.DictReader(src.open(encoding="utf-8-sig")))
    today = datetime.now().strftime("%Y-%m-%d")

    old, seen = [], set()
    if MASTER.exists():
        old = list(csv.DictReader(MASTER.open(encoding="utf-8-sig")))
        seen = {r["idx"] for r in old}

    fresh = [r for r in rows if r["idx"] not in seen]
    for r in fresh:
        r["최초수집일"] = today

    cols = list(rows[0].keys()) + ["최초수집일"] if rows else []
    if old:
        for c in old[0].keys():
            if c not in cols:
                cols.append(c)

    MASTER.parent.mkdir(parents=True, exist_ok=True)
    with MASTER.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(old + fresh)

    with NEWFILE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(fresh)

    print(f"누적 {len(old)}건 + 신규 {len(fresh)}건 = {len(old)+len(fresh)}건")
    print(f"신규 목록 -> {NEWFILE.name}")
    for r in fresh[:5]:
        print(f"  + [{r['기관명']}] {r['제목'][:40]}")


if __name__ == "__main__":
    main()
