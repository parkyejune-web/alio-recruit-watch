# alio-recruit-watch

공공기관 채용정보(잡알리오) 공고를 매일 자동 수집해 누적한다.

> 이 저장소는 크몽 서비스 납품 리허설용이다. 실제 고객 납품물이 아니다.

## 무엇이 도는가

`.github/workflows/collect.yml` 이 매일 **KST 07:00** 에 다음 순서로 돈다.

1. `collect_alio.py` — 목록 3페이지(150건) 수집 → `alio_공고.csv`
2. `validate_alio.py` — 품질검증 10항목. **FAIL이면 여기서 죽는다**
3. `append_master.py` — `data/master.csv` 에 idx 기준 신규만 누적, 신규분은 `data/신규_최근.csv`
4. 결과 커밋
5. 실패하면 이슈를 자동 생성한다

## 왜 검증을 따로 두는가

수집기는 틀린 값도 "성공"이라고 보고한다. 실제로 겪은 것:

- 제목이 10/10 전부 빈 문자열인데 로그는 "10행 수집"
- 다른 사이트에서 69% 유실인데 로그는 끝까지 "성공 12/12"

그래서 "돌았다"가 아니라 "결과 값이 맞다"를 따로 검사하고,
**검증에 실패하면 데이터를 누적하지 않는다.** 틀린 데이터가 쌓이는 것이 안 도는 것보다 나쁘다.

## 적법성

- 잡알리오 저작권정책: 저작권법 제24조의2(공공저작물 자유이용), 공공데이터법 제1·3조
  — **영리 목적 이용을 포함한 자유로운 활용이 보장**된다고 명시
- robots.txt 없음 / 로그인 불필요 / 개인 식별 정보는 수집하지 않는다

## 손으로 돌리기

```
pip install -r requirements.txt
python collect_alio.py --pages 3
python validate_alio.py
python append_master.py
```
