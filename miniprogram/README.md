# WeChat Mini Program

This is the native Mini Program client for the converter API.

## Local setup

1. Open the repository root in WeChat DevTools. Its root `project.config.json` points the Mini Program root to this directory and keeps the configured AppID.
2. For development, `config.js` points to `http://8.136.99.105`. Enable “不校验合法域名、TLS 版本及证书” in WeChat DevTools. Before release, replace it with the API's HTTPS origin and turn URL checking back on.
3. Add the API host to the Mini Program `uploadFile` and `downloadFile` allowlists in the WeChat platform console. Add it to `request` if the client later calls JSON APIs with `wx.request`.

The API must support HTTPS with a valid certificate. The media/document conversion routes accept `response_mode=link`; the returned download URL expires after 15 minutes and is removed after download. Existing direct-file API clients remain compatible.

The client limits files to 10 MiB per upload to stay within the Mini Program's standard single-upload limit. Supporting larger files in the Mini Program requires a separate chunked-upload flow; the backend's 512 MiB limit does not remove the client-side limit.

The app currently supports document-to-PDF and media conversion. Login, payment, usage history, and server-side user quotas are not included.
