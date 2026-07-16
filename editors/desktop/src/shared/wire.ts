import type { WireEvent } from "./protocol";

const JSONRPC_VERSION = "2.0";

export function parseWireLine(line: string): WireEvent | null {
  let message: unknown;
  try {
    message = JSON.parse(line);
  } catch {
    return null;
  }
  if (typeof message !== "object" || message === null) {
    return null;
  }
  const record = message as Record<string, unknown>;
  if (record.jsonrpc !== JSONRPC_VERSION) {
    return null;
  }
  if ("id" in record) {
    return null;
  }
  const method = record.method;
  if (typeof method !== "string" || !method) {
    return null;
  }
  const rawParams = record.params;
  if (rawParams === undefined) {
    return { method, params: {} };
  }
  if (typeof rawParams !== "object" || rawParams === null) {
    return null;
  }
  return { method, params: rawParams as Record<string, unknown> };
}
