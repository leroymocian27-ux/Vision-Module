const $ = (id) => document.getElementById(id);
const OVERLAY_POSE_CACHE_TTL_MS = 120;
const OVERLAY_POSE_CACHE_MAX_CENTER_SHIFT_RATIO = 0.18;
const OVERLAY_BBOX_CACHE_TTL_MS = 1000;
const OVERLAY_BBOX_FADE_START_MS = 500;
const OVERLAY_BBOX_SMOOTHING_ALPHA = 0.42;
const APP_POSE_STALE_THRESHOLD_MS = 500;
const RESULT_OVERLAY_TTL_MS = 1500;
const EVENT_STATUS_REFRESH_MS = 5000;
const EVENT_LATEST_REFRESH_MS = 3000;
const EVENT_LATEST_DISABLED_REFRESH_MS = 15000;
const EVENT_RECENT_REFRESH_MS = 5000;
const SESSION_STATUS_REFRESH_MS = 1000;
const EVENT_TIMELINE_OFFSETS = [-3000, -1000, 0, 1000, 3000, 5000];
const FRAME_FALLBACK_REFRESH_MS = 300;
const FRAME_FALLBACK_RECENT_MS = 2500;
const FRAME_FALLBACK_STREAM_ERROR_RETRY_MS = 1500;
const VIDEO_PROGRESS_RECENT_MS = 2200;
const WEBRTC_MIN_ACCEPTABLE_FPS = 8;
const WEBRTC_FPS_RECENT_MS = 3000;
const DISPLAY_MJPEG_FALLBACK_ENABLED = true;
const DISPLAY_MJPEG_DEFAULT_FPS = 12;
const VIDEO_BLACK_LUMA_THRESHOLD = 8;
const ANNOTATED_OVERLAY_ENABLED = false;
const WEBRTC_DEFAULT_ICE_SERVERS = [];
const ALARM_INDICATOR_RESET_MS = 5000;
const ALARM_INDICATOR_MARGIN_PX = 22;
const JUDGMENT_RESET_QUIET_MS = 3000;
const ACKNOWLEDGED_FALL_EVENTS_KEY = "vision-dashboard-acknowledged-fall-events-v1";
const ACKNOWLEDGED_FALL_EVENTS_MAX = 30;
const ALARM_INDICATOR_TITLES = {
  idle: "等待事件",
  candidate: "疑似跌倒，等待复核",
  dismissed: "本次事件未触发最终告警",
  confirmed: "确认跌倒，已触发最终告警",
};
const DEMO_FALL_STAGE_MS = {
  analyzing: 500,
  suspected: 1500,
  reviewing: 2600,
  completed: 4600,
  description: 4850,
  json: 5150,
};

function loadAcknowledgedFallEventIds() {
  try {
    const values = JSON.parse(window.sessionStorage.getItem(ACKNOWLEDGED_FALL_EVENTS_KEY) || "[]");
    return new Set(Array.isArray(values) ? values.filter(Boolean).map(String) : []);
  } catch {
    return new Set();
  }
}

const state = {
  pc: null,
  peerId: null,
  ws: null,
  lastResult: null,
  lastStatus: null,
  lastControlStatus: null,
  lastSessionStatus: null,
  lastEvent: null,
  lastDashboardEvent: null,
  pendingResult: null,
  pendingIceCandidates: [],
  poseCache: new Map(),
  bboxCache: new Map(),
  lastTargetPoseCacheKey: null,
  connectSeq: 0,
  userConnected: false,
  autoFrontendConnectAttempted: false,
  connectedDisplaySource: null,
  lastDisplaySource: null,
  autoReconnect: {
    webrtcAttempts: 0,
    wsAttempts: 0,
    webrtcTimer: null,
    wsTimer: null,
    connecting: false,
  },
  videoFps: {
    lastAt: null,
    lastTotalFrames: null,
    lastDroppedFrames: null,
    lastMeasuredFps: null,
    lastMeasuredAt: null,
  },
  videoPaint: {
    canvas: null,
    lastSampleAt: null,
    lastBrightAt: null,
    lastLuma: null,
  },
  frameFallback: {
    timer: null,
    loading: false,
    visible: false,
    lastOkAt: null,
    lastErrorAt: null,
    lastUrl: null,
    naturalWidth: null,
    naturalHeight: null,
    lastVideoFrameAt: null,
    lastVideoFrameTotal: null,
  },
  videoFrameCallbackActive: false,
  overlayFallbackTimer: null,
  overlayFps: {
    lastAt: null,
    lastFrames: 0,
  },
  userEditedRtspUrl: false,
  lastPlayError: null,
  sessionHotkeyBusy: false,
  stagedControlHotkeyBusy: false,
  acknowledgedFallEventIds: loadAcknowledgedFallEventIds(),
  judgmentReset: {
    active: false,
    incidentIds: new Set(),
    resetAt: null,
    quietSince: null,
  },
  demoFall: {
    active: false,
    scenario: null,
    phase: "idle",
    incidentId: null,
    startedAt: null,
    presentation: null,
    revealDescription: false,
    revealJson: false,
    timers: [],
  },
  visualHistory: {
    lastAppendAt: 0,
    binaryProbability: [],
    videoFps: [],
    frameAge: [],
  },
  eventReview: {
    status: null,
    latestRefreshMs: EVENT_LATEST_REFRESH_MS,
    apiWarned: false,
    selectedIncidentId: null,
    recentItems: [],
  },
  alarmIndicator: {
    currentEventId: null,
    resetTimer: null,
    terminalStates: new Map(),
  },
};
window.__VISION_APP_STATE__ = state;

const debugState = window.__VISION_DEBUG__ || {
  overlayMode: ANNOTATED_OVERLAY_ENABLED ? (new URLSearchParams(window.location.search).get("overlayMode") || "full") : "off",
  showRawJson: new URLSearchParams(window.location.search).get("rawJson") === "1",
  videoSamples: [],
  rtcSamples: [],
  wsSamples: [],
  statusSamples: [],
  errors: [],
  longTasks: [],
  counters: {
    wsMessages: 0,
    statusUpdates: 0,
    rawJsonUpdates: 0,
    webrtcReconnects: 0,
    wsReconnects: 0,
    displayFallbackSwitches: 0,
    overlayFramesDrawn: 0,
  },
};
window.__VISION_DEBUG__ = debugState;

debugState.setOverlayMode = (mode) => {
  if (!ANNOTATED_OVERLAY_ENABLED) {
    debugState.overlayMode = "off";
    clearOverlayCanvas();
    return;
  }
  debugState.overlayMode = mode;
  if (mode === "off") {
    clearOverlayCanvas();
  } else if (state.lastResult && !isResultExpired(state.lastResult)) {
    drawOverlay($("video"), state.lastResult);
  }
};
debugState.setRawJson = (enabled) => {
  debugState.showRawJson = Boolean(enabled);
  const box = $("statusBox");
  if (box && !debugState.showRawJson) {
    box.textContent = "Raw JSON hidden for debug";
  }
};
debugState.reset = () => {
  debugState.videoSamples = [];
  debugState.rtcSamples = [];
  debugState.wsSamples = [];
  debugState.statusSamples = [];
  debugState.errors = [];
  debugState.longTasks = [];
  debugState.counters = {
    wsMessages: 0,
    statusUpdates: 0,
    rawJsonUpdates: 0,
    webrtcReconnects: 0,
    wsReconnects: 0,
    displayFallbackSwitches: 0,
    overlayFramesDrawn: 0,
  };
  state.overlayFps.lastAt = null;
  state.overlayFps.lastFrames = 0;
  state.videoFps.lastAt = null;
  state.videoFps.lastTotalFrames = null;
  state.videoFps.lastDroppedFrames = null;
  state.videoFps.lastMeasuredFps = null;
  state.videoFps.lastMeasuredAt = null;
  state.pendingResult = null;
  state.lastResult = null;
  state.poseCache.clear();
  state.bboxCache.clear();
  window.__VISION_OVERLAY_STATS__?.reset?.();
};
debugState.snapshot = () => ({
  overlayMode: debugState.overlayMode,
  showRawJson: debugState.showRawJson,
  counters: debugState.counters,
  video: summarizeVideo(debugState.videoSamples),
  rtc: summarizeRtc(debugState.rtcSamples),
  ws: summarizeSamples(debugState.wsSamples),
  status: summarizeSamples(debugState.statusSamples),
  overlay: window.__VISION_OVERLAY_STATS__?.snapshot?.() || null,
  latestVideo: debugState.videoSamples.at(-1) || null,
  latestRtc: debugState.rtcSamples.at(-1) || null,
  errors: debugState.errors.slice(-50),
  longTasks: debugState.longTasks.slice(-50),
  dom: readFreezeDomSnapshot(),
});

const FALL_STATE_LABELS = {
  normal: "正常",
  candidate: "疑似跌倒",
  confirmed: "已确认跌倒",
  unstable: "姿态异常",
  falling: "疑似跌倒",
  fallen_candidate: "高风险倒地",
  fallen_confirmed: "倒地确认",
  cooldown: "冷却观察",
};

const RISK_LEVEL_LABELS = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  critical: "紧急风险",
  cooldown: "观察中",
};

const BEHAVIOR_LABELS = {
  standing: "站立",
  walking: "行走",
  sitting: "坐下",
  bending: "弯腰",
  lying: "躺卧",
  unknown: "未知",
};

const IDENTITY_STATE_LABELS = {
  unbound: "未绑定",
  identifying: "识别中",
  recognized: "已识别",
};

const TRACKING_STATE_LABELS = {
  idle: "空闲",
  target_locked: "已锁定",
  target_lost: "目标丢失",
  target_reacquiring: "重新寻找",
};

function apiBase() {
  if (window.location.protocol === "file:") {
    return "http://127.0.0.1:8000";
  }
  return window.location.origin;
}

function wsBase() {
  if (window.location.protocol === "file:") {
    return "ws://127.0.0.1:8000";
  }
  return `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;
}

function webrtcIceServers() {
  const stun = new URLSearchParams(window.location.search).get("stun");
  if (stun && stun.trim()) {
    return [{ urls: stun.trim() }];
  }
  return WEBRTC_DEFAULT_ICE_SERVERS;
}

function latestFrameUrl(cameraId) {
  return `${apiBase()}/stream/latest-frame.jpg?camera_id=${encodeURIComponent(cameraId)}&display=1&t=${Date.now()}`;
}

function displayStreamUrl(cameraId) {
  const fps = displayMjpegTargetFps();
  return `${apiBase()}/stream/display.mjpg?camera_id=${encodeURIComponent(cameraId)}&fps=${encodeURIComponent(fps)}&t=${Date.now()}`;
}

function displayMjpegTargetFps(status = state.lastStatus) {
  const configured = Number(status?.configuration?.effective_config?.display_mjpeg_fps);
  if (Number.isFinite(configured) && configured > 0) {
    return Math.max(1, Math.min(30, configured));
  }
  return DISPLAY_MJPEG_DEFAULT_FPS;
}

function preloadFrameFallback(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({
      width: image.naturalWidth || image.width,
      height: image.naturalHeight || image.height,
    });
    image.onerror = reject;
    image.src = url;
  });
}

function getStatusCamera(status, cameraId = currentCameraId()) {
  return (status?.cameras || []).find((item) => item.camera_id === cameraId)
    || (status?.camera_id === cameraId ? status : null)
    || null;
}

function isBackendFrameFresh(status, cameraId = currentCameraId()) {
  const camera = getStatusCamera(status, cameraId);
  const frameAgeMs = Number(camera?.frame_age_ms ?? status?.frame_age_ms ?? status?.main_frame_age_ms);
  return camera?.frame_status === "fresh"
    || status?.frame_status === "fresh"
    || (Number.isFinite(frameAgeMs) && frameAgeMs <= FRAME_FALLBACK_RECENT_MS);
}

function isStreamHealthy(stream) {
  if (!stream) {
    return false;
  }
  return stream.stream_state === "connected"
    || stream.stream_state === "streaming"
    || stream.frame_status === "fresh"
    || (stream.connected === true && stream.is_stale !== true);
}

function backendHasDisplayFrame(status, cameraId = currentCameraId()) {
  const camera = getStatusCamera(status, cameraId);
  return Boolean(
    camera?.raw_jpeg_available
    || status?.main_stream?.raw_jpeg_available
    || status?.analysis_stream?.raw_jpeg_available
    || Number.isFinite(Number(camera?.frame_seq))
  );
}

function shouldPreferMjpegDisplay(status = state.lastStatus, cameraId = currentCameraId()) {
  if (!DISPLAY_MJPEG_FALLBACK_ENABLED || !status) {
    return false;
  }
  const camera = getStatusCamera(status, cameraId);
  const protocol = camera?.source_protocol
    || status?.main_stream?.source_protocol
    || status?.analysis_stream?.source_protocol
    || camera?.source;
  return String(protocol || "").toLowerCase() === "mjpeg";
}

function shouldPollFrameFallback(status = state.lastStatus) {
  const hasViewerConnectionIntent = Boolean(
    state.userConnected
    || state.autoReconnect.connecting
    || state.pc
  );
  const backendCanServeFrame = Boolean(status && (isBackendFrameFresh(status) || backendHasDisplayFrame(status)));
  return (hasViewerConnectionIntent || backendCanServeFrame || shouldPreferMjpegDisplay(status))
    && (state.pc?.connectionState !== "connected" || !isVideoVisiblyHealthy());
}

function syncFrameFallbackLoop(status = state.lastStatus) {
  if (shouldPollFrameFallback(status)) {
    startFrameFallbackLoop();
  } else {
    stopFrameFallbackLoop();
  }
}

function startFrameFallbackLoop() {
  if (state.frameFallback.timer) {
    return;
  }
  state.frameFallback.timer = setInterval(refreshFrameFallback, FRAME_FALLBACK_REFRESH_MS);
  void refreshFrameFallback();
}

function stopFrameFallbackLoop() {
  if (!state.frameFallback.timer) {
    return;
  }
  clearInterval(state.frameFallback.timer);
  state.frameFallback.timer = null;
}

async function refreshFrameFallback() {
  const image = $("frameFallback");
  if (!image || state.frameFallback.loading) {
    updateFrameFallbackVisibility();
    return;
  }
  if (!shouldPollFrameFallback()) {
    setFrameFallbackVisible(false);
    stopFrameFallbackStream();
    stopFrameFallbackLoop();
    return;
  }
  if (DISPLAY_MJPEG_FALLBACK_ENABLED) {
    startFrameFallbackStream();
    if (image.naturalWidth && image.naturalHeight) {
      state.frameFallback.lastOkAt = Date.now();
      state.frameFallback.naturalWidth = image.naturalWidth;
      state.frameFallback.naturalHeight = image.naturalHeight;
    }
    updateFrameFallbackVisibility();
    return;
  }
  const cameraId = currentCameraId();
  state.frameFallback.loading = true;
  try {
    const url = latestFrameUrl(cameraId);
    const info = await preloadFrameFallback(url);
    if (currentCameraId() !== cameraId) {
      return;
    }
    image.src = url;
    state.frameFallback.cameraId = cameraId;
    state.frameFallback.lastOkAt = Date.now();
    state.frameFallback.lastUrl = url;
    state.frameFallback.naturalWidth = info.width;
    state.frameFallback.naturalHeight = info.height;
  } catch (error) {
    state.frameFallback.lastErrorAt = Date.now();
    pushDebugError("frameFallback", error);
  } finally {
    state.frameFallback.loading = false;
    updateFrameFallbackVisibility();
  }
}

function startFrameFallbackStream() {
  const image = $("frameFallback");
  if (!image) {
    return;
  }
  const now = Date.now();
  if (
    state.frameFallback.lastErrorAt
    && now - state.frameFallback.lastErrorAt < FRAME_FALLBACK_STREAM_ERROR_RETRY_MS
  ) {
    return;
  }
  const cameraId = currentCameraId();
  if (state.frameFallback.cameraId === cameraId && state.frameFallback.lastUrl?.includes("/stream/display.mjpg")) {
    return;
  }
  const url = displayStreamUrl(cameraId);
  image.onload = () => {
    state.frameFallback.lastOkAt = Date.now();
    state.frameFallback.naturalWidth = image.naturalWidth || image.width;
    state.frameFallback.naturalHeight = image.naturalHeight || image.height;
    updateFrameFallbackVisibility();
  };
  image.onerror = (error) => {
    state.frameFallback.lastErrorAt = Date.now();
    state.frameFallback.lastUrl = null;
    pushDebugError("frameFallbackStream", error);
  };
  image.src = url;
  state.frameFallback.cameraId = cameraId;
  state.frameFallback.lastUrl = url;
}

function stopFrameFallbackStream() {
  const image = $("frameFallback");
  if (!image || !state.frameFallback.lastUrl?.includes("/stream/display.mjpg")) {
    return;
  }
  image.removeAttribute("src");
  state.frameFallback.lastUrl = null;
}

function setFrameFallbackVisible(visible) {
  const image = $("frameFallback");
  if (!image) {
    return;
  }
  state.frameFallback.visible = Boolean(visible);
  image.hidden = !visible;
  image.classList.toggle("is-visible", Boolean(visible));
}

function sampleVideoPaint(video) {
  if (!video || video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
    return;
  }
  const now = Date.now();
  if (state.videoPaint.lastSampleAt && now - state.videoPaint.lastSampleAt < 900) {
    return;
  }
  state.videoPaint.lastSampleAt = now;
  try {
    const canvas = state.videoPaint.canvas || document.createElement("canvas");
    canvas.width = 16;
    canvas.height = 16;
    state.videoPaint.canvas = canvas;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let totalLuma = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      totalLuma += 0.2126 * pixels[index] + 0.7152 * pixels[index + 1] + 0.0722 * pixels[index + 2];
    }
    const luma = totalLuma / (pixels.length / 4);
    state.videoPaint.lastLuma = luma;
    if (luma >= VIDEO_BLACK_LUMA_THRESHOLD) {
      state.videoPaint.lastBrightAt = now;
    }
  } catch (error) {
    state.videoPaint.lastLuma = null;
    pushDebugError("videoPaint", error);
  }
}

function noteVideoProgress(quality) {
  const totalFrames = Number(quality?.totalVideoFrames);
  if (!Number.isFinite(totalFrames)) {
    return;
  }
  const fallback = state.frameFallback;
  if (fallback.lastVideoFrameTotal == null || totalFrames > fallback.lastVideoFrameTotal) {
    fallback.lastVideoFrameAt = Date.now();
  }
  fallback.lastVideoFrameTotal = totalFrames;
}

function isVideoVisiblyHealthy() {
  const video = $("video");
  if (!video || !video.srcObject || video.readyState < 2 || video.paused || !video.videoWidth || !video.videoHeight) {
    return false;
  }
  const now = Date.now();
  const totalFrames = Number(state.frameFallback.lastVideoFrameTotal);
  const hasProgress = !Number.isFinite(totalFrames)
    || totalFrames > 0 && (
      !state.frameFallback.lastVideoFrameAt
      || now - state.frameFallback.lastVideoFrameAt <= VIDEO_PROGRESS_RECENT_MS
    );
  const luma = Number(state.videoPaint.lastLuma);
  const paintLooksLive = !Number.isFinite(luma)
    || luma >= VIDEO_BLACK_LUMA_THRESHOLD
    || Boolean(state.videoPaint.lastBrightAt && now - state.videoPaint.lastBrightAt <= VIDEO_PROGRESS_RECENT_MS);
  return hasProgress && paintLooksLive && isWebRtcFpsHealthy();
}

function isWebRtcFpsHealthy() {
  if (state.pc?.connectionState !== "connected") {
    return false;
  }
  const now = Date.now();
  const measuredAt = Number(state.videoFps.lastMeasuredAt);
  if (!Number.isFinite(measuredAt) || now - measuredAt > WEBRTC_FPS_RECENT_MS) {
    return true;
  }
  const fps = Number(state.videoFps.lastMeasuredFps);
  return Number.isFinite(fps) && fps >= WEBRTC_MIN_ACCEPTABLE_FPS;
}

function updateFrameFallbackVisibility(status = state.lastStatus) {
  const image = $("frameFallback");
  if (!image) {
    return;
  }
  const now = Date.now();
  const hasRecentFallbackFrame = Boolean(
    state.frameFallback.lastOkAt
    && now - state.frameFallback.lastOkAt <= FRAME_FALLBACK_RECENT_MS
  );
  const hasLoadedFallbackFrame = Boolean(
    (image.complete || state.frameFallback.lastUrl?.includes("/stream/display.mjpg"))
    && image.naturalWidth > 0
    && image.naturalHeight > 0
    && (state.frameFallback.lastOkAt || state.frameFallback.lastUrl || image.currentSrc || image.src)
  );
  const backendCanShowLiveFrame = !status || isBackendFrameFresh(status);
  const videoHealthy = isVideoVisiblyHealthy();
  const webrtcConnected = state.pc?.connectionState === "connected";
  const shouldShowFallback = (hasRecentFallbackFrame || hasLoadedFallbackFrame) && backendCanShowLiveFrame && (!videoHealthy || !webrtcConnected);
  setFrameFallbackVisible(shouldShowFallback);
  const empty = document.querySelector(".viewer-empty");
  if (empty) {
    empty.hidden = shouldShowFallback || videoHealthy;
  }
  syncFrameFallbackLoop(status);
}

function maybeAutoConnectFrontend(status = state.lastStatus) {
  if (
    state.autoFrontendConnectAttempted
    || state.userConnected
    || state.autoReconnect.connecting
    || state.pc
    || new URLSearchParams(window.location.search).get("manualConnect") === "1"
  ) {
    return;
  }
  if (!isBackendFrameFresh(status)) {
    return;
  }
  if (shouldPreferMjpegDisplay(status)) {
    state.autoFrontendConnectAttempted = true;
    syncFrameFallbackLoop(status);
    updateFrameFallbackVisibility(status);
    return;
  }
  state.autoFrontendConnectAttempted = true;
  setTimeout(() => {
    if (!state.userConnected && !state.pc) {
      void connectWebRTC();
    }
  }, 250);
}

const DEFAULT_MANUAL_ALERT_IP = "192.168.8.253";
const LEGACY_MANUAL_ALERT_IPS = new Set(["172.18.33.66", "192.168.8.254"]);
const MANUAL_ALERT_IP_STORAGE_KEY = "vision.manualAlertTargetIp";
const MAIN_SYSTEM_BASE_URL_STORAGE_KEY = "vision.mainSystemBaseUrl";
const MAIN_SYSTEM_ALERT_PATH = "/api/integrations/fall-detection/alerts";

function initializeManualAlertControls() {
  const input = $("manualAlertIp");
  const button = $("sendManualAlertBtn");
  if (!input || !button) {
    return;
  }
  const savedIp = window.localStorage?.getItem(MANUAL_ALERT_IP_STORAGE_KEY);
  if (savedIp && !LEGACY_MANUAL_ALERT_IPS.has(savedIp)) {
    input.value = savedIp;
  } else {
    input.value = DEFAULT_MANUAL_ALERT_IP;
    window.localStorage?.setItem(MANUAL_ALERT_IP_STORAGE_KEY, DEFAULT_MANUAL_ALERT_IP);
  }
  button.addEventListener("click", sendManualAlert);
  initializeMainSystemUrlControls();
}

function initializeMainSystemUrlControls() {
  const input = $("mainSystemBaseUrl");
  const saveButton = $("saveMainSystemUrlBtn");
  const healthButton = $("testMainSystemHealthBtn");
  if (!input) {
    return;
  }
  const savedUrl = window.localStorage?.getItem(MAIN_SYSTEM_BASE_URL_STORAGE_KEY);
  if (savedUrl) {
    input.value = savedUrl;
  }
  saveButton?.addEventListener("click", saveMainSystemUrl);
  healthButton?.addEventListener("click", testMainSystemHealth);
}

async function saveMainSystemUrl() {
  const input = $("mainSystemBaseUrl");
  const baseUrl = normalizeHttpBaseUrl(input?.value || "");
  if (!baseUrl) {
    setDiscoveryResult("失败：请输入 http://主系统IPv4:8000", "error");
    input?.focus();
    return false;
  }
  try {
    const response = await fetch(`${apiBase()}/alerting/endpoint`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: baseUrl, path: MAIN_SYSTEM_ALERT_PATH, enabled: true }),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    window.localStorage?.setItem(MAIN_SYSTEM_BASE_URL_STORAGE_KEY, baseUrl);
    setDiscoveryResult(`已保存：${baseUrl}`, "success");
    await refreshDeviceDiscoveryStatus();
    return true;
  } catch (error) {
    setDiscoveryResult(`保存失败：${error}`, "error");
    return false;
  }
}

async function testMainSystemHealth() {
  const saved = await saveMainSystemUrl();
  if (!saved) {
    return;
  }
  try {
    const response = await fetch(`${apiBase()}/alerting/main-system/health`);
    const payload = await safeJson(response);
    if (response.ok && payload?.ok) {
      setDiscoveryResult(`连接成功：${payload.url}`, "success");
      $("statusBox").textContent = JSON.stringify(payload, null, 2);
      return;
    }
    setDiscoveryResult(`连接失败：${payload?.error || payload?.status_code || response.status}`, "error");
    $("statusBox").textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    setDiscoveryResult(`连接失败：${error}`, "error");
  }
}

function normalizeHttpBaseUrl(value) {
  const text = String(value || "").trim().replace(/\/+$/, "");
  if (!/^https?:\/\/[^/\s]+(?::\d+)?$/.test(text)) {
    return "";
  }
  return text;
}

async function sendManualAlert() {
  const input = $("manualAlertIp");
  const button = $("sendManualAlertBtn");
  const targetIp = input?.value.trim() || "";
  if (!isLikelyIpv4(targetIp)) {
    setManualAlertResult("失败：请输入合法的 IPv4 地址，例如 192.168.8.253", "error");
    input?.focus();
    return;
  }
  if (button) {
    button.disabled = true;
  }
  setManualAlertResult(`发送中：${targetIp}`, "pending");
  try {
    const response = await fetch(`${apiBase()}/alerting/simulation/send-once`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_ip: targetIp,
        camera_id: $("cameraId")?.value.trim() || "camera_01",
        track_id: "manual-console-probe",
        fall_prob: 0.91,
      }),
    });
    const payload = await safeJson(response);
    if (response.ok && payload?.ok) {
      window.localStorage?.setItem(MANUAL_ALERT_IP_STORAGE_KEY, targetIp);
      const remoteBody = summarizeRemoteBody(payload.response_body);
      setManualAlertResult(
        `成功：HTTP ${payload.status_code}；${remoteBody}；发送时间 ${payload.sent_at}`,
        "success",
      );
      $("statusBox").textContent = JSON.stringify(payload, null, 2);
      return;
    }
    const message = payload?.error || payload?.response_body || payload?.detail || `HTTP ${response.status}`;
    setManualAlertResult(`失败：${message}`, "error");
    $("statusBox").textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    setManualAlertResult(`失败：${error}`, "error");
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}

function isLikelyIpv4(value) {
  const parts = value.split(".");
  return parts.length === 4 && parts.every((part) => {
    if (!/^\d{1,3}$/.test(part)) {
      return false;
    }
    const numeric = Number(part);
    return numeric >= 0 && numeric <= 255;
  });
}

function setManualAlertResult(message, kind) {
  const result = $("manualAlertResult");
  if (!result) {
    return;
  }
  result.textContent = message;
  result.dataset.state = kind;
}

function setDiscoveryResult(message, kind) {
  const result = $("discoveryResult");
  if (!result) {
    return;
  }
  result.textContent = message;
  result.dataset.state = kind;
}

function summarizeRemoteBody(body) {
  if (!body) {
    return "远端无响应正文";
  }
  try {
    const parsed = JSON.parse(body);
    const flags = [];
    if (parsed.accepted !== undefined) {
      flags.push(`accepted=${parsed.accepted}`);
    }
    if (parsed.pushed !== undefined) {
      flags.push(`pushed=${parsed.pushed}`);
    }
    if (parsed.alarm_id) {
      flags.push(`alarm_id=${parsed.alarm_id}`);
    }
    return flags.length ? flags.join(" / ") : JSON.stringify(parsed).slice(0, 160);
  } catch (_) {
    return body.slice(0, 160);
  }
}

async function startStream() {
  return startStreamRequest({ updateUi: true });
}

async function startStreamRequest({ updateUi }) {
  const cameraId = $("cameraId").value.trim() || "camera_01";
  const sourceUrl = $("rtspUrl").value.trim() || null;
  const startBtn = $("startBtn");
  if (startBtn) {
    startBtn.disabled = true;
  }

  try {
    const response = await fetch(`${apiBase()}/stream/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        camera_id: cameraId,
        source_url: sourceUrl,
        rtsp_url: sourceUrl,
        main_rtsp_url: sourceUrl,
        analysis_rtsp_url: sourceUrl,
      }),
    });
    const payload = await safeJson(response);
    if (updateUi) {
      $("statusBox").textContent = JSON.stringify(payload, null, 2);
    }
    if (!response.ok) {
      throw new Error(payload?.detail || payload?.message || `stream start failed: ${response.status}`);
    }
    state.userEditedRtspUrl = false;
    await refreshStatus();
    await refreshControlStatus(cameraId);
    return payload;
  } catch (error) {
    if (updateUi) {
      $("statusBox").textContent = String(error);
    }
    throw error;
  } finally {
    if (startBtn) {
      startBtn.disabled = false;
    }
  }
}

async function connectWebRTC() {
  const cameraId = $("cameraId").value.trim() || "camera_01";
  state.userConnected = true;
  state.autoReconnect.connecting = true;
  clearReconnectTimer("webrtc");
  const connectSeq = ++state.connectSeq;
  closeConnections();
  stopOverlayLoop();
  $("connectBtn").disabled = true;
  setText("webrtcState", "connecting");
  updatePeerDebugState();
  setText("wsState", "idle");
  updateRecoveryBanner();

  try {
    await startStreamRequest({ updateUi: false });
  } catch (error) {
    setText("webrtcState", "failed");
    $("statusBox").textContent = `stream start failed before WebRTC: ${error}`;
    state.autoReconnect.connecting = false;
    $("connectBtn").disabled = false;
    return;
  }

  const pc = new RTCPeerConnection({ iceServers: webrtcIceServers() });
  state.pc = pc;
  state.peerId = null;
  state.pendingIceCandidates = [];
  updatePeerDebugState();

  pc.addTransceiver("video", { direction: "recvonly" });
  pc.onicecandidate = (event) => {
    if (state.pc !== pc || !event.candidate) {
      return;
    }
    const payload = {
      candidate: event.candidate.candidate,
      sdpMid: event.candidate.sdpMid,
      sdpMLineIndex: event.candidate.sdpMLineIndex,
    };
    if (!state.peerId) {
      state.pendingIceCandidates.push(payload);
      return;
    }
    void sendIceCandidate(state.peerId, payload);
  };
  pc.ontrack = (event) => {
    const video = $("video");
    const stream = event.streams?.[0] || new MediaStream([event.track]);
    video.srcObject = stream;
    state.lastPlayError = null;
    updateFrameFallbackVisibility();
    updatePeerDebugState();
    void video.play().then(() => {
      state.lastPlayError = null;
      updateFrameFallbackVisibility();
      updatePeerDebugState();
    }).catch((error) => {
      state.lastPlayError = String(error);
      $("statusBox").textContent = `video.play failed: ${error}`;
      updateFrameFallbackVisibility();
      updatePeerDebugState();
    });
    attachVideoFrameLoop();
  };
  pc.onconnectionstatechange = () => {
    if (state.pc === pc) {
      setText("webrtcState", pc.connectionState);
      updatePeerDebugState();
      updateRecoveryBanner();
      updateFrameFallbackVisibility();
      if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
        scheduleWebRTCReconnect(`webrtc ${pc.connectionState}`);
      } else if (pc.connectionState === "connected") {
        state.autoReconnect.webrtcAttempts = 0;
        state.connectedDisplaySource = state.lastDisplaySource
          || state.lastStatus?.display_source_current
          || state.lastStatus?.display_source
          || state.connectedDisplaySource;
        updateRecoveryBanner();
        updateFrameFallbackVisibility();
      }
    }
  };
  pc.oniceconnectionstatechange = () => {
    if (state.pc === pc) {
      updatePeerDebugState();
    }
  };
  pc.onsignalingstatechange = () => {
    if (state.pc === pc) {
      updatePeerDebugState();
    }
  };
  pc.onicegatheringstatechange = () => {
    if (state.pc === pc) {
      updatePeerDebugState();
    }
  };

  try {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    updatePeerDebugState();

    if (!isCurrentPeer(pc, connectSeq)) {
      return;
    }

    const response = await fetch(`${apiBase()}/webrtc/offer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        camera_id: cameraId,
        sdp: pc.localDescription.sdp,
        type: pc.localDescription.type,
        prefer_latest_frame: true,
        preferred_display_source: "analysis",
      }),
    });
    const answer = await safeJson(response);
    if (!response.ok) {
      throw new Error(answer?.detail || answer?.message || `webrtc offer failed: ${response.status}`);
    }

    if (!isCurrentPeer(pc, connectSeq)) {
      return;
    }
    state.peerId = answer.peer_id;
    await pc.setRemoteDescription(answer);
    flushPendingIceCandidates();
    updatePeerDebugState();
    connectResults(cameraId);
  } catch (error) {
    if (state.pc === pc) {
      setText("webrtcState", "failed");
      $("statusBox").textContent = String(error);
      updatePeerDebugState();
      closeConnections();
      state.autoReconnect.connecting = false;
      scheduleWebRTCReconnect("webrtc offer failed");
    }
  } finally {
    state.autoReconnect.connecting = false;
    $("connectBtn").disabled = false;
    updateRecoveryBanner();
  }
}

function isCurrentPeer(pc, connectSeq) {
  return state.pc === pc && state.connectSeq === connectSeq && pc.signalingState !== "closed";
}

function closeConnections() {
  clearReconnectTimer("webrtc");
  clearReconnectTimer("ws");
  stopOverlayLoop();
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }
  if (state.pc) {
    state.pc.close();
    state.pc = null;
  }
  state.peerId = null;
  state.pendingIceCandidates = [];
  state.connectedDisplaySource = null;
  state.videoFps.lastAt = null;
  state.videoFps.lastTotalFrames = null;
  state.videoFps.lastDroppedFrames = null;
  state.videoFps.lastMeasuredFps = null;
  state.videoFps.lastMeasuredAt = null;
  updateFrameFallbackVisibility();
  updatePeerDebugState();
}

async function sendIceCandidate(peerId, candidate) {
  const response = await fetch(`${apiBase()}/webrtc/candidate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      peer_id: peerId,
      candidate,
    }),
  });
  if (!response.ok) {
    const payload = await safeJson(response);
    throw new Error(payload?.detail || payload?.message || `webrtc candidate failed: ${response.status}`);
  }
}

function flushPendingIceCandidates() {
  if (!state.peerId || !state.pendingIceCandidates.length) {
    return;
  }
  const pending = state.pendingIceCandidates.splice(0, state.pendingIceCandidates.length);
  for (const candidate of pending) {
    void sendIceCandidate(state.peerId, candidate).catch((error) => {
      $("statusBox").textContent = `webrtc candidate failed: ${error}`;
    });
  }
}

function waitForIceGatheringComplete(pc) {
  if (pc.iceGatheringState === "complete") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, 3000);
    const check = () => {
      if (pc.iceGatheringState === "complete") {
        clearTimeout(timer);
        pc.removeEventListener("icegatheringstatechange", check);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", check);
  });
}

function connectResults(cameraId) {
  clearReconnectTimer("ws");
  if (state.ws) {
    state.ws.close();
  }
  const ws = new WebSocket(`${wsBase()}/ws/results?camera_id=${encodeURIComponent(cameraId)}`);
  state.ws = ws;
  ws.onopen = () => {
    setText("wsState", "connected");
    state.autoReconnect.wsAttempts = 0;
    updateRecoveryBanner();
  };
  ws.onclose = () => {
    if (state.ws === ws) {
      setText("wsState", "closed");
      scheduleWebSocketReconnect("websocket closed");
    }
  };
  ws.onerror = () => {
    if (state.ws === ws) {
      setText("wsState", "error");
      scheduleWebSocketReconnect("websocket error");
    }
  };
  ws.onmessage = (event) => {
    const startedAt = performance.now();
    const result = JSON.parse(event.data);
    const composedResult = composeOverlayResult(result);
    composedResult.overlay_received_at = Date.now();
    state.lastResult = composedResult;
    state.pendingResult = ANNOTATED_OVERLAY_ENABLED ? composedResult : null;
    if (!ANNOTATED_OVERLAY_ENABLED) {
      clearOverlayCanvas();
    }
    $("frameInfo").textContent = `${result.frame_width}x${result.frame_height} #${result.frame_seq}`;
    $("personCount").textContent = `${(result.objects || []).length}`;
    $("latency").textContent = `${result.detector?.latency_ms ?? "-"} ms`;
    updateTargetDetails(composedResult);
    updateAlarmIndicatorFromResult(composedResult);
    renderDashboard();
    debugState.counters.wsMessages += 1;
    pushLimited(debugState.wsSamples, {
      at: Date.now(),
      elapsedMs: performance.now() - startedAt,
      objects: (result.objects || []).length,
      frameSeq: result.frame_seq,
    });
    updateWsFps();
  };
}

function composeOverlayResult(result) {
  const now = Date.now();
  const cameraId = String(result?.camera_id || "");
  const activeTrackIds = new Set();
  const activeBboxTrackIds = new Set();
  const objects = (result.objects || []).map((object) => {
    const trackKey = poseCacheKey(cameraId, object);
    if (trackKey) {
      activeTrackIds.add(trackKey);
      activeBboxTrackIds.add(trackKey);
    }
    const bboxPatch = buildOverlayBboxPatch(cameraId, object, now);

    const pose = object.pose;
    if (isPoseDisabledPlaceholder(pose)) {
      if (trackKey) {
        clearPoseArtifacts(trackKey, object);
      }
      return {
        ...object,
        ...bboxPatch,
        pose,
        overlay_camera_id: cameraId,
        overlay_frame_seq: result.frame_seq,
        overlay_pose_cached: false,
        overlay_pose_age_ms: null,
        overlay_pose_expired: false,
        overlay_pose_stale: false,
        overlay_pose_waiting: false,
        overlay_pose_disabled: true,
        overlay_pose_rejected: false,
        overlay_pose_rejected_reason: null,
      };
    }
    const poseRejectedReason = validatePoseForObject(result, object, pose);
    const poseRejected = Boolean(poseRejectedReason || pose?.debug?.rejected_reason);
    const poseAgeMs = poseAgeFromObject(object);
    const poseStale = isPoseMarkedStale(object);
    if (trackKey && (poseRejected || poseStale)) {
      clearPoseArtifacts(trackKey, object);
      return {
        ...object,
        ...bboxPatch,
        pose: null,
        overlay_camera_id: cameraId,
        overlay_frame_seq: result.frame_seq,
        overlay_pose_cached: false,
        overlay_pose_age_ms: poseAgeMs,
        overlay_pose_expired: true,
        overlay_pose_stale: poseStale,
        overlay_pose_waiting: false,
        overlay_pose_rejected: true,
        overlay_pose_rejected_reason: poseRejectedReason || pose?.debug?.rejected_reason || "pose_stale",
      };
    }
    if (trackKey && hasPoseKeypoints(pose)) {
      state.poseCache.set(trackKey, {
        pose,
        bbox: object.bbox,
        poseBounds: computePoseBoundsFromPose(pose),
        updatedAt: now,
        frameSeq: result.frame_seq,
      });
      return {
        ...object,
        ...bboxPatch,
        pose,
        overlay_camera_id: cameraId,
        overlay_frame_seq: result.frame_seq,
        overlay_pose_cached: false,
        overlay_pose_age_ms: poseAgeMs,
        overlay_pose_expired: false,
        overlay_pose_stale: false,
        overlay_pose_waiting: false,
      };
    }

    const cached = trackKey ? state.poseCache.get(trackKey) : null;
    if (trackKey && cached) {
      clearPoseArtifacts(trackKey, object);
    }
    return {
      ...object,
      ...bboxPatch,
      pose: null,
      overlay_camera_id: cameraId,
      overlay_frame_seq: result.frame_seq,
      overlay_pose_cached: false,
      overlay_pose_age_ms: cached ? Math.round(now - cached.updatedAt) : null,
      overlay_pose_expired: Boolean(cached),
      overlay_pose_stale: false,
      overlay_pose_waiting: true,
    };
  });

  const targetObject = objects.find((object) => object?.is_target === true) || null;
  const targetTrackKey = targetObject ? poseCacheKey(cameraId, targetObject) : null;
  if (state.lastTargetPoseCacheKey && state.lastTargetPoseCacheKey !== targetTrackKey) {
    clearPoseArtifacts(state.lastTargetPoseCacheKey);
  }
  state.lastTargetPoseCacheKey = targetTrackKey;

  for (const [trackKey, cached] of state.poseCache.entries()) {
    if (!activeTrackIds.has(trackKey) || now - cached.updatedAt > OVERLAY_POSE_CACHE_TTL_MS) {
      clearPoseArtifacts(trackKey);
    }
  }
  for (const [trackKey, cached] of state.bboxCache.entries()) {
    if (!activeBboxTrackIds.has(trackKey) || now - cached.updatedAt > OVERLAY_BBOX_CACHE_TTL_MS) {
      state.bboxCache.delete(trackKey);
    }
  }

  return {
    ...result,
    objects,
    overlay_debug: {
      pose_cache_size: state.poseCache.size,
      pose_cache_ttl_ms: OVERLAY_POSE_CACHE_TTL_MS,
      bbox_cache_size: state.bboxCache.size,
      bbox_cache_ttl_ms: OVERLAY_BBOX_CACHE_TTL_MS,
    },
  };
}

function buildOverlayBboxPatch(cameraId, object, now) {
  const bbox = normalizeBbox(object?.bbox);
  const trackKey = poseCacheKey(cameraId, object);
  if (!bbox || !trackKey) {
    return {
      overlay_bbox: bbox || object?.bbox || null,
      overlay_bbox_age_ms: null,
      overlay_bbox_stale: false,
      overlay_bbox_alpha: 1,
    };
  }

  const cached = state.bboxCache.get(trackKey);
  const stale = object?.fusion_debug?.tracking_stale === true;
  let smoothed = bbox;
  if (cached?.bbox && !stale) {
    smoothed = smoothBbox(cached.bbox, bbox, OVERLAY_BBOX_SMOOTHING_ALPHA);
  }
  state.bboxCache.set(trackKey, {
    bbox: smoothed,
    updatedAt: now,
    frameSeq: object?.overlay_frame_seq ?? null,
  });
  const rawAge = Number(object?.fusion_debug?.tracking_age_ms);
  const ageMs = Number.isFinite(rawAge) ? Math.max(0, Math.round(rawAge)) : 0;
  const fadeSpan = Math.max(1, OVERLAY_BBOX_CACHE_TTL_MS - OVERLAY_BBOX_FADE_START_MS);
  const alpha = ageMs <= OVERLAY_BBOX_FADE_START_MS
    ? 1
    : Math.max(0.18, 1 - ((ageMs - OVERLAY_BBOX_FADE_START_MS) / fadeSpan));
  return {
    overlay_bbox: smoothed,
    overlay_bbox_age_ms: ageMs,
    overlay_bbox_stale: stale,
    overlay_bbox_alpha: Number(alpha.toFixed(3)),
  };
}

function normalizeBbox(bbox) {
  if (!Array.isArray(bbox) || bbox.length < 4) {
    return null;
  }
  const values = bbox.slice(0, 4).map(Number);
  return values.every(Number.isFinite) ? values : null;
}

function smoothBbox(previous, current, alpha) {
  return current.map((value, index) => {
    const prior = Number(previous[index]);
    if (!Number.isFinite(prior)) {
      return value;
    }
    return Number((prior + (value - prior) * alpha).toFixed(2));
  });
}

function poseCacheKey(cameraId, object) {
  const trackId = object?.track_id;
  if (trackId === null || trackId === undefined || trackId === "") {
    return null;
  }
  const scope = cameraId || object?.overlay_camera_id || "camera";
  return `${scope}:${trackId}`;
}

function hasPoseKeypoints(pose) {
  return Boolean(pose && Array.isArray(pose.keypoints) && pose.keypoints.length > 0);
}

function isPoseDisabledPlaceholder(pose) {
  return Boolean(
    pose
    && (
      String(pose?.pose_provider || "").toLowerCase() === "disabled_placeholder"
      || pose?.debug?.pose_disabled === true
    )
  );
}

function poseAgeFromObject(object) {
  const ageMs = Number(object?.pose?.debug?.pose_frame_age_ms);
  return Number.isFinite(ageMs) ? Math.max(0, Math.round(ageMs)) : null;
}

function isPoseMarkedStale(object) {
  const ageMs = poseAgeFromObject(object);
  return ageMs != null && ageMs > APP_POSE_STALE_THRESHOLD_MS;
}

function validatePoseForObject(result, object, pose) {
  if (!pose || !hasPoseKeypoints(pose)) {
    return null;
  }
  if (isPoseDisabledPlaceholder(pose)) {
    return null;
  }
  const objectTrackId = normalizeTrackId(object?.track_id);
  const poseTrackId = normalizeTrackId(pose?.track_id);
  const sourceTrackId = normalizeTrackId(pose?.source_track_id);
  if (objectTrackId == null || poseTrackId == null || sourceTrackId == null) {
    return "pose_identity_missing";
  }
  if (poseTrackId !== objectTrackId || sourceTrackId !== objectTrackId) {
    return "pose_track_mismatch";
  }
  const poseFrameSeq = normalizeFrameSeq(pose?.pose_frame_seq ?? pose?.debug?.pose_frame_seq);
  const objectFrameSeq = normalizeFrameSeq(result?.frame_seq);
  if (poseFrameSeq == null || objectFrameSeq == null) {
    return "pose_frame_missing";
  }
  if (Math.abs(objectFrameSeq - poseFrameSeq) > 2) {
    return "pose_frame_desync";
  }
  if (!isPoseBboxAligned(object?.bbox, pose?.source_bbox || pose?.pose_bbox)) {
    return "pose_bbox_drift";
  }
  return null;
}

function isPoseBboxAligned(objectBbox, poseBbox) {
  const bbox = rectFromBbox(objectBbox);
  const reference = rectFromBbox(poseBbox);
  if (!bbox || !reference) {
    return false;
  }
  if (rectIou(bbox, reference) <= 0.05) {
    return false;
  }
  const shift = distance(rectCenter(bbox), rectCenter(reference));
  const diagonal = Math.hypot(bbox.width, bbox.height) || 1;
  return shift <= diagonal * OVERLAY_POSE_CACHE_MAX_CENTER_SHIFT_RATIO;
}

function clearPoseArtifacts(trackKey, object = null) {
  if (trackKey) {
    state.poseCache.delete(trackKey);
    clearSmoothingTrackByCacheKey(trackKey);
  }
  if (object) {
    window.__VISION_POSE_SMOOTHING__?.tracks?.delete?.(Number(object.track_id));
  }
}

function clearSmoothingTrackByCacheKey(trackKey) {
  const parts = String(trackKey || "").split(":");
  const maybeTrackId = Number(parts.at(-1));
  if (Number.isFinite(maybeTrackId)) {
    window.__VISION_POSE_SMOOTHING__?.tracks?.delete?.(maybeTrackId);
  }
}

function normalizeTrackId(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function normalizeFrameSeq(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function isReusableCachedPose(cached, object, now) {
  if (!cached || now - cached.updatedAt > OVERLAY_POSE_CACHE_TTL_MS) {
    return false;
  }
  if (!hasPoseKeypoints(object?.pose)) {
    return false;
  }
  if (!Array.isArray(object?.bbox) || object.bbox.length < 4 || !cached.poseBounds) {
    return false;
  }
  const bbox = rectFromBbox(object.bbox);
  const poseBounds = rectFromBbox(cached.poseBounds);
  if (!bbox || !poseBounds) {
    return false;
  }
  const iou = rectIou(bbox, poseBounds);
  if (iou <= 0.05) {
    return false;
  }
  const shift = distance(rectCenter(bbox), rectCenter(poseBounds));
  const diagonal = Math.hypot(bbox.width, bbox.height) || 1;
  return shift <= diagonal * OVERLAY_POSE_CACHE_MAX_CENTER_SHIFT_RATIO;
}

function computePoseBoundsFromPose(pose) {
  const points = (pose?.keypoints || [])
    .map((kp) => ({
      x: Number(kp?.x),
      y: Number(kp?.y),
      confidence: Number(kp?.confidence ?? 0),
    }))
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y) && point.confidence >= 0.2);
  if (!points.length) {
    return null;
  }
  return [
    Math.min(...points.map((point) => point.x)),
    Math.min(...points.map((point) => point.y)),
    Math.max(...points.map((point) => point.x)),
    Math.max(...points.map((point) => point.y)),
  ];
}

function rectFromBbox(bbox) {
  const x1 = Number(bbox?.[0]);
  const y1 = Number(bbox?.[1]);
  const x2 = Number(bbox?.[2]);
  const y2 = Number(bbox?.[3]);
  if (![x1, y1, x2, y2].every(Number.isFinite) || x2 <= x1 || y2 <= y1) {
    return null;
  }
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1, right: x2, bottom: y2 };
}

function rectCenter(rect) {
  return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
}

function distance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function rectIou(a, b) {
  const interX1 = Math.max(a.x, b.x);
  const interY1 = Math.max(a.y, b.y);
  const interX2 = Math.min(a.right, b.right);
  const interY2 = Math.min(a.bottom, b.bottom);
  const interW = Math.max(0, interX2 - interX1);
  const interH = Math.max(0, interY2 - interY1);
  const interArea = interW * interH;
  if (interArea <= 0) {
    return 0;
  }
  const areaA = a.width * a.height;
  const areaB = b.width * b.height;
  return interArea / Math.max(1, areaA + areaB - interArea);
}

function reconnectDelayMs(attempt) {
  const steps = [1000, 2000, 5000];
  return steps[Math.min(attempt, steps.length - 1)];
}

function clearReconnectTimer(kind) {
  const key = kind === "ws" ? "wsTimer" : "webrtcTimer";
  const timer = state.autoReconnect[key];
  if (timer) {
    clearTimeout(timer);
    state.autoReconnect[key] = null;
  }
}

function scheduleWebRTCReconnect(reason) {
  if (!state.userConnected || state.autoReconnect.connecting || state.autoReconnect.webrtcTimer) {
    updateRecoveryBanner();
    return;
  }
  const attempt = state.autoReconnect.webrtcAttempts++;
  const delay = reconnectDelayMs(attempt);
  debugState.counters.webrtcReconnects += 1;
  setText("webrtcState", `重连中 ${Math.round(delay / 1000)}s`);
  updateRecoveryBanner(reason);
  state.autoReconnect.webrtcTimer = setTimeout(() => {
    state.autoReconnect.webrtcTimer = null;
    connectWebRTC();
  }, delay);
}

function scheduleWebSocketReconnect(reason) {
  if (!state.userConnected || state.autoReconnect.wsTimer) {
    updateRecoveryBanner();
    return;
  }
  const attempt = state.autoReconnect.wsAttempts++;
  const delay = reconnectDelayMs(attempt);
  debugState.counters.wsReconnects += 1;
  setText("wsState", `重连中 ${Math.round(delay / 1000)}s`);
  updateRecoveryBanner(reason);
  state.autoReconnect.wsTimer = setTimeout(() => {
    state.autoReconnect.wsTimer = null;
    const pcState = state.pc?.connectionState;
    if (!state.pc || ["failed", "closed", "disconnected"].includes(pcState)) {
      scheduleWebRTCReconnect("websocket reconnect needs webrtc");
      return;
    }
    connectResults($("cameraId").value.trim() || "camera_01");
  }, delay);
}

function updateRecoveryBanner(extraMessage = null) {
  const banner = $("recoveryBanner");
  if (!banner) {
    return;
  }
  const status = state.lastStatus || {};
  const messages = [];
  const main = status.main_stream;
  const analysis = status.analysis_stream;

  if (status.diagnostics?.camera_lost) {
    messages.push("摄像头离线：已隐藏旧帧，等待新画面");
  } else if (status.diagnostics?.capture_stale) {
    messages.push("采集停滞：等待新帧恢复");
  }

  if (state.autoReconnect.webrtcTimer || state.autoReconnect.connecting) {
    messages.push("WebRTC 重连中");
  }
  if (state.autoReconnect.wsTimer) {
    messages.push("WebSocket 重连中");
  }
  if (status.display_fallback_active || status.display_source_current === "analysis") {
    messages.push("高清流恢复中，已切换到稳定分析流显示");
  } else if (main && !isStreamHealthy(main)) {
    messages.push("高清流恢复中");
  }
  if (analysis && !isStreamHealthy(analysis)) {
    messages.push("AI 分析流恢复中");
  }
  if (extraMessage) {
    messages.push(extraMessage);
  }

  if (!messages.length) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  banner.hidden = false;
  banner.textContent = Array.from(new Set(messages)).join(" / ");
}

async function refreshStatus() {
  try {
    const startedAt = performance.now();
    const cameraId = $("cameraId").value.trim() || "camera_01";
    const response = await fetch(`${apiBase()}/status?camera_id=${encodeURIComponent(cameraId)}`);
    const data = redactStatusForUi(await response.json());
    state.lastStatus = data;
    const jsonStartedAt = performance.now();
    if (debugState.showRawJson) {
      $("statusBox").textContent = JSON.stringify(data, null, 2);
      debugState.counters.rawJsonUpdates += 1;
    }
    const rawJsonMs = performance.now() - jsonStartedAt;
    updateStreamState(data);
    updateFrameFallbackVisibility(data);
    maybeAutoConnectFrontend(data);
    updateBackendSource(data);
    syncRtspInputFromStatus(data);
    if (isResultExpired(state.lastResult)) {
      expireOverlayResult();
    }
    updateMetricPanel(data);
    renderDashboard();
    debugState.counters.statusUpdates += 1;
    pushLimited(debugState.statusSamples, {
      at: Date.now(),
      elapsedMs: performance.now() - startedAt,
      rawJsonMs,
      frameAgeMs: data.cameras?.[0]?.frame_age_ms ?? null,
      publishFps: data.pipeline?.result_publish_fps ?? null,
      displayFps: getDisplayStreamStatus(data)?.display_mjpeg_served_fps ?? getDisplayStreamStatus(data)?.display_served_fps ?? null,
      poseFps: data.pose?.pose_fps ?? null,
    });
  } catch (error) {
    $("statusBox").textContent = String(error);
  }
}

function syncRtspInputFromStatus(status) {
  const input = $("rtspUrl");
  if (!input) {
    return;
  }
  if (!state.userEditedRtspUrl && !input.value.trim()) {
    input.placeholder = "HTTP MJPEG 或 RTSP 地址";
  }
}

function redactStatusForUi(value) {
  const forbiddenKeys = new Set([
    "source_url",
    "rtsp_url",
    "main_rtsp_url",
    "analysis_rtsp_url",
    "password",
    "token",
    "authorization",
  ]);
  if (Array.isArray(value)) {
    return value.map(redactStatusForUi);
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !forbiddenKeys.has(String(key).toLowerCase()))
    .map(([key, item]) => [key, redactStatusForUi(item)]));
}

function updateBackendSource(status) {
  const target = $("backendSource");
  if (!target) {
    return;
  }
  const main = status.main_stream;
  const analysis = status.analysis_stream || (status.cameras || [])[0];
  const display = status.display_source_current || status.display_source || "single";
  const analysisSource = status.analysis_source || "single";
  const hasConfiguredSource = Boolean(main?.source_url_masked || analysis?.source_url_masked);
  if (hasConfiguredSource) {
    const protocol = main?.source_protocol || analysis?.source_protocol || "unknown";
    const rawJpeg = main?.raw_jpeg_available || analysis?.raw_jpeg_available;
    target.textContent = `受控视频源已连接（协议=${protocol}，显示=${display}，分析=${analysisSource}${rawJpeg ? "，JPEG直出" : ""}）`;
    return;
  }
  target.textContent = "视频源状态未提供连接地址";
}

function updateStreamState(status) {
  const cameraId = $("cameraId").value.trim() || "camera_01";
  const camera = (status.cameras || []).find((item) => item.camera_id === cameraId);
  if (!camera) {
    setText("streamState", "未连接");
    updateFrameFallbackVisibility(status);
    updateRecoveryBanner();
    return;
  }

  const age = camera.frame_age_ms == null ? "-" : `${Math.round(camera.frame_age_ms)}ms`;
  const protocol = camera.source_protocol || camera.source || "unknown";
  const display = status.display_source_current || status.display_source || "single";
  const suffix = status.display_fallback_active ? " / 显示=分析流" : ` / 显示=${display}`;
  const staleLabel = status.diagnostics?.camera_lost
    ? "摄像头离线"
    : status.diagnostics?.capture_stale
      ? "采集停滞 / 等待新帧"
      : streamStateLabel(camera.stream_state);
  setText("streamState", `${staleLabel} (${age} / ${protocol})${suffix}`);
  maybeReconnectForDisplaySource(status);
  updateFrameFallbackVisibility(status);
  updateRecoveryBanner();
}

async function refreshControlStatus(cameraId = currentCameraId()) {
  try {
    const response = await fetch(`${apiBase()}/runtime-control/status?camera_id=${encodeURIComponent(cameraId)}`);
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    state.lastControlStatus = payload;
    renderControlStatus(payload);
  } catch (error) {
    setControlResult("modelControlResult", `状态读取失败：${error}`, "error");
  }
}

function renderControlStatus(control) {
  const test = control?.test || {};
  const runtime = control?.runtime || {};
  const streamOn = Boolean(control?.stream_connected);
  const binaryOn = Boolean(control?.binary_enabled);
  const qwenOn = Boolean(control?.qwen_enabled);
  const testRunning = Boolean(test.running);
  const testState = String(test.state || (testRunning ? "running" : "idle")).toLowerCase();
  const testActive = testRunning || testState === "draining";
  setStateText("videoControlState", streamOn ? "ON" : "OFF", streamOn ? "on" : "off");
  setStateText("binaryControlState", binaryOn ? "ON" : "OFF", binaryOn ? "on" : "off");
  setStateText("qwenControlState", qwenOn ? "ON" : "OFF", qwenOn ? "on" : "off");
  setStateText("testControlState", formatTestState(test), testActive ? "running" : "idle");
  setStateText(
    "binaryProvider",
    runtime.binary_provider || "-",
    runtime.binary_provider_degraded ? "error" : (runtime.binary_provider === "CUDAExecutionProvider" ? "on" : ""),
  );
  setText("binarySampleFps", formatFps(runtime.binary_sample_fps ?? runtime.sample_fps));
  setText("binaryQueue", formatQueueDepth(runtime.queue_depth, runtime.frames_dropped));
  setText("binaryFrameAge", formatMs(runtime.frame_age_ms));
  setText("binaryLatency", formatMs(runtime.binary_inference_latency_avg_ms ?? runtime.binary_inference_latency_ms));
  renderTestMetrics(test, control?.performance || {});
  if (!binaryOn) {
    forceIdleAlarmIndicator();
  }

  const binaryBtn = $("binaryToggleBtn");
  if (binaryBtn) {
    binaryBtn.textContent = binaryOn ? "关闭二分类" : "开启二分类";
    binaryBtn.disabled = !streamOn && !binaryOn;
  }
  const qwenBtn = $("qwenToggleBtn");
  if (qwenBtn) {
    qwenBtn.textContent = qwenOn ? "关闭千问" : "开启千问";
    qwenBtn.disabled = (!binaryOn && !qwenOn);
  }
  const startTestBtn = $("startTestBtn");
  const stopTestBtn = $("stopTestBtn");
  if (startTestBtn) {
    startTestBtn.disabled = testActive;
  }
  if (stopTestBtn) {
    stopTestBtn.disabled = !testRunning;
  }
  setTestInputsDisabled(testActive);
  if (testRunning) {
    writeDurationInputs(test.remaining_seconds || 0);
    setControlResult("testControlResult", `测试中：${formatHms(test.remaining_seconds || 0)}；Session ${test.test_session_id || "-"}`, "pending");
  } else if (testState === "draining") {
    setControlResult("testControlResult", `等待千问归档：${test.qwen_unresolved_count || 0} 个事件；Session ${test.test_session_id || "-"}`, "pending");
  } else if (state.lastControlStatus?.test?.remaining_seconds === 0 && test.test_session_id) {
    setControlResult("testControlResult", `测试已结束：Session ${test.test_session_id}`, "success");
  }
  renderDashboard();
}

function renderTestMetrics(test, runtimePerformance = {}) {
  const perf = test?.latest_performance || runtimePerformance || {};
  setText("testSessionId", test?.test_session_id || "-");
  setText(
    "testEventCounts",
    test?.test_session_id
      ? `FALL ${test.binary_fall_count || 0} / NON ${test.binary_non_fall_count || 0} / 事件 ${test.binary_full_count || 0} / 待复核 ${test.qwen_review_count || 0} / 待归档 ${test.qwen_unresolved_count || 0}`
      : "-",
  );
  setText("testCpuUsage", formatPercent(perf.cpu_percent));
  setText("testProcessCpuUsage", formatPercent(perf.process_cpu_percent));
  setText("testGpuUsage", formatPercent(perf.gpu_util_percent));
  setText("testGpuMemory", formatGpuMemory(perf.gpu_memory_used_mb, perf.gpu_memory_total_mb));
}

function formatTestState(test) {
  const stateName = String(test?.state || "").toLowerCase();
  if (test?.running) {
    return formatHms(test.remaining_seconds || 0);
  }
  if (stateName === "draining") {
    return "DRAINING";
  }
  if (stateName === "completed") {
    return "COMPLETED";
  }
  return "IDLE";
}

async function toggleBinaryModel() {
  const control = state.lastControlStatus || {};
  const enabled = !control.binary_enabled;
  await postModelToggle("binary", enabled, "binaryToggleBtn", "modelControlResult");
}

async function toggleQwenModel() {
  const control = state.lastControlStatus || {};
  const enabled = !control.qwen_enabled;
  await postModelToggle("qwen", enabled, "qwenToggleBtn", "modelControlResult");
}

async function postModelToggle(kind, enabled, buttonId, resultId) {
  const button = $(buttonId);
  let succeeded = false;
  if (button) {
    button.disabled = true;
  }
  setControlResult(resultId, enabled ? "正在开启..." : "正在关闭...", "pending");
  try {
    const response = await fetch(`${apiBase()}/runtime-control/${kind}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ camera_id: currentCameraId(), enabled }),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    state.lastControlStatus = payload;
    renderControlStatus(payload);
    setControlResult(resultId, `${kind === "binary" ? "二分类" : "千问"}已${enabled ? "开启" : "关闭"}`, "success");
    succeeded = true;
  } catch (error) {
    setControlResult(resultId, `操作失败：${error}`, "error");
  } finally {
    await refreshControlStatus();
  }
  return succeeded;
}

async function startVideoOnly() {
  setControlResult("sessionControlResult", "F5：正在启动独立视频...", "pending");
  await Promise.all([refreshSessionStatus(), refreshControlStatus()]);
  const sessionState = String(state.lastSessionStatus?.state || "IDLE").toUpperCase();
  if (["STARTING", "RUNNING", "STOPPING"].includes(sessionState)) {
    setControlResult("sessionControlResult", "完整检测会话正在运行，请先按 F8 结束并保存，再使用 F5。", "error");
    return false;
  }

  const control = state.lastControlStatus || {};
  const binaryActive = Boolean(control.binary_enabled || control.binary_requested);
  const qwenActive = Boolean(control.qwen_enabled || control.qwen_requested);
  if (binaryActive) {
    const disabled = await postModelToggle("binary", false, "binaryToggleBtn", "modelControlResult");
    if (!disabled) {
      setControlResult("sessionControlResult", "F5 启动失败：无法关闭当前模型。", "error");
      return false;
    }
  } else if (qwenActive) {
    const disabled = await postModelToggle("qwen", false, "qwenToggleBtn", "modelControlResult");
    if (!disabled) {
      setControlResult("sessionControlResult", "F5 启动失败：无法关闭当前千问模型。", "error");
      return false;
    }
  }

  try {
    await startStreamRequest({ updateUi: false });
    await Promise.all([refreshControlStatus(), refreshStatus()]);
    setControlResult("sessionControlResult", "F5：视频已启动，二分类与千问暂未启动。", "success");
    return true;
  } catch (error) {
    setControlResult("sessionControlResult", `F5 视频启动失败：${error}`, "error");
    return false;
  }
}

async function startBothModels() {
  setControlResult("sessionControlResult", "F6：正在启动二分类与千问...", "pending");
  await refreshControlStatus();
  if (!state.lastControlStatus?.stream_connected) {
    setControlResult("sessionControlResult", "F6 启动失败：请先按 F5 启动视频。", "error");
    return false;
  }

  if (!state.lastControlStatus.binary_enabled) {
    const binaryStarted = await postModelToggle("binary", true, "binaryToggleBtn", "modelControlResult");
    if (!binaryStarted) {
      setControlResult("sessionControlResult", "F6 启动失败：二分类模型未能启动。", "error");
      return false;
    }
  }
  if (!state.lastControlStatus?.qwen_enabled) {
    const qwenStarted = await postModelToggle("qwen", true, "qwenToggleBtn", "modelControlResult");
    if (!qwenStarted) {
      setControlResult("sessionControlResult", "F6 启动失败：千问模型未能启动。", "error");
      return false;
    }
  }

  await refreshControlStatus();
  const ready = Boolean(state.lastControlStatus?.binary_enabled && state.lastControlStatus?.qwen_enabled);
  setControlResult(
    "sessionControlResult",
    ready ? "F6：二分类与千问均已启动。" : "F6 启动未完成，请查看模型状态。",
    ready ? "success" : "error",
  );
  return ready;
}

async function startTimedTest() {
  const duration = readDurationInputs();
  if (duration.totalSeconds <= 0) {
    setControlResult("testControlResult", "失败：测试时间必须大于 0 秒", "error");
    return;
  }
  setControlResult("testControlResult", "正在开始测试...", "pending");
  try {
    const response = await fetch(`${apiBase()}/runtime-control/test/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(duration.payload),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    await refreshControlStatus();
  } catch (error) {
    setControlResult("testControlResult", `启动失败：${error}`, "error");
  }
}

async function stopTimedTest() {
  setControlResult("testControlResult", "正在停止测试...", "pending");
  try {
    const response = await fetch(`${apiBase()}/runtime-control/test/stop`, { method: "POST" });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    renderControlStatus({ ...(state.lastControlStatus || {}), test: payload });
  } catch (error) {
    setControlResult("testControlResult", `停止失败：${error}`, "error");
  } finally {
    await refreshControlStatus();
  }
}

async function refreshSessionStatus(cameraId = currentCameraId()) {
  try {
    const response = await fetch(`${apiBase()}/runtime-control/session/status?camera_id=${encodeURIComponent(cameraId)}`);
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    state.lastSessionStatus = payload;
    renderSessionStatus(payload);
    if (state.demoFall.active) {
      renderDemoVisualState();
    }
  } catch (error) {
    setControlResult("sessionControlResult", `Session状态读取失败：${error}`, "error");
    if (state.demoFall.active) {
      renderDemoVisualState();
    }
  }
}

async function toggleDetectionSession() {
  const session = state.lastSessionStatus || {};
  const current = String(session.state || "IDLE").toUpperCase();
  if (["STARTING", "STOPPING"].includes(current)) {
    return;
  }
  if (current === "RUNNING") {
    await stopDetectionSession();
    return;
  }
  await startDetectionSession();
}

async function startDetectionSession() {
  const button = $("sessionToggleBtn");
  if (button) button.disabled = true;
  setControlResult("sessionControlResult", "正在启动完整检测链路...", "pending");
  try {
    const response = await fetch(`${apiBase()}/runtime-control/session/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        camera_id: currentCameraId(),
        source_url: $("rtspUrl")?.value?.trim() || null,
      }),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    state.lastSessionStatus = payload;
    renderSessionStatus(payload);
    setControlResult("sessionControlResult", payload.failure_reason ? `启动失败：${payload.failure_reason}` : "完整检测已启动", payload.failure_reason ? "error" : "success");
    await Promise.all([refreshControlStatus(), refreshStatus()]);
  } catch (error) {
    setControlResult("sessionControlResult", `启动失败：${error}`, "error");
  } finally {
    if (button) button.disabled = false;
    await refreshSessionStatus();
  }
}

async function stopDetectionSession() {
  const button = $("sessionToggleBtn");
  if (button) button.disabled = true;
  setControlResult("sessionControlResult", "正在保存最后结果，请等待当前千问复核归档...", "pending");
  try {
    const response = await fetch(`${apiBase()}/runtime-control/session/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ camera_id: currentCameraId() }),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    state.lastSessionStatus = payload;
    renderSessionStatus(payload);
    setControlResult("sessionControlResult", "本次检测已请求结束，结果正在归档。", "success");
    await Promise.all([refreshControlStatus(), refreshStatus()]);
  } catch (error) {
    setControlResult("sessionControlResult", `停止失败：${error}`, "error");
  } finally {
    if (button) button.disabled = false;
    await refreshSessionStatus();
  }
}

function renderSessionStatus(session) {
  const normalized = String(session?.state || "IDLE").toUpperCase();
  const archive = session?.archive || {};
  const presentation = session?.presentation_result || archive.presentation_result || null;
  const button = $("sessionToggleBtn");
  const interactive = !["STARTING", "STOPPING"].includes(normalized);
  const running = normalized === "RUNNING";
  const stopping = normalized === "STOPPING";
  const failed = normalized === "FAILED";
  setText("sessionStateLabel", sessionStateLabel(normalized));
  setText("sessionElapsed", formatHms(session?.elapsed_seconds || 0));
  setText("sessionIdDisplay", session?.session_id || "-");
  setStateText("sessionSaveState", sessionSaveState(session), stopping ? "running" : (failed ? "error" : ""));
  if (button) {
    button.disabled = !interactive;
    button.textContent = running ? "结束并保存检测" : (stopping ? "正在保存最后结果..." : "开始完整检测");
    button.dataset.mode = running ? "stop" : "start";
  }
  renderPresentationResult(presentation, session);
}

function renderPresentationResult(presentation, session) {
  const control = state.lastControlStatus || {};
  const result = state.lastResult || {};
  const incomingPresentation = presentation;
  const incomingDecision = targetFallDecision(result);
  const judgmentSuppressed = state.judgmentReset.active;
  const presentationAcknowledged = isAcknowledgedFallEventId(incomingPresentation?.event_id);
  const decisionAcknowledged = isAcknowledgedFallEventId(incomingDecision?.incident_id);
  const suppressStaleRuntime = judgmentSuppressed
    || (presentationAcknowledged && (!incomingDecision?.incident_id || decisionAcknowledged));
  presentation = judgmentSuppressed || presentationAcknowledged ? null : incomingPresentation;
  const decision = judgmentSuppressed || decisionAcknowledged ? null : incomingDecision;
  const qwenActive = suppressStaleRuntime
    ? false
    : Number(session?.components?.qwen?.active_count || control?.runtime?.vlm_active_count || 0) > 0;
  const binaryLabel = suppressStaleRuntime
    ? ""
    : String(decision?.binary_label || control?.runtime?.binary_last_label || "").toUpperCase();
  setAcknowledgeFallButton(incomingPresentation);
  let label = presentation?.fall_label_zh || "";
  let resultState = "idle";
  if (presentation?.analysis_status === "no_event" || !presentation?.event_id) {
    if (qwenActive) {
      label = "正在复核";
      resultState = "reviewing";
    } else if (binaryLabel === "FALL") {
      label = "疑似跌倒";
      resultState = "candidate";
    } else {
      label = "持续监测中";
      resultState = "idle";
    }
  } else if (presentation.is_real_fall === true) {
    label = "真实跌倒";
    resultState = "fall";
  } else if (presentation.is_real_fall === false) {
    label = "非真实跌倒";
    resultState = "non_fall";
  } else if (presentation.fall_label_zh === "视觉证据不足") {
    resultState = "unknown";
  } else {
    label = presentation.fall_label_zh || "无法明确判断";
    resultState = "unknown";
  }
  const panel = $("presentationResultPanel");
  if (panel) panel.dataset.resultState = resultState;
  setText("presentationAnalysisStatus", presentationStatusText(presentation, qwenActive));
  setText("realFallVerdict", label);
  setText("realFallVerdictMeta", presentation?.event_id ? `${presentationShortId(presentation.event_id)} · ${presentation.fall_verdict || "-"}` : "暂无跌倒事件");
  setText("realFallBoolean", realFallBooleanText(presentation));
  const demoPresentation = state.demoFall.active && state.demoFall.presentation === presentation;
  renderQwenDescription(demoPresentation && !state.demoFall.revealDescription ? null : presentation);
  setText("presentationBinaryState", control?.binary_enabled ? (binaryLabel || "RUNNING") : "OFF");
  setText("presentationQwenState", control?.qwen_enabled ? (qwenActive ? "REVIEWING" : "STANDBY") : "OFF");
  setText("presentationEventId", presentation?.event_id ? presentationShortId(presentation.event_id) : (decision?.incident_id ? presentationShortId(decision.incident_id) : "--"));
  setText("presentationAlarmState", presentation?.is_real_fall === true ? "等待/已推送" : "--");
  renderCoreJson(demoPresentation && !state.demoFall.revealJson ? null : presentation);
}

function setAcknowledgeFallButton(presentation) {
  const button = $("acknowledgeFallBtn");
  if (!button) return;
  const eventId = normalizedIncidentId(presentation?.event_id);
  const visible = Boolean(
    eventId
    && presentation?.is_real_fall === true
    && !isAcknowledgedFallEventId(eventId),
  );
  button.hidden = !visible;
  button.dataset.eventId = visible ? eventId : "";
}

function isAcknowledgedFallEventId(value) {
  const eventId = normalizedIncidentId(value);
  return Boolean(eventId && state.acknowledgedFallEventIds.has(eventId));
}

function persistAcknowledgedFallEventIds() {
  const values = Array.from(state.acknowledgedFallEventIds).slice(-ACKNOWLEDGED_FALL_EVENTS_MAX);
  state.acknowledgedFallEventIds = new Set(values);
  try {
    window.sessionStorage.setItem(ACKNOWLEDGED_FALL_EVENTS_KEY, JSON.stringify(values));
  } catch {
    // The acknowledgement still remains active in memory when storage is unavailable.
  }
}

function acknowledgeCurrentFall() {
  const button = $("acknowledgeFallBtn");
  const eventId = normalizedIncidentId(button?.dataset.eventId);
  if (!eventId) return;
  state.acknowledgedFallEventIds.add(eventId);
  persistAcknowledgedFallEventIds();
  forceIdleAlarmIndicator();
  setViewerAlertState("idle");
  if (state.demoFall.active && state.demoFall.incidentId === eventId) {
    resetDemoFall("模拟跌倒信息已确认收到，页面恢复持续监测状态。");
    return;
  }
  renderDashboard();
  setControlResult("sessionControlResult", "跌倒信息已确认收到，当前事件告警已解除。", "success");
}

function currentJudgmentSnapshot() {
  const session = state.lastSessionStatus || {};
  const control = state.lastControlStatus || {};
  const presentation = session.presentation_result || session.archive?.presentation_result || null;
  const decision = targetFallDecision(state.lastResult || {}) || {};
  const presentationId = presentation?.is_real_fall === true
    ? normalizedIncidentId(presentation.event_id)
    : "";
  const incidentIds = [
    presentationId,
    decision.incident_id,
    state.alarmIndicator.currentEventId,
  ].map(normalizedIncidentId).filter(Boolean);
  return {
    incidentIds: Array.from(new Set(incidentIds)),
    binaryWarning: String(decision.binary_label || control.runtime?.binary_last_label || "").toUpperCase() === "FALL",
    qwenActive: Number(session.components?.qwen?.active_count || control.runtime?.vlm_active_count || 0) > 0,
  };
}

function acknowledgeJudgmentIncidentIds(incidentIds) {
  let changed = false;
  for (const incidentId of incidentIds) {
    if (!state.acknowledgedFallEventIds.has(incidentId)) {
      state.acknowledgedFallEventIds.add(incidentId);
      changed = true;
    }
    state.judgmentReset.incidentIds.add(incidentId);
  }
  if (changed) {
    persistAcknowledgedFallEventIds();
  }
}

function synchronizeJudgmentReset() {
  if (!state.judgmentReset.active) {
    return false;
  }
  const snapshot = currentJudgmentSnapshot();
  acknowledgeJudgmentIncidentIds(snapshot.incidentIds);
  const signalActive = snapshot.binaryWarning || snapshot.qwenActive;
  if (signalActive) {
    state.judgmentReset.quietSince = null;
    return true;
  }

  if (state.judgmentReset.incidentIds.size > 0) {
    state.judgmentReset.active = false;
    state.judgmentReset.quietSince = null;
    return true;
  }
  const now = Date.now();
  state.judgmentReset.quietSince ??= now;
  if (now - state.judgmentReset.quietSince >= JUDGMENT_RESET_QUIET_MS) {
    state.judgmentReset.active = false;
    state.judgmentReset.quietSince = null;
  }
  return true;
}

function resetCurrentJudgment() {
  if (state.demoFall.active) {
    resetDemoFall("F7：当前模拟判断已停止，页面恢复持续监测状态。");
    return;
  }

  const snapshot = currentJudgmentSnapshot();
  const viewerState = document.querySelector(".viewer")?.dataset.alertState || "idle";
  const hasCurrentJudgment = Boolean(
    snapshot.incidentIds.length
    || snapshot.binaryWarning
    || snapshot.qwenActive
    || ["warning", "danger"].includes(viewerState),
  );
  state.judgmentReset.active = hasCurrentJudgment;
  state.judgmentReset.incidentIds = new Set();
  state.judgmentReset.resetAt = Date.now();
  state.judgmentReset.quietSince = hasCurrentJudgment ? null : Date.now();
  acknowledgeJudgmentIncidentIds(snapshot.incidentIds);
  forceIdleAlarmIndicator();
  setViewerAlertState("idle");
  renderDashboard();
  setControlResult(
    "sessionControlResult",
    hasCurrentJudgment ? "F7：当前判断已停止，页面已恢复持续监测。" : "F7：页面已处于默认监测状态。",
    "success",
  );
}

function renderQwenDescription(presentation) {
  const description = qwenChineseDescription(presentation);
  const panel = $("qwenDescriptionPanel");
  if (panel) {
    panel.dataset.state = description ? "filled" : "empty";
  }
  setText("timeDescriptionZh", description || "");
}

function qwenChineseDescription(presentation) {
  if (!presentation?.event_id) {
    return "";
  }
  const qwen = presentation?.qwen_analysis || presentation?.qwen || presentation?.analysis || {};
  const qwenStatus = String(qwen.analysis_status || presentation?.analysis_status || "").toLowerCase();
  if (qwenStatus && !["completed", "timeout", "failed", "parse_failed"].includes(qwenStatus)) {
    return "";
  }
  return String(
    qwen.summary
      || qwen.time_description_zh
      || presentation?.time_description_zh
      || qwen.posture
      || presentation?.summary
      || "",
  ).trim();
}

function renderCoreJson(presentation) {
  const empty = $("coreJsonEmpty");
  const box = $("coreJsonBox");
  if (!box || !empty) return;
  if (!presentation?.event_id) {
    empty.hidden = false;
    box.hidden = true;
    const button = $("toggleFullJsonBtn");
    if (button) {
      button.dataset.fullJson = "0";
      button.textContent = "完整 JSON";
    }
    return;
  }
  const qwen = presentation.qwen_analysis || null;
  const core = qwen ? {
    qwen_analysis: {
      incident_id: qwen.incident_id || presentation.event_id,
      analysis_status: qwen.analysis_status || presentation.analysis_status,
      fall_verdict: qwen.fall_verdict || presentation.fall_verdict,
      posture: qwen.posture || null,
      movement_level: qwen.movement_level || null,
      attempt_to_stand: qwen.attempt_to_stand || null,
      persistent_ground_state: qwen.persistent_ground_state || null,
      visibility: qwen.visibility || null,
      occlusion: qwen.occlusion || null,
      scene_risks: qwen.scene_risks || [],
      possible_help_gesture: qwen.possible_help_gesture || null,
      summary: qwen.summary || qwenChineseDescription(presentation) || null,
      review_points: qwen.review_points || [],
      confidence: qwen.confidence ?? presentation.confidence ?? null,
      latency_ms: qwen.latency_ms ?? null,
    },
    is_real_fall: presentation.is_real_fall,
    confidence: presentation.confidence ?? null,
    source: presentation.source || undefined,
  } : {
    time_description_zh: presentation.time_description_zh,
    is_real_fall: presentation.is_real_fall,
    fall_verdict: presentation.fall_verdict,
    confidence: presentation.confidence ?? null,
    analysis_status: presentation.analysis_status,
  };
  empty.hidden = true;
  box.hidden = false;
  box.textContent = JSON.stringify(core, null, 2);
}

function toggleFullJson() {
  const presentation = currentPresentationForJson();
  const box = $("coreJsonBox");
  const button = $("toggleFullJsonBtn");
  if (!box || !presentation?.event_id) return;
  const showingFull = button?.dataset.fullJson === "1";
  if (showingFull) {
    renderCoreJson(presentation);
    if (button) {
      button.dataset.fullJson = "0";
      button.textContent = "完整 JSON";
    }
    return;
  }
  box.hidden = false;
  box.textContent = JSON.stringify(presentation, null, 2);
  if (button) {
    button.dataset.fullJson = "1";
    button.textContent = "收起 JSON";
  }
}

function currentPresentationForJson() {
  return state.demoFall.active && state.demoFall.presentation?.event_id
    ? state.demoFall.presentation
    : state.lastSessionStatus?.presentation_result || state.lastSessionStatus?.archive?.presentation_result;
}

function toggleDemoFall() {
  toggleDemoScenario("fall");
}

function toggleDemoLowPosture() {
  toggleDemoScenario("low_posture");
}

function toggleDemoScenario(scenario) {
  if (state.demoFall.active && state.demoFall.scenario === scenario) {
    resetDemoFall("模拟展示已重置，页面恢复真实系统状态。");
    return;
  }
  startDemoScenario(scenario);
}

function startDemoScenario(scenario) {
  clearDemoFallTimers();
  const lowPosture = scenario === "low_posture";
  const incidentId = `${lowPosture ? "demo-low-posture" : "demo-fall"}-${currentCameraId()}-${Date.now().toString(16)}`;
  state.demoFall.active = true;
  state.demoFall.scenario = lowPosture ? "low_posture" : "fall";
  state.demoFall.phase = "analyzing";
  state.demoFall.incidentId = incidentId;
  state.demoFall.startedAt = Date.now();
  state.demoFall.presentation = null;
  state.demoFall.revealDescription = false;
  state.demoFall.revealJson = false;
  setControlResult(
    "sessionControlResult",
    lowPosture
      ? "DEMO 2：主动坐下低姿态已进入二分类初筛，不写入真实记录。"
      : "DEMO：模拟事件已进入二分类初筛，不写入真实记录。",
    "pending",
  );
  scheduleDemoFallPhase("suspected", DEMO_FALL_STAGE_MS.suspected);
  scheduleDemoFallPhase("reviewing", DEMO_FALL_STAGE_MS.reviewing);
  scheduleDemoFallPhase("completed", DEMO_FALL_STAGE_MS.completed);
  scheduleDemoEvidenceReveal("description", DEMO_FALL_STAGE_MS.description);
  scheduleDemoEvidenceReveal("json", DEMO_FALL_STAGE_MS.json);
  renderDemoVisualState();
}

function scheduleDemoFallPhase(phase, delayMs) {
  const timer = window.setTimeout(() => {
    if (!state.demoFall.active) {
      return;
    }
    state.demoFall.phase = phase;
    if (phase === "completed") {
      state.demoFall.presentation = buildDemoPresentation();
      setControlResult(
        "sessionControlResult",
        state.demoFall.scenario === "low_posture"
          ? "DEMO 2：千问已排除真实跌倒，已生成非跌倒 JSON 与中文事件描述。"
          : "DEMO：千问复核完成，已生成模拟 JSON 与中文事件描述。",
        "success",
      );
    }
    renderDemoVisualState();
  }, delayMs);
  state.demoFall.timers.push(timer);
}

function scheduleDemoEvidenceReveal(kind, delayMs) {
  const timer = window.setTimeout(() => {
    if (!state.demoFall.active || !state.demoFall.presentation) {
      return;
    }
    if (kind === "description") {
      state.demoFall.revealDescription = true;
      renderQwenDescription(state.demoFall.presentation);
      return;
    }
    state.demoFall.revealJson = true;
    renderCoreJson(state.demoFall.presentation);
  }, delayMs);
  state.demoFall.timers.push(timer);
}

function resetDemoFall(message = "") {
  clearDemoFallTimers();
  state.demoFall.active = false;
  state.demoFall.scenario = null;
  state.demoFall.phase = "idle";
  state.demoFall.incidentId = null;
  state.demoFall.startedAt = null;
  state.demoFall.presentation = null;
  state.demoFall.revealDescription = false;
  state.demoFall.revealJson = false;
  updateDemoButtons();
  if (message) {
    setControlResult("sessionControlResult", message, "success");
  }
  renderDashboard();
}

function clearDemoFallTimers() {
  for (const timer of state.demoFall.timers || []) {
    window.clearTimeout(timer);
  }
  state.demoFall.timers = [];
}

function renderDemoVisualState() {
  if (state.demoFall.active && hasRealActiveEventSignal()) {
    resetDemoFall("检测到真实跌倒事件，模拟展示已自动结束。");
    return;
  }
  updateDemoButtons();
  if (!state.demoFall.active) {
    setPipelineAlarmLabel("Alarm API");
    renderRealModelSentinels();
    return;
  }
  const phase = state.demoFall.phase;
  if (phase === "completed" && state.demoFall.presentation) {
    renderPresentationResult(state.demoFall.presentation, demoSessionSnapshot());
    renderDemoCompletedState();
    return;
  }
  renderDemoProgressState(phase);
}

function renderDemoProgressState(phase) {
  const lowPosture = state.demoFall.scenario === "low_posture";
  const suspected = phase === "suspected" || phase === "reviewing";
  const reviewing = phase === "reviewing";
  setAcknowledgeFallButton(null);
  setViewerAlertState(suspected ? "warning" : "idle", reviewing ? "reviewing" : "candidate");
  setModelSentinel(
    "binaryModelNode",
    suspected ? "warning" : "active",
    "binaryModelState",
    "binaryModelMeta",
    suspected ? (lowPosture ? "检测到低姿态" : "高度疑似跌倒") : "正在分析",
    suspected ? (lowPosture ? "LOW POSTURE 0.91" : "FALL 0.94") : "跌倒检测模型",
  );
  setModelSentinel("qwenModelNode", reviewing ? "warning" : "idle", "qwenModelState", "qwenModelMeta", reviewing ? "正在复核" : "默认待机", reviewing ? "REVIEWING" : "千问大模型");
  setSummaryDemoState(phase);
  setPipelineDemoState(phase);
  renderQwenDescription(null);
  renderCoreJson(null);
  setText("presentationAnalysisStatus", reviewing ? "千问复核中" : (suspected ? "等待复核" : "二分类分析"));
  setText("realFallVerdict", reviewing ? "正在复核" : (suspected ? (lowPosture ? "疑似低姿态" : "高度疑似跌倒") : "正在分析"));
  setText("realFallVerdictMeta", reviewing ? "千问正在进行场景语义复核" : (suspected ? "等待千问复核" : "二分类模型正在初筛"));
  setText("realFallBoolean", "--");
  setText("presentationBinaryState", suspected ? (lowPosture ? "LOW_POSTURE 0.91" : "FALL 0.94") : "ANALYZING");
  setText("presentationQwenState", reviewing ? "REVIEWING" : "STANDBY");
  setText("presentationEventId", presentationShortId(state.demoFall.incidentId));
  setText("presentationAlarmState", "DEMO未投递");
  setText("videoOverlayBinary", suspected ? (lowPosture ? "Binary: LOW_POSTURE 0.91" : "Binary: FALL 0.94") : "Binary: ANALYZING");
  setText("videoOverlayQwen", reviewing ? "Qwen: REVIEWING" : "Qwen: STANDBY");
  setText("videoOverlayIncident", `Event: ${presentationShortId(state.demoFall.incidentId)}`);
  const panel = $("presentationResultPanel");
  if (panel) panel.dataset.resultState = reviewing ? "reviewing" : (suspected ? "candidate" : "idle");
  appendDemoTrendPoint(phase);
}

function renderDemoCompletedState() {
  if (state.demoFall.scenario === "low_posture") {
    setViewerAlertState("idle", "cleared");
    setModelSentinel("binaryModelNode", "warning", "binaryModelState", "binaryModelMeta", "检测到低姿态", "LOW POSTURE 0.91");
    setModelSentinel("qwenModelNode", "success", "qwenModelState", "qwenModelMeta", "已排除真实跌倒", "intentional_low_posture");
    setSummaryDemoState("completed");
    setPipelineDemoState("completed");
    setText("presentationBinaryState", "LOW_POSTURE 0.91");
    setText("presentationQwenState", "INTENTIONAL_LOW_POSTURE");
    setText("presentationAlarmState", "无需告警");
    setText("videoOverlayBinary", "Binary: LOW_POSTURE 0.91");
    setText("videoOverlayQwen", "Qwen: NOT A FALL");
    setText("videoOverlayIncident", `Event: ${presentationShortId(state.demoFall.incidentId)}`);
    appendDemoTrendPoint("completed");
    return;
  }
  setViewerAlertState("danger", "confirmed");
  setModelSentinel("binaryModelNode", "warning", "binaryModelState", "binaryModelMeta", "高度疑似跌倒", "FALL 0.94");
  setModelSentinel("qwenModelNode", "danger", "qwenModelState", "qwenModelMeta", "确认真实跌倒", "confirmed_fall");
  setSummaryDemoState("completed");
  setPipelineDemoState("completed");
  setText("presentationBinaryState", "FALL 0.94");
  setText("presentationQwenState", "CONFIRMED_FALL");
  setText("presentationAlarmState", "DEMO模拟联动");
  setText("videoOverlayBinary", "Binary: FALL 0.94");
  setText("videoOverlayQwen", "Qwen: CONFIRMED_FALL");
  setText("videoOverlayIncident", `Event: ${presentationShortId(state.demoFall.incidentId)}`);
  appendDemoTrendPoint("completed");
}

function renderRealModelSentinels() {
  const control = state.lastControlStatus || {};
  const result = state.lastResult || {};
  const session = state.lastSessionStatus || {};
  const incomingPresentation = session.presentation_result || session.archive?.presentation_result || null;
  const incomingDecision = targetFallDecision(result) || {};
  const judgmentSuppressed = state.judgmentReset.active;
  const presentationAcknowledged = isAcknowledgedFallEventId(incomingPresentation?.event_id);
  const decisionAcknowledged = isAcknowledgedFallEventId(incomingDecision.incident_id);
  const suppressStaleRuntime = judgmentSuppressed
    || (presentationAcknowledged && (!incomingDecision.incident_id || decisionAcknowledged));
  const presentation = judgmentSuppressed || presentationAcknowledged ? null : incomingPresentation;
  const decision = judgmentSuppressed || decisionAcknowledged ? {} : incomingDecision;
  const binaryLabel = suppressStaleRuntime
    ? ""
    : String(decision.binary_label || control.runtime?.binary_last_label || "").toUpperCase();
  const probability = numberOrNull(decision.binary_probability ?? decision.fall_probability ?? control.runtime?.binary_last_probability);
  const qwenActive = suppressStaleRuntime
    ? false
    : Number(session.components?.qwen?.active_count || control.runtime?.vlm_active_count || 0) > 0;
  const binaryEnabled = Boolean(control.binary_enabled);
  const qwenEnabled = Boolean(control.qwen_enabled);
  const binaryWarning = binaryLabel === "FALL";
  setModelSentinel(
    "binaryModelNode",
    binaryWarning ? "warning" : (binaryEnabled ? "active" : "idle"),
    "binaryModelState",
    "binaryModelMeta",
    binaryWarning ? "高度疑似跌倒" : (binaryEnabled ? "默认监测" : "默认状态"),
    binaryWarning ? probabilityText("FALL", probability) : "跌倒检测模型",
  );
  const qwenState = presentation?.is_real_fall === true ? "danger" : (qwenActive ? "warning" : (qwenEnabled ? "active" : "idle"));
  const qwenLabel = presentation?.is_real_fall === true ? "确认真实跌倒" : (qwenActive ? "正在复核" : (qwenEnabled ? "默认待机" : "默认状态"));
  const qwenMeta = presentation?.fall_verdict || (qwenActive ? "REVIEWING" : "千问大模型");
  setModelSentinel("qwenModelNode", qwenState, "qwenModelState", "qwenModelMeta", qwenLabel, qwenMeta);
  if (presentation?.is_real_fall === true) {
    setViewerAlertState("danger", "confirmed");
  } else if (binaryWarning || qwenActive) {
    setViewerAlertState("warning", qwenActive ? "reviewing" : "candidate");
  } else {
    setViewerAlertState("idle");
  }
}

function setSummaryDemoState(phase) {
  const lowPosture = state.demoFall.scenario === "low_posture";
  setDemoCard("cardBinary", "summaryBinaryValue", "summaryBinaryMeta", phase === "analyzing" ? "正在分析" : (lowPosture ? "检测到低姿态" : "高度疑似跌倒"), phase === "analyzing" ? "DEMO analyzing" : (lowPosture ? "LOW POSTURE / 0.91" : "FALL / 0.94"), phase === "analyzing" ? "active" : "warning");
  setDemoCard("cardQwen", "summaryQwenValue", "summaryQwenMeta", phase === "reviewing" ? "复核中" : (phase === "completed" ? (lowPosture ? "已排除跌倒" : "确认真实跌倒") : "待机"), phase === "completed" ? (lowPosture ? "intentional_low_posture" : "confirmed_fall") : (phase === "reviewing" ? "qwen reviewing" : "qwen3.5:4b"), phase === "completed" ? (lowPosture ? "success" : "danger") : (phase === "reviewing" ? "warning" : "idle"));
  setDemoCard("cardEvent", "summaryEventValue", "summaryEventMeta", phase === "completed" ? (lowPosture ? "已排除跌倒" : "确认跌倒") : (phase === "analyzing" ? "模拟事件进入" : (lowPosture ? "疑似低姿态" : "疑似跌倒")), presentationShortId(state.demoFall.incidentId), phase === "completed" ? (lowPosture ? "success" : "danger") : "warning");
  setDemoCard("cardAlarm", "summaryAlarmValue", "summaryAlarmMeta", phase === "completed" ? (lowPosture ? "无需告警" : "模拟联动") : "未投递", "DEMO，不发送真实告警", phase === "completed" ? (lowPosture ? "success" : "warning") : "idle");
}

function setPipelineDemoState(phase) {
  const lowPosture = state.demoFall.scenario === "low_posture";
  setElementState("pipeVideo", "active");
  setElementState("pipeBinary", phase === "analyzing" ? "active" : "warning");
  setElementState("pipeQwen", phase === "reviewing" ? "warning" : (phase === "completed" ? (lowPosture ? "success" : "danger") : "idle"));
  setElementState("pipeJson", phase === "completed" ? "success" : "idle");
  setElementState("pipeAlarm", phase === "completed" ? (lowPosture ? "success" : "warning") : "idle");
  setPipelineAlarmLabel(phase === "completed" && lowPosture ? "无需告警" : "Alarm API");
}

function buildDemoPresentation() {
  return state.demoFall.scenario === "low_posture"
    ? buildDemoLowPosturePresentation()
    : buildDemoFallPresentation();
}

function buildDemoFallPresentation() {
  const incidentId = state.demoFall.incidentId || `demo-fall-${currentCameraId()}-${Date.now().toString(16)}`;
  const qwenAnalysis = {
    incident_id: incidentId,
    analysis_status: "completed",
    fall_verdict: "confirmed_fall",
    posture: "人物由站立姿态突然失衡并急速向地面倾倒，呈现非自主倒地过程。",
    movement_level: "unknown",
    attempt_to_stand: "unknown",
    persistent_ground_state: "unknown",
    visibility: "unknown",
    occlusion: "unknown",
    scene_risks: [],
    possible_help_gesture: "unknown",
    summary: "画面显示人物从站立位置突然失去平衡，身体快速下坠至地面，动作具有明显的失控特征，符合真实跌倒判定标准。",
    review_points: [
      "建议人工复核事件关键帧。",
    ],
  };
  return {
    event_id: incidentId,
    camera_id: currentCameraId(),
    source: "demo",
    is_demo: true,
    analysis_status: "completed",
    fall_verdict: "confirmed_fall",
    fall_label_zh: "真实跌倒",
    is_real_fall: true,
    confidence: 0.94,
    time_description_zh: qwenAnalysis.summary,
    qwen_analysis: qwenAnalysis,
    generated_at: new Date().toISOString(),
  };
}

function buildDemoLowPosturePresentation() {
  const incidentId = state.demoFall.incidentId || `demo-low-posture-${currentCameraId()}-${Date.now().toString(16)}`;
  const qwenAnalysis = {
    incident_id: incidentId,
    analysis_status: "completed",
    fall_verdict: "intentional_low_posture",
    posture: "人物从站立姿态主动受控地坐下并阅读。",
    movement_level: "unknown",
    attempt_to_stand: "unknown",
    persistent_ground_state: "observed",
    visibility: "unknown",
    occlusion: "unknown",
    scene_risks: [],
    possible_help_gesture: "unknown",
    summary: "连续画面显示人物主动弯腰、屈膝受控坐在地垫上，随后盘腿阅读文件，未见失衡或失控倒地过程。",
    review_points: [],
    confidence: 0.94,
    latency_ms: 5686.6,
  };
  return {
    event_id: incidentId,
    camera_id: currentCameraId(),
    source: "demo",
    is_demo: true,
    analysis_status: "completed",
    fall_verdict: "intentional_low_posture",
    fall_label_zh: "非真实跌倒",
    is_real_fall: false,
    confidence: 0.94,
    time_description_zh: qwenAnalysis.summary,
    qwen_analysis: qwenAnalysis,
    generated_at: new Date().toISOString(),
  };
}

function demoSessionSnapshot() {
  const elapsedSeconds = state.demoFall.startedAt ? Math.max(0, (Date.now() - state.demoFall.startedAt) / 1000) : 0;
  return {
    state: "RUNNING",
    elapsed_seconds: elapsedSeconds,
    components: { qwen: { active_count: state.demoFall.phase === "reviewing" ? 1 : 0 } },
  };
}

function updateDemoButtons() {
  const fallButton = $("demoFallBtn");
  const lowPostureButton = $("demoLowPostureBtn");
  const fallActive = state.demoFall.active && state.demoFall.scenario === "fall";
  const lowPostureActive = state.demoFall.active && state.demoFall.scenario === "low_posture";
  if (fallButton) {
    fallButton.dataset.active = fallActive ? "1" : "0";
    fallButton.innerHTML = `${fallActive ? "重置跌倒模拟" : "DEMO 模拟跌倒"} <kbd>F9</kbd>`;
  }
  if (lowPostureButton) {
    lowPostureButton.dataset.active = lowPostureActive ? "1" : "0";
    lowPostureButton.innerHTML = `${lowPostureActive ? "重置低姿态模拟" : "DEMO 模拟低姿态"} <kbd>F10</kbd>`;
  }
}

function setPipelineAlarmLabel(label) {
  const target = document.querySelector("#pipeAlarm strong");
  if (target) {
    target.textContent = label;
  }
}

function setDemoCard(cardId, valueId, metaId, value, meta, cardState) {
  setElementState(cardId, cardState);
  setText(valueId, value);
  setText(metaId, meta);
}

function setModelSentinel(nodeId, stateName, titleId, metaId, title, meta) {
  setElementState(nodeId, stateName);
  setText(titleId, title);
  setText(metaId, meta);
}

function setElementState(id, stateName) {
  const element = $(id);
  if (element) {
    element.dataset.state = stateName || "idle";
  }
}

function setViewerAlertState(stateName, phaseName = "") {
  const viewer = document.querySelector(".viewer");
  if (viewer) {
    viewer.dataset.alertState = stateName || "idle";
    viewer.dataset.alertPhase = phaseName || "";
  }
  const alertCopy = phaseName === "confirmed"
    ? ["确认真实跌倒", "千问复核完成，请立即关注现场"]
    : phaseName === "reviewing"
      ? ["疑似跌倒 · 千问复核中", "大模型正在分析关键画面"]
      : ["检测到疑似跌倒", "二分类模型已触发，正在等待千问复核"];
  setText("viewerAlertTitle", alertCopy[0]);
  setText("viewerAlertMeta", alertCopy[1]);
}

function appendDemoTrendPoint(phase) {
  const probability = phase === "analyzing" ? 0.28 : (phase === "suspected" ? 0.94 : (phase === "reviewing" ? 0.94 : 0.96));
  appendVisualHistory({ binaryProbability: probability, videoFps: null, frameAge: null });
  setText("trendBinaryValue", probability.toFixed(2));
  renderLineTrend("binaryProbabilityTrend", state.visualHistory.binaryProbability, { min: 0, max: 1, color: "rgba(255, 202, 69, 0.96)" });
}

function hasRealActiveEventSignal() {
  const decision = targetFallDecision(state.lastResult) || {};
  const eventId = normalizedIncidentId(decision.incident_id);
  return Boolean(
    eventId
    && decision.event_created === true
    && !String(eventId).startsWith("demo-fall-")
    && !isAcknowledgedFallEventId(eventId),
  );
}

function sessionStateLabel(stateName) {
  const labels = {
    IDLE: "未开始",
    STARTING: "正在启动",
    RUNNING: "完整检测中",
    STOPPING: "正在保存",
    COMPLETED: "本次检测已保存",
    FAILED: "启动失败",
  };
  return labels[stateName] || stateName;
}

function sessionSaveState(session) {
  const stateName = String(session?.state || "IDLE").toUpperCase();
  if (stateName === "STOPPING") {
    return `等待归档：${session?.archive?.qwen_unresolved_count || 0} 个复核`;
  }
  if (stateName === "COMPLETED") {
    return "已保存到 Session 文件夹";
  }
  if (stateName === "FAILED") {
    return session?.failure_reason || "启动失败";
  }
  if (stateName === "RUNNING") {
    return "记录中";
  }
  return "等待开始";
}

function presentationStatusText(presentation, qwenActive) {
  if (qwenActive) return "千问复核中";
  if (!presentation?.event_id) return "持续监测";
  const status = String(presentation.analysis_status || "").toLowerCase();
  if (status === "completed") return "复核完成";
  if (status === "timeout") return "复核超时";
  if (status === "failed" || status === "parse_failed") return "复核失败";
  return status || "已生成";
}

function targetFallDecision(result) {
  const objects = result?.objects || [];
  const target = objects.find((item) => item?.is_target === true) || objects[0];
  return target?.fall_decision || null;
}

function presentationShortId(value) {
  const text = String(value || "--");
  return text.length > 22 ? `${text.slice(0, 10)}...${text.slice(-8)}` : text;
}

function readDurationInputs() {
  const hours = clampInteger($("testHours")?.value, 0, 24);
  const minutes = clampInteger($("testMinutes")?.value, 0, 59);
  const seconds = clampInteger($("testSeconds")?.value, 0, 59);
  return {
    totalSeconds: hours * 3600 + minutes * 60 + seconds,
    payload: { hours, minutes, seconds },
  };
}

function writeDurationInputs(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if ($("testHours")) $("testHours").value = String(hours);
  if ($("testMinutes")) $("testMinutes").value = String(minutes);
  if ($("testSeconds")) $("testSeconds").value = String(seconds);
}

function setTestInputsDisabled(disabled) {
  for (const id of ["testHours", "testMinutes", "testSeconds"]) {
    const input = $(id);
    if (input) {
      input.disabled = disabled;
    }
  }
}

function clampInteger(value, min, max) {
  const numeric = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(numeric)) {
    return min;
  }
  return Math.min(max, Math.max(min, numeric));
}

function setStateText(id, value, stateName) {
  const element = $(id);
  if (!element) {
    return;
  }
  element.textContent = value;
  element.dataset.state = stateName;
}

function setControlResult(id, message, kind) {
  const element = $(id);
  if (!element) {
    return;
  }
  element.textContent = message;
  element.dataset.state = kind;
}

function formatHms(totalSeconds) {
  const safe = Math.max(0, Number(totalSeconds) || 0);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = Math.floor(safe % 60);
  return [hours, minutes, seconds].map((item) => String(item).padStart(2, "0")).join(":");
}

function formatMs(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.max(0, Math.round(number))}ms` : "-";
}

function formatPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.max(0, Math.round(number))}%` : "-";
}

function formatGpuMemory(used, total) {
  const usedNumber = Number(used);
  const totalNumber = Number(total);
  if (!Number.isFinite(usedNumber)) {
    return "-";
  }
  if (!Number.isFinite(totalNumber) || totalNumber <= 0) {
    return `${Math.round(usedNumber)}MB`;
  }
  return `${Math.round(usedNumber)} / ${Math.round(totalNumber)}MB`;
}

function formatQueueDepth(depth, dropped) {
  const numericDepth = Number(depth);
  const numericDropped = Number(dropped);
  if (!Number.isFinite(numericDepth)) {
    return "-";
  }
  const base = `${Math.max(0, Math.round(numericDepth))}`;
  return Number.isFinite(numericDropped) && numericDropped > 0 ? `${base} / drop ${Math.round(numericDropped)}` : base;
}

function maybeReconnectForDisplaySource(status) {
  const display = status.display_source_current || status.display_source || "single";
  state.lastDisplaySource = display;
  if (!state.userConnected || state.autoReconnect.connecting) {
    return;
  }
  if (!state.connectedDisplaySource) {
    state.connectedDisplaySource = display;
    return;
  }
  if (state.connectedDisplaySource !== display) {
    if (display === "analysis") {
      debugState.counters.displayFallbackSwitches += 1;
    }
    state.connectedDisplaySource = display;
    scheduleWebRTCReconnect(`显示流切换到 ${display}`);
  }
}

function streamStateLabel(streamState) {
  const labels = {
    disconnected: "未连接",
    connecting: "正在连接",
    connected: "画面正常",
    stale: "画面停滞 / 正在恢复",
    reconnecting: "正在重连",
  };
  return labels[streamState] || streamState;
}

function updateTargetDetails(result) {
  const objects = result?.objects || [];
  const target = objects.find((item) => item.is_target === true) || objects[0];
  if (!target) {
    $("targetTrackId").textContent = "-";
    $("targetFlag").textContent = "-";
    $("targetPerson").textContent = "-";
    $("trackingState").textContent = "-";
    $("identityState").textContent = "-";
    $("behaviorState").textContent = "-";
    $("poseState").textContent = "-";
    $("poseState").className = "";
    updateFallPreview(null);
    return;
  }

  const personLabel = target.person_id
    ? `${target.person_id}${target.person_name ? ` / ${target.person_name}` : ""}`
    : "-";
  const behavior = target.behavior;
  const behaviorLabel = behavior
    ? `${localizeBehaviorState(behavior.behavior_state)} (${formatScore(behavior.behavior_confidence)})`
    : "-";

  $("targetTrackId").textContent = target.track_id == null ? "-" : `#${target.track_id}`;
  $("targetFlag").textContent = target.is_target ? "是" : "否";
  $("targetPerson").textContent = personLabel;
  $("trackingState").textContent = localizeTrackingState(target.identity_state);
  $("identityState").textContent = localizeIdentityState(target);
  $("behaviorState").textContent = behaviorLabel;
  updatePoseState(target);
  updateFallPreview(target);
}

function updatePoseState(target) {
  const element = $("poseState");
  if (!element) {
    return;
  }
  element.textContent = describePoseState(target);
  element.className = poseStateClass(target);
}

function describePoseState(target) {
  if (!target) {
    return "-";
  }
  if (target.overlay_pose_disabled || isPoseDisabledPlaceholder(target.pose)) {
    return "pose placeholder";
  }
  const pose = target.pose;
  const ageMs = poseAgeFromObject(target);
  if (target.overlay_pose_stale) {
    return ageMs == null ? "pose stale" : `pose stale (${ageMs}ms)`;
  }
  if (pose && hasPoseKeypoints(pose)) {
    return ageMs == null ? "pose ready" : `pose ready (${ageMs}ms)`;
  }
  if (target.overlay_pose_rejected_reason) {
    return target.overlay_pose_rejected_reason === "pose_stale"
      ? "pose stale"
      : `pose filtered (${target.overlay_pose_rejected_reason})`;
  }
  return "waiting pose";
}

function poseStateClass(target) {
  if (!target) {
    return "";
  }
  if (target.overlay_pose_disabled || isPoseDisabledPlaceholder(target.pose)) {
    return "risk-cooldown";
  }
  if (target.overlay_pose_stale || target.overlay_pose_rejected_reason === "pose_stale") {
    return "risk-cooldown";
  }
  if (target.pose && hasPoseKeypoints(target.pose)) {
    return "risk-low";
  }
  return "";
}

function updateFallPreview(target) {
  const temporal = target?.temporal;
  const decision = target?.fall_decision;
  const alarm = target?.alarm_preview;
  const stateName = decision?.fall_state || "-";
  const risk = alarm?.risk_level || decision?.risk_level || "-";
  const probability = temporal?.fall_probability;
  const countdown = alarm?.countdown_ms ?? decision?.countdown_ms;
  const shadowProbability = temporal?.shadow?.fall_probability;
  const windowSize = temporal?.window_size;
  const windowReady = temporal?.window_ready;
  const keyframeStatus = decision?.keyframe_status || target?.keyframe_status;
  const vlmStatus = decision?.vlm_status || target?.vlm_status || "-";
  const pipeline = decision?.pipeline || state.lastResult?.detector?.pipeline || state.lastStatus?.workers?.post_fall_v2_runtime?.pipeline_mode;
  const binaryLabel = decision?.binary_label || state.lastResult?.detector?.binary_label;

  $("fallState").textContent = localizeFallState(stateName);
  $("riskLevel").textContent = localizeRiskLevel(risk);
  $("fallProbability").textContent = formatProbability(probability);
  $("fallCountdown").textContent = formatCountdown(countdown);
  $("shadowProbability").textContent = formatProbability(shadowProbability);
  $("temporalWindow").textContent = windowSize == null ? "-" : `${windowSize}${windowReady ? " / ready" : " / warmup"}`;
  $("keyframeStatus").textContent = localizeKeyframeStatus(keyframeStatus);
  $("vlmStatus").textContent = localizeVlmStatus(vlmStatus);
  $("pipelineMode").textContent = localizePipeline(pipeline);
  $("binaryLabel").textContent = localizeBinaryLabel(binaryLabel);
  $("incidentId").textContent = decision?.incident_id || "-";
  $("vlmSummary").textContent = decision?.vlm_summary || "-";
  $("fallState").className = fallStateClass(target);
  $("riskLevel").className = riskClass(risk);
}

function updateAlarmIndicatorFromResult(result) {
  if (synchronizeJudgmentReset()) {
    forceIdleAlarmIndicator();
    return;
  }
  const signal = alarmIndicatorSignalFromResult(result);
  if (!signal) {
    return;
  }
  if (signal.state === "candidate") {
    setAlarmIndicatorCandidate(signal.eventId);
    return;
  }
  setAlarmIndicatorTerminal(signal.eventId, signal.state);
}

function alarmIndicatorSignalFromResult(result) {
  const objects = result?.objects || [];
  for (const object of objects) {
    const decision = object?.fall_decision || {};
    const eventId = normalizedIncidentId(decision.incident_id);
    if (isAcknowledgedFallEventId(eventId)) {
      continue;
    }
    if (eventId && decision.event_created === true) {
      return { state: "candidate", eventId };
    }
  }

  const currentEventId = state.alarmIndicator.currentEventId;
  if (!currentEventId || isAcknowledgedFallEventId(currentEventId)) {
    return null;
  }
  for (const object of objects) {
    const decision = object?.fall_decision || {};
    const eventId = normalizedIncidentId(decision.incident_id);
    if (eventId !== currentEventId) {
      continue;
    }
    if (isFinalAlarmSignal(object)) {
      return { state: "confirmed", eventId };
    }
    if (isFinishedNonAlertSignal(object)) {
      return { state: "dismissed", eventId };
    }
  }
  return null;
}

function setAlarmIndicatorCandidate(eventId) {
  if (!eventId) {
    return;
  }
  clearAlarmIndicatorResetTimer();
  state.alarmIndicator.currentEventId = eventId;
  state.alarmIndicator.terminalStates.delete(eventId);
  renderAlarmIndicator("candidate");
}

function setAlarmIndicatorTerminal(eventId, terminalState) {
  if (!eventId || !["dismissed", "confirmed"].includes(terminalState)) {
    return;
  }
  if (state.alarmIndicator.currentEventId !== eventId) {
    return;
  }
  const previousState = state.alarmIndicator.terminalStates.get(eventId);
  if (previousState === "confirmed" || previousState === terminalState) {
    return;
  }
  clearAlarmIndicatorResetTimer();
  state.alarmIndicator.terminalStates.set(eventId, terminalState);
  renderAlarmIndicator(terminalState);
  state.alarmIndicator.resetTimer = window.setTimeout(() => {
    if (state.alarmIndicator.currentEventId === eventId) {
      renderAlarmIndicator("idle");
    }
    state.alarmIndicator.resetTimer = null;
  }, ALARM_INDICATOR_RESET_MS);
}

function forceIdleAlarmIndicator() {
  clearAlarmIndicatorResetTimer();
  state.alarmIndicator.currentEventId = null;
  state.alarmIndicator.terminalStates.clear();
  renderAlarmIndicator("idle");
}

function clearAlarmIndicatorResetTimer() {
  if (state.alarmIndicator.resetTimer) {
    window.clearTimeout(state.alarmIndicator.resetTimer);
    state.alarmIndicator.resetTimer = null;
  }
}

function renderAlarmIndicator(indicatorState) {
  const element = $("alarmIndicator");
  if (!element) {
    return;
  }
  syncAlarmIndicatorPosition();
  const nextState = ALARM_INDICATOR_TITLES[indicatorState] ? indicatorState : "idle";
  const title = ALARM_INDICATOR_TITLES[nextState];
  element.dataset.state = nextState;
  element.title = title;
  element.setAttribute("aria-label", `最终告警测试指示灯：${title}`);
}

function syncAlarmIndicatorPosition() {
  const element = $("alarmIndicator");
  const viewer = document.querySelector(".viewer");
  if (!element || !viewer) {
    return;
  }
  const viewerRect = viewer.getBoundingClientRect();
  const visibleBottom = Math.min(viewerRect.bottom, window.innerHeight || document.documentElement.clientHeight || viewerRect.bottom);
  const visibleTop = Math.max(viewerRect.top, 0);
  const lampSize = element.offsetWidth || 22;
  const top = Math.max(visibleTop + ALARM_INDICATOR_MARGIN_PX, visibleBottom - ALARM_INDICATOR_MARGIN_PX - lampSize);
  const left = viewerRect.left + ALARM_INDICATOR_MARGIN_PX;
  element.style.setProperty("--alarm-indicator-left", `${Math.round(left)}px`);
  element.style.setProperty("--alarm-indicator-top", `${Math.round(top)}px`);
}

function normalizedIncidentId(value) {
  const text = String(value || "").trim();
  return text && text !== "-" ? text : null;
}

function normalizedSafetyOutcome(object) {
  const decision = object?.fall_decision || {};
  const alarm = object?.alarm_preview || {};
  const outcome = (
    decision.safety_outcome
    || decision.safety_decision?.outcome
    || alarm.safety_outcome
    || ""
  );
  return String(outcome).trim().toLowerCase();
}

function normalizedVlmStatus(object) {
  const decision = object?.fall_decision || {};
  return String(decision.vlm_status || object?.vlm_status || "").trim().toLowerCase();
}

function isFinalAlarmSignal(object) {
  return normalizedSafetyOutcome(object) === "alert";
}

function isFinishedNonAlertSignal(object) {
  const outcome = normalizedSafetyOutcome(object);
  if (outcome === "alert") {
    return false;
  }
  if (outcome === "dismiss") {
    return true;
  }
  return ["completed", "failed", "timeout", "parse_failed"].includes(normalizedVlmStatus(object));
}

function fallStateClass(target) {
  return riskClass(displayRiskForFallState(target?.fall_decision?.fall_state, target?.alarm_preview?.confirmed, target?.alarm_preview?.risk_level || target?.fall_decision?.risk_level));
}

function displayRiskForFallState(fallState, alarmConfirmed, rawRisk) {
  if (alarmConfirmed === true || fallState === "fallen_confirmed") {
    return "critical";
  }
  if (fallState === "normal") {
    return "low";
  }
  if (fallState === "unstable") {
    return "medium";
  }
  if (fallState === "falling" || fallState === "fallen_candidate") {
    return rawRisk === "medium" ? "medium" : "high";
  }
  if (fallState === "cooldown") {
    return "cooldown";
  }
  return rawRisk || "low";
}

function updateMetricPanel(status) {
  const detection = (status.detection || [])[0];
  const detectionFps = detection?.detection_fps ?? null;
  const trackingFps = status.pipeline?.tracking_worker_fps ?? status.tracking?.tracking_fps ?? null;
  const poseFps = status.pose?.pose_fps ?? null;
  const publishFps = status.pipeline?.result_publish_fps ?? null;
  const display = getDisplayStreamStatus(status);
  $("detectionFps").textContent = formatFps(detectionFps);
  $("trackingFps").textContent = formatFps(trackingFps);
  $("poseFps").textContent = formatFps(poseFps);
  $("aiFps").textContent = `D:${formatFps(detectionFps)} T:${formatFps(trackingFps)} P:${formatFps(poseFps)} R:${formatFps(publishFps)}`;
  $("displayBackendFps").textContent = display
    ? `mjpeg ${formatFps(display.display_mjpeg_served_fps)} / all ${formatFps(display.display_served_fps)} / encoded ${formatFps(display.display_encode_fps)}`
    : "-";
  $("displayEncodeMs").textContent = display ? `${formatMs(display.encode_ms)} / max ${formatMs(display.encode_ms_max)}` : "-";
  $("displayCacheInfo").textContent = display ? `encoded ${display.encoded_frames ?? 0} / hit ${display.cache_hits ?? 0}` : "-";
  updateWsFps();
  updateOverlayAge();
  updatePeerDebugState();
  const reporter = status.fall_event_reporter || {};
  const latest = status.latest_result || {};
  $("reporterStatus").textContent = reporter.enabled
    ? `${reporter.last_post_status || "ready"}${reporter.last_incident_id ? ` / ${reporter.last_incident_id}` : ""}`
    : "disabled";
  if (!$("targetTrackId").textContent || $("targetTrackId").textContent === "-") {
    $("targetTrackId").textContent = latest.track_id == null ? "-" : `#${latest.track_id}`;
  }
}

function getDisplayStreamStatus(status, cameraId = currentCameraId()) {
  const cameras = status?.display_stream?.cameras || {};
  if (cameraId && cameras[cameraId]) {
    return cameras[cameraId];
  }
  return Object.values(cameras)[0] || null;
}

function attachVideoFrameLoop() {
  const video = $("video");
  if (!video) {
    return;
  }
  stopOverlayLoop();
  if (!ANNOTATED_OVERLAY_ENABLED) {
    clearOverlayCanvas();
    return;
  }
  if (typeof video.requestVideoFrameCallback !== "function") {
    startOverlayFallbackLoop(video);
    return;
  }
  state.videoFrameCallbackActive = true;
  const loop = (_now, metadata) => {
    if (!state.videoFrameCallbackActive) {
      return;
    }
    const result = consumePendingOverlayResult();
    if (result) {
      drawOverlay(video, result, metadata);
      debugState.counters.overlayFramesDrawn += 1;
      updateOverlayFps();
    }
    video.requestVideoFrameCallback(loop);
  };
  video.requestVideoFrameCallback(loop);
}

function stopOverlayLoop() {
  state.videoFrameCallbackActive = false;
  if (state.overlayFallbackTimer) {
    clearInterval(state.overlayFallbackTimer);
    state.overlayFallbackTimer = null;
  }
}

function startOverlayFallbackLoop(video) {
  if (!ANNOTATED_OVERLAY_ENABLED) {
    clearOverlayCanvas();
    return;
  }
  if (state.overlayFallbackTimer) {
    return;
  }
  const drawLatest = () => {
    const result = consumePendingOverlayResult();
    if (!result) {
      return;
    }
    if (!video || video.readyState < 2 || video.paused || !video.videoWidth || !video.videoHeight) {
      return;
    }
    drawOverlay(video, result, {
      mediaTime: video.currentTime,
      presentedFrames: debugState.counters.overlayFramesDrawn + 1,
    });
    debugState.counters.overlayFramesDrawn += 1;
    updateOverlayFps();
  };
  state.overlayFallbackTimer = setInterval(drawLatest, 100);
}

function consumePendingOverlayResult() {
  const result = state.pendingResult || state.lastResult;
  state.pendingResult = null;
  if (!result) {
    return null;
  }
  if (isResultExpired(result)) {
    expireOverlayResult();
    return null;
  }
  return result;
}

function isResultExpired(result) {
  if (!result) {
    return false;
  }
  const receivedAt = Number(result.overlay_received_at);
  if (!Number.isFinite(receivedAt)) {
    return false;
  }
  return Date.now() - receivedAt > RESULT_OVERLAY_TTL_MS;
}

function expireOverlayResult() {
  state.lastResult = null;
  state.pendingResult = null;
  state.poseCache.clear();
  clearOverlayCanvas();
  updateTargetDetails(null);
  updateOverlayAge();
}

function clearOverlayCanvas() {
  const canvas = $("overlay");
  const ctx = canvas?.getContext("2d");
  if (ctx) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

function updateWsFps() {
  const target = $("wsFps");
  if (!target) {
    return;
  }
  const samples = debugState.wsSamples;
  if (samples.length < 2) {
    target.textContent = "warming up";
    return;
  }
  const first = samples[0];
  const last = samples.at(-1);
  const elapsedSec = (last.at - first.at) / 1000;
  if (elapsedSec <= 0) {
    target.textContent = "-";
    return;
  }
  target.textContent = `${((samples.length - 1) / elapsedSec).toFixed(1)}`;
}

function updateOverlayFps() {
  const target = $("overlayFps");
  if (!target) {
    return;
  }
  const now = performance.now();
  const frames = debugState.counters.overlayFramesDrawn;
  if (state.overlayFps.lastAt == null) {
    state.overlayFps.lastAt = now;
    state.overlayFps.lastFrames = frames;
    target.textContent = "warming up";
    return;
  }
  const elapsedSec = (now - state.overlayFps.lastAt) / 1000;
  const frameDelta = frames - state.overlayFps.lastFrames;
  if (elapsedSec >= 1) {
    target.textContent = `${(frameDelta / elapsedSec).toFixed(1)}`;
    state.overlayFps.lastAt = now;
    state.overlayFps.lastFrames = frames;
  }
}

function updateOverlayAge() {
  const target = $("overlayAge");
  if (!target) {
    return;
  }
  const timestamp = state.lastResult?.timestamp;
  if (!timestamp) {
    target.textContent = "-";
    return;
  }
  const ageMs = Date.now() - Date.parse(timestamp);
  target.textContent = Number.isFinite(ageMs) ? `${Math.max(0, Math.round(ageMs))}ms` : "-";
}

function formatFps(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toFixed(1);
}

function formatScore(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toFixed(2);
}

function probabilityText(label, value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${label} ${number.toFixed(2)}` : label;
}

function formatProbability(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "-";
  }
  return `${Math.round(Number(value) * 100)}%`;
}

function formatCountdown(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "-";
  }
  return `${(Number(value) / 1000).toFixed(1)}秒`;
}

function localizeFallState(value) {
  return FALL_STATE_LABELS[value] || value || "-";
}

function localizePipeline(value) {
  return value === "post_fall_v2" ? "Post-Fall V2" : (value || "-");
}

function localizeBinaryLabel(value) {
  const labels = { NON_FALL: "正常", FALL: "跌倒", UNKNOWN: "未知" };
  return labels[value] || value || "-";
}

function localizeKeyframeStatus(value) {
  const labels = {
    collecting: "正在采集关键帧",
    ready: "关键帧已就绪",
    degraded: "关键帧已降级",
    expired: "关键帧已过期",
    cancelled: "关键帧已取消",
  };
  return labels[value] || value || "-";
}

function localizeVlmStatus(value) {
  const labels = {
    disabled: "未启用",
    pending: "等待关键帧",
    collecting_keyframes: "采集关键帧中",
    running: "千问分析中",
    completed: "千问分析完成",
    failed: "千问分析失败",
    timeout: "千问分析超时",
    parse_failed: "千问结果解析失败",
  };
  return labels[value] || value || "-";
}

function localizeRiskLevel(value) {
  return RISK_LEVEL_LABELS[value] || value || "-";
}

function localizeBehaviorState(value) {
  return BEHAVIOR_LABELS[value] || value || "-";
}

function localizeTrackingState(value) {
  return TRACKING_STATE_LABELS[value] || value || "-";
}

function localizeIdentityState(target) {
  if (!target?.person_id) {
    return IDENTITY_STATE_LABELS.unbound;
  }
  return IDENTITY_STATE_LABELS.recognized;
}

function riskClass(risk) {
  return RISK_LEVEL_LABELS[risk] ? `risk-${risk}` : "";
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch (_) {
    return { status: response.status, message: response.statusText };
  }
}

function pushLimited(items, item, limit = 600) {
  items.push(item);
  if (items.length > limit) {
    items.splice(0, items.length - limit);
  }
}

function summarizeSamples(samples) {
  if (!samples.length) {
    return { count: 0 };
  }
  const elapsedValues = samples
    .map((item) => item.elapsedMs)
    .filter((value) => Number.isFinite(value));
  return {
    count: samples.length,
    avgElapsedMs: average(elapsedValues),
    maxElapsedMs: max(elapsedValues),
    firstAt: samples[0].at,
    lastAt: samples.at(-1).at,
  };
}

function summarizeRtc(samples) {
  if (!samples.length) {
    return { count: 0 };
  }
  const first = samples[0];
  const last = samples.at(-1);
  return {
    count: samples.length,
    framesDecodedDelta: diff(last.framesDecoded, first.framesDecoded),
    framesDroppedDelta: diff(last.framesDropped, first.framesDropped),
    framesReceivedDelta: diff(last.framesReceived, first.framesReceived),
    packetsLostDelta: diff(last.packetsLost, first.packetsLost),
    jitterLatest: last.jitter,
    freezeCountLatest: last.freezeCount,
    totalFreezesDurationLatest: last.totalFreezesDuration,
  };
}

function summarizeVideo(samples) {
  if (!samples.length) {
    return { count: 0 };
  }
  const first = samples[0];
  const last = samples.at(-1);
  return {
    ...summarizeSamples(samples),
    currentTimeDelta: round(diff(last.currentTime, first.currentTime)),
    totalVideoFramesDelta: diff(last.totalVideoFrames, first.totalVideoFrames),
    droppedVideoFramesDelta: diff(last.droppedVideoFrames, first.droppedVideoFrames),
    droppedVideoFramesLatest: last.droppedVideoFrames,
    totalVideoFramesLatest: last.totalVideoFrames,
    readyStateLatest: last.readyState,
    pausedLatest: last.paused,
  };
}

function average(values) {
  if (!values.length) {
    return null;
  }
  return round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

function max(values) {
  if (!values.length) {
    return null;
  }
  return round(Math.max(...values));
}

function diff(last, first) {
  if (!Number.isFinite(last) || !Number.isFinite(first)) {
    return null;
  }
  return round(last - first);
}

function round(value) {
  return Math.round(Number(value) * 100) / 100;
}

function pushDebugError(kind, payload) {
  pushLimited(debugState.errors, {
    at: Date.now(),
    kind,
    message: String(payload?.message || payload?.reason || payload || ""),
    source: payload?.filename || payload?.source || null,
    line: payload?.lineno || null,
    col: payload?.colno || null,
  }, 100);
}

function readFreezeDomSnapshot() {
  const video = $("video");
  const quality = typeof video?.getVideoPlaybackQuality === "function"
    ? video.getVideoPlaybackQuality()
    : null;
  return {
    href: window.location.href,
    visibilityState: document.visibilityState,
    webrtcState: $("webrtcState")?.textContent || null,
    wsState: $("wsState")?.textContent || null,
    videoFps: $("videoFps")?.textContent || null,
    wsFps: $("wsFps")?.textContent || null,
    overlayFps: $("overlayFps")?.textContent || null,
    overlayAge: $("overlayAge")?.textContent || null,
    videoFrames: $("videoFrames")?.textContent || null,
    videoReadyState: $("videoReadyState")?.textContent || null,
    videoSize: $("videoSize")?.textContent || null,
    pcExists: $("pcExists")?.textContent || null,
    iceConnectionState: $("iceConnectionState")?.textContent || null,
    signalingState: $("signalingState")?.textContent || null,
    srcObjectTracks: $("srcObjectTracks")?.textContent || null,
    readyState: video?.readyState ?? null,
    paused: video?.paused ?? null,
    currentTime: video?.currentTime ?? null,
    totalVideoFrames: quality?.totalVideoFrames ?? null,
    droppedVideoFrames: quality?.droppedVideoFrames ?? null,
    frameFallbackVisible: state.frameFallback.visible,
    frameFallbackAgeMs: state.frameFallback.lastOkAt ? Date.now() - state.frameFallback.lastOkAt : null,
    frameFallbackSize: state.frameFallback.naturalWidth && state.frameFallback.naturalHeight
      ? `${state.frameFallback.naturalWidth}x${state.frameFallback.naturalHeight}`
      : null,
    videoLuma: Number.isFinite(state.videoPaint.lastLuma) ? Math.round(state.videoPaint.lastLuma) : null,
  };
}

function sampleVideoQuality() {
  const video = $("video");
  if (!video) {
    return;
  }
  const quality = typeof video.getVideoPlaybackQuality === "function"
    ? video.getVideoPlaybackQuality()
    : null;
  pushLimited(debugState.videoSamples, {
    at: Date.now(),
    currentTime: video.currentTime,
    readyState: video.readyState,
    paused: video.paused,
    totalVideoFrames: quality?.totalVideoFrames ?? null,
    droppedVideoFrames: quality?.droppedVideoFrames ?? null,
    corruptedVideoFrames: quality?.corruptedVideoFrames ?? null,
  });
  noteVideoProgress(quality);
  sampleVideoPaint(video);
  updateVideoFps(quality);
  renderDashboard();
  updateFrameFallbackVisibility();
}

function updateVideoFps(quality) {
  const target = $("videoFps");
  if (!target) {
    return;
  }
  if (state.pc?.connectionState !== "connected") {
    target.textContent = "--";
    return;
  }
  if (!quality || !Number.isFinite(quality.totalVideoFrames)) {
    target.textContent = "unsupported";
    return;
  }
  const now = performance.now();
  const totalFrames = Number(quality.totalVideoFrames);
  const droppedFrames = Number(quality.droppedVideoFrames || 0);
  const previous = state.videoFps;
  if (
    previous.lastAt == null
    || previous.lastTotalFrames == null
    || previous.lastDroppedFrames == null
  ) {
    previous.lastAt = now;
    previous.lastTotalFrames = totalFrames;
    previous.lastDroppedFrames = droppedFrames;
    target.textContent = "warming up";
    return;
  }
  const elapsedSec = (now - previous.lastAt) / 1000;
  const frameDelta = totalFrames - previous.lastTotalFrames;
  const dropDelta = droppedFrames - previous.lastDroppedFrames;
  previous.lastAt = now;
  previous.lastTotalFrames = totalFrames;
  previous.lastDroppedFrames = droppedFrames;
  if (elapsedSec <= 0 || frameDelta < 0 || dropDelta < 0) {
    target.textContent = "-";
    return;
  }
  const fps = frameDelta / elapsedSec;
  previous.lastMeasuredFps = fps;
  previous.lastMeasuredAt = Date.now();
  target.textContent = `${fps.toFixed(1)} (drop ${Math.round(dropDelta)})`;
  const videoFrames = $("videoFrames");
  if (videoFrames) {
    videoFrames.textContent = `${Math.round(totalFrames)} / drop ${Math.round(droppedFrames)}`;
  }
  updatePeerDebugState();
}

async function sampleRtcStats() {
  const pc = state.pc;
  if (!pc || pc.connectionState === "closed") {
    return;
  }
  try {
    const stats = await pc.getStats();
    let sample = null;
    stats.forEach((report) => {
      if (report.type === "inbound-rtp" && (report.kind === "video" || report.mediaType === "video")) {
        sample = {
          at: Date.now(),
          framesDecoded: report.framesDecoded ?? null,
          framesDropped: report.framesDropped ?? null,
          framesReceived: report.framesReceived ?? null,
          packetsLost: report.packetsLost ?? null,
          jitter: report.jitter ?? null,
          freezeCount: report.freezeCount ?? null,
          totalFreezesDuration: report.totalFreezesDuration ?? null,
        };
      }
    });
    if (sample) {
      pushLimited(debugState.rtcSamples, sample);
    }
    updatePeerDebugState();
  } catch (_) {
    // Debug-only sampling must never affect the demo.
  }
}

function updatePeerDebugState() {
  const pc = state.pc;
  const video = $("video");
  const srcObject = video?.srcObject || null;
  const pcExists = $("pcExists");
  const iceConnectionState = $("iceConnectionState");
  const signalingState = $("signalingState");
  const iceGatheringState = $("iceGatheringState");
  const hasSrcObject = $("hasSrcObject");
  const srcObjectTracks = $("srcObjectTracks");
  const videoReadyState = $("videoReadyState");
  const videoSize = $("videoSize");
  if (!pcExists || !iceConnectionState || !signalingState || !iceGatheringState || !hasSrcObject || !srcObjectTracks || !videoReadyState || !videoSize) {
    return;
  }
  pcExists.textContent = pc ? "yes" : "no";
  iceConnectionState.textContent = pc?.iceConnectionState || "-";
  signalingState.textContent = pc?.signalingState || "-";
  iceGatheringState.textContent = pc?.iceGatheringState || "-";
  hasSrcObject.textContent = srcObject ? "yes" : "no";
  const tracks = srcObject?.getTracks?.() || [];
  srcObjectTracks.textContent = tracks.length
    ? tracks.map((track) => `${track.kind}:${track.readyState}${track.muted ? ':muted' : ''}`).join(", ")
    : "-";
  videoReadyState.textContent = video ? `${video.readyState}${state.lastPlayError ? ` / playErr` : ""}` : "-";
  videoSize.textContent = video && video.videoWidth > 0 && video.videoHeight > 0
    ? `${video.videoWidth}x${video.videoHeight}`
    : "-";
}

async function refreshEventStatus() {
  try {
    const response = await fetch(`${apiBase()}/events/status`);
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    const deliveryStatus = await readDeliveryStatusQuietly();
    if (deliveryStatus) {
      payload.event_delivery_enabled = deliveryStatus.event_delivery_enabled;
      payload.delivery_backend = deliveryStatus.delivery_backend;
      payload.delivery_mode = deliveryStatus.delivery_mode;
      payload.delivery_worker_enabled = deliveryStatus.delivery_worker_enabled;
      payload.delivery_worker_running = deliveryStatus.worker_running;
    }
    state.eventReview.status = payload;
    state.eventReview.latestRefreshMs = payload.event_pipeline_enabled
      ? EVENT_LATEST_REFRESH_MS
      : EVENT_LATEST_DISABLED_REFRESH_MS;
    renderEventHealth(payload, null);
    return payload;
  } catch (error) {
    state.eventReview.latestRefreshMs = EVENT_LATEST_DISABLED_REFRESH_MS;
    renderEventPanel(normalizeEventPayload({ enabled: false, event: null, error: `Event service unavailable: ${error}` }));
    warnEventApiOnce(error);
    return null;
  }
}

async function readDeliveryStatusQuietly() {
  try {
    const response = await fetch(`${apiBase()}/events/delivery/status`);
    const payload = await safeJson(response);
    return response.ok ? payload : null;
  } catch (_) {
    return null;
  }
}

async function refreshLatestEvent(cameraId, { force = false } = {}) {
  if (state.eventReview.selectedIncidentId && !force) {
    return;
  }
  const statusPayload = state.eventReview.status || await refreshEventStatus();
  if (!statusPayload) {
    return;
  }
  if (!statusPayload.event_pipeline_enabled && !force) {
    renderEventPanel(normalizeEventPayload({ enabled: false, event: null, status: statusPayload }));
    return;
  }
  try {
    const response = await fetch(`${apiBase()}/events/latest?camera_id=${encodeURIComponent(cameraId)}`);
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    payload.status = statusPayload;
    state.lastEvent = payload.event || null;
    renderEventPanel(normalizeEventPayload(payload));
  } catch (error) {
    renderEventPanel(normalizeEventPayload({ enabled: false, event: null, status: statusPayload, error: `Event detail unavailable: ${error}` }));
    warnEventApiOnce(error);
  }
}

async function refreshRecentEvents(cameraId) {
  const statusPayload = state.eventReview.status || await refreshEventStatus();
  if (!statusPayload || !statusPayload.event_pipeline_enabled) {
    state.eventReview.recentItems = [];
    renderRecentEvents([], "事件语义链路未启用");
    return;
  }
  try {
    const response = await fetch(`${apiBase()}/events/outbox?camera_id=${encodeURIComponent(cameraId)}&limit=5`);
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    const items = Array.isArray(payload.items) ? payload.items : [];
    state.eventReview.recentItems = items;
    renderRecentEvents(items, items.length ? null : "暂无事件");
  } catch (error) {
    renderRecentEvents([], "事件列表暂不可用");
    warnEventApiOnce(error);
  }
}

async function loadEventDetail(incidentId) {
  if (!incidentId) {
    return;
  }
  try {
    const response = await fetch(`${apiBase()}/events/${encodeURIComponent(incidentId)}`);
    const event = await safeJson(response);
    if (!response.ok) {
      throw new Error(event?.detail || `HTTP ${response.status}`);
    }
    state.eventReview.selectedIncidentId = incidentId;
    renderEventPanel(normalizeEventPayload({
      enabled: true,
      status: state.eventReview.status || { event_pipeline_enabled: true },
      event,
    }));
    renderRecentEvents(state.eventReview.recentItems, null);
  } catch (error) {
    renderEventPanel(normalizeEventPayload({
      enabled: false,
      status: state.eventReview.status,
      event: null,
      error: `Event detail unavailable: ${error}`,
    }));
    warnEventApiOnce(error);
  }
}

function renderRecentEvents(items, message) {
  const list = $("eventRecentList");
  if (!list) {
    return;
  }
  if (message) {
    list.replaceChildren(textNode(message));
    list.dataset.state = "empty";
    return;
  }
  list.dataset.state = "ready";
  list.replaceChildren(...items.map((item) => {
    const event = item.event || {};
    const incidentId = event.incident_id || item.incident_id || "";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "event-recent-item";
    if (incidentId && incidentId === state.eventReview.selectedIncidentId) {
      button.classList.add("selected");
    }
    button.addEventListener("click", () => loadEventDetail(incidentId));
    const title = document.createElement("strong");
    title.textContent = shortIncidentId(incidentId);
    const meta = document.createElement("span");
    meta.textContent = [
      event.event_type || "-",
      event.risk_level || "-",
      item.status || "-",
      formatEventTime(item.updated_at || event.trigger_timestamp),
    ].join(" / ");
    button.append(title, meta);
    return button;
  }));
}

function normalizeEventPayload(eventResponse) {
  const response = eventResponse || {};
  const status = response.status || state.eventReview.status || {};
  const event = response.event || null;
  const enabled = Boolean(response.enabled && status.event_pipeline_enabled);
  if (response.error) {
    return emptyNormalizedEvent("api_error", String(response.error), status);
  }
  if (!enabled) {
    return emptyNormalizedEvent("disabled", "事件语义链路未启用", status);
  }
  if (!event) {
    return emptyNormalizedEvent("no_event", "暂无事件归档", status);
  }
  const rawEvent = event.event || {};
  const trusted = event.trusted_result || {};
  const semantics = event.event_semantics || {};
  const evidence = event.evidence_package || {};
  const delivery = normalizeDelivery(event.delivery, event, status);
  const review = normalizeReviewFields(event, rawEvent, trusted, semantics, evidence, status);
  const archiveSummary = event.archive_summary || {};
  const keyframes = normalizeKeyframes(evidence.keyframes || [], rawEvent, trusted);
  const missingCount = keyframes.filter((item) => !item.available).length;
  const qwenAdvisory = normalizeQwenKeyframeAdvisory(event.qwen_advisory, status);
  return {
    state: missingCount ? "partial_keyframes" : "event_ready",
    enabled: true,
    incident_id: rawEvent.incident_id || event.incident_id || evidence.incident_id || "-",
    camera_id: rawEvent.camera_id || evidence.camera_id || event.camera_id || "-",
    track_id: rawEvent.track_id ?? evidence.track_id ?? "-",
    event_type: trusted.final_event_type || rawEvent.event_type || "-",
    fall_state: rawEvent.fall_state || "-",
    risk_level: trusted.final_risk_level || rawEvent.risk_level || "-",
    confidence: normalizeConfidence(pickValue(trusted.confidence, semantics.risk?.confidence, rawEvent.risk_score)),
    event_status: rawEvent.status || event.status || "-",
    result_source: review.result_source,
    review_result: review.review_result,
    explanation: review.explanation,
    recommended_action: review.recommended_action,
    uncertainty: review.uncertainty,
    degradation_used: review.degradation_used,
    observed_process: review.observed_process,
    risk_interpretation: review.risk_interpretation,
    adl_likelihood: review.adl_likelihood,
    vlm_status: review.vlm_status,
    vlm_provider: review.vlm_provider,
    vlm_latency_ms: review.vlm_latency_ms,
    qwen_advisory: qwenAdvisory,
    delivery,
    delivery_status: delivery.status_text,
    delivery_mode: delivery.mode_text,
    dry_run: delivery.dry_run,
    archive_summary: archiveSummary,
    archive_status: archiveStatus(event, archiveSummary),
    timeline_image: normalizeTimelineImage(event, archiveSummary),
    keyframes,
    status,
  };
}

function emptyNormalizedEvent(stateName, message, status) {
  return {
    state: stateName,
    enabled: false,
    incident_id: "-",
    camera_id: "-",
    track_id: "-",
    event_type: "-",
    fall_state: "-",
    risk_level: "-",
    confidence: "-",
    event_status: "-",
    result_source: "-",
    review_result: stateName === "disabled" ? "VLM 复核未启用" : "-",
    explanation: message,
    recommended_action: "-",
    uncertainty: [],
    degradation_used: [],
    observed_process: "-",
    risk_interpretation: "-",
    adl_likelihood: "-",
    vlm_status: "VLM 复核未启用",
    vlm_provider: "disabled",
    vlm_latency_ms: null,
    qwen_advisory: normalizeQwenKeyframeAdvisory(null, status || {}),
    delivery: normalizeDelivery(null, {}, status || {}),
    delivery_status: "暂无投递状态",
    delivery_mode: "not configured",
    dry_run: null,
    archive_summary: {},
    archive_status: "-",
    timeline_image: { state: "missing", text: "不提供事件过程图", url: null },
    keyframes: normalizeKeyframes([], {}, {}),
    status: status || {},
  };
}

function normalizeQwenKeyframeAdvisory(rawAdvisory, status) {
  const advisory = rawAdvisory && typeof rawAdvisory === "object" ? rawAdvisory : null;
  const enabled = Boolean(status?.qwen_keyframe_analysis_enabled);
  if (!advisory) {
    return {
      status: enabled ? "waiting" : "disabled",
      scene_summary: enabled ? "等待符合条件的 confirmed 事件" : "本地关键帧分析未启用",
      posture_movement: "-",
      care_advice: "-",
      uncertainty: "-",
    };
  }
  const state = safeDisplayText(advisory.analysis_status, "degraded");
  const stateText = {
    pending: "等待本地分析",
    processing: "本地千问分析中",
    completed: "已完成，本地辅助描述",
    degraded: "已降级，保留规则结果",
    failed: "分析失败，保留规则结果",
    disabled: "本地关键帧分析未启用",
  }[state] || state;
  const posture = [
    safeDisplayText(advisory.posture_description, ""),
    safeDisplayText(advisory.movement_description, ""),
  ].filter(Boolean).join(" / ") || "-";
  const reasons = normalizeList(advisory.possible_false_positive_reasons);
  const error = safeDisplayText(advisory.error_code, "");
  return {
    status: stateText,
    scene_summary: safeDisplayText(advisory.scene_summary, state === "completed" ? "未返回场景描述" : "-"),
    posture_movement: posture,
    care_advice: normalizeList(advisory.care_advice).join("; ") || "-",
    uncertainty: [
      ...reasons,
      ...normalizeList(advisory.missing_reasons),
      error,
    ].filter(Boolean).join(", ") || "-",
  };
}

function normalizeKeyframes(rawKeyframes, rawEvent, trusted) {
  const byOffset = new Map((rawKeyframes || []).map((item) => [Number(item?.offset_ms), item]));
  return EVENT_TIMELINE_OFFSETS.map((offset) => {
    const item = byOffset.get(offset) || {};
    const available = Boolean(item.available && item.keyframe_url);
    return {
      label: item.label || timelineOffsetLabel(offset),
      keyframe_id: keyframeIdForOffset(offset),
      offset_ms: offset,
      role: item.role || keyframeRoleForOffset(offset),
      available,
      keyframe_url: available && isRelativeApiPath(item.keyframe_url) ? item.keyframe_url : null,
      missing_reason: item.missing_reason || (!available ? keyframeUnavailableReason(item) : null),
      fall_state: item.fall_state || rawEvent.fall_state || "-",
      risk_level: item.risk_level || trusted.final_risk_level || rawEvent.risk_level || "-",
      bbox: Array.isArray(item.bbox) ? item.bbox : null,
      frame_seq: item.frame_seq ?? null,
      timestamp: item.timestamp || null,
    };
  });
}

function normalizeReviewFields(event, rawEvent, trusted, semantics, evidence, status) {
  const vlmReview = event.vlm_review || trusted.vlm_review || event.vlm_result || {};
  const vlmProvider = safeDisplayText(pickValue(
    trusted.vlm_provider,
    trusted.provider,
    vlmReview.vlm_provider,
    vlmReview.provider,
    status.vlm_provider,
    status.vlm_enabled ? "configured" : null,
  ), "");
  const vlmLatency = pickValue(trusted.vlm_latency_ms, trusted.latency_ms, vlmReview.vlm_latency_ms, vlmReview.latency_ms);
  const reviewResult = safeDisplayText(pickValue(
    trusted.review_result,
    vlmReview.review_result,
    semantics.risk?.decision,
    rawEvent.metadata?.review_result,
    "rule_only",
  ));
  const observedProcess = safeDisplayText(pickValue(
    trusted.observed_process,
    vlmReview.observed_process,
    semantics.motion?.observed_process,
    semantics.motion?.main_transition,
    "-",
  ));
  const riskInterpretation = safeDisplayText(pickValue(
    trusted.risk_interpretation,
    vlmReview.risk_interpretation,
    semantics.risk?.risk_interpretation,
    semantics.risk?.decision,
    "-",
  ));
  const adlLikelihood = safeDisplayText(pickValue(
    trusted.adl_likelihood,
    vlmReview.adl_likelihood,
    semantics.evidence?.adl_likelihood,
    adlLikelihoodFromScore(evidence.adl_suppression_score ?? semantics.evidence?.adl_suppression_score),
  ));
  const uncertainty = normalizeList(pickValue(trusted.uncertainty, vlmReview.uncertainty, semantics.uncertainty));
  const degradation = normalizeList(pickValue(trusted.degradation_used, evidence.degradation_used, semantics.degradation_used));
  const hasVlmSignal = Boolean(
    (vlmProvider && vlmProvider !== "disabled")
    || reviewResult.includes("vlm")
    || vlmLatency !== null && vlmLatency !== undefined
    || safeDisplayText(vlmReview.risk_interpretation, "")
    || safeDisplayText(vlmReview.observed_process, ""),
  );
  return {
    review_result: reviewResultText(reviewResult, hasVlmSignal),
    explanation: safeDisplayText(pickValue(
      trusted.explanation,
      vlmReview.risk_interpretation,
      evidence.decision_reason,
      "Evidence is being prepared.",
    )),
    recommended_action: safeDisplayText(pickValue(trusted.recommended_action, vlmReview.recommended_action, "-")),
    uncertainty,
    degradation_used: degradation,
    observed_process: observedProcess,
    risk_interpretation: riskInterpretation,
    adl_likelihood: adlLikelihoodText(adlLikelihood),
    vlm_status: vlmStatusText(vlmProvider, vlmLatency, hasVlmSignal),
    vlm_provider: vlmProvider || "disabled",
    vlm_latency_ms: vlmLatency,
    result_source: resultSourceText(reviewResult, hasVlmSignal),
  };
}

function normalizeDelivery(delivery, event, status) {
  const record = delivery || {};
  const statusValue = safeDisplayText(pickValue(record.delivery_status, record.status, null), "");
  const mode = safeDisplayText(pickValue(record.delivery_mode, status.delivery_mode, null), "");
  const dryRun = pickValue(record.dry_run, record.payload_summary?.dry_run, null);
  const retryCount = pickValue(record.retry_count, record.attempt_count, event.retry_count, 0);
  const nextRetry = pickValue(record.next_retry_at, event.next_retry_at, null);
  const deliveredAt = pickValue(record.delivered_at, null);
  const backend = pickValue(record.delivery_backend, status.delivery_backend, status.outbox_backend, null);
  const hasRecord = Boolean(delivery && Object.keys(delivery).length);
  return {
    has_record: hasRecord,
    status: statusValue || "not_configured",
    status_text: deliveryStatusText(statusValue, mode, dryRun, hasRecord),
    mode_text: deliveryModeLabel(mode, dryRun, hasRecord),
    dry_run: dryRun,
    dry_run_text: dryRun === true ? "是，模拟投递" : (dryRun === false ? "否，正式 POST" : "-"),
    retry_count: retryCount,
    retry_text: retryCount ? `${retryCount} 次` : (statusValue === "retry" ? "等待重试" : "-"),
    next_retry_text: nextRetry ? formatEventDateTime(nextRetry) : "-",
    delivered_at_text: deliveredAt ? formatEventDateTime(deliveredAt) : "-",
    backend_text: backend ? safeDisplayText(backend) : "-",
    last_error_text: safeLastError(record.last_error),
  };
}

function renderEventPanel(model) {
  state.lastDashboardEvent = model;
  renderEventHealth(model.status, model.state);
  setEventPipelineState(model.state === "api_error" ? "error" : (model.enabled ? "enabled" : "disabled"));
  setText("eventIncidentId", model.incident_id);
  setText("eventCameraId", model.camera_id);
  setText("eventTrackId", model.track_id);
  setText("eventType", model.event_type);
  setText("eventFallState", model.fall_state);
  setText("eventRiskLevel", model.risk_level);
  setText("eventConfidence", model.confidence);
  setText("eventStatus", model.event_status);
  setText("eventResultSource", model.result_source);
  setText("eventDeliveryStatus", model.delivery_status);
  setText("eventDeliveryMode", model.delivery_mode);
  setText("eventDeliveryDryRun", model.delivery.dry_run_text);
  setText("eventDeliveryRetry", model.delivery.retry_text);
  setText("eventDeliveryNextRetry", model.delivery.next_retry_text);
  setText("eventDeliveryDeliveredAt", model.delivery.delivered_at_text);
  setText("eventDeliveryBackend", model.delivery.backend_text);
  setText("eventDeliveryLastError", model.delivery.last_error_text);
  setText("eventArchiveStatus", model.archive_status);
  setText("eventReviewResult", model.review_result);
  setText("eventExplanation", model.explanation);
  setText("eventRecommendedAction", model.recommended_action);
  setText("eventUncertainty", model.uncertainty.length ? model.uncertainty.join(", ") : "none");
  renderTagList("eventDegradation", model.degradation_used, "none");
  setText("eventObservedProcess", model.observed_process);
  setText("eventRiskInterpretation", model.risk_interpretation);
  setText("eventAdlLikelihood", model.adl_likelihood);
  setText("eventVlmStatus", model.vlm_status);
  setText("eventQwenStatus", model.qwen_advisory.status);
  setText("eventQwenSceneSummary", model.qwen_advisory.scene_summary);
  setText("eventQwenPostureMovement", model.qwen_advisory.posture_movement);
  setText("eventQwenCareAdvice", model.qwen_advisory.care_advice);
  setText("eventQwenUncertainty", model.qwen_advisory.uncertainty);
  renderEventEmptyState(model);
  renderTimelineImage(model.timeline_image);
  renderEventTimeline(model.keyframes);
  renderDashboard();
}

function renderDashboard() {
  synchronizeJudgmentReset();
  window.__VISION_DASHBOARD__?.render?.({
    status: state.lastStatus,
    control: state.lastControlStatus,
    result: state.lastResult,
    event: state.lastDashboardEvent,
  });
  if (state.lastSessionStatus) {
    renderSessionStatus(state.lastSessionStatus);
  } else {
    renderPresentationResult(null, null);
  }
  renderVisualMetrics();
  renderDemoVisualState();
}

function renderVisualMetrics() {
  const status = state.lastStatus || {};
  const control = state.lastControlStatus || {};
  const session = state.lastSessionStatus || {};
  const camera = currentCameraSnapshot(status);
  const perf = control.performance || {};
  const runtime = control.runtime || {};
  const videoReady = Boolean(control.stream_connected || camera?.connected);
  const binaryReady = Boolean(control.binary_enabled);
  const qwenReady = Boolean(control.qwen_enabled);
  const videoFps = videoReady ? numberOrNull(camera?.mjpeg_publish_fps ?? camera?.capture_fps ?? perf.capture_fps ?? state.videoFps.lastMeasuredFps) : null;
  const sampleFps = numberOrNull(perf.sample_fps ?? runtime.binary_sample_fps ?? runtime.sample_fps);
  const frameAge = videoReady ? numberOrNull(camera?.frame_age_ms ?? perf.frame_age_ms) : null;
  const binaryLatency = binaryReady ? numberOrNull(perf.binary_inference_ms_avg ?? runtime.binary_inference_latency_avg_ms ?? runtime.binary_inference_latency_ms) : null;
  const qwenQueue = qwenReady ? numberOrNull(runtime.vlm_queue_depth ?? perf.qwen?.queue_depth) : null;
  const sessionElapsed = numberOrNull(session.elapsed_seconds);
  const fallProbability = currentFallProbability();

  setHexMetric("hexVideoFps", videoFps, videoFps == null ? "--" : `${videoFps.toFixed(1)}`, "FPS", metricStateFromNumber(videoFps, { good: 8, warn: 3 }, true));
  setHexMetric("hexSampleFps", sampleFps, sampleFps == null ? "--" : `${sampleFps.toFixed(1)}`, "SPS", metricStateFromNumber(sampleFps, { good: 2, warn: 0.5 }, true));
  setHexMetric("hexFrameAge", frameAge, frameAge == null ? "--" : `${Math.round(frameAge)}ms`, "AGE", metricStateFromNumber(frameAge, { good: 800, warn: 2500 }, false));
  setHexMetric("hexBinaryLatency", binaryLatency, binaryLatency == null ? "--" : `${Math.round(binaryLatency)}ms`, "AI", metricStateFromNumber(binaryLatency, { good: 80, warn: 180 }, false));
  setHexMetric("hexQwenQueue", qwenQueue, qwenQueue == null ? "--" : String(qwenQueue), "QUEUE", metricStateFromNumber(qwenQueue, { good: 0, warn: 2 }, false));
  setHexMetric("hexSessionTime", sessionElapsed, sessionElapsed == null ? "00:00" : formatCompactDuration(sessionElapsed), "TIME", String(session.state || "IDLE").toUpperCase() === "RUNNING" ? "active" : "idle");

  appendVisualHistory({
    binaryProbability: fallProbability,
    videoFps,
    frameAge,
  });
  setText("trendBinaryValue", fallProbability == null ? "--" : fallProbability.toFixed(2));
  setText("trendVideoValue", compactJoin([
    videoFps == null ? "" : `${videoFps.toFixed(1)} FPS`,
    frameAge == null ? "" : `${Math.round(frameAge)}ms`,
  ]) || "--");
  renderLineTrend("binaryProbabilityTrend", state.visualHistory.binaryProbability, { min: 0, max: 1, color: "rgba(255, 202, 69, 0.96)" });
  renderLineTrend("videoFpsTrend", state.visualHistory.videoFps, { min: 0, color: "rgba(46, 229, 157, 0.94)" });
}

function setHexMetric(id, rawValue, displayValue, title, metricState) {
  const element = $(id);
  if (!element) return;
  element.textContent = displayValue;
  element.title = `${title}: ${rawValue == null ? "--" : rawValue}`;
  const card = element.closest(".hex-kpi");
  if (card) card.dataset.state = metricState || "idle";
}

function appendVisualHistory(values) {
  const now = Date.now();
  if (now - state.visualHistory.lastAppendAt < 900) {
    return;
  }
  state.visualHistory.lastAppendAt = now;
  for (const [key, value] of Object.entries(values)) {
    const bucket = state.visualHistory[key];
    if (!bucket || value == null || !Number.isFinite(Number(value))) {
      continue;
    }
    bucket.push(Number(value));
    while (bucket.length > 48) {
      bucket.shift();
    }
  }
}

function renderLineTrend(id, values, options = {}) {
  const element = $(id);
  if (!element) return;
  const series = (values || []).filter((value) => Number.isFinite(Number(value))).map(Number);
  if (!series.length) {
    element.classList.add("is-empty");
    element.textContent = "等待真实数据";
    return;
  }
  element.classList.remove("is-empty");
  const width = 100;
  const height = 54;
  const padding = 5;
  const min = options.min ?? Math.min(...series);
  const max = Math.max(options.max ?? Math.max(...series), min + 0.001);
  const points = series.map((value, index) => {
    const x = series.length === 1 ? width : (index / (series.length - 1)) * width;
    const clamped = Math.max(min, Math.min(max, value));
    const y = height - padding - ((clamped - min) / (max - min)) * (height - padding * 2);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const color = options.color || "rgba(24, 191, 255, 0.92)";
  element.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
      <line x1="0" y1="${height - padding}" x2="${width}" y2="${height - padding}" stroke="rgba(143,176,199,.24)" stroke-width="1"></line>
      <polyline points="${points}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"></polyline>
    </svg>
  `;
}

function currentCameraSnapshot(status) {
  const cameraId = currentCameraId();
  return (status?.cameras || []).find((item) => item.camera_id === cameraId)
    || status?.cameras?.[0]
    || null;
}

function currentFallProbability() {
  const control = state.lastControlStatus || {};
  const result = state.lastResult || {};
  const objects = result.objects || [];
  const target = objects.find((item) => item?.is_target === true) || objects[0] || {};
  const decision = target.fall_decision || {};
  if (!control.binary_enabled && !decision.binary_label && !decision.fall_probability) {
    return null;
  }
  return numberOrNull(
    decision.binary_probability
      ?? decision.fall_probability
      ?? target.temporal?.fall_probability
      ?? control.runtime?.binary_last_probability,
  );
}

function realFallBooleanText(presentation) {
  if (!presentation?.event_id || presentation.is_real_fall == null) {
    return "--";
  }
  return presentation.is_real_fall ? "YES" : "NO";
}

function metricStateFromNumber(value, thresholds, higherIsBetter) {
  if (value == null || !Number.isFinite(Number(value))) {
    return "idle";
  }
  const number = Number(value);
  if (higherIsBetter) {
    if (number >= thresholds.good) return "active";
    if (number >= thresholds.warn) return "warning";
    return "error";
  }
  if (number <= thresholds.good) return "active";
  if (number <= thresholds.warn) return "warning";
  return "error";
}

function formatCompactDuration(totalSeconds) {
  const safe = Math.max(0, Number(totalSeconds) || 0);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = Math.floor(safe % 60);
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function compactJoin(items) {
  return items.filter((item) => item !== null && item !== undefined && item !== "").join(" / ");
}

function renderEventHealth(status, eventState) {
  const enabled = Boolean(status?.event_pipeline_enabled);
  setText("eventHealthPipeline", eventState === "api_error" ? "error" : (enabled ? "enabled" : "disabled"));
  setText("eventHealthWorker", status?.worker_running ? "running" : "stopped");
  setText(
    "eventHealthOutbox",
    `${status?.outbox_count ?? 0} total · ${status?.pending_count ?? 0} / ${status?.processing_count ?? 0} / ${status?.reviewed_count ?? 0} / ${status?.failed_count ?? 0}`,
  );
}

function renderEventEmptyState(model) {
  const target = $("eventEmptyState");
  if (!target) {
    return;
  }
  const messages = {
    disabled: "事件语义链路未启用",
    no_event: "暂无事件归档",
    api_error: "事件接口暂不可用",
    partial_keyframes: "事件已归档，部分关键帧缺失",
    event_ready: "事件证据链已就绪",
  };
  target.textContent = messages[model.state] || model.explanation || "-";
  target.dataset.state = model.state;
}

function renderEventTimeline(keyframes) {
  const timeline = $("eventTimeline");
  if (!timeline) return;
  timeline.replaceChildren(...keyframes.map((item) => {
    const card = document.createElement("div");
    const missingReason = item.missing_reason || (!item.available ? keyframeUnavailableReason(item) : null);
    card.className = `event-keyframe${missingReason ? " missing" : ""}`;
    const title = document.createElement("strong");
    title.className = "event-keyframe-label";
    title.textContent = item.label;
    card.append(title);
    if (item.available && item.keyframe_url) {
      const image = document.createElement("img");
      image.src = eventAssetUrl(item.keyframe_url);
      image.alt = `${item.label} keyframe`;
      image.loading = "lazy";
      image.addEventListener("error", () => {
        card.classList.add("missing");
        image.remove();
        reason.textContent = "关键帧不可用";
      }, { once: true });
      card.append(image);
    }
    const reason = document.createElement("span");
    reason.className = "event-keyframe-status";
    reason.textContent = missingReason || item.role || "archived";
    const meta = document.createElement("dl");
    meta.className = "event-keyframe-meta";
    appendKeyframeMeta(meta, "Offset", `${item.offset_ms}ms`);
    appendKeyframeMeta(meta, "Frame", item.frame_seq ?? "-");
    appendKeyframeMeta(meta, "State", item.fall_state || "-");
    appendKeyframeMeta(meta, "Risk", item.risk_level || "-");
    appendKeyframeMeta(meta, "BBox", formatBbox(item.bbox));
    card.append(reason, meta);
    return card;
  }));
}

function appendKeyframeMeta(container, label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = String(value ?? "-");
  container.append(term, detail);
}

function renderTagList(id, values, emptyText) {
  const element = $(id);
  if (!element) {
    return;
  }
  const items = normalizeList(values);
  if (!items.length) {
    element.classList.remove("event-tag-list");
    element.textContent = emptyText || "-";
    return;
  }
  element.classList.add("event-tag-list");
  element.replaceChildren(...items.map((item) => {
    const tag = document.createElement("span");
    tag.className = "event-tag";
    tag.textContent = item;
    return tag;
  }));
}

function renderTimelineImage(timelineImage) {
  const container = $("eventTimelineImage");
  if (!container) {
    return;
  }
  const model = timelineImage || {};
  if (model.url) {
    const image = document.createElement("img");
    image.src = eventAssetUrl(model.url);
    image.alt = "Event timeline image";
    image.loading = "lazy";
    image.addEventListener("error", () => {
      container.replaceChildren(textNode("事件过程图不可用"));
    }, { once: true });
    container.replaceChildren(image);
    return;
  }
  container.replaceChildren(textNode(model.text || "不提供事件过程图"));
}

function keyframeUnavailableReason(item) {
  if (!item || Object.keys(item).length === 0) {
    return "awaiting_keyframe";
  }
  if (!item.keyframe_url && !item.image_path) {
    return "未归档";
  }
  return item.missing_reason || "image_not_found";
}

function eventAssetUrl(url) {
  if (!isRelativeApiPath(url)) {
    return "";
  }
  return `${apiBase()}${url.startsWith("/") ? "" : "/"}${url}`;
}

function normalizeTimelineImage(event, archiveSummary) {
  const url = pickValue(event.timeline_image_url, event.timeline_image?.url, archiveSummary.timeline_image_url, null);
  if (isRelativeApiPath(url)) {
    return { state: "available", text: "事件过程图", url };
  }
  if (archiveSummary.timeline_image_path) {
    return {
      state: "archived_only",
      text: "事件过程图已归档，当前未开放前端访问 URL",
      url: null,
    };
  }
  return { state: "missing", text: "不提供事件过程图", url: null };
}

function normalizeConfidence(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${Math.round(numeric * 100)}%` : "-";
}

function normalizeList(value) {
  if (Array.isArray(value)) {
    return value.map(readableListItem).filter(Boolean).slice(0, 8);
  }
  if (typeof value === "string" && value.trim()) {
    return value.split(",").map((item) => safeDisplayText(item.trim())).filter(Boolean).slice(0, 8);
  }
  return [];
}

function readableListItem(item) {
  if (item === null || item === undefined) {
    return "";
  }
  if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
    return safeDisplayText(item);
  }
  if (typeof item === "object") {
    const label = item.code || item.reason || item.name || item.type || item.message;
    return safeDisplayText(label || "structured_note");
  }
  return safeDisplayText(item);
}

function archiveStatus(event, summary) {
  if (!event?.archive_id && !Object.keys(summary || {}).length) {
    return "not archived";
  }
  const saved = summary?.keyframes_saved ?? 0;
  const missing = summary?.keyframes_missing ?? 0;
  return `archived (${saved} saved / ${missing} missing)`;
}

function deliveryStatusText(status, mode, dryRun, hasRecord) {
  if (!hasRecord) {
    return "暂无投递状态";
  }
  const normalized = String(status || "").toLowerCase();
  if (normalized === "dry_run_sent") {
    return "模拟投递完成";
  }
  if (normalized === "sent" && mode === "post" && dryRun === false) {
    return "已投递";
  }
  const labels = {
    sent: dryRun ? "模拟投递完成" : "已投递",
    retry: "等待重试",
    failed: "投递失败",
    pending: "等待投递",
    sending: "投递中",
  };
  return labels[normalized] || "未启用或暂无投递记录";
}

function deliveryModeLabel(mode, dryRun, hasRecord) {
  if (!hasRecord) {
    return "not configured";
  }
  const normalized = String(mode || "").toLowerCase();
  if (dryRun === true || normalized === "dry_run") {
    return "dry_run / 模拟";
  }
  if (normalized === "post") {
    return "post / 正式";
  }
  return normalized || "not configured";
}

function safeLastError(value) {
  const text = safeDisplayText(value, "-");
  if (text === "-") {
    return text;
  }
  return text
    .replace(/https?:\/\/[^\s]+/gi, "[url-redacted]")
    .replace(/[A-Za-z]:[\\/][^\s]+/g, "[local-path-redacted]")
    .replace(/(token|password|secret|key)=([^&\s]+)/gi, "$1=[redacted]")
    .slice(0, 180);
}

function reviewResultText(value, hasVlmSignal) {
  const normalized = safeDisplayText(value || "").toLowerCase();
  if (!hasVlmSignal) {
    return "规则复核结果";
  }
  if (normalized.includes("vlm")) {
    return "规则复核 + VLM 辅助解释";
  }
  return safeDisplayText(value, "事件级复核结果");
}

function resultSourceText(value, hasVlmSignal) {
  if (hasVlmSignal || String(value || "").toLowerCase().includes("vlm")) {
    return "事件级复核 / VLM 辅助";
  }
  return "事件级复核 / 规则";
}

function vlmStatusText(provider, latency, hasVlmSignal) {
  const normalized = safeDisplayText(provider || "disabled");
  if (!hasVlmSignal || normalized === "disabled") {
    return "VLM 复核未启用，当前为规则复核结果";
  }
  const latencyText = Number.isFinite(Number(latency)) ? `，${Math.round(Number(latency))}ms` : "";
  return `${normalized} 事件级辅助复核${latencyText}`;
}

function adlLikelihoodText(value) {
  const normalized = safeDisplayText(value || "unknown").toLowerCase();
  const labels = {
    low: "日常活动相似度：低",
    medium: "日常活动相似度：中",
    high: "日常活动相似度：高",
    unknown: "日常活动相似度：未知",
  };
  return labels[normalized] || `日常活动相似度：${safeDisplayText(value)}`;
}

function adlLikelihoodFromScore(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) {
    return "unknown";
  }
  if (score >= 0.65) return "high";
  if (score >= 0.35) return "medium";
  return "low";
}

function pickValue(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined && value !== "") {
      return value;
    }
  }
  return null;
}

function safeDisplayText(value, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  if (typeof value === "object") {
    return fallback;
  }
  return String(value).slice(0, 500);
}

function formatEventDateTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return safeDisplayText(value);
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function keyframeIdForOffset(offset) {
  const ids = {
    "-3000": "t_minus_3s",
    "-1000": "t_minus_1s",
    0: "t0",
    1000: "t_plus_1s",
    3000: "t_plus_3s",
    5000: "t_plus_5s",
  };
  return ids[offset] || String(offset);
}

function keyframeRoleForOffset(offset) {
  if (offset <= -2000) return "pre_context";
  if (offset < 0) return "pre_fall";
  if (offset === 0) return "trigger";
  if (offset < 3000) return "post_fall";
  return "post_check";
}

function isRelativeApiPath(url) {
  return typeof url === "string"
    && url.startsWith("/events/")
    && !url.includes("..")
    && !/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url);
}

function formatBbox(bbox) {
  if (!Array.isArray(bbox) || bbox.length < 4) {
    return "-";
  }
  return bbox.slice(0, 4).map((value) => Number(value).toFixed(0)).join(",");
}

function warnEventApiOnce(error) {
  if (state.eventReview.apiWarned) {
    return;
  }
  state.eventReview.apiWarned = true;
  console.warn("Event API unavailable", error);
}

function timelineOffsetLabel(offset) {
  if (offset === 0) return "T0";
  return offset < 0 ? `T-${Math.abs(offset) / 1000}s` : `T+${offset / 1000}s`;
}

function setEventPipelineState(value) {
  const element = $("eventPipelineState");
  if (!element) {
    return;
  }
  const normalized = value || "inactive";
  element.textContent = normalized;
  element.classList.remove("event-state-disabled", "event-state-enabled", "event-state-error", "event-state-inactive");
  element.classList.add(`event-state-${normalized}`);
}

window.__VISION_EVENT_REVIEW__ = Object.freeze({
  normalizeEventPayload,
  normalizeKeyframes,
  getStatus: () => structuredCloneSafe(state.eventReview.status),
  getLastEvent: () => structuredCloneSafe(state.lastEvent),
  getRecentItems: () => structuredCloneSafe(state.eventReview.recentItems),
  getSelectedIncidentId: () => state.eventReview.selectedIncidentId,
});

async function refreshDeviceDiscoveryStatus() {
  const resultBox = $("discoveryResult");
  if (!resultBox) {
    return;
  }
  try {
    const response = await fetch(`${apiBase()}/device-discovery/status`);
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    renderDeviceDiscoveryStatus(payload);
  } catch (error) {
    resultBox.textContent = `发现状态读取失败：${error}`;
    resultBox.dataset.state = "error";
  }
}

async function rescanDevices() {
  return runDeviceConnectionAction({
    endpoint: "/device-discovery/pair-main-system",
    pendingText: "正在搜索并配对主系统...",
    successPrefix: "主系统配对完成",
    activeButtonId: "rescanDevicesBtn",
  });
}

async function autoConnectDevices() {
  return runDeviceConnectionAction({
    endpoint: "/device-discovery/pair-main-system",
    pendingText: "正在自动发现主系统并完成告警端口配对...",
    successPrefix: "一键配对完成",
    activeButtonId: "autoConnectDevicesBtn",
  });
}

async function runDeviceConnectionAction({ endpoint, pendingText, successPrefix, activeButtonId }) {
  const resultBox = $("discoveryResult");
  setDiscoveryButtonsDisabled(true);
  if (resultBox) {
    resultBox.textContent = pendingText;
    resultBox.dataset.state = "pending";
  }
  try {
    const response = await fetch(`${apiBase()}${endpoint}`, { method: "POST" });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(payload?.detail || `HTTP ${response.status}`);
    }
    renderDeviceDiscoveryStatus(payload);
    if (resultBox) {
      resultBox.textContent = summarizeDeviceConnectionPayload(successPrefix, payload);
      resultBox.dataset.state = "success";
    }
    await refreshStatus();
  } catch (error) {
    if (resultBox) {
      resultBox.textContent = `${pendingText.replace("正在", "").replace("...", "")}失败：${error}`;
      resultBox.dataset.state = "error";
    }
  } finally {
    setDiscoveryButtonsDisabled(false);
    const button = $(activeButtonId);
    if (button) {
      button.disabled = false;
    }
  }
}

function setDiscoveryButtonsDisabled(disabled) {
  for (const id of ["rescanDevicesBtn", "autoConnectDevicesBtn"]) {
    const button = $(id);
    if (button) {
      button.disabled = disabled;
    }
  }
}

function summarizeDeviceConnectionPayload(prefix, payload) {
  const mainIp = payload?.main_system?.ip || "-";
  const mainStatus = discoveryStatusLabel(payload?.main_system?.status);
  const alertEndpoint = payload?.applied?.alert_endpoint || payload?.alert_pairing?.endpoint || "-";
  const deliveryLabel = payload?.applied?.alert_enabled ? "已启用真实告警" : "未启用真实告警";
  if (mainStatus === "已连接") {
    return `${prefix}：主系统 ${mainIp}（${mainStatus}），${deliveryLabel}，端口 ${alertEndpoint}`;
  }
  return `${prefix}：主系统 ${mainIp}（${mainStatus}）`;
}

function renderDeviceDiscoveryStatus(payload) {
  setText("mainSystemDiscoveryState", discoveryStatusLabel(payload?.main_system?.status));
  setText("mainSystemDiscoveryIp", payload?.main_system?.ip || "-");
  setText("mainSystemDiscoveryPort", payload?.main_system?.port || "-");
  const alertPath = payload?.applied?.alert_path || payload?.main_system?.fall_event_path || payload?.alert_pairing?.path || "-";
  setText("mainSystemDiscoveryPath", alertPath);
  const alertEnabled = payload?.applied?.alert_enabled ?? payload?.alert_pairing?.enabled;
  const alertDryRun = payload?.applied?.alert_dry_run ?? payload?.alert_pairing?.dry_run;
  setText("mainSystemDeliveryState", formatAlertPairingState(alertEnabled, alertDryRun));
  setText("discoverySubnet", payload?.local_network?.subnet || "-");
  setText("discoveryLastScan", formatDiscoveryTime(payload?.discovery?.last_scan_at));
  const resultBox = $("discoveryResult");
  if (resultBox && !resultBox.dataset.state) {
    const error = payload?.discovery?.last_error;
    resultBox.textContent = error ? `最近错误：${error}` : "发现状态已同步";
    resultBox.dataset.state = error ? "error" : "success";
  }
}

function discoveryStatusLabel(value) {
  const labels = {
    connected: "已连接",
    checking_cached_config: "验证缓存",
    scanning: "搜索中",
    unavailable: "不可用",
    unverified: "未确认",
    not_found: "未找到",
    unknown: "未知",
  };
  return labels[value] || value || "-";
}

function formatAlertPairingState(enabled, dryRun) {
  if (enabled === true && dryRun === false) {
    return "真实投递";
  }
  if (enabled === true && dryRun === true) {
    return "演练模式";
  }
  if (enabled === false) {
    return "未配对";
  }
  return "-";
}

function formatDiscoveryTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function setText(id, value) {
  const element = $(id);
  if (element) {
    element.textContent = value;
  }
}

function textNode(value) {
  return document.createTextNode(value || "");
}

function structuredCloneSafe(value) {
  if (value === null || value === undefined) {
    return value;
  }
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_) {
    return null;
  }
}

function shortIncidentId(value) {
  const text = String(value || "-");
  return text.length > 18 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text;
}

function formatEventTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function currentCameraId() {
  return $("cameraId")?.value.trim() || state.lastStatus?.cameras?.[0]?.camera_id || "camera_01";
}

function moveEngineeringColumnsToDrawer() {
  const drawer = document.querySelector(".engineering-drawer .drawer-grid");
  if (!drawer) {
    return;
  }
  for (const selector of [".dashboard-grid > .left-column", ".dashboard-grid > .right-column"]) {
    const column = document.querySelector(selector);
    if (column && column.parentElement !== drawer) {
      drawer.appendChild(column);
    }
  }
}

function handleSessionHotkey(event) {
  if (event.key !== "F8") {
    return;
  }
  const target = event.target;
  const tagName = String(target?.tagName || "").toLowerCase();
  if (tagName === "input" || tagName === "textarea" || tagName === "select" || target?.isContentEditable) {
    return;
  }
  event.preventDefault();
  if (state.sessionHotkeyBusy) {
    return;
  }
  state.sessionHotkeyBusy = true;
  Promise.resolve(toggleDetectionSession()).finally(() => {
    state.sessionHotkeyBusy = false;
  });
}

function handleStagedControlHotkey(event) {
  if (!["F5", "F6", "F7"].includes(event.key)) {
    return;
  }
  const target = event.target;
  const tagName = String(target?.tagName || "").toLowerCase();
  if (tagName === "input" || tagName === "textarea" || tagName === "select" || target?.isContentEditable) {
    return;
  }
  event.preventDefault();
  if (event.repeat) {
    return;
  }
  if (event.key === "F7") {
    resetCurrentJudgment();
    return;
  }
  if (state.stagedControlHotkeyBusy) {
    return;
  }
  state.stagedControlHotkeyBusy = true;
  const action = event.key === "F5" ? startVideoOnly() : startBothModels();
  Promise.resolve(action).finally(() => {
    state.stagedControlHotkeyBusy = false;
  });
}

function handleDemoHotkey(event) {
  if (event.key !== "F9" && event.key !== "F10") {
    return;
  }
  const target = event.target;
  const tagName = String(target?.tagName || "").toLowerCase();
  if (tagName === "input" || tagName === "textarea" || tagName === "select" || target?.isContentEditable) {
    return;
  }
  event.preventDefault();
  if (event.repeat) {
    return;
  }
  if (event.key === "F10") {
    toggleDemoLowPosture();
    return;
  }
  toggleDemoFall();
}

function startEventReviewPolling() {
  void refreshEventStatus().then(() => Promise.all([
    refreshRecentEvents(currentCameraId()),
    refreshLatestEvent(currentCameraId(), { force: true }),
  ]));
  setInterval(refreshEventStatus, EVENT_STATUS_REFRESH_MS);
  setInterval(() => refreshRecentEvents(currentCameraId()), EVENT_RECENT_REFRESH_MS);
  const pollLatest = () => {
    void refreshLatestEvent(currentCameraId()).finally(() => {
      setTimeout(pollLatest, state.eventReview.latestRefreshMs || EVENT_LATEST_REFRESH_MS);
    });
  };
  setTimeout(pollLatest, EVENT_LATEST_REFRESH_MS);
}

$("startBtn").addEventListener("click", startStream);
$("connectBtn").addEventListener("click", connectWebRTC);
$("binaryToggleBtn")?.addEventListener("click", toggleBinaryModel);
$("qwenToggleBtn")?.addEventListener("click", toggleQwenModel);
$("startTestBtn")?.addEventListener("click", startTimedTest);
$("stopTestBtn")?.addEventListener("click", stopTimedTest);
$("sessionToggleBtn")?.addEventListener("click", toggleDetectionSession);
$("toggleFullJsonBtn")?.addEventListener("click", toggleFullJson);
$("demoFallBtn")?.addEventListener("click", toggleDemoFall);
$("demoLowPostureBtn")?.addEventListener("click", toggleDemoLowPosture);
$("acknowledgeFallBtn")?.addEventListener("click", acknowledgeCurrentFall);
$("cameraId")?.addEventListener("change", () => {
  state.autoFrontendConnectAttempted = false;
  state.frameFallback.lastOkAt = null;
  setFrameFallbackVisible(false);
  void refreshStatus();
  void refreshControlStatus();
  void refreshSessionStatus();
  void refreshFrameFallback();
});
$("rescanDevicesBtn")?.addEventListener("click", rescanDevices);
$("autoConnectDevicesBtn")?.addEventListener("click", autoConnectDevices);
$("eventShowLatestBtn")?.addEventListener("click", () => {
  state.eventReview.selectedIncidentId = null;
  void refreshLatestEvent(currentCameraId(), { force: true });
  renderRecentEvents(state.eventReview.recentItems, state.eventReview.recentItems.length ? null : "暂无事件");
});
initializeManualAlertControls();
$("rtspUrl")?.addEventListener("input", () => {
  state.userEditedRtspUrl = true;
});
window.addEventListener("beforeunload", () => {
  state.userConnected = false;
  stopFrameFallbackLoop();
  stopOverlayLoop();
  closeConnections();
});
window.addEventListener("resize", () => {
  syncAlarmIndicatorPosition();
  const video = $("video");
  if (ANNOTATED_OVERLAY_ENABLED && state.lastResult && video && !isResultExpired(state.lastResult)) {
    drawOverlay(video, state.lastResult);
  } else if (isResultExpired(state.lastResult)) {
    expireOverlayResult();
  }
});
window.addEventListener("scroll", syncAlarmIndicatorPosition, { passive: true });
window.addEventListener("keydown", handleStagedControlHotkey);
window.addEventListener("keydown", handleSessionHotkey);
window.addEventListener("keydown", handleDemoHotkey);
window.addEventListener("error", (event) => pushDebugError("error", event));
window.addEventListener("unhandledrejection", (event) => pushDebugError("unhandledrejection", event));
if ("PerformanceObserver" in window) {
  try {
    const longTaskObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        pushLimited(debugState.longTasks, {
          at: Date.now(),
          name: entry.name,
          durationMs: round(entry.duration),
          startTimeMs: round(entry.startTime),
        }, 100);
      }
    });
    longTaskObserver.observe({ entryTypes: ["longtask"] });
  } catch (_) {
    // Long-task telemetry is best-effort and must never affect playback.
  }
}

function startRuntimePollingAfterFirstPaint() {
  moveEngineeringColumnsToDrawer();
  setInterval(refreshStatus, 2000);
  setInterval(refreshControlStatus, 1000);
  setInterval(refreshSessionStatus, SESSION_STATUS_REFRESH_MS);
  setInterval(sampleVideoQuality, 1000);
  setInterval(sampleRtcStats, 1000);
  syncFrameFallbackLoop();
  refreshStatus();
  refreshControlStatus();
  refreshSessionStatus();
  refreshDeviceDiscoveryStatus();
  startEventReviewPolling();
}

syncAlarmIndicatorPosition();
if ("requestAnimationFrame" in window) {
  requestAnimationFrame(() => window.setTimeout(startRuntimePollingAfterFirstPaint, 0));
} else {
  window.setTimeout(startRuntimePollingAfterFirstPaint, 0);
}
