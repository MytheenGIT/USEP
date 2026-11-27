import { describe, expect, it } from "vitest";
import { sourceLabel, timeAgo, plural } from "./format";

describe("format", () => {
  it("describes elapsed time", () => {
    const now = Date.parse("2026-11-25T10:00:00Z");
    expect(timeAgo("2026-11-25T09:59:40Z", now)).toBe("just now");
    expect(timeAgo("2026-11-25T09:30:00Z", now)).toBe("30 min ago");
    expect(timeAgo("2026-11-25T07:00:00Z", now)).toBe("3 h ago");
    expect(timeAgo("2026-11-22T10:00:00Z", now)).toBe("3 d ago");
  });
  it("names sources", () => {
    expect(sourceLabel("jira")).toBe("Jira");
    expect(sourceLabel("other")).toBe("other");
    expect(sourceLabel("gitlab")).toBe("GitLab");
  });
});

describe("plural", () => {
  it("uses the singular for one and the plural otherwise", () => {
    expect(plural(1, "relationship")).toBe("1 relationship");
    expect(plural(0, "relationship")).toBe("0 relationships");
    expect(plural(3, "policy", "policies")).toBe("3 policies");
  });
});
