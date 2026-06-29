// KB-only response types

export interface UploadResponse {
  status: "ok";
  file_name: string;
  chunks: number;
  workspace_id: string;
  graph_extracted: boolean;
}

export interface ConnectionResponse {
  id: string;
  workspace_id: string;
  connector_type: string;
  status: "active" | "syncing" | "error" | "disabled";
  last_synced_at?: string;
}
