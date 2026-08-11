// US-017 SizePicker 单测：
//   AC#1 doc=null → fallback constants/sizes.ts:SIZES 渲染全量 chip
//   AC#1 doc 有 11 码（含 null 通用码）→ 渲染全 11 chip
//   AC#3 null 码 chip 显示「通用」（与 SizeTabs NULL_SIZE_LABEL 同语义）
//   AC#1 切 doc（null → 非空）→ 自动重渲染（订阅 uploadStore.doc）
//   补充：chip 勾选 → onChange 收到对应值；null chip 勾选 → onChange 收到 null
//   补充：key/id 用 sizeKey（number → String(n)，null → 'null'）—— 无 key 冲突

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode, useState } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { SizePicker } from "../SizePicker";
import { SIZES } from "../../../constants/sizes";
import { useUploadStore } from "../../../store/uploadStore";
import type { ParsedDoc } from "../../../types/parsed";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  useUploadStore.getState().reset();
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

function getChips(): HTMLInputElement[] {
  return Array.from(container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]"));
}

function getLabels(): string[] {
  return Array.from(container!.querySelectorAll<HTMLLabelElement>(".sizes .chip label")).map(
    (l) => l.textContent ?? "",
  );
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

  it('AC#3 null 码 chip 显示「通用」（与 SizeTabs NULL_SIZE_LABEL 同语义）', () => {
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
});
