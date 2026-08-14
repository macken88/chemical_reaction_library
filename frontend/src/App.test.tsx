import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const validation = { validation_mode: "FULL", representation_status: "PASS", structure_status: "WARNING", element_balance_status: "WARNING", charge_balance_status: "PASS", mapping_status: "NOT_EVALUABLE", bond_change_status: "INFO", bond_change_summary: "C–O bond formed", element_difference: { H: "Product side: -2" }, warnings: ["Atom mapping is incomplete"], validator_version: "1", validated_at: "2026-08-14T00:00:00Z" };
const reaction = { id: 7, name: "テスト反応", reaction_smiles: "CCO>>CC=O", editor_structure_data: "CCO>>CC=O", components: [{ role: "REACTANT", coefficient: "1", structure: "CCO", display_name: "ethanol" }, { role: "PRODUCT", coefficient: "1", structure: "CC=O", display_name: "acetaldehyde" }], tags: ["酸化"], reagents_text: "Cu", process_text: "室温", notes: "memo", warning_reason: "", validation_mode: "FULL", validation, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:00Z" };

function json(body: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })); }

describe("reaction library workflow", () => {
  beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("shows the empty editor and permits keyboard component editing", async () => {
    const user = userEvent.setup(); render(<App />);
    expect(screen.getByRole("heading", { name: "新しい反応を記す" })).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("例: 酢酸エチルの加水分解"), "試験反応");
    expect(screen.getByDisplayValue("試験反応")).toBeInTheDocument();
    const add = screen.getByRole("button", { name: /成分を追加/ }); add.focus(); await user.keyboard("{Enter}");
    expect(screen.getByLabelText("3番目の係数")).toBeInTheDocument();
  });

  it("keeps import source visible after a parse error", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json({ detail: "invalid RXN" }, 422)); render(<App />);
    await user.click(within(screen.getByRole("navigation")).getByRole("button", { name: /Import/ }));
    const source = screen.getByLabelText("原文"); await user.type(source, "not a reaction");
    await user.click(screen.getByRole("button", { name: /Draft に変換する/ }));
    expect(await screen.findByText(/形式を解釈できませんでした/)).toBeInTheDocument();
    expect(source).toHaveValue("not a reaction");
  });

  it("displays warnings and allows registration when representation passes", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json(validation)).mockResolvedValueOnce(await json(reaction, 201)).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })); render(<App />);
    await user.click(screen.getByRole("button", { name: /Validation へ進む/ }));
    expect(await screen.findByText("Atom mapping is incomplete")).toBeInTheDocument();
    expect(screen.getByText("Product side: -2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "この内容で登録" }));
    expect(await screen.findByText("テスト反応")).toBeInTheDocument();
  });

  it("searches, revalidates, and asks before delete", async () => {
    const user = userEvent.setup(); vi.mocked(fetch).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })).mockResolvedValueOnce(await json({ items: [reaction], total: 1 })).mockResolvedValueOnce(await json(reaction)).mockResolvedValueOnce(new Response(null, { status: 204 })).mockResolvedValueOnce(await json({ items: [], total: 0 })); render(<App />);
    await user.click(within(screen.getByRole("navigation")).getByRole("button", { name: /Library/ }));
    expect(await screen.findByText("テスト反応")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("名称、試薬、メモ"), "酸化");
    fireEvent.submit(screen.getByRole("button", { name: "検索" }).closest("form")!);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole("button", { name: "再検証" }));
    await user.click(screen.getByRole("button", { name: "削除" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "キャンセル" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
