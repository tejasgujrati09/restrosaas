from __future__ import annotations

import io
import json

import httpx
import pytest
from PIL import Image
from weasyprint import HTML  # type: ignore[import-untyped]

from app.config import settings
from app.domains.menu.csv_import import ImportContext, parse_menu_csv
from app.domains.menu.extract.files import FileProblem, inspect, load_pages, sniff
from app.domains.menu.extract.normalize import build_csv, clean_text, parse_price, rows_from_pages
from app.domains.menu.extract.openai_provider import OpenAIProvider
from app.domains.menu.extract.provider import PageInput, ProviderError
from app.domains.menu.extract.schema import Defaults, PageExtraction
from tests.menu_extract_fakes import item, page

CTX = ImportContext(
    tax_classes={"food": ("Food", False), "vat": ("VAT", True)},
    stations={},
    modifier_groups={},
    liquor_licensed=True,
)


def extraction(*args: object, **kw: object) -> PageExtraction:
    return PageExtraction.model_validate(page(*args, **kw))  # type: ignore[arg-type]


# ---- prices -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("₹120", "120"),
        ("120", "120"),
        ("Rs. 1,250/-", "1250"),
        ("INR 99.50", "99.50"),
        ("120.0", "120"),
        ("120/180", None),
        ("MRP", None),
        ("", None),
        (None, None),
        ("-5", None),
    ],
)
def test_parse_price(raw: str | None, expected: str | None) -> None:
    assert parse_price(raw) == expected


def test_clean_text_removes_spreadsheet_formula_lead() -> None:
    assert clean_text('  =HYPERLINK("x")  ') == 'HYPERLINK("x")'
    assert clean_text("Paneer\n  Tikka") == "Paneer Tikka"
    assert clean_text(None) == ""


# ---- rows and csv -------------------------------------------------------------------------


def test_sizes_become_one_row_each_and_unlabelled_prices_are_flagged() -> None:
    rows = rows_from_pages(
        [
            (
                1,
                extraction(
                    (
                        "Pizza",
                        [
                            item("Margherita", options=[("Small", "₹100"), ("Large", "₹180")]),
                            item("Biryani", options=[(None, "120"), (None, "180")]),
                        ],
                    )
                ),
            )
        ]
    )
    assert [(r.item, r.price) for r in rows] == [
        ("Margherita (Small)", "100"),
        ("Margherita (Large)", "180"),
        ("Biryani (Option 1)", "120"),
        ("Biryani (Option 2)", "180"),
    ]
    assert any("no size names" in n for n in rows[2].notes)


def test_missing_and_unclear_prices_are_left_empty_and_flagged() -> None:
    rows = rows_from_pages(
        [(1, extraction(("Starters", [item("Soup", None), item("Tea", "market price")])))]
    )
    assert [r.price for r in rows] == ["", ""]
    assert rows[0].notes[0] == "No price found." and rows[0].confidence == "low"
    assert "market price" in rows[1].notes[0]


def test_category_continues_across_pages_and_keeps_first_casing() -> None:
    rows = rows_from_pages(
        [
            (1, extraction(("Main Course", [item("Dal")]))),
            (2, extraction((None, [item("Paneer")]), ("MAIN COURSE", [item("Naan")]))),
            (3, extraction(("Junk", []), is_menu=False)),
        ]
    )
    assert [(r.category, r.item) for r in rows] == [
        ("Main Course", "Dal"),
        ("Main Course", "Paneer"),
        ("Main Course", "Naan"),
    ]
    assert any("previous page" in n for n in rows[1].notes)


def test_first_page_without_heading_has_no_category() -> None:
    (row,) = rows_from_pages([(1, extraction((None, [item("Dal")])))])
    assert row.category == "" and "Category could not be determined." in row.notes


def test_duplicates_are_skipped_and_price_conflicts_flagged() -> None:
    rows = rows_from_pages(
        [
            (1, extraction(("A", [item("Dal", "100"), item("dal", "100"), item("Rice", "50")]))),
            (2, extraction(("A", [item("RICE", "60")]))),
        ]
    )
    assert [r.skip for r in rows] == [False, True, False, True]
    assert any("different prices" in n for n in rows[2].notes)


def test_addons_low_confidence_and_unmarked_veg_are_noted_not_invented() -> None:
    (row,) = rows_from_pages(
        [
            (
                1,
                extraction(
                    (
                        "A",
                        [
                            item(
                                "Pav Bhaji",
                                veg=None,
                                confidence="low",
                                addons=["Extra butter +₹20"],
                            )
                        ],
                    )
                ),
            )
        ]
    )
    text = " ".join(row.notes)
    assert "Add-ons seen" in text and "Low-confidence" in text and "Veg or non-veg" in text
    assert row.veg is None


def test_generated_csv_passes_the_existing_validator() -> None:
    rows = rows_from_pages(
        [
            (
                1,
                extraction(
                    ("Starters", [item("Paneer, Tikka", "180", description='Smoky "hot"\nsnack')]),
                    ("Beer", [item("Kingfisher", "250", liquor=True, veg=None)]),
                ),
            )
        ]
    )
    text, included = build_csv(rows, Defaults(food_tax_class="Food", liquor_tax_class="VAT"))
    assert included == [0, 1]
    parsed = parse_menu_csv(text, CTX)
    assert parsed.errors == []
    assert [(r.item, r.price_paise, r.tax_class, r.is_liquor) for r in parsed.rows] == [
        ("Paneer, Tikka", 18000, "Food", False),
        ("Kingfisher", 25000, "VAT", True),
    ]


def test_csv_leaves_out_skipped_rows_and_reports_missing_tax_class() -> None:
    rows = rows_from_pages([(1, extraction(("A", [item("Dal"), item("Dal"), item("Rice", None)])))])
    text, included = build_csv(rows, Defaults())
    assert included == [0, 2]
    errors = {(e.row, e.column) for e in parse_menu_csv(text, CTX).errors}
    assert errors == {(2, "tax_class"), (3, "price"), (3, "tax_class")}


# ---- files --------------------------------------------------------------------------------


def _jpeg(size: tuple[int, int] = (300, 200), orientation: int | None = None) -> bytes:
    image = Image.new("RGB", size, "white")
    out = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(out, "JPEG", exif=exif)
    else:
        image.save(out, "JPEG")
    return out.getvalue()


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(out, "PNG")
    return out.getvalue()


def _text_pdf(*pages: str) -> bytes:
    body = "".join(f'<div style="page-break-after: always">{p}</div>' for p in pages)
    return HTML(string=body).write_pdf()  # type: ignore[no-any-return]


def _scanned_pdf(pages: int = 2) -> bytes:
    out = io.BytesIO()
    images = [Image.new("RGB", (400, 600), "white") for _ in range(pages)]
    images[0].save(out, "PDF", save_all=True, append_images=images[1:])
    return out.getvalue()


def test_sniff_uses_content_not_names() -> None:
    assert sniff(_jpeg()) == "jpeg" and sniff(_png()) == "png" and sniff(_scanned_pdf()) == "pdf"
    assert sniff(b"<html>menu</html>") is None


def test_inspect_counts_pages_and_rejects_bad_files() -> None:
    assert inspect("m.pdf", _scanned_pdf(3)).pages == 3
    assert inspect("m.jpg", _jpeg()).pages == 1
    for name, data in (
        ("notes.txt", b"hello"),
        ("broken.pdf", b"%PDF-1.4 this is not a real pdf"),
        ("broken.jpg", b"\xff\xd8\xff garbage"),
        ("broken.png", b"\x89PNG\r\n\x1a\n garbage"),
    ):
        with pytest.raises(FileProblem) as exc:
            inspect(name, data)
        assert name in str(exc.value)


def test_text_pdf_pages_are_sent_as_text_and_scanned_pages_as_images() -> None:
    long_text = "Paneer Tikka 180 " * 10
    pages = load_pages(
        [("text.pdf", _text_pdf(long_text, long_text)), ("scan.pdf", _scanned_pdf(1))]
    )
    assert [p.number for p in pages] == [1, 2, 3]
    assert pages[0].text is not None and "Paneer Tikka" in pages[0].text and pages[0].image is None
    assert pages[2].text is None and sniff(pages[2].image or b"") == "jpeg"
    assert pages[0].label == "text.pdf, page 1"


def test_images_keep_upload_order_and_only_shrink_when_too_big(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "menu_extraction_max_image_px", 1000)
    original = _jpeg((300, 200))
    big = _jpeg((3000, 1500))
    pages = load_pages([("a.jpg", original), ("b.png", _png()), ("c.jpg", big)])
    assert [p.label for p in pages] == ["a.jpg", "b.png", "c.jpg"]
    assert pages[0].image == original  # untouched
    assert pages[1].image_mime == "image/jpeg"
    resized = Image.open(io.BytesIO(pages[2].image or b""))
    assert max(resized.size) == 1000


def test_exif_rotation_is_applied() -> None:
    (page_,) = load_pages([("phone.jpg", _jpeg((300, 200), orientation=6))])
    assert Image.open(io.BytesIO(page_.image or b"")).size == (200, 300)


def test_load_pages_rejects_unsupported_bytes() -> None:
    with pytest.raises(FileProblem):
        load_pages([("x.txt", b"nope")])


# ---- the OpenAI adapter (no network) ------------------------------------------------------


def _provider(handler: httpx.MockTransport) -> OpenAIProvider:
    client = httpx.AsyncClient(transport=handler, base_url="https://llm.test/v1")
    return OpenAIProvider("k", base_url="https://llm.test/v1", model="m", timeout=5, client=client)


def _reply(content: object, status: int = 200, **extra: object) -> httpx.Response:
    message = {"content": content if isinstance(content, str) else json.dumps(content), **extra}
    body = {
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    return httpx.Response(status, json=body)


async def test_openai_sends_schema_and_image_and_reads_usage() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _reply(page(("A", [item("Dal")])))

    provider = _provider(httpx.MockTransport(handler))
    result = await provider.extract_page(PageInput(1, "m.jpg", image=_jpeg()))
    assert result.usage.prompt_tokens == 7 and result.usage.requests == 1
    assert seen["response_format"]["json_schema"]["strict"] is True  # type: ignore[index]
    parts = seen["messages"][1]["content"]  # type: ignore[index]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    text_provider = _provider(httpx.MockTransport(handler))
    await text_provider.extract_page(PageInput(1, "m.pdf", text="Dal 100"))
    assert "Dal 100" in seen["messages"][1]["content"][0]["text"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("response", "retryable"),
    [
        (httpx.Response(429, headers={"retry-after": "3"}), True),
        (httpx.Response(503), True),
        (httpx.Response(401), False),
        (_reply("not json"), True),
        (_reply("[1, 2]"), True),
        (httpx.Response(200, json={"choices": []}), True),
        (_reply("{}", refusal="no"), False),
    ],
)
async def test_openai_failures_are_classified(response: httpx.Response, retryable: bool) -> None:
    provider = _provider(httpx.MockTransport(lambda request: response))
    with pytest.raises(ProviderError) as exc:
        await provider.extract_page(PageInput(1, "x", text="t"))
    assert exc.value.retryable is retryable


async def test_openai_timeouts_and_network_errors_are_retryable() -> None:
    def boom(kind: type[Exception]) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            raise kind("x")

        return httpx.MockTransport(handler)

    for kind in (httpx.ReadTimeout, httpx.ConnectError):
        with pytest.raises(ProviderError) as exc:
            await _provider(boom(kind)).extract_page(PageInput(1, "x", text="t"))
        assert exc.value.retryable
    await _provider(httpx.MockTransport(lambda r: httpx.Response(200))).aclose()
