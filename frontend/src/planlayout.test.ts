import assert from "node:assert/strict";
import test from "node:test";
import { layout, NODE_H, pathTo } from "./planlayout.ts";
import type { TreeNode } from "./planlayout.ts";

const leaf = (id: string, kind: TreeNode["kind"] = "plan"): TreeNode => ({ id, kind, title: id });
const tree: TreeNode = {
  id: "root", kind: "root", title: "plan",
  children: [
    { id: "g1", kind: "group", title: "Required", children: [
      { id: "i1", kind: "item", title: "C S 312", children: [leaf("o1"), leaf("o2"), leaf("o3", "fallback")] },
      { id: "i2", kind: "item", title: "M 408C", children: [leaf("o4")] },
    ] },
    { id: "g2", kind: "group", title: "Like", children: [{ id: "i3", kind: "out", title: "ART 301" }] },
  ],
};

test("leaves never overlap and every node is placed once", () => {
  const { nodes } = layout(tree);
  assert.equal(nodes.length, 10);
  const leaves = nodes.filter((n) => !(n.node.children?.length)).sort((a, b) => a.y - b.y);
  for (let i = 1; i < leaves.length; i++) assert.ok(leaves[i].y >= leaves[i - 1].y + NODE_H, "leaf overlap");
});

test("a parent is centred on its first and last child", () => {
  const { nodes } = layout(tree);
  const by = new Map(nodes.map((n) => [n.node.id, n]));
  const i1 = by.get("i1")!, o1 = by.get("o1")!, o3 = by.get("o3")!;
  assert.equal(i1.y, (o1.y + o3.y) / 2);
  const g1 = by.get("g1")!;
  assert.equal(g1.y, (by.get("i1")!.y + by.get("i2")!.y) / 2);
});

test("columns advance with depth and each parent has one edge per child", () => {
  const { nodes, edges } = layout(tree);
  const by = new Map(nodes.map((n) => [n.node.id, n]));
  assert.ok(by.get("g1")!.x > by.get("root")!.x && by.get("i1")!.x > by.get("g1")!.x && by.get("o1")!.x > by.get("i1")!.x);
  assert.equal(edges.length, nodes.length - 1);
  assert.ok(edges.every((e) => e.d.startsWith("M ")));
});

test("path to a node runs back to the root", () => {
  const { nodes } = layout(tree);
  assert.deepEqual([...pathTo(nodes, "o3")].sort(), ["g1", "i1", "o3", "root"]);
});

test("a single-node tree still lays out", () => {
  const { nodes, height } = layout({ id: "r", kind: "root", title: "x" });
  assert.equal(nodes.length, 1);
  assert.ok(height > NODE_H);
});
