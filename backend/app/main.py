import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from starlette.requests import ClientDisconnect

MAX_UPLOAD = 10 * 1024 * 1024
TIMEOUT = 15


@asynccontextmanager
async def lifespan(app):
    app.state.slots = asyncio.Semaphore(2)
    yield


app = FastAPI(title='Academic Research Studio', lifespan=lifespan)


@app.middleware('http')
async def privacy_headers(request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/api/health')
async def health():
    return {'status': 'ok'}


async def parse_document(data: bytes, kind: str):
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'app.worker', kind,
        cwd=Path(__file__).resolve().parent.parent,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(data), TIMEOUT)
        if process.returncode != 0:
            raise HTTPException(422, 'Документ превышает ресурсы обработки или повреждён.')
        result = json.loads(stdout)
        if 'error' in result:
            raise HTTPException(422, result['error'])
        return result
    except TimeoutError:
        raise HTTPException(422, 'Превышено время обработки документа.') from None
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


@app.post('/api/documents/extract')
async def upload(request: Request, filename: str = Query(min_length=1, max_length=255)):
    # Filename is metadata only: never used as a filesystem path.
    kind = filename.rsplit('.', 1)[-1].lower()
    if kind not in {'docx', 'pdf'}:
        raise HTTPException(415, 'Поддерживаются только DOCX и PDF.')
    if request.headers.get('content-encoding', 'identity') != 'identity':
        raise HTTPException(415, 'Сжатие HTTP-запроса не поддерживается.')
    length = request.headers.get('content-length')
    if length is not None:
        try:
            size = int(length)
        except ValueError:
            raise HTTPException(400, 'Некорректный размер запроса.') from None
        if size < 0:
            raise HTTPException(400, 'Некорректный размер запроса.')
        if size > MAX_UPLOAD:
            raise HTTPException(413, 'Максимальный размер файла — 10 МиБ.')
    try:
        await asyncio.wait_for(request.app.state.slots.acquire(), 0.05)
    except TimeoutError:
        raise HTTPException(503, 'Сервис занят. Повторите загрузку позже.') from None
    try:
        async with asyncio.timeout(30):
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > MAX_UPLOAD:
                    raise HTTPException(413, 'Максимальный размер файла — 10 МиБ.')
                data.extend(chunk)
            if not data:
                raise HTTPException(400, 'Файл пуст.')
            return await parse_document(bytes(data), kind)
    except TimeoutError:
        raise HTTPException(408, 'Превышено время загрузки.') from None
    except ClientDisconnect:
        raise HTTPException(400, 'Загрузка прервана.') from None
    finally:
        request.app.state.slots.release()
