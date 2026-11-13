(() => {
  const ns = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  const tooltip = document.createElement("div");
  tooltip.className = "metric-tooltip";
  tooltip.id = "metric-tooltip";
  tooltip.setAttribute("role", "tooltip");
  tooltip.hidden = true;
  document.body.append(tooltip);
  function show(value, target, event) {
    const host = target.closest("dialog") || document.body;
    if (tooltip.parentNode !== host) host.append(tooltip);
    tooltip.textContent = value;
    tooltip.hidden = false;
    const box = target.getBoundingClientRect();
    const x = event?.clientX ?? box.left + box.width / 2;
    const y = event?.clientY ?? box.top;
    tooltip.style.left =
      Math.max(8, Math.min(innerWidth - tooltip.offsetWidth - 8, x + 12)) +
      "px";
    tooltip.style.top =
      Math.max(8, Math.min(innerHeight - tooltip.offsetHeight - 8, y + 14)) +
      "px";
  }
  const hide = () => {
    tooltip.hidden = true;
  };
  function hint(node, value) {
    node.setAttribute("aria-describedby", "metric-tooltip");
    node.onpointermove = (e) =>
      show(typeof value === "function" ? value() : value, node, e);
    node.onpointerleave = hide;
    node.onfocus = () =>
      show(typeof value === "function" ? value() : value, node);
    node.onblur = hide;
  }
  function chart(
    node,
    points,
    { label, format, color = "#218878", max = null, keyboard = true } = {},
  ) {
    node.replaceChildren();
    node.setAttribute("viewBox", "0 0 400 100");
    node.setAttribute("preserveAspectRatio", "none");
    node.setAttribute("role", "img");
    node.setAttribute("aria-label", label);
    if (keyboard) node.setAttribute("tabindex", "0");
    const values = points.filter((p) => Number.isFinite(p.value));
    if (!values.length) {
      node.append(
        svg("line", {
          x1: 6,
          x2: 394,
          y1: 75,
          y2: 75,
          stroke: "#d9e5e8",
          "stroke-dasharray": "4 5",
        }),
      );
      return;
    }
    const ceiling = max || Math.max(1, ...values.map((p) => p.value));
    let segment = [];
    const x = (i) => 6 + (i * 388) / Math.max(1, points.length - 1),
      y = (v) => 92 - Math.max(0, Math.min(1, v / ceiling)) * 80;
    const flush = () => {
      if (!segment.length) return;
      node.append(
        svg("polygon", {
          points: [
            segment[0][0] + ",92",
            ...segment.map((p) => p.join(",")),
            segment[segment.length - 1][0] + ",92",
          ].join(" "),
          fill: color,
          "fill-opacity": ".10",
        }),
      );
      node.append(
        svg("polyline", {
          points: segment.map((p) => p.join(",")).join(" "),
          fill: "none",
          stroke: color,
          "stroke-width": "2.5",
          "vector-effect": "non-scaling-stroke",
        }),
      );
      segment = [];
    };
    points.forEach((p, i) => {
      if (p.value == null) {
        flush();
        return;
      }
      segment.push([x(i), y(p.value)]);
    });
    flush();
    const last = points
      .map((p, i) => ({ ...p, i }))
      .filter((p) => p.value != null)
      .pop();
    node.append(
      svg("circle", { cx: x(last.i), cy: y(last.value), r: 3.5, fill: color }),
    );
    const guide = svg("line", {
      y1: 5,
      y2: 95,
      stroke: color,
      "stroke-dasharray": "3 4",
      visibility: "hidden",
    });
    node.append(guide);
    let index = points.length - 1;
    const reveal = (i, event) => {
      index = Math.max(0, Math.min(points.length - 1, i));
      const p = points[index];
      guide.setAttribute("x1", x(index));
      guide.setAttribute("x2", x(index));
      guide.setAttribute("visibility", "visible");
      show(
        label +
          "\n" +
          (p.value == null ? "N/A" : format(p.value)) +
          "\n" +
          new Date(p.ts * 1000).toLocaleString(),
        node,
        event,
      );
    };
    node.onpointermove = (e) => {
      const b = node.getBoundingClientRect();
      reveal(
        Math.round(((e.clientX - b.left) / b.width) * (points.length - 1)),
        e,
      );
    };
    node.onclick = (e) => {
      const b = node.getBoundingClientRect();
      reveal(
        Math.round(((e.clientX - b.left) / b.width) * (points.length - 1)),
        e,
      );
    };
    node.onpointerleave = () => {
      guide.setAttribute("visibility", "hidden");
      hide();
    };
    node.onfocus = () => reveal(points.length - 1);
    node.onblur = () => {
      guide.setAttribute("visibility", "hidden");
      hide();
    };
    node.onkeydown = (e) => {
      if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
        e.preventDefault();
        e.stopPropagation();
        reveal(
          e.key === "Home"
            ? 0
            : e.key === "End"
              ? points.length - 1
              : index + (e.key === "ArrowLeft" ? -1 : 1),
        );
      } else if (e.key === "Escape") hide();
    };
  }
  window.OrviaViz = { svg, chart, hint, show, hide };
  window.addEventListener("scroll", hide, true);
  document.addEventListener("visibilitychange", hide);
})();
