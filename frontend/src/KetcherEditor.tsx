import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Editor } from "ketcher-react";
import "ketcher-react/dist/index.css";
import { StandaloneStructServiceProvider } from "ketcher-standalone";
import type { Ketcher } from "ketcher-core";
import { copyKetcherImage, type ImageCopyResult, type KetcherApi } from "./ketcher";

export interface KetcherEditorHandle {
  importDrawnStructure: () => Promise<string>;
  copyImage: () => Promise<ImageCopyResult>;
}

export interface KetcherEditorProps {
  value: string;
  onImport: (structure: string) => void | Promise<void>;
  label: string;
  compact?: boolean;
}

function asAdapter(ketcher: Ketcher): KetcherApi {
  return {
    getSmiles: () => ketcher.getSmiles(),
    setMolecule: (structure) => ketcher.setMolecule(structure),
    generateImage: (structure, options) => ketcher.generateImage(structure, options),
  };
}

/** Local, standalone Ketcher with an explicit drawing-to-Draft boundary. */
export const KetcherEditor = forwardRef<KetcherEditorHandle, KetcherEditorProps>(function KetcherEditor({ value, onImport, label, compact = false }, ref) {
  const provider = useMemo(() => new StandaloneStructServiceProvider(), []);
  const api = useRef<KetcherApi | null>(null);
  const lastLoaded = useRef<string | null>(null);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    if (!api.current || !value || lastLoaded.current === value) return;
    void api.current.setMolecule(value).then(() => {
      lastLoaded.current = value;
      setLoadError("");
    }).catch(() => setLoadError("Draft を Ketcher に読み込めませんでした。構造データを確認してください。"));
  }, [value, ready]);

  async function importDrawnStructure() {
    if (!api.current) throw new Error("構造式エディタを読み込み中です。少し待ってから再試行してください。");
    const structure = await api.current.getSmiles();
    if (!structure) throw new Error("Ketcher に構造がありません。構造式を描いてから取り込んでください。");
    lastLoaded.current = structure;
    try {
      await onImport(structure);
      setLoadError("");
      return structure;
    } catch (error) {
      const detail = error instanceof Error && error.message ? error.message : "描画内容を Draft に取り込めませんでした。";
      setLoadError(detail);
      throw error;
    }
  }

  useImperativeHandle(ref, () => ({
    importDrawnStructure,
    copyImage: async () => {
      if (!api.current) throw new Error("構造式エディタを読み込み中です。少し待ってから再試行してください。");
      return copyKetcherImage(api.current);
    },
  }));

  return <section className={`ketcher ${compact ? "ketcher--compact" : ""}`} aria-label={`${label} 構造式エディタ`}>
    <div className="ketcher__bar"><span>構造式エディタ / Ketcher</span><small>{ready ? "ローカル standalone" : "エディタを起動中…"}</small></div>
    <div className="ketcher__canvas">
      <Editor
        staticResourcesUrl="/"
        structServiceProvider={provider}
        errorHandler={(message) => setLoadError(`Ketcher: ${message}`)}
        onInit={(editor) => { api.current = asAdapter(editor); setReady(true); }}
        disableMacromoleculesEditor={false}
      />
    </div>
    {loadError && <p className="ketcher__error" role="status" aria-live="polite">{loadError}</p>}
    <div className="ketcher__footer"><span>描画内容は明示的に Draft へ取り込みます。</span><button className="quiet" type="button" disabled={!ready} onClick={() => void importDrawnStructure().catch(() => undefined)}>描画内容を取り込む</button></div>
  </section>;
});

/** A local Ketcher adapter is also used for SVG previews; text is only a failure fallback. */
export function KetcherSvgPreview({ structure, alt }: { structure: string; alt: string }) {
  const provider = useMemo(() => new StandaloneStructServiceProvider(), []);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");

  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  if (!structure) return <span className="reaction-preview__fallback">構造未記入</span>;
  return <div className="reaction-preview__image">
    <Editor
      staticResourcesUrl="/"
      structServiceProvider={provider}
      errorHandler={() => setError("構造式プレビューを生成できませんでした。")}
      onInit={(editor) => {
        void asAdapter(editor).generateImage(structure, { outputFormat: "svg", backgroundColor: "#f1ebdf" })
          .then((image) => { setUrl(URL.createObjectURL(image)); setError(""); })
          .catch(() => setError("構造式プレビューを生成できませんでした。"));
      }}
      disableMacromoleculesEditor={false}
    />
    {url ? <img src={url} alt={alt} /> : error ? <span className="reaction-preview__fallback">{error}<br />{structure}</span> : <span className="reaction-preview__loading">構造式を描画中…</span>}
  </div>;
}
