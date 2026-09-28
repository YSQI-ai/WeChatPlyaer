# WeChat Converter API

This service exposes short-lived conversion responses for a WeChat mini program.
Uploaded files are written to a per-request temporary directory and removed after the response is sent.

## Endpoints

- `GET /api/v1/test`: standalone deployment smoke test and capability list.
- `GET /api/v1/health`: health check.
- `POST /api/v1/convert/document-to-pdf`: multipart field `file`; supports `doc`, `docx`, `odt`, `ott`, `rtf`, and `txt`.
- `POST /api/v1/convert/media`: multipart fields `file` and `target_format`; supports `mp3`, `wav`, `flac`, `ogg`, `opus`, `aac`, `m4a`, `mp4`, `webm`, `mkv`, `mov`, and `avi`.
- Both conversion endpoints accept `response_mode=link` for clients that upload and download in separate requests. The response contains a one-time download URL that expires after 15 minutes by default. Omit the field or use `response_mode=file` to retain the direct file response.
- `GET /api/v1/download/{token}`: downloads a converted result created with `response_mode=link`; the temporary result is deleted after download or expiry.

## Example requests

```bash
curl http://SERVER_IP/api/v1/test
curl -f -F file=@sample.docx http://SERVER_IP/api/v1/convert/document-to-pdf -o sample.pdf
curl -f -F file=@sample.mp4 -F target_format=mp3 http://SERVER_IP/api/v1/convert/media -o sample.mp3
```

The OpenAPI schema is available at `/docs` and `/openapi.json`.
