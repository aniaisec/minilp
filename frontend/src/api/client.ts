// Thin fetch client for the MiniLP API (§5). All requests carry the annotator's
// API key; dev proxies /api → backend (see vite.config.ts).

import type {
  ActiveLearningBatch,
  AnnotatorReport,
  AnnotatorSelf,
  AvailableWork,
  Batch,
  Bias,
  CheckpointRegister,
  CheckpointRegistered,
  Costs,
  Distribution,
  EnrolledJudge,
  ExportFormat,
  IngestReport,
  IterationCurve,
  JudgeConfig,
  JudgeConfigCreate,
  JudgeRunResponse,
  JudgeRunRow,
  LabelOut,
  LocalBundleInfo,
  MarketplaceBundle,
  MarketplaceImportResult,
  Me,
  Pipeline,
  Progress,
  Project,
  ProjectPatch,
  ProjectPatchResult,
  ProjectSummary,
  ReviewItem,
  ReviewOutcome,
  ReviewQueue,
  Roster,
  SubmitRequest,
  Task,
  Template,
  TemplateDeleteResult,
  TemplateSample,
  TemplateSchema,
  TemplateUsage,
  UnitDetail,
  UnitSummary,
  Webhook,
  WebhookDelivery,
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

  private async patch<T>(path: string, body?: unknown): Promise<T> {
    return this.parse<T>(
      await fetch(`${this.baseUrl}${path}`, {
        method: "PATCH",
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

  // ---- M6 authoring (§2.5) -------------------------------------------------

  createTemplate(schema: TemplateSchema): Promise<Template> {
    return this.post<Template>("/templates", { schema });
  }

  /** Edit a custom template. The server applies the versioning rules (§2.5): a
   *  presentation-only change updates in place, a schema change bumps. */
  updateTemplate(id: number, schema: TemplateSchema): Promise<Template> {
    return this.put<Template>(`/templates/${id}`, { schema });
  }

  /** Delete a custom template version, or its whole lineage (§2.5).
   *
   * Refused (409) for builtins and for any version a project is bound to — the
   * error carries the blocking project names, which is what the gallery shows. */
  deleteTemplate(id: number, versions: "one" | "all" = "one"): Promise<TemplateDeleteResult> {
    return this.del<TemplateDeleteResult>(`/templates/${id}?versions=${versions}`);
  }

  /** Which projects are bound to this template — read *before* offering delete,
   *  so the reason a template can't go is visible rather than discovered. */
  getTemplateUsage(id: number): Promise<TemplateUsage> {
    return this.get<TemplateUsage>(`/templates/${id}/usage`);
  }

  // ---- who am I (§5) -------------------------------------------------------

  me(): Promise<Me> {
    return this.get<Me>("/me");
  }

  /** Get — or create on first use — the annotator record for this token.
   *  Idempotent: what turns "Start labeling" in the admin UI into a link. */
  myAnnotator(): Promise<AnnotatorSelf> {
    return this.post<AnnotatorSelf>("/me:annotator");
  }

  /** Edit a live project's config; a differing `template_schema` clones-and-rebinds. */
  patchProject(id: number, body: ProjectPatch): Promise<ProjectPatchResult> {
    return this.patch<ProjectPatchResult>(`/projects/${id}`, body);
  }

  /** URL for a JSONL export (§10) — used as an href so the browser downloads it. */
  exportUrl(projectId: number, format: ExportFormat): string {
    return `${this.baseUrl}/projects/${projectId}/export?format=${format}`;
  }

  /** Fetch an export's text (the admin UI previews the first rows before download). */
  async fetchExport(projectId: number, format: ExportFormat): Promise<string> {
    const res = await fetch(this.exportUrl(projectId, format), { headers: this.headers() });
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
    return res.text();
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

  // ---- M7 judges + webhooks (§5, §7.1, §7.3) -------------------------------

  private async del<T>(path: string): Promise<T> {
    return this.parse<T>(
      await fetch(`${this.baseUrl}${path}`, { method: "DELETE", headers: this.headers() }),
    );
  }

  listProviders(): Promise<{ providers: string[] }> {
    return this.get<{ providers: string[] }>("/judges/providers");
  }

  listJudges(): Promise<JudgeConfig[]> {
    return this.get<JudgeConfig[]>("/judges");
  }

  createJudge(body: JudgeConfigCreate): Promise<JudgeConfig> {
    return this.post<JudgeConfig>("/judges", body);
  }

  /** Write the next prompt version. Unset fields carry forward (§4). */
  versionJudge(id: number, changes: Partial<JudgeConfigCreate>): Promise<JudgeConfig> {
    return this.post<JudgeConfig>(`/judges/${id}:version`, changes);
  }

  listProjectJudges(projectId: number): Promise<{ project_id: number; judges: EnrolledJudge[] }> {
    return this.get(`/projects/${projectId}/judges`);
  }

  attachJudge(projectId: number, judgeId: number): Promise<{ annotator_id: number }> {
    return this.post(`/projects/${projectId}/judges/${judgeId}:attach`);
  }

  detachJudge(projectId: number, judgeId: number): Promise<{ project_id: number }> {
    return this.post(`/projects/${projectId}/judges/${judgeId}:detach`);
  }

  /** Run (or price, with `dry_run`) enrolled judges over the project's open slots. */
  runJudges(
    projectId: number,
    body: { judge_config_id?: number; limit?: number; dry_run?: boolean } = {},
  ): Promise<JudgeRunResponse> {
    return this.post<JudgeRunResponse>(`/projects/${projectId}/judges:run`, body);
  }

  listJudgeRuns(projectId: number): Promise<JudgeRunRow[]> {
    return this.get<JudgeRunRow[]>(`/projects/${projectId}/judge-runs`);
  }

  getCosts(projectId: number): Promise<Costs> {
    return this.get<Costs>(`/projects/${projectId}/analytics/costs`);
  }

  listWebhooks(projectId?: number): Promise<Webhook[]> {
    return this.get<Webhook[]>(`/webhooks${projectId === undefined ? "" : `?project=${projectId}`}`);
  }

  createWebhook(body: {
    event: string;
    target_url: string;
    secret?: string | null;
    project_id?: number | null;
  }): Promise<Webhook> {
    return this.post<Webhook>("/webhooks", body);
  }

  deleteWebhook(id: number): Promise<{ deleted: number }> {
    return this.del<{ deleted: number }>(`/webhooks/${id}`);
  }

  listDeliveries(projectId?: number): Promise<WebhookDelivery[]> {
    const q = projectId === undefined ? "" : `?project=${projectId}`;
    return this.get<WebhookDelivery[]>(`/webhooks/deliveries${q}`);
  }

  // ---- M8 review queue + routing (§5, §7.2) --------------------------------

  /** Escalated units awaiting a human decision, merged proposal included. */
  reviewQueue(projectId?: number, limit = 50): Promise<ReviewQueue> {
    const q = new URLSearchParams({ limit: String(limit) });
    if (projectId !== undefined) q.set("project", String(projectId));
    return this.get<ReviewQueue>(`/review/queue?${q.toString()}`);
  }

  /** One queue item plus its template — enough to render the answer widgets. */
  reviewItem(unitId: number): Promise<ReviewItem> {
    return this.get<ReviewItem>(`/review/${unitId}`);
  }

  /** Approve the merged proposal, or override it with the reviewer's own answer. */
  decideReview(
    unitId: number,
    body: { decision: "approve" | "override"; value?: Record<string, unknown>; comment?: string },
  ): Promise<ReviewOutcome> {
    return this.post<ReviewOutcome>(`/review/${unitId}:decide`, body);
  }

  getPipeline(projectId: number): Promise<Pipeline> {
    return this.get<Pipeline>(`/projects/${projectId}/pipeline`);
  }

  putPipeline(projectId: number, pipeline: Record<string, unknown>[] | null): Promise<Pipeline> {
    return this.put<Pipeline>(`/projects/${projectId}/pipeline`, { pipeline });
  }

  /** Re-run routing over a project's already-collected units after a policy change. */
  routeProject(
    projectId: number,
    body: { include_finalized?: boolean } = {},
  ): Promise<Record<string, number>> {
    return this.post<Record<string, number>>(`/projects/${projectId}/route`, body);
  }

  // ---- M9 active-learning loop (§8) -----------------------------------------

  /** Next most-informative units — pass `judgeConfigId` to weigh in that
   *  judge's own confidence (the "current student model" signal). */
  activeLearningBatch(
    projectId: number,
    opts: {
      limit?: number;
      judgeConfigId?: number;
      dedupeField?: string;
      dedupeThreshold?: number;
    } = {},
  ): Promise<ActiveLearningBatch> {
    const q = new URLSearchParams();
    if (opts.limit !== undefined) q.set("limit", String(opts.limit));
    if (opts.judgeConfigId !== undefined) q.set("judge_config_id", String(opts.judgeConfigId));
    if (opts.dedupeField) q.set("dedupe_field", opts.dedupeField);
    if (opts.dedupeThreshold !== undefined) {
      q.set("dedupe_threshold", String(opts.dedupeThreshold));
    }
    const qs = q.toString();
    return this.get<ActiveLearningBatch>(
      `/projects/${projectId}/active-learning/batch${qs ? `?${qs}` : ""}`,
    );
  }

  /** Version + attach a checkpoint in one call — the "re-enroll" step of the loop. */
  registerCheckpoint(
    projectId: number,
    body: CheckpointRegister,
  ): Promise<CheckpointRegistered> {
    return this.post<CheckpointRegistered>(
      `/projects/${projectId}/active-learning/checkpoints:register`,
      body,
    );
  }

  /** The eval curve across one checkpoint line's versions (§8 steps 4-5). */
  iterationCurve(projectId: number, name: string): Promise<IterationCurve> {
    const q = new URLSearchParams({ name });
    return this.get<IterationCurve>(
      `/projects/${projectId}/active-learning/iterations?${q.toString()}`,
    );
  }

  // ---- M10 marketplace (§12) ------------------------------------------------

  /** A template as a shareable bundle — import it on a fresh instance and it
   *  validates and previews identically (§12, M1 guarantee extended). */
  exportTemplateBundle(templateId: number): Promise<MarketplaceBundle> {
    return this.get<MarketplaceBundle>(`/templates/${templateId}:export`);
  }

  /** A judge config as a shareable bundle — never carries a credential. */
  exportJudgeBundle(judgeConfigId: number): Promise<MarketplaceBundle> {
    return this.get<MarketplaceBundle>(`/judges/${judgeConfigId}:export`);
  }

  /** A project's template + enrolled judges + config (not its units/labels) as
   *  a starter-kit bundle. For the project's data, see `exportUrl`/`fetchExport`. */
  exportProjectBundle(projectId: number): Promise<MarketplaceBundle> {
    return this.get<MarketplaceBundle>(`/projects/${projectId}:export-bundle`);
  }

  /** Metadata for every bundle shipped in the repo's local directory (§12: "no
   *  hosted registry in v1"). */
  listLocalBundles(): Promise<{ bundles: LocalBundleInfo[] }> {
    return this.get(`/marketplace/bundles`);
  }

  /** The full document for one shipped bundle — for inspecting before import. */
  getLocalBundle(filename: string): Promise<MarketplaceBundle> {
    return this.get<MarketplaceBundle>(`/marketplace/bundles/${encodeURIComponent(filename)}`);
  }

  /** Import one of the shipped bundles by filename — one click, no copy/paste. */
  importLocalBundle(filename: string, createProject = true): Promise<MarketplaceImportResult> {
    const q = new URLSearchParams({ create_project: String(createProject) });
    return this.post<MarketplaceImportResult>(
      `/marketplace/bundles/${encodeURIComponent(filename)}:import?${q.toString()}`,
    );
  }

  /** Import a pasted/uploaded bundle. Reuses the exact validation path
   *  `POST /templates` / `POST /judges` / `POST /projects` already run. */
  importBundle(bundle: MarketplaceBundle, createProject = true): Promise<MarketplaceImportResult> {
    return this.post<MarketplaceImportResult>(`/marketplace/import`, {
      bundle,
      create_project: createProject,
    });
  }
}
