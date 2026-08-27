import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getSmiles: vi.fn().mockResolvedValue("CCO>>CC=O"),
  setMolecule: vi.fn().mockResolvedValue(undefined),
  generateImage: vi.fn(),
}));

vi.mock("ketcher-react", async () => {
  const React = await import("react");
  return { Editor: ({ onInit }: { onInit: (editor: typeof api) => void }) => { React.useEffect(() => onInit(api), [onInit]); return <div data-testid="actual-ketcher" />; } };
});
vi.mock("ketcher-react/dist/index.css", () => ({}));
vi.mock("ketcher-standalone", () => ({ StandaloneStructServiceProvider: class {} }));

import { KetcherEditor } from "./KetcherEditor";

describe("local Ketcher adapter", () => {
  beforeEach(() => { vi.spyOn(window, "scrollTo").mockImplementation(() => undefined); });
  afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("loads Draft structure into Ketcher and imports a drawn reaction explicitly", async () => {
    const imported = vi.fn(); const user = userEvent.setup();
    render(<KetcherEditor label="反応" value="CCO" onImport={imported} />);
    await waitFor(() => expect(api.setMolecule).toHaveBeenCalledWith("CCO"));
    await user.click(screen.getByRole("button", { name: "描画内容を取り込む" }));
    expect(imported).toHaveBeenCalledWith("CCO>>CC=O");
  });

  it("keeps a rejected Draft import visible in the editor status", async () => {
    const user = userEvent.setup();
    render(<KetcherEditor label="反応" value="CCO" onImport={async () => { throw new Error("反応矢印を確認してください"); }} />);
    await user.click(screen.getByRole("button", { name: "描画内容を取り込む" }));
    expect(await screen.findByRole("status")).toHaveTextContent("反応矢印を確認してください");
  });

  it("restores the viewport after Ketcher initialization so its internal autofocus does not hide the masthead", async () => {
    const scrollTo = vi.mocked(window.scrollTo); vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { callback(0); return 1; }); Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
    render(<KetcherEditor label="反応" value="" onImport={vi.fn()} />);
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: "auto" }));
  });

  it("visibly resizes the Ketcher drawing area in both directions from the corner handle", () => {
    render(<KetcherEditor label="反応" value="" onImport={vi.fn()} />);
    const editor = screen.getByLabelText("反応 構造式エディタ");
    Object.defineProperty(editor, "clientWidth", { configurable: true, value: 1400 });
    const handle = screen.getByRole("button", { name: /描画領域をリサイズ/ });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    const widened = screen.getByRole("button", { name: "反応 の描画領域をリサイズ（幅 920px、高さ 420px）" });
    expect(widened.parentElement).toHaveStyle({ width: "920px" });
    fireEvent.keyDown(widened, { key: "ArrowDown" });
    const keyboardResized = screen.getByRole("button", { name: "反応 の描画領域をリサイズ（幅 920px、高さ 440px）" });
    expect(keyboardResized.parentElement).toHaveStyle({ width: "920px" });
    fireEvent.pointerDown(keyboardResized, { pointerId: 1, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(keyboardResized, { pointerId: 1, clientX: 70, clientY: 70 });
    fireEvent.pointerUp(keyboardResized, { pointerId: 1, clientX: 70, clientY: 70 });
    const dragResized = screen.getByRole("button", { name: "反応 の描画領域をリサイズ（幅 980px、高さ 500px）" });
    expect(dragResized.parentElement).toHaveStyle({ width: "980px" });
    expect(screen.getByText(/左右キーで幅、上下キーで高さ/)).toBeInTheDocument();
  });
});
