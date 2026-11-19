<script>
  import { onMount } from 'svelte';
  import InteractivePlot from './components/InteractivePlot.svelte';
  import NodeInspector from './components/NodeInspector.svelte';
  import LoopTreeModal from './components/LoopTreeModal.svelte';
  import TreeOverlayCompare from './components/TreeOverlayCompare.svelte';
  import P4HeatmapExplorer from './components/P4HeatmapExplorer.svelte';

  let presets = [];
  let activeTab = 'heights'; // 'heights' | 'ctree' | 'treeOverlay' | 'p4Heatmap'
  let layoutMode = '1col'; // '1col' | '2col' | 'overlay'
  let syncZoom = true;
  let sharedViewport = null;

  let nextPanelId = 1;
  let panels = [];

  // Node Inspector state (shared drawer or active panel inspection)
  let inspectorLoading = false;
  let inspectorDetails = null;
  let inspectorPanelId = null;
  let focusedNode = null; // { n, steps, panelId }

  // Loop Right-Click Context Menu & Floating CTree Windows
  let loopContextMenu = null; // { x, y, panel, loop }
  let nextTreeWinId = 1;
  let treeWindows = []; // [{ id, panelId, p, q, loop, defaultColor }]

  function createPanelConfig({
    title = 'グラフ 1 (3n+5 問題)',
    p = 3,
    q = [null, 5],
    n_start = 1,
    n_end = 10000,
    max_steps = 10000,
    nodeSize = 2.5,
    opacity = 0.85,
  } = {}) {
    const id = nextPanelId++;
    return {
      id,
      title,
      p,
      q: [...q],
      n_start,
      n_end,
      max_steps,
      nodeSize,
      opacity,
      visibleLoops: {},
      loopColors: {},
      data: null,
      loading: false,
      error: null,
      directInspectN: '',
      quickSpec: '',
      showControls: false,
      showAdvanced: false,
    };
  }

  /**
   * Adjust length of Q array when p changes:
   * d = p - 1, so Q has length d: [null, q_1, ..., q_{d-1}]
   */
  function handlePChange(panel, newP) {
    const pVal = Math.max(2, Math.min(30, parseInt(newP, 10) || 3));
    panel.p = pVal;
    const d = pVal - 1;
    const nextQ = [null];
    for (let r = 1; r < d; r++) {
      if (panel.q[r] !== undefined && panel.q[r] !== null && panel.q[r] > 0) {
        nextQ.push(Number(panel.q[r]));
      } else {
        // Default to smallest positive integer q_r such that (p * r + q_r) % d == 0
        const rem = (pVal * r) % d;
        const defaultQr = rem === 0 ? d : d - rem;
        nextQ.push(defaultQr);
      }
    }
    panel.q = nextQ;
    panels = [...panels];
  }

  function autoFillDivisibleQ(panel) {
    const d = panel.p - 1;
    const nextQ = [null];
    for (let r = 1; r < d; r++) {
      const rem = (panel.p * r) % d;
      nextQ.push(rem === 0 ? d : d - rem);
    }
    panel.q = nextQ;
    panels = [...panels];
  }

  function checkDivisibility(p, q) {
    const d = p - 1;
    const issues = [];
    for (let r = 1; r < d; r++) {
      const qr = Number(q[r]);
      if (!Number.isInteger(qr) || qr <= 0) {
        issues.push(`q_${r} は正の整数を指定してください`);
      } else if ((p * r + qr) % d !== 0) {
        const req = (d - ((p * r) % d)) % d;
        issues.push(`r=${r}: ${p}n+${qr} が d=${d} で割り切れません (q_${r} ≡ ${req} mod ${d} が必要)`);
      }
    }
    return issues;
  }

  function applyPreset(panel, presetIdx) {
    const pr = presets[presetIdx];
    if (!pr) return;
    panel.title = `グラフ ${panel.id} (${pr.name})`;
    panel.p = pr.p;
    panel.q = [...pr.q];
    panels = [...panels];
    computePanel(panel);
  }

  async function computePanel(panel) {
    panel.loading = true;
    panel.error = null;
    panels = [...panels];

    try {
      const res = await fetch('/api/compute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          p: Number(panel.p),
          q: panel.q.map((x, idx) => (idx === 0 ? null : Number(x))),
          n_start: Number(panel.n_start),
          n_end: Number(panel.n_end),
          max_steps: Number(panel.max_steps),
        }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP Error ${res.status}`);
      }
      const data = await res.json();
      panel.data = data;

      // Initialize visibility & colors for newly discovered loops while preserving user overrides
      const nextVisible = { ...panel.visibleLoops };
      const nextColors = { ...panel.loopColors };
      for (const lp of data.loops) {
        if (nextVisible[lp.loop_id] === undefined) {
          nextVisible[lp.loop_id] = true;
        }
        if (!nextColors[lp.loop_id]) {
          nextColors[lp.loop_id] = lp.color;
        }
      }
      panel.visibleLoops = nextVisible;
      panel.loopColors = nextColors;
    } catch (err) {
      panel.error = err.message;
    } finally {
      panel.loading = false;
      panels = [...panels];
    }
  }

  async function applyQuickSpec(panel) {
    const raw = (panel.quickSpec || '').trim();
    if (!raw) return;

    panel.error = null;
    const pMatch = raw.match(/\bp\s*=\s*(\d+)/i);
    const parsedP = pMatch ? parseInt(pMatch[1], 10) : null;
    const sysMatch = raw.match(/\b(?:sys_id|system_id|id)\s*=\s*(\d+)/i);

    if (sysMatch) {
      const targetP = parsedP ?? Number(panel.p);
      const sysId = parseInt(sysMatch[1], 10);
      panel.loading = true;
      panels = [...panels];
      try {
        const res = await fetch(`/api/summary-system?p=${targetP}&sys_id=${sysId}`);
        if (!res.ok) {
          const errBody = await res.json().catch(() => ({}));
          throw new Error(errBody.detail || `HTTP Error ${res.status}`);
        }
        const data = await res.json();
        panel.p = Number(data.p);
        panel.q = data.q.map((x, idx) => (idx === 0 ? null : Number(x)));
        panel.title = `グラフ ${panel.id} (p=${panel.p}, sys_id=${data.system_id})`;
        panel.loading = false;
        panels = [...panels];
        await computePanel(panel);
      } catch (err) {
        panel.error = err.message;
        panel.loading = false;
        panels = [...panels];
      }
      return;
    }

    const qMatch = raw.match(/(?:q\s*=\s*)?\[([^\]]+)\]/i);
    if (qMatch) {
      let tokens = qMatch[1]
        .split(/[\s,]+/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      if (tokens.length > 0 && /^(_|null|none)$/i.test(tokens[0])) {
        tokens = tokens.slice(1);
      }
      const nums = tokens.map((s) => Number(s));
      if (nums.length === 0 || nums.some((n) => !Number.isInteger(n) || n < 1)) {
        panel.error = 'Q の値は正の整数で指定してください (例: p=9,Q=[7,6,13,20,3,10,25])';
        panels = [...panels];
        return;
      }
      const targetP = parsedP ?? (nums.length + 2);
      if (targetP < 2 || targetP > 30) {
        panel.error = `p は 2〜30 の範囲で指定してください (指定値: ${targetP})`;
        panels = [...panels];
        return;
      }
      if (nums.length !== targetP - 2) {
        panel.error = `p=${targetP} に対して Q の要素数は ${targetP - 2} 個必要です（入力: ${nums.length} 個）`;
        panels = [...panels];
        return;
      }
      panel.p = targetP;
      panel.q = [null, ...nums];
      panel.title = `グラフ ${panel.id} (p=${targetP}, Q=[${nums.join(',')}])`;
      panels = [...panels];
      await computePanel(panel);
      return;
    }

    if (parsedP !== null) {
      handlePChange(panel, parsedP);
      return;
    }

    panel.error = '入力形式を認識できませんでした (例: p=9,Q=[7,6,13,20,3,10,25] または p=9,sys_id=8 / sys_id=8)';
    panels = [...panels];
  }

  function addComparisonPanel() {
    // Default second panel to 3n+1 or duplicate settings for easy comparison
    const isSecond = panels.length === 1;
    const newPanel = createPanelConfig({
      title: isSecond ? `グラフ ${nextPanelId} (3n+1 コラッツ予想)` : `グラフ ${nextPanelId} (3n+5 問題)`,
      p: 3,
      q: isSecond ? [null, 1] : [null, 5],
      n_start: panels[0]?.n_start || 1,
      n_end: panels[0]?.n_end || 10000,
      max_steps: panels[0]?.max_steps || 10000,
      nodeSize: 2.5,
      opacity: panels.length >= 1 ? 0.75 : 0.85,
    });
    panels = [...panels, newPanel];
    if (panels.length === 2 && layoutMode === '1col') {
      layoutMode = '2col';
    }
    computePanel(newPanel);
  }

  function duplicatePanel(src) {
    const copy = createPanelConfig({
      title: `${src.title} (複製)`,
      p: src.p,
      q: [...src.q],
      n_start: src.n_start,
      n_end: src.n_end,
      max_steps: src.max_steps,
      nodeSize: src.nodeSize,
      opacity: src.opacity,
    });
    copy.loopColors = { ...src.loopColors };
    copy.visibleLoops = { ...src.visibleLoops };
    panels = [...panels, copy];
    computePanel(copy);
  }

  function removePanel(id) {
    if (panels.length <= 1) return;
    panels = panels.filter((p) => p.id !== id);
    if (inspectorPanelId === id) {
      inspectorDetails = null;
      inspectorPanelId = null;
    }
  }

  function toggleAllLoops(panel, visible) {
    if (!panel.data?.loops) return;
    const next = { ...panel.visibleLoops };
    for (const lp of panel.data.loops) {
      next[lp.loop_id] = visible;
    }
    panel.visibleLoops = next;
    panels = [...panels];
  }

  function isolateSingleLoop(panel, targetLoopId) {
    if (!panel.data?.loops) return;
    const next = {};
    for (const lp of panel.data.loops) {
      next[lp.loop_id] = lp.loop_id === targetLoopId;
    }
    panel.visibleLoops = next;
    panels = [...panels];
  }

  function handleLoopRegionContextMenu(e, panel, loop = null) {
    e.preventDefault();
    e.stopPropagation();
    const selectedLoop = loop || panel.data?.loops?.[0] || null;
    if (!selectedLoop) return;
    const menuWidth = 320;
    const menuHeight = 220;
    const x = Math.min(e.clientX, window.innerWidth - menuWidth - 12);
    const y = Math.min(e.clientY, window.innerHeight - menuHeight - 12);
    loopContextMenu = {
      x: Math.max(8, x),
      y: Math.max(8, y),
      panel,
      loop: selectedLoop,
    };
  }

  function openLoopTreeWindow(panel, loop) {
    if (!panel || !loop) return;
    const color = panel.loopColors?.[loop.loop_id] || loop.color || '#0284c7';
    const winId = nextTreeWinId++;
    treeWindows = [
      ...treeWindows,
      {
        id: winId,
        panelId: panel.id,
        p: Number(panel.p),
        q: panel.q.map((x, idx) => (idx === 0 ? null : Number(x))),
        loop,
        defaultColor: color,
      },
    ];
    loopContextMenu = null;
  }

  function closeLoopTreeWindow(winId) {
    treeWindows = treeWindows.filter((w) => w.id !== winId);
  }

  async function inspectNode(panel, targetN) {
    const nVal = parseInt(targetN, 10);
    if (!Number.isInteger(nVal) || nVal < 1) return;

    inspectorPanelId = panel.id;
    inspectorLoading = true;
    try {
      const res = await fetch('/api/node-details', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          p: Number(panel.p),
          q: panel.q.map((x, idx) => (idx === 0 ? null : Number(x))),
          target_n: nVal,
          n_start: Number(panel.n_start),
          n_end: Number(panel.n_end),
          max_steps: Number(panel.max_steps),
        }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP Error ${res.status}`);
      }
      inspectorDetails = await res.json();
      focusedNode = {
        n: inspectorDetails.target.n,
        steps: inspectorDetails.target.steps,
        panelId: panel.id,
      };
    } catch (err) {
      alert(`ノード詳細の取得に失敗しました: ${err.message}`);
    } finally {
      inspectorLoading = false;
    }
  }

  function handleNodeContextInspect(event, defaultPanel) {
    const pt = event.detail;
    const targetPanel = panels.find((p) => p.id === pt.datasetId) || defaultPanel;
    if (targetPanel) {
      inspectNode(targetPanel, pt.n);
    }
  }

  async function downloadBackendExport(panel, fmt) {
    try {
      const visibleIds = Object.entries(panel.visibleLoops)
        .filter(([, vis]) => vis)
        .map(([lid]) => Number(lid));

      const res = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          p: Number(panel.p),
          q: panel.q.map((x, idx) => (idx === 0 ? null : Number(x))),
          n_start: Number(panel.n_start),
          n_end: Number(panel.n_end),
          max_steps: Number(panel.max_steps),
          format: fmt,
          visible_loop_ids: visibleIds,
          custom_colors: panel.loopColors,
          node_size: Number(panel.nodeSize),
          opacity: Number(panel.opacity),
        }),
      });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const qStr = panel.q.slice(1).join('_');
      a.href = url;
      a.download = `iter_p${panel.p}_Q${qStr}_${panel.n_start}_${panel.n_end}.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`画像出力エラー: ${err.message}`);
    }
  }

  onMount(async () => {
    try {
      const res = await fetch('/api/presets');
      if (res.ok) {
        presets = await res.json();
      }
    } catch (_) {
      // ignore preset fetch error if offline
    }

    const first = createPanelConfig();
    panels = [first];
    await computePanel(first);
  });

  $: activeInspectorPanel = panels.find((p) => p.id === inspectorPanelId) || panels[0];
</script>

<div class="app-shell">
  <!-- Top Navigation & Global Controls -->
  <header class="app-header">
    <div class="brand" title="d = p - 1, r = n mod d に応じ n/d または pn + q_r を反復し、到達ステップ・CTree・結晶成長を観察">
      <h1>T<sub>p,Q</sub>(n) 解析</h1>
    </div>

    <div class="global-actions">
      <div class="view-tabs" role="tablist" aria-label="解析ビュー切替">
        <button
          role="tab"
          aria-selected={activeTab === 'heights'}
          class:active={activeTab === 'heights'}
          on:click={() => (activeTab = 'heights')}
        >
          📈 Heights Plot
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'ctree'}
          class:active={activeTab === 'ctree'}
          on:click={() => (activeTab = 'ctree')}
        >
          🌳 CTree / 結晶成長
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'treeOverlay'}
          class:active={activeTab === 'treeOverlay'}
          on:click={() => (activeTab = 'treeOverlay')}
        >
          🔀 2ツリー重ね合わせ比較
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'p4Heatmap'}
          class:active={activeTab === 'p4Heatmap'}
          on:click={() => (activeTab = 'p4Heatmap')}
        >
          🗺️ p=4 ヒートマップ
        </button>
      </div>

      {#if activeTab === 'heights'}
        <div class="layout-switcher">
          <button
            class:active={layoutMode === '1col'}
            on:click={() => (layoutMode = '1col')}
          >
            1列
          </button>
          <button
            class:active={layoutMode === '2col'}
            on:click={() => (layoutMode = '2col')}
          >
            2列
          </button>
          <button
            class:active={layoutMode === 'overlay'}
            on:click={() => (layoutMode = 'overlay')}
            title="複数の Heights Plot を透明度付きで1つの座標軸に重ねて比較します"
          >
            Heights重ね合わせ
          </button>
        </div>

        {#if layoutMode !== 'overlay' && panels.length > 1}
          <label class="sync-toggle">
            <input type="checkbox" bind:checked={syncZoom} />
            同期ズーム
          </label>
        {/if}

        <button class="btn-add-panel" on:click={addComparisonPanel}>
          ＋ グラフ追加 ({panels.length})
        </button>
      {/if}
    </div>
  </header>

  <main class="main-content">
    {#if activeTab === 'heights'}
    <!-- Parameter & Style Control Cards for each graph panel -->
    <section class="panels-grid" class:two-col={layoutMode === '2col'}>
      {#each panels as panel (panel.id)}
        {@const divIssues = checkDivisibility(panel.p, panel.q)}
        <div class="panel-card">
          <!-- Compact Top Bar: Title, Summary, Presets, Controls Toggle -->
          <div class="panel-card-header">
            <div class="panel-title-wrap">
              <input
                class="panel-title-input"
                type="text"
                bind:value={panel.title}
                aria-label="グラフタイトル"
              />
              <span class="panel-summary-pill">
                p={panel.p}, Q=[_, {panel.q.slice(1).join(', ')}]
                {#if panel.data?.loops}
                  · ループ {panel.data.loops.length}個
                {/if}
              </span>
            </div>

            <div class="panel-header-btns">
              {#if presets.length > 0}
                <select
                  class="preset-select"
                  on:change={(e) => {
                    if (e.target.value !== '') {
                      applyPreset(panel, Number(e.target.value));
                      e.target.value = '';
                    }
                  }}
                >
                  <option value="">プリセット...</option>
                  {#each presets as pr, idx}
                    <option value={idx}>{pr.name}</option>
                  {/each}
                </select>
              {/if}

              <button
                type="button"
                class="btn-sm btn-run-mini"
                disabled={panel.loading}
                on:click={() => computePanel(panel)}
                title="現在の設定で再計算"
              >
                {panel.loading ? '計算中...' : '▶ 更新'}
              </button>

              <button
                type="button"
                class="btn-sm"
                class:btn-active={panel.showControls}
                on:click={() => {
                  panel.showControls = !panel.showControls;
                  panels = [...panels];
                }}
              >
                ⚙ メニュー {panel.showControls ? '▴' : '▾'}
              </button>
            </div>
          </div>

          {#if panel.error}
            <div class="error-banner">エラー: {panel.error}</div>
          {/if}

          {#if panel.showControls}
            <div class="controls-drawer">
              <div class="controls-subbar">
                <button
                  type="button"
                  class="btn-sm"
                  class:btn-active={panel.showAdvanced}
                  on:click={() => {
                    panel.showAdvanced = !panel.showAdvanced;
                    panels = [...panels];
                  }}
                >
                  詳細設定（範囲・見た目・複製） {panel.showAdvanced ? '▴' : '▾'}
                </button>
              </div>
              <!-- Quick Spec Input: p=..., Q=[...] or sys_id=... -->
              <div class="quick-spec-row">
                <label for="qspec-{panel.id}" class="quick-spec-label">一括指定 / DB検索:</label>
                <input
                  id="qspec-{panel.id}"
                  type="text"
                  class="quick-spec-input"
                  bind:value={panel.quickSpec}
                  placeholder="例: p=9,Q=[7,6,13,20,3,10,25] または p=9,sys_id=8 / sys_id=8"
                  on:keydown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      applyQuickSpec(panel);
                    }
                  }}
                />
                <button
                  type="button"
                  class="btn-sm btn-apply-spec"
                  disabled={panel.loading || !panel.quickSpec?.trim()}
                  on:click={() => applyQuickSpec(panel)}
                >
                  適用して計算
                </button>
              </div>

              <!-- Primary System Selector: p, Q, Run -->
              <div class="param-row">
            <div class="field-group">
              <label for="p-{panel.id}">パラメータ p (除数 d = {panel.p - 1})</label>
              <input
                id="p-{panel.id}"
                type="number"
                min="2"
                max="30"
                value={panel.p}
                on:change={(e) => handlePChange(panel, e.target.value)}
                class="input-num short"
              />
            </div>

            <div class="field-group q-vector-group">
              <div class="q-header">
                <span>ベクトル Q = [ _, {panel.q.slice(1).map((_, i) => `q_${i + 1}`).join(', ')} ]</span>
                <button
                  type="button"
                  class="btn-link"
                  on:click={() => autoFillDivisibleQ(panel)}
                  title="(p*r + q_r) mod (p-1) = 0 を満たす最小の正整数を自動セットします"
                >
                  自動補完
                </button>
              </div>
              <div class="q-inputs">
                <span class="q-unused" title="0番目 (r=0) は n/d のため不使用">[ _ ,</span>
                {#each panel.q.slice(1) as qr, idx}
                  {@const r = idx + 1}
                  {@const dStep = Math.max(1, Number(panel.p) - 1)}
                  {@const curVal = Number(panel.q[r])}
                  {@const minVal = Number.isFinite(curVal) && curVal >= 1 ? ((curVal - 1) % dStep) + 1 : 1}
                  <div class="q-item">
                    <small>q<sub>{r}</sub> (r={r})</small>
                    <input
                      type="number"
                      min={minVal}
                      step={dStep}
                      bind:value={panel.q[r]}
                      on:input={() => (panels = [...panels])}
                      class="input-num q-input"
                    />
                  </div>
                {/each}
                <span class="q-unused">]</span>
              </div>
            </div>

            <div class="field-group action-col">
              <button
                class="btn-compute"
                disabled={panel.loading}
                on:click={() => computePanel(panel)}
              >
                {panel.loading ? '計算中...' : '▶ 計算・描画更新'}
              </button>
            </div>
          </div>

          {#if divIssues.length > 0}
            <div class="warning-banner">
              ⚠ 整除条件の確認: {divIssues.join(' / ')}
            </div>
          {/if}

          {#if panel.error}
            <div class="error-banner">エラー: {panel.error}</div>
          {/if}

          <!-- Collapsible Advanced Settings (Range, Visual Sliders, Inspect, Export, Panel Ops) -->
          {#if panel.showAdvanced}
            <div class="advanced-drawer">
              <div class="param-row advanced-range-row">
                <div class="field-group">
                  <label for="start-{panel.id}">横軸 始点 N<sub>start</sub></label>
                  <input
                    id="start-{panel.id}"
                    type="number"
                    min="1"
                    bind:value={panel.n_start}
                    class="input-num medium"
                  />
                </div>

                <div class="field-group">
                  <label for="end-{panel.id}">横軸 終点 N<sub>end</sub></label>
                  <input
                    id="end-{panel.id}"
                    type="number"
                    min="1"
                    bind:value={panel.n_end}
                    class="input-num medium"
                  />
                </div>

                <div class="field-group">
                  <label for="maxs-{panel.id}">最大ステップ上限</label>
                  <input
                    id="maxs-{panel.id}"
                    type="number"
                    min="100"
                    max="500000"
                    step="1000"
                    bind:value={panel.max_steps}
                    class="input-num medium"
                  />
                </div>

                <div class="field-group">
                  <span class="ctrl-label">パネル操作</span>
                  <div class="panel-header-btns">
                    <button class="btn-sm" on:click={() => duplicatePanel(panel)} title="このグラフ設定を複製">
                      複製
                    </button>
                    {#if panels.length > 1}
                      <button class="btn-sm btn-danger" on:click={() => removePanel(panel.id)} title="削除">
                        削除
                      </button>
                    {/if}
                  </div>
                </div>
              </div>

              <div class="visual-controls-bar">
                <div class="slider-item">
                  <label for="size-{panel.id}">ノードサイズ: <strong>{panel.nodeSize}px</strong></label>
                  <input
                    id="size-{panel.id}"
                    type="range"
                    min="0.8"
                    max="10"
                    step="0.2"
                    bind:value={panel.nodeSize}
                    on:input={() => (panels = [...panels])}
                  />
                </div>

                <div class="slider-item">
                  <label for="op-{panel.id}">不透明度 (Opacity): <strong>{Math.round(panel.opacity * 100)}%</strong></label>
                  <input
                    id="op-{panel.id}"
                    type="range"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    bind:value={panel.opacity}
                    on:input={() => (panels = [...panels])}
                  />
                </div>

                <div class="direct-inspect">
                  <input
                    type="number"
                    min="1"
                    placeholder="数値 n を直接入力して検査..."
                    bind:value={panel.directInspectN}
                    on:keydown={(e) => e.key === 'Enter' && inspectNode(panel, panel.directInspectN)}
                    class="input-num medium"
                  />
                  <button
                    class="btn-sm"
                    on:click={() => inspectNode(panel, panel.directInspectN)}
                  >
                    数値検査
                  </button>
                </div>

                <div class="backend-export-group">
                  <span class="export-label">Matplotlib高精細出力:</span>
                  <button class="btn-sm" on:click={() => downloadBackendExport(panel, 'png')}>
                    PNG (1800×1000)
                  </button>
                  <button class="btn-sm" on:click={() => downloadBackendExport(panel, 'svg')}>
                    SVG
                  </button>
                </div>
              </div>
            </div>
          {/if}

          <!-- Discovered Loops Legend & Per-Loop Visibility / Color Pickers -->
          {#if panel.data?.loops}
            <!-- svelte-ignore a11y-no-static-element-interactions -->
            <div
              class="loops-section"
              on:contextmenu={(e) => handleLoopRegionContextMenu(e, panel, null)}
            >
              <div class="loops-header">
                <span>
                  特定されたループ一覧: <strong>{panel.data.loops.length} 個</strong>
                  <small>
                    （計算時間: {panel.data.elapsed_ms} ms / DB総キャッシュ数: {panel.data.total_cached_nodes.toLocaleString()} 個）
                  </small>
                  <span class="loop-ctx-hint">💡 各ループを右クリックで全要素＆CTree（木構造）表示</span>
                </span>
                <div class="loops-bulk-btns">
                  <button class="btn-xs" on:click={() => toggleAllLoops(panel, true)}>全表示</button>
                  <button class="btn-xs" on:click={() => toggleAllLoops(panel, false)}>全非表示</button>
                </div>
              </div>

              <div class="loops-chip-list">
                {#each panel.data.loops as lp}
                  {@const isVis = panel.visibleLoops[lp.loop_id] !== false}
                  <!-- svelte-ignore a11y-no-static-element-interactions -->
                  <div
                    class="loop-chip"
                    class:dimmed={!isVis}
                    on:contextmenu={(e) => handleLoopRegionContextMenu(e, panel, lp)}
                    title="右クリックでループ全要素・CTree（木構造）メニューを表示"
                  >
                    <input
                      type="checkbox"
                      checked={isVis}
                      on:change={(e) => {
                        panel.visibleLoops[lp.loop_id] = e.target.checked;
                        panels = [...panels];
                      }}
                      title="表示 / 非表示を切替"
                    />
                    <input
                      type="color"
                      value={panel.loopColors[lp.loop_id] || lp.color}
                      on:input={(e) => {
                        panel.loopColors[lp.loop_id] = e.target.value;
                        panels = [...panels];
                      }}
                      class="color-picker"
                      title="ループのプロット色を変更"
                    />
                    <span class="loop-chip-label">{lp.label}</span>
                    <span class="loop-chip-count">({lp.count_in_range.toLocaleString()}点)</span>
                    <button
                      type="button"
                      class="btn-tree-icon"
                      on:click={() => openLoopTreeWindow(panel, lp)}
                      title="このループの全要素とCTree（木構造）をフローティングウインドウで開く"
                    >
                      🌳
                    </button>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
            </div>
          {/if}

          <!-- Individual Interactive Plot (shown when NOT in overlay mode) -->
          {#if layoutMode !== 'overlay'}
            <div class="plot-container">
              <InteractivePlot
                datasets={[panel]}
                {syncZoom}
                syncedViewport={sharedViewport}
                focusedNode={focusedNode?.panelId === panel.id ? focusedNode : null}
                on:viewportChange={(e) => (sharedViewport = e.detail)}
                on:nodeContextInspect={(e) => handleNodeContextInspect(e, panel)}
              />
            </div>
          {/if}
        </div>
      {/each}
    </section>

    <!-- Combined Overlay Plot (shown when layoutMode === 'overlay') -->
    {#if layoutMode === 'overlay'}
      <section class="overlay-section">
        <div class="overlay-header">
          <h3>
            重ね合わせ比較プロット (全 {panels.length} グラフを同時描画 — 各パネルの不透明度・色・サイズ設定がリアルタイム反映されます)
          </h3>
        </div>
        <InteractivePlot
          datasets={panels}
          syncZoom={false}
          {focusedNode}
          on:nodeContextInspect={(e) => handleNodeContextInspect(e, panels[0])}
        />
      </section>
    {/if}

    <!-- Right-Click Node Inspector Table Panel -->
    <NodeInspector
      details={inspectorDetails}
      loading={inspectorLoading}
      p={activeInspectorPanel?.p || 3}
      q={activeInspectorPanel?.q || [null, 5]}
      loopColors={activeInspectorPanel?.loopColors || {}}
      on:inspectNode={(e) => inspectNode(activeInspectorPanel, e.detail.n)}
      on:focusNode={(e) => {
        focusedNode = {
          n: e.detail.n,
          steps: e.detail.steps,
          panelId: activeInspectorPanel?.id,
        };
      }}
      on:close={() => {
        inspectorDetails = null;
      }}
    />
    {:else if activeTab === 'ctree'}
      <section class="panel-card ctree-launcher-card">
        <h3>🌳 CTree / 結晶成長ビューア</h3>
        <p class="subtitle">
          計算済みパネルの各ループをクリックすると、逆木（CTree）および暗視野結晶成長 GIF 生成ウィンドウを直接開けます。
        </p>
        {#each panels as panel (panel.id)}
          <div class="ctree-panel-group">
            <div class="ctree-panel-title">
              <strong>{panel.title}</strong>
              <span>（p={panel.p}, Q=[_, {panel.q.slice(1).join(', ')}]）</span>
            </div>
            {#if panel.data?.loops?.length > 0}
              <div class="loops-chip-list">
                {#each panel.data.loops as lp}
                  <button
                    type="button"
                    class="loop-chip ctree-launch-chip"
                    on:click={() => openLoopTreeWindow(panel, lp)}
                  >
                    <span class="tt-dot" style="background: {panel.loopColors[lp.loop_id] || lp.color}"></span>
                    <span>{lp.label}</span>
                    <span class="loop-chip-count">({lp.count_in_range.toLocaleString()}点)</span>
                    <span>🌳 開く</span>
                  </button>
                {/each}
              </div>
            {:else}
              <p class="subtitle">未計算です。Heights Plot タブで「▶ 計算・描画更新」を実行してください。</p>
            {/if}
          </div>
        {/each}
      </section>
    {:else if activeTab === 'treeOverlay'}
      <TreeOverlayCompare {panels} />
    {:else if activeTab === 'p4Heatmap'}
      <P4HeatmapExplorer />
    {/if}

    <!-- Right-Click Context Menu on Loop Display Region -->
    {#if loopContextMenu}
      <!-- svelte-ignore a11y-click-events-have-key-events -->
      <!-- svelte-ignore a11y-no-static-element-interactions -->
      <div
        class="loop-context-menu"
        style="left: {loopContextMenu.x}px; top: {loopContextMenu.y}px;"
        on:click|stopPropagation
      >
        <div class="ctx-menu-header">
          <span
            class="ctx-color-dot"
            style="background: {loopContextMenu.panel.loopColors[loopContextMenu.loop.loop_id] || loopContextMenu.loop.color};"
          ></span>
          <strong>{loopContextMenu.loop.label}</strong>
          <small>（周期 {loopContextMenu.loop.length}）</small>
        </div>

        {#if loopContextMenu.panel.data?.loops?.length > 1}
          <div class="ctx-loop-selector">
            <label for="ctx-loop-sel">対象ループ切替:</label>
            <select
              id="ctx-loop-sel"
              value={loopContextMenu.loop.loop_id}
              on:change={(e) => {
                const lid = Number(e.target.value);
                const found = loopContextMenu.panel.data.loops.find((l) => l.loop_id === lid);
                if (found) loopContextMenu = { ...loopContextMenu, loop: found };
              }}
            >
              {#each loopContextMenu.panel.data.loops as lp}
                <option value={lp.loop_id}>{lp.label} ({lp.count_in_range.toLocaleString()}点)</option>
              {/each}
            </select>
          </div>
        {/if}

        <button
          type="button"
          class="ctx-menu-item primary"
          on:click={() => openLoopTreeWindow(loopContextMenu.panel, loopContextMenu.loop)}
        >
          🌳 ループ全要素 ＆ CTree（木構造）を表示...
        </button>

        <button
          type="button"
          class="ctx-menu-item"
          on:click={() => {
            inspectNode(loopContextMenu.panel, loopContextMenu.loop.min_element);
            loopContextMenu = null;
          }}
        >
          🔍 最小要素 n = {loopContextMenu.loop.min_element} をノード検査
        </button>

        <button
          type="button"
          class="ctx-menu-item"
          on:click={() => {
            isolateSingleLoop(loopContextMenu.panel, loopContextMenu.loop.loop_id);
            loopContextMenu = null;
          }}
        >
          👁 このループのみをグラフに表示
        </button>

        <button
          type="button"
          class="ctx-menu-item"
          on:click={() => {
            toggleAllLoops(loopContextMenu.panel, true);
            loopContextMenu = null;
          }}
        >
          🔄 全ループをグラフに表示
        </button>
      </div>
    {/if}

    <!-- Floating CTree Windows -->
    {#each treeWindows as win (win.id)}
      <LoopTreeModal
        windowId={win.id}
        p={win.p}
        q={win.q}
        loopInfo={{ ...win.loop, color: win.defaultColor || win.loop?.color }}
        initialX={80 + ((win.id - 1) % 5) * 32}
        initialY={60 + ((win.id - 1) % 5) * 28}
        on:close={() => closeLoopTreeWindow(win.id)}
        on:inspectNode={(e) => {
          const targetPanel = panels.find((p) => p.id === win.panelId) || panels[0];
          if (targetPanel) inspectNode(targetPanel, e.detail.n);
        }}
      />
    {/each}
  </main>
</div>

<svelte:window
  on:click={() => {
    if (loopContextMenu) loopContextMenu = null;
  }}
  on:keydown={(e) => {
    if (e.key === 'Escape' && loopContextMenu) loopContextMenu = null;
  }}
/>

<style>
  .app-shell {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  .app-header {
    background: #0f172a;
    color: #ffffff;
    padding: 6px 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
  }

  .brand h1 {
    margin: 0;
    font-size: 1rem;
    font-weight: 700;
    white-space: nowrap;
  }

  .global-actions {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
  }

  .layout-switcher {
    display: flex;
    align-items: center;
    background: #1e293b;
    padding: 3px;
    border-radius: 7px;
    gap: 3px;
  }

  .ctrl-label {
    font-size: 0.78rem;
    color: #cbd5e1;
    padding: 0 8px;
  }

  .layout-switcher button {
    background: transparent;
    border: none;
    color: #cbd5e1;
    padding: 5px 10px;
    border-radius: 5px;
    font-size: 0.8rem;
    font-weight: 600;
  }

  .layout-switcher button.active {
    background: #0284c7;
    color: #ffffff;
  }

  .sync-toggle {
    font-size: 0.82rem;
    display: flex;
    align-items: center;
    gap: 5px;
    cursor: pointer;
    color: #e2e8f0;
  }

  .btn-add-panel {
    background: #16a34a;
    color: #ffffff;
    border: none;
    padding: 7px 14px;
    border-radius: 6px;
    font-weight: 600;
    font-size: 0.84rem;
  }
  .btn-add-panel:hover {
    background: #15803d;
  }

  .main-content {
    padding: 8px 12px 16px 12px;
    max-width: 1850px;
    width: 100%;
    margin: 0 auto;
  }

  .panels-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .panels-grid.two-col {
    grid-template-columns: repeat(auto-fit, minmax(560px, 1fr));
  }

  .panel-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 8px 10px;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05);
  }

  .panel-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
    padding-bottom: 6px;
    border-bottom: 1px solid #e2e8f0;
    flex-wrap: wrap;
  }

  .panel-title-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    min-width: 0;
  }

  .panel-summary-pill {
    font-size: 0.76rem;
    color: #334155;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    padding: 2px 8px;
    border-radius: 999px;
    white-space: nowrap;
  }

  .controls-drawer {
    margin-bottom: 8px;
    padding-bottom: 8px;
    border-bottom: 1px dashed #cbd5e1;
  }

  .controls-subbar {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 6px;
  }

  .btn-run-mini {
    background: #0284c7 !important;
    color: #ffffff !important;
    border-color: #0284c7 !important;
  }

  .panel-title-input {
    font-size: 0.94rem;
    font-weight: 700;
    border: 1px solid transparent;
    padding: 2px 6px;
    border-radius: 5px;
    color: #0f172a;
    min-width: 170px;
  }
  .panel-title-input:hover,
  .panel-title-input:focus {
    border-color: #cbd5e1;
    background: #f8fafc;
  }

  .panel-header-btns {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .preset-select {
    padding: 4px 8px;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    font-size: 0.82rem;
    background: #f8fafc;
  }

  .btn-sm {
    padding: 4px 10px;
    font-size: 0.8rem;
    border: 1px solid #cbd5e1;
    background: #ffffff;
    border-radius: 5px;
    color: #334155;
    font-weight: 600;
  }
  .btn-sm:hover {
    background: #f1f5f9;
  }

  .btn-danger {
    color: #dc2626;
    border-color: #fecaca;
  }
  .btn-danger:hover {
    background: #fef2f2;
  }

  .quick-spec-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    padding: 6px 10px;
    border-radius: 7px;
  }

  .quick-spec-label {
    font-size: 0.78rem;
    font-weight: 700;
    color: #1e40af;
    white-space: nowrap;
  }

  .quick-spec-input {
    flex: 1;
    min-width: 240px;
    padding: 4px 8px;
    font-size: 0.82rem;
    font-family: monospace;
    border: 1px solid #93c5fd;
    border-radius: 5px;
    background: #ffffff;
    color: #0f172a;
  }

  .quick-spec-input:focus {
    outline: 2px solid #3b82f6;
    outline-offset: 1px;
  }

  .btn-apply-spec {
    background: #2563eb;
    color: #ffffff;
    border-color: #2563eb;
    font-weight: 600;
  }

  .btn-apply-spec:hover:not(:disabled) {
    background: #1d4ed8;
  }

  .btn-apply-spec:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .param-row {
    display: flex;
    align-items: flex-end;
    gap: 12px;
    flex-wrap: wrap;
    background: #f8fafc;
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid #e2e8f0;
  }

  .field-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .field-group label,
  .q-header {
    font-size: 0.76rem;
    font-weight: 600;
    color: #475569;
  }

  .q-vector-group {
    flex: 1;
    min-width: 210px;
  }

  .q-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .btn-link {
    background: none;
    border: none;
    color: #0284c7;
    font-size: 0.75rem;
    text-decoration: underline;
    padding: 0;
  }

  .q-inputs {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .q-unused {
    font-family: monospace;
    font-weight: 700;
    color: #64748b;
  }

  .q-item {
    display: flex;
    flex-direction: column;
  }

  .q-item small {
    font-size: 0.68rem;
    color: #64748b;
  }

  .input-num {
    padding: 5px 8px;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    font-size: 0.88rem;
  }
  .input-num.short {
    width: 72px;
  }
  .input-num.q-input {
    width: 68px;
  }
  .input-num.medium {
    width: 110px;
  }

  .btn-compute {
    background: #0284c7;
    color: #ffffff;
    border: none;
    padding: 7px 16px;
    border-radius: 6px;
    font-weight: 700;
    font-size: 0.86rem;
  }
  .btn-compute:hover:not(:disabled) {
    background: #0369a1;
  }
  .btn-compute:disabled {
    opacity: 0.6;
  }

  .warning-banner {
    margin-top: 8px;
    padding: 6px 12px;
    background: #fffbeb;
    border: 1px solid #fde68a;
    color: #92400e;
    border-radius: 6px;
    font-size: 0.8rem;
  }

  .error-banner {
    margin-top: 8px;
    padding: 6px 12px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #b91c1c;
    border-radius: 6px;
    font-size: 0.82rem;
  }

  .visual-controls-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    flex-wrap: wrap;
    margin-top: 10px;
    padding: 8px 12px;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
  }

  .slider-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.8rem;
  }

  .direct-inspect {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .backend-export-group {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .export-label {
    font-size: 0.76rem;
    color: #64748b;
    font-weight: 600;
  }

  .loops-section {
    margin-top: 10px;
    padding: 8px 12px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
  }

  .loops-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.8rem;
    margin-bottom: 8px;
    flex-wrap: wrap;
    gap: 6px;
  }

  .loops-header small {
    color: #64748b;
  }

  .loops-bulk-btns {
    display: flex;
    gap: 6px;
  }

  .btn-xs {
    padding: 2px 8px;
    font-size: 0.74rem;
    border: 1px solid #cbd5e1;
    background: #ffffff;
    border-radius: 4px;
  }

  .loops-chip-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .loop-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 9px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    font-size: 0.78rem;
  }

  .loop-chip.dimmed {
    opacity: 0.45;
    background: #f1f5f9;
  }

  .color-picker {
    width: 22px;
    height: 22px;
    border: none;
    padding: 0;
    background: transparent;
    cursor: pointer;
  }

  .loop-chip-label {
    font-family: monospace;
    font-weight: 600;
  }

  .loop-chip-count {
    color: #64748b;
    font-size: 0.73rem;
  }

  .loop-ctx-hint {
    display: inline-block;
    margin-left: 8px;
    font-size: 0.75rem;
    color: #0369a1;
    background: #e0f2fe;
    padding: 2px 8px;
    border-radius: 999px;
    font-weight: 600;
  }

  .loop-chip {
    cursor: context-menu;
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .loop-chip:hover {
    border-color: #0284c7;
    box-shadow: 0 1px 4px rgba(2, 132, 199, 0.15);
  }

  .btn-tree-icon {
    border: 1px solid #bae6fd;
    background: #f0f9ff;
    border-radius: 4px;
    padding: 1px 5px;
    font-size: 0.78rem;
    line-height: 1.2;
    cursor: pointer;
    margin-left: 2px;
  }
  .btn-tree-icon:hover {
    background: #bae6fd;
  }

  .loop-context-menu {
    position: fixed;
    z-index: 2000;
    min-width: 280px;
    max-width: 340px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    box-shadow: 0 12px 28px rgba(15, 23, 42, 0.22);
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .ctx-menu-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    border-bottom: 1px solid #e2e8f0;
    font-size: 0.8rem;
    color: #0f172a;
    margin-bottom: 2px;
  }

  .ctx-color-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .ctx-loop-selector {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px;
    font-size: 0.75rem;
    color: #475569;
  }
  .ctx-loop-selector select {
    flex: 1;
    font-size: 0.75rem;
    padding: 2px 4px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
  }

  .ctx-menu-item {
    text-align: left;
    background: transparent;
    border: none;
    padding: 7px 10px;
    border-radius: 5px;
    font-size: 0.8rem;
    color: #1e293b;
    cursor: pointer;
    font-weight: 500;
  }
  .ctx-menu-item:hover {
    background: #f1f5f9;
  }
  .ctx-menu-item.primary {
    font-weight: 700;
    color: #0369a1;
    background: #f0f9ff;
  }
  .ctx-menu-item.primary:hover {
    background: #e0f2fe;
  }

  .plot-container {
    margin-top: 12px;
  }

  .overlay-section {
    margin-top: 18px;
    background: #ffffff;
    border: 2px solid #0284c7;
    border-radius: 10px;
    padding: 14px 16px;
    box-shadow: 0 4px 14px rgba(2, 132, 199, 0.1);
  }

  .overlay-header h3 {
    margin: 0 0 10px 0;
    font-size: 0.98rem;
    color: #0369a1;
  }

  .view-tabs {
    display: flex;
    gap: 4px;
    background: #0f172a;
    padding: 4px;
    border-radius: 8px;
    border: 1px solid #334155;
  }

  .view-tabs button {
    background: transparent;
    color: #cbd5e1;
    border: none;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .view-tabs button:hover {
    color: #ffffff;
    background: rgba(255, 255, 255, 0.08);
  }

  .view-tabs button.active {
    background: #0284c7;
    color: #ffffff;
  }

  .btn-active {
    background: #e0f2fe !important;
    border-color: #0284c7 !important;
    color: #0369a1 !important;
  }

  .advanced-drawer {
    margin-top: 10px;
    padding: 12px 14px;
    background: #f8fafc;
    border: 1px dashed #cbd5e1;
    border-radius: 8px;
  }

  .advanced-range-row {
    margin-bottom: 10px;
  }

  .ctree-launcher-card h3 {
    margin: 0 0 6px 0;
    font-size: 1.05rem;
    color: #0f172a;
  }

  .ctree-panel-group {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid #e2e8f0;
  }

  .ctree-panel-title {
    margin-bottom: 8px;
    font-size: 0.92rem;
    color: #1e293b;
  }

  .ctree-launch-chip {
    cursor: pointer;
    border: 1px solid #cbd5e1;
    background: #f8fafc;
    font-family: inherit;
  }

  .ctree-launch-chip:hover {
    border-color: #0284c7;
    background: #f0f9ff;
  }
</style>

