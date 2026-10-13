# 블로그 발행

글은 `posts/2026/` 아래의 Markdown 파일이다. main에 올리면 `pages` 워크플로가
사이트를 다시 만들어 https://sungkunx.github.io/nb-league-magazine2627/ 에 올린다.

## 글 파일

파일 이름이 주소가 된다(`posts/2026/w03-end.md` → `/posts/w03-end/`). 영문·숫자·하이픈만 쓴다.

```
---
title: 3주차 결산: 무승부의 역습
date: 2026-11-09T22:00+09:00
kind: week-end
week: 3
summary: 카톡에 링크를 붙였을 때 제목 아래에 뜨는 한 줄
cover: images/w03-end.png
---

본문...
```

| `kind` | 뜻 | `week` |
|---|---|---|
| `week-start` / `week-mid` / `week-end` | 주간 시작 / 중간 / 마지막 | 필수 |
| `draft` / `preseason` / `playoff` / `notice` | 드래프트 평가 / 개막 전 / 플레이오프 특집 / 안내 | 없음 |

권장 파일 이름: `wNN-start.md`, `wNN-mid.md`, `wNN-end.md`, `draft.md`, `preseason.md`, `playoff.md`.

## 본문에서 쓸 수 있는 것

제목(`##`), 굵게, 기울임, 목록(한 단계 중첩), 인용(`>`), 구분선, 표, 링크, 이미지.
HTML은 쓸 수 없다(글자로 그대로 보인다).

한 줄에 아래만 적으면 그 주 팩트시트에서 표를 만들어 넣는다.

- `{{matchups}}` — 매치업별 카테고리 표(이긴 쪽 강조)
- `{{standings}}` — 순위표
- 다른 주의 표는 `{{standings week=2}}`처럼 쓴다.

해당 주의 `data/2026/facts/week-NN.json`이 없으면 빌드가 실패한다.

## 만평

이미지를 `posts/2026/images/`에 넣고 글 머리의 `cover:`에 경로를 적는다.
`cover`는 글 맨 위에 실리고 카톡 미리보기 이미지로도 쓰인다. 가로 1200px 안팎을 권장한다.
본문 중간에 넣으려면 `![설명](images/파일.png)`.

## 올리기 전 확인

```
python -m nbl blog        # site/ 에 만들어진다. 오류가 있으면 파일 이름과 이유가 나온다
```

글을 고친 경우 본문 끝에 무엇을 고쳤는지 한 줄 적는다.
