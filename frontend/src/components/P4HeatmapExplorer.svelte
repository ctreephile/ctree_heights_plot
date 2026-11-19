<script>
  import { onMount } from "svelte";

  let maxHeight = 10;
  let gridSize = null;
  let availableGrids = [30];
  let loading = false;
  let addingNext = false;
  let error = null;
  let statusMsg = "";

  let q1Vals = [];
  let q2Vals = [];
  let cells = {}; // key "q1,q2" -> cell object
  let families = {}; // base_str -> family metadata

  // Selection & Modal
  let selectedBase = null;
  let clickedCellKey = null;
  let showModal = false;

  // Hover tooltip
  let hoveredCell = null;
  let tooltipX = 0;
  let tooltipY = 0;

  // Pan & Zoom state
  let svgContainer;
  let svgElement;
  let zoom = 1.0;
  let panX = 0;
  let panY = 0;
  let isPanning = false;
  let panStart = { x: 0, y: 0, panX: 0, panY: 0 };
  let didDrag = false;

  $: CELL_SIZE = q1Vals.length > 50 ? 10 : 22;
  const PAD_LEFT = 56;
  const PAD_RIGHT = 96;
  const PAD_TOP = 42;
  const PAD_BOTTOM = 54;

  // Viridis-inspired 6-stop perceptual colormap
  const VIRIDIS_STOPS = [
    [68, 1, 84],
    [65, 68, 135],
    [42, 120, 142],
    [34, 168, 132],
    [122, 209, 81],
    [253, 231, 37],
  ];

  function interpolateViridis(t) {
    const clamped = Math.max(0, Math.min(1, t));
    const scaled = clamped * (VIRIDIS_STOPS.length - 1);
    const idx = Math.min(VIRIDIS_STOPS.length - 2, Math.floor(scaled));
    const frac = scaled - idx;
    const c0 = VIRIDIS_STOPS[idx];
    const c1 = VIRIDIS_STOPS[idx + 1];
    const r = Math.round(c0[0] + (c1[0] - c0[0]) * frac);
    const g = Math.round(c0[1] + (c1[1] - c0[1]) * frac);
    const b = Math.round(c0[2] + (c1[2] - c0[2]) * frac);
    return `rgb(${r}, ${g}, ${b})`;
  }

  $: allNodeValues = Object.values(cells)
    .map((c) => c.nodes)
    .filter((v) => v > 0);
  $: minNodes = allNodeValues.length ? Math.min(...allNodeValues) : 1;
  $: maxNodes = allNodeValues.length ? Math.max(...allNodeValues) : 100;
  $: logMin = Math.log10(Math.max(1, minNodes));
  $: logMax = Math.log10(Math.max(10, maxNodes));

  function getCellColor(nodes) {
    if (!nodes || nodes <= 0) return "#1e293b";
    const lv = Math.log10(nodes);
    const t = logMax > logMin ? (lv - logMin) / (logMax - logMin) : 0.5;
    return interpolateViridis(t);
  }

  $: svgWidth = PAD_LEFT + Math.max(1, q1Vals.length) * CELL_SIZE + PAD_RIGHT;
  $: svgHeight = PAD_TOP + Math.max(1, q2Vals.length) * CELL_SIZE + PAD_BOTTOM;

  $: selectedFamily = selectedBase ? families[selectedBase] || null : null;
  $: selectedMembers = selectedBase
    ? Object.values(cells)
        .filter((c) => c.base_str === selectedBase)
        .sort((a, b) => a.gcd - b.gcd)
    : [];

  $: nextMemberPreview = (() => {
    if (!selectedFamily) return null;
    const [ba, bb] = selectedFamily.base;
    let g = 1;
    while (g < 500) {
      if (g % 3 !== 0) {
        const q1 = g % 3 === 2 ? g * bb : g * ba;
        const q2 = g % 3 === 2 ? g * ba : g * bb;
        if (!cells[`${q1},${q2}`]) {
          return { g, q1, q2 };
        }
      }
      g += 1;
    }
    return null;
  })();

  async function fetchHeatmap() {
    loading = true;
    error = null;
    statusMsg = "";
    try {
      const qs = gridSize ? `max_height=${maxHeight}&grid_size=${gridSize}` : `max_height=${maxHeight}`;
      const res = await fetch(`/api/p4-heatmap?${qs}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      gridSize = data.grid_size;
      availableGrids = data.available_grids || [data.grid_size];
      q1Vals = data.q1_vals;
      q2Vals = data.q2_vals;
      cells = data.cells;
      families = data.families;
      resetZoom();
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleAddNextMember() {
    if (!selectedFamily || addingNext) return;
    addingNext = true;
    error = null;
    statusMsg = "";
    try {
      const existingQs = Object.values(cells).map((c) => [c.q1, c.q2]);
      const res = await fetch("/api/p4-heatmap/add-next", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_q1: selectedFamily.base[0],
          base_q2: selectedFamily.base[1],
          existing_qs: existingQs,
          max_height: maxHeight,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const newCell = data.cell;

      if (!q1Vals.includes(newCell.q1)) {
        q1Vals = [...q1Vals, newCell.q1].sort((a, b) => a - b);
      }
      if (!q2Vals.includes(newCell.q2)) {
        q2Vals = [...q2Vals, newCell.q2].sort((a, b) => a - b);
      }
      cells = { ...cells, [newCell.key]: newCell };

      // Recompute family summary stats
      const members = Object.values(cells)
        .filter((c) => c.base_str === selectedBase)
        .sort((a, b) => a.gcd - b.gcd);
      const ns = members.map((m) => m.nodes);
      const sts = members.map((m) => m.avg_steps);
      const meanN = Math.round((ns.reduce((a, b) => a + b, 0) / ns.length) * 10) / 10;
      const meanS = Math.round((sts.reduce((a, b) => a + b, 0) / sts.length) * 100) / 100;
      families = {
        ...families,
        [selectedBase]: {
          ...selectedFamily,
          member_keys: members.map((m) => m.key),
          mean_nodes: meanN,
          min_nodes: Math.min(...ns),
          max_nodes: Math.max(...ns),
          mean_avg_steps: meanS,
        },
      };
      statusMsg = `g=${data.g}: Q=(${newCell.q1}, ${newCell.q2}) を計算して追加しました (nodes=${newCell.nodes.toLocaleString()})`;
    } catch (e) {
      error = e.message;
    } finally {
      addingNext = false;
    }
  }

  function handleCellClick(cell) {
    if (didDrag || !cell) return;
    selectedBase = cell.base_str;
    clickedCellKey = cell.key;
    showModal = true;
    statusMsg = "";
  }

  function handleCellMouseMove(e, cell) {
    hoveredCell = cell;
    const rect = svgContainer?.getBoundingClientRect();
    if (rect) {
      tooltipX = e.clientX - rect.left + 14;
      tooltipY = e.clientY - rect.top + 14;
    }
  }

  function handleWheel(e) {
    const factor = e.deltaY < 0 ? 1.15 : 0.87;
    const newZoom = Math.max(0.4, Math.min(8.0, zoom * factor));
    const rect = svgContainer.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    panX = mx - ((mx - panX) * newZoom) / zoom;
    panY = my - ((my - panY) * newZoom) / zoom;
    zoom = newZoom;
  }

  function handleMouseDown(e) {
    if (e.button !== 0) return;
    isPanning = true;
    didDrag = false;
    panStart = { x: e.clientX, y: e.clientY, panX, panY };
  }

  function handleMouseMove(e) {
    if (!isPanning) return;
    const dx = e.clientX - panStart.x;
    const dy = e.clientY - panStart.y;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
      didDrag = true;
    }
    panX = panStart.panX + dx;
    panY = panStart.panY + dy;
  }

  function handleMouseUp() {
    isPanning = false;
  }

  function zoomBy(factor) {
    zoom = Math.max(0.4, Math.min(8.0, zoom * factor));
  }

  function resetZoom() {
    zoom = 1.0;
    panX = 12;
    panY = 8;
  }

  function buildFamilyText() {
    if (!selectedFamily) return "";
    const lines = [
      `=== p=4 Q群レポート: 基底 Q_base = ${selectedFamily.base_str} ===`,
      `性格タイプ: ${selectedFamily.personality}`,
      `表示中メンバー数: ${selectedMembers.length}`,
      `基底ループ長: [${selectedFamily.base_loop_lengths.join(", ")}]`,
      `CTreeノード数 (H=${maxHeight}): 平均=${selectedFamily.mean_nodes}, 最小=${selectedFamily.min_nodes}, 最大=${selectedFamily.max_nodes}`,
      `平均収束ステップ: ${selectedFamily.mean_avg_steps}`,
      "",
      "g\tQ=(q1,q2)\tmod4\tloops\tmaxLen\tdom%\tavgSteps\tnodes@H" + maxHeight + "\textra",
    ];
    for (const m of selectedMembers) {
      lines.push(
        `${m.gcd}\t(${m.q1},${m.q2})\t(${m.mod4[0]},${m.mod4[1]})\t${m.num_loops}\t${m.max_loop_len}\t${m.dom_share_pct}\t${m.avg_steps}\t${m.nodes}\t${m.is_extra ? "extra" : "grid"}`
      );
    }
    return lines.join("\n");
  }

  async function copyFamilyText() {
    const txt = buildFamilyText();
    if (!txt) return;
    try {
      await navigator.clipboard.writeText(txt);
      statusMsg = "群情報をクリップボードにコピーしました";
    } catch {
      statusMsg = "クリップボードへのコピーに失敗しました";
    }
  }

  function downloadFamilyText() {
    const txt = buildFamilyText();
    if (!txt) return;
    const blob = new Blob([txt], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `p4_family_${selectedFamily.base[0]}_${selectedFamily.base[1]}_h${maxHeight}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function buildExportSvgString() {
    if (!svgElement) return "";
    const clone = svgElement.cloneNode(true);
    const g = clone.querySelector("g.heatmap-root");
    if (g) g.setAttribute("transform", "translate(0,0) scale(1)");
    clone.setAttribute("width", String(svgWidth));
    clone.setAttribute("height", String(svgHeight));
    clone.setAttribute("viewBox", `0 0 ${svgWidth} ${svgHeight}`);
    clone.style.background = "#0f172a";
    return new XMLSerializer().serializeToString(clone);
  }

  function exportSvg() {
    const svgStr = buildExportSvgString();
    if (!svgStr) return;
    const blob = new Blob([svgStr], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `p4_ctree_nodes_h${maxHeight}.svg`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportPng() {
    const svgStr = buildExportSvgString();
    if (!svgStr) return;
    const img = new Image();
    const blob = new Blob([svgStr], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    img.onload = () => {
      const scale = 2;
      const canvas = document.createElement("canvas");
      canvas.width = svgWidth * scale;
      canvas.height = svgHeight * scale;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#0f172a";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob((pngBlob) => {
        if (!pngBlob) return;
        const pUrl = URL.createObjectURL(pngBlob);
        const a = document.createElement("a");
        a.href = pUrl;
        a.download = `p4_ctree_nodes_h${maxHeight}.png`;
        a.click();
        URL.revokeObjectURL(pUrl);
      }, "image/png");
    };
    img.src = url;
  }

  onMount(() => {
    fetchHeatmap();
  });
</script>

<div class="heatmap-explorer">
  <div class="hm-toolbar">
    <div class="hm-title-block">
      <h2>p=4 CTree ノード数ヒートマップ &amp; Q群エクスプローラー</h2>
      <span class="hm-subtitle">
        セルをクリックすると同じ原始群 (Q<sub>base</sub>) に属する全セルが枠で囲まれ、群の統計モーダルが開きます
      </span>
    </div>

    <div class="hm-controls">
      <label class="hm-label">
        グリッド:
        <select bind:value={gridSize} on:change={fetchHeatmap} disabled={loading}>
          {#each availableGrids as gs}
            <option value={gs}>{gs}×{gs} ({(gs * gs).toLocaleString()})</option>
          {/each}
        </select>
      </label>

      <label class="hm-label">
        高さ H:
        <select bind:value={maxHeight} on:change={fetchHeatmap} disabled={loading}>
          <option value={6}>H = 6</option>
          <option value={8}>H = 8</option>
          <option value={10}>H = 10</option>
          <option value={12}>H = 12</option>
        </select>
      </label>

      <div class="hm-btn-group">
        <button on:click={() => zoomBy(1.25)} title="拡大">＋</button>
        <button on:click={() => zoomBy(0.8)} title="縮小">－</button>
        <button on:click={resetZoom} title="表示リセット">リセット ({Math.round(zoom * 100)}%)</button>
      </div>

      <div class="hm-btn-group">
        <button on:click={exportPng} disabled={loading}>🖼️ PNG出力</button>
        <button on:click={exportSvg} disabled={loading}>📐 SVG出力</button>
        {#if selectedFamily}
          <button class="btn-accent" on:click={() => (showModal = true)}>
            📊 選択中の群: {selectedBase}
          </button>
        {/if}
      </div>
    </div>
  </div>

  {#if error}
    <div class="hm-error">⚠️ {error}</div>
  {/if}

  <div
    class="hm-canvas-wrap"
    bind:this={svgContainer}
    on:wheel|preventDefault={handleWheel}
    on:mousedown={handleMouseDown}
    on:mousemove={handleMouseMove}
    on:mouseup={handleMouseUp}
    on:mouseleave={() => {
      handleMouseUp();
      hoveredCell = null;
    }}
  >
    {#if loading}
      <div class="hm-loading">ヒートマップを読み込み・計算中...</div>
    {:else}
      <svg
        bind:this={svgElement}
        class="hm-svg"
        width="100%"
        height="100%"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <linearGradient id="viridisGrad" x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%" stop-color="rgb(68,1,84)" />
            <stop offset="20%" stop-color="rgb(65,68,135)" />
            <stop offset="40%" stop-color="rgb(42,120,142)" />
            <stop offset="60%" stop-color="rgb(34,168,132)" />
            <stop offset="80%" stop-color="rgb(122,209,81)" />
            <stop offset="100%" stop-color="rgb(253,231,37)" />
          </linearGradient>
        </defs>

        <g class="heatmap-root" transform="translate({panX}, {panY}) scale({zoom})">
          <!-- Title inside SVG (also included in PNG/SVG export) -->
          <text
            x={PAD_LEFT + (q1Vals.length * CELL_SIZE) / 2}
            y={22}
            text-anchor="middle"
            fill="#f8fafc"
            font-size="14"
            font-weight="bold"
          >
            p=4 Total CTree Nodes up to H={maxHeight} ({Object.keys(cells).length} cells){selectedBase ? ` | Family ${selectedBase}` : ""}
          </text>

          <!-- Cells -->
          {#each q2Vals as q2, rIdx}
            {@const yPos = PAD_TOP + (q2Vals.length - 1 - rIdx) * CELL_SIZE}
            {#each q1Vals as q1, cIdx}
              {@const xPos = PAD_LEFT + cIdx * CELL_SIZE}
              {@const cell = cells[`${q1},${q2}`]}
              {@const isFamily = Boolean(cell && selectedBase && cell.base_str === selectedBase)}
              <!-- svelte-ignore a11y-click-events-have-key-events -->
              <rect
                x={xPos}
                y={yPos}
                width={CELL_SIZE}
                height={CELL_SIZE}
                fill={cell ? getCellColor(cell.nodes) : "#1e293b"}
                stroke={cell ? "rgba(255,255,255,0.16)" : "rgba(148,163,184,0.12)"}
                stroke-width="0.6"
                class:clickable={Boolean(cell)}
                on:mousemove={(e) => cell && handleCellMouseMove(e, cell)}
                on:mouseleave={() => (hoveredCell = null)}
                on:click={() => handleCellClick(cell)}
              />
              {#if cell?.is_extra}
                <circle
                  cx={xPos + CELL_SIZE - 4}
                  cy={yPos + 4}
                  r="2.2"
                  fill="#38bdf8"
                  pointer-events="none"
                />
              {/if}
              {#if isFamily}
                <rect
                  x={xPos + 1}
                  y={yPos + 1}
                  width={CELL_SIZE - 2}
                  height={CELL_SIZE - 2}
                  fill="none"
                  stroke="#0f172a"
                  stroke-width="3.2"
                  pointer-events="none"
                />
                <rect
                  x={xPos + 1}
                  y={yPos + 1}
                  width={CELL_SIZE - 2}
                  height={CELL_SIZE - 2}
                  fill="none"
                  stroke={cell.key === clickedCellKey ? "#fef08a" : "#ffffff"}
                  stroke-width="1.8"
                  pointer-events="none"
                />
              {/if}
            {/each}
          {/each}

          <!-- X-axis labels (q1) -->
          {#each q1Vals as q1, cIdx}
            {#if cIdx % (q1Vals.length > 50 ? 5 : 2) === 0 || q1 > 2 + 3 * ((gridSize || 30) - 1)}
              <text
                x={PAD_LEFT + cIdx * CELL_SIZE + CELL_SIZE / 2}
                y={PAD_TOP + q2Vals.length * CELL_SIZE + 14}
                text-anchor="middle"
                fill="#cbd5e1"
                font-size="9"
              >
                {q1}
              </text>
            {/if}
          {/each}
          <text
            x={PAD_LEFT + (q1Vals.length * CELL_SIZE) / 2}
            y={PAD_TOP + q2Vals.length * CELL_SIZE + 36}
            text-anchor="middle"
            fill="#e2e8f0"
            font-size="11"
            font-weight="bold"
          >
            q1 (2, 5, 8, ..., {q1Vals[q1Vals.length - 1] ?? 89})
          </text>

          <!-- Y-axis labels (q2) -->
          {#each q2Vals as q2, rIdx}
            {#if rIdx % (q2Vals.length > 50 ? 5 : 2) === 0 || q2 > 1 + 3 * ((gridSize || 30) - 1)}
              <text
                x={PAD_LEFT - 6}
                y={PAD_TOP + (q2Vals.length - 1 - rIdx) * CELL_SIZE + CELL_SIZE / 2 + 3}
                text-anchor="end"
                fill="#cbd5e1"
                font-size="9"
              >
                {q2}
              </text>
            {/if}
          {/each}
          <text
            x={16}
            y={PAD_TOP + (q2Vals.length * CELL_SIZE) / 2}
            text-anchor="middle"
            fill="#e2e8f0"
            font-size="11"
            font-weight="bold"
            transform="rotate(-90, 16, {PAD_TOP + (q2Vals.length * CELL_SIZE) / 2})"
          >
            q2 (1, 4, 7, ..., {q2Vals[q2Vals.length - 1] ?? 88})
          </text>

          <!-- Colorbar -->
          <rect
            x={PAD_LEFT + q1Vals.length * CELL_SIZE + 18}
            y={PAD_TOP}
            width="16"
            height={q2Vals.length * CELL_SIZE}
            fill="url(#viridisGrad)"
            stroke="#475569"
            stroke-width="1"
          />
          <text
            x={PAD_LEFT + q1Vals.length * CELL_SIZE + 40}
            y={PAD_TOP + 8}
            fill="#e2e8f0"
            font-size="9.5"
          >
            {maxNodes.toLocaleString()}
          </text>
          <text
            x={PAD_LEFT + q1Vals.length * CELL_SIZE + 40}
            y={PAD_TOP + (q2Vals.length * CELL_SIZE) / 2 + 3}
            fill="#cbd5e1"
            font-size="9"
          >
            {Math.round(Math.pow(10, (logMin + logMax) / 2)).toLocaleString()}
          </text>
          <text
            x={PAD_LEFT + q1Vals.length * CELL_SIZE + 40}
            y={PAD_TOP + q2Vals.length * CELL_SIZE}
            fill="#e2e8f0"
            font-size="9.5"
          >
            {minNodes.toLocaleString()}
          </text>
        </g>
      </svg>
    {/if}

    {#if hoveredCell}
      <div class="hm-tooltip" style="left: {tooltipX}px; top: {tooltipY}px;">
        <div class="tt-head">Q = ({hoveredCell.q1}, {hoveredCell.q2}) {hoveredCell.is_extra ? "★追加" : ""}</div>
        <div>H={maxHeight} ノード和: <strong>{hoveredCell.nodes.toLocaleString()}</strong></div>
        <div>群基底 Q<sub>base</sub>: <strong>{hoveredCell.base_str}</strong> (g={hoveredCell.gcd})</div>
        <div>mod 4: ({hoveredCell.mod4[0]}, {hoveredCell.mod4[1]}) / ループ数: {hoveredCell.num_loops}</div>
        <div>ループ長: [{hoveredCell.loop_lengths.join(", ")}]</div>
        <div>平均ステップ: {hoveredCell.avg_steps}</div>
      </div>
    {/if}
  </div>

  {#if showModal && selectedFamily}
    <!-- svelte-ignore a11y-click-events-have-key-events -->
    <div class="hm-modal-backdrop" on:click={() => (showModal = false)}>
      <div class="hm-modal" on:click|stopPropagation>
        <div class="hm-modal-header">
          <div>
            <h3>Q群詳細: 基底 Q<sub>base</sub> = {selectedFamily.base_str}</h3>
            <span class="hm-personality-badge">{selectedFamily.personality}</span>
          </div>
          <button class="hm-close-btn" on:click={() => (showModal = false)}>✕</button>
        </div>

        <div class="hm-modal-stats">
          <div class="stat-box">
            <span class="stat-lbl">表示中メンバー</span>
            <span class="stat-val">{selectedMembers.length} 個</span>
          </div>
          <div class="stat-box">
            <span class="stat-lbl">平均ノード数 (H={maxHeight})</span>
            <span class="stat-val">{selectedFamily.mean_nodes.toLocaleString()}</span>
          </div>
          <div class="stat-box">
            <span class="stat-lbl">最小 / 最大ノード</span>
            <span class="stat-val">{selectedFamily.min_nodes.toLocaleString()} / {selectedFamily.max_nodes.toLocaleString()}</span>
          </div>
          <div class="stat-box">
            <span class="stat-lbl">平均ステップ</span>
            <span class="stat-val">{selectedFamily.mean_avg_steps}</span>
          </div>
        </div>

        <div class="hm-modal-actions">
          <button
            class="btn-add-next"
            on:click={handleAddNextMember}
            disabled={addingNext || !nextMemberPreview}
          >
            {#if addingNext}
              ⏳ 計算中 (n=1..100,000)...
            {:else if nextMemberPreview}
              ➕ 次の要素を計算して追加: g={nextMemberPreview.g} Q=({nextMemberPreview.q1}, {nextMemberPreview.q2})
            {:else}
              追加可能な次の要素なし
            {/if}
          </button>
          <button on:click={copyFamilyText}>📋 テキストコピー</button>
          <button on:click={downloadFamilyText}>📄 テキスト保存</button>
        </div>

        {#if statusMsg}
          <div class="hm-status">{statusMsg}</div>
        {/if}

        <div class="hm-table-wrap">
          <table>
            <thead>
              <tr>
                <th>g</th>
                <th>Q = (q1, q2)</th>
                <th>mod 4</th>
                <th>ループ数</th>
                <th>最大長</th>
                <th>支配率</th>
                <th>平均ステップ</th>
                <th>ノード和 (H={maxHeight})</th>
              </tr>
            </thead>
            <tbody>
              {#each selectedMembers as m}
                <tr class:is-clicked={m.key === clickedCellKey}>
                  <td>{m.gcd}</td>
                  <td>
                    ({m.q1}, {m.q2})
                    {#if m.is_extra}<span class="badge-extra">追加</span>{/if}
                  </td>
                  <td>({m.mod4[0]}, {m.mod4[1]})</td>
                  <td>{m.num_loops}</td>
                  <td>{m.max_loop_len}</td>
                  <td>{m.dom_share_pct}%</td>
                  <td>{m.avg_steps}</td>
                  <td><strong>{m.nodes.toLocaleString()}</strong></td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .heatmap-explorer {
    display: flex;
    flex-direction: column;
    gap: 12px;
    background: #0f172a;
    color: #f8fafc;
    border-radius: 12px;
    padding: 16px;
    border: 1px solid #334155;
  }

  .hm-toolbar {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
  }

  .hm-title-block h2 {
    margin: 0;
    font-size: 1.15rem;
    color: #f8fafc;
  }

  .hm-subtitle {
    font-size: 0.82rem;
    color: #94a3b8;
  }

  .hm-controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
  }

  .hm-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.85rem;
    color: #cbd5e1;
  }

  .hm-label select {
    background: #1e293b;
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 4px 8px;
  }

  .hm-btn-group {
    display: flex;
    gap: 6px;
  }

  .hm-btn-group button,
  .hm-modal-actions button {
    background: #1e293b;
    color: #e2e8f0;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 0.82rem;
    cursor: pointer;
  }

  .hm-btn-group button:hover:not(:disabled),
  .hm-modal-actions button:hover:not(:disabled) {
    background: #334155;
  }

  .hm-btn-group button.btn-accent {
    background: #0284c7;
    border-color: #38bdf8;
    color: #fff;
  }

  .hm-canvas-wrap {
    position: relative;
    height: 760px;
    background: #0b1120;
    border: 1px solid #334155;
    border-radius: 8px;
    overflow: hidden;
    cursor: grab;
    user-select: none;
  }

  .hm-canvas-wrap:active {
    cursor: grabbing;
  }

  .hm-svg {
    display: block;
  }

  rect.clickable {
    cursor: pointer;
  }

  .hm-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #94a3b8;
  }

  .hm-error {
    background: rgba(220, 38, 38, 0.15);
    border: 1px solid #ef4444;
    color: #fecaca;
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 0.85rem;
  }

  .hm-tooltip {
    position: absolute;
    pointer-events: none;
    background: rgba(15, 23, 42, 0.95);
    border: 1px solid #38bdf8;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 0.78rem;
    line-height: 1.45;
    color: #f1f5f9;
    z-index: 30;
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.45);
    white-space: nowrap;
  }

  .tt-head {
    font-weight: bold;
    color: #38bdf8;
    margin-bottom: 2px;
  }

  .hm-modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(2, 6, 23, 0.65);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .hm-modal {
    width: min(820px, 94vw);
    max-height: 86vh;
    background: #0f172a;
    border: 1px solid #475569;
    border-radius: 12px;
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
    overflow: hidden;
  }

  .hm-modal-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }

  .hm-modal-header h3 {
    margin: 0 0 6px 0;
    font-size: 1.15rem;
    color: #f8fafc;
  }

  .hm-personality-badge {
    display: inline-block;
    background: rgba(56, 189, 248, 0.16);
    border: 1px solid #0284c7;
    color: #7dd3fc;
    font-size: 0.8rem;
    padding: 2px 8px;
    border-radius: 999px;
  }

  .hm-close-btn {
    background: transparent;
    border: none;
    color: #94a3b8;
    font-size: 1.2rem;
    cursor: pointer;
  }

  .hm-modal-stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
  }

  .stat-box {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .stat-lbl {
    font-size: 0.72rem;
    color: #94a3b8;
  }

  .stat-val {
    font-size: 0.95rem;
    font-weight: bold;
    color: #f8fafc;
  }

  .hm-modal-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .btn-add-next {
    background: #0369a1 !important;
    border-color: #38bdf8 !important;
    color: #ffffff !important;
    font-weight: bold;
  }

  .btn-add-next:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .hm-status {
    font-size: 0.82rem;
    color: #86efac;
    background: rgba(22, 163, 74, 0.15);
    border: 1px solid #16a34a;
    padding: 6px 10px;
    border-radius: 6px;
  }

  .hm-table-wrap {
    overflow: auto;
    border: 1px solid #334155;
    border-radius: 8px;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
  }

  th,
  td {
    padding: 7px 10px;
    border-bottom: 1px solid #1e293b;
    text-align: right;
  }

  th:nth-child(2),
  td:nth-child(2),
  th:nth-child(3),
  td:nth-child(3) {
    text-align: left;
  }

  th {
    background: #1e293b;
    color: #cbd5e1;
    position: sticky;
    top: 0;
  }

  tr.is-clicked {
    background: rgba(250, 204, 21, 0.14);
  }

  .badge-extra {
    display: inline-block;
    margin-left: 4px;
    padding: 1px 5px;
    font-size: 0.68rem;
    border-radius: 4px;
    background: #0284c7;
    color: #fff;
  }
</style>

