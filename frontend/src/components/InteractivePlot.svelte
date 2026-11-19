<script>
  import { onMount, afterUpdate, createEventDispatcher } from 'svelte';

  /**
   * datasets: Array of panel objects:
   *   {
   *     id, title, p, q, n_start, n_end,
   *     nodeSize, opacity,
   *     visibleLoops: { [loop_id]: boolean },
   *     loopColors: { [loop_id]: string },
   *     data: { loops: [...], points: { n: [...], steps: [...], loop_id: [...] }, max_observed_steps }
   *   }
   */
  export let datasets = [];
  export let syncedViewport = null;
  export let syncZoom = false;
  export let focusedNode = null; // { n, steps, panelId }

  const dispatch = createEventDispatcher();

  let canvas;
  let containerWidth = 900;
  let windowHeight = typeof window !== 'undefined' ? window.innerHeight : 800;
  let showExtraTools = false;
  $: containerHeight = Math.max(
    300,
    Math.min(680, Math.max(300, windowHeight - 175), Math.round(containerWidth * (1000 / 1800)))
  );

  const MARGIN = { top: 28, right: 28, bottom: 52, left: 68 };

  // Viewport in data coordinates: { xMin, xMax, yMin, yMax }
  let viewport = { xMin: 0, xMax: 10000, yMin: 0, yMax: 300 };
  let defaultViewport = { xMin: 0, xMax: 10000, yMin: 0, yMax: 300 };

  let isDragging = false;
  let dragStart = { x: 0, y: 0, xMin: 0, xMax: 0, yMin: 0, yMax: 0 };

  let hoveredPoint = null; // { n, steps, loop_id, color, datasetTitle, datasetIndex, screenX, screenY }
  let contextMenu = null; // { x, y, point }
  let highlightedHeight = null; // number | null
  let highlightedSpine = null; // { seedA, d, hA, cA, color } | null
  let logScaleX = false; // Toggle between Linear N and Logarithmic N
  let showGuideLines = true; // Show parallel straight-line / log-curve guide lines when logScaleX is active
  let showSeaLevel = false; // Show vertical Sea-Level line at N = max(Q)
  let primitiveOnly = false; // Filter to show only primitive layer nodes: gcd(n, core_p(gcd(Q))) == 1

  function gcdInt(a, b) {
    let x = Math.abs(Math.trunc(a));
    let y = Math.abs(Math.trunc(b));
    while (y !== 0) {
      const t = x % y;
      x = y;
      y = t;
    }
    return x;
  }

  function getDatasetCoreQ(ds) {
    const pVal = Math.max(2, Number(ds?.p || 3));
    const qs = (ds?.q || []).slice(1).map((v) => Math.abs(Number(v) || 0)).filter((v) => v > 0);
    if (qs.length === 0) return { maxQ: 1, coreQ: 1 };
    const maxQ = Math.max(...qs);
    let g = qs[0];
    for (let i = 1; i < qs.length; i++) g = gcdInt(g, qs[i]);
    while (g > 1 && g % pVal === 0) {
      g = Math.floor(g / pVal);
    }
    return { maxQ, coreQ: Math.max(1, g) };
  }

  // Compute default bounds whenever datasets change their underlying range
  let lastRangeSignature = '';
  $: {
    const sig = datasets
      .map((d) => `${d.id}:${d.data?.n_start || d.n_start}-${d.data?.n_end || d.n_end}-${d.data?.max_observed_steps || 0}`)
      .join('|');
    if (sig && sig !== lastRangeSignature) {
      lastRangeSignature = sig;
      recomputeDefaultBounds(true);
    }
  }

  $: if (syncZoom && syncedViewport) {
    if (
      syncedViewport.xMin !== viewport.xMin ||
      syncedViewport.xMax !== viewport.xMax ||
      syncedViewport.yMin !== viewport.yMin ||
      syncedViewport.yMax !== viewport.yMax
    ) {
      viewport = { ...syncedViewport };
      drawPlot();
    }
  }

  $: if (focusedNode) {
    centerOnNode(focusedNode.n, focusedNode.steps);
  }

  function recomputeDefaultBounds(resetCurrent = false) {
    let xMin = Infinity;
    let xMax = -Infinity;
    let yMax = 50;

    for (const ds of datasets) {
      if (!ds.data) continue;
      const start = ds.data.n_start <= 1 ? 0 : ds.data.n_start;
      const end = ds.data.n_end;
      if (start < xMin) xMin = start;
      if (end > xMax) xMax = end;
      const maxSt = ds.data.max_observed_steps || 50;
      if (maxSt > yMax) yMax = maxSt;
    }

    if (!isFinite(xMin)) xMin = 0;
    if (!isFinite(xMax) || xMax <= xMin) xMax = xMin + 10000;
    const yTop = Math.ceil((yMax * 1.18) / 50) * 50;

    defaultViewport = { xMin, xMax, yMin: 0, yMax: Math.max(yTop, 50) };
    if (resetCurrent) {
      setViewport({ ...defaultViewport }, false);
    }
  }

  function clampViewport(vp) {
    const minXBound = logScaleX ? 1 : 0;
    const minYBound = 0;
    const xSpan = Math.max(logScaleX ? 1 : 10, vp.xMax - vp.xMin);
    const ySpan = Math.max(5, vp.yMax - vp.yMin);
    const clampedXMin = Math.max(minXBound, vp.xMin);
    const clampedYMin = Math.max(minYBound, vp.yMin);
    return {
      xMin: clampedXMin,
      xMax: clampedXMin + xSpan,
      yMin: clampedYMin,
      yMax: clampedYMin + ySpan,
    };
  }

  function setViewport(newVp, notifySync = true) {
    viewport = clampViewport(newVp);
    if (notifySync && syncZoom) {
      dispatch('viewportChange', { ...viewport });
    }
    drawPlot();
  }

  export function resetZoom() {
    recomputeDefaultBounds(false);
    setViewport({ ...defaultViewport }, true);
  }

  export function zoomByFactor(factor, centerXRatio = 0.5, centerYRatio = 0.5, axisMode = 'both') {
    const { xMin, xMax, yMin, yMax } = viewport;
    const ySpan = yMax - yMin;
    const anchorY = yMin + ySpan * centerYRatio;

    let newXMin = xMin;
    let newXMax = xMax;
    let newYMin = yMin;
    let newYMax = yMax;

    if (axisMode === 'both' || axisMode === 'x') {
      if (logScaleX) {
        const lMin = Math.log10(Math.max(1, xMin));
        const lMax = Math.log10(Math.max(10, xMax));
        const lSpan = Math.max(0.2, (lMax - lMin) * factor);
        const anchorL = lMin + (lMax - lMin) * centerXRatio;
        const nextLMin = Math.max(0, anchorL - lSpan * centerXRatio);
        newXMin = Math.pow(10, nextLMin);
        newXMax = Math.pow(10, nextLMin + lSpan);
      } else {
        const xSpan = xMax - xMin;
        const anchorX = xMin + xSpan * centerXRatio;
        const nextXSpan = Math.max(10, xSpan * factor);
        newXMin = Math.max(0, anchorX - nextXSpan * centerXRatio);
        newXMax = newXMin + nextXSpan;
      }
    }
    if (axisMode === 'both' || axisMode === 'y') {
      const nextYSpan = Math.max(5, ySpan * factor);
      newYMin = Math.max(0, anchorY - nextYSpan * centerYRatio);
      newYMax = newYMin + nextYSpan;
    }

    setViewport({ xMin: newXMin, xMax: newXMax, yMin: newYMin, yMax: newYMax }, true);
  }

  function centerOnNode(n, steps) {
    const xSpan = Math.max(100, (viewport.xMax - viewport.xMin) * 0.4);
    const ySpan = Math.max(30, (viewport.yMax - viewport.yMin) * 0.4);
    setViewport(
      {
        xMin: Math.max(0, n - xSpan / 2),
        xMax: Math.max(0, n - xSpan / 2) + xSpan,
        yMin: Math.max(0, steps - ySpan / 2),
        yMax: Math.max(0, steps - ySpan / 2) + ySpan,
      },
      true
    );
  }

  function dataToScreenX(x, plotW, vp = viewport, isLog = logScaleX, leftMargin = MARGIN.left) {
    if (isLog) {
      const lMin = Math.log10(Math.max(1, vp.xMin));
      const lMax = Math.log10(Math.max(10, vp.xMax));
      const lx = Math.log10(Math.max(1, x));
      return leftMargin + ((lx - lMin) / Math.max(1e-9, lMax - lMin)) * plotW;
    }
    return leftMargin + ((x - vp.xMin) / Math.max(1e-9, vp.xMax - vp.xMin)) * plotW;
  }

  function dataToScreenY(y, plotH, vp = viewport, topMargin = MARGIN.top) {
    return topMargin + plotH - ((y - vp.yMin) / Math.max(1e-9, vp.yMax - vp.yMin)) * plotH;
  }

  function screenToDataX(px, plotW) {
    const ratio = (px - MARGIN.left) / Math.max(1, plotW);
    if (logScaleX) {
      const lMin = Math.log10(Math.max(1, viewport.xMin));
      const lMax = Math.log10(Math.max(10, viewport.xMax));
      return Math.pow(10, lMin + ratio * (lMax - lMin));
    }
    return viewport.xMin + ratio * (viewport.xMax - viewport.xMin);
  }

  function screenToDataY(py, plotH) {
    return viewport.yMin + ((MARGIN.top + plotH - py) / plotH) * (viewport.yMax - viewport.yMin);
  }

  function computeLogTicks(min, max) {
    const effMin = Math.max(1, min);
    const effMax = Math.max(effMin * 1.1, max);
    const pMin = Math.floor(Math.log10(effMin));
    const pMax = Math.ceil(Math.log10(effMax));
    const ticks = [];
    const spanDecades = pMax - pMin;
    const multipliers = spanDecades <= 3 ? [1, 2, 3, 5] : spanDecades <= 6 ? [1, 2, 5] : [1];
    for (let exp = pMin; exp <= pMax; exp++) {
      const base = Math.pow(10, exp);
      for (const m of multipliers) {
        const v = Math.round(base * m);
        if (v >= effMin && v <= effMax) {
          ticks.push(v);
        }
      }
    }
    if (ticks.length === 0) return [Math.round(effMin), Math.round(effMax)];
    return ticks;
  }

  function computeNiceTicks(min, max, targetCount = 10, isLog = false) {
    if (isLog) return computeLogTicks(min, max);
    const span = max - min;
    if (span <= 0 || !isFinite(span)) return [min];
    const rawStep = span / targetCount;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const residual = rawStep / mag;
    let step;
    if (residual > 5) step = 10 * mag;
    else if (residual > 2) step = 5 * mag;
    else if (residual > 1) step = 2 * mag;
    else step = mag;

    const first = Math.ceil(min / step) * step;
    const ticks = [];
    for (let v = first; v <= max + step * 1e-6; v += step) {
      ticks.push(Number(v.toFixed(6)));
    }
    return ticks;
  }

  function toggleLogScaleX() {
    logScaleX = !logScaleX;
    if (logScaleX && viewport.xMin < 1) {
      viewport = { ...viewport, xMin: 1 };
    } else if (!logScaleX && viewport.xMin === 1 && defaultViewport.xMin === 0) {
      viewport = { ...viewport, xMin: 0 };
    }
    drawPlot();
  }

  function toggleSpineFromPoint(pt) {
    if (!pt) return;
    const d = Math.max(2, (pt.p || 3) - 1);
    let seedA = pt.n;
    let kShift = 0;
    while (seedA > 0 && seedA % d === 0) {
      seedA = Math.floor(seedA / d);
      kShift += 1;
    }
    const hA = Math.max(0, pt.steps - kShift);
    const cA = hA - Math.log(seedA) / Math.log(d);
    if (highlightedSpine && highlightedSpine.seedA === seedA && highlightedSpine.d === d) {
      highlightedSpine = null;
    } else {
      highlightedSpine = {
        seedA,
        d,
        hA,
        cA,
        color: '#dc2626',
      };
    }
    contextMenu = null;
    drawPlot();
  }

  function drawPlot() {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const width = containerWidth;
    const height = containerHeight;

    if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
    }

    const ctx = canvas.getContext('2d');
    ctx.save();
    ctx.scale(dpr, dpr);

    // Clear background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);

    const plotW = Math.max(50, width - MARGIN.left - MARGIN.right);
    const plotH = Math.max(50, height - MARGIN.top - MARGIN.bottom);

    // Draw grid lines
    const xTicks = computeNiceTicks(viewport.xMin, viewport.xMax, 10, logScaleX);
    const yTicks = computeNiceTicks(viewport.yMin, viewport.yMax, 7, false);

    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 0.7;
    ctx.setLineDash([2, 3]);

    for (const xt of xTicks) {
      const sx = dataToScreenX(xt, plotW);
      if (sx >= MARGIN.left && sx <= MARGIN.left + plotW) {
        ctx.beginPath();
        ctx.moveTo(sx, MARGIN.top);
        ctx.lineTo(sx, MARGIN.top + plotH);
        ctx.stroke();
      }
    }

    for (const yt of yTicks) {
      const sy = dataToScreenY(yt, plotH);
      if (sy >= MARGIN.top && sy <= MARGIN.top + plotH) {
        ctx.beginPath();
        ctx.moveTo(MARGIN.left, sy);
        ctx.lineTo(MARGIN.left + plotW, sy);
        ctx.stroke();
      }
    }
    ctx.setLineDash([]);

    // Clip to plot area for data points
    ctx.save();
    ctx.beginPath();
    ctx.rect(MARGIN.left, MARGIN.top, plotW, plotH);
    ctx.clip();

    // Optional parallel guide lines h(n) = log_d(n) + C in log-X mode
    if (logScaleX && showGuideLines && datasets.length > 0) {
      const primaryP = Number(datasets[0]?.p || 3);
      const d = Math.max(2, primaryP - 1);
      const deltaC = Math.max(2, Math.round(1 + Math.log(primaryP) / Math.log(d)));
      const x1 = Math.max(1, viewport.xMin);
      const x2 = Math.max(10, viewport.xMax);
      const logD1 = Math.log(x1) / Math.log(d);
      const logD2 = Math.log(x2) / Math.log(d);

      ctx.strokeStyle = 'rgba(100, 116, 139, 0.28)';
      ctx.lineWidth = 1.1;
      ctx.setLineDash([5, 5]);
      for (let c = -20; c <= viewport.yMax + 20; c += deltaC * 2) {
        const y1 = logD1 + c;
        const y2 = logD2 + c;
        ctx.beginPath();
        ctx.moveTo(dataToScreenX(x1, plotW), dataToScreenY(y1, plotH));
        ctx.lineTo(dataToScreenX(x2, plotW), dataToScreenY(y2, plotH));
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    // Optional Sea-Level boundary N = max(Q)
    if (showSeaLevel && datasets.length > 0) {
      const { maxQ } = getDatasetCoreQ(datasets[0]);
      if (maxQ >= viewport.xMin && maxQ <= viewport.xMax) {
        const seaX = dataToScreenX(maxQ, plotW);
        ctx.fillStyle = 'rgba(14, 165, 233, 0.09)';
        ctx.fillRect(MARGIN.left, MARGIN.top, Math.max(0, seaX - MARGIN.left), plotH);
        ctx.strokeStyle = '#0284c7';
        ctx.lineWidth = 2.0;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(seaX, MARGIN.top);
        ctx.lineTo(seaX, MARGIN.top + plotH);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#0369a1';
        ctx.font = 'bold 11px sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(`海面 N = q (${maxQ.toLocaleString()})`, seaX + 5, MARGIN.top + 6);
      }
    }

    // Optional horizontal highlight line for "same height"
    if (highlightedHeight !== null) {
      const hy = dataToScreenY(highlightedHeight, plotH);
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(MARGIN.left, hy);
      ctx.lineTo(MARGIN.left + plotW, hy);
      ctx.stroke();
    }

    // Optional highlighted spine n_k = a * d^k (straight line in log-X, log curve in linear-X)
    if (highlightedSpine !== null) {
      const { seedA, d, hA, cA, color } = highlightedSpine;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      if (logScaleX) {
        const x1 = Math.max(1, viewport.xMin);
        const x2 = Math.max(10, viewport.xMax);
        const y1 = Math.log(x1) / Math.log(d) + cA;
        const y2 = Math.log(x2) / Math.log(d) + cA;
        ctx.moveTo(dataToScreenX(x1, plotW), dataToScreenY(y1, plotH));
        ctx.lineTo(dataToScreenX(x2, plotW), dataToScreenY(y2, plotH));
      } else {
        const stepsCount = 180;
        const xStart = Math.max(1, viewport.xMin);
        const xEnd = Math.max(xStart + 10, viewport.xMax);
        for (let s = 0; s <= stepsCount; s++) {
          const xv = xStart + ((xEnd - xStart) * s) / stepsCount;
          const yv = Math.log(xv) / Math.log(d) + cA;
          const sx = dataToScreenX(xv, plotW);
          const sy = dataToScreenY(yv, plotH);
          if (s === 0) ctx.moveTo(sx, sy);
          else ctx.lineTo(sx, sy);
        }
      }
      ctx.stroke();
      ctx.setLineDash([]);

      // Draw exact spine nodes n_k = seedA * d^k
      ctx.fillStyle = color;
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.5;
      let nk = seedA;
      let hk = hA;
      while (nk <= viewport.xMax * 1.05 && hk <= viewport.yMax + 50) {
        if (nk >= Math.max(1, viewport.xMin)) {
          const sx = dataToScreenX(nk, plotW);
          const sy = dataToScreenY(hk, plotH);
          ctx.beginPath();
          ctx.arc(sx, sy, 5.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
        }
        nk *= d;
        hk += 1;
      }
    }

    // Draw points for each dataset
    for (let dIdx = 0; dIdx < datasets.length; dIdx++) {
      const ds = datasets[dIdx];
      if (!ds.data || !ds.data.points) continue;

      const ptsN = ds.data.points.n;
      const ptsSteps = ds.data.points.steps;
      const ptsLoop = ds.data.points.loop_id;
      const radius = Math.max(0.8, Number(ds.nodeSize || 2.5));
      const alpha = Number(ds.opacity ?? 0.85);

      // Group visible points in current viewport by loop_id for fast batched path drawing
      const { coreQ } = getDatasetCoreQ(ds);
      const buckets = new Map();
      for (let i = 0; i < ptsN.length; i++) {
        const nVal = ptsN[i];
        if (nVal < viewport.xMin || nVal > viewport.xMax) continue;
        if (primitiveOnly && coreQ > 1 && gcdInt(nVal, coreQ) !== 1) continue;
        const stVal = ptsSteps[i];
        if (stVal < 0 || stVal < viewport.yMin || stVal > viewport.yMax) continue;
        const lid = ptsLoop[i];
        if (ds.visibleLoops && ds.visibleLoops[lid] === false) continue;

        let arr = buckets.get(lid);
        if (!arr) {
          arr = [];
          buckets.set(lid, arr);
        }
        arr.push(i);
      }

      ctx.globalAlpha = alpha;
      for (const [lid, indices] of buckets.entries()) {
        const color = ds.loopColors?.[lid] || '#0072B2';
        ctx.fillStyle = color;
        ctx.beginPath();
        for (let k = 0; k < indices.length; k++) {
          const idx = indices[k];
          const sx = dataToScreenX(ptsN[idx], plotW);
          const sy = dataToScreenY(ptsSteps[idx], plotH);
          ctx.moveTo(sx + radius, sy);
          ctx.arc(sx, sy, radius, 0, Math.PI * 2);
        }
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1.0;

    // Highlight focused node if any
    if (focusedNode) {
      const fx = dataToScreenX(focusedNode.n, plotW);
      const fy = dataToScreenY(focusedNode.steps, plotH);
      ctx.strokeStyle = '#dc2626';
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(fx, fy, 8, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Highlight hovered point
    if (hoveredPoint) {
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = 2;
      ctx.fillStyle = hoveredPoint.color;
      ctx.beginPath();
      ctx.arc(hoveredPoint.screenX, hoveredPoint.screenY, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }

    ctx.restore(); // end clip

    // Draw border & inward ticks matching reference iter.png
    ctx.strokeStyle = '#0f172a';
    ctx.lineWidth = 1.2;
    ctx.strokeRect(MARGIN.left, MARGIN.top, plotW, plotH);

    ctx.fillStyle = '#0f172a';
    ctx.font = '13px "Times New Roman", Georgia, serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';

    for (const xt of xTicks) {
      const sx = dataToScreenX(xt, plotW);
      if (sx < MARGIN.left - 1 || sx > MARGIN.left + plotW + 1) continue;
      // Bottom & top inward ticks
      ctx.beginPath();
      ctx.moveTo(sx, MARGIN.top + plotH);
      ctx.lineTo(sx, MARGIN.top + plotH - 6);
      ctx.moveTo(sx, MARGIN.top);
      ctx.lineTo(sx, MARGIN.top + 6);
      ctx.stroke();
      ctx.fillText(xt.toLocaleString(), sx, MARGIN.top + plotH + 8);
    }

    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const yt of yTicks) {
      const sy = dataToScreenY(yt, plotH);
      if (sy < MARGIN.top - 1 || sy > MARGIN.top + plotH + 1) continue;
      // Left & right inward ticks
      ctx.beginPath();
      ctx.moveTo(MARGIN.left, sy);
      ctx.lineTo(MARGIN.left + 6, sy);
      ctx.moveTo(MARGIN.left + plotW, sy);
      ctx.lineTo(MARGIN.left + plotW - 6, sy);
      ctx.stroke();
      ctx.fillText(yt.toLocaleString(), MARGIN.left - 8, sy);
    }

    // Axis titles (N and iterN)
    ctx.font = 'bold 16px "Times New Roman", Georgia, serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText('N', MARGIN.left + plotW / 2, height - 6);

    ctx.save();
    ctx.translate(18, MARGIN.top + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('iterN', 0, 0);
    ctx.restore();

    ctx.restore();
  }

  function findNearestPoint(mouseX, mouseY) {
    const plotW = Math.max(50, containerWidth - MARGIN.left - MARGIN.right);
    const plotH = Math.max(50, containerHeight - MARGIN.top - MARGIN.bottom);
    if (
      mouseX < MARGIN.left ||
      mouseX > MARGIN.left + plotW ||
      mouseY < MARGIN.top ||
      mouseY > MARGIN.top + plotH
    ) {
      return null;
    }

    let bestDistSq = 14 * 14; // 14px pick radius
    let best = null;

    for (let dIdx = datasets.length - 1; dIdx >= 0; dIdx--) {
      const ds = datasets[dIdx];
      if (!ds.data || !ds.data.points) continue;
      const ptsN = ds.data.points.n;
      const ptsSteps = ds.data.points.steps;
      const ptsLoop = ds.data.points.loop_id;

      for (let i = 0; i < ptsN.length; i++) {
        const nVal = ptsN[i];
        if (nVal < viewport.xMin || nVal > viewport.xMax) continue;
        const stVal = ptsSteps[i];
        if (stVal < 0 || stVal < viewport.yMin || stVal > viewport.yMax) continue;
        const lid = ptsLoop[i];
        if (ds.visibleLoops && ds.visibleLoops[lid] === false) continue;

        const sx = dataToScreenX(nVal, plotW);
        const sy = dataToScreenY(stVal, plotH);
        const dx = sx - mouseX;
        const dy = sy - mouseY;
        const d2 = dx * dx + dy * dy;
        if (d2 <= bestDistSq) {
          bestDistSq = d2;
          const lpObj = (ds.data.loops || []).find((l) => l.loop_id === lid);
          best = {
            n: nVal,
            steps: stVal,
            loop_id: lid,
            loopLabel: lpObj ? lpObj.label : `Loop ${lid}`,
            color: ds.loopColors?.[lid] || '#0072B2',
            datasetIndex: dIdx,
            datasetId: ds.id,
            datasetTitle: ds.title,
            p: ds.p,
            q: ds.q,
            screenX: sx,
            screenY: sy,
          };
        }
      }
    }
    return best;
  }

  function handleWheel(e) {
    e.preventDefault();
    contextMenu = null;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const plotW = Math.max(50, containerWidth - MARGIN.left - MARGIN.right);
    const plotH = Math.max(50, containerHeight - MARGIN.top - MARGIN.bottom);

    const xRatio = Math.min(1, Math.max(0, (mx - MARGIN.left) / plotW));
    const yRatio = Math.min(1, Math.max(0, (MARGIN.top + plotH - my) / plotH));

    const factor = e.deltaY < 0 ? 0.8 : 1.25;
    let axisMode = 'both';
    if (e.shiftKey) axisMode = 'x';
    else if (e.altKey) axisMode = 'y';

    zoomByFactor(factor, xRatio, yRatio, axisMode);
  }

  function handleMouseDown(e) {
    if (e.button !== 0) return; // left button only for pan
    contextMenu = null;
    isDragging = true;
    const rect = canvas.getBoundingClientRect();
    dragStart = {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      xMin: viewport.xMin,
      xMax: viewport.xMax,
      yMin: viewport.yMin,
      yMax: viewport.yMax,
    };
  }

  function handleMouseMove(e) {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const plotW = Math.max(50, containerWidth - MARGIN.left - MARGIN.right);
    const plotH = Math.max(50, containerHeight - MARGIN.top - MARGIN.bottom);

    if (isDragging) {
      const dxPx = mx - dragStart.x;
      const dyPx = my - dragStart.y;
      const ySpan = dragStart.yMax - dragStart.yMin;
      const dyData = (dyPx / plotH) * ySpan;

      let nextXMin = dragStart.xMin;
      let nextXMax = dragStart.xMax;
      if (logScaleX) {
        const lMin = Math.log10(Math.max(1, dragStart.xMin));
        const lMax = Math.log10(Math.max(10, dragStart.xMax));
        const lSpan = lMax - lMin;
        const dL = -(dxPx / plotW) * lSpan;
        const shiftedMin = Math.max(0, lMin + dL);
        nextXMin = Math.pow(10, shiftedMin);
        nextXMax = Math.pow(10, shiftedMin + lSpan);
      } else {
        const xSpan = dragStart.xMax - dragStart.xMin;
        const dxData = -(dxPx / plotW) * xSpan;
        nextXMin = dragStart.xMin + dxData;
        nextXMax = dragStart.xMax + dxData;
      }

      setViewport(
        {
          xMin: nextXMin,
          xMax: nextXMax,
          yMin: Math.max(0, dragStart.yMin + dyData),
          yMax: Math.max(0, dragStart.yMin + dyData) + ySpan,
        },
        true
      );
      return;
    }

    const found = findNearestPoint(mx, my);
    if (
      (found?.n !== hoveredPoint?.n) ||
      (found?.datasetId !== hoveredPoint?.datasetId)
    ) {
      hoveredPoint = found;
      drawPlot();
    }
  }

  function handleMouseUp() {
    isDragging = false;
  }

  function handleContextMenu(e) {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const pt = findNearestPoint(mx, my) || hoveredPoint;
    if (pt) {
      hoveredPoint = pt;
      contextMenu = {
        x: Math.min(mx, containerWidth - 260),
        y: Math.min(my, containerHeight - 160),
        point: pt,
      };
      drawPlot();
    } else {
      contextMenu = null;
    }
  }

  function triggerInspectFromMenu(pt) {
    contextMenu = null;
    dispatch('nodeContextInspect', pt);
  }

  function toggleSameHeightLine(steps) {
    if (highlightedHeight === steps) {
      highlightedHeight = null;
    } else {
      highlightedHeight = steps;
    }
    contextMenu = null;
    drawPlot();
  }

  /**
   * Export current view (including overlays, custom colors, node sizes, and zoom)
   * as an exact 1800x1000 PNG image.
   */
  export function exportCurrentPng1800x1000(filename = 'iter_interactive_1800x1000.png') {
    const outW = 1800;
    const outH = 1000;
    const offCanvas = document.createElement('canvas');
    offCanvas.width = outW;
    offCanvas.height = outH;
    const ctx = offCanvas.getContext('2d');

    const m = { top: 55, right: 50, bottom: 95, left: 120 };
    const plotW = outW - m.left - m.right;
    const plotH = outH - m.top - m.bottom;

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, outW, outH);

    const xTicks = computeNiceTicks(viewport.xMin, viewport.xMax, 10, logScaleX);
    const yTicks = computeNiceTicks(viewport.yMin, viewport.yMax, 7, false);

    const toX = (x) => dataToScreenX(x, plotW, viewport, logScaleX, m.left);
    const toY = (y) => dataToScreenY(y, plotH, viewport, m.top);

    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1.2;
    ctx.setLineDash([4, 5]);
    for (const xt of xTicks) {
      const sx = toX(xt);
      ctx.beginPath();
      ctx.moveTo(sx, m.top);
      ctx.lineTo(sx, m.top + plotH);
      ctx.stroke();
    }
    for (const yt of yTicks) {
      const sy = toY(yt);
      ctx.beginPath();
      ctx.moveTo(m.left, sy);
      ctx.lineTo(m.left + plotW, sy);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    ctx.save();
    ctx.beginPath();
    ctx.rect(m.left, m.top, plotW, plotH);
    ctx.clip();

    for (const ds of datasets) {
      if (!ds.data || !ds.data.points) continue;
      const ptsN = ds.data.points.n;
      const ptsSteps = ds.data.points.steps;
      const ptsLoop = ds.data.points.loop_id;
      const radius = Math.max(1.2, Number(ds.nodeSize || 2.5) * 1.6);
      ctx.globalAlpha = Number(ds.opacity ?? 0.85);

      for (let i = 0; i < ptsN.length; i++) {
        const nVal = ptsN[i];
        if (nVal < viewport.xMin || nVal > viewport.xMax) continue;
        const stVal = ptsSteps[i];
        if (stVal < 0 || stVal < viewport.yMin || stVal > viewport.yMax) continue;
        const lid = ptsLoop[i];
        if (ds.visibleLoops && ds.visibleLoops[lid] === false) continue;

        ctx.fillStyle = ds.loopColors?.[lid] || '#0072B2';
        ctx.beginPath();
        ctx.arc(toX(nVal), toY(stVal), radius, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.restore();

    ctx.strokeStyle = '#0f172a';
    ctx.lineWidth = 2;
    ctx.strokeRect(m.left, m.top, plotW, plotH);

    ctx.fillStyle = '#0f172a';
    ctx.font = '24px "Times New Roman", serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const xt of xTicks) {
      const sx = toX(xt);
      ctx.fillText(xt.toLocaleString(), sx, m.top + plotH + 14);
    }

    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const yt of yTicks) {
      const sy = toY(yt);
      ctx.fillText(yt.toLocaleString(), m.left - 14, sy);
    }

    ctx.font = 'bold 30px "Times New Roman", serif';
    ctx.textAlign = 'center';
    ctx.fillText('N', m.left + plotW / 2, outH - 25);

    ctx.save();
    ctx.translate(36, m.top + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('iterN', 0, 0);
    ctx.restore();

    const url = offCanvas.toDataURL('image/png');
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
  }

  /**
   * Export current view as a zoomable vector SVG file.
   */
  export function exportCurrentSvg(filename = 'iter_interactive.svg') {
    const outW = 1800;
    const outH = 1000;
    const m = { top: 55, right: 50, bottom: 95, left: 120 };
    const plotW = outW - m.left - m.right;
    const plotH = outH - m.top - m.bottom;

    const toX = (x) => dataToScreenX(x, plotW, viewport, logScaleX, m.left).toFixed(2);
    const toY = (y) => dataToScreenY(y, plotH, viewport, m.top).toFixed(2);

    const xTicks = computeNiceTicks(viewport.xMin, viewport.xMax, 10, logScaleX);
    const yTicks = computeNiceTicks(viewport.yMin, viewport.yMax, 7, false);

    const parts = [];
    parts.push(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${outW} ${outH}" width="${outW}" height="${outH}">`
    );
    parts.push(`<rect width="100%" height="100%" fill="#ffffff"/>`);

    // Grid
    parts.push(`<g stroke="#cbd5e1" stroke-width="1" stroke-dasharray="4,4">`);
    for (const xt of xTicks) {
      const sx = toX(xt);
      parts.push(`<line x1="${sx}" y1="${m.top}" x2="${sx}" y2="${m.top + plotH}"/>`);
    }
    for (const yt of yTicks) {
      const sy = toY(yt);
      parts.push(`<line x1="${m.left}" y1="${sy}" x2="${m.left + plotW}" y2="${sy}"/>`);
    }
    parts.push(`</g>`);

    // Points
    for (const ds of datasets) {
      if (!ds.data || !ds.data.points) continue;
      const ptsN = ds.data.points.n;
      const ptsSteps = ds.data.points.steps;
      const ptsLoop = ds.data.points.loop_id;
      const radius = Math.max(1.2, Number(ds.nodeSize || 2.5) * 1.5).toFixed(2);
      const alpha = Number(ds.opacity ?? 0.85).toFixed(2);

      parts.push(`<g fill-opacity="${alpha}">`);
      for (let i = 0; i < ptsN.length; i++) {
        const nVal = ptsN[i];
        if (nVal < viewport.xMin || nVal > viewport.xMax) continue;
        const stVal = ptsSteps[i];
        if (stVal < 0 || stVal < viewport.yMin || stVal > viewport.yMax) continue;
        const lid = ptsLoop[i];
        if (ds.visibleLoops && ds.visibleLoops[lid] === false) continue;
        const color = ds.loopColors?.[lid] || '#0072B2';
        parts.push(`<circle cx="${toX(nVal)}" cy="${toY(stVal)}" r="${radius}" fill="${color}"/>`);
      }
      parts.push(`</g>`);
    }

    // Axes Box & Labels
    parts.push(
      `<rect x="${m.left}" y="${m.top}" width="${plotW}" height="${plotH}" fill="none" stroke="#0f172a" stroke-width="2"/>`
    );
    parts.push(`<g font-family="Times New Roman, serif" font-size="22" fill="#0f172a">`);
    for (const xt of xTicks) {
      parts.push(
        `<text x="${toX(xt)}" y="${m.top + plotH + 32}" text-anchor="middle">${xt.toLocaleString()}</text>`
      );
    }
    for (const yt of yTicks) {
      parts.push(
        `<text x="${m.left - 14}" y="${Number(toY(yt)) + 7}" text-anchor="end">${yt.toLocaleString()}</text>`
      );
    }
    parts.push(
      `<text x="${m.left + plotW / 2}" y="${outH - 22}" text-anchor="middle" font-size="28" font-weight="bold">N</text>`
    );
    parts.push(
      `<text x="36" y="${m.top + plotH / 2}" text-anchor="middle" font-size="28" font-weight="bold" transform="rotate(-90, 36, ${m.top + plotH / 2})">iterN</text>`
    );
    parts.push(`</g></svg>`);

    const blob = new Blob([parts.join('\n')], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  onMount(() => {
    recomputeDefaultBounds(true);
    drawPlot();
  });

  afterUpdate(() => {
    drawPlot();
  });
</script>

<svelte:window bind:innerHeight={windowHeight} />

<div class="plot-wrapper" bind:clientWidth={containerWidth}>
  <div class="plot-toolbar-compact">
    <div class="viewport-info" title="ホイール: ズーム / ドラッグ: 移動 / 点の上で右クリック: 周辺数値表">
      N ∈ [{Math.round(viewport.xMin).toLocaleString()}, {Math.round(viewport.xMax).toLocaleString()}],
      iterN ∈ [{Math.round(viewport.yMin)}, {Math.round(viewport.yMax)}]
      <span class="hint-text">（右クリック: 数値表）</span>
    </div>

    <div class="compact-actions">
      <button class="btn-tool" on:click={resetZoom} title="初期表示範囲に戻す">↺ リセット</button>
      <button
        class="btn-tool {logScaleX ? 'btn-active-log' : ''}"
        on:click={toggleLogScaleX}
        title="横軸を対数目盛り（Log N）にすると対数曲線 h(n)=log_d(n)+C_a が平行な直線になります"
      >
        📐 {logScaleX ? 'Log N' : 'Linear'}
      </button>
      {#if highlightedHeight !== null}
        <button class="btn-tool btn-highlight-clear" on:click={() => { highlightedHeight = null; drawPlot(); }}>
          水平線消去
        </button>
      {/if}
      {#if highlightedSpine !== null}
        <button class="btn-tool btn-highlight-clear" on:click={() => { highlightedSpine = null; drawPlot(); }}>
          直線消去
        </button>
      {/if}
      <button
        class="btn-tool {showExtraTools ? 'btn-active-log' : ''}"
        on:click={() => (showExtraTools = !showExtraTools)}
        title="ズーム・海面ライン・原始木・PNG/SVG保存を開く"
      >
        🛠 ツール {showExtraTools ? '▴' : '▾'}
      </button>
    </div>
  </div>

  {#if showExtraTools}
    <div class="plot-toolbar-drawer">
      <div class="zoom-controls">
        <button class="btn-tool" on:click={() => zoomByFactor(0.75)} title="ズームイン">＋ 拡大</button>
        <button class="btn-tool" on:click={() => zoomByFactor(1.33)} title="ズームアウト">－ 縮小</button>
        <button class="btn-tool" on:click={() => zoomByFactor(0.75, 0.5, 0.5, 'x')} title="横軸のみ拡大">横軸＋</button>
        <button class="btn-tool" on:click={() => zoomByFactor(1.33, 0.5, 0.5, 'x')} title="横軸のみ縮小">横軸－</button>
        {#if logScaleX}
          <button
            class="btn-tool {showGuideLines ? 'btn-active-log' : ''}"
            on:click={() => { showGuideLines = !showGuideLines; drawPlot(); }}
            title="傾き 1/ln(d) の平行直線ガイドを表示/非表示"
          >
            平行直線: {showGuideLines ? 'ON' : 'OFF'}
          </button>
        {/if}
        <button
          class="btn-tool {showSeaLevel ? 'btn-active-log' : ''}"
          on:click={() => { showSeaLevel = !showSeaLevel; drawPlot(); }}
          title="海面境界ライン N = max(Q) を表示/非表示"
        >
          🌊 海面(N=q): {showSeaLevel ? 'ON' : 'OFF'}
        </button>
        <button
          class="btn-tool {primitiveOnly ? 'btn-active-log' : ''}"
          on:click={() => { primitiveOnly = !primitiveOnly; drawPlot(); }}
          title="原始層 (gcd(n,q)=1) のみを表示"
        >
          🌱 原始木のみ: {primitiveOnly ? 'ON' : 'OFF'}
        </button>
      </div>
      <div class="export-controls">
        <button class="btn-export" on:click={() => exportCurrentPng1800x1000()}>
          ⬇ PNG (1800×1000)
        </button>
        <button class="btn-export" on:click={() => exportCurrentSvg()}>
          ⬇ SVG
        </button>
      </div>
    </div>
  {/if}

  <!-- Interactive Canvas Container -->
  <div class="canvas-stage" style="height: {containerHeight}px;">
    <canvas
      bind:this={canvas}
      on:wheel={handleWheel}
      on:mousedown={handleMouseDown}
      on:mousemove={handleMouseMove}
      on:mouseup={handleMouseUp}
      on:mouseleave={handleMouseUp}
      on:contextmenu={handleContextMenu}
      style="width: 100%; height: {containerHeight}px;"
    ></canvas>

    <!-- Hover Tooltip -->
    {#if hoveredPoint && !contextMenu}
      <div
        class="hover-tooltip"
        style="left: {Math.min(hoveredPoint.screenX + 14, containerWidth - 250)}px; top: {Math.max(10, hoveredPoint.screenY - 58)}px;"
      >
        <div class="tt-header">
          <span class="tt-dot" style="background: {hoveredPoint.color}"></span>
          <strong>n = {hoveredPoint.n.toLocaleString()}</strong>
          <span>(iterN = {hoveredPoint.steps})</span>
        </div>
        <div class="tt-sub">{hoveredPoint.loopLabel}</div>
        <div class="tt-hint">右クリックで前後の数値・同じ高さの表を表示</div>
      </div>
    {/if}

    <!-- Right-Click Context Menu -->
    {#if contextMenu}
      <div
        class="context-menu"
        style="left: {contextMenu.x}px; top: {contextMenu.y}px;"
      >
        <div class="cm-title">
          ノード <strong>n = {contextMenu.point.n.toLocaleString()}</strong> (高さ {contextMenu.point.steps})
        </div>
        <div class="cm-loop">{contextMenu.point.loopLabel}</div>
        <button class="cm-item primary" on:click={() => triggerInspectFromMenu(contextMenu.point)}>
          📋 この数値の前後（逆像・軌道）と同じ高さの表を表示
        </button>
        <button class="cm-item" on:click={() => toggleSameHeightLine(contextMenu.point.steps)}>
          📏 高さ iterN = {contextMenu.point.steps} に水平ガイド線を表示/切替
        </button>
        <button class="cm-item" on:click={() => toggleSpineFromPoint(contextMenu.point)}>
          📈 この点を通る対数曲線/直線系列 (n = a·d^k) を強調表示
        </button>
        <button
          class="cm-item"
          on:click={() => {
            const pt = contextMenu.point;
            contextMenu = null;
            centerOnNode(pt.n, pt.steps);
          }}
        >
          🔍 このノードを中心に拡大フォーカス
        </button>
        <button class="cm-item cancel" on:click={() => (contextMenu = null)}>
          閉じる
        </button>
      </div>
    {/if}
  </div>
</div>

<style>
  .plot-wrapper {
    width: 100%;
    background: #ffffff;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    overflow: hidden;
  }

  .plot-toolbar-compact {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 10px;
    background: #f8fafc;
    border-bottom: 1px solid var(--border-color);
    flex-wrap: wrap;
    gap: 6px;
  }

  .compact-actions {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-wrap: wrap;
  }

  .plot-toolbar-drawer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 10px;
    background: #f1f5f9;
    border-bottom: 1px solid var(--border-color);
    flex-wrap: wrap;
    gap: 6px;
  }

  .zoom-controls,
  .export-controls {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .btn-tool {
    padding: 4px 10px;
    font-size: 0.8rem;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    color: #1e293b;
    font-weight: 600;
  }
  .btn-tool:hover {
    background: #f1f5f9;
    border-color: #94a3b8;
  }

  .btn-highlight-clear {
    background: #fef3c7;
    border-color: #f59e0b;
    color: #92400e;
  }

  .btn-active-log {
    background: #e0f2fe;
    border-color: #0284c7;
    color: #0369a1;
  }

  .btn-export {
    padding: 4px 10px;
    font-size: 0.8rem;
    background: #0f172a;
    color: #ffffff;
    border: 1px solid #0f172a;
    border-radius: 5px;
    font-weight: 600;
  }
  .btn-export:hover {
    background: #334155;
  }

  .viewport-info {
    font-size: 0.78rem;
    color: #475569;
  }

  .hint-text {
    color: #64748b;
    margin-left: 4px;
  }

  .canvas-stage {
    position: relative;
    width: 100%;
    user-select: none;
    cursor: grab;
  }
  .canvas-stage:active {
    cursor: grabbing;
  }

  .hover-tooltip {
    position: absolute;
    pointer-events: none;
    background: rgba(15, 23, 42, 0.92);
    color: #ffffff;
    padding: 7px 11px;
    border-radius: 6px;
    font-size: 0.8rem;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    z-index: 10;
    white-space: nowrap;
  }

  .tt-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 2px;
  }

  .tt-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    display: inline-block;
  }

  .tt-sub {
    font-size: 0.75rem;
    color: #cbd5e1;
  }

  .tt-hint {
    font-size: 0.7rem;
    color: #38bdf8;
    margin-top: 2px;
  }

  .context-menu {
    position: absolute;
    width: 265px;
    background: #ffffff;
    border: 1px solid #94a3b8;
    border-radius: 8px;
    box-shadow: 0 10px 25px rgba(15, 23, 42, 0.22);
    padding: 6px;
    z-index: 25;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .cm-title {
    padding: 6px 8px 2px 8px;
    font-size: 0.86rem;
    color: #0f172a;
  }

  .cm-loop {
    padding: 0 8px 6px 8px;
    font-size: 0.75rem;
    color: #64748b;
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 2px;
  }

  .cm-item {
    text-align: left;
    padding: 7px 10px;
    border: none;
    background: transparent;
    border-radius: 5px;
    font-size: 0.8rem;
    color: #1e293b;
  }
  .cm-item:hover {
    background: #f1f5f9;
  }
  .cm-item.primary {
    background: #f0f9ff;
    color: #0369a1;
    font-weight: 600;
  }
  .cm-item.primary:hover {
    background: #e0f2fe;
  }
  .cm-item.cancel {
    color: #64748b;
    border-top: 1px solid #e2e8f0;
    margin-top: 2px;
  }
</style>

