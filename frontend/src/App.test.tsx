import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ketcherMock = vi.hoisted(() => ({ getSmiles: vi.fn().mockResolvedValue("CCO>>CC=O"), copyImage: vi.fn().mockResolvedValue("svg") }));

vi.mock("./KetcherEditor", async () => {
  const React = await import("react");
  type Props = { value: string; onImport: (value: string) => void | Promise<void>; label: string; compact?: boolean };
  type Handle = { importDrawnStructure: () => Promise<string>; copyImage: () => Promise<"svg" | "png"> };
  const KetcherEditor = React.forwardRef<Handle, Props>(function MockKetcher({ label, onImport }, ref) {
    React.useImperativeHandle(ref, () => ({ importDrawnStructure: async () => { const value = await ketcherMock.getSmiles(); await onImport(value); return value; }, copyImage: ketcherMock.copyImage }));
    return <div data-testid={`ketcher-${label}`}><button type="button" onClick={() => void ketcherMock.getSmiles().then(onImport).catch(() => undefined)}>描画内容を取り込む</button></div>;
  });
  return { KetcherEditor };
});

import { App } from "./App";

const validation = { validation_mode: "FULL", representation_status: "PASS", structure_status: "WARNING", element_balance_status: "WARNING", charge_balance_status: "PASS", mapping_status: "NOT_EVALUABLE", bond_change_status: "INFO", bond_change_summary: "C–O bond formed", element_difference: { H: "Product side: -2" }, warnings: ["Atom mapping is incomplete"], validator_version: "1", validated_at: "2026-08-14T00:00:00Z" };
const reaction = { id: 7, name: "テスト反応", reaction_smiles: "CCO>>CC=O", editor_structure_data: "CCO>>CC=O", components: [{ role: "REACTANT", coefficient: "1", structure: "CCO", display_name: "ethanol" }, { role: "PRODUCT", coefficient: "1", structure: "CC=O", display_name: "acetaldehyde" }], tags: ["酸化"], reagents_text: "Cu", process_text: "室温", notes: "memo", warning_reason: "", validation_mode: "FULL", validation, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:00Z" };
const parsed = { ...reaction, id: undefined, validation_mode: undefined, validation: undefined, created_at: undefined, updated_at: undefined };
function json(body: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })); }

describe("reaction library workflow", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal("fetch", vi.fn()); vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { callback(0); return 1; }); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("shows the empty editor and permits keyboard component editing", async () => {
    const user = userEvent.setup(); render(<App />);
    expect(screen.getByRole("heading", { name: "新しい反応を記す" })).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("例: 酢酸エチルの加水分解"), "試験反応");
    expect(screen.getByDisplayValue("試験反応")).toBeInTheDocument();
    const add = screen.getByRole("button", { name: /成分を追加/ }); add.focus(); await user.keyboard("{Enter}");
    expect(screen.getByLabelText("3番目の係数")).toBeInTheDocument();
  });

  it("asks before discarding a dirty Draft from the brand entry point", async () => {
    const user = userEvent.setup(); const confirm = vi.fn().mockReturnValue(false); vi.stubGlobal("confirm", confirm); render(<App />);
    await user.type(screen.getByPlaceholderText("例: 酢酸エチルの加水分解"), "残すDraft"); await user.click(screen.getByRole("link", { name: /反応台帳/ }));
    expect(confirm).toHaveBeenCalled(); expect(screen.getByDisplayValue("残すDraft")).toBeInTheDocument();
  });

  it("keeps import source visible after a parse error", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json({ detail: "invalid RXN" }, 422)); render(<App />);
    await user.click(within(screen.getByRole("navigation")).getByRole("button", { name: /Import/ }));
    const source = screen.getByLabelText("原文"); await user.type(source, "not a reaction"); await user.click(screen.getByRole("button", { name: /Draft に変換する/ }));
    expect(await screen.findByText(/形式を解釈できませんでした/)).toBeInTheDocument(); expect(source).toHaveValue("not a reaction");
  });

  it("normalizes a Ketcher reaction through parse before validation while retaining metadata", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json({ draft: parsed })).mockResolvedValueOnce(await json(validation)); render(<App />);
    await user.type(screen.getByPlaceholderText("例: 酢酸エチルの加水分解"), "残す名称"); await user.type(screen.getByPlaceholderText("例: エステル, 加水分解"), "残すタグ");
    await user.click(within(screen.getByTestId("ketcher-反応")).getByRole("button", { name: "描画内容を取り込む" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/reactions/parse", expect.objectContaining({ method: "POST" })));
    expect(screen.getByDisplayValue("残す名称")).toBeInTheDocument(); expect(screen.getByDisplayValue("CCO")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Validation へ進む/ }));
    await screen.findByText("Atom mapping is incomplete");
    const validationRequest = vi.mocked(fetch).mock.calls[1][1] as RequestInit;
    expect(JSON.parse(validationRequest.body as string).components).toEqual(parsed.components);
  });

  it("displays warnings and reloads the library after registration", async () => {
    const user = userEvent.setup(); const confirm = vi.fn().mockReturnValue(false); vi.stubGlobal("confirm", confirm); vi.mocked(fetch).mockResolvedValueOnce(await json(validation)).mockResolvedValueOnce(await json(reaction, 201)).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })); render(<App />);
    await user.click(screen.getByRole("button", { name: /Validation へ進む/ })); await screen.findByText("Atom mapping is incomplete"); await user.click(screen.getByRole("button", { name: "この内容で登録" }));
    expect(await screen.findByText("テスト反応")).toBeInTheDocument(); expect(vi.mocked(fetch).mock.calls.at(-1)?.[0]).toBe("/api/reactions"); await user.click(screen.getByRole("button", { name: /新規反応/ })); expect(confirm).not.toHaveBeenCalled();
  });

  it("sends independent full-text, reagent, and structural search fields as intentional AND conditions", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })); render(<App />);
    await user.click(within(screen.getByRole("navigation")).getByRole("button", { name: /Library/ })); await screen.findByText("テスト反応");
    await user.type(screen.getByPlaceholderText("名称、工程、メモ"), "酸化"); await user.type(screen.getByPlaceholderText("例: Cu, ethanol"), "Cu"); await user.type(screen.getByPlaceholderText("例: CCO"), "CCO"); await user.selectOptions(screen.getByLabelText("構造分子の対象"), "reactant");
    fireEvent.submit(screen.getByRole("button", { name: "検索" }).closest("form")!);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    const init = vi.mocked(fetch).mock.calls[1][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toMatchObject({ query: "酸化", reagent: "Cu", reactant: "CCO" });
    expect(JSON.parse(init.body as string).product).toBeUndefined();
  });

  it("requires a structural search target instead of silently dropping a SMILES filter", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })); render(<App />);
    await user.click(within(screen.getByRole("navigation")).getByRole("button", { name: /Library/ })); await screen.findByText("テスト反応");
    await user.type(screen.getByPlaceholderText("例: CCO"), "CCO"); fireEvent.submit(screen.getByRole("button", { name: "検索" }).closest("form")!);
    expect(await screen.findByRole("status")).toHaveTextContent("対象を「反応物」または「生成物」から選択"); expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("uses the backend SVG preview and only exposes text after image failure", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })); render(<App />);
    await user.click(within(screen.getByRole("navigation")).getByRole("button", { name: /Library/ })); const image = await screen.findByRole("img", { name: "テスト反応の構造式プレビュー" });
    expect(image).toHaveAttribute("loading", "lazy"); expect(image).toHaveAttribute("src", "/api/reactions/7/structure.svg"); fireEvent.error(image);
    expect(await screen.findByText("構造式プレビューを読み込めませんでした。", { exact: false })).toBeInTheDocument(); expect(screen.queryByRole("img", { name: "テスト反応の構造式プレビュー" })).not.toBeInTheDocument();
  });

  it("does not warn for an unchanged loaded record but warns after an edit", async () => {
    const user = userEvent.setup(); const confirm = vi.fn().mockReturnValue(false); vi.stubGlobal("confirm", confirm); vi.mocked(fetch).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })); render(<App />);
    await user.click(within(screen.getByRole("navigation")).getByRole("button", { name: /Library/ })); await screen.findByText("テスト反応"); await user.click(screen.getByRole("button", { name: "編集" })); await user.click(screen.getByRole("link", { name: /反応台帳/ }));
    expect(confirm).not.toHaveBeenCalled(); await user.type(screen.getByPlaceholderText("例: 酢酸エチルの加水分解"), "変更"); await user.click(screen.getByRole("link", { name: /反応台帳/ })); expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("imports a drawn substructure once before searching its selected target", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json({ items: [], total: 0 })).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })); render(<App />);
    await user.click(within(screen.getByRole("navigation")).getByRole("button", { name: /Library/ })); await screen.findByText("まだ反応がありません"); await user.click(screen.getByText("Ketcher で部分構造を描いて検索する"));
    await user.click(within(screen.getByTestId("ketcher-部分構造検索")).getByRole("button", { name: "描画内容を取り込む" })); await user.selectOptions(screen.getByLabelText("部分構造検索の対象"), "PRODUCT"); await user.click(screen.getByRole("button", { name: "部分構造を検索" }));
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith("/api/search/substructure", expect.objectContaining({ method: "POST" }))); expect(await screen.findByText("テスト反応")).toBeInTheDocument();
  });

  it("restores a selected backup file with two confirmations and reloads the list", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json({ items: [], total: 0 })).mockResolvedValueOnce(await json({ restored: true, schema_version: "1" })).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })); render(<App />);
    await user.click(within(screen.getByRole("navigation")).getByRole("button", { name: /Library/ })); await screen.findByText("まだ反応がありません");
    const file = new File(["SQLite format 3\0"], "reaction-library.sqlite3", { type: "application/vnd.sqlite3" });
    await user.upload(screen.getByLabelText("復元バックアップファイル"), file); await user.click(screen.getByRole("button", { name: "ファイルから復元" })); await user.click(screen.getByRole("button", { name: "このファイルで本当に復元する" }));
    expect(await screen.findByText("テスト反応")).toBeInTheDocument(); expect(vi.mocked(fetch).mock.calls[1][0]).toBe("/api/restore/upload"); const restoreInit = vi.mocked(fetch).mock.calls[1][1] as RequestInit; expect(restoreInit.body).toBeInstanceOf(FormData); expect((restoreInit.body as FormData).get("confirmation_token")).toBe("RESTORE_LIBRARY"); expect((restoreInit.body as FormData).get("backup_file")).toBe(file);
  });

  it("traps delete dialog focus, closes on Escape, and restores the delete trigger", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })); render(<App />);
    await user.click(within(screen.getByRole("navigation")).getByRole("button", { name: /Library/ })); await screen.findByText("テスト反応"); const trigger = screen.getByRole("button", { name: "削除" }); await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "この反応を削除しますか？" })).toBeInTheDocument(); expect(screen.getByRole("button", { name: "キャンセル" })).toHaveFocus(); await user.keyboard("{Tab}"); expect(screen.getByRole("button", { name: "削除する" })).toHaveFocus(); await user.keyboard("{Tab}"); expect(screen.getByRole("button", { name: "キャンセル" })).toHaveFocus(); await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(trigger).toHaveFocus();
  });
});
