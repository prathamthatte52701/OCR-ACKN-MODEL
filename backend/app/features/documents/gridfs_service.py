from bson import ObjectId

from app.core.database import get_gridfs


async def upload_buffer(buffer: bytes, filename: str, content_type: str) -> ObjectId:
    bucket = get_gridfs()
    grid_in = bucket.open_upload_stream(filename, metadata={"contentType": content_type})
    await grid_in.write(buffer)
    await grid_in.close()
    return grid_in._id


async def download_buffer(file_id: ObjectId) -> bytes:
    bucket = get_gridfs()
    grid_out = await bucket.open_download_stream(file_id)
    return await grid_out.read()


async def delete_file(file_id: ObjectId) -> None:
    bucket = get_gridfs()
    await bucket.delete(file_id)
