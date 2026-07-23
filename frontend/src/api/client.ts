// Thin fetch client for the MiniLP API (§5). All requests carry the annotator's
// API key; dev proxies /api → backend (see vite.config.ts).

import type {
  AnnotatorReport,
  AvailableWork,
  Batch,
  Bias,
  Distribution,
  IngestReport,
  LabelOut,
  Progress,
  Project,
  ProjectSummary,
  Roster,
  SubmitRequest,
  Task,
  Template,
  TemplateSample,
  UnitDetail,
  UnitSummary,
} from "./types";

// The subset the annotation loop needs — lets tests inject a mock (§12 testability).
export interface TaskClient {
  nextTask(annotator: number, project: number): Promise<Task | null>;
  submit(slotId: number, annotator: number, body: SubmitRequest): Promise<LabelOut>;
  skip(slotId: number, annotator: number): Promise<{ slot_id: number; status: string }>;
  // Optional so a minimal mock client stays valid; the annotation view degrades
  // to "no reputation badge" rather than failing when it is absent.
  annotatorReport?(annotator: number, project?: number): Promise<AnnotatorReport>;
}

export interface ClientConfig {
  baseUrl?: string; // default "/api" (proxied in dev)
  apiKey?: string; // Authorization: Bearer <key>
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

export class MiniLpClient {
  private baseUrl: string;
  private apiKey?: string;

  constructor(cfg: ClientConfig = {}) {
    this.baseUrl = (cfg.baseUrl ?? "/api").replace(/\/$/, "");
    this.apiKey = cfg.apiKey;
  }

  private headers(json = false): Record<string, string> {
    const h: Record<string, string> = {};
    if (this.apiKey) h["Authorization"] = `Bearer ${this.apiKey}`;
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  private async parse<T>(res: Response): Promise<T> {
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = (body && (body.detail ?? body.message)) || detail;
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(res.status, String(detail));
    }
    return (await res.json()) as T;
  }

  async getTemplate(id: number): Promise<Template> {
    const res = await fetch(`${this.baseUrl}/templates/${id}`, { headers: this.headers() });
    return this.parse<Template>(res);
  }

  async getProject(id: number): Promise<Project> {
    const res = await fetch(`${this.baseUrl}/projects/${id}`, { headers: this.headers() });
    return this.parse<Project>(res);
  }

  // GET /tasks/next → 204 (empty queue) resolves to null.
  async nextTask(annotator: number, project: number): Promise<Task | null> {
    const q = `annotator=${annotator}&project=${project}`;
    const res = await fetch(`${this.baseUrl}/tasks/next?${q}`, { headers: this.headers() });
    if (res.status === 204) return null;
    return this.parse<Task>(res);
  }

  async submit(slotId: number, annotator: number, body: SubmitRequest): Promise<LabelOut> {
    const res = await fetch(`${this.baseUrl}/tasks/${slotId}/submit?annotator=${annotator}`, {
      method: "POST",
      headers: this.headers(true),
      body: JSON.stringify(body),
    });
    return this.parse<LabelOut>(res);
  }

  // GET /tasks/available?annotator= — projects with work for the landing page.
  async availableWork(annotator: number): Promise<AvailableWork> {
    const res = await fetch(`${this.baseUrl}/tasks/available?annotator=${annotator}`, {
      headers: this.headers(),
    });
    return this.parse<AvailableWork>(res);
  }

  async annotatorReport(annotator: number, project?: number): Promise<AnnotatorReport> {
    const q = project === undefined ? "" : `?project=${project}`;
    const res = await fetch(`${this.baseUrl}/annotators/${annotator}/report${q}`, {
      headers: this.headers(),
    });
    return this.parse<AnnotatorReport>(res);
  }

  async skip(slotId: number, annotator: number): Promise<{ slot_id: number; status: string }> {
    const res = await fetch(`${this.baseUrl}/tasks/${slotId}/skip?annotator=${annotator}`, {
      method: "POST",
      headers: this.headers(),
    });
    return this.parse<{ slot_id: number; status: string }>(res);
  }

  // ---- M5 admin / analytics (§9, §11) --------------------------------------

  private async get<T>(path: string): Promise<T> {
    return this.parse<T>(await fetch(`${this.baseUrl}${path}`, { headers: this.headers() }));
  }

  private async post<T>(path: string, body?: unknown): Promise<T> {
    return this.parse<T>(
      await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: this.headers(true),
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    );
  }

  private async put<T>(path: string, body?: unknown): Promise<T> {
    return this.parse<T>(
      await fetch(`${this.baseUrl}${path}`, {
        method: "PUT",
        headers: this.headers(true),
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    );
  }

  listTemplates(): Promise<Template[]> {
    return this.get<Template[]>("/templates");
  }

  cloneTemplate(id: number, newName?: string): Promise<Template> {
    return this.post<Template>(`/templates/${id}:clone`, { new_name: newName ?? null });
  }

  previewTemplate(id: number, payload: Record<string, unknown>): Promise<unknown> {
    return this.post<unknown>(`/templates/${id}/preview`, { payload });
  }

  getTemplateSample(id: number): Promise<TemplateSample> {
    return this.get<TemplateSample>(`/templates/${id}/sample`);
  }

  saveTemplateSample(id: number, sample: Record<string, unknown>): Promise<TemplateSample> {
    return this.put<TemplateSample>(`/templates/${id}/sample`, { sample });
  }

  listProjects(): Promise<ProjectSummary[]> {
    return this.get<ProjectSummary[]>("/projects");
  }

  createProject(body: Record<string, unknown>): Promise<Project> {
    return this.post<Project>("/projects", body);
  }

  bulkUpload(
    projectId: number,
    content: string,
    format: "jsonl" | "json" | "tsv" = "jsonl",
    batchName?: string,
    sourceFilename?: string,
  ): Promise<IngestReport> {
    return this.post<IngestReport>(`/projects/${projectId}/units:bulk`, {
      jsonl: content,
      format,
      batch_name: batchName ?? null,
      source_filename: sourceFilename ?? null,
    });
  }

  getProgress(projectId: number): Promise<Progress> {
    return this.get<Progress>(`/projects/${projectId}/progress`);
  }

  getBias(projectId: number): Promise<Bias> {
    return this.get<Bias>(`/projects/${projectId}/analytics/bias`);
  }

  getDistribution(projectId: number): Promise<Distribution> {
    return this.get<Distribution>(`/projects/${projectId}/analytics/distribution`);
  }

  getRoster(projectId: number): Promise<Roster> {
    return this.get<Roster>(`/projects/${projectId}/annotators`);
  }

  listBatches(projectId: number): Promise<Batch[]> {
    return this.get<Batch[]>(`/projects/${projectId}/batches`);
  }

  listUnits(projectId: number, query: Record<string, string | number | boolean> = {}): Promise<
    UnitSummary[]
  > {
    const q = Object.entries(query)
      .filter(([, v]) => v !== "" && v !== undefined && v !== null)
      .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
      .join("&");
    return this.get<UnitSummary[]>(`/projects/${projectId}/units${q ? `?${q}` : ""}`);
  }

  getUnit(unitId: number): Promise<UnitDetail> {
    return this.get<UnitDetail>(`/units/${unitId}`);
  }

  reprioritize(
    projectId: number,
    priority: number,
    filter: { batch_id?: number; status?: string } = {},
  ): Promise<{ updated: number; priority: number }> {
    return this.post(`/projects/${projectId}/units:reprioritize`, { priority, ...filter });
  }
}
