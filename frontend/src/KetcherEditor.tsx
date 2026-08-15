import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
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
  const root = useRef<HTMLElement>(null);
  const lastLoaded = useRef<string | null>(null);
  const initialScrollY = useRef(typeof window === "undefined" ? 0 : window.scrollY);
  const restoredInitialFocus = useRef(false);
  const resizeStart = useRef<{ x: number; y: number; width: number; height: number } | null>(null);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [size, setSize] = useState(() => ({ width: compact ? 720 : 900, height: compact ? 330 : 420 }));

  const clampSize = (width: number, height: number) => {
    return { width: Math.min(Math.max(320, width), 1600), height: Math.min(Math.max(240, height), 900) };
  };

  useEffect(() => {
    // Ketcher observes its host in current versions; the event also covers older embeds.
    window.dispatchEvent(new Event("resize"));
  }, [size]);

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

  function restoreInitialViewport() {
    if (restoredInitialFocus.current || typeof window === "undefined") return;
    restoredInitialFocus.current = true;
    const schedule = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (callback: FrameRequestCallback) => window.setTimeout(() => callback(Date.now()), 0);
    schedule(() => {
      const active = document.activeElement;
      if (active instanceof HTMLElement && root.current?.contains(active)) active.blur();
      window.scrollTo({ top: initialScrollY.current, left: window.scrollX, behavior: "auto" });
    });
  }

  function startResize(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    if ("setPointerCapture" in event.currentTarget) event.currentTarget.setPointerCapture(event.pointerId);
    resizeStart.current = { x: event.clientX, y: event.clientY, ...size };
  }

  function resizeFromPointer(event: PointerEvent<HTMLButtonElement>) {
    if (!resizeStart.current) return;
    const start = resizeStart.current;
    setSize(clampSize(start.width + event.clientX - start.x, start.height + event.clientY - start.y));
  }

  function stopResize(event: PointerEvent<HTMLButtonElement>) {
    resizeStart.current = null;
    if ("hasPointerCapture" in event.currentTarget && event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function resizeFromKeyboard(event: KeyboardEvent<HTMLButtonElement>) {
    const step = event.shiftKey ? 40 : 20;
    const change = event.key === "ArrowLeft" ? [-step, 0] : event.key === "ArrowRight" ? [step, 0] : event.key === "ArrowUp" ? [0, -step] : event.key === "ArrowDown" ? [0, step] : null;
    if (!change) return;
    event.preventDefault();
    setSize((current) => clampSize(current.width + change[0], current.height + change[1]));
  }

  return <section ref={root} className={`ketcher ${compact ? "ketcher--compact" : ""}`} aria-label={`${label} 構造式エディタ`}>
    <div className="ketcher__viewport">
      <div className="ketcher__resizable" style={{ width: `${size.width}px` } as CSSProperties}>
        <div className="ketcher__bar"><span>構造式エディタ / Ketcher</span><small>{ready ? "ローカル standalone" : "エディタを起動中…"}</small></div>
        <div className="ketcher__canvas" style={{ height: size.height }}>
          <Editor
            staticResourcesUrl="/"
            structServiceProvider={provider}
            errorHandler={(message) => setLoadError(`Ketcher: ${message}`)}
            onInit={(editor) => { api.current = asAdapter(editor); setReady(true); restoreInitialViewport(); }}
            disableMacromoleculesEditor={false}
          />
        </div>
        <button className="ketcher__resize-handle" type="button" aria-label={`${label} の描画領域をリサイズ（幅 ${size.width}px、高さ ${size.height}px）`} aria-describedby={`ketcher-resize-help-${label}`} onPointerDown={startResize} onPointerMove={resizeFromPointer} onPointerUp={stopResize} onPointerCancel={stopResize} onKeyDown={resizeFromKeyboard}>
          <span aria-hidden="true">↘</span>
        </button>
      </div>
    </div>
    <p className="sr-only" id={`ketcher-resize-help-${label}`}>右下のハンドルをドラッグして幅と高さを調整できます。キーボードでは左右キーで幅、上下キーで高さを調整します。Shift キーで調整幅を大きくできます。</p>
    {loadError && <p className="ketcher__error" role="status" aria-live="polite">{loadError}</p>}
    <div className="ketcher__footer"><span>描画内容は明示的に Draft へ取り込みます。</span><button className="quiet" type="button" disabled={!ready} onClick={() => void importDrawnStructure().catch(() => undefined)}>描画内容を取り込む</button></div>
  </section>;
});
