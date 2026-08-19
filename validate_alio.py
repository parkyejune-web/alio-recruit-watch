# -*- coding: utf-8 -*-
"""
잡알리오 수집 결과 품질검증 리포트

왜 필요한가
  수집기는 **틀린 값도 성공이라고 보고한다.** 실제로 겪은 것:
   · 제목 10/10 전부 빈 문자열인데 "10행 수집" 정상 출력
   · 다른 사이트에서 69% 유실인데 로그는 끝까지 "성공 12/12"
  그래서 "돌았다"가 아니라 "결과가 맞다"를 따로 검사한다.

  통과하면 이 리포트를 고객에게 그대로 준다. 실패하면 납품하지 않는다.

사용법
  python validate_alio.py                       # alio_공고.csv + alio_run.json
  python validate_alio.py --csv x.csv --log x.json --out 리포트.md
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIRED = ["idx", "제목", "기관명", "등록일", "마감일", "상태", "상세URL"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="alio_공고.csv")
    ap.add_argument("--log", default="alio_run.json")
    ap.add_argument("--out", default="품질검증리포트.md")
    args = ap.parse_args()

    rows = list(csv.DictReader((HERE / args.csv).open(encoding="utf-8-sig")))
    log = json.loads((HERE / args.log).read_text(encoding="utf-8")) if (HERE / args.log).exists() else {}

    checks = []   # (코드, 이름, 등급, 설명)
    P, F, W = "PASS", "FAIL", "WARN"

    # C1 — 행이 있는가
    n = len(rows)
    checks.append(("C1", "수집 건수", P if n > 0 else F, f"{n}건"))

    # C2 — idx 중복
    ids = [r["idx"] for r in rows if r.get("idx")]
    dup = n - len(set(ids))
    checks.append(("C2", "중복 공고", P if dup == 0 else F,
                   f"고유 {len(set(ids))}건 / 중복 {dup}건"))

    # C3 — 필수 칼럼 빈칸
    empties = {c: sum(1 for r in rows if not (r.get(c) or "").strip()) for c in REQUIRED}
    worst = max(empties.values()) if empties else 0
    detail = ", ".join(f"{c} {v}" for c, v in empties.items() if v) or "전부 채워짐"
    checks.append(("C3", "필수 칼럼 빈칸", P if worst == 0 else F, detail))

    # C4 — 페이지별 수집량. 0건 페이지 = 조용한 유실의 대표 신호
    pages = log.get("pages", [])
    zero = [p["page"] for p in pages if p.get("rows", 0) == 0]
    counts = [p.get("rows", 0) for p in pages]
    uneven = ""
    if counts and max(counts) and min(counts[:-1] or counts) < max(counts) * 0.5:
        uneven = f" / 편차 큼(min {min(counts)}, max {max(counts)})"
    checks.append(("C4", "페이지별 수집량", P if not zero and not uneven else F,
                   (f"0건 페이지 {zero}" if zero else f"{counts}") + uneven))

    # C5 — 파서가 엉뚱한 테이블을 잡으면 제목이 비거나 기관명에 직군분야가 들어온다
    empty_title_log = sum(p.get("empty_title", 0) for p in pages)
    bad_org = [r for r in rows if "·" in (r.get("기관명") or "") and len(r.get("기관명", "")) < 14]
    checks.append(("C5", "파싱 대상 오인", P if not empty_title_log and not bad_org else F,
                   f"제목빈칸(수집시) {empty_title_log} / 기관명 의심 {len(bad_org)}건"))

    # C6 — 날짜 모순. 마감일이 등록일보다 앞서면 파싱이 어긋난 것
    bad_date = [r for r in rows if r.get("등록일") and r.get("마감일")
                and r["마감일"] < r["등록일"]]
    checks.append(("C6", "날짜 정합성", P if not bad_date else F,
                   f"마감일<등록일 {len(bad_date)}건"))

    # C7 — 마감임박 계산 검증 (실제로 버그를 잡았던 항목)
    #      사이트 D-day 표기가 비어 있는 건들이 임박 판정에서 빠지면 그게 버그다.
    today = datetime.now().date()
    recomputed = 0
    for r in rows:
        try:
            left = (datetime.strptime(r["마감일"], "%Y-%m-%d").date() - today).days
        except Exception:
            continue
        if 0 <= left <= 3:
            recomputed += 1
    flagged = sum(1 for r in rows if (r.get("마감임박") or "").strip() == "Y")
    no_dday_flagged = sum(1 for r in rows
                          if (r.get("마감임박") or "").strip() == "Y"
                          and not (r.get("D-day") or "").strip())
    checks.append(("C7", "마감임박 판정", P if flagged == recomputed else F,
                   f"표시 {flagged}건 / 날짜 재계산 {recomputed}건"
                   + (f" (사이트 D-day 표기 없는 건 {no_dday_flagged}건 포함)" if no_dday_flagged else "")))

    # C8 — 상태와 마감일 모순 (사이트 원본 품질. 고객에게 알려야 할 사항)
    stale = [r for r in rows if r.get("상태") == "진행중" and r.get("마감일")
             and r["마감일"] < today.strftime("%Y-%m-%d")]
    checks.append(("C8", "상태-마감일 모순", P if not stale else W,
                   f"'진행중'인데 마감일 지난 건 {len(stale)}건 (사이트 원본 상태값 문제)"))

    # C9 — 상세 수집 실패율
    ok, fail = log.get("detail_ok", 0), log.get("detail_fail", 0)
    if ok or fail:
        rate = fail / (ok + fail) * 100
        checks.append(("C9", "상세 수집 실패율", P if rate == 0 else (W if rate < 5 else F),
                       f"성공 {ok} / 실패 {fail} ({rate:.1f}%)"))
    else:
        checks.append(("C9", "상세 수집 실패율", P, "상세 수집 미사용"))

    # C10 — 셀 안에 개행·연속공백이 남으면 엑셀에서 셀이 깨져 보인다
    dirty = [(c, r[c]) for r in rows for c in r
             if r.get(c) and ("\n" in r[c] or "\t" in r[c] or "  " in r[c])]
    checks.append(("C10", "셀 오염(개행·중복공백)", P if not dirty else F,
                   f"{len(dirty)}건" + (f" 예: {dirty[0][0]}={dirty[0][1][:30]!r}" if dirty else "")))

    failed = [c for c in checks if c[2] == F]
    warned = [c for c in checks if c[2] == W]
    verdict = "납품 불가" if failed else ("조건부 통과" if warned else "통과")

    md = [
        "# 수집 결과 품질검증 리포트",
        "",
        f"- 대상 파일 : `{args.csv}` ({n}건)",
        f"- 검증 시각 : {datetime.now():%Y-%m-%d %H:%M}",
        f"- 수집 실행 : {log.get('started','?')} ~ {log.get('finished','?')}",
        "",
        f"## 판정 → **{verdict}**",
        "",
        "| 코드 | 항목 | 결과 | 내용 |",
        "|---|---|---|---|",
    ]
    mark = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "WARN": "⚠️ WARN"}
    for code, name, grade, desc in checks:
        md.append(f"| {code} | {name} | {mark[grade]} | {desc} |")
    md.append("")
    if failed:
        md += ["## ❌ 실패 항목 — 납품하지 않는다", ""]
        md += [f"- **{c[0]} {c[1]}** : {c[3]}" for c in failed]
        md.append("")
    if warned:
        md += ["## ⚠️ 고객에게 알려야 할 사항", ""]
        md += [f"- **{c[0]} {c[1]}** : {c[3]}" for c in warned]
        md.append("")

    if rows:
        md += ["## 데이터 요약", ""]
        for col in ["상태", "고용형태", "근무지"]:
            if col in rows[0]:
                top = Counter(r[col] for r in rows).most_common(5)
                md.append(f"- {col} : " + ", ".join(f"{k}({v})" for k, v in top))
        md.append(f"- 마감 3일 이내 : {flagged}건")
        md.append("")

    md += ["---", "",
           "> 이 리포트는 '스크립트가 돌았다'가 아니라 '결과 값이 맞다'를 검사한다.",
           "> FAIL이 하나라도 있으면 납품하지 않는다."]

    out = HERE / args.out
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\n저장: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
