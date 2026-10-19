# 블로그 발행

글은 `posts/2026/` 아래의 Markdown 파일이다. main에 올리면 `pages` 워크플로가
사이트를 다시 만들어 https://sungkunx.github.io/nb-league-magazine/ 에 올린다.

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
| `week-cartoon` | 주간 만평 | 필수 |
| `extra` | 호외 | 선택(표를 넣을 때) |
| `draft` / `preseason` / `playoff` / `notice` | 드래프트 평가 / 개막 전 / 플레이오프 특집 / 안내 | 없음 |

권장 파일 이름: `wNN-start.md`, `wNN-mid.md`, `wNN-end.md`, `wNN-cartoon.md`,
`extra-MMDD.md`, `draft.md`, `preseason.md`, `playoff.md`.
무엇을 언제 쓰는지는 `docs/editorial.md`.

## 본문에서 쓸 수 있는 것

제목(`##`), 굵게, 기울임, 목록(한 단계 중첩), 인용(`>`), 구분선, 표, 링크, 이미지.
HTML은 쓸 수 없다(글자로 그대로 보인다).

한 줄에 아래만 적으면 그 주 팩트시트에서 표를 만들어 넣는다.

- `{{matchups}}` — 매치업별 카테고리 표(이긴 쪽 강조)
- `{{standings}}` — 순위표
- 다른 주의 표는 `{{standings week=2}}`처럼 쓴다.

해당 주의 `data/2026/facts/week-NN.json`이 없으면 빌드가 실패한다.

## 만평

만평은 별도의 글(`kind: week-cartoon`)이다. 그림은 정확히 3장이고, 그림마다 바로 아래에
코멘트 한 줄을 적는다. 그림 수가 다르거나 파일이 없으면 빌드가 실패한다.

```
---
title: 3주차 만평
date: 2026-11-09T22:30+09:00
kind: week-cartoon
week: 3
summary: 카톡 미리보기에 뜨는 한 줄
---

![첫 그림 설명](images/w03-cartoon-1.png)

첫 그림의 코멘트 한 줄.

![둘째 그림 설명](images/w03-cartoon-2.png)

둘째 그림의 코멘트 한 줄.

![셋째 그림 설명](images/w03-cartoon-3.png)

셋째 그림의 코멘트 한 줄.
```

그림은 `posts/2026/images/`에 넣는다. 받은 원본(PNG 등)은 그대로 커밋하지 않고, 가로 1200px JPG(품질 80 안팎,
장당 200~400KB)로 줄여서 넣는다. 한 번 커밋한 파일은 지워도 저장소 이력에 남아 용량이 줄지 않기 때문이다.
`python -m nbl blog`는 1MB가 넘는 그림을 `WARNING:` 줄로 알려 준다. 경고가 나오면 줄인 뒤에 커밋한다.
줄이는 방법: 작업 공간에서는 Pillow(`pip install pillow`), Mac에서는 `sips -Z 1200 -s format jpeg -s formatOptions 80 원본.png --out 결과.jpg`.
`cover:`를 적지 않으면 첫 그림이 카톡 미리보기 이미지가 된다.

## 그 밖의 이미지

다른 글에도 본문에 `![설명](images/파일.png)`로 이미지를 넣을 수 있다.
글 머리에 `cover:`를 적으면 글 맨 위에 실리고 카톡 미리보기 이미지로도 쓰인다.

## 팀별 모아 보기

목록 위에 팀 이름이 한 줄로 놓이고, 누르면 그 팀이 나온 글과 해당 대목을 모은 페이지
(`/teams/<팀 번호>/`)로 간다. 손으로 다는 태그는 없다. 빌드할 때 팩트시트의 팀 이름을
글 본문에서 찾아 묶는다.

- 팀 이름은 팩트시트에 적힌 그대로 쓴다(`Cho`, `Team Jaewon`). 줄이거나 바꿔 쓰면 묶이지 않는다.
- 시즌 중에 이름이 바뀐 팀은 팀 번호로 이어진다. 옛 이름으로 쓴 글도 같은 페이지에 남는다.
- 안내 글(`notice`)과 검토 중인 글은 묶지 않는다. 표(`{{standings}}`, `{{matchups}}`) 속 이름도 세지 않는다.

## 검토 후 발행

새 글은 편집자(리그 운영자)가 확인한 뒤에 발행한다.

1. 글 머리에 `status: review`를 넣어 main에 올린다. 글의 페이지는 만들어지지만
   목록과 다른 글의 이전/다음 링크에는 나오지 않고, 페이지 위에 "미리보기" 표시가 붙는다.
   주소는 발행 후와 같다(`/posts/<파일 이름>/`).
2. 편집자에게 미리보기 주소를 알리고 답을 기다린다. 답이 없으면 발행하지 않는다.
3. 고쳐 달라는 답이면 고쳐서 다시 올리고 2로 돌아간다.
4. 발행하라는 답이면 `python -m nbl publish <파일 이름>` 으로 `status` 줄을 지우고 main에 올린다.

저장소가 공개라서 검토 중인 글도 주소를 아는 사람은 볼 수 있다. 숨기는 장치가 아니라
목록에 올리기 전의 확인 단계다.

### 자동 발행으로 바꾸기

`config/site.json`의 `auto_publish`에 적은 종류는 검토 없이 바로 발행한다(`status` 줄을 넣지 않는다).

```
"auto_publish": []                              모든 글을 검토한다 (지금 설정)
"auto_publish": ["week-start", "week-mid"]      시작·중간 글은 바로, 나머지는 검토
"auto_publish": ["all"]                         전부 바로 발행
```

## 올리기 전 확인

```
python -m nbl blog        # site/ 에 만들어진다. 오류가 있으면 파일 이름과 이유가 나온다
                          # 검토 중인 글이 있으면 "waiting for review: <주소>" 가 나온다
```

글을 고친 경우 본문 끝에 무엇을 고쳤는지 한 줄 적는다.
