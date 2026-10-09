"""Legacy rows may still carry the removed *Confidence fields; no API response may expose them."""

from datetime import UTC, datetime
from typing import Any

LEGACY = {
    "numberConfidence": 100,
    "dateConfidence": 40,
    "taxInvoiceNoConfidence": 20,
    "referenceNoConfidence": 0,
}


def _has_confidence(value: Any) -> bool:
    if isinstance(value, dict):
        return any(k.endswith("Confidence") or _has_confidence(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_confidence(v) for v in value)
    return False


async def test_list_get_and_correct_never_expose_confidence(
    client: Any, db: Any, make_user: Any
) -> None:
    u = await make_user()
    now = datetime.now(UTC)
    res = await db.documents.insert_one(
        {
            "userId": u.id,
            "autoName": "d",
            "originalFilename": "d.pdf",
            "mimeType": "application/pdf",
            "size": 1,
            "uploadStatus": "processed",
            "documentType": "Delivery Challan",
            "number": "820000001",
            "date": "05/10/2026",
            "edited": False,
            "exported": False,
            "isDeleted": False,
            "filePurged": True,
            "createdAt": now,
            "updatedAt": now,
            **LEGACY,
        }
    )
    doc_id = res.inserted_id
    listing = await client.get("/api/documents", headers=u.headers)
    assert listing.status_code == 200 and not _has_confidence(listing.json())
    one = await client.get(f"/api/documents/{doc_id}", headers=u.headers)
    assert one.status_code == 200 and not _has_confidence(one.json())
    fixed = await client.patch(
        f"/api/documents/{doc_id}/correct",
        headers=u.headers,
        json={"field": "number", "value": "820000002"},
    )
    assert fixed.status_code == 200, fixed.text
    assert not _has_confidence(fixed.json())
    stored = await db.documents.find_one({"_id": doc_id})
    assert stored["number"] == "820000002" and stored["edited"] is True
    assert stored["numberConfidence"] == 100 and stored["dateConfidence"] == 40  # not rewritten
