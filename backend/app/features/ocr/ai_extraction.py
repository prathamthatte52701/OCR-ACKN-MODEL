from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.features.ocr.extraction import build_extraction_result, empty_extraction_result
from app.features.ocr.json_parsing import parse_extraction_json
from app.features.ocr.providers.base import AIProvider
from app.features.ocr.providers.groq_provider import GroqProvider

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)), autoescape=False)

_TEMPLATE_BY_TYPE = {
    "Tax Invoice": "tax_invoice.j2",
    "Delivery Challan": "delivery_challan.j2",
}


async def extract_header(
    document_type: str,
    header_text: str | None,
    provider: AIProvider | None = None,
    min_rec_score: float | None = None,
) -> dict:
    if not header_text or not header_text.strip():
        return empty_extraction_result(document_type)

    provider = provider or GroqProvider()
    system_prompt = _env.get_template(_TEMPLATE_BY_TYPE[document_type]).render()
    user_prompt = f"Extract from this {document_type} header OCR text:\n\n{header_text}"

    raw_response = await provider.extract(system_prompt, user_prompt)
    parsed = parse_extraction_json(raw_response)
    return build_extraction_result(document_type, parsed, header_text, min_rec_score=min_rec_score)
