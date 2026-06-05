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

// Guest résumé token (carried from the landing-page upload to signup).
const GUEST_KEY = 'aijob_guest_token';
function getGuestToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(GUEST_KEY);
  } catch {
    return null;
  }
}
function setGuestToken(t: string) {
  try {
    localStorage.setItem(GUEST_KEY, t);
  } catch {}
}
function clearGuestToken() {
  try {
    localStorage.removeItem(GUEST_KEY);
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
  email_verified?: boolean;
  experience_pref?: string; // 'fresher' | 'all'
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

// signup-start / resend-otp when verification is required (no token yet)
export type AuthStartResponse = {
  status: string; // 'otp_sent'
  email: string;
  verification_required: boolean;
  dev_otp?: string | null; // only present in local dev w/o an email provider
};

export type GuestJobSample = {
  title: string;
  company: string;
  location?: string | null;
  remote: boolean;
  url: string;
};

export type GuestUploadResponse = {
  token: string;
  profile: CareerProfile;
  sample_matches: GuestJobSample[];
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
  match_label?: string | null;
  match_signals?: MatchSignals | null;
  apply_type?: string;
  source_confidence?: string; // high | medium | low | unknown
  open_status?: string;       // open | closed | unknown
  company_tier?: number | null;
  watchlisted?: boolean;
  saved?: boolean;
  hidden?: boolean;
  status: string;
  auto_apply: boolean;
  applied_manually_at?: string | null;
};

export type MatchSignals = {
  role?: number;
  experience?: number;
  skills?: number;
  company?: number;
  recency?: number;
  salary_location?: number;
  matched_skills?: string[];
  missing_skills?: string[];
  company_tier?: number;
  watchlisted?: boolean;
  reasons?: string[];
};

export type UserPreferences = {
  target_roles: string[];
  experience_level?: string | null;
  min_salary_lpa?: number | null;
  preferred_cities: string[];
  work_modes: string[];
  job_types: string[];
  prioritized_industries: string[];
  blocked_industries: string[];
  preferred_countries: string[];
  needs_sponsorship: boolean;
  excluded_keywords: string[];
  must_have_skills: string[];
  nice_to_have_skills: string[];
  alert_instant: boolean;
  alert_daily_digest: boolean;
};

export type CareerProfile = {
  name: string;
  experience_years: number;
  seniority: string;
  role_direction: string;
  current_role: string;
  current_company: string;
  target_titles: string[];
  target_job_types: string[];
  domains: string[];
  primary_skills: string[];
  summary: string;
};

export type WatchlistItem = { id: string; company: string; priority: string };

export type SourceHealth = {
  source: string;
  last_run_at?: string | null;
  last_success_at?: string | null;
  jobs_found: number;
  jobs_added: number;
  total_runs: number;
  failures: number;
  last_error?: string | null;
};

export type AdminSource = {
  name: string;
  enabled: boolean;
  stub: boolean;
  kind: string;
  confidence: string;
  configured: boolean;
  missing_credentials: string[];
  last_run_at?: string | null;
  last_success_at?: string | null;
  jobs_found: number;
  jobs_added: number;
  failures: number;
  last_error?: string | null;
};

export type SystemHealth = {
  app_env: string;
  email_provider: string;
  email_enabled: boolean;
  verification_required: boolean;
  verification_active: boolean;
  email_misconfigured: boolean;
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

export type RerankResponse = { status: string; cleared: number };

export type AdminResume = {
  id: string;
  filename?: string | null;
  is_active: boolean;
  experience_years?: number | null;
  seniority?: string | null;
  role_direction?: string | null;
  n_skills: number;
  text_chars: number;
  on_disk: boolean;
  created_at: string;
};

export type AdminUser = {
  id: string;
  email: string;
  name?: string | null;
  is_admin: boolean;
  is_active: boolean;
  experience_pref: string;
  login_method: string;
  created_at: string;
  n_resumes: number;
  n_ranked: number;
  n_shortlisted: number;
  n_applied: number;
  resumes: AdminResume[];
};

export type AdminStats = {
  total_users: number;
  active_users: number;
  users_with_resume: number;
  total_jobs: number;
  total_rankings: number;
  total_applications: number;
  last_run?: Run | null;
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
  getGuestToken,
  setGuestToken,
  clearGuestToken,
  isAuthed: () => !!getToken(),
  signup: (email: string, password: string, name?: string) =>
    http<TokenResponse>('/api/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ email, password, name }),
    }),
  // New onboarding: create account + send OTP (or log in directly if verification
  // isn't enforced). Returns TokenResponse OR AuthStartResponse — caller checks
  // for `access_token`.
  signupStart: (email: string, password: string, name?: string, guest_token?: string) =>
    http<TokenResponse | AuthStartResponse>('/api/auth/signup-start', {
      method: 'POST',
      body: JSON.stringify({ email, password, name, guest_token }),
    }),
  verifyEmail: (email: string, code: string) =>
    http<TokenResponse>('/api/auth/verify-email', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    }),
  resendOtp: (email: string) =>
    http<AuthStartResponse>('/api/auth/resend-otp', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  forgotPassword: (email: string) =>
    http<AuthStartResponse>('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  resetPassword: (email: string, code: string, new_password: string) =>
    http<TokenResponse>('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ email, code, new_password }),
    }),
  login: (email: string, password: string) =>
    http<TokenResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  // ── guest (no account) résumé upload ──
  guestUpload: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return http<GuestUploadResponse>('/api/guest/upload', { method: 'POST', body: fd });
  },
  guestGet: (token: string) => http<GuestUploadResponse>(`/api/guest/${token}`),
  google: (credential: string) =>
    http<TokenResponse>('/api/auth/google', {
      method: 'POST',
      body: JSON.stringify({ credential }),
    }),
  me: () => http<User>('/api/auth/me'),
  setExperiencePref: (pref: 'fresher' | 'all') =>
    http<User>('/api/auth/me', {
      method: 'PATCH',
      body: JSON.stringify({ experience_pref: pref }),
    }),
  deleteAccount: () => http<void>('/api/auth/me', { method: 'DELETE' }),

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
  rerank: (scope: 'ranked' | 'all' = 'ranked') =>
    http<RerankResponse>(`/api/jobs/rerank?scope=${scope}`, { method: 'POST' }),
  resetRankings: (scope: 'ranked' | 'all' = 'ranked') =>
    http<RerankResponse>(`/api/jobs/reset-rankings?scope=${scope}`, { method: 'POST' }),
  jobFeedback: (
    id: string,
    action: 'save' | 'unsave' | 'not_relevant' | 'more_like_this' | 'hide_company',
  ) =>
    http<Job>(`/api/jobs/${id}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    }),

  // ── preferences + career profile ──
  preferences: () => http<UserPreferences>('/api/preferences'),
  updatePreferences: (body: Partial<UserPreferences>) =>
    http<UserPreferences>('/api/preferences', { method: 'PUT', body: JSON.stringify(body) }),
  careerProfile: () => http<CareerProfile>('/api/preferences/profile'),
  updateCareerProfile: (body: Partial<CareerProfile>) =>
    http<CareerProfile>('/api/preferences/profile', { method: 'PUT', body: JSON.stringify(body) }),

  // ── watchlist ──
  watchlist: () => http<WatchlistItem[]>('/api/watchlist'),
  addWatchlist: (company: string, priority = 'prioritize') =>
    http<WatchlistItem>('/api/watchlist', {
      method: 'POST',
      body: JSON.stringify({ company, priority }),
    }),
  patchWatchlist: (id: string, priority: string) =>
    http<WatchlistItem>(`/api/watchlist/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ priority }),
    }),
  removeWatchlist: (id: string) =>
    http<void>(`/api/watchlist/${id}`, { method: 'DELETE' }),

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

  // ── admin (read-only) ──
  adminStats: () => http<AdminStats>('/api/admin/stats'),
  adminUsers: () => http<AdminUser[]>('/api/admin/users'),
  adminRuns: () => http<Run[]>('/api/admin/runs'),
  adminSourceHealth: () => http<SourceHealth[]>('/api/admin/source-health'),
  adminSources: () => http<AdminSource[]>('/api/admin/sources'),
  adminSystemHealth: () => http<SystemHealth>('/api/admin/system-health'),
  adminEmailTest: (to?: string) =>
    http<{
      provider: string;
      enabled: boolean;
      from: string;
      to: string;
      ok?: boolean;
      error?: string | null;
      verification_active?: boolean;
    }>(`/api/admin/email-test${to ? `?to=${encodeURIComponent(to)}` : ''}`),
};
