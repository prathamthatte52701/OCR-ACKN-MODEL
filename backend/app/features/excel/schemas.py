from app.core.base_model import CamelModel


class NewExcelFileRequest(CamelModel):
    filename: str
