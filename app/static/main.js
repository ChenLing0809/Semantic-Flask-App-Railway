let currentLogId = null;

const fileInput = document.getElementById("fileInput");
const btnUpload = document.getElementById("btnUpload");
const uploadStatus = document.getElementById("uploadStatus");
const levelRange = document.getElementById("levelRange");
const levelLabel = document.getElementById("levelLabel");
const svg = document.getElementById("petriSvg");

const semanticMetric = document.querySelectorAll('input[name="metric"]');
const semanticRange = document.getElementById("semanticRange");
const semanticLabel = document.getElementById("semanticLabel");

btnUpload.addEventListener("click", () => {
  fileInput.click();
});

//==========Data selection and uploading==========
fileInput.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  uploadStatus.textContent = `Uploading ${file.name}...`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/discover", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) throw new Error("Upload failed!");
    const data = await res.json();

    currentLogId = data.logId;
    console.log("✅ Set currentLogId:", currentLogId);
    //console.log("✅ Set semantic metric:", semanticMetric);
    uploadStatus.textContent = `Discovered petri net from ${file.name}`;
    drawPetriNet(data); //change if other graph needed
    drawAnnotation(data.tree); //draw annotations
  } catch (err) {
    console.error(err);
    uploadStatus.textContent = "Error during discovery!";
  }
});

//==========Hierarchical sliding==========
let debounceTimer;

levelRange.addEventListener("input", (e) => {
  console.log("Slider input fired!");
  const level = parseFloat(e.target.value);
  //levelLabel.textContent = level.toFixed(2);
  levelLabel.textContent = Math.round(level * 100) + "%";
  scheduleAggregation();
});

//==========Threshold sliding==========
semanticRange.addEventListener("input", (e) => {
  const v = parseFloat(e.target.value);
  //semanticLabel.textContent = v.toFixed(2);
  semanticLabel.textContent = Math.round(v * 100) + "%";
  console.log("Threshold slider changed:", v);
  scheduleAggregation();
});

//==========Semantic Metric Radio Button==========
semanticMetric.forEach((r) => {
  r.addEventListener("input", () => {
    console.log("Semantic metric changed:", r.value);
    // adjust threshold default depending on semantic mode ---
    if (r.value === "infrequent" || r.value === "short_time") {
      semanticRange.value = 0;
      semanticLabel.textContent = "0%";
    } else if (r.value === "frequent" || r.value === "long_time") {
      semanticRange.value = 1;
      semanticLabel.textContent = "100%";
    } else {
      // for "none" or other modes, keep current
      console.log("No automatic threshold reset for 'none'");
    }
    scheduleAggregation();
  });
});

//==========Schedule Aggregation==========
function scheduleAggregation() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(requestAggregation, 400);
}

function getSemanticMode() {
  const selected = document.querySelector('input[name="metric"]:checked');
  return selected ? selected.value : "none";
}

async function requestAggregation() {
  if (!currentLogId) return;

  const level = parseFloat(levelRange.value);
  const threshold = parseFloat(semanticRange.value);
  const semanticMode = getSemanticMode();

  console.log(
    "Aggregation request",
    JSON.stringify({ level, semanticMode, threshold })
  );

  try {
    const res = await fetch("/api/aggregate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        logId: currentLogId,
        level,
        semanticMode,
        threshold,
      }),
    });

    if (!res.ok) throw new Error("Aggregation failed!");
    const data = await res.json();
    drawPetriNet(data); // Re-render with new aggregation
    drawAnnotation(data.tree); //draw annotations
  } catch (err) {
    console.error(err);
    uploadStatus.textContent = "Error during aggregation!";
  }
}

//==========Petrinet Redering==========
function generateDot(petriNet) {
  let dot = "digraph PetriNet {\n  rankdir=LR;\n";

  dot += "  node [shape=circle, style=filled, fillcolor=lightblue];\n";
  petriNet.nodes
    .filter((n) => n.type === "place")
    .forEach((p) => {
      dot += `  "${p.id}" [label="${p.label}"];\n`;
    });

  dot += "  node [shape=box, style=filled, fillcolor=lightgray];\n";
  petriNet.nodes
    .filter((n) => n.type === "transition")
    .forEach((t) => {
      dot += `  "${t.id}" [label="${t.label}"];\n`;
    });

  petriNet.links.forEach((link) => {
    dot += `  "${link.source}" -> "${link.target}";\n`;
  });

  dot += "}";
  return dot;
}

function drawPetriNet(data) {
  const svg = document.getElementById("petriSvg");
  // compute dot for graph layout
  const dot = generateDot(data);
  const viz = new Viz();

  viz
    .renderSVGElement(dot)
    .then((renderedSvg) => {
      //clear existing content
      while (svg.firstChild) {
        svg.removeChild(svg.firstChild);
      }

      const graphGroup = renderedSvg.querySelector("g.graph");
      const defs = renderedSvg.querySelector("defs");

      if (defs) svg.appendChild(defs.cloneNode(true));
      if (graphGroup) svg.appendChild(graphGroup.cloneNode(true));

      requestAnimationFrame(() => {
        const bb = svg.getBBox();
        svg.setAttribute("viewBox", `${bb.x} ${bb.y} ${bb.width} ${bb.height}`);
        svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
      });

      // enable zoom and panning
      enablePanZoom(svg);
    })
    .catch((error) => {
      console.error("Viz.js rendering error:", error);
      uploadStatus.textContent = "Error rendering Petri net!";
    });
}

function enablePanZoom(svg) {
  let scale = 1.0;
  const minScale = 0.2;
  const maxScale = 8.0;
  const viewport = document.createElementNS("http://www.w3.org/2000/svg", "g");

  // Move all existing children into the <g> viewport
  while (svg.firstChild) {
    viewport.appendChild(svg.firstChild);
  }
  svg.appendChild(viewport);

  let translate = { x: 0, y: 0 };
  let isDragging = false;
  let last = { x: 0, y: 0 };

  function updateTransform() {
    viewport.setAttribute(
      "transform",
      `translate(${translate.x},${translate.y}) scale(${scale})`
    );
  }

  // Mouse drag panning
  svg.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    isDragging = true;
    last.x = e.clientX;
    last.y = e.clientY;
    svg.setPointerCapture(e.pointerId);
  });

  svg.addEventListener("pointermove", (e) => {
    if (!isDragging) return;
    const dx = e.clientX - last.x;
    const dy = e.clientY - last.y;
    last.x = e.clientX;
    last.y = e.clientY;
    translate.x += dx;
    translate.y += dy;
    updateTransform();
  });

  svg.addEventListener("pointerup", (e) => {
    isDragging = false;
    svg.releasePointerCapture(e.pointerId);
  });
  svg.addEventListener("pointerleave", () => (isDragging = false));

  // Wheel zoom (centered on cursor)
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = svg.getBoundingClientRect();
    const pt = {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    };

    const cx = (pt.x - translate.x) / scale;
    const cy = (pt.y - translate.y) / scale;

    const delta = -e.deltaY;
    const zoomFactor = Math.exp(delta * 0.0015);
    const newScale = Math.min(maxScale, Math.max(minScale, scale * zoomFactor));
    const k = newScale / scale;

    translate.x = pt.x - cx * newScale;
    translate.y = pt.y - cy * newScale;
    scale = newScale;
    updateTransform();
  });

  updateTransform();
}

//==========Aggregated Nodes Annotations==========
function drawAnnotation(treeData) {
  const viewport = document.getElementById("annotationViewport");
  viewport.innerHTML = "";

  if (!treeData) {
    viewport.textContent = "No annotation available.";
    return;
  }

  const root = createAnnotationBox(treeData);
  viewport.appendChild(root);

  requestAnimationFrame(() => {
    autoFitAnnotation();
    enableAnnotationPanZoom();
  });
}

function createAnnotationBox(node) {
  // Operator node
  if (node.operator) {
    const opType = (node.operator || "").toLowerCase(); // sequence, and, xor, or, loop, etc.
    const box = document.createElement("div");
    box.classList.add("annotation-box"); // stays uncolored

    // title
    const title = document.createElement("div");
    title.classList.add("operator-title");
    title.textContent = opType ? opType.toUpperCase() : "OP";
    box.appendChild(title);

    // layout by semantics
    const layout = opType === "sequence" ? "horizontal" : "vertical";
    const kids = document.createElement("div");
    kids.classList.add("children", layout);

    (node.children || []).forEach((child) => {
      kids.appendChild(createAnnotationBox(child));
    });

    box.appendChild(kids);
    return box;
  }

  // Leaf or aggregated leaf
  if (node.label) {
    // leaf = original Petri task → colored
    const leaf = document.createElement("div");
    leaf.classList.add("annotation-box", "leaf");
    leaf.textContent = node.label;

    // if this leaf is an aggregated node (has original subtree)
    if (node.aggregated_from) {
      const dashedWrap = document.createElement("div");
      dashedWrap.classList.add("annotation-box", "dashed"); // uncolored dashed
      // nested original subtree
      dashedWrap.appendChild(createAnnotationBox(node.aggregated_from));
      // put wrapper under the leaf label
      const wrapHolder = document.createElement("div");
      wrapHolder.style.marginTop = "6px";
      wrapHolder.appendChild(dashedWrap);
      leaf.appendChild(wrapHolder);
    }

    return leaf;
  }

  // Edge case: object with only aggregated_from but no label/operator
  if (node.aggregated_from) {
    const dashedWrap = document.createElement("div");
    dashedWrap.classList.add("annotation-box", "dashed");
    dashedWrap.appendChild(createAnnotationBox(node.aggregated_from));
    return dashedWrap;
  }

  // Fallback empty box
  const fallback = document.createElement("div");
  fallback.classList.add("annotation-box");
  fallback.textContent = "";
  return fallback;
}

function autoFitAnnotation() {
  const box = document.getElementById("annotationBox");
  const viewport = document.getElementById("annotationViewport");

  const bb = viewport.getBoundingClientRect();
  const bw = box.clientWidth;
  const bh = box.clientHeight;

  const scale = Math.min(bw / bb.width, bh / bb.height, 1);

  viewport.style.transform = `translate(0px,0px) scale(${scale})`;
  viewport.dataset.scale = scale;
  viewport.dataset.tx = 0;
  viewport.dataset.ty = 0;
}

function enableAnnotationPanZoom() {
  const viewport = document.getElementById("annotationViewport");
  let scale = Number(viewport.dataset.scale) || 1;
  let tx = Number(viewport.dataset.tx) || 0;
  let ty = Number(viewport.dataset.ty) || 0;

  function apply() {
    viewport.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    viewport.dataset.scale = scale;
    viewport.dataset.tx = tx;
    viewport.dataset.ty = ty;
  }

  // ===== Mouse wheel ZOOM =====
  document.getElementById("annotationBox").addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;

    const k = Math.exp(-e.deltaY * 0.0015);
    const newScale = Math.min(6, Math.max(0.1, scale * k));

    tx = cx - (cx - tx) * (newScale / scale);
    ty = cy - (cy - ty) * (newScale / scale);

    scale = newScale;
    apply();
  });

  // ===== Drag panning =====
  let drag = false,
    lastX = 0,
    lastY = 0;
  viewport.addEventListener("pointerdown", (e) => {
    drag = true;
    lastX = e.clientX;
    lastY = e.clientY;
  });
  window.addEventListener("pointerup", () => (drag = false));
  window.addEventListener("pointermove", (e) => {
    if (!drag) return;
    tx += e.clientX - lastX;
    ty += e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    apply();
  });

  apply(); // initial
}
