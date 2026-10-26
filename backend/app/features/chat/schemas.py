from typing import Any

from pydantic import ConfigDict

from app.core.base_model import CamelModel


class _Strict(CamelModel):
    """Unknown fields are rejected (422), so a user cannot smuggle `userId` and an admin
    cannot send `toAdminId`. Values are typed Any on purpose: the service validates them and
    answers with a plain-English 422 instead of a pydantic type error."""

    model_config = ConfigDict(
        alias_generator=CamelModel.model_config["alias_generator"],
        populate_by_name=True,
        extra="forbid",
    )


class SendMessageRequest(_Strict):
    # user sends: to_admin_id + text; admin sends: user_id + text
    to_admin_id: Any = None
    user_id: Any = None
    text: Any = None


class EditMessageRequest(_Strict):
    text: Any = None


class ReadRequest(_Strict):
    user_id: Any = None
    up_to_id: Any  # required: newer messages the screen never fetched stay unread


class ColorRequest(_Strict):
    color: Any = None


class ClearRequest(_Strict):
    user_id: Any = None
    older_than: Any = None
    dry_run: bool = False
    confirm: Any = None


class ClearAllRequest(_Strict):
    password: Any = None
    dry_run: bool = False
    confirm: Any = None
