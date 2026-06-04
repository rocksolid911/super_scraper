// Minimal API client for the super_scraper DRF backend.
// Tokens live in localStorage; all calls attach the JWT access token.

// "Pages to scrape" maps to max_pages: a number N (>=1), or "all" -> 0 (all pages).
export function parsePages(input: string): number {
  const s = (input || '').trim().toLowerCase();
  if (s === 'all' || s === '0') return 0;
  const n = parseInt(s, 10);
  return Number.isFinite(n) && n > 0 ? n : 1;
}
export function formatPages(max_pages?: number): string {
  return max_pages === 0 ? 'all' : String(max_pages ?? 1);
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000/api';

const ACCESS_KEY = 'ss_access';
const REFRESH_KEY = 'ss_refresh';
const USER_KEY = 'ss_user';

export type NotifyChannel = {
  type: 'slack' | 'discord' | 'webhook' | 'email';
  target: string;
  label?: string;
};

export type Job = {
  id: number;
  name: string;
  mode: 'visual' | 'prompt';
  status: string;
  configuration: Record<string, any>;
  total_runs: number;
  successful_runs: number;
  total_items_scraped: number;
  created_at: string;
  respect_robots_txt?: boolean;
  use_js_rendering?: boolean;
  max_pages?: number;
  is_scheduled?: boolean;
  schedule_config?: Record<string, any>;
  next_run_at?: string | null;
  notify_on_change?: boolean;
  notify_config?: { channels: NotifyChannel[] };
};

export type ScheduleConfig =
  | { type: 'interval'; interval_value: number; interval_unit: 'minutes' | 'hours' | 'days' | 'weeks' }
  | { type: 'cron'; cron_expression: string }
  | { type: 'once' };

export type Destination = {
  id: number;
  job: number;
  name: string;
  dest_type: 'postgres' | 'google_sheets' | 'webhook';
  config: Record<string, any>;
  enabled: boolean;
  last_status?: string;
  last_error?: string;
  total_rows_delivered?: number;
  last_delivery_at?: string | null;
};

export type ChangeSummary = {
  first_run?: boolean;
  changed?: boolean;
  added?: number;
  removed?: number;
  unchanged?: number;
  added_sample?: string[];
  removed_sample?: string[];
};

export type JobRun = {
  id: number;
  status: string;
  items_scraped: number;
  pages_visited: number;
  duration_seconds: number | null;
  error_message?: string;
  created_at: string;
  change_summary?: ChangeSummary;
};

export type ScrapedItem = {
  id: number;
  data: Record<string, any>;
  source_url: string;
  created_at: string;
};

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(ACCESS_KEY);
}

export function getUser(): any | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function logout() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

async function request<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401 && retry) {
    const refreshed = await tryRefresh();
    if (refreshed) return request<T>(path, options, false);
  }

  if (!res.ok) {
    let detail: any = null;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text();
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('application/json')) return (await res.blob()) as unknown as T;
  return res.json();
}

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function tryRefresh(): Promise<boolean> {
  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return false;
  try {
    const res = await fetch(`${API_BASE}/auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem(ACCESS_KEY, data.access);
    return true;
  } catch {
    return false;
  }
}

export async function login(email: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => 'Login failed'));
  const data = await res.json();
  localStorage.setItem(ACCESS_KEY, data.access);
  localStorage.setItem(REFRESH_KEY, data.refresh);
  if (data.user) localStorage.setItem(USER_KEY, JSON.stringify(data.user));
  return data;
}

export async function register(payload: {
  email: string;
  username: string;
  password: string;
  password_confirm: string;
  first_name?: string;
  last_name?: string;
}) {
  return request('/auth/register/', { method: 'POST', body: JSON.stringify(payload) });
}

// --- Jobs ---
type Paginated<T> = { results?: T[] } | T[];

function unwrap<T>(data: Paginated<T>): T[] {
  return Array.isArray(data) ? data : data.results || [];
}

export async function listJobs(): Promise<Job[]> {
  return unwrap<Job>(await request('/scraper/jobs/'));
}

export async function getJob(id: number): Promise<Job> {
  return request(`/scraper/jobs/${id}/`);
}

export async function createJob(payload: {
  name: string;
  mode: 'prompt' | 'visual';
  configuration: Record<string, any>;
  use_js_rendering?: boolean;
  respect_robots_txt?: boolean;
  max_pages?: number;
}): Promise<Job> {
  return request('/scraper/jobs/', { method: 'POST', body: JSON.stringify(payload) });
}

export async function runJob(id: number): Promise<{ run_id: number; task_id: string }> {
  return request(`/scraper/jobs/${id}/run/`, { method: 'POST' });
}

export async function updateJob(
  id: number,
  patch: Partial<{
    name: string;
    respect_robots_txt: boolean;
    use_js_rendering: boolean;
    max_pages: number;
    notify_on_change: boolean;
    notify_config: { channels: NotifyChannel[] };
  }>,
): Promise<Job> {
  return request(`/scraper/jobs/${id}/`, { method: 'PATCH', body: JSON.stringify(patch) });
}

export async function testAlert(
  id: number,
): Promise<{ success: boolean; results: { type: string; label: string; success: boolean; error?: string }[] }> {
  return request(`/scraper/jobs/${id}/test_alert/`, { method: 'POST' });
}

export async function jobRuns(id: number): Promise<JobRun[]> {
  return unwrap<JobRun>(await request(`/scraper/jobs/${id}/runs/`));
}

export async function jobItems(id: number): Promise<ScrapedItem[]> {
  return unwrap<ScrapedItem>(await request(`/scraper/jobs/${id}/items/?page_size=200`));
}

export function exportUrl(id: number): string {
  return `${API_BASE}/scraper/jobs/${id}/export/`;
}

// --- Visual selector ---
export type SnapshotElement = {
  id: number;
  selector: string;
  tag: string;
  text: string;
  href: string | null;
  src: string | null;
  box: { x: number; y: number; w: number; h: number };
};

export type SnapshotResult = {
  success: boolean;
  url: string;
  screenshot_url: string;
  width: number;
  height: number;
  elements: SnapshotElement[];
};

export type FieldDef = { name: string; selector: string; attr: string; type?: string };

export type InferResult = {
  selectors: { container: string | null; fields: Record<string, any> };
  sample: { success: boolean; items?: any[]; total_found?: number; error?: string };
};

// Media (screenshots) are served from the backend origin, not under /api.
export function mediaUrl(path: string): string {
  try {
    const u = new URL(API_BASE);
    return `${u.protocol}//${u.host}${path}`;
  } catch {
    return path;
  }
}

export async function snapshot(url: string, useJs: boolean): Promise<SnapshotResult> {
  return request('/scraper/snapshot/', {
    method: 'POST',
    body: JSON.stringify({ url, use_js_rendering: useJs }),
  });
}

export async function inferSelectors(
  url: string,
  fields: FieldDef[],
  useJs: boolean,
  container?: string | null
): Promise<InferResult> {
  return request('/scraper/infer-selectors/', {
    method: 'POST',
    body: JSON.stringify({ url, fields, container: container || null, use_js_rendering: useJs }),
  });
}

// --- Discovery (on-site map_site + list_items) ---
export type Section = { label: string; url: string };
export type DiscoverItem = { title: string; url: string };

export type SectionsResult = {
  success: boolean;
  url: string;
  sections: Section[];
  total?: number;
  error?: string;
};

export type ItemsResult = {
  success: boolean;
  url: string;
  items: DiscoverItem[];
  total?: number;
  error?: string;
};

export async function discoverSections(url: string, useJs = false): Promise<SectionsResult> {
  return request('/scraper/discover-sections/', {
    method: 'POST',
    body: JSON.stringify({ url, use_js_rendering: useJs }),
  });
}

export async function discoverItems(url: string, useJs = false): Promise<ItemsResult> {
  return request('/scraper/discover-items/', {
    method: 'POST',
    body: JSON.stringify({ url, use_js_rendering: useJs }),
  });
}

// --- Output preview (dry run, no persistence) ---
export type PreviewResult = {
  success: boolean;
  url?: string;
  columns: string[];
  rows: Record<string, any>[];
  count?: number;
  error?: string | null;
};

export async function previewScrape(payload: {
  urls: string[];
  prompt?: string;
  use_js_rendering?: boolean;
  selectors?: Record<string, any>;
}): Promise<{ task_id: string }> {
  return request('/scraper/preview/', { method: 'POST', body: JSON.stringify(payload) });
}

export async function taskStatus(
  taskId: string,
): Promise<{ status: string; ready: boolean; successful: boolean | null; result?: any; error?: string }> {
  return request(`/scraper/task-status/${taskId}/`);
}

// Dispatch a preview and poll until the task finishes (or times out).
export async function runPreview(
  payload: { urls: string[]; prompt?: string; use_js_rendering?: boolean; selectors?: Record<string, any> },
  { tries = 75, intervalMs = 2000 }: { tries?: number; intervalMs?: number } = {},
): Promise<PreviewResult> {
  const { task_id } = await previewScrape(payload);
  for (let i = 0; i < tries; i++) {
    const s = await taskStatus(task_id);
    if (s.ready) {
      if (s.successful && s.result) return s.result as PreviewResult;
      return { success: false, columns: [], rows: [], error: s.error || 'Preview failed' };
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return { success: false, columns: [], rows: [], error: 'Preview timed out' };
}

// --- Recipes (saved discovery selections) ---
export type Recipe = {
  id: number;
  name: string;
  source_url: string;
  section_label: string;
  prompt: string;
  items: DiscoverItem[];
  selectors: Record<string, any>;
  use_js_rendering: boolean;
  respect_robots_txt: boolean;
  item_urls: string[];
  created_at: string;
};

export async function listRecipes(): Promise<Recipe[]> {
  return unwrap<Recipe>(await request('/scraper/recipes/'));
}

export async function createRecipe(payload: {
  name: string;
  source_url: string;
  section_label?: string;
  prompt?: string;
  items?: DiscoverItem[];
  use_js_rendering?: boolean;
  respect_robots_txt?: boolean;
}): Promise<Recipe> {
  return request('/scraper/recipes/', { method: 'POST', body: JSON.stringify(payload) });
}

export async function deleteRecipe(id: number): Promise<void> {
  return request(`/scraper/recipes/${id}/`, { method: 'DELETE' });
}

export async function createJobFromRecipe(id: number): Promise<Job> {
  return request(`/scraper/recipes/${id}/create_job/`, { method: 'POST' });
}

// --- Scheduling ---
export async function updateSchedule(
  jobId: number,
  isScheduled: boolean,
  scheduleConfig?: ScheduleConfig
): Promise<Job> {
  return request(`/scraper/jobs/${jobId}/schedule/`, {
    method: 'PATCH',
    body: JSON.stringify({ is_scheduled: isScheduled, schedule_config: scheduleConfig || {} }),
  });
}

// --- Destinations ---
export async function listDestinations(jobId: number): Promise<Destination[]> {
  return unwrap<Destination>(await request(`/scraper/destinations/?job=${jobId}`));
}

export async function createDestination(payload: {
  job: number;
  name: string;
  dest_type: Destination['dest_type'];
  config: Record<string, any>;
  enabled?: boolean;
}): Promise<Destination> {
  return request('/scraper/destinations/', { method: 'POST', body: JSON.stringify(payload) });
}

export async function deleteDestination(id: number): Promise<void> {
  return request(`/scraper/destinations/${id}/`, { method: 'DELETE' });
}

export async function testDestination(
  id: number
): Promise<{ success: boolean; rows_delivered?: number; error?: string }> {
  return request(`/scraper/destinations/${id}/test/`, { method: 'POST' });
}
