from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema


class PyObjectId(ObjectId):
    """Pydantic-validated Mongo ObjectId - matches old utils/objectId.js's
    isValidObjectId guard: malformed ids raise (caught by FastAPI as a 422/400)
    instead of ever reaching a Mongo query."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema_: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        # Without this, Pydantic can't render a JSON Schema for the plain-
        # validator-function core schema above, and /openapi.json (therefore
        # /docs and /redoc too) crashes with a 500 the moment any route using
        # this type is included in the schema - this declares it as the plain
        # string it actually is on the wire.
        return {"type": "string", "example": "507f1f77bcf86cd799439011"}

    @classmethod
    def _validate(cls, value: Any) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        if isinstance(value, str):
            try:
                return ObjectId(value)
            except InvalidId as exc:
                raise ValueError(f"Invalid ObjectId: {value}") from exc
        raise ValueError(f"Invalid ObjectId: {value!r}")
