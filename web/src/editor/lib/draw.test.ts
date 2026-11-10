import { describe, expect, it } from "vitest";
import { emitShape, findDefinition, hasCellGrid, setCellGrid, sortSource, uniqueName, type DraftShape } from "./draw";

describe("uniqueName", () => {
  it.each([
    ["", "room", "room_1"],
    ['room "room_1" {}\nroom "room_2" {}', "room", "room_3"],
    ['room "cave_1" {}', "room", "room_1"],
    // A base with a pattern's characters is matched as written, never as a pattern.
    ['room "a.b_1" {}', "a.b", "a.b_2"],
    ['room "axb_1" {}', "a.b", "a.b_1"],
    ['room "hall (east)_1" {}', "hall (east)", "hall (east)_2"],
  ])("in %j, %s gives %s", (source, base, name) => {
    expect(uniqueName(source, base)).toBe(name);
  });
});

describe("findDefinition", () => {
  const source = 'map "m" {\n}\nroom "hall" {\n}\n  corridor "c.1" {\n}\n# room "ghost"\n';
  it.each([
    ["room", "hall", { line: 3, column: 1 }],
    ["corridor", "c.1", { line: 5, column: 3 }],
    // A name is matched as written: "c.1" is no pattern for "cx1".
    ["corridor", "cx1", null],
    ["corridor", "hall", null],
    // A declaration in a comment is none.
    ["room", "ghost", null],
  ])("%s %j is at %j", (kind, name, at) => {
    expect(findDefinition(source, kind, name)).toEqual(at);
  });
});

describe("setCellGrid", () => {
  const plain = 'map "m" {\n  size 10 x 10\n}\n';
  const gridded = 'map "m" {\n  cell_grid\n  size 10 x 10\n}\n';
  it.each([
    ["turned on", plain, true, gridded, true],
    ["left on", gridded, true, gridded, true],
    ["turned off", gridded, false, plain, false],
    ["left off", plain, false, plain, false],
    ["with no map block to put it in", 'room "a" {\n}\n', true, 'room "a" {\n}\n', false],
  ])("%s", (_case, source, on, after, has) => {
    expect(setCellGrid(source, on)).toBe(after);
    expect(hasCellGrid(after)).toBe(has);
  });
});

describe("sortSource", () => {
  it.each([
    [
      "structure first, rooms and corridors by id, a comment going with its block, a room's statements in order",
      'map "m" {\n  cell_grid\n}\n\ndoor at 1,1\n\n# the hall\nroom "b" {\n  label "B"\n\n  rect 0,0 1 x 1\n}\ncorridor "c" {\n  width 1\n}\nroom "a" {\n  rect 0,0 1 x 1\n}\n',
      'map "m" {\n  cell_grid\n}\n\nroom "a" {\n  rect 0,0 1 x 1\n}\n\n# the hall\nroom "b" {\n  rect 0,0 1 x 1\n  label "B"\n}\n\ncorridor "c" {\n  width 1\n}\n\ndoor at 1,1\n',
    ],
    [
      "ids in their numbers' order",
      'room "room_10" {\n  rect 0,0 1 x 1\n}\nroom "room_9" {\n  rect 0,0 1 x 1\n}\n',
      'room "room_9" {\n  rect 0,0 1 x 1\n}\n\nroom "room_10" {\n  rect 0,0 1 x 1\n}\n',
    ],
    [
      "a block with a statement over several lines kept as written",
      'room "b" {\n  label "B"\n  description """two\nlines"""\n}\nroom "a" {\n  rect 0,0 1 x 1\n}\n',
      'room "a" {\n  rect 0,0 1 x 1\n}\n\nroom "b" {\n  label "B"\n  description """two\nlines"""\n}\n',
    ],
    ["one declaration left alone", 'room "b" {\n  label "B"\n\n}\n', 'room "b" {\n  label "B"\n\n}\n'],
  ])("%s", (_case, source, sorted) => {
    expect(sortSource(source)).toBe(sorted);
    expect(sortSource(sorted), "sorting again changes nothing").toBe(sorted);
  });

  it("leaves a source it can't split losslessly as it is", () => {
    // Two rooms on one line under a comment: the second's comment would reach above the first, so the blocks
    // don't put the source back together, and nothing is moved.
    const source = '# header\nroom "b" { rect 0,0 1 x 1 } room "a" { rect 0,0 1 x 1 }\n';
    expect(sortSource(source)).toBe(source);
  });
});

describe("emitShape", () => {
  const taken = 'room "room_1" {\n}\ncorridor "corridor_1" {\n}\n';
  const cases: [DraftShape, string][] = [
    [{ kind: "rect", a: { x: 4, y: 3 }, b: { x: 1, y: 1.255 } }, '\nroom "room_2" {\n  rect 1,1.25 3 x 1.75\n  label "2"\n}\n'],
    [{ kind: "circle", center: { x: 0, y: 0 }, edge: { x: 3, y: 4 } }, '\nroom "room_2" {\n  circle at 0,0 radius 5\n  label "2"\n}\n'],
    [
      { kind: "polygon", pts: [{ x: 0, y: 0 }, { x: 2, y: 0 }, { x: 1, y: 1 }] },
      '\nroom "room_2" {\n  polygon (0,0) (2,0) (1,1)\n  label "2"\n}\n',
    ],
    [
      { kind: "cave", pts: [{ x: 0, y: 0 }, { x: 2, y: 0 }, { x: 1, y: 1 }] },
      '\nroom "cave_1" {\n  polygon (0,0) (2,0) (1,1)\n  line_style organic\n  label "cave_1"\n}\n',
    ],
    [
      { kind: "corridor", nodes: [{ x: 0, y: 0 }, { x: 5, y: 0 }], runs: [[0, 1]], straight: true },
      '\ncorridor "corridor_2" {\n  width 1\n  corners straight\n  node n1 at 0,0\n  node n2 at 5,0\n  run n1 to n2\n}\n',
    ],
    [
      { kind: "door", at: { x: 1, y: 2 }, connects: ["room.a", "corridor.c"], doorType: "wood", state: "closed", facing: "auto" },
      "\ndoor at 1,2 {\n  connects room.a, corridor.c\n  type wood\n  state closed\n}\n",
    ],
    [{ kind: "feature", at: { x: 1, y: 2 }, ref: "chest", region: "room.a" }, "\nfeature chest at 1,2\n"],
    [{ kind: "text", at: { x: 1, y: 2 }, content: "X" }, '\ntext "X" at 1,2\n'],
    [
      { kind: "area", pts: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }], areaKind: "water" },
      '\narea "area_1" kind water {\n  polygon (0,0) (1,0) (1,1)\n}\n',
    ],
    [{ kind: "lineFeature", pts: [{ x: 0, y: 0 }, { x: 1, y: 0 }], lineKind: "wall" }, '\nline_feature "line_1" kind wall {\n  point 0,0 point 1,0\n}\n'],
    [{ kind: "exit", at: { x: 1, y: 2 }, targetMap: "up", targetPos: { x: 3, y: 4 } }, '\nexit at 1,2 {\n  to "up" at 3,4\n}\n'],
  ];
  it.each(cases)("%j", (shape, block) => {
    expect(emitShape(taken, shape)).toBe(block);
  });
});
