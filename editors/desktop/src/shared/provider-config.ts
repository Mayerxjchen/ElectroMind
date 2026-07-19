export const DEFAULT_MODEL = "deepseek-v4-flash";

export type ProviderSetup = {
  apiKey: string;
  model: string;
  baseUrl?: string;
};

export function providerFieldFromToml(text: string, field: string): string {
  const match = text.match(new RegExp(`^\\s*${field}\\s*=\\s*(.*)$`, "m"));
  if (!match) {
    return "";
  }
  let raw = match[1].trim();
  if (raw.startsWith('"') && raw.endsWith('"')) {
    raw = raw.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  } else if (raw.startsWith("'") && raw.endsWith("'")) {
    raw = raw.slice(1, -1);
  }
  return raw.trim();
}

function tomlEscape(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

export function upsertProviderField(
  text: string,
  field: string,
  value: string,
): string {
  const keyLine = `${field} = "${tomlEscape(value)}"`;
  const pattern = new RegExp(`^\\s*${field}\\s*=\\s*.*$`, "m");
  if (pattern.test(text)) {
    return text.replace(pattern, keyLine);
  }
  const provider = text.match(/^\[provider\]\s*$/m);
  if (provider && provider.index !== undefined) {
    const insertAt = provider.index + provider[0].length;
    return text.slice(0, insertAt) + "\n" + keyLine + text.slice(insertAt);
  }
  const suffix = text.endsWith("\n") || !text ? "" : "\n";
  return text + suffix + `\n[provider]\n${keyLine}\n`;
}

export function removeProviderField(text: string, field: string): string {
  return text.replace(new RegExp(`^\\s*${field}\\s*=\\s*.*\\n?`, "m"), "");
}

export function buildProviderToml(setup: ProviderSetup): string {
  let text =
    "# pagent home 配置\n\n[provider]\n";
  text = upsertProviderField(text, "api_key", setup.apiKey.trim());
  text = upsertProviderField(text, "model", setup.model.trim() || DEFAULT_MODEL);
  const baseUrl = setup.baseUrl?.trim() ?? "";
  text = baseUrl
    ? upsertProviderField(text, "base_url", baseUrl)
    : removeProviderField(text, "base_url");
  return text;
}

export function mergeProviderToml(existing: string, setup: ProviderSetup): string {
  let text = existing.trim() ? existing : "[provider]\n";
  text = upsertProviderField(text, "api_key", setup.apiKey.trim());
  text = upsertProviderField(text, "model", setup.model.trim() || DEFAULT_MODEL);
  const baseUrl = setup.baseUrl?.trim() ?? "";
  text = baseUrl
    ? upsertProviderField(text, "base_url", baseUrl)
    : removeProviderField(text, "base_url");
  return text;
}
