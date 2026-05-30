// Tiny typed fetch wrapper around the FastAPI backend (with auth).

const BASE =
  (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_API_BASE) ||
  'http://localhost:8000';

const TOKEN_KEY = 'aijob_token';

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
function setToken(t: string) {
  try {
    localStorage.setItem(TOKEN_KEY, t);
  } catch {}
}
function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {}
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const isForm =
    typeof FormData !== 'undefined' && init?.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isForm ? {} : { 'Content-Type': 'application/json' }),
    ...((init?.headers as Record<string, string>) || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { cache: 'no-store', ...init, headers });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== 'undefined' && !/^\/(login|signup)/.test(location.pathname)) {
      location.href = '/login';
    }
    throw new Error('Not authenticated');
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    // FastAPI errors are {"detail": "..."} — surface that if present.
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = JSON.parse(text);
      if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
    } catch {
      if (text) msg += ` – ${text}`;
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

// ── Types ──
export type User = {
  id: string;
  email: string;
  name?: string | null;
  avatar_url?: string | null;
  is_admin: boolean;
  has_resume: boolean;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

export type MasterResume = {
  id?: string | null;
  filename?: string | null;
  parsed_json?: any;
  created_at?: string | null;
  has_resume: boolean;
};

export type Job = {
  id: string;
  source: string;
  external_id: string;
  url: string;
  title: string;
  company: string;
  location?: string | null;
  remote: boolean;
  department?: string | null;
  description: string;
  salary_text?: string | null;
  posted_at?: string | null;
  discovered_at: string;
  rank_score?: number | null;
  rank_breakdown?: Record<string, number> | null;
  rank_reasoning?: string | null;
  ats_keywords?: string[] | null;
  status: string;
  auto_apply: boolean;
  applied_manually_at?: string | null;
};

export type Application = {
  id: string;
  job_id: string;
  run_id?: string | null;
  resume_version_id?: string | null;
  cover_letter_id?: string | null;
  status: string;
  approval_required: boolean;
  manual: boolean;
  approved_at?: string | null;
  submitted_at?: string | null;
  attempts: number;
  error?: string | null;
  screenshot_path?: string | null;
  created_at: string;
  updated_at: string;
};

export type Run = {
  id: string;
  started_at: string;
  finished_at?: string | null;
  trigger: string;
  status: string;
  jobs_found: number;
  jobs_new: number;
  ranked: number;
  tailored: number;
  applied: number;
  failed_applications: number;
  summary?: string | null;
};

export type ResumeDoc = {
  id: string;
  job_id?: string | null;
  label?: string;
  pdf_path?: string;
  ats_keywords?: string[] | null;
  created_at?: string;
  download_url?: string | null;
};

export type CoverLetterDoc = {
  id: string;
  job_id?: string | null;
  created_at?: string;
  download_url?: string | null;
};

export type TailorResponse = {
  resume?: ResumeDoc | null;
  cover_letter?: CoverLetterDoc | null;
};

export type DashboardSummary = {
  total_jobs: number;
  ranked: number;
  shortlisted: number;
  tailored: number;
  applied: number;
  apply_mode: string;
  min_rank_to_apply: number;
  llm_model: string;
  total_applications: number;
  submitted: number;
  failed: number;
  awaiting_approval: number;
  interviews: number;
  rejected: number;
  last_run?: Run | null;
  top_jobs: Job[];
};

export const api = {
  base: BASE,

  // ── auth/token ──
  getToken,
  setToken,
  clearToken,
  isAuthed: () => !!getToken(),
  signup: (email: string, password: string, name?: string) =>
    http<TokenResponse>('/api/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ email, password, name }),
    }),
  login: (email: string, password: string) =>
    http<TokenResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  google: (credential: string) =>
    http<TokenResponse>('/api/auth/google', {
      method: 'POST',
      body: JSON.stringify({ credential }),
    }),
  me: () => http<User>('/api/auth/me'),

  // ── résumé ──
  uploadResume: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return http<MasterResume>('/api/resume/upload', { method: 'POST', body: fd });
  },
  myResume: () => http<MasterResume>('/api/resume/me'),

  // ── jobs ──
  dashboard: () => http<DashboardSummary>('/api/dashboard/summary'),
  jobs: (params: Record<string, string | number | boolean> = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) q.set(k, String(v));
    return http<{ items: Job[]; total: number }>(`/api/jobs?${q.toString()}`);
  },
  job: (id: string) => http<Job>(`/api/jobs/${id}`),
  markApplied: (id: string, note?: string) =>
    http<Job>(`/api/jobs/${id}/mark-applied`, {
      method: 'POST',
      body: JSON.stringify(note ? { note } : {}),
    }),

  // ── applications ──
  applications: (params: Record<string, string | number> = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) q.set(k, String(v));
    return http<{ items: Application[]; total: number }>(
      `/api/applications?${q.toString()}`,
    );
  },
  approveApplication: (id: string) =>
    http<Application>(`/api/applications/${id}/approve`, { method: 'POST' }),
  patchApplicationStatus: (id: string, status: string) =>
    http<Application>(`/api/applications/${id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),

  // ── runs / settings / tailor ──
  runs: () => http<Run[]>('/api/runs'),
  triggerRun: () => http<{ status: string }>('/api/runs/trigger', { method: 'POST' }),
  settings: () => http<Record<string, any>>('/api/settings'),
  patchSettings: (body: Record<string, any>) =>
    http<Record<string, any>>('/api/settings', {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  tailor: (job_id: string) =>
    http<TailorResponse>(`/api/resume/tailor`, {
      method: 'POST',
      body: JSON.stringify({ job_id }),
    }),
  forJobDocs: (job_id: string) =>
    http<TailorResponse>(`/api/resume/for-job/${job_id}`),
};
