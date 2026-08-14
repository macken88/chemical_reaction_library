import { useEffect, useRef, useState } from "react";

export interface KetcherAdapterProps {
  value: string;
  onChange: (value: string) => void;
  label: string;
}

/**
 * An iframe adapter for the official Ketcher standalone app. Set VITE_KETCHER_URL
 * to a locally served Ketcher build in production; a cross-origin public demo is
 * intentionally display-only because browser security prevents direct API calls.
 */
export function KetcherFrame({ value, onChange, label }: KetcherAdapterProps) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [sameOrigin, setSameOrigin] = useState(false);
  const src = import.meta.env.VITE_KETCHER_URL ?? "https://lifescience.opensource.epam.com/ketcher/index.html";

  const localEditor = () => (frame.current?.contentWindow as unknown as {
    ketcher?: { setMolecule?: (v: string) => Promise<void>; getSmiles?: () => Promise<string> };
  } | null)?.ketcher;

  useEffect(() => {
    const onLoad = () => {
      try {
        const editor = localEditor();
        setSameOrigin(Boolean(editor));
        if (value && editor?.setMolecule) void editor.setMolecule(value);
      } catch { setSameOrigin(false); }
    };
    const element = frame.current;
    element?.addEventListener("load", onLoad);
    return () => element?.removeEventListener("load", onLoad);
  }, [value]);

  async function readFromKetcher() {
    try {
      const next = await localEditor()?.getSmiles?.();
      if (!next) throw new Error("Ketcher content unavailable");
      onChange(next);
    } catch { setSameOrigin(false); }
  }

  return <section className="ketcher" aria-label={`${label} 構造式エディタ`}>
    <div className="ketcher__bar"><span>構造式エディタ / Ketcher</span><span>{sameOrigin ? <button type="button" className="quiet" onClick={() => void readFromKetcher()}>Ketcher の内容を読み込む</button> : <small>外部表示。SMILES欄から同期</small>}</span></div>
    <iframe ref={frame} title={`${label} Ketcher`} src={src} sandbox="allow-scripts allow-same-origin allow-downloads" />
    <label className="sr-only" htmlFor="editor-structure">構造データ (SMILES / molfile)</label>
    <textarea id="editor-structure" value={value} onChange={(event) => onChange(event.target.value)} placeholder="例: CCO または molfile を入力" />
  </section>;
}
