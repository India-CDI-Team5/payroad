"""Run from the repository root: python -m pytest scripts/paper"""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("renumber_refs", Path(__file__).with_name("renumber_refs.py"))
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)

REFS_MD = """# 참고문헌
설명 문단 [X9] 같은 줄은 항목이 아니다.

[A1] C. E. Rasmussen and C. K. I. Williams, *Gaussian Processes for Machine Learning*, MIT Press, 2006.
[B1] A. Krause, A. Singh, and C. Guestrin, "Near-optimal sensor placements," *J. Mach. Learn. Res.*, 2008. <!-- DOI 없음 -->
[D1] H. S. Farber, "Why you can't find a taxi in the rain," *Q. J. Econ.*, 2015.
[H3] H. R. Künsch, "The jackknife and the bootstrap," *Ann. Statist.*, 1989. <!-- △ 쪽수 확인 -->
"""

DRAFT = """# Ⅰ. 서론

비 오는 날 택시가 부족하다[R:D1]. GP 보간[R:A1]과 센서 배치[R:B1, R:A1]를 쓴다.
방법 B1과 숫자 [[N01]], 이미 번호인 [3]은 그대로 둔다. 다시 인용[R:D1].

```text
코드 안의 [R:H3]은 바꾸지 않는다.
```
"""


@pytest.fixture
def refs():
    return rr.parse_references(REFS_MD)


def test_parse_keeps_file_order_and_drops_notes(refs):
    assert list(refs) == ["A1", "B1", "D1", "H3"]
    assert refs["H3"].endswith("1989.")
    assert "<!--" not in refs["B1"]


def test_numbers_follow_first_appearance_and_repeat_citations_reuse_them(refs):
    body, cited = rr.renumber(DRAFT, refs)
    assert cited == ["D1", "A1", "B1"]
    assert "부족하다[1]." in body
    assert "GP 보간[2]" in body
    assert "센서 배치[2, 3]" in body            # numbers in a group are sorted
    assert "다시 인용[1]." in body


def test_brackets_without_the_prefix_and_code_blocks_are_untouched(refs):
    body, _ = rr.renumber(DRAFT, refs)
    assert "방법 B1과 숫자 [[N01]], 이미 번호인 [3]은" in body
    assert "코드 안의 [R:H3]은" in body


def test_uncited_references_are_left_out_of_the_list(refs):
    out = rr.build(DRAFT, refs)
    tail = out.split(rr.HEADING, 1)[1].strip().splitlines()
    assert tail == [f"[1] {refs['D1']}", f"[2] {refs['A1']}", f"[3] {refs['B1']}"]
    assert "Künsch" not in out.split(rr.HEADING, 1)[1]


def test_unknown_and_malformed_citations_are_errors(refs):
    with pytest.raises(ValueError, match="unknown reference Z9"):
        rr.renumber("본문[R:Z9].", refs)
    with pytest.raises(ValueError, match="malformed"):
        rr.renumber("본문[R:A1 R:B1].", refs)


def test_draft_without_citations_gets_no_list(refs):
    assert rr.build("인용 없음 [B1].\n", refs) == "인용 없음 [B1].\n"


def test_cli_writes_each_draft_to_the_output_dir(tmp_path):
    (tmp_path / "references.md").write_text(REFS_MD, encoding="utf-8")
    draft = tmp_path / "blind.md"
    draft.write_text(DRAFT, encoding="utf-8")
    out_dir = tmp_path / "build"
    assert rr.main([str(draft), "--refs", str(tmp_path / "references.md"), "--out-dir", str(out_dir)]) == 0
    written = (out_dir / "blind.md").read_text(encoding="utf-8")
    assert written.endswith(f"[3] {rr.parse_references(REFS_MD)['B1']}\n")
    bad = tmp_path / "bad.md"
    bad.write_text("[R:Q1]", encoding="utf-8")
    assert rr.main([str(bad), "--refs", str(tmp_path / "references.md"), "--out-dir", str(out_dir)]) == 1


def test_the_real_reference_list_parses():
    real = Path(__file__).resolve().parents[2] / "paper" / "references.md"
    if not real.exists():
        pytest.skip("paper/ is local only")
    refs = rr.parse_references(real.read_text(encoding="utf-8"))
    assert len(refs) == 19
    for required in ("A1", "B1", "B3", "C1", "C5", "E1", "E2", "D1", "D2", "F3", "F1", "H1", "H3", "H2", "I1", "I2"):
        assert required in refs
