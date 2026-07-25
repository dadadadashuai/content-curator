export interface Creator {
  id: number;
  platform: string;
  uid: string;
  name: string;
  avatar?: string;
  update_strategy: string;
  priority: string;
  content_types: string[];
  custom_tags: string[];
  enabled: number;
  last_checked: string;
  created_at: string;
}

export interface Content {
  id: number;
  creator_id: number;
  platform: string;
  bvid: string;
  url: string;
  title: string;
  duration: number;
  status: string;
  error_msg: string;
  retry_count: number;
  processed_at: string;
  note_path: string;
  category: string;
  sub_category: string;
  used_frames: number;
  up_name?: string;
}

export interface ProcessStats {
  total: number;
  pending: number;
  fetching: number;
  transcribing: number;
  cleaning: number;
  classifying: number;
  extracting: number;
  done: number;
  failed: number;
}

export interface Note {
  title: string;
  category: string;
  sub_category?: string;
  up: string;
  bvid: string;
  tags: string[];
  date: string;
  path: string;
}

export interface PendingClaim {
  id: number;
  content_id: number;
  claim: string;
  claim_type: string;
  status: string;
  correction: string;
  content_title?: string;
  category?: string;
  creator_name?: string;
}

export interface Settings {
  vault_path: string;
  ai_config: {
    api_base: string;
    text_model: string;
    vision_model: string;
    temperature: number;
    max_tokens: number;
  };
  whisper_config: {
    mode: string;
    model_size: string;
    language: string;
  };
  sessdata: string;
  wechat_method: string;
  schedule_config: {
    check_time: string;
    process_collections: boolean;
  };
  ad_filter_prompt: string;
  domain_taxonomy: Record<string, string[]>;
}

export interface Task {
  id?: number;
  content_id: number;
  task_type: string;
  status: string;
  started_at: string;
  finished_at: string;
  error: string;
  content_title?: string;
  creator_name?: string;
}
