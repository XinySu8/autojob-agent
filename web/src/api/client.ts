import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export const api = createClient<paths>({ baseUrl: "" });

export type Job = components["schemas"]["JobSummary"];
export type JobDetail = components["schemas"]["JobDetail"];
export type Run = components["schemas"]["RunOut"];
export type Eval = components["schemas"]["EvalOut"];
export type Bucket = "apply" | "maybe" | "skip";
export type Status = "new" | "applied" | "ignored" | "closed";

/** Unwrap an openapi-fetch result, throwing the API's error detail. */
export async function call<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (error !== undefined || data === undefined) {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    throw new Error(typeof detail === "string" ? detail : `HTTP ${response.status}`);
  }
  return data;
}
