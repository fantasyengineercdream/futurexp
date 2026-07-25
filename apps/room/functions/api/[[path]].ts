import { handlePagesRequest, type PagesEnv } from "../../pages/realtime-handler";

interface PagesContext {
  request: Request;
  env: PagesEnv;
  waitUntil(promise: Promise<unknown>): void;
}

export function onRequest(context: PagesContext): Promise<Response> {
  return handlePagesRequest(context.request, context.env, context);
}
