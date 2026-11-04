# HTML 화면 시험 문서

이 문서는 Markdown 화면 PoC 를 위한 시험 문서다. 문단은 여러 줄로 쓴다.
줄마다 원문 줄 번호가 붙으므로, 문단 안의 한 줄만 골라도 핀이 그 줄을 가리킨다.
**굵은 글**, *기울인 글*, `코드`, [Limn 저장소](https://github.com/dartworklabs/limn)가 섞여도 줄은 그대로다.

## 목록

- 첫째 항목
- 둘째 항목에는 하위 목록이 있다
  - 하위 항목 가
  - 하위 항목 나
- 셋째 항목

1. 번호 목록 하나
2. 번호 목록 둘
3. 번호 목록 셋

## 표

| 문서 종류 | 그리는 법 | 되짚는 법 |
| --- | --- | --- |
| LaTeX | PDF | SyncTeX |
| 그림 | PDF + 요소 지도 | 요소 지도 |
| Markdown | 브라우저 | 블록의 원문 줄 |

## 코드와 인용

```python
def pick(lo, hi):
    """선택한 줄 범위를 핀으로 만든다."""
    return {"lo": lo, "hi": hi}
```

> 인용 블록도 원문 줄을 가진다.
> 둘째 줄까지 이어진다.

### 셋째 단계 제목

셋째 단계 제목 아래의 문단이다. 절 단계는 이 제목부터 다음 같은 단계 이상의 제목 전까지다.

#### 넷째 단계 제목

넷째 단계 제목 아래의 문단이다.

## 보안 시험

원시 HTML 은 글자로 보인다: <script>alert(1)</script> <img src=x onerror=alert(1)>
`javascript:` 링크는 링크가 되지 않는다: [눌러 보기](javascript:alert(1))
문서 밖 상대 경로는 열지 않는다: [핸드북](docs/handbook/index.md)
원격 그림은 불러오지 않는다: ![원격 그림](https://example.com/tracker.png)

## 여러 줄 인라인

강조가 *줄을 넘어
이어진다* 그래도 줄은 맞는다.
[링크 글이 줄을
넘는다](https://example.org) 이 줄도 맞는다.

코드 표시가 `줄을
넘으면` 줄을 셀 수 없다.
그래서 이 문단은 통째로 고른다.

같은 출처 링크는 열지 않는다: [API](https://limn.example.ts.net:18020/api/meta)
다른 scheme 도 열지 않는다: <ftp://example.org/file> [앱](myapp://open)
끝에 점을 붙인 이름도 열지 않는다: [API](http://localhost.:18920/api/source?doc=fixture) <https://limn.example.ts.net.:18020/api/meta>

---

마지막 문단. 끝.
