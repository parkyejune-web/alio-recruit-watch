# -*- coding: utf-8 -*-
"""
잡알리오(공공기관 채용정보) 공고 수집기 — 리허설 의뢰 1건 전용

⚠️ 범용 스크래퍼가 아니다. 이 사이트 한 곳만 본다.
   "다른 사이트도 되게 만들자"는 생각이 들면 그날 작업을 끝낸다 (리허설 중단 조건).

적법성: `precheck_job_alio_go_kr.md` + 사이트 저작권정책
        (저작권법 24조의2 공공저작물 자유이용 / 공공데이터법 1·3조 영리 이용 포함 허용)

이 사이트에서 실제로 밟은 지뢰 3개 — 전부 조용히 틀린 값을 만든다
  (1) caption 부분 문자열 매칭 함정
      '채용정보' in '공공기관 채용정보 검색' == True
      → 목록 대신 **검색 폼 테이블**을 긁어서 기관명 칸에 '금융·보험'이 들어온다.
      → caption 완전 일치로만 찾는다.
  (2) self-closing 앵커
      `<a href="..." target="_blank"/>제목</a>` 라서 파서가 a를 빈 태그로 닫는다.
      → a.get_text() 가 **10/10 전부 빈 문자열**. 행 수도, 다른 칼럼도 멀쩡해서 눈치채기 어렵다.
      → `<a .../>` 를 `<a ...>` 로 정규화하고, 그래도 비면 td 전체 텍스트로 폴백한다.
  (3) 페이지 경계에서 idx 순서가 뒤섞인다
      page1 끝 id와 page2 첫 id가 역전되는 경우가 있다 (같은 등록일 내 정렬 불안정).
      → 페이지별 신규/중복 건수를 로그에 남겨 유실을 눈으로 볼 수 있게 한다.

사용법
  python collect_alio.py --pages 3
  python collect_alio.py --pages 3 --detail          # 근무분야까지 (공고 1건당 요청 1회 추가)
  python collect_alio.py --since 2026-08-18          # 등록일 기준 그 이후만
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
BASE = "https://job.alio.go.kr"
LIST_URL = BASE + "/recruit.do?pageNo={page}&pageSet={size}"
VIEW_URL = BASE + "/recruitview.do?idx={idx}"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) alio-collector/1.0"}

ANCHOR_FIX = re.compile(r"(<a\b[^>]*?)\s*/>")
DDAY_RE = re.compile(r"D-(\d+)")
DATE_RE = re.compile(r"(\d{2,4})\.(\d{2})\.(\d{2})")


@dataclass
class RunLog:
    started: str
    finished: str = ""
    pages: list = field(default_factory=list)   # [{page, rows, new, dup, empty_title}]
    detail_ok: int = 0
    detail_fail: int = 0
    errors: list = field(default_factory=list)
    total: int = 0


def fetch(url: str, tries: int = 3):
    """지수 백오프 재시도. 실패는 예외로 올려 조용히 넘어가지 않게 한다."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(1.5 * (2 ** i))
    raise RuntimeError(f"fetch 실패 {url} :: {type(last).__name__}: {last}")


def listing_table(html: str):
    """지뢰 (1)(2) 처리: 앵커 정규화 후 caption 완전 일치로만 목록 테이블을 찾는다."""
    soup = BeautifulSoup(ANCHOR_FIX.sub(r"\1>", html), "lxml")
    for t in soup.find_all("table"):
        cap = t.find("caption")
        if cap and cap.get_text(strip=True) == "채용정보":   # in 이 아니라 ==
            return t
    return None


def norm_date(s: str) -> str:
    """'26.09.02' / '2026.08.19' 를 2026-09-02 로 통일."""
    m = DATE_RE.search(s or "")
    if not m:
        return ""
    y, mo, d = m.groups()
    if len(y) == 2:
        y = "20" + y
    return f"{y}-{mo}-{d}"


def clean(s: str) -> str:
    """셀 안의 개행·탭이 CSV에 그대로 실려 엑셀에서 셀이 깨지는 것을 막는다.
    (실측: 고용형태가 '무기계약직\\n\\t\\t\\t외 1' 로 들어왔다)"""
    return re.sub(r"\s+", " ", (s or "")).strip()


def parse_rows(html: str):
    tb = listing_table(html)
    if tb is None:
        return []
    body = tb.find("tbody")
    if body is None:
        return []
    out = []
    for tr in body.find_all("tr", recursive=False):
        td = tr.find_all("td")
        if len(td) < 9:            # 헤더·안내행은 칼럼 수로 걸러낸다
            continue
        chk = td[0].find("input")
        idx = chk.get("value") if chk else ""
        a = td[2].find("a")
        title = (a.get_text(strip=True) if a else "") or td[2].get_text(" ", strip=True)
        deadline_cell = td[7].get_text(" ", strip=True)
        dday = DDAY_RE.search(deadline_cell)
        out.append({
            "idx": idx,
            "제목": clean(title),
            "기관명": clean(td[3].get_text(" ", strip=True)),
            "근무지": clean(td[4].get_text(" ", strip=True)),
            "고용형태": clean(td[5].get_text(" ", strip=True)),
            "등록일": norm_date(td[6].get_text(strip=True)),
            "마감일": norm_date(deadline_cell),
            "D-day": int(dday.group(1)) if dday else "",
            "상태": clean(td[8].get_text(" ", strip=True)),
            "상세URL": urllib.parse.urljoin(BASE, a.get("href")) if a and a.get("href") else "",
        })
    return out


# 상세 페이지는 "라벨 다음이 값"인 평문 구조라 라벨 사이를 잘라 쓴다.
DETAIL_LABELS = ["근무분야", "채용구분", "고용형태", "대체인력여부", "근무지",
                 "급여정보", "채용인원", "우대조건", "채용기간", "등록일"]


def parse_detail(html: str) -> dict:
    t = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    t = re.sub(r"\s+", " ", t)
    got = {}
    for i, lab in enumerate(DETAIL_LABELS):
        j = t.find(lab)
        if j < 0:
            continue
        seg = t[j + len(lab):]
        nxt = min([seg.find(n) for n in DETAIL_LABELS[i + 1:] if seg.find(n) > 0] or [80])
        got[lab] = seg[:nxt].strip(" :·")[:60]
    return {"근무분야": got.get("근무분야", ""), "채용구분": got.get("채용구분", ""),
            "채용인원": got.get("채용인원", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--size", type=int, default=50)
    ap.add_argument("--detail", action="store_true", help="상세 진입해 근무분야까지 (요청 1건/공고)")
    ap.add_argument("--since", default="", help="등록일 YYYY-MM-DD 이후만")
    ap.add_argument("--out", default="alio_공고.csv")
    ap.add_argument("--log-out", default="alio_run.json")
    ap.add_argument("--sleep", type=float, default=0.8)
    args = ap.parse_args()

    log = RunLog(started=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    seen, records = set(), []

    for p in range(1, args.pages + 1):
        try:
            html = fetch(LIST_URL.format(page=p, size=args.size))
        except Exception as e:
            log.errors.append(f"page {p}: {e}")
            log.pages.append({"page": p, "rows": 0, "new": 0, "dup": 0, "empty_title": 0})
            continue
        rows = parse_rows(html)
        new = dup = 0
        for r in rows:
            if not r["idx"] or r["idx"] in seen:
                dup += 1
                continue
            seen.add(r["idx"])
            records.append(r)
            new += 1
        empty_title = sum(1 for r in rows if not r["제목"])
        log.pages.append({"page": p, "rows": len(rows), "new": new,
                          "dup": dup, "empty_title": empty_title})
        print(f"page {p}: {len(rows)}행 (신규 {new} / 중복 {dup} / 제목빈칸 {empty_title})")
        time.sleep(args.sleep)

    if args.since:
        before = len(records)
        records = [r for r in records if r["등록일"] and r["등록일"] >= args.since]
        print(f"--since {args.since}: {before} -> {len(records)}건")

    if args.detail:
        for i, r in enumerate(records, 1):
            try:
                d = parse_detail(fetch(VIEW_URL.format(idx=r["idx"])))
                r.update(d)
                log.detail_ok += 1
            except Exception as e:
                r.update({"근무분야": "", "채용구분": "", "채용인원": ""})
                log.detail_fail += 1
                log.errors.append(f"detail {r['idx']}: {e}")
            if i % 10 == 0:
                print(f"  상세 {i}/{len(records)}")
            time.sleep(args.sleep)

    # 고객 추가 요청: 마감 3일 이내 표시
    # ⚠️ 사이트의 D-day 표기를 믿으면 안 된다 (실측 2026-08-19):
    #    마감일이 오늘/내일인 공고에는 D-day span 자체가 없어서 빈칸이 된다.
    #    즉 D-day에 의존하면 **가장 급한 건들만 골라서 놓친다.** 날짜로 직접 계산한다.
    today = datetime.now().date()
    for r in records:
        left = ""
        if r["마감일"]:
            try:
                left = (datetime.strptime(r["마감일"], "%Y-%m-%d").date() - today).days
            except ValueError:
                left = ""
        r["남은일수"] = left
        r["마감임박"] = "Y" if isinstance(left, int) and 0 <= left <= 3 else ""

    cols = ["idx", "제목", "기관명", "근무지", "고용형태", "등록일", "마감일",
            "D-day", "남은일수", "마감임박", "상태", "상세URL"]
    if args.detail:
        cols += ["근무분야", "채용구분", "채용인원"]

    out = HERE / args.out
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    log.total = len(records)
    log.finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (HERE / args.log_out).write_text(
        json.dumps(asdict(log), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{len(records)}건 -> {out}")
    print(f"실행로그 -> {HERE / args.log_out}")
    if log.errors:
        print(f"⚠️ 오류 {len(log.errors)}건 (로그 확인)")


if __name__ == "__main__":
    main()
