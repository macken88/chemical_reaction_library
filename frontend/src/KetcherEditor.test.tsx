import { render, screen, waitFor } from "@testing-library/react";
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
  afterEach(() => vi.clearAllMocks());

  it("loads Draft structure into Ketcher and imports a drawn reaction explicitly", async () => {
    const imported = vi.fn(); const user = userEvent.setup();
    render(<KetcherEditor label="反応" value="CCO" onImport={imported} />);
    await waitFor(() => expect(api.setMolecule).toHaveBeenCalledWith("CCO"));
    await user.click(screen.getByRole("button", { name: "描画内容を取り込む" }));
    expect(imported).toHaveBeenCalledWith("CCO>>CC=O");
  });
});
