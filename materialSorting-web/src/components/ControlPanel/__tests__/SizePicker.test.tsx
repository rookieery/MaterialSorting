// US-017 SizePicker 单测：
//   AC#1 doc=null → fallback constants/sizes.ts:SIZES 渲染全量 chip
//   AC#1 doc 有 11 码（含 null 通用码）→ 渲染全 11 chip
//   AC#3 null 码 chip 显示「通用」（与 QtyMatrix 列头「通用」同语义）
//   AC#1 切 doc（null → 非空）→ 自动重渲染（订阅 uploadStore.doc）
//   补充：chip 勾选 → onChange 收到对应值；null chip 勾选 → onChange 收到 null
//   补充：key/id 用 sizeKey（number → String(n)，null → 'null'）—— 无 key 冲突

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode, useState } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { SizePicker, computeTotalCutPieces, effectiveDemand } from "../SizePicker";
import { SIZES } from "../../../constants/sizes";
import { useQtyStore } from "../../../store/qtyStore";
import { useUploadStore } from "../../../store/uploadStore";
import type { ParsedDoc } from "../../../types/parsed";
import type { PieceQuantityMap } from "../../../types/qty";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
});

afterEach(() => {
  if (root) {
    const r = root;
    act(() => {
      r.unmount();
    });
    root = null;
  }
  container?.remove();
  container = null;
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
});

function renderPicker(selected: (number | null)[] = [], onChange: (n: (number | null)[]) => void = () => {}) {
  act(() => {
    root!.render(
      <StrictMode>
        <SizePicker selected={selected} onChange={onChange} />
      </StrictMode>,
    );
  });
}

/** 构造 11 码母版（含 null 通用码殿后）：28..36 + null = 11。 */
function makeDoc11(): ParsedDoc {
  return {
    doc_id: "doc-11",
    filename: "M1787-11.dxf",
    sizes: [
      { size: 28, pieces: [] },
      { size: 29, pieces: [] },
      { size: 30, pieces: [] },
      { size: 31, pieces: [] },
      { size: 32, pieces: [] },
      { size: 33, pieces: [] },
      { size: 34, pieces: [] },
      { size: 35, pieces: [] },
      { size: 36, pieces: [] },
      { size: 38, pieces: [] },
      { size: null, pieces: [] },
    ],
  };
}

/**
 * 构造 3 码母版（带不同裁片数，用于总裁片数量累加测试）：
 * 28 → 2 片，29 → 3 片，30 → 1 片。pieces 内容仅需占位（总裁片数量只读 length）。
 */
function makeDocWithPieces(): ParsedDoc {
  const piece = (label: string) => ({
    label,
    name: label,
    polygon: [],
    internal_lines: [],
    notches: [],
    net_polygon: [],
    grain_line: null,
  });
  return {
    doc_id: "doc-pieces",
    filename: "M1787-pieces.dxf",
    sizes: [
      { size: 28, pieces: [piece("A"), piece("B")] },
      { size: 29, pieces: [piece("A"), piece("B"), piece("C")] },
      { size: 30, pieces: [piece("A")] },
    ],
  };
}

/**
 * US-004 配对片型 doc：28 码 A 前片(paired) + B 单排(内片)。
 * demand=1 份 → A 实际 2 物理片、B 1 物理片。
 */
function makePairedDoc(): ParsedDoc {
  const piece = (label: string, ptype: string, paired: boolean) => ({
    label,
    name: ptype,
    ptype,
    paired,
    polygon: [],
    internal_lines: [],
    notches: [],
    net_polygon: [],
    grain_line: null,
  });
  return {
    doc_id: "doc-paired",
    filename: "M1787-paired.dxf",
    sizes: [
      { size: 28, pieces: [piece("A", "前片", true), piece("B", "单排", false)] },
      { size: 30, pieces: [piece("A", "前片", true)] },
    ],
  };
}

function getChips(): HTMLInputElement[] {
  return Array.from(container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]"));
}

function getLabels(): string[] {
  return Array.from(container!.querySelectorAll<HTMLLabelElement>(".sizes .chip label")).map(
    (l) => l.textContent ?? "",
  );
}

/** 读 .sizes-total strong 的文案（总裁片数量展示）。 */
function getTotalText(): string {
  const el = container!.querySelector<HTMLElement>(".sizes-total strong");
  return el?.textContent ?? "";
}

describe("SizePicker (US-017)", () => {
  it("AC#1 doc=null → fallback SIZES 渲染全量 chip（数量=8，文案=数字）", () => {
    renderPicker();
    const chips = getChips();
    expect(chips).toHaveLength(SIZES.length);
    const values = chips.map((c) => parseInt(c.value, 10));
    expect(values).toEqual([...SIZES]);
    // 数字码文案 = String(n)
    const labels = getLabels();
    expect(labels).toEqual(SIZES.map((s) => String(s)));
  });

  it("AC#1 doc 有 11 码 → 渲染全 11 chip（数量=11，值=doc.sizes 顺序）", () => {
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    renderPicker();
    const chips = getChips();
    expect(chips).toHaveLength(11);
    // doc.sizes.map(s=>s.size) 顺序：28,29,...,36,38,null
    const keys = chips.map((c) => c.value);
    expect(keys).toEqual(["28", "29", "30", "31", "32", "33", "34", "35", "36", "38", "null"]);
  });

  it('AC#3 null 码 chip 显示「通用」（与 QtyMatrix 列头「通用」同语义）', () => {
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    renderPicker();
    const labels = getLabels();
    // 最后一个是 null 码 → 通用
    expect(labels[labels.length - 1]).toBe("通用");
    // id 规范：sz_null（不与数字码冲突）
    const nullInput = container!.querySelector<HTMLInputElement>("#sz_null");
    expect(nullInput).not.toBeNull();
    expect(nullInput!.value).toBe("null");
  });

  it("AC#1 切 doc（null → 11 码）→ SizePicker 自动重渲染（订阅 uploadStore.doc）", () => {
    // 初始 doc=null → 8 chip
    renderPicker();
    expect(getChips()).toHaveLength(SIZES.length);
    // 切到 doc 非空（11 码）→ 自动重渲染 11 chip
    act(() => {
      useUploadStore.setState({ status: "done", doc: makeDoc11() });
    });
    expect(getChips()).toHaveLength(11);
  });

  it("toggle 数字 chip → onChange 收到 [number]（按 chip 列表原顺序，不二次排序）", () => {
    // 模拟父级累积 selected（用 useState 触发 re-render，受控组件无内部 state）
    const onChange = vi.fn();
    function PassThrough() {
      const [selected, setSelected] = useState<(number | null)[]>([]);
      const handleChange = (next: (number | null)[]) => {
        onChange(next);
        setSelected(next);
      };
      return <SizePicker selected={selected} onChange={handleChange} />;
    }
    act(() => {
      root!.render(
        <StrictMode>
          <PassThrough />
        </StrictMode>,
      );
    });
    // 勾 31（index=3）→ [31]
    act(() => getChips()[3].click());
    expect(onChange).toHaveBeenLastCalledWith([31]);
    // 再勾 28（index=0）→ append 在尾部 → [31, 28]（不二次排序）
    act(() => getChips()[0].click());
    expect(onChange).toHaveBeenLastCalledWith([31, 28]);
  });

  it("toggle null chip → onChange 收到 [null]（null 能正确进 selected）", () => {
    const onChange = vi.fn();
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    renderPicker([], onChange);
    const chips = getChips();
    // 最后一个是 null chip
    const nullChip = chips[chips.length - 1];
    act(() => nullChip.click());
    expect(onChange).toHaveBeenLastCalledWith([null]);
  });

  it("selected 含 null → 对应 null chip 渲染为 checked", () => {
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    renderPicker([null]);
    const nullInput = container!.querySelector<HTMLInputElement>("#sz_null");
    expect(nullInput!.checked).toBe(true);
  });

  it("key/id 用 sizeKey —— number → String(n)，null → 'null'（无 key 冲突）", () => {
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    renderPicker();
    // 所有 chip id 唯一
    const ids = new Set(getChips().map((c) => c.id));
    expect(ids.size).toBe(11);
    // null chip id 存在
    expect(container!.querySelector("#sz_null")).not.toBeNull();
    // 28 chip id 存在
    expect(container!.querySelector("#sz_28")).not.toBeNull();
  });

  it("总裁片数量 = 所选码号裁片数之和（未配置 demand → 默认 1，实时随勾选变化）", () => {
    useUploadStore.setState({ status: "done", doc: makeDocWithPieces() });
    // quantities={}（未 hydrate）→ 未配置 demand 按 1 计，等价于裁片数之和
    // 无勾选 → 0 片
    renderPicker([]);
    expect(getTotalText()).toBe("0 片");
    // 勾 28(2 片) + 30(1 片) → 3 片
    renderPicker([28, 30]);
    expect(getTotalText()).toBe("3 片");
    // 全选 28(2) + 29(3) + 30(1) → 6 片
    renderPicker([28, 29, 30]);
    expect(getTotalText()).toBe("6 片");
    // 仅勾 29(3 片) → 3 片
    renderPicker([29]);
    expect(getTotalText()).toBe("3 片");
  });

  it("总裁片数量随勾选实时更新（toggle 驱动 selected → 重算）", () => {
    useUploadStore.setState({ status: "done", doc: makeDocWithPieces() });
    const onChange = vi.fn();
    function PassThrough() {
      const [selected, setSelected] = useState<(number | null)[]>([]);
      const handleChange = (next: (number | null)[]) => {
        onChange(next);
        setSelected(next);
      };
      return <SizePicker selected={selected} onChange={handleChange} />;
    }
    act(() => {
      root!.render(
        <StrictMode>
          <PassThrough />
        </StrictMode>,
      );
    });
    expect(getTotalText()).toBe("0 片");
    // 勾 28（index=0，2 片）→ 2 片
    act(() => getChips()[0].click());
    expect(getTotalText()).toBe("2 片");
    // 再勾 29（index=1，3 片）→ 5 片
    act(() => getChips()[1].click());
    expect(getTotalText()).toBe("5 片");
  });

  it("demand>1 → 总裁片数量按 demand 放大（每片 × demand）", () => {
    useUploadStore.setState({ status: "done", doc: makeDocWithPieces() });
    // 28 码 A 片 demand=3（其余未配置 → 1）：28 = A(3) + B(1) = 4；30 = A(1) = 1 → 合计 5
    useQtyStore.getState().setPiecePerSize("A", 28, 3);
    renderPicker([28, 30]);
    expect(getTotalText()).toBe("5 片");
  });

  it("demand=0 → 该片不计入总裁片数量（显式排除）", () => {
    useUploadStore.setState({ status: "done", doc: makeDocWithPieces() });
    // 28 码 A 片 demand=0：28 = A(0) + B(1) = 1；30 = A(1) = 1 → 合计 2
    useQtyStore.getState().setPiecePerSize("A", 28, 0);
    renderPicker([28, 30]);
    expect(getTotalText()).toBe("2 片");
  });

  it("qtyStore 变化 → 总裁片数量实时重算（订阅 quantities）", () => {
    useUploadStore.setState({ status: "done", doc: makeDocWithPieces() });
    renderPicker([28]);
    // 初始未配置 → 28 = A(1) + B(1) = 2 片
    expect(getTotalText()).toBe("2 片");
    // 改 A 片 28 码 demand=5 → 28 = A(5) + B(1) = 6 片（订阅触发重渲染）
    act(() => useQtyStore.getState().setPiecePerSize("A", 28, 5));
    expect(getTotalText()).toBe("6 片");
  });

  it("doc=null（fallback SIZES，无裁片数据）→ 总裁片数量显示「—」", () => {
    renderPicker([28, 29]);
    expect(getTotalText()).toBe("—");
  });
});

// 纯函数单测：computeTotalCutPieces / effectiveDemand（不挂 React，直接验证口径）。
describe("computeTotalCutPieces / effectiveDemand", () => {
  const doc = makeDocWithPieces(); // 28:[A,B] 29:[A,B,C] 30:[A]

  it("quantities={} → 未配置 demand=1，等价于裁片数之和", () => {
    const q: PieceQuantityMap = {};
    expect(computeTotalCutPieces(doc, [28, 30], q)).toBe(3); // (A+B) + A
    expect(computeTotalCutPieces(doc, [28, 29, 30], q)).toBe(6);
  });

  it("doc=null → null（无裁片数据）", () => {
    expect(computeTotalCutPieces(null, [28], {})).toBeNull();
  });

  it("selected 含 doc 没有的码 → 该码跳过（不计入）", () => {
    expect(computeTotalCutPieces(doc, [999], {})).toBe(0);
  });

  it("per-size demand 按 (label,size) 精确生效", () => {
    const q: PieceQuantityMap = {
      A: { perSize: { "28": 3 }, baseValue: 3 },
    };
    // 28: A(3)+B(1未配置→1)=4
    expect(computeTotalCutPieces(doc, [28], q)).toBe(4);
    // 29: A(29 未配置→1)+B(1)+C(1)=3（A 的 28 码值不影响 29 码）
    expect(computeTotalCutPieces(doc, [29], q)).toBe(3);
  });

  it("effectiveDemand：未配置 label/per-size 缺省 → 1；显式 0 → 0", () => {
    const q: PieceQuantityMap = {
      A: { perSize: { "28": 0 }, baseValue: 1 },
    };
    expect(effectiveDemand({}, "A", 28)).toBe(1); // label 未配置
    expect(effectiveDemand(q, "A", 28)).toBe(0); // 显式 0
    expect(effectiveDemand(q, "A", 29)).toBe(1); // per-size 缺省该码
    expect(effectiveDemand(q, "B", 28)).toBe(1); // B 未配置
  });
});

// US-004 物理片数口径：配对片型（paired=true）demand ×2，缺字段向后兼容 ×1。
describe("computeTotalCutPieces (US-004 物理片数口径)", () => {
  const pairedDoc = makePairedDoc(); // 28:[A 前片 paired, B 单排] 30:[A 前片 paired]

  it("paired=true → 该片 ×2（勾 28 → A 2 物理片 + B 1 物理片 = 3 片）", () => {
    expect(computeTotalCutPieces(pairedDoc, [28], {})).toBe(3);
  });

  it("勾多码 → 配对片逐码 ×2（28+30 → 3 + 2 = 5 物理片）", () => {
    expect(computeTotalCutPieces(pairedDoc, [28, 30], {})).toBe(5);
  });

  it("paired × demand 复合放大（A@28 demand=3 → 3×2=6；勾 28 → 6+1=7）", () => {
    const q: PieceQuantityMap = {
      A: { perSize: { "28": 3 }, baseValue: 3 },
    };
    expect(computeTotalCutPieces(pairedDoc, [28], q)).toBe(7);
  });

  it("paired 片 demand=0 → 0×2=0 不计入（勾 28 → B 1 片）", () => {
    const q: PieceQuantityMap = {
      A: { perSize: { "28": 0 }, baseValue: 0 },
    };
    expect(computeTotalCutPieces(pairedDoc, [28], q)).toBe(1);
  });

  it("缺 paired 字段（旧响应/测试桩）→ ×1 兜底（makeDocWithPieces 无字段）", () => {
    const legacy = makeDocWithPieces(); // 28:[A,B] 无 paired 字段
    expect(computeTotalCutPieces(legacy, [28], {})).toBe(2);
  });

  it("配对片 UI 展示：勾 28 码 →「3 片」（物理口径实时反映）", () => {
    useUploadStore.setState({ status: "done", doc: makePairedDoc() });
    renderPicker([28]);
    expect(getTotalText()).toBe("3 片");
  });
});
