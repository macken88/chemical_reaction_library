export type Role = "REACTANT" | "PRODUCT" | "CONDITION";
export type ValidationMode = "FULL" | "REPEAT_UNIT" | "LOCAL" | "LIMITED";
export type Status = "PASS" | "WARNING" | "FAIL" | "NOT_EVALUABLE" | "INFO";

export interface ComponentDraft {
  role: Role;
  coefficient: string;
  structure: string;
  canonical_smiles?: string | null;
  display_name?: string | null;
}

export interface ReactionDraft {
  name: string;
  reaction_smiles: string;
  editor_structure_data: string;
  components: ComponentDraft[];
  tags: string[];
  reagents_text: string;
  process_text: string;
  notes: string;
  warning_reason: string;
}

export type ImportedStructureFormat = "reaction_smiles" | "rxn";

export interface ImportedComponentName {
  role: Role;
  occurrence_index: number;
  display_name: string;
}

/** Mirrors the strict, versioned Pydantic contract for /reactions/import-json. */
export interface ReactionImportRequest {
  schema_version: 1;
  structure: { format: ImportedStructureFormat; value: string };
  component_names?: ImportedComponentName[];
  name: string;
  tags: string[];
  reagents_text: string;
  process_text: string;
  notes: string;
}

export interface ValidationResult {
  validation_mode: ValidationMode;
  representation_status: Status;
  structure_status: Status;
  element_balance_status: Status;
  charge_balance_status: Status;
  mapping_status: Status;
  bond_change_summary: string;
  bond_change_status: Status;
  element_difference: Record<string, string>;
  warnings: string[];
  validator_version?: string;
  validated_at?: string;
}

export interface Reaction extends ReactionDraft {
  id: number;
  validation_mode: ValidationMode;
  validation?: ValidationResult | null;
  created_at: string;
  updated_at: string;
}

export interface SearchFilters {
  query?: string;
  tag?: string;
  reagent?: string;
  reactant?: string;
  product?: string;
  validation_status?: Status | "";
}

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const hasFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { ...(hasFormData ? {} : { "Content-Type": "application/json" }), ...init?.headers },
  });
  if (!response.ok) {
    let detail = "サーバーが処理を完了できませんでした。入力内容または接続を確認してください。";
    try {
      const body = await response.json() as { detail?: string | Array<{ msg?: string }> };
      if (typeof body.detail === "string") detail = body.detail;
      if (Array.isArray(body.detail)) detail = body.detail.map((item) => item.msg).filter(Boolean).join("、") || detail;
    } catch { /* keep usable fallback */ }
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  parse: async (content: string, format: "reaction_smiles" | "rxn") => (await request<{ draft: ReactionDraft }>("/reactions/parse", json("POST", { content, format }))).draft,
  importJson: async (source: ReactionImportRequest) => (await request<{ draft: ReactionDraft }>("/reactions/import-json", json("POST", source))).draft,
  validate: (draft: ReactionDraft) => request<ValidationResult>("/reactions/validate", json("POST", draft)),
  create: (draft: ReactionDraft) => request<Reaction>("/reactions", json("POST", draft)),
  update: (id: number, draft: ReactionDraft) => request<Reaction>(`/reactions/${id}`, json("PUT", draft)),
  list: async () => (await request<{ items: Reaction[] }>("/reactions")).items,
  get: (id: number) => request<Reaction>(`/reactions/${id}`),
  remove: (id: number) => request<void>(`/reactions/${id}`, { method: "DELETE" }),
  revalidate: (id: number) => request<Reaction>(`/reactions/${id}/revalidate`, json("POST")),
  revalidateAll: async () => (await request<{ items: Reaction[] }>("/reactions/revalidate-all", json("POST"))).items,
  search: async (filters: SearchFilters) => (await request<{ items: Reaction[] }>("/reactions/search", json("POST", filters))).items,
  substructure: async (structure: string, target: "REACTANT" | "PRODUCT" | "BOTH") => (await request<{ items: Reaction[] }>("/search/substructure", json("POST", { structure, target }))).items,
  aiCopy: (id: number) => request<{ text: string }>(`/reactions/${id}/ai-copy`),
  backup: () => request<{ backup_token: string; filename: string; schema_version: string }>("/backup", json("POST")),
  restore: (backupToken: string) => request<{ restored: boolean; schema_version: string }>("/restore", json("POST", {
    confirmation_token: "RESTORE_LIBRARY",
    backup_token: backupToken,
  })),
  restoreUpload: (file: File) => {
    const body = new FormData();
    body.append("backup_file", file);
    body.append("confirmation_token", "RESTORE_LIBRARY");
    return request<{ restored: boolean; schema_version: string }>("/restore/upload", { method: "POST", body });
  },
  schemaVersion: () => request<{ schema_version: string }>("/schema-version"),
};

export const emptyDraft = (): ReactionDraft => ({
  name: "", reaction_smiles: "", editor_structure_data: "",
  components: [{ role: "REACTANT", coefficient: "1", structure: "", display_name: "" }, { role: "PRODUCT", coefficient: "1", structure: "", display_name: "" }],
  tags: [], reagents_text: "", process_text: "", notes: "", warning_reason: "",
});
