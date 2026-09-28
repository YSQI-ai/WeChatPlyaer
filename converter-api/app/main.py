from __future__ import annotations

import logging
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


SERVICE_NAME = "wechat-converter-api"
SERVICE_VERSION = "1.0.0"
CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
CONVERSION_TIMEOUT_SECONDS = int(os.getenv("CONVERSION_TIMEOUT_SECONDS", "600"))
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))
TMP_ROOT = Path(os.getenv("CONVERTER_TMP_ROOT", "/var/lib/wechat-converter/tmp"))
LIBREOFFICE_BIN = os.getenv("LIBREOFFICE_BIN", "libreoffice")
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")

logger = logging.getLogger(SERVICE_NAME)
conversion_slots = threading.BoundedSemaphore(MAX_CONCURRENT_JOBS)

DOCUMENT_EXTENSIONS = {
    "doc",
    "docx",
    "odt",
    "ott",
    "rtf",
    "txt",
}

MEDIA_PROFILES: dict[str, dict[str, object]] = {
    "mp3": {
        "args": ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"],
        "media_type": "audio/mpeg",
    },
    "wav": {
        "args": ["-vn", "-c:a", "pcm_s16le"],
        "media_type": "audio/wav",
    },
    "flac": {
        "args": ["-vn", "-c:a", "flac"],
        "media_type": "audio/flac",
    },
    "ogg": {
        "args": ["-vn", "-c:a", "libvorbis", "-q:a", "5"],
        "media_type": "audio/ogg",
    },
    "opus": {
        "args": ["-vn", "-c:a", "libopus", "-b:a", "128k"],
        "media_type": "audio/ogg",
    },
    "aac": {
        "args": ["-vn", "-c:a", "aac", "-b:a", "192k"],
        "media_type": "audio/aac",
    },
    "m4a": {
        "args": ["-vn", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"],
        "media_type": "audio/mp4",
    },
    "mp4": {
        "args": [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
        ],
        "media_type": "video/mp4",
    },
    "webm": {
        "args": [
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "32",
            "-b:v",
            "0",
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
        ],
        "media_type": "video/webm",
    },
    "mkv": {
        "args": [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
        ],
        "media_type": "video/x-matroska",
    },
    "mov": {
        "args": [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
        ],
        "media_type": "video/quicktime",
    },
    "avi": {
        "args": ["-c:v", "mpeg4", "-q:v", "5", "-c:a", "libmp3lame", "-b:a", "192k"],
        "media_type": "video/x-msvideo",
    },
}


class UploadTooLarge(Exception):
    pass


class ConversionFailed(Exception):
    pass


def _safe_stem(filename: str | None) -> str:
    raw_stem = Path(filename or "upload").stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_stem).strip("._")
    return safe_stem[:120] or "converted"


def _extension(filename: str | None) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def _new_job_dir() -> Path:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="job-", dir=TMP_ROOT))


def _remove_job_dir(job_dir: str | Path) -> None:
    shutil.rmtree(job_dir, ignore_errors=True)


def _save_upload(upload: UploadFile, destination: Path) -> int:
    total = 0
    with destination.open("wb") as output:
        while True:
            chunk = upload.file.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise UploadTooLarge
            output.write(chunk)
    return total


def _run_command(command: list[str], cwd: Path) -> None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=CONVERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ConversionFailed(f"Required converter is not installed: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConversionFailed("Conversion timed out") from exc

    if result.returncode != 0:
        error_tail = (result.stderr or result.stdout or "converter failed").strip()[-2000:]
        logger.warning("Converter failed with exit code %s: %s", result.returncode, error_tail)
        raise ConversionFailed("The file could not be converted")


def _convert_document(job_dir: Path, input_path: Path) -> tuple[Path, str]:
    output_dir = job_dir / "output"
    output_dir.mkdir()
    profile_dir = job_dir / "libreoffice-profile"
    profile_uri = profile_dir.as_uri()
    command = [
        LIBREOFFICE_BIN,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        f"-env:UserInstallation={profile_uri}",
        str(input_path),
    ]
    _run_command(command, job_dir)
    expected_output = output_dir / f"{input_path.stem}.pdf"
    if not expected_output.exists():
        candidates = list(output_dir.glob("*.pdf"))
        if len(candidates) != 1:
            raise ConversionFailed("The document converter did not produce a PDF")
        expected_output = candidates[0]
    return expected_output, "application/pdf"


def _convert_media(job_dir: Path, input_path: Path, target_format: str) -> tuple[Path, str]:
    target = target_format.lower().strip().lstrip(".")
    profile = MEDIA_PROFILES.get(target)
    if profile is None:
        raise ValueError(f"Unsupported target format: {target}")
    output_path = job_dir / f"{_safe_stem(input_path.name)}.{target}"
    command = [
        FFMPEG_BIN,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-map_metadata",
        "0",
        *profile["args"],  # type: ignore[index]
        str(output_path),
    ]
    _run_command(command, job_dir)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ConversionFailed("The media converter did not produce an output file")
    return output_path, str(profile["media_type"])


def _file_response(output_path: Path, media_type: str, download_name: str, job_dir: Path) -> FileResponse:
    return FileResponse(
        output_path,
        media_type=media_type,
        filename=download_name,
        background=BackgroundTask(_remove_job_dir, job_dir),
    )


def _handle_failure(job_dir: Path, exc: Exception) -> None:
    _remove_job_dir(job_dir)
    if isinstance(exc, UploadTooLarge):
        raise HTTPException(status_code=413, detail="Uploaded file is too large") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, ConversionFailed):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.exception("Unexpected conversion failure")
    raise HTTPException(status_code=500, detail="Unexpected conversion failure") from exc


def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOW_ORIGINS", "*")
    if configured.strip() == "*":
        return ["*"]
    return [item.strip() for item in configured.split(",") if item.strip()]


app = FastAPI(
    title="WeChat Converter API",
    version=SERVICE_VERSION,
    description="Document and media conversion service for a WeChat mini program.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
    }


@app.get("/api/v1/test")
def test_endpoint() -> dict[str, object]:
    """Standalone capability endpoint for a quick deployment smoke test."""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "message": "converter API is ready",
        "document_endpoint": "POST /api/v1/convert/document-to-pdf",
        "media_endpoint": "POST /api/v1/convert/media",
        "document_extensions": sorted(DOCUMENT_EXTENSIONS),
        "media_formats": sorted(MEDIA_PROFILES),
        "max_upload_bytes": MAX_UPLOAD_BYTES,
    }


@app.post("/api/v1/convert/document-to-pdf")
def document_to_pdf(file: UploadFile = File(...)) -> FileResponse:
    extension = _extension(file.filename)
    if extension not in DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported document type. Allowed: {', '.join(sorted(DOCUMENT_EXTENSIONS))}",
        )
    if not conversion_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Too many conversions in progress")

    job_dir = _new_job_dir()
    try:
        input_path = job_dir / f"input.{extension}"
        _save_upload(file, input_path)
        output_path, media_type = _convert_document(job_dir, input_path)
        return _file_response(output_path, media_type, f"{_safe_stem(file.filename)}.pdf", job_dir)
    except (UploadTooLarge, ConversionFailed, ValueError) as exc:
        _handle_failure(job_dir, exc)
        raise AssertionError("unreachable")
    except Exception as exc:
        _handle_failure(job_dir, exc)
        raise AssertionError("unreachable")
    finally:
        file.file.close()
        conversion_slots.release()


@app.post("/api/v1/convert/media")
def media_convert(
    file: UploadFile = File(...),
    target_format: str = Form(..., description="Target format, for example mp3 or mp4"),
) -> FileResponse:
    target = target_format.lower().strip().lstrip(".")
    if target not in MEDIA_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported target format. Allowed: {', '.join(sorted(MEDIA_PROFILES))}",
        )
    if not conversion_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Too many conversions in progress")

    job_dir = _new_job_dir()
    try:
        input_extension = _extension(file.filename) or "input"
        input_path = job_dir / f"input.{input_extension}"
        _save_upload(file, input_path)
        output_path, media_type = _convert_media(job_dir, input_path, target)
        download_name = f"{_safe_stem(file.filename)}.{target}"
        return _file_response(output_path, media_type, download_name, job_dir)
    except (UploadTooLarge, ConversionFailed, ValueError) as exc:
        _handle_failure(job_dir, exc)
        raise AssertionError("unreachable")
    except Exception as exc:
        _handle_failure(job_dir, exc)
        raise AssertionError("unreachable")
    finally:
        file.file.close()
        conversion_slots.release()


@app.get("/")
def root() -> dict[str, str]:
    return {"service": SERVICE_NAME, "docs": "/docs", "test": "/api/v1/test"}
