import certifi
import shutil
import json
import hashlib
import re
from pathlib import Path
from typing import Optional
import httpx
import uvicorn
import asyncio
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    FileResponse,
    StreamingResponse,
    Response as FastAPIResponse,
)
from datetime import datetime, timedelta, timezone
from fastapi.concurrency import run_in_threadpool
import os
from urllib.parse import quote, urlparse, unquote_plus
from starlette.background import BackgroundTask
import io
import zipfile
import mammoth
import sys
import tempfile
import subprocess
import threading
from api_utils import (
    base_url,
    get_assignment_location,
    get_draft_text,
    get_parent_structure,
    get_search_list,
    get_section_materials,
    get_material,
    get_upcoming_materials,
    get_sections,
    get_overdue_materials,
    delete_draft,
    save_draft,
    submit_assignment,
    submit_assignment_files,
    get_section,
)
from error_classes import AccountNotFound, InvalidCredentials
from get_token import get_session_token
from app_updater import check_for_updates

if getattr(sys, "frozen", False):
    resource_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    data_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Better-Schoology"
else:
    resource_dir = Path(__file__).resolve().parent
    data_dir = resource_dir

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


LIBREOFFICE_URL = (
    "https://github.com/Momarchristensen/Better-Schoology/releases/download/"
    "libreoffice-runtime/libreoffice.zip"
)

LIBREOFFICE_DIR = data_dir / "libreoffice"
SOFFICE_PATH = LIBREOFFICE_DIR / "program" / "soffice.exe"
LIBREOFFICE_SHA256 = "bc5d73a4a83a665a23701619034795b88c4f3505ac30a44f858ec5d0c4700d2b"
print("Data Dir", data_dir)

html_dir = resource_dir / "web"
legacy_html_dir = resource_dir / "HTML"

if legacy_html_dir.exists() and not html_dir.exists():
    html_dir = legacy_html_dir

html_dir.mkdir(parents=True, exist_ok=True)

RESOURCES_DIR = html_dir / "static"
legacy_resources_dir = html_dir / "resources"

if not RESOURCES_DIR.exists() and legacy_resources_dir.exists():
    RESOURCES_DIR = legacy_resources_dir

RESOURCES_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR = data_dir / "cached_files"
CACHE_DIR.mkdir(parents=True, exist_ok=True)



PORT = 3498

app = FastAPI()

DOCX_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 900px;
            margin: 40px auto;
            padding: 0 30px;
            line-height: 1.6;
        }}

        img {{
            max-width: 100%;
        }}

        table {{
            border-collapse: collapse;
            width: 100%;
        }}

        td, th {{
            border: 1px solid #ccc;
            padding: 8px;
        }}
    </style>
</head>
<body>
    {body}
</body>
</html>
"""


_lo_lock = threading.Lock()
lo_status = {"state": "idle", "progress": 0.0, "error": None}

def parse_session_cookie(cookie_value: Optional[str]):
    if not cookie_value:
        return None
    try:
        return json.loads(cookie_value)
    except json.JSONDecodeError:
        return None


async def session_token_is_valid(session_token):
    if not session_token:
        return False
    async with httpx.AsyncClient(
        http2=True, verify=True, follow_redirects=True, headers={}, trust_env=False
    ) as client:
        client.cookies.update(session_token)
        resp = await client.get(base_url)
        return str(resp.url).startswith(base_url)


def serve_html_file(filename: str):
    file_path = html_dir / filename
    if file_path.exists():
        with open(file_path, "rb") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    raise HTTPException(status_code=404, detail="File not found")


def login_redirect_url(request: Request) -> str:
    return_path = request.url.path
    if request.url.query:
        return_path += f"?{request.url.query}"
    return f"/login?next={quote(return_path, safe='')}"


def safe_next_path(next_path: Optional[str]) -> str:
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/home"


@app.post("/api/get_token")
async def api_get_token(request: Request, response: Response):
    data = await request.json()
    email = data.get("email")
    password = data.get("password")
    try:
        token = await run_in_threadpool(get_session_token, email, password)
        response.set_cookie(
            "sessionToken",
            json.dumps(token),
            max_age=86400,
            path="/",
            httponly=True,
            samesite="lax",
        )
        return {"status": "ok"}
    except AccountNotFound:
        return {"status": "error", "message": "Account not found (invalid email)"}
    except InvalidCredentials:
        return {"status": "error", "message": "Invalid password"}
    except json.JSONDecodeError:
        return {"status": "error", "message": "Invalid JSON"}


@app.post("/api/logout")
async def api_logout(response: Response):
    response.delete_cookie(
        key="sessionToken",
        path="/",
        samesite="lax",
    )

    return {"status": "ok"}


def extract_filename(url: str, headers: dict | None = None) -> str:
    if headers and "content-disposition" in headers:
        cd = headers["content-disposition"]

        m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.IGNORECASE)
        if m:
            return unquote_plus(m.group(1).strip().strip('"'))

        m = re.search(r'filename="([^"]+)"', cd, re.IGNORECASE)
        if not m:
            m = re.search(r"filename=([^;]+)", cd, re.IGNORECASE)
        if m:
            return unquote_plus(m.group(1).strip().strip('"'))

    path = urlparse(url).path
    filename = os.path.basename(path)

    return unquote_plus(filename) or "file"


def get_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def cache_paths(cache_key: str):
    data_path = CACHE_DIR / cache_key
    meta_path = CACHE_DIR / f"{cache_key}.meta.json"
    return data_path, meta_path


def read_cache(cache_key: str) -> Optional[dict]:
    data_path, meta_path = cache_paths(cache_key)
    if not (data_path.exists() and meta_path.exists()):
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    meta["data_path"] = data_path
    return meta


def write_cache(
    cache_key: str, content: bytes, filename: str, media_type: str, kind: str
):
    data_path, meta_path = cache_paths(cache_key)
    data_path.write_bytes(content)
    meta_path.write_text(
        json.dumps({"filename": filename, "media_type": media_type, "kind": kind}),
        encoding="utf-8",
    )


def serve_cached(meta: dict):
    data_path: Path = meta["data_path"]
    kind = meta.get("kind", "raw")
    filename = meta.get("filename", data_path.name)
    media_type = meta.get("media_type", "application/octet-stream")

    if kind == "html":
        return HTMLResponse(content=data_path.read_bytes(), media_type="text/html")

    return FileResponse(
        data_path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
    )


def libreoffice_installed() -> bool:
    return SOFFICE_PATH.exists()



import certifi

FALLBACK_HTTP_OPTIONS = {"trust_env": False, "verify": certifi.where()}


def _download_libreoffice(zip_path: Path, **client_options) -> str:
    """Download the zip to zip_path and return its SHA-256 hex digest."""
    sha = hashlib.sha256()
    with httpx.stream(
        "GET", LIBREOFFICE_URL, follow_redirects=True, timeout=None, **client_options
    ) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(zip_path, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if total:
                    lo_status["progress"] = 0.9 * done / total
    return sha.hexdigest()


def ensure_libreoffice():
    """Download and extract LibreOffice on first use (blocking, thread-safe)."""
    if libreoffice_installed():
        return

    with _lo_lock:
        if libreoffice_installed():
            return

        zip_path = data_dir / "libreoffice.zip.part"
        extract_dir = data_dir / "libreoffice.tmp"
        shutil.rmtree(extract_dir, ignore_errors=True)
        shutil.rmtree(LIBREOFFICE_DIR, ignore_errors=True)

        try:
            lo_status.update(state="downloading", progress=0.0, error=None)

            try:
                digest = _download_libreoffice(zip_path)
            except Exception as first_exc:
                print(
                    f"LibreOffice download failed ({first_exc}); retrying with fallback options",
                    file=sys.stderr,
                )
                zip_path.unlink(missing_ok=True)
                lo_status["progress"] = 0.0
                digest = _download_libreoffice(zip_path, **FALLBACK_HTTP_OPTIONS)

            if digest.lower() != LIBREOFFICE_SHA256.lower():
                raise RuntimeError("LibreOffice download failed integrity check")

            lo_status.update(state="extracting", progress=0.9)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_dir)

            os.replace(extract_dir, LIBREOFFICE_DIR)
            lo_status.update(state="ready", progress=1.0)
        except Exception as exc:
            lo_status.update(state="error", error=str(exc))
            shutil.rmtree(extract_dir, ignore_errors=True)
            raise
        finally:
            zip_path.unlink(missing_ok=True)


def convert_docx_to_html(docx_bytes: bytes, _ext: str) -> bytes:
    result = mammoth.convert_to_html(io.BytesIO(docx_bytes))
    html = DOCX_HTML_TEMPLATE.format(title="document", body=result.value)
    return html.encode("utf-8")


def convert_ppt_to_pdf(ppt_bytes: bytes, extension: str = ".pptx") -> bytes:
    ensure_libreoffice()
    with tempfile.TemporaryDirectory() as tmp_dir:
        ppt_path = os.path.join(tmp_dir, f"slides{extension}")

        with open(ppt_path, "wb") as f:
            f.write(ppt_bytes)

        # Give each conversion its own LibreOffice profile dir. Sharing the
        # default profile across concurrent/back-to-back conversions can
        # cause silent failures due to profile-lock contention.
        profile_dir = Path(tmp_dir) / "profile"

        result = subprocess.run(
            [
                str(SOFFICE_PATH),
                "--headless",
                "--norestore",
                f"-env:UserInstallation=file:///{profile_dir.as_posix()}",
                "--convert-to",
                "pdf",
                "--outdir",
                tmp_dir,
                ppt_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise Exception(f"PowerPoint -> PDF conversion failed: {result.stderr}")

        pdf_path = os.path.join(tmp_dir, "slides.pdf")

        if not os.path.exists(pdf_path):
            raise Exception("Expected converted PDF not found")

        with open(pdf_path, "rb") as f:
            return f.read()


CONVERTERS = {
    ".docx": {
        "convert": convert_docx_to_html,
        "kind": "html",
        "media_type": "text/html",
        "out_ext": ".html",
    },
    ".ppt": {
        "convert": convert_ppt_to_pdf,
        "kind": "pdf",
        "media_type": "application/pdf",
        "out_ext": ".pdf",
    },
    ".pptx": {
        "convert": convert_ppt_to_pdf,
        "kind": "pdf",
        "media_type": "application/pdf",
        "out_ext": ".pdf",
    },
}


@app.get("/api/search_list")
async def api_search_list(request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)

    if not token:
        raise HTTPException(status_code=401, detail="No session token")

    return await get_search_list(token)


@app.get("/api/file")
async def api_file(url: str, request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)

    if not token:
        raise HTTPException(status_code=401, detail="No session token")

    cache_key = get_cache_key(url)

    cached_meta = read_cache(cache_key)
    if cached_meta:
        return serve_cached(cached_meta)

    client = httpx.AsyncClient(
        http2=True, verify=False, follow_redirects=True, trust_env=False
    )
    client.cookies.update(token)

    range_header = request.headers.get("range")
    request_headers = {"Range": range_header} if range_header else {}

    req = client.build_request("GET", url, headers=request_headers)
    r = await client.send(req, stream=True)

    if r.status_code not in (200, 206):
        await r.aclose()
        await client.aclose()
        raise HTTPException(status_code=400, detail="Failed to fetch file")

    filename = extract_filename(url, r.headers)
    ext = os.path.splitext(filename)[1].lower()
    converter = CONVERTERS.get(ext)

    if converter:
        try:
            raw_bytes = await r.aread()
            await r.aclose()
            converted = await run_in_threadpool(converter["convert"], raw_bytes, ext)
        except Exception as exc:
            await client.aclose()
            raise HTTPException(
                status_code=500, detail=f"Failed to convert {ext}: {exc}"
            )

        await client.aclose()

        out_filename = os.path.splitext(filename)[0] + converter["out_ext"]
        write_cache(
            cache_key,
            converted,
            filename=out_filename,
            media_type=converter["media_type"],
            kind=converter["kind"],
        )

        if converter["kind"] == "html":
            return HTMLResponse(content=converted, media_type="text/html")

        return FastAPIResponse(
            content=converted,
            media_type=converter["media_type"],
            headers={"Content-Disposition": f'inline; filename="{out_filename}"'},
        )

    if not range_header:
        try:
            raw_bytes = await r.aread()
        except Exception as exc:
            await r.aclose()
            await client.aclose()
            raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")

        await r.aclose()
        await client.aclose()

        media_type = r.headers.get("content-type", "application/octet-stream")

        write_cache(
            cache_key,
            raw_bytes,
            filename=filename,
            media_type=media_type,
            kind="raw",
        )

        return FastAPIResponse(
            content=raw_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    response_headers = {"Content-Disposition": f'inline; filename="{filename}"'}

    for header in (
        "content-length",
        "content-range",
        "accept-ranges",
        "etag",
        "last-modified",
    ):
        if header in r.headers:
            response_headers[header] = r.headers[header]

    async def cleanup():
        await r.aclose()
        await client.aclose()

    return StreamingResponse(
        r.aiter_bytes(),
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/octet-stream"),
        headers=response_headers,
        background=BackgroundTask(cleanup),
    )


@app.get("/api/attachments.zip")
async def api_attachments_zip(request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)

    if not token:
        raise HTTPException(status_code=401, detail="No session token")

    urls = request.query_params.getlist("url")
    if not urls:
        raise HTTPException(status_code=400, detail="No attachment URLs")

    archive = io.BytesIO()
    used_names = set()

    async with httpx.AsyncClient(
        http2=True, verify=False, follow_redirects=True, trust_env=False
    ) as client:
        client.cookies.update(token)

        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for index, url in enumerate(urls, start=1):
                response = await client.get(url)
                if response.status_code >= 400:
                    raise HTTPException(status_code=400, detail="Failed to fetch attachment")

                filename = extract_filename(url, response.headers) or f"attachment-{index}"
                filename = Path(filename).name or f"attachment-{index}"
                stem = Path(filename).stem
                suffix = Path(filename).suffix
                candidate = filename
                duplicate = 2
                while candidate.lower() in used_names:
                    candidate = f"{stem} ({duplicate}){suffix}"
                    duplicate += 1
                used_names.add(candidate.lower())
                zip_file.writestr(candidate, response.content)

    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="attachments.zip"'},
    )


@app.get("/api/courses")
async def api_courses(request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not token:
        return {"status": "error", "message": "No session token"}
    courses = await get_sections(token)
    return {"status": "ok", "courses": courses}


@app.get("/api/section_details/{section_id}")
async def api_section_details(request: Request, section_id: str):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not token:
        return {"status": "error", "message": "No session token"}

    section = await get_section(token, section_id)

    return {"status": "ok", "section": section}


@app.get("/api/section/{full_path:path}")
async def api_section(full_path: str, request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not token:
        return {"status": "error", "message": "No session token"}

    parts = list(filter(None, full_path.strip("/").split("/")))
    section_id = parts[0] if parts else None
    if not section_id:
        return {"status": "error", "message": "Invalid API path"}

    folder_id = None
    if len(parts) >= 2 and parts[1] == "folder":
        folder_id = parts[2] if len(parts) >= 3 else None
        if folder_id == "root":
            folder_id = None

    if "material" in parts:
        try:
            mat_index = parts.index("material")
            material_id = parts[mat_index + 1]
        except Exception:
            material_id = None
        if not material_id:
            return {"status": "error", "message": "Material not found"}

        material_json = await get_material(token, section_id, folder_id, material_id)
        return {"status": "ok", "material": material_json}

    materials = await get_section_materials(token, section_id, folder_id)
    if not materials:
        return {"status": "error", "message": "Course not found"}

    return {"status": "ok", "materials": materials}


_whisper_model = None
_whisper_lock = threading.Lock()


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        # "base" is fast; use "small" or "medium" for better accuracy.
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper_model


def _vtt_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def generate_vtt(media_bytes: bytes, suffix: str, on_progress=None) -> str:
    with tempfile.TemporaryDirectory() as tmp_dir:
        media_path = os.path.join(tmp_dir, f"media{suffix}")
        with open(media_path, "wb") as f:
            f.write(media_bytes)

        lines = ["WEBVTT", ""]
        with _whisper_lock:
            model = _get_whisper_model()
            segments, info = model.transcribe(media_path, vad_filter=True)
            total = info.duration or 0
            for seg in segments:
                if on_progress and total:
                    on_progress(min(seg.end / total, 1.0))
                text = seg.text.strip()
                if not text:
                    continue
                lines.append(
                    f"{_vtt_timestamp(seg.start)} --> {_vtt_timestamp(seg.end)}"
                )
                lines.append(text)
                lines.append("")

        return "\n".join(lines)



_caption_jobs: dict[str, dict] = {}
_background_tasks: set = set()


async def _run_caption_job(job_id: str, token: dict, url: str):
    job = _caption_jobs[job_id]
    try:
        chunks = []
        async with httpx.AsyncClient(
            http2=True, verify=False, follow_redirects=True, trust_env=False
        ) as client:
            client.cookies.update(token)
            async with client.stream("GET", url, timeout=None) as r:
                if r.status_code != 200:
                    raise Exception(f"Failed to fetch video (HTTP {r.status_code})")
                total = int(r.headers.get("content-length") or 0)
                received = 0
                async for chunk in r.aiter_bytes():
                    chunks.append(chunk)
                    received += len(chunk)
                    if total:
                        job["progress"] = 0.15 * received / total
                filename = extract_filename(url, r.headers)

        media = b"".join(chunks)
        suffix = Path(filename).suffix or ".mp4"

        job["status"] = "transcribing"
        job["progress"] = 0.15

        def on_progress(frac: float):
            job["progress"] = 0.15 + 0.85 * frac

        vtt = await run_in_threadpool(generate_vtt, media, suffix, on_progress)

        write_cache(
            job_id,
            vtt.encode("utf-8"),
            filename="captions.vtt",
            media_type="text/vtt",
            kind="raw",
        )
        job.update(status="done", progress=1.0)
    except Exception as exc:
        job.update(status="error", error=str(exc))



@app.api_route("/captions", methods=["GET", "POST"])
async def api_captions(request: Request):
    token = parse_session_cookie(request.cookies.get("sessionToken"))
    if not token:
        raise HTTPException(status_code=401, detail="No session token")

    url = request.query_params.get("url")
    upload_bytes: Optional[bytes] = None
    suffix = ".mp4"

    if request.method == "POST":
        form = await request.form()
        url = form.get("url") or url
        upload = form.get("file")
        if upload is not None and getattr(upload, "filename", None):
            upload_bytes = await upload.read()
            suffix = Path(upload.filename).suffix or ".mp4"

    if not upload_bytes and not url:
        raise HTTPException(status_code=400, detail="Provide a video file or url")

    if upload_bytes:
        cache_key = "captions-" + hashlib.sha256(upload_bytes).hexdigest()
    else:
        cache_key = "captions-" + get_cache_key(url)

    cached_meta = read_cache(cache_key)
    if cached_meta:
        return serve_cached(cached_meta)

    if not upload_bytes:
        async with httpx.AsyncClient(
            http2=True, verify=False, follow_redirects=True, trust_env=False
        ) as client:
            client.cookies.update(token)
            r = await client.get(url, timeout=None)
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch video")
        upload_bytes = r.content
        suffix = Path(extract_filename(url, r.headers)).suffix or ".mp4"

    try:
        vtt = await run_in_threadpool(generate_vtt, upload_bytes, suffix)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Caption generation failed: {exc}")

    write_cache(
        cache_key,
        vtt.encode("utf-8"),
        filename="captions.vtt",
        media_type="text/vtt",
        kind="raw",
    )

    return FastAPIResponse(
        content=vtt,
        media_type="text/vtt",
        headers={"Content-Disposition": 'inline; filename="captions.vtt"'},
    )




@app.get("/captions/start")
async def captions_start(request: Request, url: str):
    token = parse_session_cookie(request.cookies.get("sessionToken"))
    if not token:
        raise HTTPException(status_code=401, detail="No session token")

    job_id = "captions-" + get_cache_key(url)  # same key /captions uses for its cache

    if read_cache(job_id):
        return {"job": job_id, "status": "done", "progress": 1.0}

    job = _caption_jobs.get(job_id)
    if not job or job["status"] == "error":
        _caption_jobs[job_id] = {"status": "downloading", "progress": 0.0, "error": None}
        task = asyncio.create_task(_run_caption_job(job_id, token, url))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return {"job": job_id, **_caption_jobs[job_id]}


@app.get("/captions/status")
async def captions_status(request: Request, job: str):
    if not parse_session_cookie(request.cookies.get("sessionToken")):
        raise HTTPException(status_code=401, detail="No session token")

    info = _caption_jobs.get(job)
    if not info:
        if read_cache(job):
            return {"status": "done", "progress": 1.0, "error": None}
        raise HTTPException(status_code=404, detail="Unknown job")
    return info



@app.get("/api/parent_structure")
async def api_parent_structure(request: Request, section_id: str, folder_id: str):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not token:
        return {"status": "error", "message": "No session token"}

    structure = await get_parent_structure(token, section_id, folder_id)
    return {"status": "ok", "structure": structure}


@app.get("/api/overdue")
async def api_overdue(request: Request, section_id: Optional[str] = None):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not token:
        return {"status": "error", "message": "No session token"}

    overdue_materials = await get_overdue_materials(token, section_id)
    return {"status": "ok", "materials": overdue_materials}


@app.get("/api/upcoming")
async def api_upcoming(request: Request, section_id: Optional[str] = None):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not token:
        return {"status": "error", "message": "No session token"}

    upcoming_materials = await get_upcoming_materials(token, section_id)
    return {"status": "ok", "materials": upcoming_materials}


@app.post("/submit_assignment")
async def api_submit_assignment(request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not token:
        return {"status": "error", "message": "No session token"}

    form = await request.form()

    assignment_id = form.get("assignment_id")
    if not assignment_id:
        return {"status": "error", "message": "Missing assignment_id"}

    draft_revision_id = form.get("draft_revision_id") or None
    if draft_revision_id == "null":
        draft_revision_id = None

    html = form.get("html")
    comment = form.get("comment") or ""
    uploads = form.getlist("files")

    has_html = bool(html and html.strip())
    has_files = any(getattr(upload, "filename", None) for upload in uploads)

    if not has_html and not has_files:
        return {"status": "error", "message": "Nothing to submit"}

    if has_html and has_files:
        return {
            "status": "error",
            "message": "Submit either written text or files, not both",
        }

    try:
        if has_html:
            resp = await submit_assignment(token, assignment_id, html)
            if resp.status_code >= 400:
                return {
                    "status": "error",
                    "message": f"Text submission failed ({resp.status_code})",
                }
            return {"status": "ok", "results": {"text_submission": "ok"}}

        file_payloads = []
        for upload in uploads:
            filename = getattr(upload, "filename", None)
            if not filename:
                continue
            content = await upload.read()
            if not content:
                continue
            file_payloads.append({"file_name": filename, "file_content": content})

        if not file_payloads:
            return {"status": "error", "message": "Nothing to submit"}

        # Schoology hides the upload form while a draft exists. If the
        # client tells us there's a draft in play, snapshot its text and
        # clear it before attempting the upload. On any failure, restore
        # the draft so nothing the user typed is lost.
        saved_draft_text = None
        if draft_revision_id:
            try:
                saved_draft_text = await get_draft_text(token, assignment_id)
            except Exception:
                saved_draft_text = None

            try:
                await delete_draft(token, assignment_id, draft_revision_id)
            except Exception as exc:
                return {
                    "status": "error",
                    "message": f"Could not clear existing draft before uploading: {exc}",
                }

        try:
            resp = await submit_assignment_files(
                token, assignment_id, file_payloads, comment=comment
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"File submission failed ({resp.status_code})")
        except Exception as exc:
            if draft_revision_id and saved_draft_text is not None:
                try:
                    await save_draft(token, assignment_id, saved_draft_text)
                except Exception:
                    pass
            return {"status": "error", "message": f"Submission failed: {exc}"}

        return {"status": "ok", "results": {"file_submission": "ok"}}
    except Exception as exc:
        return {"status": "error", "message": f"Submission failed: {exc}"}


@app.post("/save_draft")
async def api_save_draft(request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not token:
        return {"status": "error", "message": "No session token"}

    form = await request.form()

    assignment_id = form.get("assignment_id")
    html = form.get("html")

    if not assignment_id or not (html and html.strip()):
        return {"status": "error", "message": "Nothing to save"}

    try:
        resp = await save_draft(token, assignment_id, html)
        if resp.status_code >= 400:
            return {
                "status": "error",
                "message": f"Draft save failed ({resp.status_code})",
            }
    except Exception as exc:
        return {"status": "error", "message": f"Draft save failed: {exc}"}

    return {"status": "ok"}


@app.post("/delete_draft")
async def api_delete_draft(request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not token:
        return {"status": "error", "message": "No session token"}

    form = await request.form()
    assignment_id = form.get("assignment_id")
    revision_id = form.get("revision_id")

    if not assignment_id or not revision_id:
        return {"status": "error", "message": "Missing draft identifiers"}

    try:
        response = await delete_draft(token, assignment_id, revision_id)
        if response.status_code >= 400:
            return {
                "status": "error",
                "message": f"Draft deletion failed ({response.status_code})",
            }
    except Exception as exc:
        return {"status": "error", "message": f"Draft deletion failed: {exc}"}

    return {"status": "ok"}


@app.get("/")
async def root():
    return RedirectResponse(url="/login")


@app.get("/login")
async def login_page(request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    is_valid = await session_token_is_valid(token)
    if is_valid:
        return RedirectResponse(url=safe_next_path(request.query_params.get("next")))

    return serve_html_file("login.html")


@app.get("/home")
async def home_page(request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not await session_token_is_valid(token):
        return RedirectResponse(url=login_redirect_url(request))

    return serve_html_file("home.html")

@app.get("/calendar")
async def calendar_page(request: Request):
    token = parse_session_cookie(request.cookies.get("sessionToken"))
    if not await session_token_is_valid(token):
        return RedirectResponse(url=login_redirect_url(request))
    return serve_html_file("calendar.html")




def _ics_text(s) -> str:
    return (str(s).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))

@app.get("/api/calendar.ics")
async def api_calendar_ics(request: Request):
    token = parse_session_cookie(request.cookies.get("sessionToken"))
    if not token:
        raise HTTPException(status_code=401, detail="No session token")

    materials = await get_upcoming_materials(token, None)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Better Schoology//EN"]
    for m in materials:
        due = datetime.fromisoformat(str(m["dueDate"]))         # <-- adjust key and format
        if due.tzinfo is None:
            due = due.astimezone()                           # treat naive times as local
        due = due.astimezone(timezone.utc)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{m['id']}@better-schoology",                # <-- adjust key
            f"DTSTAMP:{now}",
            f"DTSTART:{due.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{(due + timedelta(minutes=30)).strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{_ics_text(m.get('title', 'Assignment'))}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return FastAPIResponse(
        content="\r\n".join(lines) + "\r\n",
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="schoology.ics"'},
    )

@app.get("/settings")
async def settings_page(request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not await session_token_is_valid(token):
        return RedirectResponse(url=login_redirect_url(request))

    return serve_html_file("settings.html")


@app.get("/section/{full_path:path}")
async def section_page(full_path: str, request: Request):
    cookie = request.cookies.get("sessionToken")
    token = parse_session_cookie(cookie)
    if not await session_token_is_valid(token):
        return RedirectResponse(url=login_redirect_url(request))

    parts = full_path.strip("/").split("/")
    if parts and parts[0]:
        section_id = parts[0]
        if len(parts) >= 3 and parts[1] == "assignment":
            assignment_id = parts[2]
            if not assignment_id:
                raise HTTPException(status_code=404, detail="Assignment not found")

            section_id, folder_id, assignment_id = await get_assignment_location(
                token, section_id, assignment_id
            )

            redirect_url = (
                f"/section/{section_id}/folder/{folder_id}/material/{assignment_id}"
            )
            if redirect_url:
                return RedirectResponse(url=redirect_url)

            raise HTTPException(status_code=404, detail="Assignment not found")

        if len(parts) >= 2 and parts[1] == "folder":
            if len(parts) >= 4 and parts[3] == "material":

                return serve_html_file("material.html")
            return serve_html_file("course.html")
        else:
            return serve_html_file("course.html")

    raise HTTPException(status_code=404, detail="Path not found")


@app.get("/{filename}")
async def serve_resource(filename: str):
    file_path = (RESOURCES_DIR / filename).resolve()

    if (
        RESOURCES_DIR.resolve() not in file_path.parents
        and file_path != RESOURCES_DIR.resolve()
    ):
        raise HTTPException(status_code=404, detail="Not found")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    return FileResponse(file_path)


if __name__ == "__main__":
    try:
        check_for_updates()
    except Exception as exc:
        print(f"Update check failed: {exc}", file=sys.stderr)
    print(f"Serving at http://localhost:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT)
