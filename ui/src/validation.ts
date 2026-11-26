import { ConfigInput } from "./api/types";

export type FieldErrors = Partial<Record<keyof ConfigInput, string>>;

export const FIELDS: { key: keyof ConfigInput; label: string; required: boolean; placeholder: string }[] = [
  { key: "name", label: "Configuration name", required: true, placeholder: "Payments platform" },
  { key: "git_url", label: "Git URL", required: true, placeholder: "https://github.com/acme/checkout" },
  { key: "jira_url", label: "Jira URL", required: true, placeholder: "https://acme.atlassian.net/jira/software/projects/PAY" },
  { key: "confluence_url", label: "Confluence URL", required: true, placeholder: "https://acme.atlassian.net/wiki/spaces/PAY" },
  { key: "figma_url", label: "Figma URL", required: true, placeholder: "https://www.figma.com/file/..." },
  { key: "ad_url", label: "Active Directory URL", required: false, placeholder: "ldaps://dc01.corp.example.com or https://adfs.example.com" },
];

/** Client-side check for fast feedback only. The API repeats it; the UI is never the control. */
export function validateUrl(value: string, protocols: string[] = ["https:"]): string {
  let u: URL;
  try { u = new URL(value); } catch { return "Enter a full URL, for example https://example.com/path"; }
  if (!protocols.includes(u.protocol)) return `Only ${protocols.map((p) => p + "//").join(" or ")} URLs are accepted`;
  if (u.username || u.password) return "Remove credentials from the URL; secrets are never stored here";
  if (!u.hostname.includes(".")) return "Enter a public host name";
  return "";
}

export function validateConfig(input: ConfigInput): FieldErrors {
  const errors: FieldErrors = {};
  const name = input.name.trim();
  if (!name) errors.name = "Name is required";
  else if (name.length > 80) errors.name = "Name must be 80 characters or fewer";
  for (const f of FIELDS) {
    if (f.key === "name") continue;
    const v = input[f.key].trim();
    if (!v) { if (f.required) errors[f.key] = `${f.label} is required`; continue; }
    if (v.length > 2048) { errors[f.key] = "URL is too long"; continue; }
    const bad = validateUrl(v, f.key === "ad_url" ? ["https:", "ldaps:"] : ["https:"]);
    if (bad) errors[f.key] = bad;
  }
  return errors;
}

export const emptyConfig = (): ConfigInput => ({ name: "", git_url: "", jira_url: "", confluence_url: "", figma_url: "", ad_url: "" });
