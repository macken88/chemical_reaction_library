import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { api, ApiError, emptyDraft, type ComponentDraft, type Reaction, type ReactionDraft, type SearchFilters, type Status, type ValidationResult } from "./api";
import { KetcherFrame } from "./KetcherFrame";

type View = "editor" | "import" | "validation" | "library";
const STATUS_LABEL: Record<Status, string> = { PASS: "Pass", WARNING: "Warning", FAIL: "Error", NOT_EVALUABLE: "評価対象外", INFO: "Info" };

function messageFor(error: unknown) {
  return error instanceof ApiError ? error.message : "通信に失敗しました。バックエンドが起動しているか確認してください。";
}

function StatusMark({ value }: { value: Status }) { return <span className={`status status--${value.toLowerCase()}`}>{STATUS_LABEL[value]}</span>; }

function hasValidationError(result: ValidationResult) {
  return [result.representation_status, result.structure_status, result.element_balance_status, result.charge_balance_status, result.mapping_status].includes("FAIL");
}

function ValidationPanel({ result }: { result: ValidationResult }) {
  const rows: Array<[string, Status]> = [
    ["保存表現", result.representation_status], ["構造 / 原子価", result.structure_status], ["元素収支", result.element_balance_status], ["電荷収支", result.charge_balance_status], ["Atom mapping", result.mapping_status],
  ];
  return <section className="validation-sheet" aria-live="polite">
    <header><p className="eyebrow">Validation coverage</p><h2>{result.validation_mode.replace("_", " ")}</h2><p>検証できた機械的整合性を記録しています。反応が現実に成立することを保証するものではありません。</p></header>
    <dl className="status-grid">{rows.map(([label, status]) => <div key={label}><dt>{label}</dt><dd><StatusMark value={status} /></dd></div>)}</dl>
    <div className="validation-detail"><strong>結合変化</strong><p>{result.bond_change_summary || "検出された結合変化はありません。"}</p></div>
    {Object.keys(result.element_difference).length > 0 && <table><caption>元素差分（生成物 − 反応物）</caption><tbody>{Object.entries(result.element_difference).map(([element, amount]) => <tr key={element}><th>{element}</th><td>{amount}</td></tr>)}</tbody></table>}
    {result.warnings.length > 0 && <aside className="warning-note"><strong>確認が必要な点</strong><ul>{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></aside>}
  </section>;
}

function ComponentRows({ components, setComponents }: { components: ComponentDraft[]; setComponents: (next: ComponentDraft[]) => void }) {
  function change(index: number, field: keyof ComponentDraft, value: string) { setComponents(components.map((item, i) => i === index ? { ...item, [field]: value } : item)); }
  return <section className="component-ledger"><div className="section-title"><div><p className="eyebrow">Reaction ledger</p><h2>構成成分</h2></div><button type="button" className="quiet" onClick={() => setComponents([...components, { role: "CONDITION", coefficient: "1", structure: "", display_name: "" }])}>＋ 成分を追加</button></div>
    {components.map((component, index) => <div className="component-row" key={index}>
      <span className="index">{String(index + 1).padStart(2, "0")}</span>
      <label>役割<select value={component.role} onChange={(event) => change(index, "role", event.target.value)}><option value="REACTANT">反応物</option><option value="PRODUCT">生成物</option><option value="CONDITION">条件側成分</option></select></label>
      <label>係数<input aria-label={`${index + 1}番目の係数`} value={component.coefficient} pattern="[0-9]+|n" onChange={(event) => change(index, "coefficient", event.target.value)} /></label>
      <label>名称<input value={component.display_name ?? ""} onChange={(event) => change(index, "display_name", event.target.value)} placeholder="任意" /></label>
      <label className="structure-field">構造（SMILES）<input value={component.structure} onChange={(event) => change(index, "structure", event.target.value)} placeholder="例: CCO" /></label>
      <button className="icon-button" type="button" aria-label={`${index + 1}番目の成分を削除`} onClick={() => setComponents(components.filter((_, i) => i !== index))}>×</button>
    </div>)}</section>;
}

export function App() {
  const [view, setView] = useState<View>("editor");
  const [draft, setDraft] = useState<ReactionDraft>(emptyDraft);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [library, setLibrary] = useState<Reaction[]>([]);
  const [notice, setNotice] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Reaction | null>(null);

  const go = (next: View) => { setNotice(""); setView(next); };
  const update = <K extends keyof ReactionDraft>(key: K, value: ReactionDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const reloadLibrary = async () => { setBusy(true); try { setLibrary(await api.list()); } catch (error) { setNotice(messageFor(error)); } finally { setBusy(false); } };
  useEffect(() => { if (view === "library") void reloadLibrary(); }, [view]);

  async function runValidation() {
    setBusy(true); setNotice("");
    try { setValidation(await api.validate(draft)); go("validation"); }
    catch (error) { setNotice(`検証できませんでした: ${messageFor(error)}`); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!validation) return;
    if (hasValidationError(validation)) { setNotice("Error があるため登録できません。Editor で構造表現を修正してください。"); return; }
    setBusy(true);
    try { const saved = editingId ? await api.update(editingId, draft) : await api.create(draft); setEditingId(saved.id); setNotice("反応を台帳へ保存しました。"); go("library"); }
    catch (error) { setNotice(`登録できませんでした: ${messageFor(error)}`); }
    finally { setBusy(false); }
  }
  function newDraft() { setDraft(emptyDraft()); setEditingId(null); setValidation(null); go("editor"); }
  async function copyAi() {
    const fallback = `Reaction:\n${draft.reaction_smiles || draft.editor_structure_data || "構造表現なし"}\n\nReagents / Catalysts / Conditions:\n${draft.reagents_text}\n\nProcess:\n${draft.process_text}\n\nNotes:\n${draft.notes}\n\nValidation:\n${validation ? `- Coverage: ${validation.validation_mode}\n- Structure: ${validation.structure_status}\n- Warnings: ${validation.warnings.join("; ") || "None"}` : "Not yet run"}`;
    try { const text = editingId ? (await api.aiCopy(editingId)).text : fallback; await navigator.clipboard.writeText(text); setNotice("AI 用の反応記録をコピーしました。外部AIの回答は必ず化学的に確認してください。"); } catch { setNotice("AI 用テキストをコピーできませんでした。ブラウザのクリップボード権限を確認してください。"); }
  }
  function editReaction(reaction: Reaction) { const { id, validation, validation_mode: _mode, created_at: _created, updated_at: _updated, ...next } = reaction; setDraft(next); setEditingId(id); setValidation(validation ?? null); go("editor"); }
  async function copyStructure() {
    const text = draft.reaction_smiles || draft.editor_structure_data || draft.components.map((c) => c.structure).filter(Boolean).join(".");
    if (!text) { setNotice("コピーする構造がありません。構造データまたは成分の SMILES を入力してください。"); return; }
    try { await navigator.clipboard.writeText(text); setNotice("構造データをクリップボードにコピーしました。"); } catch { setNotice("コピーできませんでした。ブラウザのクリップボード権限を確認してください。"); }
  }

  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#top" onClick={(event) => { event.preventDefault(); newDraft(); }}><span>CRL</span><strong>反応台帳</strong><small>Chemistry ledger</small></a>
      <nav aria-label="主な画面">{([ ["editor", "01", "Editor"], ["import", "02", "Import"], ["validation", "03", "Validation"], ["library", "04", "Library"] ] as Array<[View, string, string]>).map(([id, number, label]) => <button key={id} className={view === id ? "nav-item active" : "nav-item"} onClick={() => go(id)}><span>{number}</span>{label}</button>)}</nav>
      <div className="sidebar-note">機械的な構造整合性を確認するための個人用ノート。化学的な実現性は保証しません。</div>
    </aside>
    <main id="top"><header className="masthead"><div><p className="eyebrow">PERSONAL REACTION RECORD</p><h1>{view === "editor" ? (editingId ? "反応を改訂する" : "新しい反応を記す") : view === "import" ? "外部表現を取り込む" : view === "validation" ? "検証の記録を読む" : "反応ライブラリ"}</h1></div>{view !== "editor" && <button className="outline" onClick={newDraft}>＋ 新規反応</button>}</header>
      {notice && <div className="notice" role="status">{notice}<button aria-label="通知を閉じる" onClick={() => setNotice("")}>×</button></div>}
      {view === "editor" && <Editor draft={draft} update={update} onValidate={runValidation} onCopy={copyStructure} onAiCopy={copyAi} busy={busy} />}
      {view === "import" && <Import onImported={(next) => { setDraft(next); setValidation(null); setEditingId(null); go("editor"); }} report={setNotice} />}
      {view === "validation" && <section className="page-grid">{validation ? <><ValidationPanel result={validation} /><section className="decision-panel"><label>Warning を許容する理由（任意）<textarea value={draft.warning_reason} onChange={(event) => update("warning_reason", event.target.value)} placeholder="判断の背景や後で見返す注意点を残せます。" /></label><div className="action-row"><button className="outline" onClick={() => go("editor")}>← 修正へ戻る</button><button className="primary" disabled={busy || hasValidationError(validation)} onClick={() => void save()}>{busy ? "保存中…" : "この内容で登録"}</button></div></section></> : <EmptyValidation onBack={() => go("editor")} />}</section>}
      {view === "library" && <Library reactions={library} busy={busy} onEdit={editReaction} onDelete={setDeleteTarget} onRevalidate={async (id) => { try { await api.revalidate(id); await reloadLibrary(); setNotice("最新のルールで再検証しました。"); } catch (error) { setNotice(messageFor(error)); } }} onRevalidateAll={async () => { try { await api.revalidateAll(); await reloadLibrary(); setNotice("ライブラリ全体を再検証しました。"); } catch (error) { setNotice(messageFor(error)); } }} onSearch={(items) => setLibrary(items)} report={setNotice} />}
    </main>
    {deleteTarget && <ConfirmDelete reaction={deleteTarget} onCancel={() => setDeleteTarget(null)} onConfirm={async () => { try { await api.remove(deleteTarget.id); setDeleteTarget(null); await reloadLibrary(); setNotice("反応を削除しました。この操作は元に戻せません。"); } catch (error) { setNotice(messageFor(error)); } }} />}
  </div>;
}

function Editor({ draft, update, onValidate, onCopy, onAiCopy, busy }: { draft: ReactionDraft; update: <K extends keyof ReactionDraft>(key: K, value: ReactionDraft[K]) => void; onValidate: () => Promise<void>; onCopy: () => Promise<void>; onAiCopy: () => Promise<void>; busy: boolean }) {
  return <div className="editor-layout"><section className="editor-paper"><div className="section-title"><div><p className="eyebrow">Reaction draft</p><h2>構造と条件</h2></div><div className="utility-actions"><button className="quiet" onClick={() => void onCopy()}>構造式をコピー</button><button className="quiet" onClick={() => void onAiCopy()}>AI用コピー</button></div></div>
    <label className="title-field">反応名 <input value={draft.name} onChange={(event) => update("name", event.target.value)} placeholder="例: 酢酸エチルの加水分解" /></label>
    <KetcherFrame label="反応" value={draft.editor_structure_data} onChange={(value) => update("editor_structure_data", value)} />
    <label>Reaction SMILES <input value={draft.reaction_smiles} onChange={(event) => update("reaction_smiles", event.target.value)} placeholder="例: CC(=O)OCC.O&gt;&gt;CC(=O)O" /></label>
    <ComponentRows components={draft.components} setComponents={(components) => update("components", components)} />
  </section><aside className="metadata-panel"><p className="eyebrow">Annotations</p><h2>実務メモ</h2>
    <label>タグ（カンマ区切り）<input value={draft.tags.join(", ")} onChange={(event) => update("tags", event.target.value.split(",").map((tag) => tag.trim()).filter(Boolean))} placeholder="例: エステル, 加水分解" /></label>
    <label>試薬・触媒・溶媒<textarea value={draft.reagents_text} onChange={(event) => update("reagents_text", event.target.value)} /></label>
    <label>加工工程・条件<textarea value={draft.process_text} onChange={(event) => update("process_text", event.target.value)} /></label>
    <label>一般メモ<textarea value={draft.notes} onChange={(event) => update("notes", event.target.value)} /></label>
    <button className="primary full" disabled={busy} onClick={() => void onValidate()}>{busy ? "検証中…" : "Validation へ進む →"}</button>
  </aside></div>;
}

function Import({ onImported, report }: { onImported: (draft: ReactionDraft) => void; report: (message: string) => void }) {
  const [source, setSource] = useState(""); const [format, setFormat] = useState<"reaction_smiles" | "rxn">("reaction_smiles"); const [busy, setBusy] = useState(false);
  async function parse(event: FormEvent) { event.preventDefault(); if (!source.trim()) { report("Reaction SMILES または RXN の原文を入力してください。"); return; } setBusy(true); try { onImported(await api.parse(source, format)); report("取り込みました。Editor で構造とメモを確認してから検証してください。"); } catch (error) { report(`形式を解釈できませんでした。原文は保持しています。${messageFor(error)}`); } finally { setBusy(false); } }
  function fileSelected(event: ChangeEvent<HTMLInputElement>) { const file = event.target.files?.[0]; if (!file) return; void file.text().then((text) => { setSource(text); setFormat("rxn"); }); }
  return <section className="import-paper"><p className="eyebrow">Import station</p><h2>外部の反応表現を Draft に変換</h2><p>ここでは保存しません。変換後は必ず Editor で確認・修正し、共通 Validation を通します。</p><form onSubmit={(event) => void parse(event)}><fieldset><legend>入力形式</legend><label><input type="radio" checked={format === "reaction_smiles"} onChange={() => setFormat("reaction_smiles")} /> Reaction SMILES</label><label><input type="radio" checked={format === "rxn"} onChange={() => setFormat("rxn")} /> RXN file</label><input aria-label="RXN ファイルを選択" type="file" accept=".rxn,text/plain" onChange={fileSelected} /></fieldset><label>原文<textarea value={source} onChange={(event) => setSource(event.target.value)} placeholder="Reaction SMILES または RXN の内容を貼り付けます。失敗しても原文はこの欄に残ります。" /></label><button className="primary" disabled={busy}>{busy ? "変換中…" : "Draft に変換する →"}</button></form></section>;
}

function EmptyValidation({ onBack }: { onBack: () => void }) { return <section className="empty-state"><p className="eyebrow">No validation yet</p><h2>まず構造を検証します</h2><p>Editor または Import から Draft を準備してください。</p><button className="primary" onClick={onBack}>Editor へ戻る</button></section>; }

function Library({ reactions, busy, onEdit, onDelete, onRevalidate, onRevalidateAll, onSearch, report }: { reactions: Reaction[]; busy: boolean; onEdit: (reaction: Reaction) => void; onDelete: (reaction: Reaction) => void; onRevalidate: (id: number) => Promise<void>; onRevalidateAll: () => Promise<void>; onSearch: (items: Reaction[]) => void; report: (message: string) => void }) {
  const [filters, setFilters] = useState<SearchFilters>({}); const [query, setQuery] = useState(""); const [componentTarget, setComponentTarget] = useState<"" | "reactant" | "product">(""); const [substructure, setSubstructure] = useState(""); const [target, setTarget] = useState<"REACTANT" | "PRODUCT" | "BOTH">("BOTH"); const [backupToken, setBackupToken] = useState("");
  async function search(event: FormEvent) { event.preventDefault(); try { onSearch(await api.search({ ...filters, query, reactant: componentTarget === "reactant" ? query : undefined, product: componentTarget === "product" ? query : undefined })); } catch (error) { report(messageFor(error)); } }
  async function searchSubstructure() { if (!substructure.trim()) { report("Ketcher で描いた部分構造または SMILES を入力してください。"); return; } try { onSearch(await api.substructure(substructure, target)); } catch (error) { report(messageFor(error)); } }
  async function createBackup() { try { const backup = await api.backup(); setBackupToken(backup.backup_token); const anchor = document.createElement("a"); anchor.href = `/api/backup/${backup.backup_token}`; anchor.download = backup.filename; anchor.click(); report(`バックアップ「${backup.filename}」を作成・ダウンロードしました。復元トークンも入力欄に設定済みです。`); } catch (error) { report(messageFor(error)); } }
  return <section className="library-page"><div className="library-tools"><form onSubmit={(event) => void search(event)}><label>台帳を検索<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="名称、試薬、メモ" /></label><label>タグ<input value={filters.tag ?? ""} onChange={(event) => setFilters({ ...filters, tag: event.target.value })} placeholder="例: ポリマー" /></label><label>成分検索<select value={componentTarget} onChange={(event) => setComponentTarget(event.target.value as typeof componentTarget)}><option value="">指定しない</option><option value="reactant">反応物</option><option value="product">生成物</option></select></label><label>Validation<select value={filters.validation_status ?? ""} onChange={(event) => setFilters({ ...filters, validation_status: event.target.value as SearchFilters["validation_status"] })}><option value="">すべて</option><option value="PASS">Pass</option><option value="WARNING">Warning</option><option value="FAIL">Error</option><option value="NOT_EVALUABLE">評価対象外</option></select></label><button className="primary">検索</button></form><div className="substructure"><label>Ketcher 部分構造検索 <input value={substructure} onChange={(event) => setSubstructure(event.target.value)} placeholder="部分構造 SMILES" /></label><select aria-label="部分構造検索の対象" value={target} onChange={(event) => setTarget(event.target.value as typeof target)}><option value="BOTH">両方</option><option value="REACTANT">反応物</option><option value="PRODUCT">生成物</option></select><button className="outline" onClick={() => void searchSubstructure()}>部分構造を検索</button></div><div className="archive-actions"><button className="quiet" onClick={() => void createBackup()}>バックアップ</button><RestoreControl token={backupToken} onToken={setBackupToken} report={report} /><button className="quiet" onClick={() => void onRevalidateAll()}>全件を再検証</button></div></div>
    <div className="library-summary"><p className="eyebrow">{busy ? "Reading ledger…" : `${reactions.length} RECORDS`}</p><h2>保存済み反応</h2></div>{!busy && reactions.length === 0 ? <div className="empty-state"><h2>まだ反応がありません</h2><p>Editor または Import から最初の Draft を作成してください。</p></div> : <ol className="reaction-list">{reactions.map((reaction) => <li key={reaction.id}><article><div className="reaction-preview"><span>{reaction.components.filter((item) => item.role === "REACTANT").map((item) => item.structure).filter(Boolean).join(" + ") || "構造未記入"}</span><b>→</b><span>{reaction.components.filter((item) => item.role === "PRODUCT").map((item) => item.structure).filter(Boolean).join(" + ") || "構造未記入"}</span></div><div className="reaction-card"><div><p className="eyebrow">{reaction.validation_mode}</p><h3>{reaction.name || "名称未設定の反応"}</h3><p className="tags">{reaction.tags.map((tag) => <span key={tag}>#{tag}</span>)}</p><small>更新 {new Intl.DateTimeFormat("ja-JP", { dateStyle: "medium" }).format(new Date(reaction.updated_at))}</small></div><div className="card-actions"><StatusMark value={reaction.validation?.structure_status ?? "NOT_EVALUABLE"} /><button className="quiet" onClick={() => onEdit(reaction)}>編集</button><button className="quiet" onClick={() => void onRevalidate(reaction.id)}>再検証</button><button className="danger-text" onClick={() => onDelete(reaction)}>削除</button></div></div></article></li>)}</ol>}</section>;
}

function RestoreControl({ token, onToken, report }: { token: string; onToken: (token: string) => void; report: (message: string) => void }) { const [confirming, setConfirming] = useState(false); async function restore() { if (!token.trim()) { report("バックアップ作成時に発行された復元トークンを入力してください。"); return; } if (!confirming) { setConfirming(true); return; } try { await api.restore(token); report("復元しました。画面を再読み込みして台帳を確認してください。"); setConfirming(false); } catch (error) { report(messageFor(error)); } } return <span className="restore"><input aria-label="復元トークン" value={token} onChange={(event) => { onToken(event.target.value); setConfirming(false); }} placeholder="復元トークン" /><button className="quiet" onClick={() => void restore()}>{confirming ? "本当に復元する" : "復元"}</button></span>; }

function ConfirmDelete({ reaction, onCancel, onConfirm }: { reaction: Reaction; onCancel: () => void; onConfirm: () => Promise<void> }) { return <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title"><p className="eyebrow">Permanent action</p><h2 id="delete-title">この反応を削除しますか？</h2><p>「{reaction.name || "名称未設定の反応"}」と最新の Validation 記録を削除します。この操作は元に戻せません。</p><div className="action-row"><button autoFocus className="outline" onClick={onCancel}>キャンセル</button><button className="danger" onClick={() => void onConfirm()}>削除する</button></div></section></div>; }
