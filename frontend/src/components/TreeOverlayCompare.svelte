<script>
  import { onMount } from "svelte";

  export let panels = [];

  function makeSide(label, p, q, color, offsetX, offsetY) {
    return {
      label,
      p,
      q: [...q],
      rootMode: "loop",
      loopId: 1,
      rootN: 1,
      maxHeight: 6,
      color,
      opacity: 0.85,
      offsetX,
      offsetY,
      loading: false,
      error: null,
      treeData: null,
      nodes: [],
      links: [],
      spineLinks: [],
    };
  }

  let sideA = makeSide("ツリー A", 3, [null, 1], "#0284c7", -140, 0);
  let sideB = makeSide("ツリー B", 3, [null, 3], "#ea580c", 140, 0);

  let orientation = "radial"; // 'radial' | 'BT'
  let showLabels = true;
  let dragTarget = "B"; // 'A' | 'B' | 'pan'
  let showSettings = false;

  // Stage pan/zoom
  let stageScale = 1.0;
  let stagePanX = 480;
  let stagePanY = 290;
  let isDragging = false;
  let dragStart = { x: 0, y: 0, ox: 0, oy: 0 };

  function getSide(key) {
    return key === "A" ? sideA : sideB;
  }

  function setSide(key, patch) {
    if (key === "A") sideA = { ...sideA, ...patch };
    else sideB = { ...sideB, ...patch };
  }

  function handlePChange(key, newP) {
    const side = getSide(key);
    const pVal = Math.max(2, Math.min(30, parseInt(newP, 10) || 3));
    const d = pVal - 1;
    const nextQ = [null];
    for (let r = 1; r < d; r++) {
      nextQ.push(side.q[r] ?? ((d - (pVal * r) % d) % d || d));
    }
    setSide(key, { p: pVal, q: nextQ });
  }

  function autoFillQ(key) {
    const side = getSide(key);
    const d = side.p - 1;
    const nextQ = [null];
    for (let r = 1; r < d; r++) {
      let val = (d - ((side.p * r) % d)) % d;
      if (val === 0) val = d;
      nextQ.push(val);
    }
    setSide(key, { q: nextQ });
  }

  function importFromPanel(key, panelIdStr) {
    const pid = Number(panelIdStr);
    const src = panels.find((p) => p.id === pid);
    if (!src) return;
    setSide(key, { p: src.p, q: [...src.q] });
    fetchSideTree(key);
  }

  function layoutTree(treeRoot, maxH, mode) {
    if (!treeRoot) return { nodes: [], links: [], spineLinks: [] };

    function countLeaves(nd) {
      const ch = nd.children || [];
      nd._leaves = ch.length === 0 ? 1 : ch.reduce((acc, c) => acc + countLeaves(c), 0);
      return nd._leaves;
    }

    const topNodes = treeRoot.children || [];
    const totalLeaves = topNodes.reduce((acc, c) => acc + countLeaves(c), 0) || 1;
    const nodes = [];
    const links = [];
    const spineLinks = [];

    if (mode === "radial") {
      const assignRadial = (nd, aStart, aEnd) => {
        const h = Number(nd.height || 0);
        const theta = 0.5 * (aStart + aEnd);
        const r = h === 0 ? 28 : 28 + h * 36;
        const x = r * Math.cos(theta);
        const y = r * Math.sin(theta);
        nodes.push({ n: nd.n, h, x, y, isLoop: !!nd.is_loop });
        const ch = nd.children || [];
        if (ch.length > 0) {
          let cur = aStart;
          const span = aEnd - aStart;
          const tot = ch.reduce((acc, c) => acc + c._leaves, 0) || 1;
          for (const c of ch) {
            const cSpan = span * (c._leaves / tot);
            const childPt = assignRadial(c, cur, cur + cSpan);
            links.push({ x1: x, y1: y, x2: childPt.x, y2: childPt.y });
            cur += cSpan;
          }
        }
        return { x, y };
      };

      let curA = 0;
      const topCoords = [];
      for (const top of topNodes) {
        const span = 2 * Math.PI * (top._leaves / totalLeaves);
        topCoords.push(assignRadial(top, curA, curA + span));
        curA += span;
      }
      if (topCoords.length > 1) {
        for (let i = 0; i < topCoords.length; i++) {
          const a = topCoords[i];
          const b = topCoords[(i + 1) % topCoords.length];
          spineLinks.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y });
        }
      }
    } else {
      // BT bottom-to-top layout
      const totalWidth = Math.max(260, totalLeaves * 26);
      const assignBT = (nd, xStart, xEnd) => {
        const h = Number(nd.height || 0);
        const x = 0.5 * (xStart + xEnd);
        const y = 120 - h * 46;
        nodes.push({ n: nd.n, h, x, y, isLoop: !!nd.is_loop });
        const ch = nd.children || [];
        if (ch.length > 0) {
          let cur = xStart;
          const span = xEnd - xStart;
          const tot = ch.reduce((acc, c) => acc + c._leaves, 0) || 1;
          for (const c of ch) {
            const cSpan = span * (c._leaves / tot);
            const childPt = assignBT(c, cur, cur + cSpan);
            links.push({ x1: x, y1: y, x2: childPt.x, y2: childPt.y });
            cur += cSpan;
          }
        }
        return { x, y };
      };

      let curX = -totalWidth / 2;
      const topCoords = [];
      for (const top of topNodes) {
        const span = totalWidth * (top._leaves / totalLeaves);
        topCoords.push(assignBT(top, curX, curX + span));
        curX += span;
      }
      if (topCoords.length > 1) {
        for (let i = 0; i < topCoords.length; i++) {
          const a = topCoords[i];
          const b = topCoords[(i + 1) % topCoords.length];
          spineLinks.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y });
        }
      }
    }

    return { nodes, links, spineLinks };
  }

  function relayoutAll() {
    if (sideA.treeData?.tree) {
      const laid = layoutTree(sideA.treeData.tree, sideA.maxHeight, orientation);
      sideA = { ...sideA, ...laid };
    }
    if (sideB.treeData?.tree) {
      const laid = layoutTree(sideB.treeData.tree, sideB.maxHeight, orientation);
      sideB = { ...sideB, ...laid };
    }
  }

  async function fetchSideTree(key) {
    const side = getSide(key);
    setSide(key, { loading: true, error: null });

    try {
      const res = await fetch("/api/loop-tree", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          p: Number(side.p),
          q: side.q.map((x, idx) => (idx === 0 ? null : Number(x))),
          loop_id: side.rootMode === "loop" ? Number(side.loopId) : null,
          root_n: side.rootMode === "single" ? Number(side.rootN) : null,
          root_mode: side.rootMode,
          max_height: Number(side.maxHeight),
          max_nodes: 3500,
        }),
      });
      const json = await res.json();
      if (!res.ok) {
        throw new Error(json.detail || `HTTP ${res.status}`);
      }
      const laid = layoutTree(json.tree, side.maxHeight, orientation);
      setSide(key, {
        treeData: json,
        nodes: laid.nodes,
        links: laid.links,
        spineLinks: laid.spineLinks,
      });
    } catch (err) {
      setSide(key, { error: err.message });
    } finally {
      setSide(key, { loading: false });
    }
  }

  function alignCenters() {
    sideA = { ...sideA, offsetX: 0, offsetY: 0 };
    sideB = { ...sideB, offsetX: 0, offsetY: 0 };
    stagePanX = 480;
    stagePanY = 290;
    stageScale = 1.0;
  }

  function placeSideBySide() {
    sideA = { ...sideA, offsetX: -190, offsetY: 0 };
    sideB = { ...sideB, offsetX: 190, offsetY: 0 };
    stagePanX = 480;
    stagePanY = 290;
    stageScale = 0.95;
  }

  function handleStagePointerDown(e, forcedTarget = null) {
    if (e.button !== 0) return;
    e.stopPropagation();
    const tgt = forcedTarget || dragTarget;
    dragTarget = tgt;
    isDragging = true;
    if (tgt === "A") {
      dragStart = { x: e.clientX, y: e.clientY, ox: sideA.offsetX, oy: sideA.offsetY };
    } else if (tgt === "B") {
      dragStart = { x: e.clientX, y: e.clientY, ox: sideB.offsetX, oy: sideB.offsetY };
    } else {
      dragStart = { x: e.clientX, y: e.clientY, ox: stagePanX, oy: stagePanY };
    }
  }

  function handleStagePointerMove(e) {
    if (!isDragging) return;
    const dx = e.clientX - dragStart.x;
    const dy = e.clientY - dragStart.y;
    if (dragTarget === "A") {
      sideA = { ...sideA, offsetX: dragStart.ox + dx / stageScale, offsetY: dragStart.oy + dy / stageScale };
    } else if (dragTarget === "B") {
      sideB = { ...sideB, offsetX: dragStart.ox + dx / stageScale, offsetY: dragStart.oy + dy / stageScale };
    } else {
      stagePanX = dragStart.ox + dx;
      stagePanY = dragStart.oy + dy;
    }
  }

  function handleStagePointerUp() {
    isDragging = false;
  }

  function handleStageWheel(e) {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 0.89;
    stageScale = Math.max(0.25, Math.min(4.0, stageScale * factor));
  }

  onMount(() => {
    if (panels.length >= 1) {
      sideA.p = panels[0].p;
      sideA.q = [...panels[0].q];
    }
    if (panels.length >= 2) {
      sideB.p = panels[1].p;
      sideB.q = [...panels[1].q];
    }
    fetchSideTree("A");
    fetchSideTree("B");
  });
</script>

<section class="overlay-compare-shell">
  <div class="compare-toolbar">
    <div class="compare-title-row">
      <h3>🔀 2ツリー重ね合わせ比較（マウスドラッグで位置合わせ・透過比較）</h3>
      <div class="compare-quick-btns">
        <label>
          向き:
          <select bind:value={orientation} on:change={relayoutAll}>
            <option value="radial">❄️ 放射状</option>
            <option value="BT">下→上</option>
          </select>
        </label>
        <label class="chk-label">
          <input type="checkbox" bind:checked={showLabels} />
          数値ラベル
        </label>
        <button type="button" class="btn-sm" on:click={alignCenters}>🎯 中心を重ねる (0,0)</button>
        <button type="button" class="btn-sm" on:click={placeSideBySide}>↔ 左右に並べる</button>
        <button
          type="button"
          class="btn-sm"
          on:click={() => (showSettings = !showSettings)}
        >
          ⚙ ツリー設定 {showSettings ? "▴" : "▾"}
        </button>
      </div>
    </div>

    <div class="drag-mode-bar">
      <span>ドラッグ対象:</span>
      <button
        type="button"
        class="btn-xs"
        class:active-a={dragTarget === "A"}
        on:click={() => (dragTarget = "A")}
      >
        🔵 ツリーAを移動 ({Math.round(sideA.offsetX)}, {Math.round(sideA.offsetY)})
      </button>
      <button
        type="button"
        class="btn-xs"
        class:active-b={dragTarget === "B"}
        on:click={() => (dragTarget = "B")}
      >
        🟠 ツリーBを移動 ({Math.round(sideB.offsetX)}, {Math.round(sideB.offsetY)})
      </button>
      <button
        type="button"
        class="btn-xs"
        class:active-pan={dragTarget === "pan"}
        on:click={() => (dragTarget = "pan")}
      >
        ✋ キャンバス全体をパン (拡大率: {Math.round(stageScale * 100)}%)
      </button>
      <span class="hint">※ 各ツリーを直接ドラッグしても移動できます</span>
    </div>

    {#if showSettings}
      <div class="sides-grid">
        {#each [
          { key: "A", side: sideA, badge: "🔵 ツリー A" },
          { key: "B", side: sideB, badge: "🟠 ツリー B" }
        ] as item (item.key)}
          <div class="side-card">
            <div class="side-card-head">
              <strong>{item.badge}</strong>
              {#if panels.length > 0}
                <select
                  class="preset-select"
                  on:change={(e) => {
                    if (e.target.value !== "") {
                      importFromPanel(item.key, e.target.value);
                      e.target.value = "";
                    }
                  }}
                >
                  <option value="">既存パネルからコピー...</option>
                  {#each panels as pn}
                    <option value={pn.id}>{pn.title} (p={pn.p})</option>
                  {/each}
                </select>
              {/if}
              <label class="opacity-inline">
                不透明度 {Math.round(item.side.opacity * 100)}%
                <input
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  bind:value={item.side.opacity}
                  on:input={() => {
                    if (item.key === "A") sideA = { ...sideA };
                    else sideB = { ...sideB };
                  }}
                />
              </label>
            </div>

            <div class="side-params">
              <label>
                p:
                <input
                  type="number"
                  min="2"
                  max="30"
                  value={item.side.p}
                  on:change={(e) => handlePChange(item.key, e.target.value)}
                  class="input-num short"
                />
              </label>
              <div class="q-inline">
                <span>Q=[_,</span>
                {#each item.side.q.slice(1) as _, idx}
                  {@const r = idx + 1}
                  {@const dStep = Math.max(1, Number(item.side.p) - 1)}
                  {@const curVal = Number(item.side.q[r])}
                  {@const minVal = Number.isFinite(curVal) && curVal >= 1 ? ((curVal - 1) % dStep) + 1 : 1}
                  <input
                    type="number"
                    min={minVal}
                    step={dStep}
                    bind:value={item.side.q[r]}
                    class="input-num q-mini"
                  />
                {/each}
                <span>]</span>
                <button type="button" class="btn-link" on:click={() => autoFillQ(item.key)}>補完</button>
              </div>
              <label>
                H:
                <input type="number" min="1" max="15" bind:value={item.side.maxHeight} class="input-num short" />
              </label>
              <label>
                loop_id:
                <input type="number" min="1" bind:value={item.side.loopId} class="input-num short" />
              </label>
              <button
                type="button"
                class="btn-compute"
                disabled={item.side.loading}
                on:click={() => fetchSideTree(item.key)}
              >
                {item.side.loading ? "読込中..." : "▶ 読込"}
              </button>
            </div>

            {#if item.side.error}
              <div class="error-banner">{item.side.error}</div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <!-- Shared Interactive SVG Canvas -->
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div
    class="compare-stage"
    on:mousedown={(e) => handleStagePointerDown(e, null)}
    on:mousemove={handleStagePointerMove}
    on:mouseup={handleStagePointerUp}
    on:mouseleave={handleStagePointerUp}
    on:wheel={handleStageWheel}
  >
    <svg viewBox="0 0 960 580" class="compare-svg">
      <g transform="translate({stagePanX}, {stagePanY}) scale({stageScale})">
        <!-- Origin Crosshair -->
        <line x1="-24" y1="0" x2="24" y2="0" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="3,3" />
        <line x1="0" y1="-24" x2="0" y2="24" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="3,3" />

        <!-- Tree A -->
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <g
          transform="translate({sideA.offsetX}, {sideA.offsetY})"
          opacity={sideA.opacity}
          style="cursor: move;"
          on:mousedown={(e) => handleStagePointerDown(e, "A")}
        >
          {#each sideA.links as lk}
            <line x1={lk.x1} y1={lk.y1} x2={lk.x2} y2={lk.y2} stroke={sideA.color} stroke-width="1.6" stroke-opacity="0.7" />
          {/each}
          {#each sideA.spineLinks as sp}
            <line x1={sp.x1} y1={sp.y1} x2={sp.x2} y2={sp.y2} stroke={sideA.color} stroke-width="2.4" />
          {/each}
          {#each sideA.nodes as nd}
            <circle
              cx={nd.x}
              cy={nd.y}
              r={nd.isLoop ? 6 : 4.2}
              fill={nd.isLoop ? "#38bdf8" : sideA.color}
              stroke="#0f172a"
              stroke-width="0.8"
            />
            {#if showLabels && nd.h <= 3}
              <text x={nd.x} y={nd.y - 7} text-anchor="middle" font-size="9" fill="#0369a1">{nd.n}</text>
            {/if}
          {/each}
        </g>

        <!-- Tree B -->
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <g
          transform="translate({sideB.offsetX}, {sideB.offsetY})"
          opacity={sideB.opacity}
          style="cursor: move;"
          on:mousedown={(e) => handleStagePointerDown(e, "B")}
        >
          {#each sideB.links as lk}
            <line x1={lk.x1} y1={lk.y1} x2={lk.x2} y2={lk.y2} stroke={sideB.color} stroke-width="1.6" stroke-opacity="0.7" />
          {/each}
          {#each sideB.spineLinks as sp}
            <line x1={sp.x1} y1={sp.y1} x2={sp.x2} y2={sp.y2} stroke={sideB.color} stroke-width="2.4" />
          {/each}
          {#each sideB.nodes as nd}
            <circle
              cx={nd.x}
              cy={nd.y}
              r={nd.isLoop ? 6 : 4.2}
              fill={nd.isLoop ? "#fbbf24" : sideB.color}
              stroke="#0f172a"
              stroke-width="0.8"
            />
            {#if showLabels && nd.h <= 3}
              <text x={nd.x} y={nd.y + 13} text-anchor="middle" font-size="9" fill="#9a3412">{nd.n}</text>
            {/if}
          {/each}
        </g>
      </g>
    </svg>
  </div>
</section>

<style>
  .overlay-compare-shell {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px 10px;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
  }
  .compare-title-row {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }
  .compare-title-row h3 {
    margin: 0;
    font-size: 1rem;
    color: #0f172a;
  }
  .compare-quick-btns {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    font-size: 0.84rem;
  }
  .drag-mode-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    font-size: 0.82rem;
    margin-bottom: 10px;
  }
  .active-a {
    background: #e0f2fe !important;
    border-color: #0284c7 !important;
    color: #0369a1 !important;
  }
  .active-b {
    background: #ffedd5 !important;
    border-color: #ea580c !important;
    color: #9a3412 !important;
  }
  .active-pan {
    background: #e2e8f0 !important;
    border-color: #475569 !important;
    color: #0f172a !important;
  }
  .hint {
    color: #64748b;
    font-size: 0.78rem;
    margin-left: auto;
  }
  .sides-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 10px;
    margin-bottom: 12px;
  }
  .side-card {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 12px;
  }
  .side-card-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    font-size: 0.85rem;
  }
  .opacity-inline {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.8rem;
  }
  .side-params {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    font-size: 0.84rem;
  }
  .q-inline {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .q-mini {
    width: 48px;
    padding: 3px 5px;
  }
  .compare-stage {
    width: 100%;
    height: 580px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #ffffff;
    overflow: hidden;
    user-select: none;
  }
  .compare-svg {
    width: 100%;
    height: 100%;
    display: block;
  }
</style>

