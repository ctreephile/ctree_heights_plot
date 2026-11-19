<script>
  import { onMount, onDestroy, createEventDispatcher } from "svelte";

  export let windowId = 1;
  export let p = 3;
  export let q = [null, 5];
  export let loopInfo = null; // { loop_id, rank, label, color, members }
  export let initialX = 80;
  export let initialY = 60;

  const dispatch = createEventDispatcher();

  // Floating window position & size
  let winX = initialX;
  let winY = initialY;
  let isMaximized = false;
  let draggingWindow = false;
  let dragWinOffset = { x: 0, y: 0 };

  // Tree query parameters (Default: height 10 from loop)
  let rootMode = "loop"; // 'loop' | 'single'
  let rootN = loopInfo?.members?.[0] || 1;
  let maxHeight = 10;

  // Visual style parameters
  let orientation = "BT"; // 'BT' (Root Bottom), 'TB' (Root Top), 'LR' (Root Left), 'RL' (Root Right)
  let nodeRadius = 6;
  let nodeColor = loopInfo?.color || "#0284c7";
  let loopNodeColor = "#dc2626";
  let branchColor = "#64748b";
  let branchWidth = 1.5;
  let treeOpacity = 0.95;

  let showLabels = true;
  let labelFontSize = 10;
  let labelColor = "#0f172a";

  // Spacing (narrow/dense vs spacious)
  let siblingSpacing = 34; // px between leaves
  let levelSpacing = 75; // px between depth levels

  // Background settings
  let bgTransparent = false;
  let bgColor = "#ffffff";
  let bgOpacity = 1.0;

  // Show/hide full loop elements drawer inside modal
  let showLoopElementsPanel = true;
  let showSpectrumPanel = true;

  // Tree structure compression mode:
  // 'full': all nodes
  // 'skeleton': contract intermediate r=0 (*d^k) straight-line conduit nodes, keeping only loop roots & r!=0 branch nodes
  // 'branch_points': contract degree-1 chains, keeping only loop roots, multi-branch nodes, and leaves
  let treeStructureMode = "full";
  let highlightNodeRoles = true; // highlight r!=0 branching nodes vs r=0 conduit nodes & sea-level (n <= maxQ)
  let colorBranchByQ = false; // color branching nodes individually by used q_r (r = 1..d-1)

  // Computed diagnostics for Height Spectrum N(h) & h=1 Rootlets & per-r q_r usage
  let heightSpectrum = []; // [{ h, total, branchNodes, belowSea }]
  let h1Rootlets = []; // nodes at h=1 with branch_r != 0
  let rUsageCounts = []; // [{ r, qVal, count, color }]
  let seaLevelQ = 1;

  // Snow Crystal Growth Mode (Dark-Field Microscopy)
  let crystalMode = false;
  let crystalData = null;
  let crystalGen = 0;
  let crystalMaxGen = 5;
  let crystalMultiplier = p === 4 ? 2 : p;
  let crystalPlaying = false;
  let crystalPlayTimer = null;
  let crystalGifLoading = false;
  let prevBgBeforeCrystal = null;

  // Fetched tree data
  let loading = false;
  let error = null;
  let treeData = null;

  // Interactive SVG Pan & Zoom state
  let svgElement;
  let viewportWidth = 960;
  let viewportHeight = 520;
  let zoomScale = 1.0;
  let panX = 40;
  let panY = 40;
  let isPanning = false;
  let panStart = { x: 0, y: 0, panX: 0, panY: 0 };

  let hoveredNode = null;
  let showTreeOptions = false;

  // Computed layout nodes & links
  let layoutNodes = [];
  let layoutLinks = [];
  let loopSpineLinks = [];
  let treeBounds = { minX: 0, maxX: 800, minY: 0, maxY: 500 };

  async function fetchLoopTree() {
    loading = true;
    error = null;
    try {
      const res = await fetch("/api/loop-tree", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          p: Number(p),
          q: q.map((x, idx) => (idx === 0 ? null : Number(x))),
          loop_id: loopInfo?.loop_id ?? null,
          root_n: rootMode === "single" ? Number(rootN) : null,
          root_mode: rootMode,
          max_height: Number(maxHeight),
          max_nodes: 15000,
        }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP Error ${res.status}`);
      }
      treeData = await res.json();
      if (crystalMode) {
        await fetchCrystalGrowth(false);
      } else {
        recomputeLayout(true);
      }
    } catch (err) {
      error = err.message;
    } finally {
      loading = false;
    }
  }

  async function fetchCrystalGrowth(autoFit = true) {
    loading = true;
    error = null;
    try {
      const res = await fetch("/api/crystal-growth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          p: Number(p),
          q: q.map((x, idx) => (idx === 0 ? null : Number(x))),
          loop_id: loopInfo?.loop_id ?? null,
          root_n: rootMode === "single" ? Number(rootN) : null,
          root_mode: rootMode,
          max_height: Math.min(Number(maxHeight), 12),
          max_gen: Number(crystalMaxGen),
          base_multiplier: Number(crystalMultiplier),
        }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP Error ${res.status}`);
      }
      crystalData = await res.json();
      if (crystalGen > crystalData.max_gen) {
        crystalGen = crystalData.max_gen;
      }
      applyCrystalGeneration(crystalGen, autoFit);
    } catch (err) {
      error = err.message;
    } finally {
      loading = false;
    }
  }

  function applyCrystalGeneration(genIdx, autoFit = false) {
    if (!crystalData?.generations?.length) return;
    const gObj =
      crystalData.generations[
        Math.min(genIdx, crystalData.generations.length - 1)
      ];
    if (!gObj) return;
    crystalGen = gObj.generation;
    treeData = {
      ...treeData,
      p: crystalData.p,
      q: gObj.q,
      total_nodes: gObj.total_nodes,
      loop: gObj.loop,
      tree: gObj.tree,
      frozen_height: gObj.frozen_height,
      counts_by_state: gObj.counts_by_state,
      multiplier: gObj.multiplier,
    };
    recomputeLayout(autoFit);
  }

  async function toggleCrystalMode() {
    stopCrystalPlay();
    if (crystalMode) {
      prevBgBeforeCrystal = {
        bgColor,
        bgTransparent,
        orientation,
        labelColor,
      };
      bgTransparent = false;
      bgColor = "#030712";
      labelColor = "#e2e8f0";
      orientation = "radial";
      crystalMultiplier = Number(p) === 4 ? 2 : Number(p);
      crystalGen = 0;
      await fetchCrystalGrowth(true);
    } else {
      if (prevBgBeforeCrystal) {
        bgColor = prevBgBeforeCrystal.bgColor;
        bgTransparent = prevBgBeforeCrystal.bgTransparent;
        orientation = prevBgBeforeCrystal.orientation;
        labelColor = prevBgBeforeCrystal.labelColor;
      } else {
        bgColor = "#ffffff";
        labelColor = "#0f172a";
        orientation = "BT";
      }
      await fetchLoopTree();
    }
  }

  function toggleCrystalPlay() {
    if (crystalPlaying) {
      stopCrystalPlay();
    } else {
      crystalPlaying = true;
      crystalPlayTimer = setInterval(() => {
        const maxG = crystalData?.max_gen ?? crystalMaxGen;
        const nextG = crystalGen >= maxG ? 0 : crystalGen + 1;
        applyCrystalGeneration(nextG, false);
      }, 950);
    }
  }

  function stopCrystalPlay() {
    crystalPlaying = false;
    if (crystalPlayTimer) {
      clearInterval(crystalPlayTimer);
      crystalPlayTimer = null;
    }
  }

  async function downloadCrystalGif() {
    crystalGifLoading = true;
    try {
      const res = await fetch("/api/crystal-growth-gif", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          p: Number(p),
          q: q.map((x, idx) => (idx === 0 ? null : Number(x))),
          loop_id: loopInfo?.loop_id ?? null,
          root_n: rootMode === "single" ? Number(rootN) : null,
          root_mode: rootMode,
          max_height: Math.min(Number(maxHeight), 11),
          max_gen: Number(crystalMaxGen),
          base_multiplier: Number(crystalMultiplier),
          layout_mode: orientation === "radial" ? "radial" : "tree",
          frame_duration_ms: 900,
          show_labels: Boolean(showLabels),
        }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP Error ${res.status}`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const qStr = q.slice(1).join("_");
      a.href = url;
      a.download = `CTree_Crystal_p${p}_Q${qStr}_x${crystalMultiplier}_h${maxHeight}.gif`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      error = err.message;
    } finally {
      crystalGifLoading = false;
    }
  }

  function applySpacingPreset(mode) {
    if (mode === "dense") {
      siblingSpacing = 16;
      levelSpacing = 42;
    } else if (mode === "normal") {
      siblingSpacing = 34;
      levelSpacing = 75;
    } else if (mode === "spacious") {
      siblingSpacing = 65;
      levelSpacing = 125;
    }
    recomputeLayout(false);
  }

  const Q_BRANCH_PALETTE = [
    "#ef4444", // r=1: Red
    "#f97316", // r=2: Orange
    "#ca8a04", // r=3: Amber
    "#16a34a", // r=4: Green
    "#0d9488", // r=5: Teal
    "#0284c7", // r=6: Sky Blue
    "#4f46e5", // r=7: Indigo
    "#9333ea", // r=8: Purple
    "#db2777", // r=9: Pink
    "#65a30d", // r=10: Lime
    "#0891b2", // r=11: Cyan
    "#be123c", // r=12: Rose
  ];

  function getQBranchColor(r) {
    const idx = Number(r) - 1;
    if (idx < 0) return "#94a3b8";
    if (idx < Q_BRANCH_PALETTE.length) return Q_BRANCH_PALETTE[idx];
    const hue = Math.round((idx * 137.508) % 360);
    return `hsl(${hue}, 72%, 44%)`;
  }

  /**
   * Build a transformed tree according to `treeStructureMode` ('full' | 'skeleton' | 'branch_points')
   * and compute whole-tree diagnostics (`heightSpectrum`, `h1Rootlets`, `rUsageCounts`, `seaLevelQ`).
   */
  function buildEffectiveTreeAndDiagnostics(rawRoot) {
    const validQs = (q || [])
      .slice(1)
      .map((v) => Math.abs(Number(v) || 0))
      .filter((v) => v > 0);
    seaLevelQ = validQs.length > 0 ? Math.max(...validQs) : 1;

    // 1. Collect full-tree diagnostics by height h and per-r q_r usage
    const d = Math.max(2, Number(p) - 1);
    const byH = new Map();
    const rootletsH1 = [];
    const rCountMap = new Map();
    for (let r = 1; r < d; r++) rCountMap.set(r, 0);

    function scanFull(node) {
      if (!node || node.is_virtual_hub) {
        for (const ch of node?.children || []) scanFull(ch);
        return;
      }
      const h = Number(node.height ?? 0);
      if (!byH.has(h)) {
        byH.set(h, { h, total: 0, branchNodes: 0, belowSea: 0 });
      }
      const entry = byH.get(h);
      entry.total += 1;
      if (node.r !== 0 && !node.is_loop) entry.branchNodes += 1;
      if (node.n <= seaLevelQ) entry.belowSea += 1;

      const br = Number(node.branch_r ?? 0);
      if (!node.is_loop && br > 0 && br < d) {
        rCountMap.set(br, (rCountMap.get(br) || 0) + 1);
      }

      if (h === 1 && node.branch_r !== 0 && !node.is_loop) {
        rootletsH1.push({
          n: node.n,
          r: node.r,
          branch_r: node.branch_r,
          formula: node.formula,
        });
      }
      for (const ch of node.children || []) scanFull(ch);
    }
    scanFull(rawRoot);

    heightSpectrum = Array.from(byH.values()).sort((a, b) => a.h - b.h);
    h1Rootlets = rootletsH1.sort((a, b) => a.n - b.n);
    rUsageCounts = Array.from(rCountMap.entries()).map(([r, count]) => ({
      r,
      qVal: q?.[r],
      count,
      color: getQBranchColor(r),
    }));

    // 2. Transform tree structure if skeleton mode is active
    if (treeStructureMode === "full") {
      function cloneFull(nd) {
        return {
          ...nd,
          contracted_steps: 1,
          children: (nd.children || []).map(cloneFull),
        };
      }
      return cloneFull(rawRoot);
    }

    if (treeStructureMode === "skeleton") {
      // Keep virtual hub, loop roots (h=0), and non-trivial branch nodes (r !== 0 / branch_r !== 0).
      // Contract all intermediate r === 0 (*d^k) straight conduit nodes!
      function extractSkeletonDescendants(node, stepsSoFar) {
        const results = [];
        for (const ch of node.children || []) {
          const isKeep = ch.is_loop || ch.r !== 0 || ch.branch_r !== 0;
          if (isKeep) {
            const skChild = {
              ...ch,
              contracted_steps: stepsSoFar + 1,
              children: extractSkeletonDescendants(ch, 0),
            };
            results.push(skChild);
          } else {
            // ch is an r=0 (*d) conduit node: pass through it and accumulate steps
            const deeper = extractSkeletonDescendants(ch, stepsSoFar + 1);
            results.push(...deeper);
          }
        }
        return results;
      }

      if (rawRoot.is_virtual_hub) {
        // Keep all loop roots (or odd/non-divisible loop roots if user wants, keeping all loop roots preserves full loop spine)
        return {
          ...rawRoot,
          children: (rawRoot.children || []).map((lc) => ({
            ...lc,
            contracted_steps: 0,
            children: extractSkeletonDescendants(lc, 0),
          })),
        };
      } else {
        return {
          ...rawRoot,
          contracted_steps: 0,
          children: extractSkeletonDescendants(rawRoot, 0),
        };
      }
    }

    if (treeStructureMode === "branch_points") {
      // Contract degree-1 chains (nodes with exactly 1 child that are not loop roots)
      function compressChain(node, stepsAcc = 1) {
        const chs = node.children || [];
        if (!node.is_loop && !node.is_virtual_hub && chs.length === 1) {
          return compressChain(chs[0], stepsAcc + 1);
        }
        return {
          ...node,
          contracted_steps: stepsAcc,
          children: chs.map((c) => compressChain(c, 1)),
        };
      }
      return compressChain(rawRoot, 0);
    }

    return rawRoot;
  }

  /**
   * Compute tidy hierarchical layout for `treeData.tree` and map (breadth, depth)
   * into (x, y) according to `orientation` ('TB' | 'BT' | 'LR' | 'RL').
   */
  function recomputeLayout(autoFit = false) {
    if (!treeData?.tree) return;

    const root = buildEffectiveTreeAndDiagnostics(treeData.tree);
    let leafCursor = 0;

    // Post-order traversal to assign breadth coordinate `u` (in leaf units)
    // and depth coordinate `v` (0, 1, 2, ...)
    function assignCoordinates(node, depth) {
      const children = node.children || [];
      let u;
      if (children.length === 0) {
        u = leafCursor;
        leafCursor += 1;
      } else {
        const childUs = children.map((ch) => assignCoordinates(ch, depth + 1));
        u = (childUs[0] + childUs[childUs.length - 1]) / 2;
      }
      node._u = u;
      node._depth = depth;
      return u;
    }

    const isVirtualHub = Boolean(root.is_virtual_hub);
    if (isVirtualHub) {
      // Root's children are the loop elements at depth 0
      const loopChildren = root.children || [];
      for (const lc of loopChildren) {
        assignCoordinates(lc, 0);
        // Add a small extra gap between distinct loop elements' subtrees
        leafCursor += 0.35;
      }
    } else {
      assignCoordinates(root, 0);
    }

    const nodes = [];
    const links = [];
    const spine = [];
    const totalLeafSpan = Math.max(1, leafCursor);

    function mapUVToXY(u, depth) {
      if (orientation === "radial") {
        const angle = (2 * Math.PI * (u + 0.25)) / totalLeafSpan;
        const radius = (depth + 1) * levelSpacing * 0.78;
        return {
          x: radius * Math.cos(angle),
          y: radius * Math.sin(angle),
        };
      }
      const breadthPx = u * siblingSpacing;
      const depthPx = depth * levelSpacing;
      if (orientation === "TB") {
        return { x: breadthPx, y: depthPx };
      } else if (orientation === "BT") {
        return { x: breadthPx, y: -depthPx };
      } else if (orientation === "LR") {
        return { x: depthPx, y: breadthPx };
      } else {
        return { x: -depthPx, y: breadthPx };
      }
    }

    function collectNodesAndLinks(node) {
      const { x, y } = mapUVToXY(node._u, node._depth);
      const item = {
        n: node.n,
        height: node.height,
        depth: node._depth,
        r: node.r,
        branch_r: node.branch_r,
        formula: node.formula,
        is_loop: node.is_loop,
        crystal_state: node.crystal_state || null,
        contracted_steps: node.contracted_steps || 1,
        below_sea: node.n <= seaLevelQ,
        x,
        y,
      };
      nodes.push(item);

      for (const ch of node.children || []) {
        const chItem = collectNodesAndLinks(ch);
        links.push({
          source: item,
          target: chItem,
          branch_r: ch.branch_r,
          crystal_state: ch.crystal_state || null,
          contracted_steps: ch.contracted_steps || 1,
        });
      }
      return item;
    }

    if (isVirtualHub) {
      const loopRootItems = [];
      for (const lc of root.children || []) {
        const item = collectNodesAndLinks(lc);
        loopRootItems.push(item);
      }
      // Connect adjacent loop elements at depth 0 with a dashed spine
      for (let i = 0; i < loopRootItems.length - 1; i++) {
        spine.push({
          source: loopRootItems[i],
          target: loopRootItems[i + 1],
        });
      }
      if (orientation === "radial" && loopRootItems.length > 2) {
        spine.push({
          source: loopRootItems[loopRootItems.length - 1],
          target: loopRootItems[0],
        });
      }
    } else {
      collectNodesAndLinks(root);
    }

    layoutNodes = nodes;
    layoutLinks = links;
    loopSpineLinks = spine;

    if (nodes.length > 0) {
      let minX = Infinity,
        maxX = -Infinity,
        minY = Infinity,
        maxY = -Infinity;
      for (const nd of nodes) {
        if (nd.x < minX) minX = nd.x;
        if (nd.x > maxX) maxX = nd.x;
        if (nd.y < minY) minY = nd.y;
        if (nd.y > maxY) maxY = nd.y;
      }
      const pad = 60;
      treeBounds = {
        minX: minX - pad,
        maxX: maxX + pad,
        minY: minY - pad,
        maxY: maxY + pad,
      };
      if (autoFit) {
        fitToView();
      }
    }
  }

  function fitToView() {
    const bw = Math.max(100, treeBounds.maxX - treeBounds.minX);
    const bh = Math.max(100, treeBounds.maxY - treeBounds.minY);
    const scaleX = (viewportWidth - 40) / bw;
    const scaleY = (viewportHeight - 40) / bh;
    zoomScale = Math.max(0.08, Math.min(2.5, Math.min(scaleX, scaleY)));
    panX = (viewportWidth - bw * zoomScale) / 2 - treeBounds.minX * zoomScale;
    panY = (viewportHeight - bh * zoomScale) / 2 - treeBounds.minY * zoomScale;
  }

  function zoomBy(factor, cx = viewportWidth / 2, cy = viewportHeight / 2) {
    const nextScale = Math.max(0.03, Math.min(12, zoomScale * factor));
    const ratio = nextScale / zoomScale;
    panX = cx - (cx - panX) * ratio;
    panY = cy - (cy - panY) * ratio;
    zoomScale = nextScale;
  }

  function handleSvgWheel(e) {
    e.preventDefault();
    const rect = svgElement.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.2 : 0.83;
    zoomBy(factor, mx, my);
  }

  function handleSvgMouseDown(e) {
    if (e.button !== 0) return;
    isPanning = true;
    panStart = { x: e.clientX, y: e.clientY, panX, panY };
  }

  function handleSvgMouseMove(e) {
    if (!isPanning) return;
    panX = panStart.panX + (e.clientX - panStart.x);
    panY = panStart.panY + (e.clientY - panStart.y);
  }

  function handleSvgMouseUp() {
    isPanning = false;
  }

  function linkPath(link) {
    const sx = link.source.x;
    const sy = link.source.y;
    const tx = link.target.x;
    const ty = link.target.y;
    if (orientation === "radial") {
      return `M ${sx} ${sy} L ${tx} ${ty}`;
    }
    if (orientation === "TB" || orientation === "BT") {
      const midY = (sy + ty) / 2;
      return `M ${sx} ${sy} C ${sx} ${midY}, ${tx} ${midY}, ${tx} ${ty}`;
    } else {
      const midX = (sx + tx) / 2;
      return `M ${sx} ${sy} C ${midX} ${sy}, ${midX} ${ty}, ${tx} ${ty}`;
    }
  }

  function labelOffset({ is_loop }) {
    const dist = Number(nodeRadius) + 5;
    if (orientation === "BT" || orientation === "radial")
      return { dx: 0, dy: -dist, anchor: "middle" };
    if (orientation === "TB")
      return { dx: 0, dy: dist + labelFontSize * 0.8, anchor: "middle" };
    if (orientation === "LR")
      return { dx: dist, dy: labelFontSize * 0.35, anchor: "start" };
    return { dx: -dist, dy: labelFontSize * 0.35, anchor: "end" };
  }

  function hexToRgba(hex, alpha) {
    const clean = hex.replace("#", "");
    const r = parseInt(clean.substring(0, 2), 16) || 255;
    const g = parseInt(clean.substring(2, 4), 16) || 255;
    const b = parseInt(clean.substring(4, 6), 16) || 255;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function getNodeFillColor(nd, useQColor = colorBranchByQ) {
    if (crystalMode && nd.crystal_state) {
      if (nd.crystal_state === "core") return "#ffffff";
      if (nd.crystal_state === "newborn") return "#fde047";
      if (nd.crystal_state === "frozen") return "#e0f2fe";
      return "#60a5fa";
    }
    if (nd.is_loop) return loopNodeColor;
    const effR = Number(nd.branch_r || nd.r || 0);
    if (useQColor && effR > 0) {
      return getQBranchColor(effR);
    }
    if (!highlightNodeRoles) return nodeColor;
    if (nd.r !== 0 || nd.branch_r !== 0) return "#dc2626"; // Non-trivial branching node (odd/non-divisible)
    if (nd.below_sea) return "#0284c7"; // Below sea-level (n <= maxQ)
    return "#94a3b8"; // *d conduit node (r === 0)
  }

  function getNodeRadiusPx(nd) {
    const base = Number(nodeRadius);
    if (crystalMode && nd.crystal_state) {
      if (nd.crystal_state === "core") return base * 1.4;
      if (nd.crystal_state === "newborn") return base * 1.25;
      if (nd.crystal_state === "frozen") return base * 1.05;
      return Math.max(3, base * 0.82);
    }
    if (nd.is_loop) return base * 1.3;
    if (highlightNodeRoles && (nd.r !== 0 || nd.branch_r !== 0))
      return base * 1.15;
    if (highlightNodeRoles && nd.r === 0 && treeStructureMode === "full")
      return Math.max(2.5, base * 0.78);
    return base;
  }

  function selectAsSingleRoot(nVal) {
    rootMode = "single";
    rootN = nVal;
    fetchLoopTree();
  }

  function switchToFullLoopRoot() {
    rootMode = "loop";
    fetchLoopTree();
  }

  /**
   * Build standalone SVG string for export (and PNG rasterization).
   */
  function buildStandaloneSvgString() {
    const bw = Math.max(200, Math.ceil(treeBounds.maxX - treeBounds.minX));
    const bh = Math.max(200, Math.ceil(treeBounds.maxY - treeBounds.minY));
    const vx = Math.floor(treeBounds.minX);
    const vy = Math.floor(treeBounds.minY);

    const parts = [];
    parts.push(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vx} ${vy} ${bw} ${bh}" width="${bw}" height="${bh}">`,
    );

    if (!bgTransparent && bgOpacity > 0) {
      parts.push(
        `<rect x="${vx}" y="${vy}" width="${bw}" height="${bh}" fill="${bgColor}" fill-opacity="${bgOpacity}"/>`,
      );
    }

    parts.push(`<g opacity="${treeOpacity}">`);

    // Loop spine links
    for (const sp of loopSpineLinks) {
      parts.push(
        `<line x1="${sp.source.x}" y1="${sp.source.y}" x2="${sp.target.x}" y2="${sp.target.y}" stroke="${loopNodeColor}" stroke-width="${branchWidth * 1.3}" stroke-dasharray="4,4" opacity="0.7"/>`,
      );
    }

    // Tree branch links
    parts.push(
      `<g fill="none" stroke="${branchColor}" stroke-width="${branchWidth}">`,
    );
    for (const lk of layoutLinks) {
      const dash = lk.branch_r === 0 ? "" : ' stroke-dasharray="3,2"';
      parts.push(`<path d="${linkPath(lk)}"${dash}/>`);
    }
    parts.push(`</g>`);

    // Nodes
    for (const nd of layoutNodes) {
      const fillCol = getNodeFillColor(nd);
      const r = getNodeRadiusPx(nd);
      parts.push(
        `<circle cx="${nd.x}" cy="${nd.y}" r="${r}" fill="${fillCol}" stroke="#ffffff" stroke-width="1"/>`,
      );
    }

    // Node number labels
    if (showLabels) {
      const off = labelOffset({});
      parts.push(
        `<g font-family="monospace, sans-serif" font-size="${labelFontSize}" fill="${labelColor}" text-anchor="${off.anchor}">`,
      );
      for (const nd of layoutNodes) {
        parts.push(
          `<text x="${nd.x + off.dx}" y="${nd.y + off.dy}">${nd.n}</text>`,
        );
      }
      parts.push(`</g>`);
    }

    parts.push(`</g></svg>`);
    return { svgString: parts.join("\n"), width: bw, height: bh };
  }

  function exportTreeSvg() {
    const { svgString } = buildStandaloneSvgString();
    const blob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const qStr = q.slice(1).join("_");
    a.href = url;
    a.download = `CTree_p${p}_Q${qStr}_loop${loopInfo?.rank || 1}_h${maxHeight}.svg`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportTreePng() {
    const { svgString, width, height } = buildStandaloneSvgString();
    const img = new Image();
    const blob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);

    img.onload = () => {
      // Scale to crisp resolution while keeping max dimension reasonable
      const scale = Math.min(
        2.0,
        Math.max(1.0, 2400 / Math.max(width, height)),
      );
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      const ctx = canvas.getContext("2d");
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);

      const pngUrl = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      const qStr = q.slice(1).join("_");
      a.href = pngUrl;
      a.download = `CTree_p${p}_Q${qStr}_loop${loopInfo?.rank || 1}_h${maxHeight}.png`;
      a.click();
    };
    img.src = url;
  }

  // Window dragging handlers
  function startWindowDrag(e) {
    if (isMaximized) return;
    if (
      e.target.closest("button") ||
      e.target.closest("input") ||
      e.target.closest("select")
    )
      return;
    draggingWindow = true;
    dragWinOffset = { x: e.clientX - winX, y: e.clientY - winY };
    window.addEventListener("mousemove", onWindowDragMove);
    window.addEventListener("mouseup", stopWindowDrag);
  }

  function onWindowDragMove(e) {
    if (!draggingWindow) return;
    winX = Math.max(10, e.clientX - dragWinOffset.x);
    winY = Math.max(10, e.clientY - dragWinOffset.y);
  }

  function stopWindowDrag() {
    draggingWindow = false;
    window.removeEventListener("mousemove", onWindowDragMove);
    window.removeEventListener("mouseup", stopWindowDrag);
  }

  onMount(() => {
    fetchLoopTree();
  });

  onDestroy(() => {
    stopCrystalPlay();
  });
</script>

<div
  class="floating-window"
  class:maximized={isMaximized}
  style={isMaximized ? "" : `left: ${winX}px; top: ${winY}px;`}
>
  <!-- Draggable Window Title Bar -->
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div class="window-header" on:mousedown={startWindowDrag}>
    <div class="win-title">
      <span class="win-dot" style="background: {nodeColor}"></span>
      <strong
        >CTree ビジュアライザ — (p={p}, Q=[_, {q.slice(1).join(", ")}])</strong
      >
      <span class="win-sub">
        {loopInfo?.label || `Loop ID ${loopInfo?.loop_id}`}
      </span>
      {#if treeData}
        <span class="node-count-badge">
          表示ノード総数: {treeData.total_nodes.toLocaleString()} 個
          {treeData.truncated ? "(上限到達)" : ""}
        </span>
      {/if}
    </div>

    <div class="win-actions">
      <button
        class="btn-win"
        on:click={() => (showSpectrumPanel = !showSpectrumPanel)}
        title="高さ別ノード数 N(h)・初段発根数・海面診断バーの表示/非表示"
      >
        {showSpectrumPanel
          ? "▲ スペクトル N(h) 隠す"
          : "📊 スペクトル N(h) 診断"}
      </button>
      <button
        class="btn-win"
        on:click={() => (showLoopElementsPanel = !showLoopElementsPanel)}
        title="ループ全要素リストの表示/非表示"
      >
        {showLoopElementsPanel ? "▲ ループ要素を隠す" : "▼ ループ全要素を表示"}
      </button>
      <button
        class="btn-win"
        on:click={() => {
          isMaximized = !isMaximized;
          setTimeout(() => fitToView(), 50);
        }}
      >
        {isMaximized ? "🗗 元のサイズ" : "🗖 最大化"}
      </button>
      <button
        class="btn-win btn-close"
        on:click={() => dispatch("close", { windowId })}
      >
        ✕ 閉じる
      </button>
    </div>
  </div>

  <!-- Section 1: All Elements of the Loop -->
  {#if showLoopElementsPanel && treeData?.loop}
    <div class="loop-elements-panel">
      <div class="loop-elements-header">
        <div>
          <strong
            >ループ構成要素（全 {treeData.loop.length} 要素、最小値 = {treeData
              .loop.min_value}）</strong
          >
          <small class="hint"
            >※ 要素をクリックすると、その数値を起点にした部分木（Single
            Root）に切り替えます</small
          >
        </div>
        <div class="loop-mode-btns">
          {#if rootMode === "single"}
            <button class="btn-xs primary" on:click={switchToFullLoopRoot}>
              ↺ ループ全体（全要素）起点に戻す
            </button>
          {/if}
        </div>
      </div>

      <div class="loop-elements-chain">
        {#each treeData.loop.elements_detail as el}
          <button
            class="loop-el-chip"
            class:selected-root={rootMode === "single" &&
              Number(rootN) === el.n}
            on:click={() => selectAsSingleRoot(el.n)}
            title="変換式: {el.rule} (クリックでこの数値を木の根に設定)"
          >
            <span class="el-idx">#{el.index + 1}</span>
            <strong class="el-val">{el.n}</strong>
            <small class="el-r">(r={el.r})</small>
          </button>
          <span class="chain-arrow">→</span>
        {/each}
        <span class="loop-back-badge">↺ {treeData.loop.members[0]} へ戻る</span>
      </div>
    </div>
  {/if}

  <!-- Section 1.5: Whole-Tree Diagnostics: Height Spectrum N(h) & First-Step Rootlets (h=1) -->
  {#if showSpectrumPanel && heightSpectrum.length > 0}
    <div class="spectrum-panel">
      <div class="spectrum-summary-row">
        <div class="diag-badge-group">
          <span class="diag-title">📊 CTree 構造診断:</span>
          {#if h1Rootlets.length > 0}
            <span
              class="diag-pill rootlet-ok"
              title="h=1 でループから直接外へ伸びる非自明分岐（低い自然数領域を獲得する初段根っこ）"
            >
              ★ 初段発根 (h=1): {h1Rootlets.length}本 ({h1Rootlets
                .map((rt) => `n=${rt.n}`)
                .join(", ")})
            </span>
          {:else}
            <span
              class="diag-pill rootlet-sealed"
              title="h=1 で非自明分岐が0本（×d で高高度へ持ち上がってから分岐するため吸引シェアが小さくなりやすい）"
            >
              × 初段封印 (h=1 非自明分岐: 0本)
            </span>
          {/if}
          <span
            class="diag-pill sea-pill"
            title="海面境界 n ≤ max(Q) のノード（これより下からは新しい非自明分岐が生まれない領域）"
          >
            🌊 海面境界 (n ≤ {seaLevelQ}): 計 {heightSpectrum.reduce(
              (a, b) => a + b.belowSea,
              0,
            )} ノード
          </span>
          <span class="diag-pill mode-pill">
            現在表示: {layoutNodes.length} / 全 {treeData?.total_nodes || 0} ノード
          </span>
        </div>
        <div
          class="spectrum-vector-text"
          title="高さ h=0..H ごとのノード数ベクトル N(h)"
        >
          <code>N(h) = [{heightSpectrum.map((s) => s.total).join(", ")}]</code>
        </div>
      </div>

      <div class="spectrum-bars-row">
        {#each heightSpectrum as sp}
          {@const maxTotal = Math.max(1, ...heightSpectrum.map((x) => x.total))}
          {@const barH = Math.max(4, Math.round((sp.total / maxTotal) * 28))}
          <div
            class="sp-col"
            title="高さ h={sp.h}: 計 {sp.total} 個 (うち分岐ノード r≠0: {sp.branchNodes} 個, 海面下 n≤{seaLevelQ}: {sp.belowSea} 個)"
          >
            <span class="sp-cnt">{sp.total}</span>
            <div class="sp-bar-wrap">
              <div
                class="sp-bar"
                style="height: {barH}px; background: {sp.h === 0
                  ? '#0f172a'
                  : sp.branchNodes > 0
                    ? '#dc2626'
                    : '#64748b'};"
              ></div>
            </div>
            <span class="sp-h">h={sp.h}</span>
          </div>
        {/each}
      </div>

      {#if rUsageCounts.length > 0}
        <div class="r-usage-row">
          <span
            class="r-usage-label"
            title="高さ h ≤ {maxHeight} の分岐ノードで各 q_r (r=1..{p - 2}) が使用された回数"
          >
            🌿 q別分岐回数 (h≤{maxHeight}):
          </span>
          <div class="r-usage-badges">
            {#each rUsageCounts as item}
              <span
                class="r-usage-pill"
                class:unused={item.count === 0}
                style="--q-col: {item.color};"
                title="r={item.r} (q_{item.r}={item.qVal}): {item.count}回"
              >
                <span class="r-dot" style="background: {item.color};"></span>
                r={item.r} (q={item.qVal}): <strong>{item.count}</strong>
              </span>
            {/each}
          </div>
          <code
            class="r-usage-dict"
            title="Python辞書形式: {'{'}r: 使用回数{'}'}"
          >
            {'{'}{rUsageCounts.map((it) => `${it.r}: ${it.count}`).join(", ")}{'}'}
          </code>
          <label
            class="chk-label r-color-toggle"
            title="各分岐ノードを、使用している q_r (r=1..{p - 2}) ごとの色で塗り分けます"
          >
            <input type="checkbox" bind:checked={colorBranchByQ} />
            🎨 q別に色分け
          </label>
        </div>
      {/if}
    </div>
  {/if}

  <!-- Compact Quick Bar (always visible) -->
  <div class="tree-compact-bar">
    <label>
      高さ(H):
      <input
        type="number"
        min="1"
        max="20"
        bind:value={maxHeight}
        on:change={() => fetchLoopTree()}
        class="num-input short"
      />
    </label>

    <label>
      向き:
      <select bind:value={orientation} on:change={() => recomputeLayout(true)}>
        <option value="BT">下→上</option>
        <option value="TB">上→下</option>
        <option value="LR">左→右</option>
        <option value="RL">右→左</option>
        <option value="radial">❄️ 放射状</option>
      </select>
    </label>

    <label class="chk-label">
      <input
        type="checkbox"
        bind:checked={crystalMode}
        on:change={toggleCrystalMode}
      />
      ❄️ 結晶成長
    </label>

    {#if crystalMode}
      <label class="gen-slider-label">
        k={crystalGen} (×{Math.pow(crystalMultiplier, crystalGen)}):
        <input
          type="range"
          min="0"
          max={crystalData?.max_gen ?? crystalMaxGen}
          step="1"
          bind:value={crystalGen}
          on:input={() => {
            stopCrystalPlay();
            applyCrystalGeneration(Number(crystalGen), false);
          }}
        />
      </label>
      <button class="btn-xs primary" on:click={toggleCrystalPlay}>
        {crystalPlaying ? "⏸" : "▶"}
      </button>
    {/if}

    <button
      type="button"
      class="btn-xs tree-opt-toggle"
      class:active={showTreeOptions}
      on:click={() => (showTreeOptions = !showTreeOptions)}
    >
      ⚙ 詳細設定 (ノード・色・書き出し) {showTreeOptions ? "▴" : "▾"}
    </button>
  </div>

  <!-- Section 2: Control Toolbar (Collapsible) -->
  {#if showTreeOptions}
    <div class="tree-controls-grid">
      <!-- Group A: Tree Structure (Root, Height, Orientation) -->
      <div class="ctrl-group">
        <div class="ctrl-group-title">① 起点・高さ・表示方向</div>
        <div class="ctrl-row">
          <label>
            起点モード:
            <select bind:value={rootMode} on:change={() => fetchLoopTree()}>
              <option value="loop">ループ全体 (h=0〜{maxHeight})</option>
              <option value="single">指定した数値を根にする</option>
            </select>
          </label>

          {#if rootMode === "single"}
            <label>
              起点の数値:
              <input
                type="number"
                min="1"
                bind:value={rootN}
                on:change={() => fetchLoopTree()}
                class="num-input"
              />
            </label>
          {/if}

          <label>
            高さ (H):
            <input
              type="number"
              min="1"
              max="20"
              bind:value={maxHeight}
              on:change={() => fetchLoopTree()}
              class="num-input short"
            />
          </label>

          <label>
            木の向き (根の位置):
            <select
              bind:value={orientation}
              on:change={() => recomputeLayout(true)}
            >
              <option value="BT">下から上 (根＝下・縦向き)</option>
              <option value="TB">上から下 (根＝上・縦向き)</option>
              <option value="LR">左から右 (根＝左・横向き)</option>
              <option value="RL">右から左 (根＝右・横向き)</option>
              <option value="radial">❄️ 放射状 (雪の結晶・中心＝根)</option>
            </select>
          </label>

          <label
            title="×d の直線導管ノードを縮約して骨格構造だけを観察できます"
          >
            🦴 骨格縮約モード:
            <select
              bind:value={treeStructureMode}
              on:change={() => recomputeLayout(true)}
              class="skeleton-select"
            >
              <option value="full">通常 CTree (全ノード表示)</option>
              <option value="skeleton"
                >🦴 奇数/分岐骨格木 (r≠0 分岐点のみ抽出)</option
              >
              <option value="branch_points"
                >🌿 分岐点骨格木 (1本道の中間点を縮約)</option
              >
            </select>
          </label>

          <label
            class="chk-label"
            title="赤=非自明分岐ノード(r≠0), 水色=海面下(n≤q), 灰=×d導管ノード(r=0)"
          >
            <input type="checkbox" bind:checked={highlightNodeRoles} />
            役割別に色分け(分岐/海面/導管)
          </label>

          <label
            class="chk-label"
            title="非自明分岐ノードを、使用している q_r (r=1..{p - 2}) ごとの色で塗り分けます"
          >
            <input type="checkbox" bind:checked={colorBranchByQ} />
            🎨 分岐ノードをq別に色分け
          </label>
        </div>
      </div>

      <!-- Group B: Node, Branch, & Label Styling -->
      <div class="ctrl-group">
        <div class="ctrl-group-title">② ノード・枝・数値ラベル設定</div>
        <div class="ctrl-row">
          <label title="ノード半径">
            サイズ({nodeRadius}):
            <input
              type="range"
              min="2"
              max="18"
              step="0.5"
              bind:value={nodeRadius}
            />
          </label>

          <label title="通常ノードの色">
            ノード色:
            <input type="color" bind:value={nodeColor} class="color-btn" />
          </label>

          <label title="ループ要素 (高さ0) の色">
            根(ループ)色:
            <input type="color" bind:value={loopNodeColor} class="color-btn" />
          </label>

          <label title="Treeの枝（エッジ）の色">
            枝の色:
            <input type="color" bind:value={branchColor} class="color-btn" />
          </label>

          <label title="枝の太さ">
            枝太さ:
            <input
              type="range"
              min="0.5"
              max="5"
              step="0.5"
              bind:value={branchWidth}
              class="short-range"
            />
          </label>

          <label title="Tree全体の不透明度">
            不透明度({Math.round(treeOpacity * 100)}%):
            <input
              type="range"
              min="0.15"
              max="1.0"
              step="0.05"
              bind:value={treeOpacity}
              class="short-range"
            />
          </label>

          <label class="chk-label">
            <input type="checkbox" bind:checked={showLabels} />
            数値を隣接表示
          </label>

          {#if showLabels}
            <label title="文字サイズ">
              文字({labelFontSize}px):
              <input
                type="range"
                min="6"
                max="18"
                step="1"
                bind:value={labelFontSize}
                class="short-range"
              />
            </label>
            <input
              type="color"
              bind:value={labelColor}
              class="color-btn"
              title="文字色"
            />
          {/if}
        </div>
      </div>

      <!-- Group C: Node Spacing & Background & Export -->
      <div class="ctrl-group">
        <div class="ctrl-group-title">
          ③ ノード間隔（密度）・背景・ファイル出力
        </div>
        <div class="ctrl-row">
          <div class="preset-btns">
            <span>間隔:</span>
            <button class="btn-xs" on:click={() => applySpacingPreset("dense")}
              >狭く(高密度)</button
            >
            <button class="btn-xs" on:click={() => applySpacingPreset("normal")}
              >標準</button
            >
            <button
              class="btn-xs"
              on:click={() => applySpacingPreset("spacious")}>ゆったり</button
            >
          </div>

          <label title="兄弟ノード同士の間隔">
            横間隔({siblingSpacing}):
            <input
              type="range"
              min="10"
              max="110"
              step="2"
              bind:value={siblingSpacing}
              on:input={() => recomputeLayout(false)}
              class="short-range"
            />
          </label>

          <label title="階層（高さ）間の距離">
            階層間隔({levelSpacing}):
            <input
              type="range"
              min="25"
              max="180"
              step="5"
              bind:value={levelSpacing}
              on:input={() => recomputeLayout(false)}
              class="short-range"
            />
          </label>

          <label class="chk-label">
            <input type="checkbox" bind:checked={bgTransparent} />
            背景透明
          </label>

          {#if !bgTransparent}
            <label>
              背景色:
              <input type="color" bind:value={bgColor} class="color-btn" />
            </label>
            <label title="背景の不透明度">
              背景濃度:
              <input
                type="range"
                min="0.1"
                max="1.0"
                step="0.05"
                bind:value={bgOpacity}
                class="short-range"
              />
            </label>
          {/if}

          <div class="export-btns">
            <button class="btn-export" on:click={exportTreePng}
              >⬇ PNG出力</button
            >
            <button class="btn-export" on:click={exportTreeSvg}
              >⬇ SVG出力</button
            >
            <button
              class="btn-export crystal-gif-btn"
              disabled={crystalGifLoading}
              on:click={downloadCrystalGif}
              title="世代 k=0..K の結晶成長を暗視野撮影風アニメーションGIFとして出力します"
            >
              {crystalGifLoading ? "⏳ GIF生成中..." : "🎬 暗視野GIF生成"}
            </button>
          </div>
        </div>
      </div>

      <!-- Group D: Snow Crystal Growth Mode (Dark-Field Interactive Evolution) -->
      <div class="ctrl-group crystal-ctrl-bar" class:active={crystalMode}>
        <div class="ctrl-group-title">④ ❄️ 雪の結晶成長 (暗視野)</div>
        <div class="ctrl-row">
          <label class="chk-label crystal-toggle">
            <input
              type="checkbox"
              bind:checked={crystalMode}
              on:change={toggleCrystalMode}
            />
            <strong>❄️ 結晶成長モード ON/OFF</strong>
          </label>

          {#if crystalMode}
            <label
              title="世代ごとに掛ける倍率 g (p=3なら3, p=4なら2, p=5なら5, p=6なら6/2/3等)"
            >
              倍率(×g):
              <input
                type="number"
                min="2"
                max="29"
                bind:value={crystalMultiplier}
                on:change={() => fetchCrystalGrowth(false)}
                class="num-input short"
              />
            </label>

            <label title="最大世代 K">
              最大世代(K):
              <input
                type="number"
                min="1"
                max="7"
                bind:value={crystalMaxGen}
                on:change={() => fetchCrystalGrowth(false)}
                class="num-input short"
              />
            </label>

            <button class="btn-xs primary" on:click={toggleCrystalPlay}>
              {crystalPlaying ? "⏸ 停止" : "▶ コマ送り再生"}
            </button>

            <label class="gen-slider-label">
              世代 k = <strong>{crystalGen}</strong> (×{crystalMultiplier}<sup
                >{crystalGen}</sup
              >
              = ×{Math.pow(crystalMultiplier, crystalGen)}):
              <input
                type="range"
                min="0"
                max={crystalData?.max_gen ?? crystalMaxGen}
                step="1"
                bind:value={crystalGen}
                on:input={() => {
                  stopCrystalPlay();
                  applyCrystalGeneration(Number(crystalGen), false);
                }}
              />
            </label>

            {#if treeData?.counts_by_state}
              <span class="crystal-legend-pills">
                <span class="c-pill core"
                  >● 核(h=0): {treeData.counts_by_state.core}</span
                >
                <span class="c-pill frozen"
                  >❄️ 凍結完了(h≤{treeData.frozen_height || 0}): {treeData
                    .counts_by_state.frozen}</span
                >
                <span class="c-pill newborn"
                  >✨ 新芽発芽: {treeData.counts_by_state.newborn}</span
                >
              </span>
            {/if}
          {:else}
            <span class="crystal-hint">
              ONにすると暗視野顕微鏡モードになり、世代 k
              ごとに中心から外側へ枝が凍結・発芽していく結晶成長をスライダーや自動再生で観察できます
            </span>
          {/if}
        </div>
      </div>
    </div>
  {/if}

  <!-- Section 3: Interactive SVG Tree Viewport -->
  <div
    class="tree-stage"
    class:checkerboard={bgTransparent || bgOpacity < 1}
    bind:clientWidth={viewportWidth}
    bind:clientHeight={viewportHeight}
    style={!bgTransparent
      ? `background-color: ${hexToRgba(bgColor, bgOpacity)};`
      : ""}
  >
    <!-- Floating Zoom overlay controls -->
    <div class="stage-zoom-bar">
      <button on:click={() => zoomBy(1.25)} title="ズームイン">＋ 拡大</button>
      <button on:click={() => zoomBy(0.8)} title="ズームアウト">－ 縮小</button>
      <button on:click={fitToView} title="ツリー全体を画面にフィット"
        >⊡ 全体フィット</button
      >
      <span class="zoom-pct">{Math.round(zoomScale * 100)}%</span>
    </div>

    {#if loading}
      <div class="stage-overlay">CTree を構築中...</div>
    {:else if error}
      <div class="stage-overlay error">エラー: {error}</div>
    {:else}
      <!-- svelte-ignore a11y-no-static-element-interactions -->
      <svg
        bind:this={svgElement}
        width="100%"
        height="100%"
        on:wheel={handleSvgWheel}
        on:mousedown={handleSvgMouseDown}
        on:mousemove={handleSvgMouseMove}
        on:mouseup={handleSvgMouseUp}
        on:mouseleave={handleSvgMouseUp}
      >
        <g
          transform="translate({panX}, {panY}) scale({zoomScale})"
          opacity={treeOpacity}
        >
          <!-- Concentric Height Rings in Radial / Crystal Mode -->
          {#if orientation === "radial"}
            {#each Array(Number(maxHeight) + 1) as _, hIdx}
              {@const ringR = (hIdx + 1) * levelSpacing * 0.78}
              {@const isFrozenRing =
                crystalMode &&
                crystalGen > 0 &&
                hIdx <= (treeData?.frozen_height || 0)}
              <circle
                cx="0"
                cy="0"
                r={ringR}
                fill="none"
                stroke={isFrozenRing
                  ? "#38bdf8"
                  : crystalMode
                    ? "#1e293b"
                    : "#cbd5e1"}
                stroke-width={isFrozenRing ? 1.4 : 0.8}
                stroke-dasharray={isFrozenRing ? "none" : "4,4"}
                opacity={isFrozenRing ? 0.5 : 0.45}
              />
            {/each}
          {/if}

          <!-- Loop Spine Links (dashed line connecting loop members at h=0) -->
          {#each loopSpineLinks as sp}
            <line
              x1={sp.source.x}
              y1={sp.source.y}
              x2={sp.target.x}
              y2={sp.target.y}
              stroke={crystalMode ? "#7dd3fc" : loopNodeColor}
              stroke-width={branchWidth * 1.4}
              stroke-dasharray={crystalMode ? "none" : "4,4"}
              opacity="0.82"
            />
          {/each}

          <!-- Tree Branches -->
          <g fill="none">
            {#each layoutLinks as lk}
              {@const brCol = crystalMode
                ? lk.crystal_state === "newborn"
                  ? "#fde047"
                  : lk.crystal_state === "frozen"
                    ? "#e0f2fe"
                    : "#60a5fa"
                : branchColor}
              {#if crystalMode}
                <path
                  d={linkPath(lk)}
                  stroke={lk.crystal_state === "newborn"
                    ? "#f59e0b"
                    : "#38bdf8"}
                  stroke-width={branchWidth * 2.8}
                  opacity="0.28"
                />
              {/if}
              <path
                d={linkPath(lk)}
                stroke={brCol}
                stroke-width={crystalMode && lk.crystal_state === "newborn"
                  ? branchWidth * 1.35
                  : branchWidth}
                stroke-dasharray={!crystalMode && lk.branch_r !== 0
                  ? "4,2"
                  : "none"}
              />
            {/each}
          </g>

          <!-- Tree Nodes -->
          {#each layoutNodes as nd}
            <!-- svelte-ignore a11y-click-events-have-key-events -->
            <!-- svelte-ignore a11y-no-static-element-interactions -->
            <circle
              cx={nd.x}
              cy={nd.y}
              r={getNodeRadiusPx(nd)}
              fill={getNodeFillColor(nd, colorBranchByQ)}
              stroke="#ffffff"
              stroke-width="1"
              class="tree-node-circle"
              on:mouseenter={() => (hoveredNode = nd)}
              on:mouseleave={() => (hoveredNode = null)}
              on:click|stopPropagation={() => selectAsSingleRoot(nd.n)}
            />
          {/each}

          <!-- Node Number Labels -->
          {#if showLabels}
            {@const off = labelOffset({})}
            <g
              font-family="monospace, sans-serif"
              font-size={labelFontSize}
              fill={labelColor}
              text-anchor={off.anchor}
              pointer-events="none"
            >
              {#each layoutNodes as nd}
                <text x={nd.x + off.dx} y={nd.y + off.dy}>
                  {nd.n}{treeStructureMode !== "full" && !nd.is_loop
                    ? ` (h=${nd.height})`
                    : ""}
                </text>
              {/each}
            </g>
          {/if}
        </g>
      </svg>

      {#if hoveredNode}
        <div class="node-hover-card">
          <div>
            <strong>数値 n = {hoveredNode.n.toLocaleString()}</strong> (高さ h = {hoveredNode.height})
          </div>
          <div>
            余り r = {hoveredNode.r}
            {#if !hoveredNode.is_loop && hoveredNode.branch_r > 0}
              / 使用 q: q<sub>{hoveredNode.branch_r}</sub> = {q?.[hoveredNode.branch_r]}
            {/if}
            / 遷移: {hoveredNode.formula}
          </div>
          <div class="click-hint">クリックでこの数値を起点(Root)に設定</div>
        </div>
      {/if}
    {/if}
  </div>
</div>

<style>
  .floating-window {
    position: fixed;
    width: 1080px;
    height: 760px;
    min-width: 520px;
    min-height: 420px;
    background: #ffffff;
    border: 2px solid #0284c7;
    border-radius: 10px;
    box-shadow: 0 20px 50px rgba(15, 23, 42, 0.32);
    z-index: 1000;
    display: flex;
    flex-direction: column;
    resize: both;
    overflow: hidden;
  }

  .floating-window.maximized {
    left: 16px !important;
    top: 16px !important;
    width: calc(100vw - 32px) !important;
    height: calc(100vh - 32px) !important;
    resize: none;
  }

  .window-header {
    background: #0f172a;
    color: #ffffff;
    padding: 9px 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: move;
    user-select: none;
    gap: 10px;
    flex-wrap: wrap;
  }

  .win-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.92rem;
    flex-wrap: wrap;
  }

  .win-dot {
    width: 11px;
    height: 11px;
    border-radius: 50%;
    display: inline-block;
  }

  .win-sub {
    color: #cbd5e1;
    font-family: monospace;
    font-size: 0.82rem;
  }

  .node-count-badge {
    background: #0284c7;
    color: #ffffff;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 600;
  }

  .win-actions {
    display: flex;
    gap: 6px;
  }

  .btn-win {
    background: #1e293b;
    color: #e2e8f0;
    border: 1px solid #334155;
    padding: 4px 10px;
    border-radius: 5px;
    font-size: 0.78rem;
  }
  .btn-win:hover {
    background: #334155;
  }
  .btn-win.btn-close:hover {
    background: #dc2626;
    border-color: #dc2626;
    color: #ffffff;
  }

  .loop-elements-panel {
    background: #f8fafc;
    border-bottom: 1px solid #cbd5e1;
    padding: 8px 14px;
    max-height: 125px;
    overflow-y: auto;
  }

  .loop-elements-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.8rem;
    margin-bottom: 6px;
    flex-wrap: wrap;
    gap: 8px;
  }

  .loop-elements-header .hint {
    color: #64748b;
    margin-left: 8px;
  }

  .loop-elements-chain {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
  }

  .loop-el-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 7px;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    background: #ffffff;
    font-family: monospace;
    font-size: 0.8rem;
  }
  .loop-el-chip:hover {
    border-color: #0284c7;
    background: #f0f9ff;
  }
  .loop-el-chip.selected-root {
    background: #0284c7;
    color: #ffffff;
    border-color: #0369a1;
  }

  .el-idx {
    font-size: 0.68rem;
    color: #94a3b8;
  }
  .selected-root .el-idx,
  .selected-root .el-r {
    color: #e0f2fe;
  }

  .el-r {
    color: #64748b;
    font-size: 0.7rem;
  }

  .chain-arrow {
    color: #94a3b8;
    font-size: 0.75rem;
  }

  .loop-back-badge {
    font-size: 0.75rem;
    font-weight: 600;
    color: #0369a1;
    background: #e0f2fe;
    padding: 2px 7px;
    border-radius: 4px;
  }

  .tree-controls-grid {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px 14px;
    background: #f1f5f9;
    border-bottom: 1px solid #cbd5e1;
    font-size: 0.78rem;
  }

  .ctrl-group {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .ctrl-group-title {
    font-weight: 700;
    color: #334155;
    min-width: 155px;
  }

  .ctrl-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    flex: 1;
  }

  .ctrl-row label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: #1e293b;
    font-weight: 500;
  }

  .num-input {
    width: 82px;
    padding: 3px 6px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    font-size: 0.8rem;
  }
  .num-input.short {
    width: 54px;
  }

  .short-range {
    width: 68px;
  }

  .color-btn {
    width: 24px;
    height: 22px;
    border: none;
    padding: 0;
    background: transparent;
    cursor: pointer;
  }

  .chk-label {
    cursor: pointer;
    user-select: none;
  }

  .preset-btns {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .btn-xs {
    padding: 2px 7px;
    font-size: 0.74rem;
    border: 1px solid #cbd5e1;
    background: #ffffff;
    border-radius: 4px;
  }
  .btn-xs:hover {
    background: #e2e8f0;
  }
  .btn-xs.primary {
    background: #0284c7;
    color: #ffffff;
    border-color: #0284c7;
  }

  .export-btns {
    margin-left: auto;
    display: flex;
    gap: 6px;
  }

  .btn-export {
    background: #0f172a;
    color: #ffffff;
    border: none;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 0.76rem;
    font-weight: 600;
  }
  .btn-export:hover {
    background: #334155;
  }

  .tree-stage {
    flex: 1;
    position: relative;
    overflow: hidden;
    cursor: grab;
    user-select: none;
  }
  .tree-stage:active {
    cursor: grabbing;
  }

  .tree-stage.checkerboard {
    background-image: linear-gradient(45deg, #e2e8f0 25%, transparent 25%),
      linear-gradient(-45deg, #e2e8f0 25%, transparent 25%),
      linear-gradient(45deg, transparent 75%, #e2e8f0 75%),
      linear-gradient(-45deg, transparent 75%, #e2e8f0 75%);
    background-size: 20px 20px;
    background-position:
      0 0,
      0 10px,
      10px -10px,
      -10px 0px;
  }

  .stage-zoom-bar {
    position: absolute;
    top: 10px;
    left: 10px;
    z-index: 5;
    display: flex;
    align-items: center;
    gap: 5px;
    background: rgba(255, 255, 255, 0.9);
    padding: 4px 8px;
    border-radius: 6px;
    border: 1px solid #cbd5e1;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
  }

  .stage-zoom-bar button {
    padding: 3px 8px;
    font-size: 0.76rem;
    border: 1px solid #cbd5e1;
    background: #ffffff;
    border-radius: 4px;
    font-weight: 600;
  }
  .stage-zoom-bar button:hover {
    background: #f1f5f9;
  }

  .zoom-pct {
    font-size: 0.75rem;
    color: #475569;
    font-family: monospace;
    margin-left: 4px;
  }

  .tree-node-circle {
    cursor: pointer;
    transition: stroke-width 0.12s;
  }
  .tree-node-circle:hover {
    stroke: #0f172a;
    stroke-width: 2.5px;
  }

  .node-hover-card {
    position: absolute;
    bottom: 12px;
    left: 12px;
    background: rgba(15, 23, 42, 0.92);
    color: #ffffff;
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 0.8rem;
    pointer-events: none;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  }

  .click-hint {
    font-size: 0.72rem;
    color: #38bdf8;
    margin-top: 2px;
  }

  .stage-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1rem;
    font-weight: 600;
    color: #334155;
    background: rgba(255, 255, 255, 0.75);
  }
  .stage-overlay.error {
    color: #dc2626;
  }

  .spectrum-panel {
    background: #f8fafc;
    border-bottom: 1px solid #cbd5e1;
    padding: 6px 14px;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }

  .spectrum-summary-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 0.76rem;
  }

  .diag-badge-group {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .diag-title {
    font-weight: 700;
    color: #0f172a;
  }

  .diag-pill {
    padding: 2px 8px;
    border-radius: 999px;
    font-weight: 600;
    font-size: 0.73rem;
  }

  .diag-pill.rootlet-ok {
    background: #fef2f2;
    color: #b91c1c;
    border: 1px solid #fecaca;
  }

  .diag-pill.rootlet-sealed {
    background: #f3e8ff;
    color: #6b21a8;
    border: 1px solid #e9d5ff;
  }

  .diag-pill.sea-pill {
    background: #e0f2fe;
    color: #0369a1;
    border: 1px solid #bae6fd;
  }

  .diag-pill.mode-pill {
    background: #e2e8f0;
    color: #334155;
  }

  .spectrum-vector-text code {
    background: #e2e8f0;
    color: #0f172a;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.72rem;
  }

  .r-usage-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    padding-top: 4px;
    border-top: 1px dashed #cbd5e1;
    font-size: 0.73rem;
  }

  .r-usage-label {
    font-weight: 700;
    color: #334155;
    white-space: nowrap;
  }

  .r-usage-badges {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
  }

  .r-usage-pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 1px 6px;
    border-radius: 999px;
    background: #ffffff;
    border: 1px solid color-mix(in srgb, var(--q-col) 45%, #cbd5e1);
    color: #1e293b;
    font-size: 0.71rem;
    font-family: monospace;
  }

  .r-usage-pill.unused {
    opacity: 0.55;
    border-style: dashed;
  }

  .r-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .r-usage-dict {
    background: #e2e8f0;
    color: #0f172a;
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 0.71rem;
  }

  .r-color-toggle {
    margin-left: auto;
    font-size: 0.74rem;
    font-weight: 600;
    color: #0f172a;
    white-space: nowrap;
  }

  .spectrum-bars-row {
    display: flex;
    align-items: flex-end;
    gap: 6px;
    overflow-x: auto;
    padding: 2px 0;
  }

  .sp-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 28px;
    font-size: 0.68rem;
  }

  .sp-cnt {
    font-weight: 700;
    color: #1e293b;
    font-family: monospace;
  }

  .sp-bar-wrap {
    height: 30px;
    display: flex;
    align-items: flex-end;
  }

  .sp-bar {
    width: 14px;
    border-radius: 3px 3px 0 0;
  }

  .sp-h {
    color: #64748b;
    font-family: monospace;
  }

  .skeleton-select {
    font-weight: 600;
    color: #0f172a;
    border-color: #0284c7;
    background: #f0f9ff;
  }

  .crystal-gif-btn {
    background: #0369a1;
  }
  .crystal-gif-btn:hover {
    background: #0284c7;
  }

  .crystal-ctrl-bar {
    background: #e0f2fe;
    padding: 5px 10px;
    border-radius: 6px;
    border: 1px solid #bae6fd;
  }
  .crystal-ctrl-bar.active {
    background: #0f172a;
    color: #f8fafc;
    border-color: #38bdf8;
  }
  .crystal-ctrl-bar.active .ctrl-group-title,
  .crystal-ctrl-bar.active label {
    color: #e0f2fe;
  }

  .gen-slider-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .crystal-legend-pills {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-left: auto;
  }

  .c-pill {
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
  }
  .c-pill.core {
    background: #ffffff;
    color: #0f172a;
  }
  .c-pill.frozen {
    background: #0284c7;
    color: #e0f2fe;
  }
  .c-pill.newborn {
    background: #f59e0b;
    color: #0f172a;
  }

  .crystal-hint {
    color: #0369a1;
    font-size: 0.74rem;
  }

  .tree-compact-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    padding: 6px 12px;
    background: #f1f5f9;
    border-bottom: 1px solid #cbd5e1;
    font-size: 0.8rem;
  }

  .tree-compact-bar label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: #1e293b;
  }

  .tree-opt-toggle {
    margin-left: auto;
  }

  .tree-opt-toggle.active {
    background: #e0f2fe;
    border-color: #0284c7;
    color: #0369a1;
  }
</style>
