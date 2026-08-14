export type KetcherImageFormat = "svg" | "png";

export interface KetcherApi {
  getSmiles: () => Promise<string>;
  setMolecule: (structure: string) => Promise<void | undefined>;
  generateImage: (structure: string, options: { outputFormat: KetcherImageFormat; backgroundColor?: string }) => Promise<Blob>;
}

export type ImageCopyResult = "svg" | "png";

function clipboardItem(mime: string, image: Blob): ClipboardItem {
  if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write) {
    throw new Error("このブラウザは画像クリップボードに対応していません");
  }
  return new ClipboardItem({ [mime]: image });
}

/** Writes a real image object, never a text-only success fallback. */
export async function copyKetcherImage(api: KetcherApi): Promise<ImageCopyResult> {
  const structure = await api.getSmiles();
  if (!structure) throw new Error("構造式エディタにコピーできる構造がありません");

  try {
    const svg = await api.generateImage(structure, { outputFormat: "svg", backgroundColor: "#fffdf7" });
    await navigator.clipboard.write([clipboardItem("image/svg+xml", svg)]);
    return "svg";
  } catch (svgError) {
    try {
      const png = await api.generateImage(structure, { outputFormat: "png", backgroundColor: "#fffdf7" });
      await navigator.clipboard.write([clipboardItem("image/png", png)]);
      return "png";
    } catch {
      const reason = svgError instanceof Error ? svgError.message : "画像の生成またはクリップボード書き込みに失敗しました";
      throw new Error(`${reason}。ブラウザのクリップボード権限を許可し、対応ブラウザで再試行してください。`);
    }
  }
}
