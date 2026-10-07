from pydantic import BaseModel, ConfigDict

from app.core.object_id import PyObjectId


def to_camel(snake: str) -> str:
    first, *rest = snake.split("_")
    return first + "".join(word.capitalize() for word in rest)


class CamelModel(BaseModel):
    """Base for every document/response model. Fields are snake_case in
    Python (idiomatic) but (de)serialize as camelCase on the wire via alias,
    so the existing camelCase frontend needs zero field-name changes when
    reconnected in Phase 6 - see ANALYSIS.md open question #2."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={PyObjectId: str},
    )
