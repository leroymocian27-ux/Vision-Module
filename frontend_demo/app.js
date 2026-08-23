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
const EVENT_TIMELINE_OFFSETS = [-3000, -1000, 0, 1000, 3000, 5000];
const FRAME_FALLBACK_REFRESH_MS = 300;
const FRAME_FALLBACK_RECENT_MS = 2500;
const VIDEO_PROGRESS_RECENT_MS = 2200;
const VIDEO_BLACK_LUMA_THRESHOLD = 8;

const state = {
  pc: null,
  peerId: null,
  ws: null,
  lastResult: null,
  lastStatus: null,
  lastEvent: null,
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
  eventReview: {
    status: null,
    latestRefreshMs: EVENT_LATEST_REFRESH_MS,
    apiWarned: false,
    selectedIncidentId: null,
    recentItems: [],
  },
};
window.__VISION_APP_STATE__ = state;

const debugState = window.__VISION_DEBUG__ || {
  overlayMode: new URLSearchParams(window.location.search).get("overlayMode") || "full",
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

function latestFrameUrl(cameraId) {
  return `${apiBase()}/stream/latest-frame.jpg?camera_id=${encodeURIComponent(cameraId)}&t=${Date.now()}`;
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

function startFrameFallbackLoop() {
  if (state.frameFallback.timer) {
    return;
  }
  void refreshFrameFallback();
  state.frameFallback.timer = setInterval(refreshFrameFallback, FRAME_FALLBACK_REFRESH_MS);
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
  return hasProgress && paintLooksLive;
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
  const backendFresh = !status || isBackendFrameFresh(status);
  const videoHealthy = isVideoVisiblyHealthy();
  const webrtcConnected = state.pc?.connectionState === "connected";
  const shouldShowFallback = hasRecentFallbackFrame && backendFresh && (!videoHealthy || !webrtcConnected);
  setFrameFallbackVisible(shouldShowFallback);
  const empty = document.querySelector(".viewer-empty");
  if (empty) {
    empty.hidden = shouldShowFallback || videoHealthy;
  }
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
  const rtspUrl = $("rtspUrl").value.trim() || null;
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
        rtsp_url: rtspUrl,
        main_rtsp_url: rtspUrl,
        analysis_rtsp_url: rtspUrl,
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
  $("webrtcState").textContent = "connecting";
  updatePeerDebugState();
  $("wsState").textContent = "idle";
  updateRecoveryBanner();

  try {
    await startStreamRequest({ updateUi: false });
  } catch (error) {
    $("webrtcState").textContent = "failed";
    $("statusBox").textContent = `stream start failed before WebRTC: ${error}`;
    state.autoReconnect.connecting = false;
    $("connectBtn").disabled = false;
    return;
  }

  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });
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
      $("webrtcState").textContent = pc.connectionState;
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
      $("webrtcState").textContent = "failed";
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
    $("wsState").textContent = "connected";
    state.autoReconnect.wsAttempts = 0;
    updateRecoveryBanner();
  };
  ws.onclose = () => {
    if (state.ws === ws) {
      $("wsState").textContent = "closed";
      scheduleWebSocketReconnect("websocket closed");
    }
  };
  ws.onerror = () => {
    if (state.ws === ws) {
      $("wsState").textContent = "error";
      scheduleWebSocketReconnect("websocket error");
    }
  };
  ws.onmessage = (event) => {
    const startedAt = performance.now();
    const result = JSON.parse(event.data);
    const composedResult = composeOverlayResult(result);
    composedResult.overlay_received_at = Date.now();
    state.lastResult = composedResult;
    state.pendingResult = composedResult;
    $("frameInfo").textContent = `${result.frame_width}x${result.frame_height} #${result.frame_seq}`;
    $("personCount").textContent = `${(result.objects || []).length}`;
    $("latency").textContent = `${result.detector?.latency_ms ?? "-"} ms`;
    updateTargetDetails(composedResult);
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
  $("webrtcState").textContent = `重连中 ${Math.round(delay / 1000)}s`;
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
  $("wsState").textContent = `重连中 ${Math.round(delay / 1000)}s`;
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
  } else if (main && main.stream_state !== "connected") {
    messages.push("高清流恢复中");
  }
  if (analysis && analysis.stream_state !== "connected") {
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
    void refreshDeviceDiscoveryStatus();
    syncRtspInputFromStatus(data);
    if (isResultExpired(state.lastResult)) {
      expireOverlayResult();
    }
    updateMetricPanel(data);
    debugState.counters.statusUpdates += 1;
    pushLimited(debugState.statusSamples, {
      at: Date.now(),
      elapsedMs: performance.now() - startedAt,
      rawJsonMs,
      frameAgeMs: data.cameras?.[0]?.frame_age_ms ?? null,
      publishFps: data.pipeline?.result_publish_fps ?? null,
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
    input.placeholder = "仅手动输入经批准的摄像头地址";
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
    target.textContent = `受控视频源已连接（显示=${display}，分析=${analysisSource}）`;
    return;
  }
  target.textContent = "视频源状态未提供连接地址";
}

function updateStreamState(status) {
  const cameraId = $("cameraId").value.trim() || "camera_01";
  const camera = (status.cameras || []).find((item) => item.camera_id === cameraId);
  if (!camera) {
    $("streamState").textContent = "未连接";
    updateFrameFallbackVisibility(status);
    updateRecoveryBanner();
    return;
  }

  const age = camera.frame_age_ms == null ? "-" : `${Math.round(camera.frame_age_ms)}ms`;
  const display = status.display_source_current || status.display_source || "single";
  const suffix = status.display_fallback_active ? " / 显示=分析流" : ` / 显示=${display}`;
  const staleLabel = status.diagnostics?.camera_lost
    ? "摄像头离线"
    : status.diagnostics?.capture_stale
      ? "采集停滞 / 等待新帧"
      : streamStateLabel(camera.stream_state);
  $("streamState").textContent = `${staleLabel} (${age})${suffix}`;
  maybeReconnectForDisplaySource(status);
  updateFrameFallbackVisibility(status);
  updateRecoveryBanner();
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
  $("detectionFps").textContent = formatFps(detectionFps);
  $("trackingFps").textContent = formatFps(trackingFps);
  $("poseFps").textContent = formatFps(poseFps);
  $("aiFps").textContent = `D:${formatFps(detectionFps)} T:${formatFps(trackingFps)} P:${formatFps(poseFps)} R:${formatFps(publishFps)}`;
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

function attachVideoFrameLoop() {
  const video = $("video");
  if (!video) {
    return;
  }
  stopOverlayLoop();
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
  updateFrameFallbackVisibility();
}

function updateVideoFps(quality) {
  const target = $("videoFps");
  if (!target) {
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
    endpoint: "/device-discovery/rescan",
    pendingText: "正在重新搜索主系统和摄像头...",
    successPrefix: "搜索完成",
    activeButtonId: "rescanDevicesBtn",
  });
}

async function autoConnectDevices() {
  return runDeviceConnectionAction({
    endpoint: "/device-discovery/connect-all",
    pendingText: "正在自动连接主系统和摄像头...",
    successPrefix: "一键连接完成",
    activeButtonId: "autoConnectDevicesBtn",
  });
}

async function connectMainSystem() {
  return runDeviceConnectionAction({
    endpoint: "/device-discovery/connect-main-system",
    pendingText: "正在连接主系统...",
    successPrefix: "主系统连接完成",
    activeButtonId: "connectMainSystemBtn",
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
  for (const id of ["rescanDevicesBtn", "autoConnectDevicesBtn", "connectMainSystemBtn"]) {
    const button = $(id);
    if (button) {
      button.disabled = disabled;
    }
  }
}

function summarizeDeviceConnectionPayload(prefix, payload) {
  const mainIp = payload?.main_system?.ip || "-";
  const cameraIp = payload?.camera?.ip || "-";
  const mainStatus = discoveryStatusLabel(payload?.main_system?.status);
  const cameraStatus = discoveryStatusLabel(payload?.camera?.status);
  const mode = payload?.applied?.mode || "all";
  if (mode === "main_system") {
    return `${prefix}：主系统 ${mainIp}（${mainStatus}）`;
  }
  return `${prefix}：主系统 ${mainIp}（${mainStatus}），摄像头 ${cameraIp}（${cameraStatus}）`;
}

function renderDeviceDiscoveryStatus(payload) {
  setText("mainSystemDiscoveryState", discoveryStatusLabel(payload?.main_system?.status));
  setText("mainSystemDiscoveryIp", payload?.main_system?.ip || "-");
  setText("cameraDiscoveryState", discoveryStatusLabel(payload?.camera?.status));
  setText("cameraDiscoveryIp", payload?.camera?.ip || "-");
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
$("cameraId")?.addEventListener("change", () => {
  state.autoFrontendConnectAttempted = false;
  state.frameFallback.lastOkAt = null;
  setFrameFallbackVisible(false);
  void refreshStatus();
  void refreshFrameFallback();
});
$("rescanDevicesBtn")?.addEventListener("click", rescanDevices);
$("autoConnectDevicesBtn")?.addEventListener("click", autoConnectDevices);
$("connectMainSystemBtn")?.addEventListener("click", connectMainSystem);
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
  const video = $("video");
  if (state.lastResult && video && !isResultExpired(state.lastResult)) {
    drawOverlay(video, state.lastResult);
  } else if (isResultExpired(state.lastResult)) {
    expireOverlayResult();
  }
});
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
setInterval(refreshStatus, 2000);
setInterval(sampleVideoQuality, 1000);
setInterval(sampleRtcStats, 1000);
startFrameFallbackLoop();
refreshStatus();
refreshDeviceDiscoveryStatus();
startEventReviewPolling();
