// Thin fetch client for the MiniLP API (§5). All requests carry the annotator's
// API key; dev proxies /api → backend (see vite.config.ts).

import type {
  AnnotatorReport,
  LabelOut,
  Project,
  SubmitRequest,
  Task,
  Template,
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
}
