export interface Creator {
  id: number;
  platform: string;
  uid: string;
  name: string;
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
  pub_date: string;
  cover: string;
  status: string;
  error_msg: string;
  category: string;
  sub_category: string;
  used_frames: number;
  note_path: string;
  ai_summary: string;
  processed_at: string;
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
  path: string;
  title: string;
  category: string;
  sub_category: string;
  up: string;
  bvid: string;
  tags: string[];
}

export interface PendingClaim {
  id: number;
  content_id: number;
  claim: string;
  claim_type: string;
  status: string;
  correction: string;
  title: string;
  category: string;
}

export interface Settings {
  [key: string]: any;
}
