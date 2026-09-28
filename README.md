# WeChatPlayer 转换服务

这是一个面向微信小程序的文件转换后端服务，提供文档转 PDF、音视频格式转换以及健康检查接口。服务基于 FastAPI 编写，转换任务分别调用 LibreOffice 和 FFmpeg 完成，转换结果以文件流形式返回。

## 功能概览

- 文档转 PDF：支持 `doc`、`docx`、`odt`、`ott`、`rtf`、`txt`。
- 媒体格式转换：支持 `mp3`、`wav`、`flac`、`ogg`、`opus`、`aac`、`m4a`、`mp4`、`webm`、`mkv`、`mov`、`avi`。
- 健康检查和部署自检接口。
- 每个请求使用独立临时目录，响应完成后自动清理上传文件和输出文件。
- 上传大小、转换超时、并发任务数、临时目录和 CORS 来源均可通过环境变量配置。
- 内置 OpenAPI 文档，可通过 `/docs` 或 `/openapi.json` 查看。

## 目录结构

```text
.
├── converter-api/
│   ├── app/
│   │   ├── __init__.py
│   │   └── main.py                 # FastAPI 应用与转换逻辑
│   ├── deploy/
│   │   ├── wechat-converter.service # systemd 服务模板
│   │   └── wechat-converter.conf    # Nginx 反向代理模板
│   ├── requirements.txt
│   └── README.md
└── .gitignore
```

## 运行环境

- Python 3.9 或更高版本（建议使用虚拟环境）。
- LibreOffice：用于文档转 PDF。
- FFmpeg：用于音视频格式转换。
- Linux 部署时建议使用 Nginx + systemd。

## 本地启动

```bash
cd converter-api
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 18080 --reload
```

启动后可访问：

- 服务根路径：`http://127.0.0.1:18080/`
- Swagger 文档：`http://127.0.0.1:18080/docs`
- 健康检查：`http://127.0.0.1:18080/api/v1/health`
- 部署自检：`http://127.0.0.1:18080/api/v1/test`

## API 接口

### `GET /api/v1/health`

返回服务状态、版本和当前上传大小限制。

### `GET /api/v1/test`

返回服务能力列表，适合部署完成后的快速检查。

### `POST /api/v1/convert/document-to-pdf`

使用 `multipart/form-data` 上传字段 `file`。文件扩展名必须属于支持的文档类型，成功后返回 `application/pdf` 文件流。

```bash
curl -f -F "file=@sample.docx" \
  http://127.0.0.1:18080/api/v1/convert/document-to-pdf \
  -o sample.pdf
```

### `POST /api/v1/convert/media`

使用 `multipart/form-data` 上传字段 `file` 和 `target_format`。`target_format` 可以带或不带点号，例如 `mp3` 或 `.mp3`。

```bash
curl -f -F "file=@sample.mp4" -F "target_format=mp3" \
  http://127.0.0.1:18080/api/v1/convert/media \
  -o sample.mp3
```

## 配置项

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MAX_UPLOAD_BYTES` | `536870912` | 单个上传文件最大字节数，默认 512 MiB |
| `CONVERSION_TIMEOUT_SECONDS` | `600` | 单次转换超时时间 |
| `MAX_CONCURRENT_JOBS` | `2` | 同时执行的最大转换任务数 |
| `CONVERTER_TMP_ROOT` | `/var/lib/wechat-converter/tmp` | 转换任务临时目录 |
| `LIBREOFFICE_BIN` | `libreoffice` | LibreOffice 可执行文件路径或命令名 |
| `FFMPEG_BIN` | `ffmpeg` | FFmpeg 可执行文件路径或命令名 |
| `CORS_ALLOW_ORIGINS` | `*` | 允许的 CORS 来源，多个来源用逗号分隔 |

示例：

```bash
export MAX_UPLOAD_BYTES=$((256 * 1024 * 1024))
export MAX_CONCURRENT_JOBS=4
export CORS_ALLOW_ORIGINS="https://example.com,https://miniapp.example.com"
```

## 错误状态码

| 状态码 | 含义 |
| --- | --- |
| `400` | 目标格式参数无效 |
| `413` | 上传文件超过大小限制 |
| `415` | 不支持的文档类型 |
| `422` | 转换器执行失败、超时或未生成输出文件 |
| `429` | 当前转换任务数已达到并发上限 |
| `500` | 未预期的服务端错误 |

## Linux 部署

项目提供了 `converter-api/deploy/` 下的 systemd 和 Nginx 模板。模板默认约定：

1. 应用部署到 `/opt/wechat-converter-api`，并在该目录创建 `.venv`。
2. 以 `converter` 用户运行 Uvicorn，监听 `127.0.0.1:18080`。
3. Nginx 对外监听 80 端口，并将 `/api/v1/`、`/docs` 和 `/openapi.json` 代理到应用。
4. `/var/lib/wechat-converter` 用于保存临时文件，运行用户需要具备读写权限。

基本安装流程示例：

```bash
sudo apt-get install -y python3 python3-venv libreoffice ffmpeg nginx
sudo useradd --system --home /var/lib/wechat-converter --shell /usr/sbin/nologin converter
sudo mkdir -p /opt/wechat-converter-api /var/lib/wechat-converter
sudo chown -R converter:converter /opt/wechat-converter-api /var/lib/wechat-converter

cd /opt/wechat-converter-api/converter-api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

将 `wechat-converter.service` 复制到 `/etc/systemd/system/`，将 `wechat-converter.conf` 复制到 Nginx 配置目录，并根据实际域名、路径和安全策略调整后，再执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wechat-converter
sudo nginx -t
sudo systemctl reload nginx
```

## 安全与运维建议

- 生产环境不要直接使用默认的 `CORS_ALLOW_ORIGINS=*`，应限制为实际来源。
- 建议在 Nginx 或网关层配置 HTTPS、认证、访问频率限制和更严格的请求体大小限制。
- 转换服务会调用外部系统程序，生产环境应使用专用低权限用户运行，并限制临时目录权限。
- 大文件转换会占用 CPU、内存和磁盘空间，应结合机器规格调整并发数和超时时间。
- 建议通过 `/api/v1/health` 配置监控，并定期检查 systemd 和 Nginx 日志。

## 开发说明

当前仓库主要包含后端转换 API，尚未提供自动化测试套件。修改转换参数或部署配置后，建议至少使用 `/api/v1/test`、`/api/v1/health` 以及实际样例文件完成冒烟验证。

