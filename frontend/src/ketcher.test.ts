import { afterEach, describe, expect, it, vi } from "vitest";
import { copyKetcherImage, type KetcherApi } from "./ketcher";

class TestClipboardItem {
  constructor(readonly items: Record<string, Blob>) {}
}

function apiWith(generateImage: KetcherApi["generateImage"]): KetcherApi {
  return { getSmiles: vi.fn().mockResolvedValue("CCO"), setMolecule: vi.fn(), generateImage };
}

describe("Ketcher image clipboard adapter", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("writes Ketcher SVG as an image clipboard item", async () => {
    const write = vi.fn().mockResolvedValue(undefined); vi.stubGlobal("ClipboardItem", TestClipboardItem); Object.assign(navigator, { clipboard: { write } });
    const generateImage = vi.fn().mockResolvedValue(new Blob(["<svg />"], { type: "image/svg+xml" }));
    await expect(copyKetcherImage(apiWith(generateImage))).resolves.toBe("svg");
    expect(generateImage).toHaveBeenCalledWith("CCO", { outputFormat: "svg" });
    expect(write).toHaveBeenCalledOnce();
    expect((write.mock.calls[0][0][0] as TestClipboardItem).items).toHaveProperty("image/svg+xml");
  });

  it("falls back to PNG only when SVG image copy fails", async () => {
    const write = vi.fn().mockRejectedValueOnce(new Error("SVG clipboard rejected")).mockResolvedValueOnce(undefined); vi.stubGlobal("ClipboardItem", TestClipboardItem); Object.assign(navigator, { clipboard: { write } });
    const generateImage = vi.fn().mockResolvedValueOnce(new Blob(["<svg />"], { type: "image/svg+xml" })).mockResolvedValueOnce(new Blob(["png"], { type: "image/png" }));
    await expect(copyKetcherImage(apiWith(generateImage))).resolves.toBe("png");
    expect(generateImage).toHaveBeenNthCalledWith(2, "CCO", { outputFormat: "png" });
    expect((write.mock.calls[1][0][0] as TestClipboardItem).items).toHaveProperty("image/png");
  });
});
