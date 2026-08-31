// US-017 SizePicker 单测：
//   AC#1 doc=null → fallback constants/sizes.ts:SIZES 渲染全量 chip
//   AC#1 doc 有 11 码（含 null 通用码）→ 渲染 10 chip（null 不渲染，2026-08-31 起）
//   null 通用码不渲染 chip（sz_null 不存在）：通用片不参与求解（WS 载荷过滤 null），
//     排查入口 = 预览页 QtyMatrix「通用」行 + 解析完成 toast（useParseDxf 触发）
//   AC#1 切 doc（null → 非空）→ 自动重渲染（订阅 uploadStore.doc）
//   补充：chip 勾选 → onChange 收到对应值
//   补充：key/id 用 sizeKey（number → String(n)）—— 无 key 冲突

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

/** 占位裁片（总裁片数量只读 label，几何字段留空）。 */
function piece(label: string) {
  return {
    label,
    polygon: [],
    internal_lines: [],
    notches: [],
    net_polygon: [],
    grain_line: null,
  };
}

/**
 * 构造 3 码母版（带不同裁片数，用于总裁片数量累加测试）：
 * 28 → 2 片，29 → 3 片，30 → 1 片。pieces 内容仅需占位（总裁片数量只读 label）。
 */
function makeDocWithPieces(): ParsedDoc {
  return {
    doc_id: "doc-pieces",
    filename: "M1787-pieces.dxf",
    sizes: [
      { size: 28, pieces: [piece("g01"), piece("g02")] },
      { size: 29, pieces: [piece("g01"), piece("g02"), piece("g03")] },
      { size: 30, pieces: [piece("g01")] },
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

  it("AC#1 doc 有 11 码（含 null）→ 渲染 10 chip（null 通用码不渲染，值=doc.sizes 顺序）", () => {
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    renderPicker();
    const chips = getChips();
    // 10 个数字码 chip；null 组不渲染（通用片不参与求解，提示走 toast）
    expect(chips).toHaveLength(10);
    const keys = chips.map((c) => c.value);
    expect(keys).toEqual(["28", "29", "30", "31", "32", "33", "34", "35", "36", "38"]);
  });

  it("null 通用码不渲染 chip（无「通用」文案、无 sz_null 元素）", () => {
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    renderPicker();
    // 无「通用」文案 chip
    const labels = getLabels();
    expect(labels).not.toContain("通用");
    // 无 sz_null 元素（React key / DOM id 均不存在）
    expect(container!.querySelector("#sz_null")).toBeNull();
  });

  it("AC#1 切 doc（null → 11 码）→ SizePicker 自动重渲染（订阅 uploadStore.doc）", () => {
    // 初始 doc=null → 8 chip
    renderPicker();
    expect(getChips()).toHaveLength(SIZES.length);
    // 切到 doc 非空（11 码，含 null 不渲染）→ 自动重渲染 10 chip
    act(() => {
      useUploadStore.setState({ status: "done", doc: makeDoc11() });
    });
    expect(getChips()).toHaveLength(10);
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

  it("无 null chip 可 toggle（onChange 只可能收到 number 数组）", () => {
    const onChange = vi.fn();
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    renderPicker([], onChange);
    const chips = getChips();
    // 全部 10 个 chip 均为数字码 —— 点击任一都产出 number
    for (const chip of chips) {
      expect(chip.value).not.toBe("null");
    }
    act(() => chips[0].click());
    expect(onChange).toHaveBeenLastCalledWith([28]);
  });

  it("selected 残留 null → 不渲染 checked 的 null chip（UI 无入口，纯防御不崩）", () => {
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    // 外部直接传含 null 的 selected（正常 UI 流不可能，防御渲染不崩 + 无 null chip）
    renderPicker([28, null]);
    expect(container!.querySelector("#sz_null")).toBeNull();
    expect(container!.querySelector<HTMLInputElement>("#sz_28")!.checked).toBe(true);
  });

  it("key/id 用 sizeKey —— number → String(n)（无 key 冲突）", () => {
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    renderPicker();
    // 所有 chip id 唯一（10 个数字码）
    const ids = new Set(getChips().map((c) => c.id));
    expect(ids.size).toBe(10);
    // null chip id 不存在
    expect(container!.querySelector("#sz_null")).toBeNull();
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
    useQtyStore.getState().setPiecePerSize("g01", 28, 3);
    renderPicker([28, 30]);
    expect(getTotalText()).toBe("5 片");
  });

  it("demand=0 → 该片不计入总裁片数量（显式排除）", () => {
    useUploadStore.setState({ status: "done", doc: makeDocWithPieces() });
    // 28 码 A 片 demand=0：28 = A(0) + B(1) = 1；30 = A(1) = 1 → 合计 2
    useQtyStore.getState().setPiecePerSize("g01", 28, 0);
    renderPicker([28, 30]);
    expect(getTotalText()).toBe("2 片");
  });

  it("qtyStore 变化 → 总裁片数量实时重算（订阅 quantities）", () => {
    useUploadStore.setState({ status: "done", doc: makeDocWithPieces() });
    renderPicker([28]);
    // 初始未配置 → 28 = A(1) + B(1) = 2 片
    expect(getTotalText()).toBe("2 片");
    // 改 A 片 28 码 demand=5 → 28 = A(5) + B(1) = 6 片（订阅触发重渲染）
    act(() => useQtyStore.getState().setPiecePerSize("g01", 28, 5));
    expect(getTotalText()).toBe("6 片");
  });

  it("doc=null（fallback SIZES，无裁片数据）→ 总裁片数量显示「—」", () => {
    renderPicker([28, 29]);
    expect(getTotalText()).toBe("—");
  });
});

// 全选框（2026-08-31）：标题行 tri-state checkbox —— 勾选态纯派生（不新增状态存储），
// 部分勾选 → indeterminate 半选；点击 = 全勾⇄全清 / 部分勾选补齐全集；空 chip 列表禁用。
describe("SizePicker 全选框 (2026-08-31)", () => {
  function getSelectAll(): HTMLInputElement | null {
    return container!.querySelector<HTMLInputElement>("#sz_all");
  }

  it("默认（selected=[]）→ 全选未勾选、非半选", () => {
    renderPicker();
    const all = getSelectAll()!;
    expect(all).not.toBeNull();
    expect(all.checked).toBe(false);
    expect(all.indeterminate).toBe(false);
  });

  it("勾选态纯派生：chip 全勾 → checked；退一个 → unchecked + 半选；全空 → 非半选", () => {
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    const all10 = [28, 29, 30, 31, 32, 33, 34, 35, 36, 38];
    // 全勾 → 全选框勾选
    renderPicker(all10);
    expect(getSelectAll()!.checked).toBe(true);
    expect(getSelectAll()!.indeterminate).toBe(false);
    // 退一个（36）→ 未勾 + 半选（下方 chip 变化 → 全选框及时联动）
    renderPicker(all10.filter((s) => s !== 36));
    expect(getSelectAll()!.checked).toBe(false);
    expect(getSelectAll()!.indeterminate).toBe(true);
    // 全空 → 未勾 + 非半选
    renderPicker([]);
    expect(getSelectAll()!.checked).toBe(false);
    expect(getSelectAll()!.indeterminate).toBe(false);
  });

  it("点全选 → onChange 收到全部数字码（10 码；null 通用码不入集，与 WS/export 口径一致）", () => {
    useUploadStore.setState({ status: "done", doc: makeDoc11() });
    const onChange = vi.fn();
    renderPicker([], onChange);
    act(() => getSelectAll()!.click());
    expect(onChange).toHaveBeenLastCalledWith([28, 29, 30, 31, 32, 33, 34, 35, 36, 38]);
  });

  it("全勾态点全选 → onChange([]) 全清", () => {
    useUploadStore.setState({ status: "done", doc: makeDocWithPieces() });
    const onChange = vi.fn();
    renderPicker([28, 29, 30], onChange);
    act(() => getSelectAll()!.click());
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("部分勾选态点全选 → onChange 收到全集（补齐而非清空）", () => {
    useUploadStore.setState({ status: "done", doc: makeDocWithPieces() });
    const onChange = vi.fn();
    renderPicker([29], onChange);
    act(() => getSelectAll()!.click());
    expect(onChange).toHaveBeenLastCalledWith([28, 29, 30]);
  });

  it("chip 列表为空（母版只有 null 通用码）→ 全选禁用且未勾选", () => {
    useUploadStore.setState({
      status: "done",
      doc: { doc_id: "doc-null-only", filename: "null-only.dxf", sizes: [{ size: null, pieces: [] }] },
    });
    renderPicker();
    const all = getSelectAll()!;
    expect(all.checked).toBe(false);
    expect(all.disabled).toBe(true);
  });

  it("disabled（求解中）→ 全选框随 chip 一起冻结", () => {
    act(() => {
      root!.render(
        <StrictMode>
          <SizePicker selected={[]} onChange={() => {}} disabled />
        </StrictMode>,
      );
    });
    expect(getSelectAll()!.disabled).toBe(true);
  });

  it("端到端受控回路：勾 1 chip → 半选；点全选 → 全集且框勾上；再点 → 全清", () => {
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
    // 勾 28（index=0）→ 部分勾选 → 半选
    act(() => getChips()[0].click());
    expect(getSelectAll()!.checked).toBe(false);
    expect(getSelectAll()!.indeterminate).toBe(true);
    // 点全选 → 全集（受控回写后全选框勾上、半选消失）
    act(() => getSelectAll()!.click());
    expect(onChange).toHaveBeenLastCalledWith([28, 29, 30]);
    expect(getSelectAll()!.checked).toBe(true);
    expect(getSelectAll()!.indeterminate).toBe(false);
    // 再点 → 全清
    act(() => getSelectAll()!.click());
    expect(onChange).toHaveBeenLastCalledWith([]);
    expect(getSelectAll()!.checked).toBe(false);
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

  it("selected 残留 null 通用码 → 跳过不计（与 WS/export 过滤 null 同口径，总数不虚高）", () => {
    // null 组即使有裁片也不计（chip 已隐藏，UI 无入口；防御外部直传）
    const docWithNull: ParsedDoc = {
      doc_id: "doc-null",
      filename: "null.dxf",
      sizes: [
        { size: 28, pieces: [piece("g01"), piece("g02")] },
        { size: null, pieces: [piece("g09")] },
      ],
    };
    expect(computeTotalCutPieces(docWithNull, [28, null], {})).toBe(2);
    expect(computeTotalCutPieces(docWithNull, [null], {})).toBe(0);
  });

  it("per-size demand 按 (label,size) 精确生效", () => {
    const q: PieceQuantityMap = {
      g01: { perSize: { "28": 3 }, baseValue: 3 },
    };
    // 28: A(3)+B(1未配置→1)=4
    expect(computeTotalCutPieces(doc, [28], q)).toBe(4);
    // 29: A(29 未配置→1)+B(1)+C(1)=3（A 的 28 码值不影响 29 码）
    expect(computeTotalCutPieces(doc, [29], q)).toBe(3);
  });

  it("effectiveDemand：未配置 label/per-size 缺省 → 1；显式 0 → 0", () => {
    const q: PieceQuantityMap = {
      g01: { perSize: { "28": 0 }, baseValue: 1 },
    };
    expect(effectiveDemand({}, "g01", 28)).toBe(1); // label 未配置
    expect(effectiveDemand(q, "g01", 28)).toBe(0); // 显式 0
    expect(effectiveDemand(q, "g01", 29)).toBe(1); // per-size 缺省该码
    expect(effectiveDemand(q, "g02", 28)).toBe(1); // B 未配置
  });
});

// US-003 数量即一切口径：总裁片数量 = Σ 数量（配对 ×2 / 缺字段兜底概念已删）。
describe("computeTotalCutPieces (US-003 Σ 数量口径)", () => {
  const doc = makeDocWithPieces(); // 28:[A,B] 29:[A,B,C] 30:[A]

  it("无乘数：勾 28 → A+B = 2 片（数量即一切，一份 = 母版一个轮廓）", () => {
    expect(computeTotalCutPieces(doc, [28], {})).toBe(2);
  });

  it("勾多码逐码累加（28+30 → 2 + 1 = 3 片）", () => {
    expect(computeTotalCutPieces(doc, [28, 30], {})).toBe(3);
  });

  it("数量放大（A@28=3 → 28 码 = 3+1 = 4；勾 28 → 4 片）", () => {
    const q: PieceQuantityMap = {
      g01: { perSize: { "28": 3 }, baseValue: 3 },
    };
    expect(computeTotalCutPieces(doc, [28], q)).toBe(4);
  });

  it("数量 0 → 不计入（A@28=0 → 勾 28 → B 1 片）", () => {
    const q: PieceQuantityMap = {
      g01: { perSize: { "28": 0 }, baseValue: 0 },
    };
    expect(computeTotalCutPieces(doc, [28], q)).toBe(1);
  });

  it("UI 展示：勾 28 码 →「2 片」（Σ 口径实时反映）", () => {
    useUploadStore.setState({ status: "done", doc: makeDocWithPieces() });
    renderPicker([28]);
    expect(getTotalText()).toBe("2 片");
  });
});
