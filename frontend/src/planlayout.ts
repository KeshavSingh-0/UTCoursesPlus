// Pure layout for the plan map: turns a tree into x/y positions and curved connectors. No DOM, so it can be tested.

export type TreeNode = {
  id: string;
  kind: "root" | "group" | "item" | "plan" | "fallback" | "alt" | "out" | "backup" | "bsection";
  title: string;
  sub?: string;
  sub2?: string;
  tone?: string; // group id, used for colour
  data?: unknown;
  children?: TreeNode[];
};
export type Placed = { node: TreeNode; depth: number; x: number; y: number; w: number; h: number; parent: string | null };
export type Edge = { from: string; to: string; d: string };

export const COL_X = [16, 244, 472, 744];
export const COL_W = [200, 200, 244, 272];
export const NODE_H = 64;
export const GAP_Y = 8;

export function layout(root: TreeNode): { nodes: Placed[]; edges: Edge[]; width: number; height: number } {
  const nodes: Placed[] = [];
  const edges: Edge[] = [];
  let cursor = 12;

  function place(n: TreeNode, depth: number, parent: string | null): Placed {
    const d = Math.min(depth, COL_X.length - 1);
    const kids = (n.children ?? []).map((c) => place(c, depth + 1, n.id));
    let y: number;
    if (kids.length === 0) {
      y = cursor;
      cursor += NODE_H + GAP_Y;
    } else {
      y = (kids[0].y + kids[kids.length - 1].y) / 2;
    }
    const p: Placed = { node: n, depth, x: COL_X[d], y, w: COL_W[d], h: NODE_H, parent };
    nodes.push(p);
    for (const k of kids) {
      const x1 = p.x + p.w, y1 = p.y + NODE_H / 2, x2 = k.x, y2 = k.y + NODE_H / 2;
      const dx = (x2 - x1) / 2;
      edges.push({ from: n.id, to: k.node.id, d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}` });
    }
    return p;
  }
  place(root, 0, null);
  const deepest = Math.max(...nodes.map((n) => n.depth), 0);
  const d = Math.min(deepest, COL_X.length - 1);
  return { nodes, edges, width: COL_X[d] + COL_W[d] + 24, height: cursor + 8 };
}

/** Ids from the root down to the given node, for highlighting the path. */
export function pathTo(nodes: Placed[], id: string): Set<string> {
  const byId = new Map(nodes.map((n) => [n.node.id, n]));
  const out = new Set<string>();
  let cur: string | null = id;
  while (cur) {
    out.add(cur);
    cur = byId.get(cur)?.parent ?? null;
  }
  return out;
}
