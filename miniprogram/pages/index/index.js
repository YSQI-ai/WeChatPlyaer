const { API_BASE_URL } = require('../../config');
const API_ORIGIN = API_BASE_URL.replace(/\/+$/, '');

const DOCUMENT_EXTENSIONS = ['doc', 'docx', 'odt', 'ott', 'rtf', 'txt'];
const MEDIA_FORMATS = ['mp3', 'wav', 'flac', 'ogg', 'opus', 'aac', 'm4a', 'mp4', 'webm', 'mkv', 'mov', 'avi'];
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const VIDEO_FORMATS = ['mp4', 'webm', 'mkv', 'mov', 'avi'];

function extensionOf(name = '') {
  const point = name.lastIndexOf('.');
  return point < 0 ? '' : name.slice(point + 1).toLowerCase();
}

function formatSize(bytes = 0) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function responseMessage(data, fallback) {
  try {
    const parsed = typeof data === 'string' ? JSON.parse(data) : data;
    return parsed.detail || parsed.message || fallback;
  } catch (_) {
    return fallback;
  }
}

Page({
  data: {
    mode: 'document',
    formats: MEDIA_FORMATS,
    targetIndex: 0,
    file: null,
    uploading: false,
    progress: 0,
    result: null,
    resultKind: '',
    resultTempPath: '',
    savedPath: '',
    apiConfigured: /^https?:\/\/[^/]+$/.test(API_ORIGIN) && !API_ORIGIN.includes('YOUR_API_DOMAIN')
  },

  chooseMode(event) {
    if (this.data.uploading) return;
    this.setData({ mode: event.currentTarget.dataset.mode, file: null, result: null, resultKind: '', resultTempPath: '', savedPath: '' });
  },

  chooseFile() {
    if (this.data.uploading) return;
    const options = { count: 1, type: 'file' };
    if (this.data.mode === 'document') options.extension = DOCUMENT_EXTENSIONS;

    wx.chooseMessageFile({
      ...options,
      success: ({ tempFiles }) => {
        const file = tempFiles[0];
        if (file.size > MAX_UPLOAD_BYTES) {
          wx.showToast({ title: '文件超过小程序单次上传限制（10 MB）', icon: 'none' });
          return;
        }
        if (this.data.mode === 'document' && !DOCUMENT_EXTENSIONS.includes(extensionOf(file.name))) {
          wx.showToast({ title: '暂不支持此文档格式', icon: 'none' });
          return;
        }
        this.setData({
          file: { ...file, sizeText: formatSize(file.size) },
          result: null,
          resultKind: '',
          resultTempPath: '',
          savedPath: ''
        });
      }
    });
  },

  clearFile() {
    if (!this.data.uploading) this.setData({ file: null, result: null, resultKind: '', resultTempPath: '', savedPath: '' });
  },

  changeFormat(event) {
    this.setData({ targetIndex: Number(event.detail.value), result: null, resultKind: '', resultTempPath: '', savedPath: '' });
  },

  startConversion() {
    if (!this.data.apiConfigured) {
      wx.showToast({ title: '请先配置 API 域名', icon: 'none' });
      return;
    }
    if (!this.data.file) {
      wx.showToast({ title: '请先选择文件', icon: 'none' });
      return;
    }
    if (this.data.uploading) return;

    const endpoint = this.data.mode === 'document'
      ? '/api/v1/convert/document-to-pdf'
      : '/api/v1/convert/media';
    const formData = { response_mode: 'link' };
    if (this.data.mode === 'media') formData.target_format = this.data.formats[this.data.targetIndex];

    this.setData({ uploading: true, progress: 0, result: null, resultKind: '', resultTempPath: '', savedPath: '' });
    const task = wx.uploadFile({
      url: `${API_ORIGIN}${endpoint}`,
      filePath: this.data.file.path,
      name: 'file',
      formData,
      success: (response) => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          wx.showToast({ title: responseMessage(response.data, '转换失败'), icon: 'none' });
          return;
        }
        try {
          const result = JSON.parse(response.data);
          if (!result.download_url || !result.filename) throw new Error('invalid response');
          const extension = extensionOf(result.filename);
          const resultKind = extension === 'pdf' ? 'pdf' : VIDEO_FORMATS.includes(extension) ? 'video' : 'audio';
          const expiresMinutes = Math.ceil(Number(result.expires_in || 900) / 60);
          this.setData({ result: { ...result, expiresText: `${expiresMinutes} 分钟` }, resultKind });
        } catch (_) {
          wx.showToast({ title: '服务返回格式异常', icon: 'none' });
        }
      },
      fail: (error) => {
        if (error.errMsg && !error.errMsg.includes('abort')) {
          wx.showToast({ title: '网络连接失败', icon: 'none' });
        }
      },
      complete: () => this.setData({ uploading: false, progress: 0 })
    });
    task.onProgressUpdate(({ progress }) => this.setData({ progress }));
    this.uploadTask = task;
  },

  cancelUpload() {
    if (this.uploadTask && this.data.uploading) this.uploadTask.abort();
  },

  downloadResult() {
    if (!this.data.result) return;
    wx.downloadFile({
      url: `${API_ORIGIN}${this.data.result.download_url}`,
      success: (response) => {
        if (response.statusCode !== 200) {
          wx.showToast({ title: '下载链接已失效，请重新转换', icon: 'none' });
          this.setData({ result: null });
          return;
        }
        this.setData({ resultTempPath: response.tempFilePath });
      },
      fail: () => wx.showToast({ title: '下载失败，请重试', icon: 'none' })
    });
  },

  openResult() {
    if (!this.data.resultTempPath) return;
    wx.openDocument({
      filePath: this.data.resultTempPath,
      showMenu: true,
      fail: () => wx.showToast({ title: '无法打开此文件', icon: 'none' })
    });
  },

  saveResult() {
    if (!this.data.resultTempPath) return;
    wx.saveFile({
      tempFilePath: this.data.resultTempPath,
      success: ({ savedFilePath }) => {
        this.setData({ savedPath: savedFilePath });
        wx.showToast({ title: '已保存到小程序文件', icon: 'success' });
      },
      fail: () => wx.showToast({ title: '保存失败', icon: 'none' })
    });
  }
});
