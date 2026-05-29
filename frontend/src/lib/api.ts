// Tiny typed fetch wrapper around the FastAPI backend.

const BASE =
  (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_API_BASE) ||
  'http://localhost:8000';

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText} – ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── Types (mirror backend schemas) ──
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
  rankOnlyCsvUrl: `${BASE}/api/jobs/export/rank-only.csv`,
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
  runs: () => http<Run[]>('/api/runs'),
  triggerRun: () => http<{ status: string }>('/api/runs/trigger', { method: 'POST' }),
  settings: () => http<Record<string, any>>('/api/settings'),
  tailor: (job_id: string) =>
    http<TailorResponse>(`/api/resume/tailor`, {
      method: 'POST',
      body: JSON.stringify({ job_id }),
    }),
  forJobDocs: (job_id: string) =>
    http<TailorResponse>(`/api/resume/for-job/${job_id}`),
};
