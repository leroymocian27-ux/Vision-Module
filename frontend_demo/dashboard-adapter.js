(function () {
  const $ = (id) => document.getElementById(id);
  const MAX_HISTORY_POINTS = 32;
  const FLASHABLE_TEXT_IDS = new Set([
    "summaryVideoValue",
    "summaryBinaryValue",
    "summaryQwenValue",
    "summaryEventValue",
    "summaryAlarmValue",
    "videoFps",
    "dashboardCaptureFps",
    "dashboardDisplayFps",
    "dashboardBinaryLatency",
    "dashboardQwenQueue",
    "testCpuUsage",
    "testGpuUsage",
    "testProcessCpuUsage",
    "testGpuMemory",
    "eventQwenStatus",
    "eventDeliveryStatus",
    "eventIncidentId",
    "eventCameraId",
    "eventTrackId",
    "eventType",
    "eventFallState",
    "eventRiskLevel",
    "eventConfidence",
    "eventStatus",
    "eventPrimaryBadge",
    "eventRiskMini",
    "eventConfidenceMini",
    "eventStageMini",
  ]);
  const flashTimers = new WeakMap();
  const previousTextValues = new Map();
  const performanceHistory = {
    cpu: [],
    gpu: [],
    processCpu: [],
    videoFps: [],
    captureFps: [],
    displayFps: [],
    binaryLatency: [],
    qwenQueue: [],
  };

  const FALL_LABELS = {
    normal: "正常监测",
    candidate: "疑似跌倒",
    confirmed: "确认跌倒",
    unstable: "姿态异常",
    falling: "疑似跌倒",
    fallen_candidate: "高风险倒地",
    fallen_confirmed: "确认跌倒",
    cooldown: "冷却观察",
  };

  const VLM_LABELS = {
    disabled: "未开启",
    pending: "等待复核",
    collecting_keyframes: "采集关键帧",
    running: "复核中",
    completed: "复核完成",
    failed: "复核失败",
    timeout: "复核超时",
    parse_failed: "解析失败",
  };

  function updateClock() {
    const now = new Date();
    setText("dashboardClock", now.toLocaleTimeString("zh-CN", { hour12: false }));
    setText("dashboardDate", now.toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      weekday: "short",
    }));
  }

  function render(snapshot) {
    const status = snapshot?.status || null;
    const control = snapshot?.control || null;
    const result = snapshot?.result || null;
    const eventModel = snapshot?.event || null;

    renderSummary(status, control, result, eventModel);
    renderLinks(status, control, eventModel);
    renderVideoOverlay(status, control, result);
    renderPipeline(status, control, result, eventModel);
    renderPerformance(status, control);
    renderQwenJson(eventModel);
    renderEventState(status, control, result, eventModel);
    renderQwenState(status, control, result, eventModel);
    renderDeliveryState(status, eventModel);
  }

  function renderSummary(status, control, result, eventModel) {
    const camera = currentCamera(status);
    const streamConnected = Boolean(control?.stream_connected || camera?.connected);
    const streamState = normalizeStreamState(camera, status, streamConnected);
    setCard("cardVideo", "summaryVideoValue", "summaryVideoMeta", streamState.label, streamState.meta, streamState.state);

    const runtime = control?.runtime || {};
    const binary = binarySnapshot(control, result);
    setCard(
      "cardBinary",
      "summaryBinaryValue",
      "summaryBinaryMeta",
      binary.label,
      compactJoin([runtime.binary_provider || "EfficientNet-B0", formatFps(runtime.binary_sample_fps ?? runtime.sample_fps, "FPS采样")]),
      binary.state,
    );

    const qwen = qwenSnapshot(control, result);
    setCard(
      "cardQwen",
      "summaryQwenValue",
      "summaryQwenMeta",
      qwen.label,
      compactJoin([runtime.vlm_model, runtime.vlm_provider]),
      qwen.state,
    );

    const event = eventSnapshot(result, eventModel);
    setCard("cardEvent", "summaryEventValue", "summaryEventMeta", event.label, event.meta, event.state);

    const alarm = alarmSnapshot(status, eventModel);
    setCard("cardAlarm", "summaryAlarmValue", "summaryAlarmMeta", alarm.label, alarm.meta, alarm.state);
  }

  function renderLinks(status, control, eventModel) {
    const camera = currentCamera(status);
    const runtime = control?.runtime || {};
    const reporter = status?.fall_event_reporter || {};
    const eventStatus = eventModel?.status || window.__VISION_EVENT_REVIEW__?.getStatus?.() || {};
    const source = camera?.source_url_masked || status?.main_stream?.source_url_masked || status?.analysis_stream?.source_url_masked || "--";

    setStateText("dashboardGo2Status", camera?.connected ? "在线" : "未连接", camera?.connected ? "on" : "off");
    setText("dashboardVideoSource", source);
    if ($("dashboardVideoSource")) $("dashboardVideoSource").title = source;
    setStateText("dashboardMainSystemStatus", mainSystemText(reporter), reporter.main_system_reachable === false ? "error" : (reporter.enabled ? "on" : "off"));
    setStateText("dashboardOllamaStatus", qwenServiceText(control), control?.qwen_enabled ? "on" : "off");
    setStateText("dashboardEventServiceStatus", eventStatus.event_pipeline_enabled ? "Ready" : "未启用", eventStatus.event_pipeline_enabled ? "on" : "off");
    setText("dashboardProviderLine", compactJoin([runtime.binary_provider, runtime.vlm_provider, runtime.vlm_model]) || "--");
  }

  function renderVideoOverlay(status, control, result) {
    const camera = currentCamera(status);
    const binary = binarySnapshot(control, result);
    const qwen = qwenSnapshot(control, result);
    const event = eventSnapshot(result, null);
    const frameAge = formatMs(camera?.frame_age_ms);
    const videoState = camera?.connected ? "Video Connected" : "等待视频";

    setText("videoCameraMeta", camera?.camera_id || control?.camera_id || "Go2 Front Camera");
    setText("videoConnectedMeta", compactJoin([videoState, frameAge && `Age ${frameAge}`]));
    setText("videoOverlayBinary", `Binary: ${binary.overlay}`);
    setText("videoOverlayQwen", `Qwen: ${qwen.overlay}`);
    setText("videoOverlayIncident", `Event: ${event.meta || "--"}`);

    const viewer = document.querySelector(".viewer");
    if (viewer) {
      viewer.dataset.alertState = event.state === "danger" ? "danger" : "idle";
    }
  }

  function renderPipeline(status, control, result, eventModel) {
    const camera = currentCamera(status);
    const binary = binarySnapshot(control, result);
    const qwen = qwenSnapshot(control, result);
    const event = eventSnapshot(result, eventModel);
    const alarm = alarmSnapshot(status, eventModel);

    setPipe("pipeVideo", camera?.connected ? "active" : "idle");
    setPipe("pipeBinary", binary.state);
    setPipe("pipeQwen", qwen.state);
    setPipe("pipeJson", eventModel?.enabled ? (event.state === "idle" ? "idle" : "success") : "idle");
    setPipe("pipeAlarm", alarm.state);
  }

  function renderPerformance(status, control) {
    const camera = currentCamera(status);
    const perf = control?.performance || {};
    const runtime = control?.runtime || {};
    const receiveFpsValue = numberOrNull(camera?.mjpeg_receive_fps);
    const publishFpsValue = numberOrNull(camera?.mjpeg_publish_fps ?? camera?.capture_fps);
    const displayStatus = displayStreamStatus(status, camera?.camera_id);
    const displayFpsValue = numberOrNull(displayStatus?.display_mjpeg_served_fps ?? displayStatus?.display_served_fps ?? displayStatus?.display_encode_fps);
    const displayEncodeMsValue = numberOrNull(displayStatus?.encode_ms);
    const captureFpsValue = numberOrNull(perf.capture_fps ?? receiveFpsValue ?? publishFpsValue ?? camera?.capture_fps);
    const binaryLatencyValue = numberOrNull(perf.binary_inference_ms_avg ?? runtime.binary_inference_latency_avg_ms ?? runtime.binary_inference_latency_ms);
    const qwenQueueValue = numberOrNull(runtime.vlm_queue_depth ?? perf.qwen?.queue_depth ?? perf.qwen?.busy);
    const videoFpsValue = numberOrNull(parseMetricValue($("videoFps")?.textContent));
    const cpuValue = numberOrNull(perf.cpu_percent);
    const gpuValue = numberOrNull(perf.gpu_util_percent);
    const processCpuValue = numberOrNull(perf.process_cpu_percent);

    setText("dashboardCaptureFps", formatFps(captureFpsValue, "FPS"));
    setTitle("dashboardCaptureFps", compactJoin([
      receiveFpsValue !== null ? `receive ${formatFps(receiveFpsValue, "FPS")}` : "",
      publishFpsValue !== null ? `publish ${formatFps(publishFpsValue, "FPS")}` : "",
      displayFpsValue !== null ? `display ${formatFps(displayFpsValue, "FPS")}` : "",
      Number.isFinite(Number(camera?.mjpeg_dropped_frames)) ? `drop ${camera.mjpeg_dropped_frames}` : "",
      formatMs(camera?.mjpeg_inter_frame_ms) && `interval ${formatMs(camera?.mjpeg_inter_frame_ms)}`,
      formatMs(camera?.mjpeg_publish_latency_ms) && `publish ${formatMs(camera?.mjpeg_publish_latency_ms)}`,
    ]));
    setText("dashboardDisplayFps", formatFps(displayFpsValue, "FPS"));
    setTitle("dashboardDisplayFps", compactJoin([
      displayStatus ? `mjpeg ${formatFps(displayStatus.display_mjpeg_served_fps, "FPS")}` : "",
      displayStatus ? `served all ${formatFps(displayStatus.display_served_fps, "FPS")}` : "",
      displayStatus ? `latest ${formatFps(displayStatus.latest_frame_served_fps, "FPS")}` : "",
      displayStatus ? `encoded ${formatFps(displayStatus.display_encode_fps, "FPS")}` : "",
      displayEncodeMsValue !== null ? `encode ${formatMs(displayEncodeMsValue)}` : "",
      displayStatus?.cache_hits != null ? `cache hit ${displayStatus.cache_hits}` : "",
    ]));
    setText("dashboardBinaryLatency", formatMs(binaryLatencyValue));
    setText("dashboardQwenQueue", qwenQueueText(runtime, perf.qwen));

    updateHexMetric("cpuMetric", "cpuGauge", "testCpuUsage", cpuValue);
    updateHexMetric("gpuMetric", "gpuGauge", "testGpuUsage", gpuValue);
    const overallMetric = [cpuValue, gpuValue].filter((value) => Number.isFinite(value));
    setPanelState("performancePanel", metricState(overallMetric.length ? Math.max(...overallMetric) : null, { low: 40, mid: 72, high: 88 }));

    setSparklineHistory("cpu", cpuValue);
    setSparklineHistory("gpu", gpuValue);
    setSparklineHistory("processCpu", processCpuValue);
    setSparklineHistory("videoFps", videoFpsValue);
    setSparklineHistory("captureFps", captureFpsValue);
    setSparklineHistory("displayFps", displayFpsValue);
    setSparklineHistory("binaryLatency", binaryLatencyValue);
    setSparklineHistory("qwenQueue", qwenQueueValue);

    renderSparkline("cpuSparkline", performanceHistory.cpu, { color: "rgba(46, 229, 157, 0.96)" });
    renderSparkline("gpuSparkline", performanceHistory.gpu, { color: "rgba(24, 191, 255, 0.96)" });
    renderSparkline("videoFpsSparkline", performanceHistory.videoFps, { color: "rgba(24, 191, 255, 0.96)" });
    renderSparkline("captureFpsSparkline", performanceHistory.captureFps, { color: "rgba(46, 229, 157, 0.92)" });
    renderSparkline("displayFpsSparkline", performanceHistory.displayFps, { color: "rgba(255, 202, 69, 0.92)" });
    renderSparkline("binaryLatencySparkline", performanceHistory.binaryLatency, { color: "rgba(255, 202, 69, 0.96)" });
    renderSparkline("qwenQueueSparkline", performanceHistory.qwenQueue, { color: "rgba(255, 91, 91, 0.92)" });

    setText("testProcessCpuUsage", formatCompactMetric("Process", processCpuValue, "%"));
    setText("testGpuMemory", formatGpuSummary(perf.gpu_memory_used_mb, perf.gpu_memory_total_mb));
    setPanelState("cpuMetric", metricState(cpuValue, { low: 40, mid: 72, high: 88 }));
    setPanelState("gpuMetric", metricState(gpuValue, { low: 45, mid: 75, high: 90 }));
  }

  function renderQwenJson(eventModel) {
    const box = $("qwenJsonBox");
    if (!box) return;
    if (!eventModel || !eventModel.enabled || eventModel.incident_id === "-") {
      box.textContent = "等待结构化结果";
      return;
    }
    const payload = {
      incident_id: emptyToNull(eventModel.incident_id),
      event_type: emptyToNull(eventModel.event_type),
      fall_state: emptyToNull(eventModel.fall_state),
      risk_level: emptyToNull(eventModel.risk_level),
      confidence: emptyToNull(eventModel.confidence),
      event_status: emptyToNull(eventModel.event_status),
      qwen_status: emptyToNull(eventModel.qwen_advisory?.status),
      delivery_status: emptyToNull(eventModel.delivery_status),
      delivery_mode: emptyToNull(eventModel.delivery_mode),
    };
    box.textContent = JSON.stringify(dropEmpty(payload), null, 2);
  }

  function renderEventState(status, control, result, eventModel) {
    const event = eventSnapshot(result, eventModel);
    const panel = document.querySelector(".event-analysis-card");
    const empty = $("eventEmptyState");
    if (panel) {
      panel.dataset.state = event.state;
    }
    if (empty) {
      if (event.label === "无活跃事件") {
        empty.textContent = "系统正在监听\n暂无活跃跌倒事件\nBinary 候选事件触发后将显示事件详情";
        empty.dataset.state = eventModel?.state === "api_error" ? "api_error" : "event_ready";
      } else {
        const confirmed = event.state === "danger";
        empty.textContent = `${confirmed ? "确认跌倒事件" : "疑似跌倒事件"}\n${event.meta || "--"}\n正在同步右侧事件详情`;
        empty.dataset.state = confirmed ? "partial_keyframes" : "event_ready";
      }
    }
    const confirmed = event.state === "danger";
    const warning = event.state === "warning";
    setText("eventPrimaryBadge", confirmed ? "CONFIRMED FALL" : (warning ? "FALL CANDIDATE" : "NO ACTIVE EVENT"));
    setText("eventRiskMini", emptyToNull(eventModel?.risk_level) || (warning ? "WATCH" : "LOW"));
    setText("eventConfidenceMini", emptyToNull(eventModel?.confidence) || "--");
    setText("eventStageMini", confirmed ? "ALARM" : (warning ? "REVIEW" : "LISTENING"));
  }

  function renderDeliveryState(status, eventModel) {
    const delivery = alarmSnapshot(status, eventModel);
    const panel = document.querySelector(".alarm-card");
    const statusBox = $("eventDeliveryStatus");
    if (panel) {
      panel.dataset.state = delivery.state;
    }
    if (statusBox) {
      const reporter = status?.fall_event_reporter || {};
      if (delivery.state === "success") {
        statusBox.textContent = "READY";
      } else if (delivery.state === "error") {
        statusBox.textContent = "FAILED";
      } else if (!reporter.enabled) {
        statusBox.textContent = "NOT CONFIGURED";
      } else if (delivery.state === "active") {
        statusBox.textContent = "SENDING";
      } else {
        statusBox.textContent = delivery.label;
      }
      statusBox.title = compactJoin([delivery.label, delivery.meta]) || delivery.label;
    }
    renderDeliveryTrack(status, eventModel, delivery);
  }

  function renderQwenState(status, control, result, eventModel) {
    const qwen = qwenSnapshot(control, result);
    const panel = document.querySelector(".qwen-card");
    const statusBox = $("eventQwenStatus");
    const sceneSummary = $("eventQwenSceneSummary");
    const postureMovement = $("eventQwenPostureMovement");
    const careAdvice = $("eventQwenCareAdvice");
    const uncertainty = $("eventQwenUncertainty");
    if (panel) {
      panel.dataset.state = qwen.state;
    }
    if (statusBox) {
      if (!control?.qwen_enabled) {
        statusBox.textContent = "DISABLED";
      } else if (qwen.state === "warning") {
        statusBox.textContent = "REVIEWING";
      } else if (qwen.state === "success") {
        statusBox.textContent = "COMPLETED";
      } else if (qwen.state === "error") {
        statusBox.textContent = "FAILED";
      } else {
        statusBox.textContent = "STANDBY";
      }
      statusBox.title = compactJoin([qwen.label, qwen.overlay]) || qwen.label;
    }
    const hasEvent = Boolean(eventModel?.incident_id && eventModel.incident_id !== "-");
    if (!hasEvent) {
      if (sceneSummary) sceneSummary.textContent = control?.qwen_enabled ? "等待 Binary 候选事件" : "千问复核尚未开启";
      if (postureMovement) postureMovement.textContent = "—";
      if (careAdvice) careAdvice.textContent = "—";
      if (uncertainty) uncertainty.textContent = "—";
      return;
    }
    if (sceneSummary && (!sceneSummary.textContent || sceneSummary.textContent === "-" || sceneSummary.textContent === "--")) {
      sceneSummary.textContent = "正在同步关键帧复核结果";
    }
    if (postureMovement && (!postureMovement.textContent || postureMovement.textContent === "-" || postureMovement.textContent === "--")) {
      postureMovement.textContent = "—";
    }
    if (careAdvice && (!careAdvice.textContent || careAdvice.textContent === "-" || careAdvice.textContent === "--")) {
      careAdvice.textContent = "—";
    }
    if (uncertainty && (!uncertainty.textContent || uncertainty.textContent === "-" || uncertainty.textContent === "--")) {
      uncertainty.textContent = "—";
    }
  }

  function currentCamera(status) {
    const cameraId = $("cameraId")?.value?.trim();
    return (status?.cameras || []).find((item) => item.camera_id === cameraId)
      || status?.cameras?.[0]
      || null;
  }

  function displayStreamStatus(status, cameraId) {
    const cameras = status?.display_stream?.cameras || {};
    if (cameraId && cameras[cameraId]) {
      return cameras[cameraId];
    }
    return Object.values(cameras)[0] || null;
  }

  function normalizeStreamState(camera, status, streamConnected) {
    if (status?.diagnostics?.camera_lost || camera?.last_error) {
      return { label: "异常", meta: camera?.last_error || "摄像头离线", state: "error" };
    }
    if (streamConnected) {
      const receiveFps = numberOrNull(camera?.mjpeg_receive_fps);
      const publishFps = numberOrNull(camera?.mjpeg_publish_fps ?? camera?.capture_fps);
      return {
        label: "已连接",
        meta: compactJoin([
          camera?.source_protocol || "视频流",
          formatFps(receiveFps ?? publishFps ?? camera?.capture_fps, "FPS"),
        ]),
        state: "active",
      };
    }
    if (camera?.stream_state === "connecting" || camera?.stream_state === "reconnecting") {
      return { label: "连接中", meta: camera.stream_state, state: "warning" };
    }
    return { label: "未连接", meta: "--", state: "idle" };
  }

  function binarySnapshot(control, result) {
    const runtime = control?.runtime || {};
    const label = targetDecision(result)?.binary_label || runtime.binary_last_label;
    const probability = targetProbability(result) ?? runtime.binary_last_probability;
    if (runtime.last_error && control?.binary_enabled) {
      return { label: "异常", overlay: runtime.last_error, state: "error" };
    }
    if (!control?.binary_enabled) {
      return { label: "已停止", overlay: "OFF", state: "idle" };
    }
    if (runtime.binary_model_loading) {
      return { label: "加载中", overlay: "LOADING", state: "active" };
    }
    if (String(label).toUpperCase() === "FALL") {
      return { label: probabilityText("FALL", probability), overlay: probabilityText("FALL", probability), state: "warning" };
    }
    if (String(label).toUpperCase() === "NON_FALL") {
      return { label: "运行中", overlay: probabilityText("NON_FALL", probability), state: "active" };
    }
    return { label: "运行中", overlay: "--", state: "active" };
  }

  function qwenSnapshot(control, result) {
    const runtime = control?.runtime || {};
    const decision = targetDecision(result);
    const raw = decision?.vlm_status || (runtime.vlm_active_count ? "running" : null);
    if (!control?.qwen_enabled) {
      return { label: "未开启", overlay: "STANDBY", state: "idle" };
    }
    if (runtime.vlm_active_count || raw === "running") {
      return { label: "复核中", overlay: "REVIEWING", state: "warning" };
    }
    if (raw && raw !== "disabled") {
      const state = ["failed", "timeout", "parse_failed"].includes(raw) ? "error" : "success";
      return { label: VLM_LABELS[raw] || raw, overlay: VLM_LABELS[raw] || raw, state };
    }
    return { label: "待机", overlay: "STANDBY", state: "active" };
  }

  function eventSnapshot(result, eventModel) {
    const decision = targetDecision(result);
    const incidentId = decision?.incident_id || eventModel?.incident_id;
    if (decision?.event_created === true || incidentId && incidentId !== "-") {
      const fallState = decision?.fall_state || eventModel?.fall_state;
      const risk = decision?.risk_level || eventModel?.risk_level;
      const confirmed = fallState === "fallen_confirmed" || fallState === "confirmed" || risk === "critical";
      return {
        label: confirmed ? "确认跌倒" : "疑似跌倒",
        meta: shortId(incidentId),
        state: confirmed ? "danger" : "warning",
      };
    }
    if (eventModel?.state === "api_error") {
      return { label: "事件异常", meta: "Event API", state: "error" };
    }
    return { label: "无活跃事件", meta: "--", state: "idle" };
  }

  function alarmSnapshot(status, eventModel) {
    const reporter = status?.fall_event_reporter || {};
    const delivery = eventModel?.delivery || {};
    if (delivery?.has_record) {
      const raw = String(delivery.status || "").toLowerCase();
      if (raw === "sent" || raw === "dry_run_sent") {
        return { label: delivery.status_text, meta: delivery.mode_text, state: raw === "sent" ? "success" : "warning" };
      }
      if (raw === "failed") return { label: "推送失败", meta: delivery.last_error_text || "--", state: "error" };
      if (raw === "sending" || raw === "pending" || raw === "retry") return { label: delivery.status_text, meta: delivery.mode_text, state: "active" };
    }
    if (reporter.enabled) {
      if (reporter.main_system_reachable === false) {
        return { label: "离线", meta: "主系统不可达", state: "error" };
      }
      if (reporter.main_system_reachable === true) {
        return { label: "已连接", meta: reporter.endpoint_path || "Alarm API Ready", state: "success" };
      }
      return { label: "已配置", meta: reporter.endpoint_path || "等待健康检查", state: "idle" };
    }
    return { label: "未启用", meta: "--", state: "idle" };
  }

  function targetDecision(result) {
    const objects = result?.objects || [];
    const target = objects.find((item) => item?.is_target === true) || objects[0];
    return target?.fall_decision || null;
  }

  function targetProbability(result) {
    const objects = result?.objects || [];
    const target = objects.find((item) => item?.is_target === true) || objects[0];
    return target?.temporal?.fall_probability ?? target?.fall_decision?.binary_probability ?? null;
  }

  function qwenServiceText(control) {
    const runtime = control?.runtime || {};
    if (!control?.qwen_enabled) return "未开启";
    return compactJoin([runtime.vlm_provider || "运行中", runtime.vlm_model]) || "运行中";
  }

  function mainSystemText(reporter) {
    if (!reporter?.enabled) return "未启用";
    if (reporter.main_system_reachable === false) return "离线";
    if (reporter.main_system_reachable === true) return "已连接";
    return "已启用";
  }

  function qwenQueueText(runtime, qwenPerf) {
    const active = runtime?.vlm_active_count ?? qwenPerf?.busy;
    const depth = runtime?.vlm_queue_depth ?? qwenPerf?.queue_depth;
    if (active == null && depth == null) return "--";
    return `active ${active ?? 0} / queue ${depth ?? 0}`;
  }

  function setCard(cardId, valueId, metaId, value, meta, state) {
    const card = $(cardId);
    if (card) card.dataset.state = state || "idle";
    setText(valueId, value || "--");
    setText(metaId, meta || "--");
  }

  function setPipe(id, state) {
    const element = $(id);
    if (element) element.dataset.state = state || "idle";
  }

  function setStateText(id, value, stateName) {
    const element = $(id);
    if (!element) return;
    element.textContent = value || "--";
    element.dataset.state = stateName || "";
  }

  function setText(id, value) {
    const element = $(id);
    if (!element) return;
    const next = value == null || value === "" ? "--" : String(value);
    const prev = previousTextValues.get(id);
    element.textContent = next;
    if (FLASHABLE_TEXT_IDS.has(id) && prev !== undefined && prev !== next) {
      element.dataset.flash = "1";
      const existingTimer = flashTimers.get(element);
      if (existingTimer) {
        clearTimeout(existingTimer);
      }
      const timer = setTimeout(() => {
        element.dataset.flash = "0";
        flashTimers.delete(element);
      }, 420);
      flashTimers.set(element, timer);
    }
    previousTextValues.set(id, next);
  }

  function setTitle(id, value) {
    const element = $(id);
    if (!element) return;
    element.title = value || "";
  }

  function setPanelState(id, state) {
    const element = $(id);
    if (element) {
      element.dataset.state = state || "idle";
    }
  }

  function renderDeliveryTrack(status, eventModel, delivery) {
    const deliveryStatus = String(eventModel?.delivery?.status || eventModel?.delivery_status || "").toLowerCase();
    const hasEvent = Boolean(eventModel?.incident_id && eventModel.incident_id !== "-");
    const hasRecord = Boolean(eventModel?.delivery?.has_record);
    const success = ["sent", "dry_run_sent", "delivered"].includes(deliveryStatus) || delivery.state === "success";
    const error = ["failed", "error"].includes(deliveryStatus) || delivery.state === "error";
    const active = ["sending", "pending", "retry"].includes(deliveryStatus) || delivery.state === "active";
    setDeliveryStep("deliveryStepEvent", hasEvent ? "success" : "idle", hasEvent ? "ready" : "idle");
    setDeliveryStep("deliveryStepPost", success || active || error || hasRecord ? (error ? "error" : (success ? "success" : "active")) : "idle", hasRecord ? deliveryStatus || "record" : "idle");
    setDeliveryStep("deliveryStepAck", success ? "success" : (error ? "error" : "idle"), success ? "ack" : (error ? "failed" : "idle"));
    setDeliveryStep("deliveryStepDelivered", success ? "success" : (error ? "error" : "idle"), success ? "done" : (error ? "error" : "idle"));
  }

  function setDeliveryStep(id, state, label) {
    const element = $(id);
    if (!element) {
      return;
    }
    element.dataset.state = state || "idle";
    const em = element.querySelector("em");
    if (em) {
      em.textContent = label || "idle";
    }
  }

  function numberOrNull(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function parseMetricValue(text) {
    if (text == null) {
      return null;
    }
    const match = String(text).match(/-?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  }

  function metricState(value, thresholds) {
    if (!Number.isFinite(value)) {
      return "idle";
    }
    if (thresholds?.high !== undefined && value >= thresholds.high) {
      return "error";
    }
    if (thresholds?.mid !== undefined && value >= thresholds.mid) {
      return "warning";
    }
    if (thresholds?.low !== undefined && value >= thresholds.low) {
      return "active";
    }
    return "success";
  }

  function setSparklineHistory(key, value) {
    if (!performanceHistory[key] || !Number.isFinite(value)) {
      return;
    }
    const bucket = performanceHistory[key];
    bucket.push(Number(value));
    while (bucket.length > MAX_HISTORY_POINTS) {
      bucket.shift();
    }
  }

  function renderSparkline(id, values, options = {}) {
    const element = $(id);
    if (!element) {
      return;
    }
    const series = values.filter((value) => Number.isFinite(value));
    if (!series.length) {
      element.classList.add("is-empty");
      element.textContent = "—";
      return;
    }
    element.classList.remove("is-empty");
    const min = Math.min(...series);
    const max = Math.max(...series);
    const span = max - min || Math.max(Math.abs(max), 1);
    const width = 100;
    const height = 28;
    const paddingY = 3;
    const points = series.map((value, index) => {
      const x = series.length === 1 ? width : (index / (series.length - 1)) * width;
      const y = height - paddingY - (((value - min) / span) * (height - paddingY * 2));
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(" ");
    const lastY = height - paddingY - (((series[series.length - 1] - min) / span) * (height - paddingY * 2));
    const areaPath = `M 0 ${height - paddingY} L ${points.replaceAll(" ", " L ")} L ${width} ${height - paddingY} Z`;
    const color = options.color || "rgba(24, 191, 255, 0.92)";
    const fill = options.fill || "rgba(24, 191, 255, 0.12)";
    element.style.setProperty("--sparkline-color", color);
    element.style.setProperty("--sparkline-fill", fill);
    element.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
        <path class="sparkline-fill" d="${areaPath}"></path>
        <polyline points="${points}"></polyline>
        <circle cx="${width}" cy="${lastY.toFixed(2)}" r="1.8" fill="${color}"></circle>
      </svg>
    `;
  }

  function updateHexMetric(metricId, gaugeId, valueId, value) {
    const metric = $(metricId);
    const gauge = $(gaugeId);
    if (metric) {
      metric.dataset.state = metricState(value, { low: 40, mid: 70, high: 88 });
    }
    if (gauge) {
      const numeric = Number.isFinite(value) ? Math.max(0, Math.min(100, Number(value))) : 0;
      gauge.style.setProperty("--gauge-fill", `${numeric}%`);
      gauge.dataset.state = metric?.dataset.state || "idle";
    }
    setText(valueId, Number.isFinite(value) ? `${Math.round(value)}%` : "--");
  }

  function formatCompactMetric(prefix, value, suffix) {
    if (!Number.isFinite(value)) {
      return "--";
    }
    return `${prefix} ${Math.round(value)}${suffix || ""}`;
  }

  function formatGpuSummary(used, total) {
    const usedNumber = Number(used);
    const totalNumber = Number(total);
    if (!Number.isFinite(usedNumber) && !Number.isFinite(totalNumber)) {
      return "--";
    }
    if (Number.isFinite(usedNumber) && Number.isFinite(totalNumber) && totalNumber > 0) {
      return `${Math.round(usedNumber)}MB / ${Math.round(totalNumber)}MB`;
    }
    if (Number.isFinite(usedNumber)) {
      return `${Math.round(usedNumber)}MB`;
    }
    return "--";
  }

  function formatFps(value, suffix = "") {
    const number = Number(value);
    if (!Number.isFinite(number)) return "";
    return `${number.toFixed(1)}${suffix ? ` ${suffix}` : ""}`;
  }

  function formatMs(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "";
    return `${Math.max(0, Math.round(number))}ms`;
  }

  function probabilityText(label, value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return label;
    return `${label} ${number.toFixed(2)}`;
  }

  function compactJoin(items) {
    return items.filter((item) => item !== null && item !== undefined && item !== "").join(" / ");
  }

  function shortId(value) {
    const text = String(value || "--");
    return text.length > 18 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text;
  }

  function emptyToNull(value) {
    return value === undefined || value === null || value === "-" || value === "--" ? null : value;
  }

  function dropEmpty(payload) {
    return Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== null));
  }

  updateClock();
  window.setInterval(updateClock, 1000);
  window.__VISION_DASHBOARD__ = Object.freeze({ render, updateClock, labels: { fall: FALL_LABELS, vlm: VLM_LABELS } });
})();
