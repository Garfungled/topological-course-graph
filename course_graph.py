"""
RPI Course Prerequisite Graph
"""

import math
import argparse
import json
import sys
from collections import defaultdict
from typing import Optional

import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── Graph construction ──────────────────────────────────────────────────────

def load_courses(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_graph(courses: list[dict], prefix_filter: Optional[str] = None) -> nx.DiGraph:
    G = nx.DiGraph()
    course_map = {c["course_id"]: c for c in courses}
    if prefix_filter:
        primary_ids = {c["course_id"] for c in courses if c["prefix"] == prefix_filter.upper()}
    else:
        primary_ids = {c["course_id"] for c in courses}

    for course in courses:
        cid = course["course_id"]

        if prefix_filter and course["prefix"] != prefix_filter.upper():
            continue

        # Add the course node
        G.add_node(cid,
                    title=course.get("title", ""),
                    credit_hours=course.get("credit_hours", ""),
                    prefix=course.get("prefix", ""),
                    description=course.get("description", ""),
                    external=False)

        for prereq_id in course.get("prerequisites", []):
            if prereq_id not in G:
                if prereq_id in course_map:
                    p = course_map[prereq_id]
                    G.add_node(prereq_id,
                               title=p.get("title", ""),
                               credit_hours=p.get("credit_hours", ""),
                               prefix=p.get("prefix", ""),
                               description=p.get("description", ""),
                               external=prereq_id not in primary_ids)
                else:
                    G.add_node(prereq_id,
                               title="(not in catalog)",
                               credit_hours="",
                               prefix=prereq_id.split()[0] if " " in prereq_id else "",
                               description="",
                               external=True)

            G.add_edge(prereq_id, cid, relationship="prerequisite")

    return G


# ── Cycle detection and resolution ──────────────────────────────────────────

def detect_cycles(G: nx.DiGraph) -> list[list[str]]:
    return list(nx.simple_cycles(G))


def print_cycles(G: nx.DiGraph):
    cycles = detect_cycles(G)
    if not cycles:
        print("\n  No cycles found: graph is DAG.")
        return cycles

    print(f"Cycle Detection")
    print(f"  Found {len(cycles)} cycle(s):\n")

    for i, cycle in enumerate(cycles, 1):
        loop = cycle + [cycle[0]]
        print(f"  Cycle {i}: {' → '.join(loop)}")

        # Show why each edge exists
        for j in range(len(cycle)):
            src = cycle[j]
            dst = cycle[(j + 1) % len(cycle)]
            src_title = G.nodes[src].get("title", "")
            dst_title = G.nodes[dst].get("title", "")
            print(f"    {src} ({src_title})")
            print(f"      lists {dst} ({dst_title}) as prerequisite")
        print()

    return cycles


def break_cycles(G: nx.DiGraph, strategy: str = "auto") -> list[tuple[str, str]]:
    removed_edges = []

    if strategy == "min_edges":
        try:
            fas = nx.minimum_edge_cut(G)
        except Exception:
            fas = set()

        while not nx.is_directed_acyclic_graph(G):
            cycles = list(nx.simple_cycles(G))
            if not cycles:
                break
            cycle = cycles[0]
            edge = _pick_edge_to_remove(G, cycle)
            G.remove_edge(*edge)
            removed_edges.append(edge)
        return removed_edges

    max_iterations = 1000
    iteration = 0

    while not nx.is_directed_acyclic_graph(G) and iteration < max_iterations:
        cycles = list(nx.simple_cycles(G))
        if not cycles:
            break

        cycle = cycles[0]
        edge = _pick_edge_to_remove(G, cycle)
        G.remove_edge(*edge)
        removed_edges.append(edge)
        iteration += 1

    if not nx.is_directed_acyclic_graph(G):
        print(f"  Warning: could not fully resolve cycles after {max_iterations} removals.")

    return removed_edges


def _pick_edge_to_remove(G: nx.DiGraph, cycle: list[str]) -> tuple[str, str]:
    def _course_number(node: str) -> int:
        parts = node.split()
        if len(parts) >= 2:
            num = parts[1].split(".")[0]
            if num.isdigit():
                return int(num)
        return 0

    best_edge = None
    best_score = -float("inf")

    for i in range(len(cycle)):
        src = cycle[i]
        dst = cycle[(i + 1) % len(cycle)]

        src_num = _course_number(src)
        dst_num = _course_number(dst)
        score = src_num - dst_num

        if score == best_score and best_edge:
            if G.out_degree(src) < G.out_degree(best_edge[0]):
                best_edge = (src, dst)
                best_score = score
        elif score > best_score:
            best_edge = (src, dst)
            best_score = score

    if best_edge is None or best_score <= 0:
        min_out = float("inf")
        for i in range(len(cycle)):
            src = cycle[i]
            dst = cycle[(i + 1) % len(cycle)]
            if G.out_degree(src) < min_out:
                min_out = G.out_degree(src)
                best_edge = (src, dst)

    return best_edge


# ── Topological sort ────────────────────────────────────────────────────────

try:
    from topo_sort import (
        topo_sort_priority,
        topo_sort_kahns,
        topo_sort_grouped as _topo_grouped,
        graph_to_adj,
    )
    _HAS_CUSTOM_TOPO = True
except ImportError:
    _HAS_CUSTOM_TOPO = False


def topological_sort(G: nx.DiGraph) -> list[str]:
    if not nx.is_directed_acyclic_graph(G):
        cycles = list(nx.simple_cycles(G))
        cycle_str = "\n  ".join(
            " → ".join(c) + f" → {c[0]}" for c in cycles[:5]
        )
        raise ValueError(
            f"Graph has cycles — topological sort impossible.\n"
            f"  {cycle_str}"
            + ("\n  ..." if len(cycles) > 5 else "")
        )

    if _HAS_CUSTOM_TOPO:
        adj, in_deg = graph_to_adj(G)
        return topo_sort_priority(adj, in_deg)
    else:
        return list(nx.topological_sort(G))


def topological_sort_grouped(G: nx.DiGraph) -> list[list[str]]:
    if not nx.is_directed_acyclic_graph(G):
        raise ValueError("Graph has cycles — cannot compute semester groups.")

    if _HAS_CUSTOM_TOPO:
        adj, in_deg = graph_to_adj(G)
        return _topo_grouped(adj, in_deg)
    else:
        return list(nx.topological_generations(G))


# ── Path finding ────────────────────────────────────────────────────────────

def find_path_to_course(G: nx.DiGraph, target: str) -> dict:
    if target not in G:
        available = sorted(G.nodes())
        raise ValueError(
            f"Course '{target}' not found in graph.\n"
            f"Available courses: {', '.join(available[:20])}"
            + ("..." if len(available) > 20 else "")
        )

    ancestors = nx.ancestors(G, target)
    relevant_nodes = ancestors | {target}

    subgraph = G.subgraph(relevant_nodes).copy()

    path_order = topological_sort(subgraph)

    # Semester grouping
    semester_plan = topological_sort_grouped(subgraph)

    return {
        "target": target,
        "ancestors": ancestors,
        "path_order": path_order,
        "semester_plan": semester_plan,
        "subgraph": subgraph,
    }


# ── Visualization ───────────────────────────────────────────────────────────

_MANUAL_COLORS = {
    "MATH": "#4A90D9",
    "CSCI": "#E06C75",
    "PHYS": "#98C379",
    "ECSE": "#E5C07B",
    "BIOL": "#56B6C2",
    "CHEM": "#C678DD",
    "ENGR": "#D19A66",
    "MATP": "#61AFEF",
    "MANE": "#FF6B6B",
    "CIVL": "#E06C9F",
    "ARCH": "#7C8CF5",
    "ARTS": "#F5A623",
    "BMED": "#50E3C2",
    "CHME": "#9B59B6",
    "COGS": "#3498DB",
    "ECON": "#E74C3C",
    "ISYE": "#1ABC9C",
    "ITWS": "#2ECC71",
    "MGMT": "#F39C12",
    "MTLE": "#8E44AD",
    "STSO": "#D35400",
    "LGHT": "#F1C40F",
    "PHIL": "#16A085",
    "PSYC": "#C0392B",
    "COMM": "#E91E63",
    "LANG": "#27AE60",
    "LITR": "#2980B9",
    "WRIT": "#8BC34A",
    "ERTH": "#795548",
    "ENVE": "#009688",
}

# just cause
def _generate_color(prefix: str) -> str:
    import hashlib
    h = hashlib.md5(prefix.encode()).hexdigest()
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    avg = (r + g + b) / 3
    r = int(min(255, r + (r - avg) * 0.5))
    g = int(min(255, g + (g - avg) * 0.5))
    b = int(min(255, b + (b - avg) * 0.5))
    r, g, b = max(40, r), max(40, g), max(40, b)
    return f"#{r:02x}{g:02x}{b:02x}"


PREFIX_COLORS = dict(_MANUAL_COLORS)

def _get_prefix_color(prefix: str) -> str:
    if prefix not in PREFIX_COLORS:
        PREFIX_COLORS[prefix] = _generate_color(prefix)
    return PREFIX_COLORS[prefix]


DEFAULT_COLOR = "#ABB2BF"
EXTERNAL_COLOR = "#666666"
HIGHLIGHT_COLOR = "#FF6B6B"


def _get_node_color(G: nx.DiGraph, node: str, highlight: Optional[set] = None) -> str:
    if highlight and node in highlight:
        return HIGHLIGHT_COLOR
    if G.nodes[node].get("external", False):
        return EXTERNAL_COLOR
    prefix = G.nodes[node].get("prefix", "")
    return _get_prefix_color(prefix)


LAYOUT_CHOICES = [
    "semester",
    "cluster",
    "dot",
    "kamada_kawai",
    "spring",
    "shell",
    "circular",
    "spiral",
    "planar",
    "spectral",
]


def _neural_net_layout(G: nx.DiGraph) -> dict:
    generations = list(nx.topological_generations(G))
    if not generations:
        return {}

    node_layer = {}
    for layer_idx, gen in enumerate(generations):
        for node in gen:
            node_layer[node] = layer_idx

    for layer_idx, gen in enumerate(generations):
        non_leaves = [n for n in gen if G.out_degree(n) > 0]
        leaves = [n for n in gen if G.out_degree(n) == 0]

        if non_leaves and leaves:
            for node in leaves:
                node_layer[node] = layer_idx - 1  # push left (behind)

    changed = True
    while changed:
        changed = False
        for src, dst in G.edges():
            if src in node_layer and dst in node_layer:
                if node_layer[src] >= node_layer[dst]:
                    node_layer[dst] = node_layer[src] + 1
                    changed = True

    min_layer = min(node_layer.values()) if node_layer else 0
    if min_layer < 0:
        for node in node_layer:
            node_layer[node] -= min_layer

    max_layer = max(node_layer.values()) if node_layer else 0
    adjusted_layers = defaultdict(list)
    for node, layer in node_layer.items():
        adjusted_layers[layer].append(node)

    num_layers = max_layer + 1
    max_layer_size = max(len(v) for v in adjusted_layers.values()) if adjusted_layers else 1

    pos = {}

    for layer_idx in range(num_layers):
        gen_sorted = sorted(adjusted_layers.get(layer_idx, []))
        layer_size = len(gen_sorted)
        if layer_size == 0:
            continue

        x = layer_idx / max(num_layers - 1, 1)

        for node_idx, node in enumerate(gen_sorted):
            if layer_size == 1:
                y = 0.5
            else:
                y = node_idx / (layer_size - 1)
            y_offset = (max_layer_size - layer_size) / (2 * max(max_layer_size - 1, 1))
            y = y * (layer_size - 1) / max(max_layer_size - 1, 1) + y_offset

            pos[node] = (x, y)

    if pos:
        all_x = [p[0] for p in pos.values()]
        all_y = [p[1] for p in pos.values()]
        x_min, x_max = min(all_x), max(all_x)
        y_min, y_max = min(all_y), max(all_y)
        x_range = x_max - x_min if x_max != x_min else 1
        y_range = y_max - y_min if y_max != y_min else 1
        pos = {
            n: ((x - x_min) / x_range * 2 - 1,
                -((y - y_min) / y_range * 2 - 1))
            for n, (x, y) in pos.items()
        }

    return pos


def _cluster_layout(G: nx.DiGraph) -> dict:
    dept_nodes = defaultdict(list)
    for node in G.nodes():
        prefix = G.nodes[node].get("prefix", "UNKNOWN")
        dept_nodes[prefix].append(node)

    departments = sorted(dept_nodes.keys())
    n_depts = len(departments)

    if n_depts == 0:
        return {}

    meta_G = nx.Graph()
    for dept in departments:
        meta_G.add_node(dept, size=len(dept_nodes[dept]))

    for u, v in G.edges():
        u_prefix = G.nodes[u].get("prefix", "")
        v_prefix = G.nodes[v].get("prefix", "")
        if u_prefix != v_prefix:
            if meta_G.has_edge(u_prefix, v_prefix):
                meta_G[u_prefix][v_prefix]["weight"] += 1
            else:
                meta_G.add_edge(u_prefix, v_prefix, weight=1)

    if n_depts <= 1:
        dept_positions = {departments[0]: (0.0, 0.0)}
    elif n_depts == 2:
        dept_positions = {departments[0]: (-1.0, 0.0), departments[1]: (1.0, 0.0)}
    else:
        dept_positions = nx.spring_layout(
            meta_G, k=3.0, iterations=200, seed=42,
            weight="weight"
        )

    initial_pos = {}
    for dept in departments:
        cx, cy = dept_positions.get(dept, (0, 0))
        nodes = dept_nodes[dept]
        n = len(nodes)

        radius = 0.15 * math.sqrt(n) / math.sqrt(max(len(G), 1)) * 10

        for i, node in enumerate(sorted(nodes)):
            if n == 1:
                initial_pos[node] = (cx, cy)
            else:
                angle = 2 * math.pi * i / n
                initial_pos[node] = (
                    cx + radius * math.cos(angle),
                    cy + radius * math.sin(angle),
                )

    n_nodes = len(G)
    k = 1.5 / math.sqrt(max(n_nodes, 1))
    iterations = 80 if n_nodes < 300 else 40

    pos = nx.spring_layout(
        G,
        pos=initial_pos,
        k=k,
        iterations=iterations,
        seed=42,
    )

    return pos


def _get_layout(G: nx.DiGraph, layout: str = "semester") -> dict:
    layout = layout.lower()

    # ── Semester / neural network-style layout ──
    if layout == "semester":
        if nx.is_directed_acyclic_graph(G):
            pos = _neural_net_layout(G)
            return pos
        else:
            print("  Warning: graph has cycles, falling back to shell layout.")
            layout = "cluster"

    # ── Cluster layout ──
    if layout == "cluster":
        return _cluster_layout(G)

    # ── Graphviz dot layout ──
    if layout == "dot":
        try:
            from networkx.drawing.nx_agraph import graphviz_layout
            return graphviz_layout(G, prog="dot", args="-Grankdir=BT")
        except ImportError:
            print("  Warning: pygraphviz not installed, falling back to semester layout.")
            return _get_layout(G, "semester")
        except Exception as e:
            print(f"  Warning: graphviz failed ({e}), falling back to semester layout.")
            return _get_layout(G, "semester")

    # ── Kamada-Kawai ──
    if layout == "kamada_kawai":
        return nx.kamada_kawai_layout(G)

    # ── Spring ──
    if layout == "spring":
        pos = nx.spring_layout(G, k=2.5, iterations=200, seed=42)
        if nx.is_directed_acyclic_graph(G):
            for gen_idx, generation in enumerate(nx.topological_generations(G)):
                for node in generation:
                    if node in pos:
                        pos[node] = (pos[node][0], gen_idx * 1.5)
        return pos

    # ── Shell (concentric rings by course level) ──
    if layout == "shell":
        level_groups = defaultdict(list)
        for n in G.nodes():
            parts = n.split()
            if len(parts) == 2 and parts[1].isdigit():
                level = int(parts[1][0])
            else:
                level = 0
            level_groups[level].append(n)
        shells = [level_groups[k] for k in sorted(level_groups.keys())]
        return nx.shell_layout(G, nlist=shells)

    # ── Circular ──
    if layout == "circular":
        return nx.circular_layout(G)

    # ── Spiral ──
    if layout == "spiral":
        return nx.spiral_layout(G)

    # ── Planar ──
    if layout == "planar":
        try:
            return nx.planar_layout(G)
        except nx.NetworkXException:
            print("  Warning: graph is not planar, falling back to kamada_kawai.")
            return nx.kamada_kawai_layout(G)

    # ── Spectral ──
    if layout == "spectral":
        return nx.spectral_layout(G)

    # Unknown layout fall back to semester
    print(f"  Warning: unknown layout '{layout}', using semester.")
    return _get_layout(G, "semester")


def visualize_graph(
    G: nx.DiGraph,
    title: str = "Course Prerequisite Graph",
    highlight_nodes: Optional[set] = None,
    output_path: Optional[str] = None,
    figsize: tuple = None,
    layout: str = "semester",
):

    if len(G) == 0:
        print("Graph is empty — nothing to visualize.")
        return

    n_nodes = G.number_of_nodes()

    if n_nodes > 200 and not output_path:
        print(f"  Warning: {n_nodes} nodes is very large for matplotlib's interactive window.")
        print(f"  Consider using --interactive for a smooth experience, or --save to export a static image.")

    if n_nodes <= 20:
        node_size_primary = 600
        node_size_external = 350
        font_size = 7
        edge_width = 1.5
        arrow_size = 15
        edge_alpha = 0.6
        if figsize is None:
            figsize = (16, 10)
    elif n_nodes <= 80:
        node_size_primary = 350
        node_size_external = 200
        font_size = 5
        edge_width = 1.0
        arrow_size = 10
        edge_alpha = 0.4
        if figsize is None:
            figsize = (24, 14)
    elif n_nodes <= 250:
        node_size_primary = 120
        node_size_external = 70
        font_size = 3.5
        edge_width = 0.5
        arrow_size = 6
        edge_alpha = 0.25
        if figsize is None:
            figsize = (36, 20)
    else:
        node_size_primary = 40
        node_size_external = 20
        font_size = 0
        edge_width = 0.3
        arrow_size = 4
        edge_alpha = 0.15
        if figsize is None:
            figsize = (48, 30)

    fig, ax = plt.subplots(1, 1, figsize=figsize)
    ax.set_title(title, fontsize=16, fontweight="bold", pad=20)

    pos = _get_layout(G, layout=layout)
    is_cluster = layout == "cluster"

    node_colors = [_get_node_color(G, n, highlight_nodes) for n in G.nodes()]

    if is_cluster:
        max_deg = max((G.degree(n) for n in G.nodes()), default=1) or 1
        node_sizes = []
        for n in G.nodes():
            deg = G.degree(n)
            base = node_size_external if G.nodes[n].get("external", False) else node_size_primary
            scale = 0.4 + 0.6 * (deg / max_deg)
            node_sizes.append(base * scale * 2.5)
    else:
        node_sizes = [
            node_size_primary if not G.nodes[n].get("external", False) else node_size_external
            for n in G.nodes()
        ]

    if is_cluster:
        import matplotlib.colors as mcolors
        edge_colors = []
        for u, v in G.edges():
            prefix = G.nodes[u].get("prefix", "")
            hex_color = _get_prefix_color(prefix)
            rgb = mcolors.hex2color(hex_color)
            edge_colors.append((*rgb, edge_alpha))

        nx.draw_networkx_edges(
            G, pos, ax=ax,
            edge_color=edge_colors,
            arrows=False,
            width=edge_width,
        )
    else:
        nx.draw_networkx_edges(
            G, pos, ax=ax,
            edge_color="#555555",
            arrows=True,
            arrowsize=arrow_size,
            arrowstyle="-|>",
            connectionstyle="arc3,rad=0.05",
            alpha=edge_alpha,
            width=edge_width,
        )

    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=node_colors,
        node_size=node_sizes,
        edgecolors="#333333",
        linewidths=0.3 if is_cluster else (0.5 if n_nodes > 80 else 1.0),
        alpha=0.9,
    )

    if font_size > 0:
        labels = {}
        for n in G.nodes():
            parts = n.split()
            if len(parts) == 2:
                if n_nodes > 80:
                    labels[n] = parts[1]
                else:
                    labels[n] = f"{parts[0]}\n{parts[1]}"
            else:
                labels[n] = n

        nx.draw_networkx_labels(
            G, pos, labels, ax=ax,
            font_size=font_size,
            font_weight="bold",
            font_color="white",
        )

    seen_prefixes = set()
    legend_handles = []
    for n in G.nodes():
        prefix = G.nodes[n].get("prefix", "")
        if prefix and prefix not in seen_prefixes:
            seen_prefixes.add(prefix)
            color = _get_prefix_color(prefix)
            legend_handles.append(
                mpatches.Patch(color=color, label=prefix)
            )
    if any(G.nodes[n].get("external", False) for n in G.nodes()):
        legend_handles.append(
            mpatches.Patch(color=EXTERNAL_COLOR, label="External dept")
        )

    if legend_handles:
        ax.legend(handles=legend_handles, loc="upper left", fontsize=9)

    ax.set_axis_off()
    plt.tight_layout()

    if output_path:
        dpi = 150 if n_nodes <= 80 else 100 if n_nodes <= 250 else 72
        plt.savefig(output_path, dpi=dpi, bbox_inches="tight")
        print(f"  Saved visualization to {output_path} ({n_nodes} nodes, {figsize[0]}x{figsize[1]} @ {dpi}dpi)")
    else:
        plt.show()

    plt.close()


def visualize_interactive(
    G: nx.DiGraph,
    title: str = "Course Prerequisite Graph",
    highlight_nodes: Optional[set] = None,
    output_path: str = "course_graph.html",
    layout: str = "semester",
):
    try:
        from pyvis.network import Network
    except ImportError:
        print("  Error: pyvis is not installed. Install it with:")
        print("    pip install pyvis")
        print("  Falling back to matplotlib.")
        visualize_graph(G, title=title, highlight_nodes=highlight_nodes, layout=layout)
        return

    # Create pyvis network
    net = Network(
        height="100vh",
        width="100%",
        directed=True,
        heading="",
        bgcolor="#1e1e1e",
        font_color="#ffffff",
    )

    pos = _get_layout(G, layout=layout)

    n_nodes = G.number_of_nodes()
    is_cluster = layout == "cluster"

    if n_nodes <= 20:
        scale_x, scale_y = 800, 500
        node_size_primary, node_size_external = 25, 16
        font_size = 14
        edge_width = 2
        show_labels = True
    elif n_nodes <= 80:
        scale_x, scale_y = 1200, 800
        node_size_primary, node_size_external = 18, 12
        font_size = 11
        edge_width = 1.5
        show_labels = True
    elif n_nodes <= 250:
        scale_x, scale_y = 2500, 1800
        node_size_primary, node_size_external = 12, 8
        font_size = 8
        edge_width = 0.8
        show_labels = True
    else:
        scale_x, scale_y = 4000, 3000
        node_size_primary, node_size_external = 8, 5
        font_size = 0
        edge_width = 0.3
        show_labels = False

    if is_cluster:
        arrows_enabled = "false" if is_cluster else "true"
        edge_inherit = "true" if is_cluster else "false"
        net.set_options("""
        {
            "physics": {
                "enabled": true,
                "barnesHut": {
                    "gravitationalConstant": -8000,
                    "centralGravity": 0.3,
                    "springLength": 120,
                    "springConstant": 0.02,
                    "damping": 0.4,
                    "avoidOverlap": 1.0
                },
                "stabilization": {
                    "enabled": true,
                    "iterations": 300,
                    "updateInterval": 25,
                    "fit": true
                }
            },
            "edges": {
                "arrows": { "to": { "enabled": """ + arrows_enabled + """, "scaleFactor": 0.4 } },
                "color": { "inherit": """ + edge_inherit + """ },
                "smooth": { "type": "continuous" },
                "width": """ + str(edge_width) + """
            },
            "interaction": {
                "hover": true,
                "navigationButtons": true,
                "keyboard": true,
                "dragNodes": true,
                "zoomView": true,
                "tooltipDelay": 100
            }
        }
        """)
    else:
        net.set_options("""
        {
            "physics": { "enabled": false },
            "edges": {
                "arrows": { "to": { "enabled": true, "scaleFactor": 0.5 } },
                "color": { "color": "#555555", "highlight": "#ffffff" },
                "smooth": { "type": "cubicBezier" },
                "width": """ + str(edge_width) + """
            },
            "interaction": {
                "hover": true,
                "navigationButtons": true,
                "keyboard": true,
                "dragNodes": true,
                "zoomView": true
            }
        }
        """)

    max_deg = max((G.degree(n) for n in G.nodes()), default=1) or 1

    for node in G.nodes():
        data = G.nodes[node]
        prefix = data.get("prefix", "")
        node_title = data.get("title", "")
        credit = data.get("credit_hours", "")
        is_external = data.get("external", False)

        if highlight_nodes and node in highlight_nodes:
            color = HIGHLIGHT_COLOR
        elif is_external:
            color = EXTERNAL_COLOR
        else:
            color = _get_prefix_color(prefix)

        if is_cluster:
            deg = G.degree(node)
            base = node_size_external if is_external else node_size_primary
            scale = 0.5 + 0.5 * (deg / max_deg)
            size = base * scale * 2.5
        else:
            size = node_size_primary if not is_external else node_size_external

        tooltip_lines = [f"<b>{node}</b>"]
        if node_title:
            tooltip_lines.append(node_title)
        if credit:
            tooltip_lines.append(f"Credits: {credit}")
        if is_external:
            tooltip_lines.append("<i>(not in scraped data)</i>")

        prereqs = list(G.predecessors(node))
        if prereqs:
            tooltip_lines.append(f"Prereqs: {', '.join(prereqs)}")

        dependents = list(G.successors(node))
        if dependents:
            tooltip_lines.append(f"Required by: {', '.join(dependents)}")

        tooltip = "<br>".join(tooltip_lines)

        nx_pos = pos.get(node, (0, 0))
        px_x = nx_pos[0] * scale_x
        px_y = nx_pos[1] * scale_y

        if show_labels:
            label = node if n_nodes <= 80 else node.split()[-1] if " " in node else node
        else:
            label = " "

        net.add_node(
            node,
            label=label,
            title=tooltip,
            color=color,
            size=size,
            x=px_x,
            y=px_y,
            font={"color": "#ffffff" if show_labels else "transparent",
                  "size": font_size if show_labels else 1,
                  "face": "mono"},
            borderWidth=1 if n_nodes > 80 else 2,
            borderWidthSelected=3,
        )

    for src, dst in G.edges():
        if is_cluster:
            src_prefix = G.nodes[src].get("prefix", "")
            net.add_edge(src, dst, color=_get_prefix_color(src_prefix))
        else:
            net.add_edge(src, dst)

    net.write_html(output_path)

    with open(output_path, "r", encoding="utf-8") as f:
        html = f.read()

    fullscreen_css = """
    <style>
        html, body { margin: 0; padding: 0; overflow: hidden; width: 100%; height: 100%; }
        #mynetwork { width: 100vw !important; height: 100vh !important; border: none !important; }
        .card { border: none !important; }
        h1, h2, center { display: none !important; }
    </style>
    <title>""" + title + """</title>
    """
    html = html.replace("<head>", "<head>" + fullscreen_css, 1)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved interactive graph to {output_path}")
    print(f"  Open in your browser for GPU-accelerated pan/zoom.")


# ── Reporting ───────────────────────────────────────────────────────────────

def print_graph_stats(G: nx.DiGraph):
    print(f"\n{'='*50}")
    print(f"  Graph Statistics")
    print(f"{'='*50}")
    print(f"  Courses (nodes):      {G.number_of_nodes()}")
    print(f"  Prerequisites (edges): {G.number_of_edges()}")

    primary = [n for n in G.nodes() if not G.nodes[n].get("external", False)]
    external = [n for n in G.nodes() if G.nodes[n].get("external", False)]
    print(f"  Primary courses:       {len(primary)}")
    print(f"  External prereqs:      {len(external)}")

    is_dag = nx.is_directed_acyclic_graph(G)
    print(f"  Is DAG (no cycles):    {is_dag}")

    if is_dag:
        longest = nx.dag_longest_path(G)
        print(f"  Longest prereq chain:  {len(longest)} courses")
        print(f"    {' → '.join(longest)}")

    most_prereqs = sorted(G.nodes(), key=lambda n: G.in_degree(n), reverse=True)[:5]
    print(f"\n  Most prerequisites (top 5):")
    for n in most_prereqs:
        if G.in_degree(n) > 0:
            print(f"    {n}: {G.in_degree(n)} direct prereqs")

    most_depended = sorted(G.nodes(), key=lambda n: G.out_degree(n), reverse=True)[:5]
    print(f"\n  Most depended-on (top 5):")
    for n in most_depended:
        if G.out_degree(n) > 0:
            print(f"    {n}: required by {G.out_degree(n)} courses")

    missing = [n for n in G.nodes() if G.nodes[n].get("title") == "(not in catalog)"]
    if missing:
        print(f"\n  Missing prerequisites ({len(missing)} courses referenced but not in data, could be courses not available anymore):")
        for n in sorted(missing):
            dependents = list(G.successors(n))
            print(f"    {n} — needed by: {', '.join(dependents)}")
        missing_prefixes = sorted({n.split()[0] for n in missing})
        print(f"\n  Scrape these departments to resolve:")
        print(f"    python rpi_scrape.py --prefix {' '.join(missing_prefixes)}")


def print_topological_order(G: nx.DiGraph):
    try:
        semesters = topological_sort_grouped(G)
    except ValueError as e:
        print(f"\n  Error: {e}")
        return

    print(f"\n{'='*50}")
    print(f"  Semester Plan (Topological Ordering)")
    print(f"{'='*50}")
    for i, group in enumerate(semesters, 1):
        courses = sorted(group)
        print(f"\n  Semester {i}:")
        for c in courses:
            title = G.nodes[c].get("title", "")
            ext = " (external)" if G.nodes[c].get("external", False) else ""
            print(f"    {c} — {title}{ext}")


def print_path_to_target(G: nx.DiGraph, target: str):
    try:
        result = find_path_to_course(G, target)
    except ValueError as e:
        print(f"\n  Error: {e}")
        return result if 'result' in dir() else None

    print(f"\n{'='*50}")
    print(f"  Path to {target}")
    title = G.nodes[target].get("title", "")
    if title:
        print(f"  ({title})")
    print(f"{'='*50}")
    print(f"  Total courses needed: {len(result['path_order'])}")
    print(f"  Semesters required:   {len(result['semester_plan'])}")

    print(f"\n  Semester-by-semester plan:")
    for i, group in enumerate(result["semester_plan"], 1):
        courses = sorted(group)
        print(f"\n  Semester {i}:")
        for c in courses:
            title = G.nodes[c].get("title", "")
            marker = " ← TARGET" if c == target else ""
            ext = " (external)" if G.nodes[c].get("external", False) else ""
            print(f"    {c} — {title}{ext}{marker}")

    return result


def main():
    parser = argparse.ArgumentParser(description="RPI Course Prerequisite Graph")
    parser.add_argument("input", nargs="*", default=None,
                        help="Path(s) to JSON file(s) from rpi_scrape.py. "
                             "Defaults to all .json files in data_scraping/")
    parser.add_argument("--prefix", type=str, default=None,
                        help="Filter to one department (e.g. MATH)")
    parser.add_argument("--target", type=str, default=None,
                        help="Find path to a specific course (e.g. 'MATH 4100')")
    parser.add_argument("--visualize", action="store_true",
                        help="Show graph visualization")
    parser.add_argument("--save", type=str, default=None,
                        help="Save matplotlib visualization to file (e.g. graph.png)")
    parser.add_argument("--interactive", type=str, nargs="?", const="course_graph.html",
                        default=None, metavar="FILE",
                        help="Save interactive HTML graph via pyvis (default: course_graph.html). "
                             "Opens in browser with smooth GPU-accelerated pan/zoom.")
    parser.add_argument("--layout", type=str, default="semester",
                        choices=LAYOUT_CHOICES,
                        help="Graph layout algorithm (default: semester)")
    parser.add_argument("--stats", action="store_true", default=True,
                        help="Print graph statistics (default: on)")
    parser.add_argument("--semester-plan", action="store_true",
                        help="Print full semester plan")
    parser.add_argument("--break-cycles", action="store_true",
                        help="Automatically break cycles to make the graph a DAG. "
                             "Removes edges where a higher-numbered course is listed "
                             "as a prereq for a lower-numbered one.")
    args = parser.parse_args()

    import glob
    import os

    if args.input:
        input_files = args.input
    else:
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_scraping")
        input_files = sorted(glob.glob(os.path.join(data_dir, "*.json")))
        if not input_files:
            print(f"No JSON files found in {data_dir}/")
            print(f"Run the scraper first: python rpi_scrape.py --prefix MATH")
            sys.exit(1)

    courses = []
    seen_ids = set()
    for path in input_files:
        print(f"Loading {path}...")
        file_courses = load_courses(path)
        for c in file_courses:
            if c["course_id"] not in seen_ids:
                seen_ids.add(c["course_id"])
                courses.append(c)
    print(f"  Total: {len(courses)} unique courses from {len(input_files)} file(s).")

    G = build_graph(courses, prefix_filter=args.prefix)

    if not nx.is_directed_acyclic_graph(G):
        cycles = print_cycles(G)
        if args.break_cycles:
            print(f"  Breaking cycles...")
            removed = break_cycles(G)
            print(f"  Removed {len(removed)} edge(s) to make graph acyclic:")
            for src, dst in removed:
                src_title = G.nodes.get(src, {}).get("title", "") if src in G else ""
                dst_title = G.nodes.get(dst, {}).get("title", "") if dst in G else ""
                print(f"    Cut {src} ({src_title}) → {dst} ({dst_title})")
            if nx.is_directed_acyclic_graph(G):
                print(f"  Graph is now a valid DAG.")
            else:
                print(f"  Graph still has cycles — some may need manual review.")
        else:
            print(f"  Tip: run with --break-cycles to automatically resolve these.")
            print(f"  Topological sort and semester planning require a DAG.")

    if args.stats:
        print_graph_stats(G)

    if args.semester_plan:
        print_topological_order(G)

    path_result = None
    if args.target:
        path_result = print_path_to_target(G, args.target)

    if args.visualize or args.save:
        if args.target and path_result:
            visualize_graph(
                path_result["subgraph"],
                title=f"Prerequisites for {args.target}",
                highlight_nodes={args.target},
                output_path=args.save,
                layout=args.layout,
            )
        else:
            visualize_graph(
                G,
                title=f"Course Prerequisite Graph"
                      + (f" ({args.prefix.upper()})" if args.prefix else ""),
                output_path=args.save,
                layout=args.layout,
            )

    if args.interactive:
        if args.target and path_result:
            visualize_interactive(
                path_result["subgraph"],
                title=f"Prerequisites for {args.target}",
                highlight_nodes={args.target},
                output_path=args.interactive,
                layout=args.layout,
            )
        else:
            visualize_interactive(
                G,
                title=f"Course Prerequisite Graph"
                      + (f" ({args.prefix.upper()})" if args.prefix else ""),
                output_path=args.interactive,
                layout=args.layout,
            )


if __name__ == "__main__":
    main()