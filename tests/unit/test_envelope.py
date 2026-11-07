import json
from datetime import UTC, date, datetime

from pydantic import BaseModel

from tearsheet.core.envelope import Entity, Envelope, Source, Units, to_result


class Revenue(BaseModel):
    value: float


def make() -> Envelope[Revenue]:
    return Envelope[Revenue](
        data=Revenue(value=1234.5),
        entity=Entity(name="Example Ltd", nse="EXAMPLE"),
        as_of=date(2026, 9, 30),
        retrieved_at=datetime(2026, 11, 8, tzinfo=UTC),
        units=Units(),
        sources=[Source(provider="tijori", url="https://example.com/x")],
    )


def test_unverified_is_the_default():
    assert make().verification.status == "unchecked"


def test_retrieved_at_defaults_to_an_aware_time():
    assert Envelope[int](data=1).retrieved_at.tzinfo is not None


def test_result_holds_structured_data_and_matching_compact_text():
    result = to_result(make())
    assert result.structured_content["data"] == {"value": 1234.5}
    assert result.structured_content["as_of"] == "2026-09-30"
    text = result.content[0].text
    assert json.loads(text) == result.structured_content
    assert "\n" not in text
    assert '": ' not in text


def test_empty_optional_fields_are_left_out_to_save_tokens():
    payload = to_result(Envelope[int](data=1)).structured_content
    assert not {"entity", "as_of", "units", "next_cursor"} & payload.keys()


def test_indian_text_stays_readable():
    text = to_result(Envelope[str](data="₹ नमस्ते")).content[0].text
    assert "₹ नमस्ते" in text


def test_schema_marks_data_as_required():
    assert "data" in Envelope[Revenue].model_json_schema()["required"]


class WithBlank(BaseModel):
    required_but_blank: str | None
    figure: float | None


def test_blanks_inside_the_data_are_kept_so_the_result_matches_its_schema():
    envelope = Envelope[WithBlank](data=WithBlank(required_but_blank=None, figure=None))
    payload = to_result(envelope).structured_content
    assert payload["data"] == {"required_but_blank": None, "figure": None}
    Envelope[WithBlank].model_validate(payload)


def test_an_oversized_result_is_refused_with_a_way_forward():
    import pytest

    from tearsheet.core.envelope import MAX_RESULT_CHARS
    from tearsheet.core.errors import TearsheetError

    with pytest.raises(TearsheetError) as caught:
        to_result(Envelope[str](data="x" * MAX_RESULT_CHARS))
    assert "fewer periods" in caught.value.hint
