"""
Custom Topological Sorting Algorithms for Course Prerequisites
"""

import heapq
from collections import deque
from typing import Optional


# ── 1. Standard Kahn's Algorithm ────────────────────────────────────────────

def topo_sort_kahns(adj: dict[str, list[str]], in_deg: dict[str, int]) -> list[str]:
    in_degree = dict(in_deg)
    queue = deque()

    for node in in_degree:
        if in_degree[node] == 0:
            queue.append(node)

    result = []

    while queue:
        node = queue.popleft()
        result.append(node)

        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(in_degree):
        raise ValueError(
            f"Cycle detected: processed {len(result)} of {len(in_degree)} nodes. "
            f"Remaining nodes are involved in a cycle."
        )

    return result


# ── 2. Priority Topological Sort ────────────────────────────────────────────

def _compute_descendant_counts(adj: dict[str, list[str]], all_nodes: set[str], approximate: bool = False) -> dict[str, int]:
    if approximate:
        return {node: len(adj.get(node, [])) for node in all_nodes}

    reverse_adj = {n: [] for n in all_nodes}
    in_deg = {n: 0 for n in all_nodes}
    for u in adj:
        for v in adj[u]:
            reverse_adj[v].append(u)
            in_deg[u] = in_deg.get(u, 0)

    in_deg_copy = {n: 0 for n in all_nodes}
    for u in adj:
        for v in adj[u]:
            in_deg_copy[v] = in_deg_copy.get(v, 0) + 1

    topo_order = topo_sort_kahns(adj, in_deg_copy)

    descendants = {n: set() for n in all_nodes}
    for node in reversed(topo_order):
        for child in adj.get(node, []):
            descendants[node].add(child)
            descendants[node] |= descendants[child]

    return {n: len(descendants[n]) for n in all_nodes}


def topo_sort_priority(adj: dict[str, list[str]], in_deg: dict[str, int], approximate: bool = False) -> list[str]:
    all_nodes = set(in_deg.keys())
    desc_count = _compute_descendant_counts(adj, all_nodes, approximate=approximate)

    in_degree = dict(in_deg)

    # Max-heap: Python heapq is a min-heap, so negate the priority
    heap = []
    for node in in_degree:
        if in_degree[node] == 0:
            heapq.heappush(heap, (-desc_count.get(node, 0), node))

    result = []

    while heap:
        neg_priority, node = heapq.heappop(heap)
        result.append(node)

        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                heapq.heappush(heap, (-desc_count.get(neighbor, 0), neighbor))

    if len(result) != len(in_degree):
        raise ValueError(
            f"Cycle detected: processed {len(result)} of {len(in_degree)} nodes."
        )

    return result


# ── 3. Grouped Topological Sort (Semester Layers) ──────────────────────────

def topo_sort_grouped(adj: dict[str, list[str]], in_deg: dict[str, int]) -> list[list[str]]:
    all_nodes = set(in_deg.keys())

    in_degree_copy = dict(in_deg)
    desc_count = _compute_descendant_counts(adj, all_nodes, approximate=True)

    in_degree = dict(in_deg)
    generations = []

    current_gen = [n for n in in_degree if in_degree[n] == 0]

    while current_gen:
        current_gen.sort(key=lambda n: -desc_count.get(n, 0))
        generations.append(current_gen)

        next_gen = []
        for node in current_gen:
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_gen.append(neighbor)

        current_gen = next_gen

    total = sum(len(g) for g in generations)
    if total != len(in_deg):
        raise ValueError(
            f"Cycle detected: assigned {total} of {len(in_deg)} nodes to generations."
        )

    return generations


# ── Helper: extract adj/in_deg from a networkx DiGraph ──────────────────────

def graph_to_adj(G) -> tuple[dict[str, list[str]], dict[str, int]]:
    adj = {n: [] for n in G.nodes()}
    in_deg = {n: 0 for n in G.nodes()}

    for u, v in G.edges():
        adj[u].append(v)
        in_deg[v] += 1

    return adj, in_deg