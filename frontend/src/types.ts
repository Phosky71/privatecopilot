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
}

export interface ModelsResponse {
  default: string | null;
  models: ModelInfo[];
}

export interface GitStatus {
  branch: string;
  pending_changes: string[];
  repo_path?: string;
  error?: string;
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

