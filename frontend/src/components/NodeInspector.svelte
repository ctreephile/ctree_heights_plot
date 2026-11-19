<script>
  import { createEventDispatcher } from 'svelte';

  export let details = null;
  export let loading = false;
  export let p = 3;
  export let q = [null, 5];
  export let loopColors = {};

  const dispatch = createEventDispatcher();

  let activeTab = 'neighbors'; // 'neighbors' | 'same_height' | 'orbit'
  let filterSameLoopOnly = false;
  let searchN = '';

  $: target = details?.target || null;
  $: neighbors = details?.algorithmic_neighbors || null;
  $: sameHeight = details?.same_height || null;

  $: filteredSameHeightNodes = (sameHeight?.nodes || []).filter((item) => {
    if (filterSameLoopOnly && !item.same_loop) return false;
    if (searchN.trim() !== '' && !String(item.n).includes(searchN.trim())) return false;
    return true;
  });

  function inspectNumber(n) {
    dispatch('inspectNode', { n });
  }

  function focusOnGraph(n, steps) {
    dispatch('focusNode', { n, steps });
  }

  function closeInspector() {
    dispatch('close');
  }

  function getLoopColor(loopId) {
    return loopColors?.[loopId] || '#0284c7';
  }
</script>

{#if loading || details}
  <div class="inspector-panel">
    <div class="inspector-header">
      <div class="header-title">
        {#if loading}
          <span>ノード詳細を計算中...</span>
        {:else if target}
          <span class="badge-node">選択ノード n = {target.n.toLocaleString()}</span>
          <span class="badge-height">高さ (iterN) = {target.steps}</span>
          <span
            class="badge-loop"
            style="background-color: {getLoopColor(target.loop_id)}22; border-color: {getLoopColor(target.loop_id)}; color: {getLoopColor(target.loop_id)}"
          >
            {target.loop_label || `Loop ID ${target.loop_id}`}
          </span>
          <span class="badge-rule">式: {target.rule} (r = {target.r})</span>
        {/if}
      </div>
      <button class="btn-close" on:click={closeInspector} title="閉じる">✕ 閉じる</button>
    </div>

    {#if !loading && target && neighbors}
      <!-- Visual CTree summary banner -->
      <div class="ctree-banner">
        <div class="ctree-box forward-box">
          <div class="ctree-label">【前】1ステップ先 T(n) (ループ方向・高さ {Math.max(0, target.steps - 1)})</div>
          {#if neighbors.immediate_forward}
            <div class="ctree-nodes">
              <button
                class="node-pill forward-pill"
                on:click={() => inspectNumber(neighbors.immediate_forward.n)}
                title="クリックして {neighbors.immediate_forward.n} を検査"
              >
                <strong>{neighbors.immediate_forward.n}</strong>
                <small>({target.rule})</small>
              </button>
            </div>
          {:else}
            <div class="ctree-empty">なし（自身がループ内要素）</div>
          {/if}
        </div>

        <div class="ctree-arrow">⟵ T<sub>{p},Q</sub> ⟵</div>

        <div class="ctree-box current-box">
          <div class="ctree-label">【現在選択】n (高さ {target.steps})</div>
          <div class="ctree-current-val">{target.n}</div>
        </div>

        <div class="ctree-arrow">⟵ T<sub>{p},Q</sub> ⟵</div>

        <div class="ctree-box backward-box">
          <div class="ctree-label">
            【後】1ステップ後 T<sup>-1</sup>(n) (逆像・高さ {target.steps + 1}) [{neighbors.predecessors_step1.length}個]
          </div>
          {#if neighbors.predecessors_step1.length > 0}
            <div class="ctree-nodes">
              {#each neighbors.predecessors_step1 as pred}
                <button
                  class="node-pill backward-pill"
                  on:click={() => inspectNumber(pred.n)}
                  title="クリックして {pred.n} を検査"
                >
                  <strong>{pred.n}</strong>
                  <small>[r={pred.r}: {pred.formula}]</small>
                </button>
              {/each}
            </div>
          {:else}
            <div class="ctree-empty">逆像なし</div>
          {/if}
        </div>
      </div>

      <!-- Tabs -->
      <div class="inspector-tabs">
        <button
          class:active={activeTab === 'neighbors'}
          on:click={() => (activeTab = 'neighbors')}
        >
          アルゴリズム上の前後の数値 (前: {neighbors.immediate_forward ? 1 : 0} / 後1段: {neighbors.predecessors_step1.length} / 後2段: {neighbors.predecessors_step2.length})
        </button>
        <button
          class:active={activeTab === 'same_height'}
          on:click={() => (activeTab = 'same_height')}
        >
          同じ高さ (iterN = {target.steps}) の数値一覧 ({sameHeight?.total_count_in_range || 0}個)
        </button>
        <button
          class:active={activeTab === 'orbit'}
          on:click={() => (activeTab = 'orbit')}
        >
          ループまでの全順方向軌道 ({neighbors.forward_orbit.length}ステップ)
        </button>
      </div>

      <div class="inspector-body">
        {#if activeTab === 'neighbors'}
          <div class="tables-grid">
            <!-- Predecessors ("後") table -->
            <div class="table-section">
              <h4>
                【後の数値】逆像 T<sup>-1</sup>({target.n}), T<sup>-2</sup>({target.n})
                <small>（アルゴリズムで {target.n} に到達する直前・2つ前の数値）</small>
              </h4>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>前後区分</th>
                      <th>数値 m</th>
                      <th>余り r</th>
                      <th>変換式 T(m)</th>
                      <th>高さ (iterN)</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each neighbors.predecessors_step1 as p1}
                      <tr class="row-step1">
                        <td><span class="step-tag tag-after1">1つ後 (+1)</span></td>
                        <td class="num-cell">{p1.n.toLocaleString()}</td>
                        <td>r = {p1.r}</td>
                        <td class="mono">{p1.formula}</td>
                        <td>{p1.steps} {p1.is_loop_member ? '(ループ内)' : ''}</td>
                        <td class="actions-cell">
                          <button class="btn-mini" on:click={() => inspectNumber(p1.n)}>検査</button>
                          <button class="btn-mini" on:click={() => focusOnGraph(p1.n, p1.steps)}>図で表示</button>
                        </td>
                      </tr>
                    {/each}
                    {#each neighbors.predecessors_step2 as p2}
                      <tr class="row-step2">
                        <td><span class="step-tag tag-after2">2つ後 (+2, {p2.via_n}経由)</span></td>
                        <td class="num-cell">{p2.n.toLocaleString()}</td>
                        <td>r = {p2.r}</td>
                        <td class="mono">{p2.formula} → {target.n}</td>
                        <td>{p2.steps} {p2.is_loop_member ? '(ループ内)' : ''}</td>
                        <td class="actions-cell">
                          <button class="btn-mini" on:click={() => inspectNumber(p2.n)}>検査</button>
                          <button class="btn-mini" on:click={() => focusOnGraph(p2.n, p2.steps)}>図で表示</button>
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            </div>

            <!-- Forward ("前") table -->
            <div class="table-section">
              <h4>
                【前の数値】順方向 T({target.n}), T<sup>2</sup>({target.n}), ...
                <small>（{target.n} からループへ向かう側の数値）</small>
              </h4>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>前後区分</th>
                      <th>数値 m</th>
                      <th>余り r</th>
                      <th>次の変換式</th>
                      <th>高さ (iterN)</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each neighbors.forward_orbit.slice(1, 15) as fwd}
                      <tr>
                        <td><span class="step-tag tag-before">{fwd.offset}つ前 (-{fwd.offset})</span></td>
                        <td class="num-cell">{fwd.n.toLocaleString()}</td>
                        <td>r = {fwd.r}</td>
                        <td class="mono">{fwd.rule}</td>
                        <td>{fwd.steps} {fwd.is_loop_member ? '(ループ要素)' : ''}</td>
                        <td class="actions-cell">
                          <button class="btn-mini" on:click={() => inspectNumber(fwd.n)}>検査</button>
                          <button class="btn-mini" on:click={() => focusOnGraph(fwd.n, fwd.steps)}>図で表示</button>
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        {:else if activeTab === 'same_height'}
          <div class="filter-bar">
            <label>
              <input type="checkbox" bind:checked={filterSameLoopOnly} />
              同じループ（Loop #{target.loop_rank}）に属する数値のみ表示
            </label>
            <input
              type="text"
              placeholder="数値 n で絞り込み..."
              bind:value={searchN}
              class="search-input"
            />
            <span class="filter-count">
              表示中: {filteredSameHeightNodes.length} / 範囲内合計: {sameHeight.total_count_in_range} 個
            </span>
          </div>
          <div class="table-scroll wide-scroll">
            <table>
              <thead>
                <tr>
                  <th>数値 n</th>
                  <th>高さ (iterN)</th>
                  <th>選択ノードとの差 (n - {target.n})</th>
                  <th>余り r</th>
                  <th>1つ前の数値 T(n)</th>
                  <th>所属ループ</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {#each filteredSameHeightNodes as node}
                  <tr class:highlight-row={node.n === target.n}>
                    <td class="num-cell">
                      {node.n.toLocaleString()}
                      {#if node.n === target.n}
                        <span class="current-marker">★選択中</span>
                      {/if}
                    </td>
                    <td>{node.steps}</td>
                    <td class="mono">{node.diff_from_target >= 0 ? `+${node.diff_from_target}` : node.diff_from_target}</td>
                    <td>r = {node.r}</td>
                    <td class="mono">{node.next_n.toLocaleString()}</td>
                    <td>
                      <span
                        class="loop-dot"
                        style="background-color: {getLoopColor(node.loop_id)}"
                      ></span>
                      Loop #{node.loop_rank}
                    </td>
                    <td class="actions-cell">
                      <button class="btn-mini" on:click={() => inspectNumber(node.n)}>検査</button>
                      <button class="btn-mini" on:click={() => focusOnGraph(node.n, node.steps)}>図で表示</button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {:else if activeTab === 'orbit'}
          <div class="table-scroll wide-scroll">
            <table>
              <thead>
                <tr>
                  <th>ステップ経過</th>
                  <th>数値 m</th>
                  <th>余り r = m mod (p-1)</th>
                  <th>適用変換 T(m)</th>
                  <th>残りステップ数 (高さ)</th>
                  <th>状態</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {#each neighbors.forward_orbit as step}
                  <tr class:highlight-row={step.offset === 0}>
                    <td>{step.offset === 0 ? '0 (初期選択)' : `-${step.offset} ステップ`}</td>
                    <td class="num-cell">{step.n.toLocaleString()}</td>
                    <td>r = {step.r}</td>
                    <td class="mono">{step.rule}</td>
                    <td>{step.steps}</td>
                    <td>
                      {#if step.is_loop_member}
                        <span class="step-tag tag-loop">ループ内要素</span>
                      {:else}
                        軌道上
                      {/if}
                    </td>
                    <td class="actions-cell">
                      <button class="btn-mini" on:click={() => inspectNumber(step.n)}>検査</button>
                      <button class="btn-mini" on:click={() => focusOnGraph(step.n, step.steps)}>図で表示</button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .inspector-panel {
    background: var(--bg-card);
    border: 2px solid #0284c7;
    border-radius: 10px;
    margin-top: 14px;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
    overflow: hidden;
  }

  .inspector-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #f0f9ff;
    padding: 10px 16px;
    border-bottom: 1px solid #bae6fd;
    flex-wrap: wrap;
    gap: 8px;
  }

  .header-title {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
  }

  .badge-node {
    font-weight: 700;
    font-size: 1.05rem;
    color: #0f172a;
  }

  .badge-height {
    background: #0284c7;
    color: white;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.85rem;
    font-weight: 600;
  }

  .badge-loop {
    border: 1.5px solid;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.82rem;
    font-weight: 600;
  }

  .badge-rule {
    font-family: monospace;
    font-size: 0.9rem;
    background: #e2e8f0;
    padding: 3px 8px;
    border-radius: 6px;
  }

  .btn-close {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 0.85rem;
    color: #334155;
  }
  .btn-close:hover {
    background: #fee2e2;
    border-color: #fca5a5;
    color: #b91c1c;
  }

  .ctree-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 12px 16px;
    background: #f8fafc;
    border-bottom: 1px solid var(--border-color);
    flex-wrap: wrap;
  }

  .ctree-box {
    flex: 1;
    min-width: 200px;
    padding: 8px 12px;
    border-radius: 8px;
    border: 1px solid #cbd5e1;
    background: #ffffff;
  }

  .forward-box {
    border-left: 4px solid #16a34a;
  }

  .current-box {
    flex: 0 0 auto;
    min-width: 140px;
    text-align: center;
    border: 2px solid #0284c7;
    background: #f0f9ff;
  }

  .backward-box {
    border-left: 4px solid #d97706;
  }

  .ctree-label {
    font-size: 0.76rem;
    color: var(--text-muted);
    margin-bottom: 6px;
    font-weight: 600;
  }

  .ctree-current-val {
    font-size: 1.35rem;
    font-weight: 800;
    color: #0369a1;
  }

  .ctree-arrow {
    font-weight: 700;
    color: #64748b;
    font-size: 0.9rem;
  }

  .ctree-nodes {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .node-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 6px;
    border: 1px solid;
    font-size: 0.85rem;
    background: #fff;
  }

  .forward-pill {
    border-color: #86efac;
    background: #f0fdf4;
    color: #166534;
  }
  .forward-pill:hover {
    background: #dcfce7;
  }

  .backward-pill {
    border-color: #fcd34d;
    background: #fffbeb;
    color: #92400e;
  }
  .backward-pill:hover {
    background: #fef3c7;
  }

  .inspector-tabs {
    display: flex;
    border-bottom: 1px solid var(--border-color);
    background: #f1f5f9;
    padding: 0 12px;
    gap: 4px;
  }

  .inspector-tabs button {
    border: none;
    background: transparent;
    padding: 10px 16px;
    font-size: 0.88rem;
    font-weight: 600;
    color: #475569;
    border-bottom: 3px solid transparent;
  }

  .inspector-tabs button.active {
    color: #0284c7;
    border-bottom-color: #0284c7;
    background: #ffffff;
  }

  .inspector-body {
    padding: 12px 16px;
  }

  .tables-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }

  @media (max-width: 1000px) {
    .tables-grid {
      grid-template-columns: 1fr;
    }
  }

  .table-section h4 {
    margin: 0 0 8px 0;
    font-size: 0.92rem;
    color: #1e293b;
  }

  .table-section h4 small {
    font-weight: normal;
    color: #64748b;
  }

  .table-scroll {
    max-height: 280px;
    overflow-y: auto;
    border: 1px solid var(--border-color);
    border-radius: 6px;
  }

  .wide-scroll {
    max-height: 320px;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.84rem;
  }

  th, td {
    padding: 6px 10px;
    text-align: left;
    border-bottom: 1px solid #e2e8f0;
  }

  th {
    position: sticky;
    top: 0;
    background: #f8fafc;
    font-weight: 600;
    color: #334155;
    z-index: 1;
  }

  .num-cell {
    font-weight: 700;
    font-family: monospace;
    font-size: 0.92rem;
  }

  .mono {
    font-family: monospace;
  }

  .step-tag {
    display: inline-block;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
  }

  .tag-after1 {
    background: #fef3c7;
    color: #92400e;
  }

  .tag-after2 {
    background: #ffedd5;
    color: #9a3412;
  }

  .tag-before {
    background: #dcfce7;
    color: #166534;
  }

  .tag-loop {
    background: #dbeafe;
    color: #1e40af;
  }

  .btn-mini {
    padding: 2px 7px;
    font-size: 0.76rem;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background: #ffffff;
    margin-right: 4px;
  }
  .btn-mini:hover {
    background: #0284c7;
    color: #ffffff;
    border-color: #0284c7;
  }

  .filter-bar {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 10px;
    flex-wrap: wrap;
    font-size: 0.86rem;
  }

  .search-input {
    padding: 4px 10px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    font-size: 0.85rem;
  }

  .filter-count {
    color: var(--text-muted);
    margin-left: auto;
  }

  .highlight-row {
    background: #f0f9ff;
  }

  .current-marker {
    color: #0284c7;
    font-size: 0.75rem;
    margin-left: 4px;
  }

  .loop-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 4px;
    vertical-align: middle;
  }
</style>

