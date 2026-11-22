export interface Workspace {
  id: string;
  name: string;
  folders: string[];
  files: string[];
  model?: string;
}

export interface ModelInfo {
  id: string;
  name: string;
  model: string;
  provider_id?: string;
  provider_name?: string;
  provider_type?: string;
  is_local?: boolean;
}

export interface ProviderStatus {
  id: string;
  name: string;
  type: string;
  base_url: string;
  online: boolean;
}

export interface LLMProviderConfig {
  id: string;
  name: string;
  provider_type: string;
  base_url: string;
  has_api_key: boolean;
  api_key_masked: string | null;
  models: string[];
  enabled: boolean;
}

export interface ProviderFormPayload {
  name: string;
  provider_type: 'ollama' | 'openai_compatible' | 'anthropic';
  base_url: string;
  api_key?: string;
  models: string[];
  enabled: boolean;
}

export interface ModelsResponse {
  default: string | null;
  models: ModelInfo[];
  providers_status?: ProviderStatus[];
}

export type GitInitPolicy = 'ask' | 'auto' | 'never';

export interface GitRepoStatus {
  repo_path: string;
  name: string;
  initialized: boolean;
  branch: string | null;
  pending_changes: string[];
  error?: string;
}

export interface GitStatus {
  initialized?: boolean;
  branch: string | null;
  pending_changes: string[];
  repo_path?: string;
  repositories?: GitRepoStatus[];
  error?: string;
}

export interface GitApplyResponse {
  status: string;
  branch: string;
  repo_path?: string;
}

export interface IndexProgress {
  workspace_id: string;
  status: 'idle' | 'running' | 'completed' | 'error';
  phase: 'idle' | 'scanning' | 'indexing' | 'cleaning' | 'completed' | 'error';
  total_files: number;
  processed_files: number;
  indexed_files: number;
  skipped_files: number;
  failed_files: number;
  removed_files: number;
  current_file: string | null;
  percent: number;
  error: string | null;
}

export interface FsEntry {
  name: string;
  path: string;
  is_dir: boolean;
}

export interface FsListResponse {
  path: string;
  items: FsEntry[];
}

export interface Message {
  role: string;
  content: string;
  status?: 'thinking' | 'streaming' | 'done';
}

export interface EditBlock {
  file: string;
  original: string;
  replacement: string;
}

