import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

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

  it("generates an SVG image preview through the local Ketcher adapter", async () => {
    const originalUrl = URL.createObjectURL;
    Object.assign(URL, { createObjectURL: vi.fn().mockReturnValue("blob:preview"), revokeObjectURL: vi.fn() });
    api.generateImage.mockResolvedValue(new Blob(["<svg />"], { type: "image/svg+xml" }));
    const { KetcherSvgPreview } = await import("./KetcherEditor");
    render(<KetcherSvgPreview structure="CCO>>CC=O" alt="reaction preview" />);
    expect(await screen.findByRole("img", { name: "reaction preview" })).toHaveAttribute("src", "blob:preview");
    expect(api.generateImage).toHaveBeenCalledWith("CCO>>CC=O", { outputFormat: "svg", backgroundColor: "#f1ebdf" });
    Object.assign(URL, { createObjectURL: originalUrl });
  });
});
